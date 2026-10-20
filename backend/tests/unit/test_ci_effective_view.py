"""C44 / deterministic-engine.md 5.15.2 — the dashboard only reshapes Brain 1's rows; it computes nothing."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.services.ci_workspace import effective_price_view
from calc_engine.api.competitor_effective_price import compute_competitor_effective_price
from calc_engine.formulas.effective_price import ObservedOffer

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def _rows(**kw):
    base = dict(competitor_ref="c1", source_ref="s1", listed_paise=299900, visible_discount_paise=30000, delivery_charge_paise=4900, offers=[], computed_at=NOW)
    base.update(kw)
    return compute_competitor_effective_price(**base)


def test_the_view_carries_each_figure_with_its_engine_ref() -> None:
    rows = _rows(offers=[ObservedOffer("COUPON", 10000), ObservedOffer("BANK_OFFER", 25000, "HDFC")])
    view = effective_price_view(rows, delivery_paise=4900, offers=[{"kind": "COUPON", "amount_paise": 10000, "condition_text": None}, {"kind": "BANK_OFFER", "amount_paise": 25000, "condition_text": "HDFC"}])
    assert view["effective"]["valuePaise"] == 259900 and view["buyerTotal"]["valuePaise"] == 264800  # 2999 - 300 - 100, + 49
    assert view["effective"]["engineResultRef"] and view["effective"]["engineResultRef"] != view["buyerTotal"]["engineResultRef"]
    assert view["excludedOffers"] == [{"kind": "BANK_OFFER", "reason": "CONDITIONAL"}]
    assert [o["conditional"] for o in view["offers"]] == [False, True]


def test_unconfirmed_delivery_leaves_the_total_unavailable_with_its_reason() -> None:
    view = effective_price_view(_rows(delivery_charge_paise=None), delivery_paise=None, offers=[])
    assert view["effective"]["isAvailable"] and not view["buyerTotal"]["isAvailable"] and view["buyerTotal"]["unavailableReason"] == "DELIVERY_CHARGE_NOT_OBSERVED"
    assert view["deliveryChargePaise"] is None


def test_contradictory_inputs_are_unavailable_not_a_number() -> None:
    view = effective_price_view(_rows(listed_paise=10000, visible_discount_paise=10000), delivery_paise=None, offers=[])
    assert not view["effective"]["isAvailable"] and view["effective"]["valuePaise"] is None and view["effective"]["unavailableReason"] == "DISCOUNTS_EXCEED_LISTED_PRICE"
