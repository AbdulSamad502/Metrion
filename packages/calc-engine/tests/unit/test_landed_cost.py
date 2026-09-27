"""landed_cost.py / compute_landed_cost — deterministic-engine.md §5.13.1, §7.2.1."""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from calc_engine.api.compute_metric import compute_landed_cost
from calc_engine.formulas.landed_cost import (
    LandedCostQuote,
    landed_cost_per_unit,
    parse_supplier_quote_adjustment,
)
from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Paise

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def _quote(**overrides: object) -> LandedCostQuote:
    base = dict(
        supplier_name="Acme Traders",
        sku=None,
        unit_cost_paise=Paise(10_000),
        moq=None,
        lead_time_days=None,
        shipping_paise=None,
        payment_terms=None,
        reliability_note=None,
    )
    base.update(overrides)
    return LandedCostQuote(**base)  # type: ignore[arg-type]


# --- parse_supplier_quote_adjustment ---------------------------------------------------------


def test_parse_supplier_quote_adjustment_full_shape():
    entry = parse_supplier_quote_adjustment(
        {
            "supplier_name": "Acme Traders",
            "sku": "SKU-1",
            "unit_cost_paise": 10_000,
            "moq": 50,
            "lead_time_days": 7,
            "shipping_paise": 1_000,
            "payment_terms": "NET30",
            "reliability_note": "consistent on-time deliveries",
        }
    )
    assert entry == LandedCostQuote(
        supplier_name="Acme Traders",
        sku="SKU-1",
        unit_cost_paise=Paise(10_000),
        moq=50,
        lead_time_days=7,
        shipping_paise=Paise(1_000),
        payment_terms="NET30",
        reliability_note="consistent on-time deliveries",
    )


def test_parse_supplier_quote_adjustment_minimal_shape():
    entry = parse_supplier_quote_adjustment({"supplier_name": "Acme Traders", "unit_cost_paise": 5_000})
    assert entry == LandedCostQuote(
        supplier_name="Acme Traders",
        sku=None,
        unit_cost_paise=Paise(5_000),
        moq=None,
        lead_time_days=None,
        shipping_paise=None,
        payment_terms=None,
        reliability_note=None,
    )


def test_parse_supplier_quote_adjustment_missing_unit_cost_raises():
    with pytest.raises(ValueError):
        parse_supplier_quote_adjustment({"supplier_name": "Acme Traders"})


def test_parse_supplier_quote_adjustment_missing_supplier_name_raises():
    with pytest.raises(ValueError):
        parse_supplier_quote_adjustment({"unit_cost_paise": 5_000})


def test_parse_supplier_quote_adjustment_wrong_type_unit_cost_raises():
    with pytest.raises(ValueError):
        parse_supplier_quote_adjustment({"supplier_name": "Acme Traders", "unit_cost_paise": "5000"})
    with pytest.raises(ValueError):
        parse_supplier_quote_adjustment({"supplier_name": "Acme Traders", "unit_cost_paise": 5000.0})


# --- landed_cost_per_unit ---------------------------------------------------------------------


def test_landed_cost_per_unit_no_shipping_returns_unit_cost_unchanged():
    quote = _quote(unit_cost_paise=Paise(12_345), shipping_paise=None)
    for quantity in (1, 2, 100):
        assert landed_cost_per_unit(quote, quantity) == Paise(12_345)


def test_landed_cost_per_unit_divides_shipping_with_half_up_rounding():
    # unit_cost=10000, shipping=1000, quantity=3: 1000/3 = 333.333..., half-up rounds to 333
    # (remainder=1, denom=3, 2*1=2 < 3, so no round-up) -> every unit is quoted the SAME
    # per-unit figure, 10333, never a value that depends on which unit index it is.
    quote = _quote(unit_cost_paise=Paise(10_000), shipping_paise=Paise(1_000))
    expected_shipping_per_unit = round_half_up_paise(Fraction(1_000, 3))
    assert expected_shipping_per_unit == Paise(333)  # confirms the hand-computed value above
    assert landed_cost_per_unit(quote, 3) == Paise(10_000) + expected_shipping_per_unit
    assert landed_cost_per_unit(quote, 3) == Paise(10_333)


