"""deterministic-engine.md §5.18.3 test series MS1–MS7 (Round 8), plus conservation and determinism properties."""

from __future__ import annotations

import pytest

from calc_engine.formulas import expense_assignment as a
from calc_engine.types import Paise

CAT = {"A": "A", "B": "B", "C": "C", "D": "D"}


def eq(*skus: str) -> a.SkuAssignment:
    return a.SkuAssignment("EQUAL", tuple((s, None) for s in skus))


def ex(**bp: int) -> a.SkuAssignment:
    return a.SkuAssignment("EXPLICIT_SHARES", tuple(bp.items()))


def values(r: a.AssignmentResult) -> dict[str, int]:
    return {k: v.value for k, v in r.assigned.items()}


def test_ms1_an_equal_split_of_an_odd_paise_amount_over_three_skus_sums_exactly() -> None:
    r = a.assign(Paise(10_001), eq("A", "B", "C"), CAT)
    assert sorted(values(r).values()) == [3_333, 3_334, 3_334] and r.assigned_total.value == 10_001 and r.unassigned.value == 0 and r.reason is None
    assert values(r) == {"A": 3_334, "B": 3_334, "C": 3_333}  # the leftover paise go to the first SKUs in order


def test_ms2_explicit_shares_below_ten_thousand_basis_points_leave_the_rest_visibly_unassigned() -> None:
    r = a.assign(Paise(100_000), ex(A=4_000, B=3_000), CAT)
    assert values(r) == {"A": 40_000, "B": 30_000} and r.unassigned.value == 30_000 and r.reason == "SHARES_BELOW_100_PERCENT"
    assert r.assigned_total.value + r.unassigned.value == 100_000


def test_explicit_shares_use_largest_remainder_on_the_assigned_part() -> None:
    r = a.assign(Paise(100), ex(A=3_333, B=3_333, C=3_334), CAT)
    assert r.assigned_total.value == 100 and r.unassigned.value == 0 and sorted(values(r).values()) == [33, 33, 34] and values(r)["C"] == 34


def test_no_basis_assigns_nothing_and_the_data_bases_take_no_basis_points() -> None:
    r = a.assign(Paise(5_000), a.SkuAssignment(None, (("A", None),)), CAT)
    assert r.assigned == {} and r.unassigned.value == 5_000 and r.reason == "BASIS_NOT_SELECTED"
    for basis in ("UNITS", "ORDERS", "NET_REVENUE"):
        assert a.validate(a.SkuAssignment(basis, (("A", None),))) is None  # the data decides the split
        assert a.validate(a.SkuAssignment(basis, (("A", 5_000),))) == "INVALID_ASSIGNMENT"  # basis points belong to EXPLICIT_SHARES only


def test_ms4_no_mapped_sku_leaves_the_whole_amount_unassigned() -> None:
    r = a.assign(Paise(7_000), eq("X", "Y"), CAT)
    assert r.assigned == {} and r.unassigned.value == 7_000 and r.reason == "NO_MAPPED_SKU" and r.unmapped == ("X", "Y")


def test_ms5_an_unmapped_sku_gets_no_share_and_is_returned_for_the_review_queue() -> None:
    r = a.assign(Paise(9_000), eq("A", "B", "X"), CAT)
    assert values(r) == {"A": 4_500, "B": 4_500} and r.unmapped == ("X",) and r.unassigned.value == 0 and r.reason == "UNMAPPED_SKU"  # equal split over the mapped SKUs only
    r2 = a.assign(Paise(10_000), ex(A=5_000, X=5_000), CAT)
    assert values(r2) == {"A": 5_000} and r2.unassigned.value == 5_000 and r2.unmapped == ("X",) and r2.reason == "UNMAPPED_SKU"  # its basis points stay unassigned


@pytest.mark.parametrize("shares", [{"A": 10_001}, {"A": 6_000, "B": 4_001}, {"A": 5_000, "B": 5_000, "C": 1}])
def test_ms7_shares_above_ten_thousand_basis_points_are_rejected(shares) -> None:
    assert a.validate(ex(**shares)) == "SHARES_ABOVE_100_PERCENT"
    r = a.assign(Paise(100), ex(**shares), CAT)
    assert r.assigned == {} and r.unassigned.value == 100 and r.reason == "SHARES_ABOVE_100_PERCENT"  # never computed


