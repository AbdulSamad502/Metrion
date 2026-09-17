"""metric_result repository — deterministic-engine.md §9.

Persists the `MetricResult` objects `api/compute_metric.py` already builds in memory. This
module does no calculation and no interpretation of the result — it is a thin mapping from
`MetricResult` to the `metric_result` row shape, through `tenant_context.tenant_scope()`.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from calc_engine.api.compute_metric import MetricResult
from calc_engine.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO metric_result
        (id, tenant_id, metric_code, grain, target_ref, period, value_paise, recognition_state,
         confidence, calculation_basis, formula_version, config_version, canonical_data_version,
         manual_adjustment_set, as_of_date, input_refs, exclusions, is_trial, is_available,
         unavailable_reason, computed_at)
    VALUES
        (:id, :tenant_id, :metric_code, :grain, :target_ref, :period, :value_paise, :recognition_state,
         :confidence, :calculation_basis, :formula_version, :config_version, :canonical_data_version,
         CAST(:manual_adjustment_set AS jsonb), :as_of_date, CAST(:input_refs AS jsonb), CAST(:exclusions AS jsonb),
         :is_trial, :is_available, :unavailable_reason, :computed_at)
    """
)

_GET_SQL = text(
    """
    SELECT id, metric_code, grain, target_ref, period, value_paise, recognition_state, confidence,
           calculation_basis, formula_version, config_version, canonical_data_version,
           manual_adjustment_set, as_of_date, input_refs, exclusions, is_trial, is_available,
           unavailable_reason, computed_at
    FROM metric_result
    WHERE id = :id
    """
)


def _json_safe(value: object) -> object:
    """input_refs/exclusions may contain UUIDs, which json.dumps can't serialise directly."""
    if isinstance(value, UUID):
        return str(value)
    return value


def save(
    tenant_id: UUID,
    result: MetricResult,
    *,
    grain: str,
    target_ref: str,
    period: str | None,
    config_version: str,
    is_trial: bool = False,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(result.id),
                "tenant_id": str(tenant_id),
                "metric_code": result.metric_code,
                "grain": grain,
                "target_ref": target_ref,
                "period": period,
                "value_paise": result.value_paise,
                "recognition_state": result.recognition_state.value,
                "confidence": result.confidence,
                "calculation_basis": result.calculation_basis,
                "formula_version": result.formula_version,
                "config_version": config_version,
                "canonical_data_version": result.canonical_data_version,
                "manual_adjustment_set": json.dumps(list(result.manual_adjustment_set)),
                "as_of_date": result.as_of_date,
                "input_refs": json.dumps([_json_safe(x) for x in result.input_refs]),
                "exclusions": json.dumps(list(result.exclusions)),
                "is_trial": is_trial,
                "is_available": result.is_available,
                "unavailable_reason": result.unavailable_reason,
                "computed_at": result.computed_at,
            },
        )
    return result.id


def get(tenant_id: UUID, result_id: UUID) -> dict[str, object] | None:
    """Fetches one metric_result by its engine_result_ref, scoped to tenant_id. Returns None
    both when the row doesn't exist and when it belongs to another tenant — RLS makes those
    two cases indistinguishable by design (§9.1), which is correct: a cross-tenant existence
    leak (404 vs "belongs to someone else") is itself an isolation violation."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_GET_SQL, {"id": str(result_id)}).first()
        return dict(row._mapping) if row is not None else None
