"""api/compute_metric.py's compute_price_positioning / compute_repricing_scenario wrappers —
engine_result_ref minting, MetricResult shape, UNAVAILABLE wrapping (§5.15)."""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction

from calc_engine.api.compute_metric import compute_price_positioning, compute_repricing_scenario
from calc_engine.formulas.price_positioning import CompetitorPrice, RepricingStance
from calc_engine.types import Confidence, Paise, Unavailable

NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)


def _cp(paise: int) -> CompetitorPrice:
    return CompetitorPrice(value_paise=Paise(paise), confidence=Confidence.DERIVED, source_ref="snap-1")


def test_compute_price_positioning_returns_three_results() -> None:
    results = compute_price_positioning(
        seller_price_paise=Paise(100_000),
        seller_price_confidence=Confidence.VERIFIED,
        competitor_prices=[_cp(80_000), _cp(90_000), _cp(100_000)],
        computed_at=NOW,
    )
    assert len(results) == 3
    assert all(r.metric_code == "PRICE_POSITIONING" for r in results)
    assert all(r.is_available for r in results)
    assert all(r.id is not None for r in results)  # engine_result_ref minted per row
    assert len({r.id for r in results}) == 3  # each row gets its own ref


def test_compute_price_positioning_unavailable_wraps_single_result() -> None:
    results = compute_price_positioning(
        seller_price_paise=Paise(100_000),
        seller_price_confidence=Confidence.VERIFIED,
        competitor_prices=[],
        computed_at=NOW,
    )
    assert len(results) == 1
    assert results[0].is_available is False
    assert results[0].value_paise is None
    assert results[0].unavailable_reason is not None


def test_compute_repricing_scenario_result_shape() -> None:
    result = compute_repricing_scenario(
        seller_price_paise=Paise(100_000),
        seller_price_confidence=Confidence.VERIFIED,
        competitor_prices=[_cp(70_000)],
        stance=RepricingStance.MATCH_LOWEST,
        stance_param=None,
        computed_at=NOW,
    )
    assert result.metric_code == "REPRICING_SCENARIO"
    assert result.is_available is True
    assert result.value_paise == 70_000
    assert "not margin-aware" in result.calculation_basis


def test_the_gap_is_also_stated_as_a_percentage_of_the_sellers_own_price_with_both_denominators_in_the_basis() -> None:
    """₹399 against ₹329: the gap is ₹70.00; 70/399 = 17.54% of the seller's price and 70/329 = 21.28% of the competitor's. Both are exact, rounded once, and labelled."""
    (row, *_rest) = compute_price_positioning(seller_price_paise=Paise(39_900), seller_price_confidence=Confidence.MANUAL, competitor_prices=[_cp(32_900)], computed_at=NOW)
    assert row.value_paise == 7_000
    assert "gap_pct=21.28%" in row.calculation_basis and "gap_pct_of_seller_price=17.54%" in row.calculation_basis
    (cheaper, *_r) = compute_price_positioning(seller_price_paise=Paise(30_000), seller_price_confidence=Confidence.MANUAL, competitor_prices=[_cp(40_000)], computed_at=NOW)
    assert cheaper.value_paise == -10_000 and "gap_pct_of_seller_price=-33.33%" in cheaper.calculation_basis and "gap_pct=-25.00%" in cheaper.calculation_basis
