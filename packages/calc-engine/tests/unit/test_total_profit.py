"""Total profit (Option A), `StorageCosts` and the allocation invariant — engine spec §5.8.1 (Round 6/8), expense-tracker AC15/F5/F3, TP1–TP10, A10.

Everything here is a NEW, inactive formula version (`CONTRIBUTION_PROFIT.v2`, `TOTAL_PROFIT.v1`, …). Nothing in this file changes what
`CONTRIBUTION_PROFIT.v1` or the default path computes; the last tests prove that.
"""

from __future__ import annotations

import inspect

import pytest

from calc_engine.definitions.seed_definitions import SEED_DEFINITIONS
from calc_engine.formulas.allocation import AllocationBasis
from calc_engine.formulas.allocation_outcome import AllocationTarget, allocate_with_basis
from calc_engine.formulas.contribution_profit import contribution_profit as contribution_profit_v1
from calc_engine.formulas.expense_profit import (
    CONTRIBUTION_PROFIT_V2,
    ProfitStatement,
    compute_profit_statement,
    contribution_profit_v2,
    pool_split,
)
from calc_engine.types import ZERO, Paise, Unavailable

P = "2026-09-01/2026-09-30"
S = "ALL"


def T(ref, *, rev=None, sold=None, ret=None, orders=None, period=P, scope=S):
    return AllocationTarget(
        ref=ref, data_period=period, data_scope=scope,
        net_revenue=None if rev is None else Paise(rev), units_sold=sold, units_returned=ret,
        order_ids=None if orders is None else frozenset(orders),
    )


STD_TARGETS = [T("A", rev=60_000, sold=6, ret=0, orders={"o1", "o2"}), T("B", rev=40_000, sold=4, ret=1, orders={"o3"})]

NRR, COGS, FEES, SHIP, RTO, OTHER = Paise(100_000), Paise(30_000), Paise(10_000), Paise(5_000), Paise(2_000), Paise(1_000)


def pool(total, basis, targets=STD_TARGETS, *, sku_level=0, period=P, scope=S):
    business = Paise(total - sku_level)
    return pool_split(Paise(total), Paise(sku_level), allocate_with_basis(business, pool_period=period, pool_scope=scope, basis=basis, targets=targets))


def statement(basis_adv=None, basis_sto=None, basis_ovh=None, *, cogs=COGS, targets=STD_TARGETS, adv=7_000, sto=3_000, ovh=9_001, adv_sku=0):
    return compute_profit_statement(
        net_realized_revenue=NRR, cogs=cogs, marketplace_fees=FEES, shipping_logistics=SHIP, return_rto_losses=RTO,
        other_attributed_costs=OTHER,
        advertising=pool(adv, basis_adv, targets, sku_level=adv_sku), storage=pool(sto, basis_sto, targets), overhead=pool(ovh, basis_ovh, targets),
    )


def total_of(s: ProfitStatement) -> int:
    assert isinstance(s.total_profit, Paise)
    return s.total_profit.value


EVERYTHING = NRR.value - COGS.value - FEES.value - SHIP.value - RTO.value - OTHER.value - 7_000 - 3_000 - 9_001


# --- the definitions ----------------------------------------------------------------------------------------------------------------------
def test_total_profit_option_a_includes_all_overhead_allocated_and_unallocated():
    s = statement(AllocationBasis.NET_REVENUE, None, AllocationBasis.UNITS)
    assert total_of(s) == EVERYTHING


def test_relations_between_contribution_fully_allocated_and_total():
    s = statement(AllocationBasis.NET_REVENUE, AllocationBasis.UNITS, AllocationBasis.ORDERS)
    assert s.fully_allocated_profit == s.contribution_profit - s.allocated_overhead
    assert s.total_profit == s.fully_allocated_profit - s.unallocated_advertising - s.unallocated_storage - s.unallocated_overhead


