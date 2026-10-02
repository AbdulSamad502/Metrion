"""reconciliation_run / reconciliation_match / reconciliation_exception repository —
`packages/calc-engine/migrations/versions/20260925_0004_reconciliation_tables.py` (§5.9 schema,
data-foundation.md §5.8 for the algorithm these rows record the outcome of).

Insert-only, mirroring `repositories/metric_result_repo.py`'s style exactly: parameterized
`text()` SQL, one function per table, `tenant_scope()` for every statement, no calculation or
interpretation of any kind here — this module is a thin mapping from already-decided outcomes
(computed by `calc_engine.api.reconcile.reconcile`) to row shape.

`reconciliation_run` additionally gets a `mark_reconciliation_run_finished` update function,
mirroring `data_foundation.repositories.ingestion_run_repo.mark_finished`'s exact
insert-then-update-in-place pattern (a run starts `RUNNING`, later flips to `COMPLETE`/`FAILED`
with its counts filled in — never re-inserted, never deleted).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from calc_engine.repositories.tenant_context import tenant_scope

_INSERT_RUN_SQL = text(
    """
    INSERT INTO reconciliation_run
        (id, tenant_id, marketplace, period_start, period_end, as_of_date,
         tolerance_config_version, formula_version, status, settlement_line_count,
         sales_line_count, match_count, exception_count, join_key_validated, started_at,
         finished_at)
    VALUES
        (:id, :tenant_id, :marketplace, :period_start, :period_end, :as_of_date,
         :tolerance_config_version, :formula_version, :status, :settlement_line_count,
         :sales_line_count, :match_count, :exception_count, :join_key_validated, :started_at,
         :finished_at)
    """
)

_MARK_RUN_FINISHED_SQL = text(
    """
    UPDATE reconciliation_run
    SET status = :status, finished_at = :finished_at, settlement_line_count = :settlement_line_count,
        sales_line_count = :sales_line_count, match_count = :match_count, exception_count = :exception_count
    WHERE id = :id
    """
)

_INSERT_MATCH_SQL = text(
    """
    INSERT INTO reconciliation_match
        (id, tenant_id, reconciliation_run_id, sales_line_id, settlement_line_id, component_code,
         outcome, variance_paise, confidence, formula_version, computed_at)
    VALUES
        (:id, :tenant_id, :reconciliation_run_id, :sales_line_id, :settlement_line_id, :component_code,
         :outcome, :variance_paise, :confidence, :formula_version, :computed_at)
    """
)

_INSERT_EXCEPTION_SQL = text(
    """
    INSERT INTO reconciliation_exception
        (id, tenant_id, reconciliation_run_id, reconciliation_match_id, exception_type,
         sales_line_id, settlement_line_id, candidate_sales_line_ids, marketplace, component_code,
         amount_paise, confidence, formula_version, computed_at)
    VALUES
        (:id, :tenant_id, :reconciliation_run_id, :reconciliation_match_id, :exception_type,
         :sales_line_id, :settlement_line_id, CAST(:candidate_sales_line_ids AS jsonb), :marketplace,
         :component_code, :amount_paise, :confidence, :formula_version, :computed_at)
    """
)


def insert_reconciliation_run(
    tenant_id: UUID,
    *,
    marketplace: str,
    period_start: date,
    period_end: date,
    as_of_date: date,
    tolerance_config_version: int,
    formula_version: str,
    status: str,
    join_key_validated: bool,
    started_at: datetime,
    finished_at: datetime | None = None,
    settlement_line_count: int | None = None,
    sales_line_count: int | None = None,
    match_count: int | None = None,
    exception_count: int | None = None,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_RUN_SQL,
            {
                "id": str(new_id),
                "tenant_id": str(tenant_id),
                "marketplace": marketplace,
                "period_start": period_start,
                "period_end": period_end,
                "as_of_date": as_of_date,
                "tolerance_config_version": tolerance_config_version,
                "formula_version": formula_version,
                "status": status,
                "settlement_line_count": settlement_line_count,
                "sales_line_count": sales_line_count,
                "match_count": match_count,
                "exception_count": exception_count,
                "join_key_validated": join_key_validated,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
    return new_id


def mark_reconciliation_run_finished(
    tenant_id: UUID,
    run_id: UUID,
    *,
    status: str,
    finished_at: datetime,
    settlement_line_count: int,
    sales_line_count: int,
    match_count: int,
    exception_count: int,
) -> None:
    """Flips a `RUNNING` row to its final status with every count populated — a status flip on
    the same row, never a re-insert or delete, mirroring
    `data_foundation.repositories.ingestion_run_repo.mark_finished`'s exact convention."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _MARK_RUN_FINISHED_SQL,
            {
                "id": str(run_id),
                "status": status,
                "finished_at": finished_at,
                "settlement_line_count": settlement_line_count,
                "sales_line_count": sales_line_count,
                "match_count": match_count,
                "exception_count": exception_count,
            },
        )


