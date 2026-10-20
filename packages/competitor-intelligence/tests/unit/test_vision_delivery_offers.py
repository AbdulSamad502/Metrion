"""C44 — the extractor reads delivery charge and offers as plain, structural records; absence is never zero; conditional offers stay conditional."""

from __future__ import annotations

import json

import pytest

from competitor_intelligence.evidence.vision_extractor import _parse_delivery, _parse_offers, fields_from_reply
from competitor_intelligence.intake.policy import AskReason, FieldAction, decide_field, is_consequential
from competitor_intelligence.types import Confidence


@pytest.mark.parametrize("raw,expected", [("FREE", 0), ("Free delivery", 0), ("₹49", 4900), ("Rs. 40.50", 4050), (49, 4900), ("₹49 or ₹99", None), (None, None), ("", None), ("varies", None), (True, None)])
def test_delivery_charge_free_is_an_observed_zero_and_absence_is_not_zero(raw, expected) -> None:
    assert _parse_delivery(raw) == expected


def test_offers_are_kept_as_short_structural_records() -> None:
    offers = _parse_offers([
        {"kind": "coupon", "amount": "₹100"},
        {"kind": "BANK_OFFER", "amount": "250", "condition": "  with   HDFC cards "},
        {"kind": "weird", "condition": "first order only"},
        {"kind": "COUPON"},  # nothing usable: dropped
        "not an object",
    ])
    assert offers == [
        {"kind": "COUPON", "amount_paise": 10000, "condition_text": None},
        {"kind": "BANK_OFFER", "amount_paise": 25000, "condition_text": "with HDFC cards"},
        {"kind": "OTHER", "amount_paise": None, "condition_text": "first order only"},
    ]


def test_offers_are_capped_and_long_conditions_truncated() -> None:
    many = [{"kind": "COUPON", "amount": str(10 + i)} for i in range(9)]
    assert len(_parse_offers(many)) == 5
    assert len(_parse_offers([{"kind": "OTHER", "condition": "x" * 500}])[0]["condition_text"]) == 120
    assert _parse_offers("a coupon") == [] and _parse_offers(None) == []


def test_a_reply_with_delivery_and_offers_yields_those_fields() -> None:
    reply = json.dumps({"listed_price": "2699", "availability": "In stock", "delivery_charge": "FREE", "offers": [{"kind": "COUPON", "amount": "100"}]})
    fields = {f.field_name: f.value for f in fields_from_reply(reply)}
    assert fields["delivery_charge_paise"] == 0 and fields["offers"] == [{"kind": "COUPON", "amount_paise": 10000, "condition_text": None}]


def test_a_reply_without_them_has_no_such_fields_so_they_stay_unknown() -> None:
    fields = {f.field_name for f in fields_from_reply(json.dumps({"listed_price": "2699", "availability": "In stock"}))}
    assert "delivery_charge_paise" not in fields and "offers" not in fields


def test_delivery_and_offers_feed_brain_1_so_a_vision_read_must_be_confirmed() -> None:
    assert is_consequential("delivery_charge_paise") and is_consequential("offers")
    for name in ("delivery_charge_paise", "offers"):
        d = decide_field(name, source=Confidence.VISION_EXTRACTED, present=True)
        assert d.action is FieldAction.ASK_SELLER and d.reason is AskReason.CONSEQUENTIAL_FIELD
        assert decide_field(name, source=Confidence.SELLER_ENTERED, present=True).action is FieldAction.STORE
        assert decide_field(name, source=None, present=False).action is FieldAction.LEAVE_UNKNOWN  # absence is unknown, not asked unprompted
