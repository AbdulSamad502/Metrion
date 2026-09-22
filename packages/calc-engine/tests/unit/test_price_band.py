"""deterministic-engine.md §5.15.1 `compute_price_band` — formula-level tests, matching the
spec's own worked examples (T31-T34) exactly. Mirrors test_price_positioning.py's style.
"""

from __future__ import annotations

from calc_engine.formulas.price_band import (
    ENGINE_MIN_COMPETITORS_FOR_PRICE_BAND,
    compute_price_band,
)
from calc_engine.formulas.price_positioning import CompetitorPrice
from calc_engine.types import Confidence, Paise, Unavailable


def _prices(values: list[int], confidence: Confidence = Confidence.DERIVED) -> list[CompetitorPrice]:
    return [CompetitorPrice(Paise(v), confidence, f"ref{i}") for i, v in enumerate(values)]


class TestInsufficientCompetitorPrices:
    def test_two_prices_is_unavailable(self) -> None:
        # T31: 2 supplied, 3 required — no band values returned.
        result = compute_price_band(_prices([90000, 95000]))
        assert isinstance(result, Unavailable)
        assert "INSUFFICIENT_COMPETITOR_PRICES" in result.reason
        assert "2 supplied" in result.reason
        assert "3 required" in result.reason

    def test_zero_prices_is_unavailable(self) -> None:
        result = compute_price_band([])
        assert isinstance(result, Unavailable)

    def test_engine_floor_cannot_be_lowered_below_three(self) -> None:
        # Rule 1: configuration may raise the minimum but never lower it below the engine's
        # floor of 3 — passing min_competitors=1 must not let 2 supplied prices pass.
        result = compute_price_band(_prices([90000, 95000]), min_competitors=1)
        assert isinstance(result, Unavailable)
        assert "3 required" in result.reason

    def test_configured_minimum_above_engine_floor_is_honoured(self) -> None:
        result = compute_price_band(_prices([90000, 95000, 100000]), min_competitors=5)
        assert isinstance(result, Unavailable)
        assert "5 required" in result.reason


class TestWorkedExample:
    """T32 — the spec's own worked example, reproduced exactly."""

    def test_five_prices_with_one_outlier(self) -> None:
        band = compute_price_band(_prices([85000, 90000, 95000, 105000, 400000]))
        assert not isinstance(band, Unavailable)

        assert band.q1_paise == Paise(90000)
        assert band.q3_paise == Paise(105000)
        assert band.iqr_paise == Paise(15000)
        assert band.lower_fence_paise == Paise(67500)
        assert band.upper_fence_paise == Paise(127500)
        assert band.typical_low_paise == Paise(85000)
        assert band.typical_high_paise == Paise(105000)

        outliers = {p.price.value_paise.value: p.is_outlier for p in band.points}
        assert outliers[400000] is True
        assert outliers[85000] is False
        assert outliers[90000] is False
        assert outliers[95000] is False
        assert outliers[105000] is False

    def test_outliers_still_participate_in_quartile_calculation(self) -> None:
        # Rule 6: Q1/Q3 are computed from the FULL set including the outlier — removing it
        # would change Q1/Q3 (a pre-filtered calculation is exactly what's forbidden).
        with_outlier = compute_price_band(_prices([85000, 90000, 95000, 105000, 400000]))
        without_outlier = compute_price_band(_prices([85000, 90000, 95000, 105000]))
        assert not isinstance(with_outlier, Unavailable)
        assert not isinstance(without_outlier, Unavailable)
        assert with_outlier.q1_paise != without_outlier.q1_paise or with_outlier.q3_paise != without_outlier.q3_paise

    def test_outlier_is_never_dropped_from_the_full_distribution(self) -> None:
        band = compute_price_band(_prices([85000, 90000, 95000, 105000, 400000]))
        assert not isinstance(band, Unavailable)
        assert len(band.points) == 5


class TestReproducibility:
    def test_identical_input_produces_identical_band(self) -> None:
        # T33: byte-identical results for a fixed input tuple.
        prices = _prices([85000, 90000, 95000, 105000, 400000])
        band1 = compute_price_band(prices)
        band2 = compute_price_band(prices)
        assert not isinstance(band1, Unavailable)
        assert not isinstance(band2, Unavailable)
        assert band1.q1_paise == band2.q1_paise
        assert band1.q3_paise == band2.q3_paise
        assert band1.lower_fence_paise == band2.lower_fence_paise
        assert band1.upper_fence_paise == band2.upper_fence_paise


class TestConfidence:
    def test_result_confidence_is_derived_when_every_input_is_derived(self) -> None:
        # T34: never VERIFIED or PROVISIONAL — the only case CI can produce.
        band = compute_price_band(_prices([85000, 90000, 95000]))
        assert not isinstance(band, Unavailable)
        assert band.confidence == Confidence.DERIVED

    def test_confidence_is_monotonic_weakest_input_wins(self) -> None:
        prices = [
            CompetitorPrice(Paise(85000), Confidence.DERIVED, "ref0"),
            CompetitorPrice(Paise(90000), Confidence.MANUAL, "ref1"),
            CompetitorPrice(Paise(95000), Confidence.DERIVED, "ref2"),
        ]
        band = compute_price_band(prices)
        assert not isinstance(band, Unavailable)
        assert band.confidence == Confidence.MANUAL


class TestAllOutliersEdgeCase:
    def test_identical_prices_produce_zero_iqr_and_no_outliers(self) -> None:
        # A degenerate but valid case: IQR=0 makes the fences equal Q1/Q3 exactly, and since
        # no value is strictly less/greater than an equal fence, nothing is flagged an
        # outlier — this is the correct, not a fabricated, outcome of the locked formula.
        band = compute_price_band(_prices([90000, 90000, 90000]))
        assert not isinstance(band, Unavailable)
        assert band.iqr_paise == Paise(0)
        assert all(not p.is_outlier for p in band.points)
        assert band.typical_low_paise is not None
        assert band.typical_high_paise is not None
