"""cash_reconciliation() — deterministic-engine.md §5.13.3.

Composition layer only: every financial number here is either a direct sum of already-real,
already-persisted `settlement_line`/`line_component` amounts, or reuses `calc_engine.formulas.
leak`'s already-tested `classify_settlement_lag`/`should_report_unsettled_as_leak` unchanged —
the same functions `calc_engine.api.reconcile`'s own Path B already runs. This module invents no
new financial arithmetic.

**Why `CASH_EXPECTED`/`CASH_VARIANCE` are structurally `UNAVAILABLE` here, always, this pass.**
See §5.13.3's own long note: no adapter in this codebase maps an invoice-side marketplace-fee
`line_component` (the one input a net "expected settlement" figure needs). Approximating it from
`sales_line.gross_item_amount` (before any deduction) would misrepresent every normal settlement
as a large false shortfall — the exact class of plausible-but-unconfirmed number CLAUDE.md's hard
rule forbids. This is a real, disclosed, structural gap, not a bug in this module.

**Why `TCS_COLLECTED` is scoped to FLIPKART only.** `flipkart.sales_report.v1` is the one real
adapter in this codebase mapping an invoice-side `component_code = 'TCS'` row (§5.13.3's own
correction of `reconcile()`'s Decision A docstring, which is right about the load-bearing
capability gap but imprecise about that one column). No other marketplace's real adapter maps a
TCS or TDS component anywhere — verified by grep against `packages/data-foundation/src/
data_foundation/adapters` when this module was written (2026-09-29).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from calc_engine.api.compute_metric import MetricResult
from calc_engine.dates import resolve_document_date
from calc_engine.formulas.leak import ReconciliationOutcome, classify_settlement_lag, should_report_unsettled_as_leak
from calc_engine.repositories import canonical_repo, config_repo, settlement_repo
from calc_engine.types import Confidence, Paise, RecognitionState, combine_confidence

_FORMULA_VERSION = "cash_reconciliation.v1"
_NON_CANONICAL = "non-canonical"  # mirrors reconcile.py's own precedent — see that module's docstring

# §5.13.3 point 3: the one marketplace with a real, confirmed invoice-side TCS mapping today.
_TCS_SUPPORTED_MARKETPLACES: frozenset[str] = frozenset({"FLIPKART"})

# reconcile.py's own join-key lookup, duplicated deliberately (not imported) — this module must
# stay independently callable without a prior reconcile() run having occurred, per §5.13.3's own
# "does not depend on reconcile() having already run" design choice.
_JOIN_KEY_FIELD: dict[str, str] = {
    "MEESHO": "line_ref",
    "AMAZON": "order_ref",
    "FLIPKART": "order_ref",
}


@dataclass(frozen=True, slots=True)
class CashReconciliationResult:
    cash_received: MetricResult
    cash_expected: MetricResult
    cash_variance: MetricResult
    tcs_collected: MetricResult
    tds_deducted: MetricResult
    settled_within_lag_count: int
    unsettled_beyond_lag_count: int
    dates_missing_count: int
    formula_version: str
    computed_at: datetime


def _unavailable_metric(*, metric_code: str, reason: str, as_of_date: date, computed_at: datetime) -> MetricResult:
    return MetricResult(
        id=uuid4(),
        metric_code=metric_code,
        value_paise=None,
        recognition_state=RecognitionState.UNAVAILABLE,
        confidence="DERIVED",
        calculation_basis=f"{metric_code} (deterministic-engine.md §5.13.3) — UNAVAILABLE, see unavailable_reason",
        formula_version=_FORMULA_VERSION,
        canonical_data_version=_NON_CANONICAL,
        as_of_date=as_of_date,
        input_refs=(),
        exclusions=(),
        computed_at=computed_at,
        is_available=False,
        unavailable_reason=reason,
    )


def cash_reconciliation(
    tenant_id: UUID,
    *,
    marketplace: str,
    period_start: date,
    period_end: date,
    as_of_date: date,
    computed_at: datetime,
) -> CashReconciliationResult:
    if marketplace not in _JOIN_KEY_FIELD:
        raise ValueError(
            f"cash_reconciliation() has no join-key mapping for marketplace={marketplace!r} — "
            "data-foundation.md §5.1.5 only specifies MEESHO/AMAZON/FLIPKART; refusing to guess "
            "a join key for an unspecified marketplace rather than silently defaulting one."
        )
    join_key_field = _JOIN_KEY_FIELD[marketplace]

    # --- CASH_RECEIVED: Σ settlement_line.gross_settlement_amount, real rows only ------------
    all_settlement_lines = settlement_repo.settlement_lines_in_period(
        tenant_id, period_start=period_start, period_end=period_end, marketplace=marketplace
    )
    settlement_lines = [row for row in all_settlement_lines if row["marketplace"] == marketplace]

    received_amounts: list[int] = []
    received_confidences: list[Confidence] = []
    amount_unavailable_count = 0
    for row in settlement_lines:
        if row["gross_settlement_amount"] is None:
            # Amazon's melted amount-type/description/value triple (data-foundation.md's
            # documented shape) — excluded from the sum, counted, never treated as a zero
            # contribution (§5.13.3 point 1).
            amount_unavailable_count += 1
            continue
        received_amounts.append(row["gross_settlement_amount"])
        received_confidences.append(Confidence(row["confidence"]))

    if not settlement_lines:
        cash_received = _unavailable_metric(
            metric_code="CASH_RECEIVED",
            reason=(
                f"No settlement_line rows for marketplace={marketplace!r} in "
                f"{period_start.isoformat()}..{period_end.isoformat()}"
            ),
            as_of_date=as_of_date,
            computed_at=computed_at,
        )
    else:
        total_received = sum(received_amounts)
        received_confidence = (
            combine_confidence(*received_confidences) if received_confidences else Confidence.DERIVED
        )
        cash_received = MetricResult(
            id=uuid4(),
            metric_code="CASH_RECEIVED",
            value_paise=total_received,
            recognition_state=RecognitionState.RECOGNISED,
            confidence=received_confidence.value,
            calculation_basis=(
                f"CASH_RECEIVED = Σ settlement_line.gross_settlement_amount across "
                f"{len(received_amounts)} settlement row(s) ({amount_unavailable_count} excluded, "
                "amount not populated) — deterministic-engine.md §5.13.3 point 1"
            ),
            formula_version=_FORMULA_VERSION,
            canonical_data_version=_NON_CANONICAL,
            as_of_date=as_of_date,
            input_refs=(),
            exclusions=(),
            computed_at=computed_at,
            is_available=True,
        )

    # --- CASH_EXPECTED / CASH_VARIANCE: structurally UNAVAILABLE this pass (§5.13.3 point 2) --
    unavailable_reason = (
        "no invoice-side marketplace-fee component data exists for any adapter yet — see "
        "deterministic-engine.md §5.13.3"
    )
    cash_expected = _unavailable_metric(
        metric_code="CASH_EXPECTED", reason=unavailable_reason, as_of_date=as_of_date, computed_at=computed_at
    )
    cash_variance = _unavailable_metric(
        metric_code="CASH_VARIANCE", reason=unavailable_reason, as_of_date=as_of_date, computed_at=computed_at
    )

    # --- TCS_COLLECTED / TDS_DEDUCTED (§5.13.3 points 3-4) ------------------------------------
    tds_deducted = _unavailable_metric(
        metric_code="TDS_DEDUCTED",
        reason="no adapter maps a TDS component for any marketplace yet",
        as_of_date=as_of_date,
        computed_at=computed_at,
    )

    if marketplace not in _TCS_SUPPORTED_MARKETPLACES:
        tcs_collected = _unavailable_metric(
            metric_code="TCS_COLLECTED",
            reason=f"no adapter maps a TCS component for marketplace={marketplace!r}",
            as_of_date=as_of_date,
            computed_at=computed_at,
        )
        sales_lines: list[dict[str, Any]] = []
        dateless_sales_lines: list[dict[str, Any]] = []
    else:
        dated_sales_lines = canonical_repo.sales_lines_in_period(
            tenant_id, period_start=period_start, period_end=period_end, marketplace=marketplace
        )
        dated_sales_lines = [row for row in dated_sales_lines if row["marketplace"] == marketplace]
        dateless_sales_lines = canonical_repo.sales_lines_without_document_date(tenant_id, marketplace=marketplace)

        sales_lines_by_id: dict[Any, dict[str, Any]] = {}
        for row in dated_sales_lines + dateless_sales_lines:
            sales_lines_by_id[row["sales_line_id"]] = row
        sales_lines = list(sales_lines_by_id.values())

        component_rows = canonical_repo.components_for_lines(
            tenant_id, sales_line_ids=[row["sales_line_id"] for row in sales_lines]
        )
        tcs_amounts = [
            row["amount"]
            for row in component_rows
            if row["source_side"] == "INVOICE" and row["component_code"] == "TCS"
        ]
        tcs_confidences = [
            Confidence(sales_lines_by_id[row["sales_line_id"]]["confidence"])
            for row in component_rows
            if row["source_side"] == "INVOICE" and row["component_code"] == "TCS"
        ]
        total_tcs = sum(tcs_amounts)
        tcs_confidence = combine_confidence(*tcs_confidences) if tcs_confidences else Confidence.DERIVED
        tcs_collected = MetricResult(
            id=uuid4(),
            metric_code="TCS_COLLECTED",
            value_paise=total_tcs,
            recognition_state=RecognitionState.RECOGNISED,
            confidence=tcs_confidence.value,
            calculation_basis=(
                f"TCS_COLLECTED = Σ line_component.amount where component_code='TCS', "
                f"source_side='INVOICE', across {len(tcs_amounts)} row(s) for marketplace="
                f"{marketplace!r} — deterministic-engine.md §5.13.3 point 3. A genuine zero (the "
                "mapping exists, nothing summed) is distinct from the UNAVAILABLE branch above."
            ),
            formula_version=_FORMULA_VERSION,
            canonical_data_version=_NON_CANONICAL,
            as_of_date=as_of_date,
            input_refs=(),
            exclusions=(),
            computed_at=computed_at,
            is_available=True,
        )

    # --- Timing: settled_within_lag / unsettled_beyond_lag / dates_missing (§5.13.3 point 5) --
    if marketplace not in _TCS_SUPPORTED_MARKETPLACES:
        # sales_lines were not fetched above (TCS-branch skipped) — fetch them now, independently
        # of TCS support, since timing classification applies to every supported marketplace.
        dated_sales_lines = canonical_repo.sales_lines_in_period(
            tenant_id, period_start=period_start, period_end=period_end, marketplace=marketplace
        )
        dated_sales_lines = [row for row in dated_sales_lines if row["marketplace"] == marketplace]
        dateless_sales_lines = canonical_repo.sales_lines_without_document_date(tenant_id, marketplace=marketplace)
        sales_lines_by_id = {}
        for row in dated_sales_lines + dateless_sales_lines:
            sales_lines_by_id[row["sales_line_id"]] = row
        sales_lines = list(sales_lines_by_id.values())

    # A sales_line counts as "settled" for timing purposes when at least one settlement_line in
    # this period/marketplace shares its join-key value — the same existence test reconcile()'s
    # own Path A performs via resolve_match_candidates, simplified here to a boolean presence
    # check (this module needs "settled or not", not Collision/NoCandidate/SingleMatch detail).
    settled_join_key_values = {
        row.get(join_key_field) for row in settlement_lines if row.get(join_key_field) is not None
    }

    settled_within_lag_count = 0
    unsettled_beyond_lag_count = 0
    dates_missing_count = 0

    default_tolerance_row = config_repo.resolve_reconciliation_tolerance(
        tenant_id, marketplace=marketplace, component_code="*", as_of_date=as_of_date
    )

    for sales_line in sales_lines:
        if sales_line.get(join_key_field) in settled_join_key_values:
            # Already settled — not part of the "still waiting" timing count. The realized lag
            # for a settled line is `calc_engine.formulas.settlement_lag.
            # settlement_lag_days_aggregate`'s concern (requires a real reconciliation_match row
            # from a prior reconcile() run), out of this function's own scope.
            continue

        invoice_date = sales_line.get("invoice_date")
        dispatch_date = sales_line.get("dispatch_date")
        order_date = sales_line.get("order_date")
        if invoice_date is None and dispatch_date is None and order_date is None:
            dates_missing_count += 1
            continue

        if default_tolerance_row is None:
            # No marketplace-wide default lag config at all — never invent a lag threshold
            # (mirrors reconcile()'s own Path B guard).
            continue

        document_date = resolve_document_date(invoice_date, dispatch_date, order_date)
        settlement_lag_days = int(default_tolerance_row["settlement_lag_days"])
        outcome = classify_settlement_lag(
            document_date=document_date, as_of_date=as_of_date, settlement_lag_days=settlement_lag_days
        )
        if outcome == ReconciliationOutcome.UNSETTLED_WITHIN_LAG:
            settled_within_lag_count += 1
            continue

        grace_period_days = int(default_tolerance_row["grace_period_days"])
        if should_report_unsettled_as_leak(
            document_date=document_date,
            as_of_date=as_of_date,
            settlement_lag_days=settlement_lag_days,
            grace_period_days=grace_period_days,
        ):
            unsettled_beyond_lag_count += 1

    return CashReconciliationResult(
        cash_received=cash_received,
        cash_expected=cash_expected,
        cash_variance=cash_variance,
        tcs_collected=tcs_collected,
        tds_deducted=tds_deducted,
        settled_within_lag_count=settled_within_lag_count,
        unsettled_beyond_lag_count=unsettled_beyond_lag_count,
        dates_missing_count=dates_missing_count,
        formula_version=_FORMULA_VERSION,
        computed_at=computed_at,
    )
