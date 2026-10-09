"""Q31: no silent zero in a pricing curve. The three allocated costs are required on the HTTP route, and a cost the seller marked "unknown" makes every
dependent figure UNAVAILABLE (with a named data request) instead of being computed as if it were zero."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest
from calc_engine.formulas.fee_resolution import FeeReference
from calc_engine.formulas.margin_curve import margin_at_price
from calc_engine.types import Paise, Unavailable
from pydantic import ValidationError

from backend.api.v1 import cfo as cfo_routes


def _fee() -> FeeReference:
    return FeeReference(rate_pct=Fraction(10), rate_low_pct=None, rate_high_pct=None, confidence="DERIVED", source="test", version="1")  # type: ignore[call-arg]


def _base(**over):
    args = dict(
        basis="EXCLUSIVE", gst_rate=None, cogs=Paise(30_000), fee_reference=_fee(), shipping_logistics=Paise(1_000), advertising_costs=Paise(2_000),
        return_rto_losses=Paise(500), other_allocated_costs=Paise(300),
    )
    args.update(over)
    return args


def test_known_costs_are_subtracted_exactly():
    # 100000 - 10% fee (10000) - cogs 30000 - ship 1000 - ads 2000 - rto 500 - other 300
    assert margin_at_price(Paise(100_000), **_base()) == Paise(56_200)


@pytest.mark.parametrize("name", ["shipping_logistics", "advertising_costs", "other_allocated_costs"])
def test_an_unknown_allocated_cost_makes_the_margin_unavailable_not_larger(name):
    unknown = Unavailable(reason=f"{name} marked unknown", missing_inputs=(name,))
    out = margin_at_price(Paise(100_000), **_base(**{name: unknown}))
    assert out == unknown  # never a number computed as if the cost were zero


def test_cogs_keeps_its_precedence_over_the_allocated_costs():
    cogs = Unavailable(reason="no cogs", missing_inputs=("cogs_per_unit",))
    ship = Unavailable(reason="no shipping", missing_inputs=("shipping_logistics",))
    assert margin_at_price(Paise(100_000), **_base(cogs=cogs, shipping_logistics=ship)) == cogs


def _body(**over):
    fields = dict(
        sku="S", candidate_prices_paise=[100_000], basis="EXCLUSIVE", marketplace="AMAZON", category="c", fee_type="referral", as_of_date=date(2026, 9, 25),
        shipping_logistics_paise=0, advertising_costs_paise=0, other_allocated_costs_paise=0,
    )
    fields.update(over)
    return fields


@pytest.mark.parametrize("missing", ["shipping_logistics_paise", "advertising_costs_paise", "other_allocated_costs_paise"])
def test_the_route_refuses_a_request_that_omits_an_allocated_cost(missing):
    fields = _body()
    del fields[missing]
    with pytest.raises(ValidationError):
        cfo_routes.PricingCurveHttpRequest(**fields)


def test_a_null_amount_means_unknown_and_carries_the_sellers_reason():
    unknown = cfo_routes._cost_or_unavailable(None, "supplier has not told me", "shipping_logistics")
    assert isinstance(unknown, Unavailable) and unknown.reason == "supplier has not told me" and unknown.missing_inputs == ("shipping_logistics",)
    assert isinstance(cfo_routes._cost_or_unavailable(None, None, "advertising_costs"), Unavailable)
    assert cfo_routes._cost_or_unavailable(0, None, "other_allocated_costs") == Paise(0)  # a deliberately sent zero is an amount
