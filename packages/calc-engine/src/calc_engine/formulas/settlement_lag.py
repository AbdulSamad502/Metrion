"""SettlementLagDays aggregate — docs/specs/anomaly-detection.md §6.1/§6.6, and that spec's own
§10 P1 blocker this checkpoint closes: "SETTLEMENT_LAG_DAYS has no period-level aggregate
function anywhere in packages/calc-engine."

**Mean, not median — a disclosed choice, not a silent pick.** §6.1's own row for this series
("An aggregate (mean or median days-to-settle) per period...") leaves the statistic genuinely
open. This module uses the MEAN, for consistency with the anomaly engine's own `Z_SCORE`/
`PERIOD_OVER_PERIOD_DELTA` methods (`calc_engine/anomaly/_stats.py`'s `mean_and_sample_variance`),
which already assume mean/sample-variance baseline behaviour. Using a different statistic
(median) for the series itself while every anomaly method assumes a mean-based baseline would
be an avoidable inconsistency this module deliberately does not introduce. Reconsidering this
requires a spec amendment (anomaly-detection.md §6.1), not a silent change here.

**Negative lag — excluded, disclosed, never included as-is.** A pair whose `settlement_date`
precedes its resolved sales date produces a negative `lag_days`. This is almost certainly a
wrong join or a bad date on one side of the pair, not a genuine "settled before it was sold"
business event — so it is EXCLUDED from the mean rather than folded in. Excluded pairs are
counted (`negative_lag_excluded_count`) and disclosed on the resulting `MetricResult`'s
`calculation_basis` (see `calc_engine.api.compute_metric.compute_settlement_lag_days`), never
silently dropped without a trace.

**Missing-date pairs — same quarantine-and-disclose discipline `calc_engine.api.reconcile`'s own
Decision B already established for Path B.** A pair whose sales_line carries no resolvable date
at all (`invoice_date`/`dispatch_date`/`order_date` all `None`) is skipped, counted
(`dates_missing_count`), never guessed, never crashed on.

Pure `Fraction` arithmetic — no float anywhere in this module (CLAUDE.md, AC4-equivalent). This
module performs no database access of its own (see `calc_engine.repositories.reconciliation_repo.
settlement_lag_pairs_for_run` for the one query that fetches the raw rows this function
consumes) — mirroring `formulas/return_rate.py`'s "pure formula, caller does the fetching"
convention exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping, Sequence

from calc_engine.dates import resolve_document_date
from calc_engine.types import Confidence, Unavailable


@dataclass(frozen=True, slots=True)
class SettlementLagAggregate:
    """The result of aggregating every matched (sales_line, settlement_line) pair's lag_days
    for one reconciliation run. `confidences` carries every contributing pair's own
    `reconciliation_match.confidence` (guaranteed non-empty whenever this dataclass is
    returned at all — see `settlement_lag_days_aggregate`'s own guard) — this is how the
    per-marketplace join-key confidence cap (deterministic-engine.md §5.12.2) flows through to
    `compute_settlement_lag_days`'s `combine_confidence` call, since `reconciliation_match.
    confidence` already carries that cap from `reconcile()`'s own construction."""

    mean_lag_days: Fraction
    pair_count: int
    confidences: tuple[Confidence, ...]
    dates_missing_count: int
    negative_lag_excluded_count: int


def settlement_lag_days_aggregate(
    pairs: Sequence[Mapping[str, Any]],
) -> "SettlementLagAggregate | Unavailable":
    """`pairs` is `reconciliation_repo.settlement_lag_pairs_for_run`'s own raw row shape: each
    row carries `match_confidence`, `invoice_date`, `dispatch_date`, `order_date` (the sales
    side) and `settlement_date` (the settlement side) for one already-matched
    (`MATCHED_EXACT`/`MATCHED_WITHIN_TOLERANCE`) pair — that repository function has already
    filtered to exactly those two outcomes, so this function makes no outcome check of its own.

    `Unavailable` when zero pairs produce a usable, non-negative lag (empty `pairs`, every pair
    missing a date, or every pair's lag negative) — never a fabricated 0-day mean (CLAUDE.md's
    "missing input is UNAVAILABLE, never zero")."""
    lag_days_values: list[int] = []
    confidences: list[Confidence] = []
    dates_missing_count = 0
    negative_lag_excluded_count = 0

    for pair in pairs:
        settlement_date = pair.get("settlement_date")
        if settlement_date is None:
            # Defensive only: `settlement_lag_pairs_for_run` joins against real matched
            # settlement_line rows, which (in practice, today) always carry a non-null
            # settlement_date, because reconcile()'s own settlement_lines_in_period() only ever
            # feeds it rows whose settlement_date already satisfied a BETWEEN filter. This
            # module makes no unchecked assumption about that holding for every possible
            # caller, though — counted the same as a missing sales date, never crashed on.
            dates_missing_count += 1
            continue

        invoice_date = pair.get("invoice_date")
        dispatch_date = pair.get("dispatch_date")
        order_date = pair.get("order_date")
        if invoice_date is None and dispatch_date is None and order_date is None:
            # Decision B (calc_engine.api.reconcile's own docstring), mirrored here: check date
            # presence BEFORE calling resolve_document_date(), never let it raise.
            dates_missing_count += 1
            continue

        resolved_sales_date = resolve_document_date(invoice_date, dispatch_date, order_date)
        lag_days = (settlement_date - resolved_sales_date).days

        if lag_days < 0:
            # Disclosed choice: a negative lag is almost certainly a wrong join or a bad date,
            # not a genuine "settled before it was sold" event — excluded from the mean, never
            # included as-is, never silently dropped without a trace (see this module's own
            # docstring).
            negative_lag_excluded_count += 1
            continue

        lag_days_values.append(lag_days)
        confidences.append(Confidence(pair["match_confidence"]))

    if not lag_days_values:
        return Unavailable(
            reason=(
                "No matched (sales_line, settlement_line) pair for this run produced a usable, "
                f"non-negative settlement lag ({dates_missing_count} pair(s) missing a date, "
                f"{negative_lag_excluded_count} pair(s) excluded for a negative lag)"
            )
        )

    mean_lag_days = Fraction(sum(lag_days_values), len(lag_days_values))

    return SettlementLagAggregate(
        mean_lag_days=mean_lag_days,
        pair_count=len(lag_days_values),
        confidences=tuple(confidences),
        dates_missing_count=dates_missing_count,
        negative_lag_excluded_count=negative_lag_excluded_count,
    )
