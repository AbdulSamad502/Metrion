"""deterministic-engine.md §5.15.2 — effective price and buyer total of one observed competitor listing."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from calc_engine.api.competitor_effective_price import compute_competitor_effective_price
from calc_engine.formulas.effective_price import ObservedOffer, compute_effective_price
from calc_engine.types import Paise, Unavailable

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def test_listed_less_discount_is_the_effective_price_and_delivery_makes_the_buyer_total() -> None:
    r = compute_effective_price(listed_paise=299900, visible_discount_paise=30000, delivery_charge_paise=4900)
    assert r.effective == Paise(269900) and r.buyer_total == Paise(274800) and r.discount_observed


def test_no_visible_discount_observed_is_stated_not_guessed() -> None:
    r = compute_effective_price(listed_paise=299900, visible_discount_paise=None, delivery_charge_paise=0)
    assert r.effective == Paise(299900) and not r.discount_observed and r.buyer_total == Paise(299900)  # an observed zero delivery charge is free delivery


def test_a_missing_delivery_charge_is_not_free_delivery() -> None:
    r = compute_effective_price(listed_paise=299900, visible_discount_paise=0, delivery_charge_paise=None)
    assert r.effective == Paise(299900) and r.buyer_total is None and r.delivery is None


@pytest.mark.parametrize("listed,discount,delivery,reason", [
    (None, 0, 0, "LISTED_PRICE_NOT_OBSERVED"), (0, 0, 0, "LISTED_PRICE_NOT_POSITIVE"), (-5, 0, 0, "LISTED_PRICE_NOT_POSITIVE"),
    (100, -1, 0, "VISIBLE_DISCOUNT_NEGATIVE"), (100, 0, -1, "DELIVERY_CHARGE_NEGATIVE"), (100, 100, 0, "DISCOUNTS_EXCEED_LISTED_PRICE"), (100, 150, 0, "DISCOUNTS_EXCEED_LISTED_PRICE"),
])
def test_contradictory_or_missing_inputs_are_unavailable_never_clamped(listed, discount, delivery, reason) -> None:
    r = compute_effective_price(listed_paise=listed, visible_discount_paise=discount, delivery_charge_paise=delivery)
    assert isinstance(r, Unavailable) and r.reason == reason


def test_only_an_unconditional_offer_with_an_amount_is_subtracted() -> None:
    offers = [
        ObservedOffer("COUPON", 10000),
        ObservedOffer("BANK_OFFER", 25000, "10% off with HDFC cards"),
        ObservedOffer("FIRST_ORDER", 15000, "first order only"),
        ObservedOffer("EXTRA_OFF", None),
    ]
    r = compute_effective_price(listed_paise=299900, visible_discount_paise=20000, delivery_charge_paise=0, offers=offers)
    assert r.effective == Paise(269900) and r.unconditional_offer_total == Paise(10000)
    assert [(e.offer.kind, e.reason) for e in r.excluded_offers] == [("BANK_OFFER", "CONDITIONAL"), ("FIRST_ORDER", "CONDITIONAL"), ("EXTRA_OFF", "NO_AMOUNT")]


def test_the_result_is_deterministic_and_integer_only() -> None:
    a = compute_effective_price(listed_paise=299999, visible_discount_paise=1, delivery_charge_paise=1)
    b = compute_effective_price(listed_paise=299999, visible_discount_paise=1, delivery_charge_paise=1)
    assert a == b and isinstance(a.effective.value, int) and a.effective.value == 299998 and a.buyer_total.value == 299999


# ---- the API rows ---------------------------------------------------------------------
def test_rows_are_derived_non_canonical_and_cite_the_source_without_any_margin() -> None:
    rows = compute_competitor_effective_price(competitor_ref="c1", source_ref="snap-1", listed_paise=299900, visible_discount_paise=30000, delivery_charge_paise=4900,
                                              offers=[ObservedOffer("BANK_OFFER", 25000, "HDFC")], computed_at=NOW)
    by = {r.metric_code: r for r in rows}
    assert by["EFFECTIVE_PRICE"].value_paise == 269900 and by["BUYER_TOTAL"].value_paise == 274800
    for r in rows:
        assert r.confidence == "DERIVED" and r.canonical_data_version == "non-canonical" and r.formula_version == "EFFECTIVE_PRICE.v1" and r.input_refs == ("snap-1",)
        assert r.exclusions == ({"kind": "BANK_OFFER", "reason": "CONDITIONAL", "condition": "HDFC"},)
        assert "margin" not in r.calculation_basis.lower().replace("not margin", "")
    assert len({r.id for r in rows}) == 2


def test_an_unavailable_effective_price_is_one_named_row() -> None:
    (row,) = compute_competitor_effective_price(competitor_ref="c1", source_ref="s", listed_paise=None, visible_discount_paise=None, delivery_charge_paise=None, computed_at=NOW)
    assert not row.is_available and row.value_paise is None and row.unavailable_reason == "LISTED_PRICE_NOT_OBSERVED"


def test_a_missing_delivery_charge_gives_an_available_effective_price_and_an_unavailable_total() -> None:
    rows = compute_competitor_effective_price(competitor_ref="c1", source_ref="s", listed_paise=100000, visible_discount_paise=None, delivery_charge_paise=None, computed_at=NOW)
    by = {r.metric_code: r for r in rows}
    assert by["EFFECTIVE_PRICE"].is_available and not by["BUYER_TOTAL"].is_available and by["BUYER_TOTAL"].unavailable_reason == "DELIVERY_CHARGE_NOT_OBSERVED"
