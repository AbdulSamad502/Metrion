"""`cmo_generation` + `cmo_title_option` (spec §5, §8). Append-only for the application role.

Every query filters on `tenant_id` explicitly in addition to RLS (defence in depth, auth.md §7.3).
`insert_generation` writes the generation row and its title options in the caller's single
transaction, so a title set is never visible without its options. The idempotency index
(`cmo_generation_idempotency_idx`, COMPLETE rows only) turns a duplicate delivery into
`DuplicateArtefact`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from slim_cmo.billing import ExistingArtefact
from slim_cmo.service.models import (
    DuplicateArtefact,
    GenerationRecord,
    StoredGeneration,
    StoredOption,
    StoredOptionDetail,
    StoredTitleSet,
)
from slim_cmo.types import GenerationStatus, Marketplace, OutputType

IDEMPOTENCY_INDEX = "cmo_generation_idempotency_idx"

_FIND = text(
    "SELECT id, output_type, marketplace, request_key, status FROM cmo_generation "
    "WHERE tenant_id = :tenant_id AND request_key = :request_key"
)
_INSERT = text(
    """
    INSERT INTO cmo_generation
      (tenant_id, sku, marketplace, output_type, input_mode, ci_inputs_snapshot, image_analysis_id,
       grounding_approval_id, grounding_basis, output_text, output_structured, format_constraint_ref,
       status, failure_reason, request_key, agent_run_id, generated_by)
    VALUES
      (:tenant_id, :sku, :marketplace, :output_type, :input_mode, CAST(:ci_inputs_snapshot AS jsonb), :image_analysis_id,
       :grounding_approval_id, :grounding_basis, :output_text, CAST(:output_structured AS jsonb),
       :format_constraint_ref, :status, :failure_reason, :request_key, :agent_run_id, :generated_by)
    RETURNING id
    """
)
_INSERT_OPTION = text(
    """
    INSERT INTO cmo_title_option (tenant_id, generation_id, rank, title_text, char_count, constraint_check)
    VALUES (:tenant_id, :generation_id, :rank, :title_text, :char_count, CAST(:constraint_check AS jsonb))
    """
)
_TITLE_SET = text(
    "SELECT id, marketplace, sku, output_structured #>> '{category_context,category_hint}' AS category_hint, output_structured ->> 'workflow' AS workflow "
    "FROM cmo_generation "
    "WHERE tenant_id = :tenant_id AND id = :id AND output_type = 'TITLE_SET' AND status = 'COMPLETE'"
)
_OPTIONS = text(
    "SELECT id, rank, title_text FROM cmo_title_option "
    "WHERE tenant_id = :tenant_id AND generation_id = :generation_id ORDER BY rank"
)
_LOAD = text(
    "SELECT id, output_type, marketplace, status, failure_reason, output_text, output_structured, agent_run_id, created_at "
    "FROM cmo_generation WHERE tenant_id = :tenant_id AND id = :id"
)
_OPTIONS_DETAIL = text(
    "SELECT id, rank, title_text, char_count FROM cmo_title_option "
    "WHERE tenant_id = :tenant_id AND generation_id = :generation_id ORDER BY rank"
)
_SIBLINGS = text(
    "SELECT marketplace, output_structured FROM cmo_generation "
    "WHERE tenant_id = :tenant_id AND request_key = :request_key AND output_type = 'LISTING_COPY' "
    "AND status = 'COMPLETE' AND marketplace <> :marketplace"
)


def find_artefacts(conn: Connection, tenant_id: UUID, request_key: str) -> list[ExistingArtefact]:
    return [
        ExistingArtefact(
            r.id, OutputType(r.output_type), Marketplace(r.marketplace) if r.marketplace else None,
            r.request_key, GenerationStatus(r.status),
        )
        for r in conn.execute(_FIND, {"tenant_id": tenant_id, "request_key": request_key})
    ]


def is_idempotency_violation(exc: IntegrityError) -> bool:
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return bool(name == IDEMPOTENCY_INDEX or IDEMPOTENCY_INDEX in str(exc.orig))


def insert_generation(conn: Connection, tenant_id: UUID, rec: GenerationRecord) -> UUID:
    try:
        row = conn.execute(
            _INSERT,
            {
                "tenant_id": tenant_id, "sku": rec.sku, "marketplace": rec.marketplace.value if rec.marketplace else None,
                "output_type": rec.output_type.value, "image_analysis_id": rec.image_analysis_id,
                "grounding_approval_id": rec.grounding_approval_id,
                "grounding_basis": rec.grounding_basis.value if rec.grounding_basis else None,
                "output_text": rec.output_text,
                "output_structured": json.dumps(rec.output_structured) if rec.output_structured is not None else None,
                "format_constraint_ref": rec.format_constraint_ref, "status": rec.status.value,
                "failure_reason": rec.failure_reason, "request_key": rec.request_key,
                "agent_run_id": rec.agent_run_id, "generated_by": rec.generated_by,
                "input_mode": rec.input_mode, "ci_inputs_snapshot": json.dumps(rec.ci_inputs_snapshot) if rec.ci_inputs_snapshot is not None else None,
            },
        ).one()
    except IntegrityError as exc:
        if is_idempotency_violation(exc):
            raise DuplicateArtefact() from exc
        raise
    generation_id: UUID = row.id
    for option in rec.options:
        conn.execute(
            _INSERT_OPTION,
            {
                "tenant_id": tenant_id, "generation_id": generation_id, "rank": option.rank,
                "title_text": option.text, "char_count": option.char_count,
                "constraint_check": json.dumps(option.constraint_check),
            },
        )
    return generation_id


def load_title_set(conn: Connection, tenant_id: UUID, generation_id: UUID) -> StoredTitleSet | None:
    head = conn.execute(_TITLE_SET, {"tenant_id": tenant_id, "id": generation_id}).first()
    if head is None:
        return None
    options = tuple(
        StoredOption(r.id, r.rank, r.title_text)
        for r in conn.execute(_OPTIONS, {"tenant_id": tenant_id, "generation_id": generation_id})
    )
    return StoredTitleSet(head.id, Marketplace(head.marketplace), head.sku, options, head.category_hint, head.workflow)


def load_sibling_packs(
    conn: Connection, tenant_id: UUID, request_key: str, exclude: Marketplace
) -> dict[Marketplace, Mapping[str, Any]]:
    rows = conn.execute(_SIBLINGS, {"tenant_id": tenant_id, "request_key": request_key, "marketplace": exclude.value})
    return {Marketplace(r.marketplace): r.output_structured for r in rows if isinstance(r.output_structured, dict)}


def load_generation(conn: Connection, tenant_id: UUID, generation_id: UUID) -> StoredGeneration | None:
    r = conn.execute(_LOAD, {"tenant_id": tenant_id, "id": generation_id}).first()
    if r is None:
        return None
    options: tuple[StoredOptionDetail, ...] = ()
    if r.output_type == OutputType.TITLE_SET.value:
        options = tuple(
            StoredOptionDetail(o.id, o.rank, o.title_text, o.char_count)
            for o in conn.execute(_OPTIONS_DETAIL, {"tenant_id": tenant_id, "generation_id": generation_id})
        )
    return StoredGeneration(
        r.id, OutputType(r.output_type), Marketplace(r.marketplace) if r.marketplace else None,
        GenerationStatus(r.status), r.failure_reason, r.output_text,
        r.output_structured if isinstance(r.output_structured, dict) else None,
        r.agent_run_id, r.created_at, options,
    )


def list_recent_for_tenant(tenant_id: UUID, *, limit: int) -> list[dict[str, Any]]:
    """The tenant's most recent generations, newest first: which output, for which SKU and marketplace, and how it ended. Deliberately NOT the generated
    copy (`output_text` / `output_structured`): a read for the CEO's Business State (spec 6.13), which never relays specialist free text (R9)."""
    from slim_cmo.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT id, sku, marketplace, output_type, status, created_at FROM cmo_generation "
                "WHERE tenant_id = :tenant_id ORDER BY created_at DESC, id LIMIT :limit"
            ),
            {"tenant_id": str(tenant_id), "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def list_recent_content_for_tenant(tenant_id: UUID, *, limit: int) -> list[dict[str, Any]]:
    """The tenant's most recent COMPLETE generations WITH the text the seller was given (`output_text`, or the ranked title options of a title set), newest
    first. A read for the CEO's `BS_CMO_CONTENT_LATEST` (agent-needs-and-shared-knowledge.md 7.3): the CEO shows it quoted and labelled as written by Slim CMO,
    never as a figure. Rows with no stored text (structured-only packs, failed attempts) are not returned. Tenant-scoped; read-only."""
    from slim_cmo.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT id, sku, marketplace, output_type, created_at, output_text FROM cmo_generation "
                "WHERE tenant_id = :tenant_id AND status = 'COMPLETE' "
                "AND (output_type = 'TITLE_SET' OR (output_text IS NOT NULL AND output_text <> '')) "
                "ORDER BY created_at DESC, id LIMIT :limit"
            ),
            {"tenant_id": str(tenant_id), "limit": limit},
        ).mappings().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            if item["output_type"] == OutputType.TITLE_SET.value:
                opts = conn.execute(
                    text("SELECT title_text FROM cmo_title_option WHERE tenant_id = :tenant_id AND generation_id = :gid ORDER BY rank"),
                    {"tenant_id": str(tenant_id), "gid": str(item["id"])},
                ).all()
                item["items"] = [str(o.title_text) for o in opts]
            else:
                item["items"] = [str(item["output_text"])]
            if item["items"]:
                out.append(item)
    return out
