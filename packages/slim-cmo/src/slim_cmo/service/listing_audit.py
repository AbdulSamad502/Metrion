"""Persistence for the M6 listing audit (docs/specs/slim-cmo-agent.md section 6.18.5). Zero units, no model, no network. One immutable row per (pack, content hash): saving the same version again
returns the existing row (idempotent); a different version of the text is a new row, so every revision keeps its own audit. A pack id that is not the caller's tenant's looks exactly like a missing one.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.errors import NotFound
from slim_cmo.service.models import Actor

_COLS = "id, generation_id, marketplace, content_hash, rules_basis, verdict, method_version, checks, findings, keyword_map, measured, created_at"
_INSERT = text(
    f"""
    INSERT INTO cmo_listing_audit (tenant_id, generation_id, marketplace, content_hash, rules_basis, verdict, method_version, checks, findings, keyword_map, measured, created_by, agent_run_id)
    VALUES (:t, :g, :mp, :h, :rb, :v, :m, CAST(:checks AS jsonb), CAST(:findings AS jsonb), CAST(:kmap AS jsonb), CAST(:measured AS jsonb), :u, :run)
    ON CONFLICT (tenant_id, generation_id, content_hash) DO NOTHING
    RETURNING {_COLS}
    """
)
_FIND = text(f"SELECT {_COLS} FROM cmo_listing_audit WHERE tenant_id = :t AND generation_id = :g AND content_hash = :h")
_LATEST = text(f"SELECT {_COLS} FROM cmo_listing_audit WHERE tenant_id = :t AND generation_id = :g ORDER BY created_at DESC, id LIMIT 1")


def _json(v: Any) -> Any:
    return v if not isinstance(v, str) else json.loads(v)


def _row(r: Any) -> dict[str, Any]:
    return {
        "auditId": str(r.id), "generationId": str(r.generation_id), "marketplace": r.marketplace, "contentHash": r.content_hash, "rulesBasis": r.rules_basis, "verdict": r.verdict,
        "method": r.method_version, "checks": _json(r.checks), "findings": _json(r.findings), "keywordMap": _json(r.keyword_map), "measured": _json(r.measured),
        "createdAt": r.created_at.isoformat(),
    }


class ListingAuditStore:
    def save(self, actor: Actor, *, generation_id: UUID, marketplace: str, content_hash: str, rules_basis: str, result: dict[str, Any], keyword_map: dict[str, Any],
             agent_run_id: UUID | None = None) -> dict[str, Any]:
        params = {
            "t": actor.tenant_id, "g": generation_id, "mp": marketplace, "h": content_hash, "rb": rules_basis, "v": result["verdict"], "m": result["method"],
            "checks": json.dumps(result["checks"]), "findings": json.dumps(result["findings"]), "kmap": json.dumps(keyword_map), "measured": json.dumps(result["measured"]),
            "u": actor.user_id, "run": agent_run_id,
        }
        try:
            with tenant_scope(actor.tenant_id) as conn:
                row = conn.execute(_INSERT, params).first()
                if row is not None:
                    return {**_row(row), "reused": False}
                found = conn.execute(_FIND, {"t": actor.tenant_id, "g": generation_id, "h": content_hash}).first()
        except IntegrityError as exc:  # the composite foreign key: a pack that is not this tenant's
            raise NotFound("listing not found") from exc
        assert found is not None
        return {**_row(found), "reused": True}

    def latest(self, tenant_id: UUID, generation_id: UUID) -> dict[str, Any] | None:
        with tenant_scope(tenant_id) as conn:
            r = conn.execute(_LATEST, {"t": tenant_id, "g": generation_id}).first()
        return None if r is None else _row(r)
