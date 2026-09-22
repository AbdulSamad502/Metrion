"""deterministic-engine.md §5.15.1 `api/compute_metric.py::compute_price_band` —
MetricResult-wrapping tests, mirroring test_compute_price_positioning_api.py's style.
"""

from __future__ import annotations

from datetime import datetime, timezone

from calc_engine.api.compute_metric import compute_price_band
from calc_engine.formulas.price_positioning import CompetitorPrice
from calc_engine.types import Confidence, Paise

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def _prices(values: list[int]) -> list[CompetitorPrice]:
    return [CompetitorPrice(Paise(v), Confidence.DERIVED, f"ref{i}") for i, v in enumerate(values)]


def test_unavailable_returns_single_row_with_reason() -> None:
    rows = compute_price_band(
        product_ref="SKU-1", category="Mice", competitor_prices=_prices([90000, 95000]), computed_at=NOW
    )
    assert len(rows) == 1
    assert rows[0].is_available is False
    assert rows[0].value_paise is None
    assert "INSUFFICIENT_COMPETITOR_PRICES" in (rows[0].unavailable_reason or "")
    assert rows[0].metric_code == "PRICE_BAND"


def test_available_result_emits_all_rows_with_real_engine_result_refs() -> None:
    prices = _prices([85000, 90000, 95000, 105000, 400000])
    rows = compute_price_band(product_ref="SKU-1", category="Mice", competitor_prices=prices, computed_at=NOW)

    # 5 aggregate rows (Q1, Q3, IQR, LOWER_FENCE, UPPER_FENCE, TYPICAL_LOW, TYPICAL_HIGH = 7)
    # + 5 per-price rows = 12.
    assert len(rows) == 12
    assert all(r.metric_code == "PRICE_BAND" for r in rows)
    assert all(r.is_available for r in rows)
    assert len({r.id for r in rows}) == 12  # every row mints its own real engine_result_ref

    q1_row = next(r for r in rows if "Q1 " in r.calculation_basis)
    assert q1_row.value_paise == 90000

    outlier_row = next(r for r in rows if "is_outlier=True" in r.calculation_basis)
    assert outlier_row.value_paise == 400000


def test_result_is_never_part_of_canonical_data_version() -> None:
    rows = compute_price_band(
        product_ref="SKU-1", category=None, competitor_prices=_prices([85000, 90000, 95000]), computed_at=NOW
    )
    assert all(r.canonical_data_version == "non-canonical" for r in rows)


def test_unknown_category_is_recorded_honestly_not_inferred() -> None:
    rows = compute_price_band(
        product_ref="SKU-1", category=None, competitor_prices=_prices([85000, 90000, 95000]), computed_at=NOW
    )
    assert "category=UNKNOWN" in rows[0].calculation_basis
