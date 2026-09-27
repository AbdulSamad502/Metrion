"""expense_pools.py — deterministic-engine.md §5.6, §5.10, §7.2.1. Confirmed decision (Category
E): absent expense.advertising resolves to zero, not Unavailable — opt-in seller data, not a
cost every line definitely incurred.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest

from calc_engine.formulas.expense_pools import (
    ExpenseBudgetEntry,
    ExpensePoolEntry,
    allocate_account_level_expense_pool,
    check_expense_budget,
    parse_expense_budget_adjustment,
    parse_expense_pool_adjustment,
    resolve_sku_level_expense,
)
from calc_engine.types import Confidence, Paise, ZERO


def test_parse_expense_pool_adjustment_full_shape():
    entry = parse_expense_pool_adjustment({"amount_paise": 10_000, "gst_amount_paise": 1_800, "marketplace": "MEESHO"})
    assert entry == ExpensePoolEntry(Paise(10_000), Paise(1_800), "MEESHO")


def test_parse_expense_pool_adjustment_minimal_shape():
    entry = parse_expense_pool_adjustment({"amount_paise": 5_000})
    assert entry == ExpensePoolEntry(Paise(5_000), None, None)


def test_parse_expense_pool_adjustment_missing_amount_raises():
    with pytest.raises(ValueError):
        parse_expense_pool_adjustment({"gst_amount_paise": 100})


def test_resolve_sku_level_expense_absent_is_zero_not_unavailable():
    # confirmed: absent expense.advertising = zero ad spend, never UNAVAILABLE
    value, confidence = resolve_sku_level_expense(None)
    assert value == ZERO
    assert confidence == Confidence.PROVISIONAL


def test_resolve_sku_level_expense_present_is_manual():
    value, confidence = resolve_sku_level_expense({"amount_paise": 7_500})
    assert value == Paise(7_500)
    assert confidence == Confidence.MANUAL


def test_t14_account_level_ad_spend_allocated_by_net_revenue_share():
    # T14: account-level ad spend ₹10,000 across 3 SKUs, parts sum exactly to ₹10,000 (AC7)
    weights = [("SKU-A", Fraction(1)), ("SKU-B", Fraction(1)), ("SKU-C", Fraction(1))]
    result = allocate_account_level_expense_pool({"amount_paise": 1_000_000}, weights)
    assert sum(p.value for p in result.values()) == 1_000_000
    assert set(result) == {"SKU-A", "SKU-B", "SKU-C"}


def test_t15_ad_spend_with_zero_net_revenue_reported_unallocated_not_dropped():
    # T15: ad spend with zero net revenue in scope -> reported unallocated, not dropped (E19)
    weights = [("SKU-A", Fraction(0)), ("SKU-B", Fraction(0))]
    result = allocate_account_level_expense_pool({"amount_paise": 1_000_000}, weights)
    assert result == {"SKU-A": ZERO, "SKU-B": ZERO}
    assert set(result) == {"SKU-A", "SKU-B"}  # every target still present, never dropped


def test_allocate_account_level_expense_pool_absent_is_zero_for_every_target():
    weights = [("SKU-A", Fraction(1)), ("SKU-B", Fraction(1))]
    result = allocate_account_level_expense_pool(None, weights)
    assert result == {"SKU-A": ZERO, "SKU-B": ZERO}


# --- expense.budget (Feature 2: budget-limit check) ---


def test_parse_expense_budget_adjustment_full_shape():
    entry = parse_expense_budget_adjustment(
        {
            "category": "packaging",
            "amount_paise": 500_000,
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
        }
    )
    assert entry == ExpenseBudgetEntry(
        category="packaging",
        amount_paise=Paise(500_000),
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
    )


def test_parse_expense_budget_adjustment_missing_amount_raises():
    with pytest.raises(ValueError):
        parse_expense_budget_adjustment(
            {"category": "packaging", "period_start": "2026-09-01", "period_end": "2026-09-30"}
        )


def test_parse_expense_budget_adjustment_invalid_category_raises():
    with pytest.raises(ValueError):
        parse_expense_budget_adjustment(
            {
                "category": "not_a_real_category",
                "amount_paise": 500_000,
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
            }
        )


def test_parse_expense_budget_adjustment_end_before_start_raises():
    with pytest.raises(ValueError):
        parse_expense_budget_adjustment(
            {
                "category": "packaging",
                "amount_paise": 500_000,
                "period_start": "2026-09-30",
                "period_end": "2026-09-01",
            }
        )


def test_check_expense_budget_under_budget_not_exceeded():
    result = check_expense_budget(Paise(500_000), Paise(300_000))
    assert result.remaining_paise == Paise(200_000)
    assert result.exceeded is False


def test_check_expense_budget_exact_spend_not_exceeded():
    result = check_expense_budget(Paise(500_000), Paise(500_000))
    assert result.remaining_paise == ZERO
    assert result.exceeded is False


def test_check_expense_budget_exceeded_remaining_is_negative_not_floored():
    result = check_expense_budget(Paise(500_000), Paise(650_000))
    assert result.remaining_paise == Paise(-150_000)  # real overage, never floored to zero
    assert result.exceeded is True
