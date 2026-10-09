"""Spec §6.33: the form inputs of the two decision playbooks. Strict shape, integer paise, every cost in one of three explicit states, bounds with no default."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from backend.api.v1.ceo import UiActionBody
from backend.ceo.playbook_inputs import InvalidInputs, NewProductInputs, PriceImpactInputs, cost_to_slot, validate_inputs

COMP = str(uuid.uuid4())


def price(**over):
    base = {
        "competitor_url_id": COMP, "sku": "S", "marketplace": "AMAZON", "category": "Home", "fee_type": "referral", "basis": "EXCLUSIVE", "current_price_paise": 49900,
        "candidate_prices_paise": [44900], "shipping": {"state": "NONE_CONFIRMED"}, "advertising": {"state": "UNKNOWN"},
        "return_rto": {"state": "AMOUNT", "amount_paise": 0}, "other": {"state": "AMOUNT", "amount_paise": 500},
    }
    return {**base, **over}


def test_a_complete_form_is_valid_and_costs_map_to_the_routes_amount_or_unknown_shape():
    p = validate_inputs("COMPETITOR_PRICE_IMPACT", price(), max_candidate_prices=3)
    assert isinstance(p, PriceImpactInputs)
    assert cost_to_slot(p.shipping, "x") == {"x_paise": 0, "x_unavailable_reason": None}  # "none (0), I confirm" is a deliberate zero
    assert cost_to_slot(p.advertising, "x") == {"x_paise": None, "x_unavailable_reason": None}  # unknown stays unknown
    assert cost_to_slot(p.other, "x") == {"x_paise": 500, "x_unavailable_reason": None}


@pytest.mark.parametrize("cost", ["shipping", "advertising", "return_rto", "other"])
def test_a_cost_with_no_state_is_invalid_never_a_zero(cost):
    bad = price()
    del bad[cost]
    with pytest.raises(InvalidInputs):
        validate_inputs("COMPETITOR_PRICE_IMPACT", bad, max_candidate_prices=3)


@pytest.mark.parametrize("bad_cost", [{}, {"state": "ZERO"}, {"state": "AMOUNT"}, {"state": "AMOUNT", "amount_paise": -1}, {"state": "AMOUNT", "amount_paise": 1.5}, 0, None, "0"])
def test_a_malformed_cost_is_invalid(bad_cost):
    with pytest.raises(InvalidInputs):
        validate_inputs("COMPETITOR_PRICE_IMPACT", price(shipping=bad_cost), max_candidate_prices=3)


def test_extra_fields_money_floats_and_non_positive_prices_are_refused():
    for over in ({"surprise": 1}, {"current_price_paise": 499.5}, {"current_price_paise": 0}, {"candidate_prices_paise": []}, {"candidate_prices_paise": [0]}, {"basis": "GROSS"},
                 {"gst_rate_pct": "abc"}, {"gst_rate_pct": "-1"}, {"sku": ""}):
        with pytest.raises(InvalidInputs):
            validate_inputs("COMPETITOR_PRICE_IMPACT", price(**over), max_candidate_prices=3)


def test_the_candidate_price_bound_and_duplicates():
    with pytest.raises(InvalidInputs, match="at most 2"):
        validate_inputs("COMPETITOR_PRICE_IMPACT", price(candidate_prices_paise=[1, 2, 3]), max_candidate_prices=2)
    with pytest.raises(InvalidInputs, match="different"):
        validate_inputs("COMPETITOR_PRICE_IMPACT", price(candidate_prices_paise=[10, 10]), max_candidate_prices=5)


def test_a_stance_needs_its_parameter():
    with pytest.raises(InvalidInputs):
        validate_inputs("COMPETITOR_PRICE_IMPACT", price(stance="BEAT_LOWEST_BY_PCT"), max_candidate_prices=3)
    with pytest.raises(InvalidInputs):
        validate_inputs("COMPETITOR_PRICE_IMPACT", price(stance="BEAT_LOWEST_BY_PAISE"), max_candidate_prices=3)
    assert validate_inputs("COMPETITOR_PRICE_IMPACT", price(stance="BEAT_LOWEST_BY_PCT", stance_param_pct="2.5"), max_candidate_prices=3)
    assert validate_inputs("COMPETITOR_PRICE_IMPACT", price(stance="MATCH_LOWEST"), max_candidate_prices=3)


def test_new_product_inputs():
    ok = {"sku": "S", "quantity": 10, "period_start": "2026-07-01", "period_end": "2026-09-30"}
    assert isinstance(validate_inputs("NEW_PRODUCT_DECISION", ok, today=date(2026, 10, 1)), NewProductInputs)
    for over in ({"quantity": 0}, {"quantity": 1.5}, {"period_end": "2026-06-01"}, {"period_end": "2026-10-02"}, {"surprise": True}):
        with pytest.raises(InvalidInputs):
            validate_inputs("NEW_PRODUCT_DECISION", {**ok, **over}, today=date(2026, 10, 1))


def test_an_unknown_playbook_takes_no_form_inputs():
    with pytest.raises(InvalidInputs):
        validate_inputs("PROFIT_DIAGNOSIS", {})


def test_the_error_does_not_echo_the_raw_value():
    with pytest.raises(InvalidInputs) as exc:
        validate_inputs("COMPETITOR_PRICE_IMPACT", price(sku="x" * 500), max_candidate_prices=3)
    assert "x" * 50 not in str(exc.value)


# the API edge
def test_the_api_body_accepts_inputs_only_for_a_form_playbook():
    ok = UiActionBody(kind="PLAYBOOK", key="NEW_PRODUCT_DECISION", inputs={"sku": "S", "quantity": 1, "period_start": "2026-07-01", "period_end": "2026-09-30"})
    assert ok.inputs is not None
    for kind, key in (("ACTION", "cfo.financial_health"), ("PLAYBOOK", "PROFIT_DIAGNOSIS"), ("BUSINESS_STATE", "BS_PNL_LATEST")):
        with pytest.raises(ValidationError):
            UiActionBody(kind=kind, key=key, inputs={})
    with pytest.raises(ValidationError):
        UiActionBody(kind="PLAYBOOK", key="NEW_PRODUCT_DECISION", inputs={"sku": "S"})  # malformed shape is a 422 at the edge
