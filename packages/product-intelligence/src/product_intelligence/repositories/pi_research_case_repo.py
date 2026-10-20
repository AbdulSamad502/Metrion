"""pi_research_case — docs/specs/ceo-pi-research-flow.md §5.1. One row per research case: the top-5 order, the deterministic pre-rank explanation, the
recommendation snapshot, the CFO result references the CEO attached (PI never fetches or computes those) and the named gaps. Every function takes `tenant_id`
first and reaches the database only through `tenant_scope()` (auth.md §7.3)."""

from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope


def upsert_case(
    tenant_id: UUID, run_id: UUID, *, investigation_id: UUID | None, top5_candidate_ids: Sequence[UUID], prerank_explanation: Any,
) -> None:
    """Creates the case, or refreshes its top-5 and pre-rank (deterministic, so a repeat gives the same result). Never touches an existing recommendation,
    CFO refs or gaps."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                "INSERT INTO pi_research_case (run_id, tenant_id, investigation_id, top5_candidate_ids, prerank_explanation) "
                "VALUES (:run_id, :tenant_id, :investigation_id, CAST(:ids AS uuid[]), CAST(:pre AS jsonb)) "
                "ON CONFLICT (run_id) DO UPDATE SET top5_candidate_ids = EXCLUDED.top5_candidate_ids, "
                "prerank_explanation = EXCLUDED.prerank_explanation, "
                "investigation_id = COALESCE(pi_research_case.investigation_id, EXCLUDED.investigation_id)"
            ),
            {
                "run_id": str(run_id), "tenant_id": str(tenant_id), "investigation_id": str(investigation_id) if investigation_id else None,
                "ids": [str(i) for i in top5_candidate_ids], "pre": json.dumps(prerank_explanation, default=str),
            },
        )


def get_case(tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM pi_research_case WHERE tenant_id = :tenant_id AND run_id = :run_id"),
            {"tenant_id": str(tenant_id), "run_id": str(run_id)},
        ).mappings().first()
    return dict(row) if row is not None else None


def set_final(tenant_id: UUID, run_id: UUID, *, top5_candidate_ids: Sequence[UUID], recommendation: Any, gaps: Any) -> bool:
    """Stores the final (Stage 4) order, the deterministic recommendation and the gaps. False when no case exists."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                "UPDATE pi_research_case SET top5_candidate_ids = CAST(:ids AS uuid[]), recommendation = CAST(:rec AS jsonb), gaps = CAST(:gaps AS jsonb) "
                "WHERE tenant_id = :tenant_id AND run_id = :run_id"
            ),
            {
                "run_id": str(run_id), "tenant_id": str(tenant_id), "ids": [str(i) for i in top5_candidate_ids],
                "rec": json.dumps(recommendation, default=str), "gaps": json.dumps(gaps, default=str),
            },
        )
        return result.rowcount == 1


def attach_cfo_results(tenant_id: UUID, run_id: UUID, refs: Sequence[dict[str, Any]]) -> bool:
    """Appends references to CFO results the CEO obtained for this case's products (`{candidate_id, kind: ENGINE|ESTIMATE, ref, leg_key, status}`).
    Only references are stored: PI never computes or holds a CFO figure."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text("UPDATE pi_research_case SET cfo_refs = cfo_refs || CAST(:refs AS jsonb) WHERE tenant_id = :tenant_id AND run_id = :run_id"),
            {"run_id": str(run_id), "tenant_id": str(tenant_id), "refs": json.dumps(list(refs), default=str)},
        )
        return result.rowcount == 1


def replace_cfo_results(tenant_id: UUID, run_id: UUID, candidate_id: UUID, refs: Sequence[dict[str, Any]]) -> bool:
    """Replaces the CFO references the CEO attached for ONE product (a re-run after the seller changed a quote supersedes the earlier entries); other products'
    entries are untouched. Only references and the display text the CEO resolved from them are stored: PI holds no CFO figure of its own."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                "UPDATE pi_research_case SET cfo_refs = COALESCE((SELECT jsonb_agg(e) FROM jsonb_array_elements(cfo_refs) e WHERE e->>'candidate_id' <> :cid), '[]'::jsonb) "
                "|| CAST(:refs AS jsonb) WHERE tenant_id = :tenant_id AND run_id = :run_id"
            ),
            {"run_id": str(run_id), "tenant_id": str(tenant_id), "cid": str(candidate_id), "refs": json.dumps(list(refs), default=str)},
        )
        return result.rowcount == 1