def _match_params(
    new_id: UUID,
    tenant_id: UUID,
    *,
    reconciliation_run_id: UUID,
    sales_line_id: UUID,
    settlement_line_id: UUID,
    component_code: str | None,
    outcome: str,
    variance_paise: int,
    confidence: str,
    formula_version: str,
    computed_at: datetime,
) -> dict[str, Any]:
    return {
        "id": str(new_id),
        "tenant_id": str(tenant_id),
        "reconciliation_run_id": str(reconciliation_run_id),
        "sales_line_id": str(sales_line_id),
        "settlement_line_id": str(settlement_line_id),
        "component_code": component_code,
        "outcome": outcome,
        "variance_paise": variance_paise,
        "confidence": confidence,
        "formula_version": formula_version,
        "computed_at": computed_at,
    }


def _exception_params(
    new_id: UUID,
    tenant_id: UUID,
    *,
    reconciliation_run_id: UUID,
    reconciliation_match_id: UUID | None = None,
    exception_type: str,
    sales_line_id: UUID | None = None,
    settlement_line_id: UUID | None = None,
    candidate_sales_line_ids: list[UUID] | None = None,
    marketplace: str,
    component_code: str | None = None,
    amount_paise: int,
    confidence: str,
    formula_version: str,
    computed_at: datetime,
) -> dict[str, Any]:
    candidate_json: str | None = (
        json.dumps([str(i) for i in candidate_sales_line_ids]) if candidate_sales_line_ids is not None else None
    )
    return {
        "id": str(new_id),
        "tenant_id": str(tenant_id),
        "reconciliation_run_id": str(reconciliation_run_id),
        "reconciliation_match_id": str(reconciliation_match_id) if reconciliation_match_id else None,
        "exception_type": exception_type,
        "sales_line_id": str(sales_line_id) if sales_line_id else None,
        "settlement_line_id": str(settlement_line_id) if settlement_line_id else None,
        "candidate_sales_line_ids": candidate_json,
        "marketplace": marketplace,
        "component_code": component_code,
        "amount_paise": amount_paise,
        "confidence": confidence,
        "formula_version": formula_version,
        "computed_at": computed_at,
    }


def insert_reconciliation_match(
    tenant_id: UUID,
    *,
    reconciliation_run_id: UUID,
    sales_line_id: UUID,
    settlement_line_id: UUID,
    component_code: str | None,
    outcome: str,
    variance_paise: int,
    confidence: str,
    formula_version: str,
    computed_at: datetime,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_MATCH_SQL,
            _match_params(
                new_id, tenant_id, reconciliation_run_id=reconciliation_run_id, sales_line_id=sales_line_id,
                settlement_line_id=settlement_line_id, component_code=component_code, outcome=outcome,
                variance_paise=variance_paise, confidence=confidence, formula_version=formula_version,
                computed_at=computed_at,
            ),
        )
    return new_id


def insert_reconciliation_exception(
    tenant_id: UUID,
    *,
    reconciliation_run_id: UUID,
    reconciliation_match_id: UUID | None = None,
    exception_type: str,
    sales_line_id: UUID | None = None,
    settlement_line_id: UUID | None = None,
    candidate_sales_line_ids: list[UUID] | None = None,
    marketplace: str,
    component_code: str | None = None,
    amount_paise: int,
    confidence: str,
    formula_version: str,
    computed_at: datetime,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_EXCEPTION_SQL,
            _exception_params(
                new_id, tenant_id, reconciliation_run_id=reconciliation_run_id,
                reconciliation_match_id=reconciliation_match_id, exception_type=exception_type,
                sales_line_id=sales_line_id, settlement_line_id=settlement_line_id,
                candidate_sales_line_ids=candidate_sales_line_ids, marketplace=marketplace,
                component_code=component_code, amount_paise=amount_paise, confidence=confidence,
                formula_version=formula_version, computed_at=computed_at,
            ),
        )
    return new_id


def insert_reconciliation_rows(
    tenant_id: UUID,
    *,
    matches: Sequence[tuple[UUID, dict[str, Any]]],
    exceptions: Sequence[tuple[UUID, dict[str, Any]]],
) -> None:
    """Bulk twin of `insert_reconciliation_match` / `insert_reconciliation_exception`: each
    entry is `(client_generated_id, the exact keyword arguments the single-row function takes)`.
    One transaction, one executemany round trip per table. Matches are written first — an
    exception's `reconciliation_match_id` may reference a match in this same batch."""
    if not matches and not exceptions:
        return
    with tenant_scope(tenant_id) as conn:
        if matches:
            conn.execute(_INSERT_MATCH_SQL, [_match_params(i, tenant_id, **kw) for i, kw in matches])
        if exceptions:
            conn.execute(_INSERT_EXCEPTION_SQL, [_exception_params(i, tenant_id, **kw) for i, kw in exceptions])