# --- A10: overhead never enters contribution margin ---------------------------------------------------------------------------------------
def test_a10_overhead_is_not_a_parameter_of_contribution_profit_and_changing_it_changes_nothing_there():
    assert "overhead" not in " ".join(inspect.signature(contribution_profit_v2).parameters)
    low = statement(None, None, AllocationBasis.NET_REVENUE, ovh=100)
    high = statement(None, None, AllocationBasis.NET_REVENUE, ovh=900_000)
    assert low.contribution_profit == high.contribution_profit
    assert low.total_profit != high.total_profit  # but it does move total profit


def test_storage_is_a_contribution_term_only_for_its_allocated_or_sku_level_part():
    unalloc = statement(None, None, None)
    alloc = statement(None, AllocationBasis.NET_REVENUE, None)
    assert alloc.contribution_profit == unalloc.contribution_profit - Paise(3_000)
    assert total_of(alloc) == total_of(unalloc)


# --- F5 / TP5: all bases and none give identical total profit -----------------------------------------------------------------------------
@pytest.mark.parametrize("basis", [None, AllocationBasis.NET_REVENUE, AllocationBasis.UNITS, AllocationBasis.ORDERS])
def test_tp5_f5_every_allocation_method_gives_the_same_total_profit(basis):
    assert total_of(statement(basis, basis, basis)) == EVERYTHING


# --- TP1 zero denominator / no sales lines ------------------------------------------------------------------------------------------------
def test_tp1_zero_denominator_and_no_sales_lines_leave_overhead_unallocated_and_total_unchanged():
    zero_rev = [T("A", rev=0, sold=0, ret=0, orders=set()), T("B", rev=0, sold=0, ret=0, orders=set())]
    s = statement(None, None, AllocationBasis.NET_REVENUE, targets=zero_rev, ovh=10_000)
    assert s.unallocated_overhead == Paise(10_000) and s.allocated_overhead == ZERO
    assert s.overhead_reason == "ZERO_DENOMINATOR"
    none_selected = statement(None, None, None, targets=zero_rev, ovh=10_000)
    assert s.total_profit == none_selected.total_profit
    no_sales = statement(None, None, AllocationBasis.NET_REVENUE, targets=[], ovh=10_000)
    assert no_sales.overhead_reason == "NO_REVENUE_FOR_PERIOD" and no_sales.unallocated_overhead == Paise(10_000)
    assert no_sales.total_profit == none_selected.total_profit


# --- TP2 mixed methods ---------------------------------------------------------------------------------------------------------------------
def test_tp2_mixed_methods_equal_the_all_unallocated_case():
    mixed = statement(AllocationBasis.NET_REVENUE, AllocationBasis.UNITS, AllocationBasis.ORDERS)
    assert mixed.total_profit == statement(None, None, None).total_profit


# --- TP3 period mismatch -------------------------------------------------------------------------------------------------------------------
def test_tp3_period_mismatch_leaves_the_pool_unallocated_total_unchanged():
    wrong = [T("A", rev=60_000, period="2026-08-01/2026-08-31"), T("B", rev=40_000)]
    s = statement(None, None, AllocationBasis.NET_REVENUE, targets=wrong)
    assert (s.overhead_reason, s.overhead_detail) == ("INVALID_BASIS", "PERIOD_MISMATCH")
    assert s.total_profit == statement(None, None, None).total_profit


# --- TP4 missing sales / missing units -------------------------------------------------------------------------------------------------------
def test_tp4_missing_units_data_is_unallocated_not_zero_and_total_still_includes_the_pool():
    no_units = [T("A", rev=60_000), T("B", rev=40_000)]
    s = statement(None, None, AllocationBasis.UNITS, targets=no_units)
    assert s.overhead_reason == "UNITS_UNAVAILABLE" and s.unallocated_overhead == Paise(9_001)
    assert s.total_profit == statement(None, None, None).total_profit


