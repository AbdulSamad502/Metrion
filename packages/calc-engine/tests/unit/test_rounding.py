"""round_half_up_paise / largest_remainder_allocate — deterministic-engine.md §5.11, D8."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from calc_engine.rounding import largest_remainder_allocate, round_half_up_paise
from calc_engine.types import Paise


def test_round_half_up_positive():
    assert round_half_up_paise(Fraction(25, 10)) == Paise(3)  # 2.5 -> 3
    assert round_half_up_paise(Fraction(24, 10)) == Paise(2)  # 2.4 -> 2


def test_round_half_away_from_zero_for_negatives():
    # confirmed decision (§G): negative amounts round half-AWAY-from-zero, not half-up-toward-zero
    assert round_half_up_paise(Fraction(-25, 10)) == Paise(-3)
    assert round_half_up_paise(Fraction(-24, 10)) == Paise(-2)


def test_largest_remainder_allocate_worked_example():
    weights = [("A", Fraction(1)), ("B", Fraction(1)), ("C", Fraction(1))]
    result = largest_remainder_allocate(Paise(10), weights)
    assert result == {"A": Paise(4), "B": Paise(3), "C": Paise(3)}


def test_largest_remainder_allocate_zero_weight_sum_returns_all_zero():
    weights = [("A", Fraction(0)), ("B", Fraction(0))]
    result = largest_remainder_allocate(Paise(10_000), weights)
    assert result == {"A": Paise(0), "B": Paise(0)}


@given(
    total=st.integers(min_value=-1_000_000, max_value=1_000_000),
    n=st.integers(min_value=1, max_value=12),
)
def test_largest_remainder_allocate_always_sums_to_total(total: int, n: int):
    weights = [(i, Fraction(1)) for i in range(n)]
    result = largest_remainder_allocate(Paise(total), weights)
    assert sum(p.value for p in result.values()) == total  # AC7, unconditionally
