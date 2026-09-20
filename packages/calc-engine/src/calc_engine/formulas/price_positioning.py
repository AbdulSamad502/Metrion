"""Price positioning and repricing scenario — deterministic-engine.md §5.15 (NEW, not deferred).

Pure price-fact arithmetic: no COGS, no fee resolution. Distinct from the deferred
`estimate_competitor_margin_range` (§5.13, competitor-intelligence-agent.md C17) — that
feature answers "what is this competitor's margin, roughly"; this one answers "what is the
price gap, and what would a repriced number look like." Neither is inferred: `seller_price_paise`
is a caller-supplied fact (no live "current listed price" lookup exists anywhere in this
engine), and `competitor_prices` are supplied by CI, always entering as `DERIVED` per the
confidence-boundary rule stated at competitor-intelligence-agent.md §5.1/§5.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Sequence

from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Confidence, Paise, Unavailable, combine_confidence


@dataclass(frozen=True, slots=True)
class CompetitorPrice:
    """One competitor price fact, as CI hands it across the boundary. `confidence` is
    expected to always be DERIVED at this boundary (CI's own spec enforces that on its side);
    this module does not re-enforce it, only propagates whatever confidence it's given
    through the ordinary monotonic-combination rule."""

    value_paise: Paise
    confidence: Confidence
    source_ref: str


class PositionReference(str, Enum):
    AVERAGE = "AVERAGE"
    MIN = "MIN"
    MAX = "MAX"


@dataclass(frozen=True, slots=True)
class PositionGap:
    """Rule 1 (§5.15): gap vs. average/min/max, each as both gap_paise (signed, seller minus
    reference) and gap_pct. `gap_pct` is a Fraction here — unrounded, per rule 5 ("computed
    from unrounded paise, rounded once at presentation") — the caller (api/compute_metric.py)
    is responsible for the single presentation-time rounding.
    """

    reference: PositionReference
    reference_price_paise: Paise
    gap_paise: Paise
    gap_pct: Fraction
    confidence: Confidence


def _average_paise(values: Sequence[Paise]) -> Paise:
    total = sum((v.value for v in values), 0)
    return round_half_up_paise(Fraction(total, len(values)))


def _gap_pct(seller_price_paise: Paise, reference_price_paise: Paise) -> Fraction:
    """(seller - reference) / reference * 100, as an exact Fraction. Division by a zero
    reference is a caller error, not a runtime case this module needs to guard — a zero
    competitor price is itself an `Unavailable`-worthy input the caller should have excluded
    before reaching here (mirrors competitor-intelligence's own delta/compute.py precedent for
    a zero base price)."""
    return Fraction(seller_price_paise.value - reference_price_paise.value, reference_price_paise.value) * 100


def compute_position_gaps(
    seller_price_paise: Paise | Unavailable,
    seller_price_confidence: Confidence,
    competitor_prices: Sequence[CompetitorPrice],
) -> tuple[PositionGap, ...] | Unavailable:
    """Rule 2: UNAVAILABLE — never a fabricated gap — when competitor_prices is empty or
    seller_price_paise is missing. Rule 3: confidence is the least certain of the seller price
    and every competitor price supplied (monotonic combination, data-foundation §7.1)."""
    if isinstance(seller_price_paise, Unavailable):
        return seller_price_paise
    if not competitor_prices:
        return Unavailable(reason="no competitor prices supplied")
    if any(cp.value_paise.value == 0 for cp in competitor_prices):
        return Unavailable(reason="a supplied competitor price is zero — percentage gap is undefined")

    combined_confidence = combine_confidence(
        seller_price_confidence, *(cp.confidence for cp in competitor_prices)
    )
    values = [cp.value_paise for cp in competitor_prices]

    average_paise = _average_paise(values)
    min_paise = min(values, key=lambda p: p.value)
    max_paise = max(values, key=lambda p: p.value)

    gaps = []
    for reference, reference_price in (
        (PositionReference.AVERAGE, average_paise),
        (PositionReference.MIN, min_paise),
        (PositionReference.MAX, max_paise),
    ):
        gaps.append(
            PositionGap(
                reference=reference,
                reference_price_paise=reference_price,
                gap_paise=seller_price_paise - reference_price,
                gap_pct=_gap_pct(seller_price_paise, reference_price),
                confidence=combined_confidence,
            )
        )
    return tuple(gaps)


class RepricingStance(str, Enum):
    MATCH_LOWEST = "MATCH_LOWEST"
    BEAT_LOWEST_BY_PCT = "BEAT_LOWEST_BY_PCT"
    BEAT_LOWEST_BY_PAISE = "BEAT_LOWEST_BY_PAISE"
    MATCH_AVERAGE = "MATCH_AVERAGE"
    MATCH_HIGHEST = "MATCH_HIGHEST"


_STANCES_REQUIRING_PARAM = frozenset({RepricingStance.BEAT_LOWEST_BY_PCT, RepricingStance.BEAT_LOWEST_BY_PAISE})


@dataclass(frozen=True, slots=True)
class RepricingScenario:
    """Rule 1 (§5.15): a single suggested price implied by `stance`, plus the resulting gap
    versus the seller's current price, using the same arithmetic as compute_position_gaps.
    Rule 2: explicitly not margin-aware — no COGS, no fee reference, no profitability
    implication of any kind."""

    suggested_price_paise: Paise
    gap_paise: Paise
    gap_pct: Fraction
    confidence: Confidence


def compute_repricing_scenario(
    seller_price_paise: Paise | Unavailable,
    seller_price_confidence: Confidence,
    competitor_prices: Sequence[CompetitorPrice],
    stance: RepricingStance,
    stance_param: Fraction | Paise | None = None,
) -> RepricingScenario | Unavailable:
    if isinstance(seller_price_paise, Unavailable):
        return seller_price_paise
    if not competitor_prices:
        return Unavailable(reason="no competitor prices supplied")
    if any(cp.value_paise.value == 0 for cp in competitor_prices):
        return Unavailable(reason="a supplied competitor price is zero — percentage gap is undefined")
    if stance in _STANCES_REQUIRING_PARAM and stance_param is None:
        return Unavailable(reason=f"stance {stance.value} requires a stance_param, none supplied")

    combined_confidence = combine_confidence(
        seller_price_confidence, *(cp.confidence for cp in competitor_prices)
    )
    values = [cp.value_paise for cp in competitor_prices]
    lowest = min(values, key=lambda p: p.value)
    highest = max(values, key=lambda p: p.value)
    average = _average_paise(values)

    if stance == RepricingStance.MATCH_LOWEST:
        suggested = lowest
    elif stance == RepricingStance.MATCH_AVERAGE:
        suggested = average
    elif stance == RepricingStance.MATCH_HIGHEST:
        suggested = highest
    elif stance == RepricingStance.BEAT_LOWEST_BY_PAISE:
        assert isinstance(stance_param, Paise)
        suggested = lowest - stance_param
    elif stance == RepricingStance.BEAT_LOWEST_BY_PCT:
        assert isinstance(stance_param, Fraction)
        discount = round_half_up_paise(Fraction(lowest.value) * stance_param / 100)
        suggested = lowest - discount
    else:  # pragma: no cover - exhaustive over RepricingStance
        return Unavailable(reason=f"unhandled stance {stance!r}")

    return RepricingScenario(
        suggested_price_paise=suggested,
        gap_paise=seller_price_paise - suggested,
        gap_pct=_gap_pct(seller_price_paise, suggested),
        confidence=combined_confidence,
    )
