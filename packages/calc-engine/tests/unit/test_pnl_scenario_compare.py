"""The what-if comparison (calculator.md §14): the change between two hypothetical scenarios is an engine figure, never browser arithmetic; a missing figure on either
side is "not available", never zero; inputs are not mutated."""

from __future__ import annotations

from dataclasses import replace

from calc_engine.formulas.pnl_scenario import EMPTY, calculate_scenario, compare_results, set_
from tests.unit.test_pnl_scenario import base_detailed, rupees


def test_a_cheaper_product_raises_profit_by_exactly_the_cost_saved_before_gst_effects() -> None:
    base_in = base_detailed()
    what_in = replace(base_in, selling_price=set_(rupees(1500)))
    base, what = calculate_scenario(base_in), calculate_scenario(what_in)
    c = compare_results(base, what)
    assert c.per_kept_change is not None and c.per_kept_change.value == what.per_kept.contribution.value - base.per_kept.contribution.value
    assert c.monthly_change.value == what.monthly.contribution.value - base.monthly.contribution.value
    assert c.margin_change_bps == what.metrics.contribution_margin_bps - base.metrics.contribution_margin_bps
    assert c.per_kept_change.value != 0


def test_the_same_scenario_has_a_real_zero_change() -> None:
    r = calculate_scenario(base_detailed())
    c = compare_results(r, calculate_scenario(base_detailed()))
    assert (c.per_kept_change.value, c.per_placed_change.value, c.margin_change_bps) == (0, 0, 0)


def test_an_incomplete_side_gives_no_change_not_zero() -> None:
    good = calculate_scenario(base_detailed())
    incomplete = calculate_scenario(replace(base_detailed(), selling_price=EMPTY))
    for c in (compare_results(good, incomplete), compare_results(incomplete, good)):
        assert c.per_kept_change is None and c.per_placed_change is None and c.monthly_change is None and c.margin_change_bps is None


def test_a_missing_monthly_orders_leaves_only_the_monthly_change_unavailable() -> None:
    good = calculate_scenario(base_detailed())
    no_orders = calculate_scenario(replace(base_detailed(), monthly_orders=EMPTY))
    c = compare_results(good, no_orders)
    assert c.monthly_change is None and c.per_kept_change is not None


def test_the_comparison_does_not_touch_its_inputs() -> None:
    a, b = calculate_scenario(base_detailed()), calculate_scenario(replace(base_detailed(), product_cost=set_(rupees(300))))
    before = (a, b)
    compare_results(a, b)
    assert (a, b) == before