@pytest.mark.parametrize(
    "assignment",
    [eq(), a.SkuAssignment("EQUAL", (("A", 5),)), ex(A=0), ex(A=-1), ex(A=True), a.SkuAssignment("EXPLICIT_SHARES", (("A", None),)), a.SkuAssignment("EQUAL", (("A", None), ("A", None))),
     a.SkuAssignment("EQUAL", (("", None),))],
)
def test_malformed_assignments_are_invalid(assignment) -> None:
    assert a.validate(assignment) == "INVALID_ASSIGNMENT"


def test_a_valid_assignment_validates_and_ten_thousand_is_allowed() -> None:
    assert a.validate(eq("A", "B")) is None and a.validate(ex(A=10_000)) is None and a.validate(ex(A=2_500, B=7_500)) is None


def test_a_single_sku_assignment_is_the_plain_manual_tag() -> None:
    r = a.assign(Paise(12_345), eq("A"), CAT)
    assert values(r) == {"A": 12_345} and r.unassigned.value == 0


def test_a_negative_amount_keeps_its_sign_on_every_share_and_conserves() -> None:
    r = a.assign(Paise(-10_001), eq("A", "B", "C"), CAT)
    assert values(r) == {"A": -3_334, "B": -3_334, "C": -3_333} and r.assigned_total.value + r.unassigned.value == -10_001


def test_a_zero_amount_gives_zero_shares() -> None:
    r = a.assign(Paise(0), eq("A", "B"), CAT)
    assert values(r) == {"A": 0, "B": 0} and r.unassigned.value == 0 and r.reason is None


def test_the_result_does_not_depend_on_the_order_the_skus_were_listed() -> None:
    assert values(a.assign(Paise(10_001), eq("C", "A", "B"), CAT)) == values(a.assign(Paise(10_001), eq("A", "B", "C"), CAT))
    assert values(a.assign(Paise(1_001), ex(B=3_333, A=3_333, C=3_334), CAT)) == values(a.assign(Paise(1_001), ex(A=3_333, B=3_333, C=3_334), CAT))


@pytest.mark.parametrize("amount", [0, 1, 2, 3, 7, 99, 100, 101, 12_345, 9_999_999_999_999])
@pytest.mark.parametrize("n", [1, 2, 3, 4, 7])
def test_equal_splits_always_conserve_and_differ_by_at_most_one_paisa(amount, n) -> None:
    skus = [f"S{i}" for i in range(n)]
    r = a.assign(Paise(amount), eq(*skus), {s: s for s in skus})
    vals = list(values(r).values())
    assert sum(vals) + r.unassigned.value == amount and r.unassigned.value == 0 and max(vals) - min(vals) <= 1


@pytest.mark.parametrize("amount", [1, 3, 101, 12_345, 1_000_000_007])
def test_explicit_splits_always_conserve(amount) -> None:
    r = a.assign(Paise(amount), ex(A=1_234, B=2_345, C=3_456), CAT)
    assert r.assigned_total.value + r.unassigned.value == amount and r.unassigned.value >= 0
    exact_total = amount * (1_234 + 2_345 + 3_456) // 10_000
    assert r.assigned_total.value == exact_total  # the assigned part is the exact fraction (floor), split by largest remainder


# ---- the data-driven bases (section 5.18.3 with 5.10.1): NET_REVENUE, UNITS, ORDERS, restricted to the assigned SKUs ----------------------------------------------


def data(basis: str, *skus: str) -> a.SkuAssignment:
    return a.SkuAssignment(basis, tuple((s, None) for s in skus))


def tgt(sku: str, **kw) -> object:
    return a.basis_target(sku, **kw)


def test_net_revenue_splits_in_proportion_to_each_skus_revenue_and_conserves_the_amount() -> None:
    d = {"A": tgt("A", net_revenue=Paise(60_000)), "B": tgt("B", net_revenue=Paise(40_000))}
    r = a.assign(Paise(10_001), data("NET_REVENUE", "A", "B"), CAT, d)
    assert values(r) == {"A": 6_001, "B": 4_000} and r.assigned_total.value + r.unassigned.value == 10_001 and r.unassigned.value == 0 and r.reason is None


def test_units_follow_net_units_sold_less_returned_and_rto() -> None:
    d = {"A": tgt("A", units_sold=10, units_returned=2), "B": tgt("B", units_sold=4, units_returned=0)}  # 8 and 4 net units
    assert values(a.assign(Paise(1_200), data("UNITS", "A", "B"), CAT, d)) == {"A": 800, "B": 400}


