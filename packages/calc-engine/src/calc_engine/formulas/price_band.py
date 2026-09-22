"""Price band and outliers — deterministic-engine.md §5.15.1 (NEW — the approved amendment
resolving competitor-intelligence-agent.md D10/Q14, both now closed there).

The percentile distribution of a set of competitor prices for one seller product or
category, with quartile fences and outlier flags. Not margin-aware (rule 12) — identical
boundary to price_positioning.py's two functions. CI's role is exactly the same as it plays
for those: supply the tenant's tracked competitor prices as `DERIVED` inputs and render the
returned rows unchanged. This module never receives, and never needs, a seller price.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from calc_engine.formulas.price_positioning import CompetitorPrice
from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Confidence, Paise, Unavailable, combine_confidence

# Rule 1: the engine floor. A caller-supplied minimum (CI passes
# ci_tenant_config.min_competitors_for_price_band) may raise this but never lower it.
ENGINE_MIN_COMPETITORS_FOR_PRICE_BAND = 3


@dataclass(frozen=True, slots=True)
class PriceBandPoint:
    """One supplied competitor price, flagged for the outlier rule (rule 5) — never dropped,
    per rule 6 ("the engine never silently drops a supplied price")."""

    price: CompetitorPrice
    is_outlier: bool


@dataclass(frozen=True, slots=True)
class PriceBand:
    """Rule 7's output shape, in memory. `typical_low_paise`/`typical_high_paise` are `None`
    only in the (spec-unaddressed, extreme) edge case where every supplied price is an
    outlier — this module never fabricates a "typical range" from zero non-outlier points;
    the caller (api/compute_metric.py) renders that as those two rows simply being absent,
    not as a zero or a guess."""

    q1_paise: Paise
    q3_paise: Paise
    iqr_paise: Paise
    lower_fence_paise: Paise
    upper_fence_paise: Paise
    typical_low_paise: Paise | None
    typical_high_paise: Paise | None
    points: tuple[PriceBandPoint, ...]
    confidence: Confidence


def _percentile(sorted_values: Sequence[int], percentile: int) -> Fraction:
    """Rule 2: linear interpolation between closest ranks — NumPy's default `percentile` /
    SQL `PERCENTILE_CONT`. Computed as an exact `Fraction` throughout (this package's
    established no-float convention, e.g. price_positioning.py's `_gap_pct`) — rounded once,
    by the caller, per rule 8."""
    n = len(sorted_values)
    h = Fraction(percentile, 100) * (n - 1)
    lower_index = math.floor(h)
    frac = h - lower_index
    lower_value = sorted_values[lower_index]
    if lower_index + 1 < n:
        upper_value = sorted_values[lower_index + 1]
        return Fraction(lower_value) + frac * (upper_value - lower_value)
    return Fraction(lower_value)


def compute_price_band(
    competitor_prices: Sequence[CompetitorPrice],
    *,
    min_competitors: int = ENGINE_MIN_COMPETITORS_FOR_PRICE_BAND,
) -> PriceBand | Unavailable:
    """`product_ref`/`category` (the spec's first two parameters) are audit/scoping context
    only — they select *which* competitor_prices the caller supplies, they never enter this
    function's arithmetic, so they are not parameters here; `api/compute_metric.py`'s
    `compute_price_band` (the spec-facing entry point) carries them through into
    `calculation_basis` instead, the same "context that never touches the numbers" pattern
    already used for `product_ref`-shaped identifiers elsewhere in this engine."""
    effective_min = max(ENGINE_MIN_COMPETITORS_FOR_PRICE_BAND, min_competitors)
    if len(competitor_prices) < effective_min:
        return Unavailable(
            reason=(
                f"INSUFFICIENT_COMPETITOR_PRICES: {len(competitor_prices)} supplied, "
                f"{effective_min} required"
            )
        )

    confidence = combine_confidence(*(cp.confidence for cp in competitor_prices))
    values = sorted(cp.value_paise.value for cp in competitor_prices)

    q1 = round_half_up_paise(_percentile(values, 25))
    q3 = round_half_up_paise(_percentile(values, 75))
    iqr = Paise(q3.value - q1.value)
    lower_fence = round_half_up_paise(Fraction(q1.value) - Fraction(3, 2) * Fraction(iqr.value))
    upper_fence = round_half_up_paise(Fraction(q3.value) + Fraction(3, 2) * Fraction(iqr.value))

    points: list[PriceBandPoint] = []
    non_outlier_values: list[int] = []
    for cp in competitor_prices:
        is_outlier = cp.value_paise.value < lower_fence.value or cp.value_paise.value > upper_fence.value
        points.append(PriceBandPoint(price=cp, is_outlier=is_outlier))
        if not is_outlier:
            non_outlier_values.append(cp.value_paise.value)

    typical_low = Paise(min(non_outlier_values)) if non_outlier_values else None
    typical_high = Paise(max(non_outlier_values)) if non_outlier_values else None

    return PriceBand(
        q1_paise=q1,
        q3_paise=q3,
        iqr_paise=iqr,
        lower_fence_paise=lower_fence,
        upper_fence_paise=upper_fence,
        typical_low_paise=typical_low,
        typical_high_paise=typical_high,
        points=tuple(points),
        confidence=confidence,
    )
