"""Row-seeding helpers for the integration tests.

Tenant-owned rows are inserted through `tenant_scope()` as `metrion_app` — the role the
application runs as — so every seed also proves the grants and RLS WITH CHECK allow a
legitimate write. Platform rows (`format_constraint`, `vision_eval_run`) are inserted as the
owner role, exactly as a real operator would; they are always marked as test data
(`row_kind = 'TEST_FIXTURE'`, `run_by = 'pytest'`) so cleanup can never touch real rows.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Engine, text

from slim_cmo.repositories.tenant_context import tenant_scope

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def insert_format_constraint(
    migrate_engine: Engine,
    *,
    marketplace: str = "AMAZON",
    category: str | None = None,
    version: int = 1,
    row_kind: str = "TEST_FIXTURE",
    **overrides: Any,
) -> uuid.UUID:
    row_id = new_id()
    values: dict[str, Any] = {
        "id": str(row_id),
        "marketplace": marketplace,
        "category": category,
        "title_max_chars": 120,
        "title_option_count": 5,
        "bullet_count": 5,
        "bullet_max_chars": None,
        "description_type": "plain",
        "description_max_chars": None,
        "keywords_max_count": None,
        "keywords_max_chars": None,
        "backend_terms_max_bytes": None,
        "hashtags_supported": None,
        "count_rule": "UTF16_CODE_UNITS",
        "source_url": "https://example.invalid/test-fixture",
        "verified_at": NOW,
        "version": version,
        "row_kind": row_kind,
    }
    values.update(overrides)
    cols = ", ".join(values)
    binds = ", ".join(f":{k}" for k in values)
    with migrate_engine.begin() as conn:
        conn.execute(text(f"INSERT INTO format_constraint ({cols}) VALUES ({binds})"), values)
    return row_id


def insert_vision_eval_run(
    migrate_engine: Engine,
    *,
    provider: str = "test-provider",
    model: str = "test-model",
    schema_version: str = "v1",
    passed: bool = True,
) -> uuid.UUID:
    row_id = new_id()
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO vision_eval_run
                  (id, provider, model, schema_version, dataset_ref, metrics, bar_ref, passed, run_by)
                VALUES
                  (:id, :provider, :model, :schema_version, 'test-dataset', CAST(:metrics AS jsonb),
                   'test-bar', :passed, 'pytest')
                """
            ),
            {
                "id": str(row_id),
                "provider": provider,
                "model": model,
                "schema_version": schema_version,
                "metrics": json.dumps({"note": "test"}),
                "passed": passed,
            },
        )
    return row_id


def insert_asset(tenant_id: uuid.UUID, *, sha256: str | None = None) -> uuid.UUID:
    row_id = new_id()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO seller_image_asset
                  (id, tenant_id, storage_uri, sha256, content_type, byte_size, uploaded_by, status)
                VALUES
                  (:id, :tenant_id, :uri, :sha, 'image/jpeg', 1024, :uploader, 'ACTIVE')
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "uri": f"file:///test/{row_id}",
                "sha": sha256 or uuid.uuid4().hex + uuid.uuid4().hex,
                "uploader": str(new_id()),
            },
        )
    return row_id


def insert_analysis(
    tenant_id: uuid.UUID,
    asset_id: uuid.UUID,
    *,
    attributes: list[dict[str, Any]] | None = None,
    eval_gate_ref: uuid.UUID | None = None,
    provider: str = "test-provider",
    model: str = "test-model",
    schema_version: str = "v1",
    analysis_state: str = "COMPLETE",
    degraded_reason: str | None = None,
) -> uuid.UUID:
    row_id = new_id()
    attrs = attributes if attributes is not None else [
        {"name": "color", "value": "blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}
    ]
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO product_image_analysis
                  (id, tenant_id, image_asset_id, schema_version, provider, model, eval_gate_ref,
                   attributes, analysis_state, degraded_reason)
                VALUES
                  (:id, :tenant_id, :asset, :schema_version, :provider, :model, :gate,
                   CAST(:attrs AS jsonb), :state, :reason)
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "asset": str(asset_id),
                "schema_version": schema_version,
                "provider": provider,
                "model": model,
                "gate": str(eval_gate_ref) if eval_gate_ref else None,
                "attrs": json.dumps(attrs),
                "state": analysis_state,
                "reason": degraded_reason,
            },
        )
    return row_id


