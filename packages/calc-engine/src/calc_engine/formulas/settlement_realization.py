"""Settlement realisation ratio and the estimated settlement of an unsettled line (docs/specs/cfo-phase3-scope.md CA3).

A marketplace's net payout for a line is not known until it settles (commissions are deducted on the settlement side). To forecast *cash on
already-sold lines* the engine uses what the marketplace has actually done before: for each earlier line that settled, the ratio
`settled amount / gross item amount`. The **lower median** of those observed ratios (`sorted[(n − 1) // 2]`, an observed value, never an
interpolation) is applied to an unsettled line's gross amount and rounded half-up once, at the end (engine §5.11).

The result is an **estimate**, not a measured fact: it requires at least `min_samples` observed pairs (configuration, no default; `None` ->
`Unavailable(CONFIG_MISSING)`), a marketplace without enough pairs yields `Unavailable`, and callers label every figure built on it ESTIMATED.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Paise, Unavailable


@dataclass(frozen=True, slots=True)
class RealizationRatio:
    ratio: Fraction  # an observed settled/gross value (the lower median)
    samples: int


def realization_ratio(pairs: Sequence[tuple[int, int]], min_samples: int | None) -> RealizationRatio | Unavailable:
    """`pairs` = (gross item amount, settled amount) in paise for lines that have settled. Pairs with a non-positive gross are ignored (a ratio on
    them is meaningless); a negative settled amount (net clawback) is a legitimate observation and kept."""
    if min_samples is None:
        return Unavailable(reason="CONFIG_MISSING: no minimum number of settled lines is configured for the realisation ratio", missing_inputs=("min_samples",))
    if min_samples < 1:
        raise ValueError("min_samples must be at least 1")
    ratios = sorted(Fraction(settled, gross) for gross, settled in pairs if gross > 0)
    if len(ratios) < min_samples:
        return Unavailable(reason=f"{len(ratios)} settled line(s) observed; at least {min_samples} are needed to estimate what an unsettled line will pay out",
                           missing_inputs=("settled_lines",))
    return RealizationRatio(ratios[(len(ratios) - 1) // 2], len(ratios))


def estimate_settlement(gross_item_amount_paise: int, ratio: RealizationRatio) -> int:
    """gross × ratio, rounded half-up once (half-away-from-zero for negatives). An estimate: callers must label it so."""
    return round_half_up_paise(Fraction(gross_item_amount_paise) * ratio.ratio).value


def observed_lag_days(document_dates_and_settlement_dates: Sequence[tuple[int, int]]) -> list[int]:
    """Whole days between a line's document date and its settlement date, given as ordinal day numbers (`date.toordinal()`); a settlement before the
    document date is a data defect and is dropped here rather than turned into a negative lag."""
    return [s - d for d, s in document_dates_and_settlement_dates if s >= d]


__all__ = ["RealizationRatio", "realization_ratio", "estimate_settlement", "observed_lag_days", "Paise"]
