"""SKU_CONCENTRATION, MARGIN_STABILITY and BREAK_EVEN_PRICE — deterministic-engine.md §5.17.1 (7), (8), (9).

Exact arithmetic only (`Fraction` and integer paise), no rounding, no clock. Missing inputs are `Unavailable`, thresholds with no
seeded default (`min_periods`) are caller-supplied configuration and `None` means CONFIG_MISSING.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

from calc_engine.formulas.completeness import Completeness
from calc_engine.types import Unavailable


# ------------------------------------------------------------------------------------------------ SKU concentration
@dataclass(frozen=True, slots=True)
class SkuShare:
    sku: str
    nrr_paise: int
    share: Fraction


@dataclass(frozen=True, slots=True)
class SkuConcentration:
    ranked: tuple[SkuShare, ...]  # every eligible SKU, share descending, ties by SKU ascending; shares sum to exactly 1
    top: tuple[SkuShare, ...]
    top_share: Fraction
    total_nrr_paise: int
    excluded_non_positive: tuple[str, ...]
    excluded_unavailable: tuple[str, ...]
    completeness: Completeness


def sku_concentration(nrr_by_sku: Mapping[str, int | None], top_n: int) -> SkuConcentration | Unavailable:
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    eligible = {sku: v for sku, v in nrr_by_sku.items() if v is not None and v > 0}
    non_positive = tuple(sorted(sku for sku, v in nrr_by_sku.items() if v is not None and v <= 0))
    unavailable = tuple(sorted(sku for sku, v in nrr_by_sku.items() if v is None))
    total = sum(eligible.values())
    if not eligible or total <= 0:
        return Unavailable(reason="no SKU has a positive Net Realized Revenue to measure concentration against", missing_inputs=("NET_REALIZED_REVENUE",))
    ranked = tuple(SkuShare(sku, v, Fraction(v, total)) for sku, v in sorted(eligible.items(), key=lambda kv: (-kv[1], kv[0])))
    top = ranked[:top_n]
    return SkuConcentration(
        ranked=ranked, top=top, top_share=sum((s.share for s in top), Fraction(0)), total_nrr_paise=total,
        excluded_non_positive=non_positive, excluded_unavailable=unavailable,
        completeness=Completeness.PARTIAL if (non_positive or unavailable) else Completeness.COMPLETE,
    )


# ------------------------------------------------------------------------------------------------ margin stability
@dataclass(frozen=True, slots=True)
class MarginStability:
    mad: Fraction  # mean absolute deviation of the margin across periods (exactly rational; chosen over standard deviation)
    mean: Fraction
    periods: int
    completeness: Completeness


def margin_stability(margins: Sequence[Fraction | None], min_periods: int | None) -> MarginStability | Unavailable:
    if min_periods is None:
        return Unavailable(reason="CONFIG_MISSING: no minimum number of periods is configured for margin stability", missing_inputs=("min_periods",))
    if min_periods < 2:
        raise ValueError("min_periods must be at least 2")
    if any(m is None for m in margins):
        return Unavailable(reason="at least one period's contribution margin is unavailable", missing_inputs=("CONTRIBUTION_MARGIN_PCT",))
    if len(margins) < min_periods:
        return Unavailable(reason=f"{len(margins)} period(s) of margin history; at least {min_periods} are required", missing_inputs=("margin_history",))
    values = [m for m in margins if m is not None]
    mean = sum(values, Fraction(0)) / len(values)
    mad = sum((abs(v - mean) for v in values), Fraction(0)) / len(values)
    return MarginStability(mad=mad, mean=mean, periods=len(values), completeness=Completeness.COMPLETE)


# ------------------------------------------------------------------------------------------------ break-even price
class BreakEvenKind(str, Enum):
    BRACKET = "BRACKET"  # break-even lies between two evaluated prices
    BELOW_GRID = "BELOW_GRID"  # already non-negative at the lowest price evaluated
    ABOVE_GRID = "ABOVE_GRID"  # still negative at the highest price evaluated


@dataclass(frozen=True, slots=True)
class BreakEven:
    kind: BreakEvenKind
    low_price_paise: int | None  # last evaluated price with a negative margin
    high_price_paise: int | None  # first evaluated price with a non-negative margin
    non_monotonic: bool  # the margin changes sign more than once: the first bracket is reported, with this flag


def break_even_bracket(points: Sequence[tuple[int, int | None]]) -> BreakEven | Unavailable:
    """The bracket at the FIRST negative-to-non-negative step of margin along ascending price. Never a point estimate."""
    if len(points) < 2:
        return Unavailable(reason="break-even needs margins at two or more prices", missing_inputs=("margin_points",))
    by_price: dict[int, int | None] = {}
    for price, margin in points:
        if price in by_price and by_price[price] != margin:
            raise ValueError(f"conflicting margins for price {price}")
        by_price[price] = margin
    pts = sorted(by_price.items())
    if len(pts) < 2:
        return Unavailable(reason="break-even needs margins at two or more distinct prices", missing_inputs=("margin_points",))

    # Walk consecutive *known* points; an unavailable margin between or before them hides where the sign really changes, so the first
    # crossing is only asserted when every price below it has a known margin.
    bracket: tuple[int, int] | None = None
    sign_changes = 0
    unknown_before = False
    prev: tuple[int, int] | None = None  # (price, margin) of the previous known point
    gap_since_prev = False
    for price, margin in pts:
        if margin is None:
            unknown_before = True
            gap_since_prev = True
            continue
        if prev is not None and (prev[1] < 0) != (margin < 0):
            sign_changes += 1
            if prev[1] < 0 and margin >= 0 and bracket is None:
                if gap_since_prev or any(m is None for pr, m in pts if pr < prev[0]):
                    return Unavailable(reason="a price with an unavailable margin precedes the crossing, so the first break-even cannot be asserted",
                                       missing_inputs=("margin_points",))
                bracket = (prev[0], price)
        prev = (price, margin)
        gap_since_prev = False
    known = [m for _, m in pts if m is not None]
    if bracket is not None:
        return BreakEven(BreakEvenKind.BRACKET, bracket[0], bracket[1], non_monotonic=sign_changes > 1)
    if not known:
        return Unavailable(reason="no price has an available margin", missing_inputs=("margin_points",))
    if unknown_before:
        return Unavailable(reason="some prices have an unavailable margin, so the margin's position relative to break-even across the grid cannot be asserted",
                           missing_inputs=("margin_points",))
    kind = BreakEvenKind.BELOW_GRID if known[0] >= 0 else BreakEvenKind.ABOVE_GRID
    return BreakEven(kind, None, None, non_monotonic=sign_changes > 0)
