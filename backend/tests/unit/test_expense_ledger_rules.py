"""Pure rules of the expense ledger (kickoff S3b): the closed category list with default cost classes (Round 9 R9-4), the vendor amount-pattern rule (Q22), the
conservative bounds proposed for owner review (R9-5; derived from existing code where it exists) and the review-state transitions."""

from __future__ import annotations

import pytest

from backend.services import expense_ledger_rules as rules


def test_the_category_list_is_closed_and_maps_to_default_cost_classes():
    assert rules.CATEGORIES["packaging"].cost_class == "DIRECT"
    assert rules.CATEGORIES["inward_freight"].cost_class == "DIRECT"
    assert rules.CATEGORIES["advertising"].cost_class == "ADVERTISING"
    assert rules.CATEGORIES["storage"].cost_class == "STORAGE"
    for overhead in ("operating_overhead", "software", "personnel", "financial_charges", "other"):
        assert rules.CATEGORIES[overhead].cost_class == "OVERHEAD"
    assert "direct_product_costs" not in rules.CATEGORIES  # COGS stays cogs_per_unit, never an expense amount
    assert rules.CATEGORIES["taxes"].treatment == "informational"  # GST / ITC / TCS are not an operating expense (P9)
    assert all(c.treatment in ("incremental", "informational") for c in rules.CATEGORIES.values())
    assert {c.cost_class for c in rules.CATEGORIES.values()} <= {"ADVERTISING", "STORAGE", "OVERHEAD", "DIRECT"}


@pytest.mark.parametrize("vendor", ["Acme Traders", "3M", "7 Eleven", "Studio 54", "Zone 2", "ABC 1999", "Shree Ganesh & Sons"])
def test_q22_ordinary_vendor_names_and_short_numerals_are_allowed(vendor):
    assert rules.vendor_error(vendor) is None


@pytest.mark.parametrize("vendor", [
    "Acme ₹500", "Rs 1200", "Rs. 99", "INR 100", "Acme $20", "paid 1,200.50 to Acme", "Acme 1,200", "Acme 12.50", "Acme 100000", "€5 shop", "£10",
])
def test_q22_a_currency_symbol_or_an_amount_like_number_is_refused_with_an_edit_prompt(vendor):
    msg = rules.vendor_error(vendor)
    assert msg is not None and "vendor" in msg.lower() and "amount" in msg.lower()


def test_text_bounds_and_amount_ceiling_are_the_proposed_conservative_limits():
    assert rules.AMOUNT_MAX_PAISE == 9_999_999_999_999  # 11 rupee digits: the ceiling frontend/lib/pnlText.ts already uses
    assert rules.amount_error(0) is None and rules.amount_error(-4_000) is None and rules.amount_error(rules.AMOUNT_MAX_PAISE) is None
    assert rules.amount_error(rules.AMOUNT_MAX_PAISE + 1) is not None and rules.amount_error(-rules.AMOUNT_MAX_PAISE - 1) is not None
    assert rules.amount_error(True) is not None and rules.amount_error(1.5) is not None and rules.amount_error("5") is not None  # integer paise only
    assert rules.VENDOR_MAX == 120 and rules.DESCRIPTION_MAX == 500 and rules.REASON_MAX == 500
    assert rules.PAGE_SIZE_DEFAULT == 50 and rules.PAGE_SIZE_MAX == 200


def test_review_transitions_voided_is_terminal_and_void_has_its_own_action():
    for a in ("draft", "pending_review", "confirmed"):
        for b in ("draft", "pending_review", "confirmed"):
            assert rules.review_transition_allowed(a, b)
    for b in ("draft", "pending_review", "confirmed", "voided"):
        assert not rules.review_transition_allowed("voided", b)
    assert not rules.review_transition_allowed("confirmed", "voided")  # void goes through the void action, which requires a reason


def test_a_refund_amount_must_be_negative_and_a_cost_positive_or_zero():
    assert rules.cost_amount_error(0) is None and rules.cost_amount_error(5) is None
    assert rules.cost_amount_error(-1) is not None
    assert rules.refund_amount_error(-1) is None and rules.refund_amount_error(0) is not None and rules.refund_amount_error(1) is not None
