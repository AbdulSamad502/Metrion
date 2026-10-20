"""ci_candidate_relevance — competitor-intelligence-agent.md §5.4, §6.14.

One row per candidate per scoring pass. Never collapsed into a single number on
`ci_candidate` (C25) — `axis_scores`/`axis_states`/`axis_rationale` are persisted as their
own jsonb columns so the full breakdown (§6.14.3 step 3) is always reconstructable, never
just the band.

Every function takes `tenant_id` first and receives its connection only via `tenant_scope()`
(auth.md §7.3), matching every other repository in this package.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.discovery.relevance_scoring import AXIS_ORDER, RelevanceBreakdown
from competitor_intelligence.repositories.tenant_context import tenant_scope


def _axis_scores_json(breakdown: RelevanceBreakdown) -> str:
    return json.dumps({axis: breakdown.axis_results[axis].score for axis in AXIS_ORDER})


def _axis_states_json(breakdown: RelevanceBreakdown) -> str:
    return json.dumps({axis: breakdown.axis_results[axis].state.value for axis in AXIS_ORDER})


def _axis_rationale_json(breakdown: RelevanceBreakdown) -> str:
    return json.dumps({axis: breakdown.axis_results[axis].rationale for axis in AXIS_ORDER})


def insert_relevance(
    tenant_id: UUID,
    *,
    candidate_id: UUID,
    breakdown: RelevanceBreakdown,
    recalculated_from: UUID | None = None,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_candidate_relevance
                    (tenant_id, candidate_id, is_provisional, band, total_score,
                     axis_scores, axis_states, axis_rationale, recalculated_from)
                VALUES
                    (:tenant_id, :candidate_id, :is_provisional, :band, :total_score,
                     CAST(:axis_scores AS jsonb), CAST(:axis_states AS jsonb),
                     CAST(:axis_rationale AS jsonb), :recalculated_from)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "candidate_id": str(candidate_id),
                "is_provisional": breakdown.is_provisional,
                "band": breakdown.band.value,
                "total_score": breakdown.total_score,
                "axis_scores": _axis_scores_json(breakdown),
                "axis_states": _axis_states_json(breakdown),
                "axis_rationale": _axis_rationale_json(breakdown),
                "recalculated_from": str(recalculated_from) if recalculated_from else None,
            },
        ).one()
        return cast(UUID, row[0])


def get_latest_relevance(tenant_id: UUID, candidate_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT * FROM ci_candidate_relevance
                WHERE tenant_id = :tenant_id AND candidate_id = :candidate_id
                ORDER BY scored_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "candidate_id": str(candidate_id)},
        ).mappings().first()
        return dict(row) if row is not None else None


def list_relevance_history(tenant_id: UUID, candidate_id: UUID) -> list[dict[str, Any]]:
    """All scoring passes for a candidate, most recent first — including any row a later
    pass superseded via `recalculated_from` (§6.14.0: contradicted-by-evidence recalculation
    retains the prior row rather than overwriting it)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM ci_candidate_relevance
                WHERE tenant_id = :tenant_id AND candidate_id = :candidate_id
                ORDER BY scored_at DESC
                """
            ),
            {"tenant_id": str(tenant_id), "candidate_id": str(candidate_id)},
        ).mappings().all()
        return [dict(r) for r in rows]