def insert_generation(
    tenant_id: uuid.UUID,
    *,
    output_type: str = "TITLE_SET",
    marketplace: str | None = "AMAZON",
    status: str = "COMPLETE",
    request_key: str | None = None,
    format_constraint_ref: uuid.UUID | None = None,
    input_mode: str = "INDEPENDENT",
    ci_inputs_snapshot: dict[str, Any] | None = None,
    grounding_basis: str | None = None,
    grounding_approval_id: uuid.UUID | None = None,
    image_analysis_id: uuid.UUID | None = None,
    failure_reason: str | None = None,
    output_text: str | None = None,
    output_structured: dict[str, Any] | None = None,
    billable_units: int = 1,
    allow_empty_output: bool = False,
) -> uuid.UUID:
    row_id = new_id()
    if status == "COMPLETE" and output_text is None and output_structured is None and not allow_empty_output:
        output_structured = {"delivered": True}
    if status == "FAILED" and failure_reason is None:
        failure_reason = "test failure"  # pass failure_reason="" to exercise the DB check
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO cmo_generation
                  (id, tenant_id, marketplace, output_type, input_mode, ci_inputs_snapshot,
                   image_analysis_id, grounding_approval_id, grounding_basis, output_text,
                   output_structured, format_constraint_ref, status, failure_reason, request_key,
                   billable_units, generated_by)
                VALUES
                  (:id, :tenant_id, :marketplace, :output_type, :input_mode, CAST(:ci AS jsonb),
                   :analysis, :approval, :grounding_basis, :output_text,
                   CAST(:structured AS jsonb), :constraint_ref, :status, :failure_reason, :request_key,
                   :billable_units, :generated_by)
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "marketplace": marketplace,
                "output_type": output_type,
                "input_mode": input_mode,
                "ci": json.dumps(ci_inputs_snapshot) if ci_inputs_snapshot is not None else None,
                "analysis": str(image_analysis_id) if image_analysis_id else None,
                "approval": str(grounding_approval_id) if grounding_approval_id else None,
                "grounding_basis": grounding_basis,
                "output_text": output_text,
                "structured": json.dumps(output_structured) if output_structured is not None else None,
                "constraint_ref": str(format_constraint_ref) if format_constraint_ref else None,
                "status": status,
                "failure_reason": failure_reason,
                "request_key": request_key or f"req-{row_id}",
                "billable_units": billable_units,
                "generated_by": str(new_id()),
            },
        )
    return row_id


def insert_option(tenant_id: uuid.UUID, generation_id: uuid.UUID, *, rank: int = 1, text_value: str = "A title") -> uuid.UUID:
    row_id = new_id()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO cmo_title_option
                  (id, tenant_id, generation_id, rank, title_text, char_count, constraint_check)
                VALUES
                  (:id, :tenant_id, :gen, :rank, :title, :n, CAST(:cc AS jsonb))
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "gen": str(generation_id),
                "rank": rank,
                "title": text_value,
                "n": len(text_value),
                "cc": json.dumps({"max_chars": 120, "passed": True}),
            },
        )
    return row_id


def insert_approval(
    tenant_id: uuid.UUID,
    generation_id: uuid.UUID,
    *,
    option_id: uuid.UUID | None,
    edited_by_seller: bool | None = None,
    approved_text: str = "A title",
) -> uuid.UUID:
    row_id = new_id()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO cmo_title_approval
                  (id, tenant_id, generation_id, option_id, approved_text, edited_by_seller, approved_by)
                VALUES
                  (:id, :tenant_id, :gen, :opt, :txt, :edited, :by)
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "gen": str(generation_id),
                "opt": str(option_id) if option_id else None,
                "txt": approved_text,
                "edited": (option_id is None) if edited_by_seller is None else edited_by_seller,
                "by": str(new_id()),
            },
        )
    return row_id


def insert_fact(
    tenant_id: uuid.UUID,
    *,
    fact_type: str = "ATTRIBUTE",
    fact_value: str | None = "stainless steel",
    value_paise: int | None = None,
    cmo_generation_id: uuid.UUID | None = None,
    image_analysis_id: uuid.UUID | None = None,
) -> uuid.UUID:
    row_id = new_id()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO seller_fact
                  (id, tenant_id, cmo_generation_id, image_analysis_id, fact_type, fact_value, value_paise, provided_by)
                VALUES
                  (:id, :tenant_id, :gen, :analysis, :fact_type, :fact_value, :value_paise, :by)
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "gen": str(cmo_generation_id) if cmo_generation_id else None,
                "analysis": str(image_analysis_id) if image_analysis_id else None,
                "fact_type": fact_type,
                "fact_value": fact_value,
                "value_paise": value_paise,
                "by": str(new_id()),
            },
        )
    return row_id


def insert_niche_term(
    tenant_id: uuid.UUID,
    *,
    term: str | None = None,
    status: str = "SUGGESTED",
    origin: str = "SELLER_STATED",
    confirmed: bool | None = None,
) -> uuid.UUID:
    row_id = new_id()
    is_confirmed = (status == "CONFIRMED") if confirmed is None else confirmed
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO cmo_niche_term
                  (id, tenant_id, term, origin, status, confirmed_by, confirmed_at)
                VALUES
                  (:id, :tenant_id, :term, :origin, :status, :by, :at)
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "term": term if term is not None else f"term-{row_id}",
                "origin": origin,
                "status": status,
                "by": str(new_id()) if is_confirmed else None,
                "at": NOW if is_confirmed else None,
            },
        )
    return row_id


def insert_trend_report(
    tenant_id: uuid.UUID,
    generation_id: uuid.UUID,
    *,
    sections_requested: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
    outbound_queries: list[Any] | None = None,
) -> uuid.UUID:
    row_id = new_id()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO cmo_trend_report
                  (id, tenant_id, generation_id, sections_requested, sections, evidence,
                   outbound_queries, config_snapshot, market_signal_run_ref)
                VALUES
                  (:id, :tenant_id, :gen, CAST(:requested AS text[]), '{}'::jsonb, CAST(:evidence AS jsonb),
                   CAST(:queries AS jsonb), '{}'::jsonb, :run)
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "gen": str(generation_id),
                "requested": "{" + ",".join(sections_requested if sections_requested is not None else ["NICHE"]) + "}",
                "evidence": json.dumps(evidence if evidence is not None else {"limitations": ["no sales data"]}),
                "queries": json.dumps(outbound_queries if outbound_queries is not None else []),
                "run": str(new_id()),
            },
        )
    return row_id