# --- TP6 unavailable propagation -----------------------------------------------------------------------------------------------------------
def test_tp6_missing_cogs_makes_contribution_and_total_unavailable_but_unallocated_lines_still_report():
    s = statement(None, None, None, cogs=Unavailable("COGS missing"))
    assert isinstance(s.contribution_profit, Unavailable) and isinstance(s.total_profit, Unavailable)
    assert s.unallocated_overhead == Paise(9_001)


# --- TP7 rounding --------------------------------------------------------------------------------------------------------------------------
def test_tp7_odd_paise_pool_over_three_skus_is_exact_and_total_unchanged():
    three = [T("A", rev=1), T("B", rev=1), T("C", rev=1)]
    s = statement(None, None, AllocationBasis.NET_REVENUE, targets=three, ovh=100)
    assert s.allocated_overhead == Paise(100)
    assert total_of(s) == total_of(statement(None, None, None, ovh=100))


# --- TP8 refund in the pool ----------------------------------------------------------------------------------------------------------------
def test_tp8_a_refund_nets_into_the_pool_and_a_net_credit_is_kept_not_floored():
    s = statement(None, None, AllocationBasis.NET_REVENUE, ovh=10_000 - 2_500)  # cost 10,000 + refund -2,500
    assert s.allocated_overhead == Paise(7_500)
    credit = statement(None, None, AllocationBasis.NET_REVENUE, ovh=-500)
    assert credit.allocated_overhead == Paise(-500)
    assert credit.total_profit == statement(None, None, None, ovh=-500).total_profit


# --- TP9 non-positive weights ---------------------------------------------------------------------------------------------------------------
def test_tp9_non_positive_weights_are_excluded_and_total_unchanged():
    mixed = [T("A", rev=60_000), T("B", rev=0), T("C", rev=-10)]
    s = statement(None, None, AllocationBasis.NET_REVENUE, targets=mixed)
    assert s.allocated_overhead == Paise(9_001)
    assert s.total_profit == statement(None, None, None).total_profit


# --- TP10 reconciliation --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("basis", [None, AllocationBasis.NET_REVENUE, AllocationBasis.UNITS])
def test_tp10_expense_total_equals_pl_expense_lines_plus_unallocated_lines(basis):
    s = statement(basis, basis, basis, adv_sku=2_000)
    expense_total = 7_000 + 3_000 + 9_001 + OTHER.value  # the ledger pools, whatever the allocation
    assert s.pl_expense_lines.value + s.unallocated_lines.value == expense_total


def test_adv_sku_level_part_is_in_contribution_profit_directly():
    s = statement(None, None, None, adv_sku=2_000)
    base = statement(None, None, None, adv_sku=0)
    assert s.contribution_profit == base.contribution_profit - Paise(2_000)
    assert s.total_profit == base.total_profit


# --- pool split guards ----------------------------------------------------------------------------------------------------------------------
def test_pool_split_rejects_an_outcome_for_a_different_pool():
    outcome = allocate_with_basis(Paise(100), pool_period=P, pool_scope=S, basis=None, targets=[])
    with pytest.raises(ValueError):
        pool_split(Paise(500), Paise(0), outcome)


# --- inactive: nothing existing changed -----------------------------------------------------------------------------------------------------
def test_old_results_and_the_default_version_are_unchanged():
    assert CONTRIBUTION_PROFIT_V2 == "CONTRIBUTION_PROFIT.v2"
    assert set(SEED_DEFINITIONS) == {"GROSS_ORDER_VALUE.v1", "SELLER_FUNDED_DISCOUNTS.v1", "NET_REALIZED_REVENUE.v1", "CONTRIBUTION_PROFIT.v1"}
    v1 = contribution_profit_v1(NRR, COGS, FEES, SHIP, Paise(7_000), RTO, OTHER)
    assert v1 == Paise(100_000 - 30_000 - 10_000 - 5_000 - 7_000 - 2_000 - 1_000)
    # v1 still takes the overhead-bearing "other allocated costs" term; v2 does not exist as a parameter there
    assert "other_allocated_costs" in inspect.signature(contribution_profit_v1).parameters
