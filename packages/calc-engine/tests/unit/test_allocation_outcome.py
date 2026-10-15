"""Allocation with an explicit basis (engine spec §5.10, §5.10.1; expense-tracker A1–A10).

No basis is ever defaulted. Weights come from the data the basis names (`NET_REVENUE`, `UNITS` net of returns, `ORDERS` distinct orders per
SKU), every unusable case leaves the pool visibly unallocated with a reason code, and allocated + unallocated always equals the pool.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from calc_engine.formulas.allocation import AllocationBasis
from calc_engine.formulas.allocation_outcome import (
    AllocationOutcome,
    AllocationTarget,
    allocate_with_basis,
)
from calc_engine.types import Confidence, Paise, Unavailable

P = "2026-09-01/2026-09-30"
S = "AMAZON"


def rev(ref: str, paise: int | None) -> AllocationTarget:
    return AllocationTarget(ref=ref, data_period=P, data_scope=S, net_revenue=None if paise is None else Paise(paise))


def run(pool: int, basis, targets, *, period: str = P, scope: str = S) -> AllocationOutcome:
    return allocate_with_basis(Paise(pool), pool_period=period, pool_scope=scope, basis=basis, targets=targets)


def conserved(o: AllocationOutcome) -> bool:
    return sum(v.value for v in o.allocated.values()) + o.unallocated.value == o.pool.value


# --- A1 ---------------------------------------------------------------------------------------------------------------------------------
def test_a1_no_basis_selected_means_no_allocation_and_no_default():
    o = run(10_000, None, [rev("A", 6000), rev("B", 4000)])
    assert o.allocated == {}
    assert o.unallocated == Paise(10_000)
    assert o.reason == "BASIS_NOT_SELECTED"
    assert o.basis is None
    assert conserved(o)


# --- A2 ---------------------------------------------------------------------------------------------------------------------------------
def test_a2_net_revenue_valid_shares_sum_exactly_and_basis_is_stamped():
    o = run(10_000, AllocationBasis.NET_REVENUE, [rev("A", 6000), rev("B", 3000), rev("C", 1000)])
    assert {k: v.value for k, v in o.allocated.items()} == {"A": 6000, "B": 3000, "C": 1000}
    assert o.unallocated == Paise(0)
    assert o.reason is None
    assert o.basis is AllocationBasis.NET_REVENUE
    assert o.confidence is Confidence.DERIVED
    assert conserved(o)


def test_a2_odd_paise_uses_largest_remainder_and_stays_exact():
    o = run(100, AllocationBasis.NET_REVENUE, [rev("A", 1), rev("B", 1), rev("C", 1)])
    assert sorted(v.value for v in o.allocated.values()) == [33, 33, 34]
    assert conserved(o)


def test_target_order_does_not_change_the_result():
    a = run(101, AllocationBasis.NET_REVENUE, [rev("A", 1), rev("B", 1), rev("C", 1)])
    b = run(101, AllocationBasis.NET_REVENUE, [rev("C", 1), rev("A", 1), rev("B", 1)])
    assert a.allocated == b.allocated


# --- A3 ---------------------------------------------------------------------------------------------------------------------------------
def units(ref: str, sold: int | None, returned: int | None) -> AllocationTarget:
    return AllocationTarget(ref=ref, data_period=P, data_scope=S, units_sold=sold, units_returned=returned)


def orders(ref: str, ids: set[str] | None) -> AllocationTarget:
    return AllocationTarget(ref=ref, data_period=P, data_scope=S, order_ids=None if ids is None else frozenset(ids))


def test_a3_units_are_net_of_returns():
    o = run(1000, AllocationBasis.UNITS, [units("A", 10, 0), units("B", 10, 5)])  # net 10 vs 5
    assert {k: v.value for k, v in o.allocated.items()} == {"A": 667, "B": 333}
    assert o.basis is AllocationBasis.UNITS
    assert conserved(o)


def test_a3_orders_are_distinct_orders_per_sku():
    o = run(900, AllocationBasis.ORDERS, [orders("A", {"o1", "o2", "o3"}), orders("B", {"o3"}), orders("C", {"o4", "o4"})])
    # A has 3 distinct orders, B has 1, C has 1 (o4 counted once) -> 3:1:1 of 900
    assert {k: v.value for k, v in o.allocated.items()} == {"A": 540, "B": 180, "C": 180}
    assert conserved(o)


# --- A4 ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "basis,targets,reason",
    [
        (AllocationBasis.NET_REVENUE, [rev("A", 100), rev("B", None)], "BASIS_DATA_UNAVAILABLE"),
        (AllocationBasis.NET_REVENUE, [rev("A", 100), AllocationTarget(ref="B", data_period=P, data_scope=S, net_revenue=Unavailable("x"))], "BASIS_DATA_UNAVAILABLE"),
        (AllocationBasis.UNITS, [units("A", 5, 0), units("B", None, 0)], "UNITS_UNAVAILABLE"),
        (AllocationBasis.UNITS, [units("A", 5, 0), units("B", 5, None)], "UNITS_UNAVAILABLE"),  # a missing return count is not zero
        (AllocationBasis.ORDERS, [orders("A", {"o1"}), orders("B", None)], "ORDERS_UNAVAILABLE"),
    ],
)
def test_a4_missing_or_invalid_data_leaves_the_pool_unallocated_with_a_reason(basis, targets, reason):
    o = run(5_000, basis, targets)
    assert o.allocated == {}
    assert o.unallocated == Paise(5_000)
    assert o.reason == reason
    assert conserved(o)


# --- A5 ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "basis,targets",
    [
        (AllocationBasis.NET_REVENUE, [rev("A", 0), rev("B", -50)]),
        (AllocationBasis.UNITS, [units("A", 0, 0), units("B", 3, 3)]),
        (AllocationBasis.ORDERS, [orders("A", set()), orders("B", set())]),
    ],
)
def test_a5_zero_denominator_is_unallocated_not_a_divide_error(basis, targets):
    o = run(5_000, basis, targets)
    assert o.reason == "ZERO_DENOMINATOR"
    assert o.allocated == {}
    assert o.unallocated == Paise(5_000)


@pytest.mark.parametrize(
    "basis,reason",
    [
        (AllocationBasis.NET_REVENUE, "NO_REVENUE_FOR_PERIOD"),
        (AllocationBasis.UNITS, "UNITS_UNAVAILABLE"),
        (AllocationBasis.ORDERS, "ORDERS_UNAVAILABLE"),
    ],
)
def test_a5_no_sales_lines_at_all(basis, reason):
    o = run(5_000, basis, [])
    assert o.reason == reason
    assert o.unallocated == Paise(5_000)


def test_zero_or_negative_targets_are_excluded_with_a_reason_and_the_rest_is_still_allocated():
    o = run(1000, AllocationBasis.NET_REVENUE, [rev("A", 500), rev("B", 0), rev("C", -20), rev("D", 500)])
    assert set(o.allocated) == {"A", "D"}
    assert o.excluded == {"B": "NON_POSITIVE_WEIGHT", "C": "NON_POSITIVE_WEIGHT"}
    assert o.reason is None
    assert conserved(o)


# --- mismatches -------------------------------------------------------------------------------------------------------------------------
def test_period_mismatch_makes_the_basis_invalid():
    other = AllocationTarget(ref="B", data_period="2026-08-01/2026-08-31", data_scope=S, net_revenue=Paise(100))
    o = run(1000, AllocationBasis.NET_REVENUE, [rev("A", 100), other])
    assert (o.reason, o.detail) == ("INVALID_BASIS", "PERIOD_MISMATCH")
    assert o.unallocated == Paise(1000) and o.allocated == {}


def test_scope_mismatch_makes_the_basis_invalid():
    other = AllocationTarget(ref="B", data_period=P, data_scope="FLIPKART", net_revenue=Paise(100))
    o = run(1000, AllocationBasis.NET_REVENUE, [rev("A", 100), other])
    assert (o.reason, o.detail) == ("INVALID_BASIS", "SCOPE_MISMATCH")


# --- A6 (property) ----------------------------------------------------------------------------------------------------------------------
@settings(max_examples=200, deadline=None)
@given(
    pool=st.integers(min_value=-10_000_000, max_value=10_000_000),
    weights=st.lists(st.integers(min_value=-5_000, max_value=5_000), min_size=0, max_size=8),
    basis=st.sampled_from([None, AllocationBasis.NET_REVENUE]),
)
def test_a6_allocated_plus_unallocated_equals_the_pool_always(pool, weights, basis):
    o = run(pool, basis, [rev(f"S{i}", w) for i, w in enumerate(weights)])
    assert conserved(o)
    if basis is None:
        assert o.allocated == {}


@settings(max_examples=100, deadline=None)
@given(pool=st.integers(min_value=-1_000_000, max_value=1_000_000), sold=st.lists(st.tuples(st.integers(0, 50), st.integers(0, 50)), min_size=1, max_size=6))
def test_a6_units_basis_is_also_conserved(pool, sold):
    o = run(pool, AllocationBasis.UNITS, [units(f"S{i}", s, r) for i, (s, r) in enumerate(sold)])
    assert conserved(o)


# --- A7 reconciliation ------------------------------------------------------------------------------------------------------------------
def test_a7_allocated_plus_unallocated_overhead_equals_the_ledger_overhead_total():
    pools = [(4_000, AllocationBasis.NET_REVENUE), (2_500, AllocationBasis.UNITS), (1_000, None)]
    targets_rev = [rev("A", 300), rev("B", 100)]
    targets_units = [units("A", 3, 1), units("B", 1, 0)]
    outcomes = [
        run(4_000, AllocationBasis.NET_REVENUE, targets_rev),
        run(2_500, AllocationBasis.UNITS, targets_units),
        run(1_000, None, targets_rev),
    ]
    ledger_total = sum(p for p, _ in pools)
    assert sum(sum(v.value for v in o.allocated.values()) + o.unallocated.value for o in outcomes) == ledger_total


# --- A9 ---------------------------------------------------------------------------------------------------------------------------------
def test_a9_a_basis_change_never_mutates_an_earlier_outcome():
    before = run(1000, AllocationBasis.NET_REVENUE, [rev("A", 1), rev("B", 3)])
    snapshot = (dict(before.allocated), before.unallocated, before.basis)
    after = allocate_with_basis(
        Paise(1000), pool_period=P, pool_scope=S, basis=AllocationBasis.UNITS, targets=[units("A", 1, 0), units("B", 1, 0)]
    )
    assert (dict(before.allocated), before.unallocated, before.basis) == snapshot
    assert after.basis is AllocationBasis.UNITS and after.allocated != before.allocated
    with pytest.raises(Exception):
        before.basis = AllocationBasis.ORDERS  # type: ignore[misc]  # frozen: a reported outcome is immutable


def test_the_old_allocator_is_unchanged_and_the_new_one_does_not_default_to_net_revenue():
    from calc_engine.formulas.expense_pools import allocate_account_level_expense_pool

    # existing behaviour kept exactly (its own tests cover it): an absent adjustment still yields ZERO per key
    assert allocate_account_level_expense_pool(None, [("A", Fraction(1))]) == {"A": Paise(0)}
    # the new function has no default basis: omitting it is a TypeError, and None is an explicit "not selected"
    with pytest.raises(TypeError):
        allocate_with_basis(Paise(1), pool_period=P, pool_scope=S, targets=[])  # type: ignore[call-arg]
