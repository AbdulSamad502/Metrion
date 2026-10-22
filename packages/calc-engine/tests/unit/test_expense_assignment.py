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


def test_ms3_the_remaining_bases_are_not_offered_here_and_no_basis_assigns_nothing() -> None:
    r = a.assign(Paise(5_000), a.SkuAssignment(None, (("A", None),)), CAT)
    assert r.assigned == {} and r.unassigned.value == 5_000 and r.reason == "BASIS_NOT_SELECTED"
    for basis in ("UNITS", "ORDERS", "NET_REVENUE"):
        assert a.validate(a.SkuAssignment(basis, (("A", None),))) == "INVALID_ASSIGNMENT"  # only the two seller-chosen bases exist in this slice


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
