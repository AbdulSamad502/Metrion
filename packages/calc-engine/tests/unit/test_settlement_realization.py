"""Realisation ratio + estimate (docs/specs/cfo-phase3-scope.md CA3): golden values, boundaries, never a default."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest
from hypothesis import given, strategies as st

from calc_engine.formulas.settlement_realization import estimate_settlement, observed_lag_days, realization_ratio
from calc_engine.types import Unavailable


def test_lower_median_of_observed_ratios_is_an_observed_value() -> None:
    r = realization_ratio([(10_000, 8_000), (10_000, 9_000), (10_000, 7_000)], min_samples=3)
    assert not isinstance(r, Unavailable) and r.ratio == Fraction(4, 5) and r.samples == 3  # sorted .7 .8 .9 -> .8
    even = realization_ratio([(10_000, 9_000), (10_000, 7_000)], min_samples=2)
    assert not isinstance(even, Unavailable) and even.ratio == Fraction(7, 10)  # lower median of .7 .9 is .7, not .8


def test_the_boundary_is_exact_min_samples_passes_one_fewer_does_not() -> None:
    pairs = [(1_000, 800)] * 5
    assert not isinstance(realization_ratio(pairs, 5), Unavailable)
    short = realization_ratio(pairs, 6)
    assert isinstance(short, Unavailable) and "5 settled line(s)" in short.reason


def test_no_configuration_is_unavailable_not_a_guess() -> None:
    r = realization_ratio([(1_000, 800)] * 10, None)
    assert isinstance(r, Unavailable) and "CONFIG_MISSING" in r.reason
    with pytest.raises(ValueError):
        realization_ratio([(1, 1)], 0)


def test_non_positive_gross_pairs_are_ignored_and_a_clawback_is_kept() -> None:
    r = realization_ratio([(0, 500), (-100, 5), (10_000, -2_000), (10_000, 8_000), (10_000, 9_000)], min_samples=3)
    assert not isinstance(r, Unavailable) and r.samples == 3 and r.ratio == Fraction(4, 5)  # -0.2, .8, .9


def test_the_estimate_rounds_half_up_once() -> None:
    r = realization_ratio([(3, 1)] * 3, 3)  # ratio 1/3
    assert not isinstance(r, Unavailable)
    assert estimate_settlement(10_000, r) == 3_333 and estimate_settlement(10_001, r) == 3_334 and estimate_settlement(1, r) == 0
    half = realization_ratio([(2, 1)] * 3, 3)
    assert not isinstance(half, Unavailable) and estimate_settlement(5, half) == 3 and estimate_settlement(-5, half) == -3  # 2.5 -> 3, -2.5 -> -3


def test_lag_drops_a_settlement_before_its_document_date() -> None:
    d = lambda y, m, dd: date(y, m, dd).toordinal()  # noqa: E731
    assert observed_lag_days([(d(2026, 9, 1), d(2026, 9, 8)), (d(2026, 9, 5), d(2026, 9, 5)), (d(2026, 9, 9), d(2026, 9, 1))]) == [7, 0]


@given(st.lists(st.tuples(st.integers(1, 10**8), st.integers(-10**7, 10**8)), min_size=1, max_size=40))
def test_property_the_ratio_is_always_one_of_the_observed_ratios(pairs) -> None:
    r = realization_ratio(pairs, 1)
    assert not isinstance(r, Unavailable)
    assert r.ratio in {Fraction(s, g) for g, s in pairs}