def test_orders_follow_distinct_order_counts() -> None:
    d = {"A": tgt("A", order_ids=frozenset({"1", "2", "3"})), "B": tgt("B", order_ids=frozenset({"9"}))}
    assert values(a.assign(Paise(4_000), data("ORDERS", "A", "B"), CAT, d)) == {"A": 3_000, "B": 1_000}


def test_ms3_a_sku_without_quantity_leaves_the_amount_unassigned_with_the_reason_not_zero() -> None:
    d = {"A": tgt("A", units_sold=5, units_returned=0), "B": tgt("B", units_sold=None, units_returned=0)}
    r = a.assign(Paise(9_000), data("UNITS", "A", "B"), CAT, d)
    assert r.assigned == {} and r.unassigned.value == 9_000 and r.reason == "UNITS_UNAVAILABLE"
    missing_return = {"A": tgt("A", units_sold=5, units_returned=None), "B": tgt("B", units_sold=5, units_returned=0)}
    assert a.assign(Paise(9_000), data("UNITS", "A", "B"), CAT, missing_return).reason == "UNITS_UNAVAILABLE"  # an unknown return count is not zero
    assert a.assign(Paise(9_000), data("ORDERS", "A", "B"), CAT, {"A": tgt("A", order_ids=frozenset({"1"}))}).reason == "ORDERS_UNAVAILABLE"
    assert a.assign(Paise(9_000), data("NET_REVENUE", "A"), CAT, {}).unassigned.value == 9_000  # no data at all for the SKU


def test_ms4_a_zero_denominator_leaves_everything_unassigned() -> None:
    d = {"A": tgt("A", units_sold=3, units_returned=3), "B": tgt("B", units_sold=0, units_returned=0)}
    r = a.assign(Paise(5_000), data("UNITS", "A", "B"), CAT, d)
    assert r.assigned == {} and r.unassigned.value == 5_000 and r.reason == "ZERO_DENOMINATOR"


def test_a_sku_with_no_positive_weight_gets_no_share_and_the_rest_share_the_whole_amount() -> None:
    d = {"A": tgt("A", units_sold=6, units_returned=0), "B": tgt("B", units_sold=2, units_returned=2)}
    r = a.assign(Paise(900), data("UNITS", "A", "B"), CAT, d)
    assert values(r) == {"A": 900} and r.unassigned.value == 0


def test_ms5_an_unmapped_sku_gets_no_share_under_a_data_basis_too() -> None:
    d = {"A": tgt("A", net_revenue=Paise(1)), "B": tgt("B", net_revenue=Paise(1))}
    r = a.assign(Paise(1_000), data("NET_REVENUE", "A", "B", "X"), CAT, d)
    assert values(r) == {"A": 500, "B": 500} and r.unmapped == ("X",) and r.reason == "UNMAPPED_SKU"


def test_a_refund_keeps_its_sign_on_every_data_share_and_conserves() -> None:
    d = {"A": tgt("A", units_sold=3, units_returned=0), "B": tgt("B", units_sold=1, units_returned=0)}
    r = a.assign(Paise(-1_001), data("UNITS", "A", "B"), CAT, d)
    assert all(v < 0 for v in values(r).values()) and r.assigned_total.value + r.unassigned.value == -1_001


def test_a_single_sku_under_a_data_basis_takes_the_whole_amount() -> None:
    assert values(a.assign(Paise(777), data("ORDERS", "A"), CAT, {"A": tgt("A", order_ids=frozenset({"1"}))})) == {"A": 777}


@pytest.mark.parametrize("basis", ["NET_REVENUE", "UNITS", "ORDERS"])
def test_the_split_does_not_depend_on_the_order_the_skus_were_listed(basis) -> None:
    d = {"A": tgt("A", net_revenue=Paise(70), units_sold=7, units_returned=0, order_ids=frozenset(map(str, range(7)))),
         "B": tgt("B", net_revenue=Paise(30), units_sold=3, units_returned=0, order_ids=frozenset(map(str, range(3))))}
    assert a.assign(Paise(1_001), data(basis, "A", "B"), CAT, d) == a.assign(Paise(1_001), data(basis, "B", "A"), CAT, d)


@pytest.mark.parametrize("amount", [0, 1, 7, 10_001, -3])
def test_conservation_holds_for_every_data_basis(amount) -> None:
    d = {"A": tgt("A", units_sold=5, units_returned=1), "B": tgt("B", units_sold=3, units_returned=0), "C": tgt("C", units_sold=1, units_returned=0)}
    r = a.assign(Paise(amount), data("UNITS", "A", "B", "C"), CAT, d)
    assert r.assigned_total.value + r.unassigned.value == amount