def test_landed_cost_per_unit_half_up_rounds_ties_up():
    # shipping=3, quantity=2: 3/2 = 1.5 -> half-up rounds to 2 (remainder=1, denom=2,
    # 2*1=2 >= 2, so round up), matching round_half_up_paise's documented tie-break (§G).
    quote = _quote(unit_cost_paise=Paise(0), shipping_paise=Paise(3))
    assert landed_cost_per_unit(quote, 2) == Paise(2)


def test_landed_cost_per_unit_zero_quantity_raises():
    quote = _quote()
    with pytest.raises(ValueError):
        landed_cost_per_unit(quote, 0)


def test_landed_cost_per_unit_negative_quantity_raises():
    quote = _quote()
    with pytest.raises(ValueError):
        landed_cost_per_unit(quote, -1)


# --- compute_landed_cost -----------------------------------------------------------------------


def test_compute_landed_cost_result_shape():
    quote = _quote(unit_cost_paise=Paise(10_000), shipping_paise=Paise(1_000))
    adjustment_id = uuid4()
    result = compute_landed_cost(
        quote,
        3,
        sku="SKU-1",
        active_adjustment_ids=[adjustment_id],
        computed_at=NOW,
    )
    assert result.metric_code == "LANDED_COST_PER_UNIT"
    assert result.is_available is True
    assert result.value_paise == landed_cost_per_unit(quote, 3).value
    assert result.canonical_data_version == "non-canonical"
    assert isinstance(result.id, UUID)
    assert result.manual_adjustment_set == (str(adjustment_id),)


# --- Hypothesis property tests -----------------------------------------------------------------


@given(
    unit_cost_low=st.integers(min_value=0, max_value=1_000_000),
    unit_cost_delta=st.integers(min_value=0, max_value=1_000_000),
    shipping=st.integers(min_value=0, max_value=100_000),
    quantity=st.integers(min_value=1, max_value=50),
)
def test_landed_cost_per_unit_monotonic_in_unit_cost(unit_cost_low, unit_cost_delta, shipping, quantity):
    quote_low = _quote(unit_cost_paise=Paise(unit_cost_low), shipping_paise=Paise(shipping))
    quote_high = _quote(unit_cost_paise=Paise(unit_cost_low + unit_cost_delta), shipping_paise=Paise(shipping))
    assert landed_cost_per_unit(quote_high, quantity).value >= landed_cost_per_unit(quote_low, quantity).value


@given(
    unit_cost=st.integers(min_value=0, max_value=1_000_000),
    shipping_low=st.integers(min_value=0, max_value=100_000),
    shipping_delta=st.integers(min_value=0, max_value=100_000),
    quantity=st.integers(min_value=1, max_value=50),
)
def test_landed_cost_per_unit_monotonic_in_shipping(unit_cost, shipping_low, shipping_delta, quantity):
    quote_low = _quote(unit_cost_paise=Paise(unit_cost), shipping_paise=Paise(shipping_low))
    quote_high = _quote(unit_cost_paise=Paise(unit_cost), shipping_paise=Paise(shipping_low + shipping_delta))
    assert landed_cost_per_unit(quote_high, quantity).value >= landed_cost_per_unit(quote_low, quantity).value


@given(
    unit_cost=st.integers(min_value=0, max_value=1_000_000),
    shipping=st.integers(min_value=0, max_value=100_000),
    quantity=st.integers(min_value=1, max_value=50),
)
def test_landed_cost_per_unit_sum_exactness_within_rounding_tolerance(unit_cost, shipping, quantity):
    # A single half-up rounding of shipping/quantity has error magnitude <= 0.5 paise per
    # unit (proven: diff = quantity * round_half_up(shipping/quantity) - shipping is exactly
    # `shipping mod quantity` or `quantity - (shipping mod quantity)`, both bounded by
    # `quantity // 2`) -- tighter than the old largest-remainder-allocate tolerance
    # (`quantity - 1`), because every unit now gets the identical, not per-index-varying, figure.
    quote = _quote(unit_cost_paise=Paise(unit_cost), shipping_paise=Paise(shipping))
    per_unit = landed_cost_per_unit(quote, quantity)
    exact_total = unit_cost * quantity + shipping
    approx_total = per_unit.value * quantity
    assert abs(approx_total - exact_total) <= quantity // 2