_EXCEPTIONS_FOR_RUN_SQL = text(
    """
    SELECT id, tenant_id, reconciliation_run_id, reconciliation_match_id, exception_type,
           sales_line_id, settlement_line_id, candidate_sales_line_ids, marketplace,
           component_code, amount_paise, confidence, formula_version, computed_at
    FROM reconciliation_exception
    WHERE reconciliation_run_id = :reconciliation_run_id
    """
)


_SETTLEMENT_LAG_PAIRS_FOR_RUN_SQL = text(
    """
    SELECT rm.confidence AS match_confidence,
           sl.invoice_date, sl.dispatch_date, sl.order_date,
           stl.settlement_date
    FROM reconciliation_match rm
    JOIN sales_line sl ON sl.id = rm.sales_line_id AND sl.tenant_id = rm.tenant_id
    JOIN settlement_line stl ON stl.id = rm.settlement_line_id AND stl.tenant_id = rm.tenant_id
    WHERE rm.tenant_id = :tenant_id
      AND rm.reconciliation_run_id = :reconciliation_run_id
      AND rm.outcome IN ('MATCHED_EXACT', 'MATCHED_WITHIN_TOLERANCE')
    """
)


def settlement_lag_pairs_for_run(tenant_id: UUID, reconciliation_run_id: UUID) -> list[dict[str, Any]]:
    """anomaly-detection.md §6.1/§6.6/§10 P1's `SETTLEMENT_LAG_DAYS` aggregate's own real read
    path — the one query joining `reconciliation_match` (this package's own table) to
    data-foundation's `sales_line`/`settlement_line` (read-only, the same convention
    `canonical_repo.py`/`settlement_repo.py` already establish for those two tables).

    Scoped to ONE `reconciliation_run_id` — the run `reconcile()` (via
    `backend.services.cfo_actions.run_leak_shield_reconciliation`) just produced — rather than a
    marketplace/period range, since a run's own `reconciliation_match` rows already carry a real
    join-key confidence cap (deterministic-engine.md §5.12.2) and a real marketplace scope
    (`reconciliation_run.marketplace`); re-deriving either from a separate marketplace/period
    filter here would risk drifting out of sync with what that specific run actually produced.

    `outcome IN ('MATCHED_EXACT', 'MATCHED_WITHIN_TOLERANCE')` only — the "MATCHED_*" family this
    checkpoint's own brief names explicitly. Disclosed choice: `VARIANCE_EXCEEDS_TOLERANCE` rows,
    though also genuinely settled pairs with a real `settlement_date`, are NOT prefixed
    `MATCHED_` and are excluded here — each such row already gets its own dedicated
    `LEAK_EXCEPTION_AMOUNT`/`leak_finding` treatment elsewhere; not double-purposing it as a
    lag-timing input too is the narrower, safer reading of "the MATCHED_* family" as written.
    `UNSETTLED_*`/`ORPHAN_*`/`DUPLICATE_*`/`AMBIGUOUS_MATCH` outcomes never reach
    `reconciliation_match` at all (this migration's own docstring: only the three outcomes above
    are ever written there) — this filter is not excluding rows that could theoretically appear
    here, it names, for the reader, exactly which of the three real `outcome` values survive it.

    Returns raw rows (three sales-side date columns + one settlement-side date + the match's own
    `confidence`) — resolving the sales line's effective date
    (`calc_engine.dates.resolve_document_date`), computing `lag_days`, and aggregating the mean
    is `calc_engine.formulas.settlement_lag.settlement_lag_days_aggregate`'s job, not this
    repository's — mirrors `exceptions_for_run`'s own "no calculation or interpretation of any
    kind here" convention exactly."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _SETTLEMENT_LAG_PAIRS_FOR_RUN_SQL,
            {"tenant_id": str(tenant_id), "reconciliation_run_id": str(reconciliation_run_id)},
        )
        return [dict(row._mapping) for row in rows]


def exceptions_for_run(tenant_id: UUID, reconciliation_run_id: UUID) -> list[dict[str, Any]]:
    """Every `reconciliation_exception` row this run produced — the one read path this
    insert-only module lacked (D5). Same `tenant_scope()`/dict-row-return convention as every
    other function in this module and `canonical_repo.py`'s own read functions: no calculation
    or interpretation, a thin mapping from row to dict. This is how `backend.services.
    cfo_actions.run_leak_shield_reconciliation` fetches back the exception rows `reconcile()`
    just persisted, to build real `leak_finding` rows from them."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _EXCEPTIONS_FOR_RUN_SQL, {"reconciliation_run_id": str(reconciliation_run_id)}
        )
        return [dict(row._mapping) for row in rows]
