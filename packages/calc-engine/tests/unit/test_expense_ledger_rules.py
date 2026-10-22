"""Pure ledger rules (docs/specs/cfo-expense-ledger.md §6): normalisation, identity, duplicate and overlap holds. No database."""

from __future__ import annotations

from datetime import date

import pytest

from calc_engine.expense_ledger import (
    Disposition, LedgerRuleError, NewEntry, decide, entry_identity, is_overlap_like, normalize_category, possible_duplicate_key, validate_new_entry,
)
from calc_engine.formulas.expense_accounting import ExpenseHold

D = date(2026, 10, 5)


def e(**kw) -> NewEntry:
    base = dict(entry_date=D, amount_paise=1_200_000, category="Rent", vendor="Landlord & Co", description="October rent", payment_ref="UTR1")
    base.update(kw)
    return NewEntry(**base)  # type: ignore[arg-type]


def test_identity_is_stable_across_spacing_and_case_but_changes_with_meaning() -> None:
    a = validate_new_entry(e())
    b = validate_new_entry(e(category="  rent ", vendor="landlord   &  co", description="OCTOBER   RENT"))
    assert entry_identity(a) == entry_identity(b)
    for changed in (e(amount_paise=1_200_001), e(entry_date=date(2026, 10, 6)), e(category="Salary"), e(vendor="Other"), e(payment_ref="UTR2"), e(description="Nov rent")):
        assert entry_identity(validate_new_entry(changed)) != entry_identity(a)


def test_identity_ignores_provenance_marketplace_and_gst_so_a_reupload_is_the_same_payment() -> None:
    a = validate_new_entry(e())
    b = validate_new_entry(e(marketplace="meesho", gst_amount_paise=100, gst_treatment="CREDITABLE", source="FILE", source_row_number=7, ingestion_run_id="run-1"))
    assert entry_identity(a) == entry_identity(b) and b.marketplace == "MEESHO"


def test_a_refund_is_a_different_entry_from_the_expense_it_reverses() -> None:
    assert entry_identity(validate_new_entry(e(amount_paise=-1_200_000))) != entry_identity(validate_new_entry(e()))


@pytest.mark.parametrize("bad,msg", [
    (dict(category="   "), "category"), (dict(amount_paise=0), "zero"), (dict(amount_paise=True), "paise"), (dict(marketplace="EBAY"), "marketplace"),
    (dict(paid_date=date(2026, 10, 4)), "paid before"), (dict(gst_treatment="MAYBE", gst_amount_paise=1), "GST treatment"),
    (dict(gst_treatment="CREDITABLE"), "GST amount"), (dict(source="CSV"), "source"),
])
def test_invalid_entries_are_refused_with_a_reason(bad: dict, msg: str) -> None:
    with pytest.raises(LedgerRuleError, match=msg):
        validate_new_entry(e(**bad))


def test_a_missing_category_is_never_defaulted() -> None:
    with pytest.raises(LedgerRuleError):
        normalize_category(None)


def test_decide_exact_duplicate_is_skipped() -> None:
    n = validate_new_entry(e())
    d = decide(n, {entry_identity(n)}, set())
    assert d.disposition is Disposition.SKIP_EXACT_DUPLICATE


def test_same_day_amount_vendor_with_different_text_is_held_as_a_possible_duplicate() -> None:
    first = validate_new_entry(e())
    second = validate_new_entry(e(description="Rent (second payment?)"))
    d = decide(second, {entry_identity(first)}, {possible_duplicate_key(first)})
    assert d.disposition is Disposition.STORE and d.hold is ExpenseHold.POSSIBLE_DUPLICATE


def test_a_different_day_is_not_a_duplicate_even_with_everything_else_equal() -> None:
    first = validate_new_entry(e())
    nxt = validate_new_entry(e(entry_date=date(2026, 11, 5)))
    d = decide(nxt, {entry_identity(first)}, {possible_duplicate_key(first)})
    assert d.disposition is Disposition.STORE and d.hold is ExpenseHold.NONE


@pytest.mark.parametrize("category,like", [("Commission", True), ("Marketplace commission adjustment", True), ("TCS", True), ("Shipping fee", True), ("Rent", False), ("Software", False)])
def test_marketplace_deduction_like_categories_are_held_until_confirmed(category: str, like: bool) -> None:
    assert is_overlap_like(category) is like
    d = decide(validate_new_entry(e(category=category)), set(), set())
    assert d.hold is (ExpenseHold.MAY_OVERLAP_UNCONFIRMED if like else ExpenseHold.NONE)


def test_a_possible_duplicate_outranks_an_overlap_hold() -> None:
    first = validate_new_entry(e(category="Commission"))
    second = validate_new_entry(e(category="Commission", description="again"))
    assert decide(second, {entry_identity(first)}, {possible_duplicate_key(first)}).hold is ExpenseHold.POSSIBLE_DUPLICATE
