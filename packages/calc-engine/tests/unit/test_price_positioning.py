"""deterministic-engine.md §5.15 — compute_position_gaps / compute_repricing_scenario."""

from __future__ import annotations

from fractions import Fraction

import pytest

from calc_engine.formulas.price_positioning import (
    CompetitorPrice,
    PositionReference,
    RepricingStance,
    compute_position_gaps,
    compute_repricing_scenario,
)
from calc_engine.types import Confidence, Paise, Unavailable


def _cp(paise: int, confidence: Confidence = Confidence.DERIVED, ref: str = "snap-1") -> CompetitorPrice:
    return CompetitorPrice(value_paise=Paise(paise), confidence=confidence, source_ref=ref)


def test_gaps_computed_against_average_min_max() -> None:
    gaps = compute_position_gaps(
        Paise(100_000), Confidence.VERIFIED, [_cp(80_000), _cp(90_000), _cp(100_000)]
    )
    assert not isinstance(gaps, Unavailable)
    by_ref = {g.reference: g for g in gaps}

    assert by_ref[PositionReference.MIN].reference_price_paise == Paise(80_000)
    assert by_ref[PositionReference.MAX].reference_price_paise == Paise(100_000)
    assert by_ref[PositionReference.AVERAGE].reference_price_paise == Paise(90_000)

    # seller (100,000) vs min (80,000): +20,000 paise, +25%
    assert by_ref[PositionReference.MIN].gap_paise == Paise(20_000)
    assert by_ref[PositionReference.MIN].gap_pct == Fraction(25)

    # seller vs max (100,000): flat
    assert by_ref[PositionReference.MAX].gap_paise == Paise(0)
    assert by_ref[PositionReference.MAX].gap_pct == Fraction(0)


def test_unavailable_when_no_competitor_prices() -> None:
    result = compute_position_gaps(Paise(100_000), Confidence.VERIFIED, [])
    assert isinstance(result, Unavailable)


def test_unavailable_when_seller_price_missing() -> None:
    result = compute_position_gaps(
        Unavailable(reason="seller price not provided"), Confidence.VERIFIED, [_cp(80_000)]
    )
    assert isinstance(result, Unavailable)


def test_unavailable_never_fabricated_on_zero_competitor_price() -> None:
    result = compute_position_gaps(Paise(100_000), Confidence.VERIFIED, [_cp(0)])
    assert isinstance(result, Unavailable)


def test_confidence_is_monotonic_weakest_wins() -> None:
    gaps = compute_position_gaps(
        Paise(100_000),
        Confidence.VERIFIED,
        [_cp(80_000, confidence=Confidence.DERIVED)],
    )
    assert not isinstance(gaps, Unavailable)
    # a CI-sourced (DERIVED) competitor price caps the whole result at DERIVED, even though
    # the seller's own price was VERIFIED — this IS the boundary rule §5.15 references.
    assert all(g.confidence == Confidence.DERIVED for g in gaps)


def test_repricing_match_lowest() -> None:
    result = compute_repricing_scenario(
        Paise(100_000), Confidence.VERIFIED, [_cp(70_000), _cp(90_000)], RepricingStance.MATCH_LOWEST, None
    )
    assert not isinstance(result, Unavailable)
    assert result.suggested_price_paise == Paise(70_000)
    assert result.gap_paise == Paise(30_000)


def test_repricing_beat_lowest_by_pct() -> None:
    result = compute_repricing_scenario(
        Paise(100_000),
        Confidence.VERIFIED,
        [_cp(70_000)],
        RepricingStance.BEAT_LOWEST_BY_PCT,
        Fraction(10),
    )
    assert not isinstance(result, Unavailable)
    # 10% off 70,000 = 7,000 -> suggested 63,000
    assert result.suggested_price_paise == Paise(63_000)


def test_repricing_beat_lowest_by_pct_requires_param() -> None:
    result = compute_repricing_scenario(
        Paise(100_000), Confidence.VERIFIED, [_cp(70_000)], RepricingStance.BEAT_LOWEST_BY_PCT, None
    )
    assert isinstance(result, Unavailable)


def test_repricing_not_margin_aware_no_cogs_input_possible() -> None:
    """Structural check: the function signature has no COGS/fee parameter at all — this test
    exists to make that boundary explicit and catch any future accidental widening."""
    import inspect

    sig = inspect.signature(compute_repricing_scenario)
    assert "cogs" not in sig.parameters
    assert "fee" not in " ".join(sig.parameters).lower()
