"""Golden tests for profit_bridge + check_additive (deterministic-engine.md §5.17)."""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from calc_engine.formulas.identities import check_additive
from calc_engine.formulas.profit_bridge import BRIDGE_COMPONENTS, profit_bridge
from calc_engine.types import Unavailable


def _cp(c: dict[str, int]) -> int:
    """Test-side oracle for Contribution Profit from components (engine §5.8's definition)."""
    signs = dict(BRIDGE_COMPONENTS)
    return sum(signs[k] * v for k, v in c.items())


A = {"NET_REALIZED_REVENUE": 1_000_000, "COGS": 400_000, "MARKETPLACE_FEES": 150_000, "SHIPPING_LOGISTICS": 80_000,
     "ADVERTISING_COSTS": 50_000, "RETURN_RTO_LOSSES": 30_000, "OTHER_ALLOCATED_COSTS": 20_000}
B = {"NET_REALIZED_REVENUE": 950_000, "COGS": 390_000, "MARKETPLACE_FEES": 168_000, "SHIPPING_LOGISTICS": 82_000,
     "ADVERTISING_COSTS": 75_000, "RETURN_RTO_LOSSES": 62_000, "OTHER_ALLOCATED_COSTS": 20_000}


def test_golden_bridge_reconciles_exactly() -> None:
    r = profit_bridge(cp_a=_cp(A), cp_b=_cp(B), components_a=A, components_b=B)
    assert not isinstance(r, Unavailable)
    assert _cp(A) == 270_000 and _cp(B) == 153_000
    assert r.delta_paise == -117_000
    assert r.reconciles and r.other_paise == 0
    assert sum(d.effect_paise for d in r.drivers) == r.delta_paise


def test_drivers_ranked_by_absolute_effect_then_code() -> None:
    r = profit_bridge(cp_a=_cp(A), cp_b=_cp(B), components_a=A, components_b=B)
    assert not isinstance(r, Unavailable)
    effects = [abs(d.effect_paise) for d in r.drivers]
    assert effects == sorted(effects, reverse=True)
    # The largest verified drivers in this fixture are return/RTO losses (-32,000) and ads (-25,000).
    assert r.drivers[0].component_code == "NET_REALIZED_REVENUE"  # -50,000
    assert {d.component_code: d.effect_paise for d in r.drivers}["RETURN_RTO_LOSSES"] == -32_000
    assert {d.component_code: d.effect_paise for d in r.drivers}["ADVERTISING_COSTS"] == -25_000


def test_incomplete_bridge_surfaces_nonzero_other() -> None:
    # CP_B is 10,000 lower than its components explain -> a component feeding CP is missing from the bridge.
    r = profit_bridge(cp_a=_cp(A), cp_b=_cp(B) - 10_000, components_a=A, components_b=B)
    assert not isinstance(r, Unavailable)
    assert r.other_paise == -10_000 and not r.reconciles


def test_unavailable_period_or_component_is_unavailable_never_zero() -> None:
    assert isinstance(profit_bridge(cp_a=None, cp_b=1, components_a=A, components_b=B), Unavailable)
    assert isinstance(profit_bridge(cp_a=1, cp_b=None, components_a=A, components_b=B), Unavailable)
    b_missing = {**B, "ADVERTISING_COSTS": None}
    r = profit_bridge(cp_a=_cp(A), cp_b=_cp(B), components_a=A, components_b=b_missing)  # type: ignore[arg-type]
    assert isinstance(r, Unavailable) and "ADVERTISING_COSTS" in r.missing_inputs


@given(
    st.fixed_dictionaries({k: st.integers(min_value=-10**9, max_value=10**9) for k, _ in BRIDGE_COMPONENTS}),
    st.fixed_dictionaries({k: st.integers(min_value=-10**9, max_value=10**9) for k, _ in BRIDGE_COMPONENTS}),
)
def test_property_bridge_always_reconciles_when_cp_follows_definition(a: dict[str, int], b: dict[str, int]) -> None:
    r = profit_bridge(cp_a=_cp(a), cp_b=_cp(b), components_a=a, components_b=b)
    assert not isinstance(r, Unavailable)
    assert r.reconciles
    assert sum(d.effect_paise for d in r.drivers) == r.delta_paise


def test_additive_exact_and_difference() -> None:
    ok = check_additive({"AMAZON": 100, "FLIPKART": 250, "MEESHO": -50}, 300)
    assert ok.ok and ok.sum_of_parts_paise == 300 and ok.difference_paise == 0
    bad = check_additive({"AMAZON": 100, "FLIPKART": 250}, 351)
    assert not bad.ok and bad.difference_paise == 1


def test_additive_unavailable_part_is_not_ok_and_is_named() -> None:
    r = check_additive({"AMAZON": 100, "MEESHO": None}, 100)
    assert not r.ok and r.unavailable_parts == ("MEESHO",) and r.difference_paise is None


def test_additive_unavailable_whole_with_parts_is_not_ok() -> None:
    assert not check_additive({"AMAZON": 100}, None).ok
    assert check_additive({}, None).ok  # vacuous


@pytest.mark.parametrize("whole", [0, -5])
def test_additive_zero_and_negative_totals(whole: int) -> None:
    assert check_additive({"A": whole}, whole).ok


def test_unexplained_share_exact_fraction_and_zero_delta() -> None:
    from fractions import Fraction

    from calc_engine.formulas.identities import unexplained_share

    assert unexplained_share(-100_000, -10_000) == Fraction(1, 10)
    assert unexplained_share(50, 0) == Fraction(0)
    assert unexplained_share(0, 0) is None
