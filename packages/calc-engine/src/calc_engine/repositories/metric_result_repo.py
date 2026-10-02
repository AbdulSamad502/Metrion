"""metric_result repository — deterministic-engine.md §9.

Persists the `MetricResult` objects `api/compute_metric.py` already builds in memory. This
module does no calculation and no interpretation of the result — it is a thin mapping from
`MetricResult` to the `metric_result` row shape, through `tenant_context.tenant_scope()`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.api.compute_metric import MetricResult
from calc_engine.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO metric_result
        (id, tenant_id, metric_code, grain, target_ref, period, value_paise,
         value_fraction_numerator, value_fraction_denominator, recognition_state,
         confidence, calculation_basis, formula_version, config_version, canonical_data_version,
         manual_adjustment_set, as_of_date, input_refs, exclusions, is_trial, is_available,
         unavailable_reason, computed_at)
    VALUES
        (:id, :tenant_id, :metric_code, :grain, :target_ref, :period, :value_paise,
         :value_fraction_numerator, :value_fraction_denominator, :recognition_state,
         :confidence, :calculation_basis, :formula_version, :config_version, :canonical_data_version,
         CAST(:manual_adjustment_set AS jsonb), :as_of_date, CAST(:input_refs AS jsonb), CAST(:exclusions AS jsonb),
         :is_trial, :is_available, :unavailable_reason, :computed_at)
    """
)

_GET_SQL = text(
    """
    SELECT id, metric_code, grain, target_ref, period, value_paise,
           value_fraction_numerator, value_fraction_denominator, recognition_state, confidence,
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


def _params(
    tenant_id: UUID,
    result: MetricResult,
    *,
    grain: str,
    target_ref: str,
    period: str | None,
    config_version: str,
    is_trial: bool = False,
) -> dict[str, Any]:
    return {
        "id": str(result.id),
        "tenant_id": str(tenant_id),
        "metric_code": result.metric_code,
        "grain": grain,
        "target_ref": target_ref,
        "period": period,
        "value_paise": result.value_paise,
        "value_fraction_numerator": (
            result.value_fraction.numerator if result.value_fraction is not None else None
        ),
        "value_fraction_denominator": (
            result.value_fraction.denominator if result.value_fraction is not None else None
        ),
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
    }


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
            _params(
                tenant_id, result, grain=grain, target_ref=target_ref, period=period,
                config_version=config_version, is_trial=is_trial,
            ),
        )
    return result.id


def save_many(tenant_id: UUID, items: Sequence[tuple[MetricResult, dict[str, Any]]]) -> list[UUID]:
    """Bulk twin of `save`: each item is `(result, the keyword arguments `save` takes — grain,
    target_ref, period, config_version[, is_trial])`. One transaction, one executemany round trip
    (measured: a CEO Hub reconcile spent ~1.8 s of a 4.6 s request on 128 one-row `save` calls)."""
    if not items:
        return []
    with tenant_scope(tenant_id) as conn:
        conn.execute(_INSERT_SQL, [_params(tenant_id, result, **kw) for result, kw in items])
    return [result.id for result, _ in items]


_LIST_BY_METRIC_CODE_SQL = text(
    """
    SELECT id, metric_code, grain, target_ref, period, value_paise,
           value_fraction_numerator, value_fraction_denominator, recognition_state, confidence,
           calculation_basis, formula_version, config_version, canonical_data_version,
           manual_adjustment_set, as_of_date, input_refs, exclusions, is_trial, is_available,
           unavailable_reason, computed_at
    FROM metric_result
    WHERE metric_code = :metric_code
      AND (CAST(:period_start AS text) IS NULL OR period >= :period_start)
      AND (CAST(:period_end AS text) IS NULL OR period <= :period_end)
    ORDER BY period ASC
    """
)


def list_by_metric_code(
    tenant_id: UUID,
    *,
    metric_code: str,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[dict[str, object]]:
    """Fetches every `metric_result` row for `tenant_id` whose `metric_code` matches, tenant-
    scoped via `tenant_scope()` exactly like `get()` — the one genuinely missing read path CP
    B2 (`twinkly-mapping-canyon.md`) needs: there was no way to fetch a tenant's history across
    multiple periods for one metric before this function, only single-row lookup by exact id
    (`get`).

    **Why `period_start`/`period_end` are plain ISO date strings compared as TEXT, not a real
    date-range query on typed columns:** `save()`'s own `period` parameter is persisted as a
    single nullable TEXT column, not two typed date columns — for a `TENANT_PERIOD`-grain
    result it holds a compound `"{period_start.isoformat()}/{period_end.isoformat()}"` label
    (see `compute_period_pnl`'s `period_label` in `backend/services/cfo_actions.py`); for a
    `SKU`-grain result (pricing curves, landed cost) it is `NULL`. There is no separate
    `period_start`/`period_end` column to filter on, and this function does not invent one —
    it filters/orders against the real, already-persisted TEXT shape. Because every real label
    this repository has ever written begins with the period's own ISO-8601 start date followed
    immediately by `/` (ASCII `0x2F`, which sorts before every digit `0`-`9`), a lexicographic
    `>=` against a lower-bound ISO date string and `<=` against an upper-bound ISO date string
    both correctly include/exclude a compound label by its start date — this is a genuine text
    comparison over the real stored shape, not a synthetic date-range filter pretending to be
    something the schema doesn't have. `ORDER BY period ASC` sorts chronologically for the same
    reason. A `NULL` period (SKU-grain rows) never satisfies either bound and is excluded by a
    period filter, which is correct: a per-SKU result has no period to compare against a range.
    `period_start`/`period_end` are each optional; passing neither returns every row for the
    `metric_code`, ordered by `period` (nulls first, per Postgres's default `NULLS FIRST` for
    ascending order on a nullable column).

    No calculation happens here — this is a plain, read-only SQL SELECT, the same kind of thin
    mapping `get()` already is."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _LIST_BY_METRIC_CODE_SQL,
            {"metric_code": metric_code, "period_start": period_start, "period_end": period_end},
        ).fetchall()
        return [dict(row._mapping) for row in rows]


def get(tenant_id: UUID, result_id: UUID) -> dict[str, object] | None:
    """Fetches one metric_result by its engine_result_ref, scoped to tenant_id. Returns None
    both when the row doesn't exist and when it belongs to another tenant — RLS makes those
    two cases indistinguishable by design (§9.1), which is correct: a cross-tenant existence
    leak (404 vs "belongs to someone else") is itself an isolation violation."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_GET_SQL, {"id": str(result_id)}).first()
        return dict(row._mapping) if row is not None else None
