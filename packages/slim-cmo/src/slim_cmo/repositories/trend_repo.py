"""`TrendStore` over Postgres: a trend report is one `cmo_generation` row (TREND_REPORT, no marketplace) plus its
`cmo_trend_report` row, written in ONE tenant-scoped transaction. Append-only for the application role (no update path)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from slim_cmo.billing import ExistingArtefact
from slim_cmo.repositories import config_repo, generation_repo
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.models import GenerationRecord
from slim_cmo.service.trends import StoredTrendReport, TrendRecord
from slim_cmo.types import GenerationStatus, OutputType

_INSERT_REPORT = text(
    """
    INSERT INTO cmo_trend_report (tenant_id, generation_id, niche_term_ids, sections_requested, sections, interpretation,
                                  evidence, outbound_queries, config_snapshot, market_signal_run_ref)
    VALUES (:tenant_id, :generation_id, :niche_term_ids, :sections_requested, CAST(:sections AS jsonb), CAST(:interpretation AS jsonb),
            CAST(:evidence AS jsonb), CAST(:outbound_queries AS jsonb), CAST(:config_snapshot AS jsonb), :run_ref)
    """
)
_LOAD = text(
    """
    SELECT g.id, g.status, g.failure_reason, g.created_at, g.agent_run_id,
           r.sections, r.interpretation, r.evidence, r.outbound_queries, r.config_snapshot, r.niche_term_ids, r.sections_requested
    FROM cmo_generation g LEFT JOIN cmo_trend_report r ON r.tenant_id = g.tenant_id AND r.generation_id = g.id
    WHERE g.tenant_id = :tenant_id AND g.output_type = 'TREND_REPORT' AND g.id = :id
    """
)
_LIST = text(
    """
    SELECT g.id, g.status, g.failure_reason, g.created_at, g.agent_run_id, r.sections_requested, g.output_structured
    FROM cmo_generation g LEFT JOIN cmo_trend_report r ON r.tenant_id = g.tenant_id AND r.generation_id = g.id
    WHERE g.tenant_id = :tenant_id AND g.output_type = 'TREND_REPORT'
    ORDER BY g.created_at DESC, g.id LIMIT :limit
    """
)


def _report(r: Any) -> dict[str, Any]:
    return {
        "sections": r.sections, "interpretation": r.interpretation, "evidence": r.evidence, "outbound_queries": r.outbound_queries,
        "config_snapshot": r.config_snapshot, "niche_term_ids": [str(x) for x in (r.niche_term_ids or [])],
        "sections_requested": list(r.sections_requested or []),
    }


class PostgresTrendStore:
    def load_config(self, tenant_id: UUID, keys: Sequence[str], as_of: date) -> Mapping[str, Any]:
        with tenant_scope(tenant_id) as conn:
            return config_repo.load_config_values(conn, tenant_id, keys, as_of)

    def find_artefacts(self, tenant_id: UUID, request_key: str) -> Sequence[ExistingArtefact]:
        with tenant_scope(tenant_id) as conn:
            return generation_repo.find_artefacts(conn, tenant_id, request_key)

    def save_report(
        self, tenant_id: UUID, user_id: UUID, *, request_key: str, status: GenerationStatus, failure_reason: str | None,
        agent_run_id: UUID | None, summary: dict[str, Any] | None, trend: TrendRecord | None,
    ) -> UUID:
        record = GenerationRecord(
            output_type=OutputType.TREND_REPORT, marketplace=None, sku=None, status=status, request_key=request_key,
            generated_by=user_id, agent_run_id=agent_run_id, output_text=None, output_structured=summary,
            failure_reason=failure_reason, format_constraint_ref=None, image_analysis_id=None, grounding_basis=None,
            grounding_approval_id=None,
        )
        with tenant_scope(tenant_id) as conn:  # the generation row and its report commit together (a duplicate rolls both back)
            generation_id = generation_repo.insert_generation(conn, tenant_id, record)
            if trend is not None:
                conn.execute(
                    _INSERT_REPORT,
                    {
                        "tenant_id": tenant_id, "generation_id": generation_id, "niche_term_ids": list(trend.niche_term_ids),
                        "sections_requested": list(trend.sections_requested), "sections": json.dumps(trend.sections),
                        "interpretation": json.dumps(trend.interpretation), "evidence": json.dumps(trend.evidence),
                        "outbound_queries": json.dumps(trend.outbound_queries), "config_snapshot": json.dumps(trend.config_snapshot),
                        "run_ref": trend.market_signal_run_ref,
                    },
                )
            return generation_id

    def load_report(self, tenant_id: UUID, generation_id: UUID) -> StoredTrendReport | None:
        with tenant_scope(tenant_id) as conn:
            r = conn.execute(_LOAD, {"tenant_id": tenant_id, "id": generation_id}).first()
        if r is None:
            return None
        return StoredTrendReport(r.id, GenerationStatus(r.status), r.failure_reason, r.created_at, r.agent_run_id, _report(r) if r.sections is not None else None)

    def list_reports(self, tenant_id: UUID, limit: int) -> Sequence[StoredTrendReport]:
        with tenant_scope(tenant_id) as conn:
            rows = conn.execute(_LIST, {"tenant_id": tenant_id, "limit": limit}).all()
        return [
            StoredTrendReport(
                r.id, GenerationStatus(r.status), r.failure_reason, r.created_at, r.agent_run_id,
                {"sections_requested": list(r.sections_requested or []), "summary": r.output_structured},
            )
            for r in rows
        ]
