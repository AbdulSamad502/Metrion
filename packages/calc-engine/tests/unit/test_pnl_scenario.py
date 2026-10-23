"""Hypothetical P&L scenario — parity with the reference public calculator (docs/specs/calculator.md §14, N-AC2/N-AC4).

Every expected number below is a hand-checked fixture from the reference calculator's own tests (Metrion-P-L-website
`src/engine/calculate.test.ts` and `solve.test.ts`) and `docs/CALCULATION.md`; they are re-asserted here to the paisa so the Brain 1
implementation cannot drift from the specification it was ported from. All example numbers are fictional test inputs, not marketplace rates.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import replace
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from calc_engine.formulas.pnl_scenario import (
    EMPTY,
    NA,
    Band,
    Entry,
    FeeAmount,
    FeeInput,
    Recovery,
    ScenarioInputs,
    SolveTarget,
    calculate_scenario,
    invalid,
    set_,
    solve_price,
)
from calc_engine.formulas.pnl_scenario import model as pnl_model
from calc_engine.rounding import round_half_up_paise


def rupees(n: int) -> int:
    return n * 100


def flat(paise: int, refund_bps: Entry = EMPTY) -> FeeInput:
    return FeeInput(set_(FeeAmount("single", paise)), refund_bps)


def pct(bps: int, refund_bps: Entry = EMPTY) -> FeeInput:
    return FeeInput(set_(FeeAmount("single", bps)), refund_bps)


def tiers(mode: str, bands: list[tuple[int | None, int]], basis: str | None = None) -> FeeInput:
    return FeeInput(set_(FeeAmount("tiers", mode=mode, bands=tuple(Band(u, a) for u, a in bands))), EMPTY, basis)


def base_detailed(**over) -> ScenarioInputs:
    """Amazon, Detailed, registered with ITC: 18% GST, price Rs 1,180, cost Rs 354, packaging Rs 23.60, no returns."""
    fields = dict(
        marketplace="amazon",
        mode="detailed",
        selling_price=set_(rupees(1180)),
        gst_rate_bps=set_(1800),
        product_cost=set_(rupees(354)),
        packaging_cost=set_(2360),
        fees={"referral": pct(1000), "closing": flat(2000), "shipping": flat(5000)},
        monthly_orders=set_(100),
        rto_bps=set_(0),
        return_bps=set_(0),
        ad_spend=NA,
    )
    fields.update(over)
    return ScenarioInputs(**fields)


def amount_of(lines, id_: str) -> int:
    return next((ln.amount.value for ln in lines if ln.id == id_), 0)


# ---- A1 ---------------------------------------------------------------------------------------------------------------------------

def test_a1_registered_itc_no_returns_matches_hand_calculation() -> None:
    r = calculate_scenario(base_detailed())
    assert r.status == "estimate" and r.missing_costs == ()
    v = r.per_kept
    assert v.revenue.value == 100000
    assert amount_of(v.lines, "product") == 30000
    assert amount_of(v.lines, "packaging") == 2000
    assert amount_of(v.lines, "fee_referral") == 11800
    assert amount_of(v.lines, "fee_closing") == 2000
    assert amount_of(v.lines, "fee_shipping") == 5000
    assert v.contribution.value == 49200
    assert r.metrics.contribution_margin_bps == 4920
    assert r.metrics.gst_recovered_per_kept.value == 9144
    assert r.monthly.contribution.value == 4920000


# ---- A2 ---------------------------------------------------------------------------------------------------------------------------

def test_a2_rto_returns_recovery_salvage() -> None:
    r = calculate_scenario(
        base_detailed(
            rto_bps=set_(1000),
            return_bps=set_(1000),
            rto_recovery=Recovery(set_(5000), set_(0)),
            return_recovery=Recovery(set_(5000), set_(2500)),
            salvage_bps=set_(4000),
        )
    )
    assert r.orders.kept == Fraction(80)
    m = r.monthly
    assert m.revenue.value == 8000000
    assert amount_of(m.lines, "product") == 2400000
    assert amount_of(m.lines, "stock_loss") == 324000
    assert m.contribution.value == 3196000
    assert r.per_kept.contribution.value == 39950
    assert amount_of(r.per_kept.lines, "stock_loss") == 4050
    assert r.per_placed.contribution.value == 31960
    assert r.metrics.contribution_margin_bps == 3995
    codes = [a.code for a in r.assumptions]
    assert "refund_default" in codes and "itc_written_off" in codes and "recovery_default" not in codes


def test_refunded_fees_credit_back() -> None:
    r = calculate_scenario(
        base_detailed(
            return_bps=set_(2000),
            return_recovery=Recovery(set_(10000), set_(0)),
            fees={"referral": pct(1000, set_(10000)), "closing": flat(2000), "shipping": flat(5000)},
        )
    )
    assert amount_of(r.monthly.lines, "fee_refunds") == -236000


# ---- GST variants -----------------------------------------------------------------------------------------------------------------

def test_registered_without_itc() -> None:
    r = calculate_scenario(base_detailed(gst_status="registered_no_itc"))
    v = r.per_kept
    assert v.revenue.value == 100000
    assert amount_of(v.lines, "product") == 35400
    assert amount_of(v.lines, "packaging") == 2360
    assert amount_of(v.lines, "fee_gst") == 3384
    assert v.contribution.value == 40056
    assert r.metrics.gst_recovered_per_kept is None


def test_unregistered_collects_no_gst() -> None:
    r = calculate_scenario(base_detailed(gst_status="unregistered", gst_rate_bps=EMPTY))
    assert r.status == "estimate"
    assert r.per_kept.revenue.value == 118000
    assert r.per_kept.contribution.value == 58056


# ---- zero kept --------------------------------------------------------------------------------------------------------------------

def test_zero_kept_orders_gives_no_per_kept_figures() -> None:
    r = calculate_scenario(base_detailed(rto_bps=set_(6000), return_bps=set_(4000)))
    assert r.no_kept_orders and r.per_kept is None and r.metrics is None
    assert r.monthly.revenue.value == 0 and r.monthly.contribution.value < 0 and r.per_placed.contribution.value < 0
    assert "recovery_default" in [a.code for a in r.assumptions]


def test_outcomes_over_100_percent_block() -> None:
    assert calculate_scenario(base_detailed(rto_bps=set_(7000), return_bps=set_(4000))).status == "incomplete"


# ---- statuses: empty is never zero ------------------------------------------------------------------------------------------------

def test_nothing_entered_is_incomplete_and_names_what_is_needed() -> None:
    r = calculate_scenario(ScenarioInputs(marketplace="amazon", mode="quick"))
    assert r.status == "incomplete" and r.per_kept is None and r.monthly is None
    assert {"price_missing", "gst_missing", "cost_missing"} <= {i.code for i in r.issues}


def test_empty_fees_make_it_provisional_and_are_excluded_not_zero() -> None:
    r = calculate_scenario(
        ScenarioInputs(
            marketplace="amazon", mode="quick", selling_price=set_(118000), gst_rate_bps=set_(1800), product_cost=set_(35400),
            rto_bps=set_(0), return_bps=set_(0),
        )
    )
    assert r.status == "provisional"
    assert {"Referral fee", "Closing fee", "Shipping / weight-handling fee"} <= set(r.missing_costs)
    assert r.per_kept.contribution.value == 100000 - 30000


def test_quick_mode_estimate_carries_a_scope_note() -> None:
    r = calculate_scenario(
        ScenarioInputs(
            marketplace="amazon", mode="quick", selling_price=set_(118000), gst_rate_bps=set_(1800), product_cost=set_(35400),
            fees={"referral": pct(1000), "closing": flat(2000), "shipping": flat(5000)}, rto_bps=set_(0), return_bps=set_(0),
        )
    )
    assert r.status == "estimate" and "packaging" in r.scope_note
    assert r.per_kept.contribution.value == 100000 - 30000 - 11800 - 2000 - 5000


def test_not_applicable_is_a_confirmed_zero_but_empty_is_missing() -> None:
    with_na = calculate_scenario(base_detailed(packaging_cost=NA))
    assert with_na.status == "estimate" and amount_of(with_na.per_kept.lines, "packaging") == 0
    empty = calculate_scenario(base_detailed(packaging_cost=EMPTY))
    assert empty.status == "provisional" and "Packaging cost" in empty.missing_costs


def test_operating_profit_only_when_answered() -> None:
    assert calculate_scenario(base_detailed()).per_kept.operating_profit is None
    r = calculate_scenario(base_detailed(operating_expenses=set_(1000000)))
    assert r.monthly.operating_profit.value == 4920000 - 1000000
    assert r.per_kept.operating_expenses.value == 10000
    assert r.per_kept.operating_profit.value == 49200 - 10000


def test_monthly_costs_are_not_allocated_without_monthly_orders() -> None:
    r = calculate_scenario(base_detailed(monthly_orders=EMPTY, operating_expenses=set_(1000000), ad_spend=set_(500000)))
    assert r.monthly is None and r.status == "provisional" and r.per_kept.operating_profit is None


def test_advertising_metrics_exact() -> None:
    r = calculate_scenario(base_detailed(ad_spend=set_(1180000), ad_revenue=set_(5900000)))
    m = r.metrics
    assert (m.acos_bps, m.roas_bps, m.tacos_bps) == (2000, 50000, 1000)


def test_invalid_or_zero_price_never_produces_a_figure() -> None:
    bad = calculate_scenario(base_detailed(selling_price=invalid("Enter a valid amount")))
    assert bad.status == "incomplete" and bad.per_kept is None
    assert calculate_scenario(base_detailed(selling_price=set_(0))).status == "incomplete"


def test_no_fee_rate_is_ever_assumed() -> None:
    """Fee fields hold labels only. With no fee entered nothing is charged and the gap is named."""
    r = calculate_scenario(base_detailed(fees={}))
    assert r.status == "provisional"
    assert {"Referral fee", "Closing fee", "Shipping / weight-handling fee"} <= set(r.missing_costs)
    assert not any(ln.id.startswith("fee_") for ln in r.per_kept.lines)


# ---- precision and rounding ------------------------------------------------------------------------------------------------------

def test_rounding_is_half_away_from_zero_for_negative_amounts() -> None:
    assert round_half_up_paise(Fraction(-5, 2)).value == -3
    assert round_half_up_paise(Fraction(5, 2)).value == 3
    assert round_half_up_paise(Fraction(-1, 3)).value == 0


def test_values_beyond_the_js_safe_integer_stay_exact() -> None:
    big = 9_007_199_254_740_993  # 2**53 + 1
    r = calculate_scenario(base_detailed(selling_price=set_(big), gst_status="unregistered", gst_rate_bps=EMPTY, product_cost=set_(1)))
    assert r.per_kept.revenue.value == big


# ---- solver ----------------------------------------------------------------------------------------------------------------------

def _simple(cost: int, fees: dict) -> ScenarioInputs:
    """Unregistered, no GST on services, Detailed mode, Meesho: profit(P) = P - cost - fees."""
    return ScenarioInputs(
        marketplace="meesho", mode="detailed", gst_status="unregistered", selling_price=set_(1000), product_cost=set_(cost),
        services_gst_rate_bps=NA, packaging_cost=NA, ad_spend=NA, monthly_orders=set_(1), rto_bps=set_(0), return_bps=set_(0), fees=fees,
    )


_NA_FEE = FeeInput(NA, EMPTY)
_OTHER = {"shipping": _NA_FEE, "reverse": _NA_FEE, "other": _NA_FEE}


def _flipkart() -> ScenarioInputs:
    return replace(
        _simple(10000, {}), marketplace="flipkart", services_gst_rate_bps=set_(1800),
        fees={"commission": pct(1000), "shipping": flat(2000), "fixed_fee": _NA_FEE, "collection_fee": _NA_FEE, "reverse": _NA_FEE, "other": _NA_FEE},
    )


def test_break_even_price_is_rs_140_14() -> None:
    r = solve_price(_flipkart(), SolveTarget("breakeven"))
    assert r.kind == "price" and r.price.value == 14014


def test_20_percent_target_margin_price_is_rs_181_24() -> None:
    r = solve_price(_flipkart(), SolveTarget("margin", 2000))
    assert r.kind == "price" and r.price.value == 18124


def test_solver_works_without_a_selling_price_entered() -> None:
    base = replace(_flipkart(), selling_price=EMPTY)
    assert solve_price(base, SolveTarget("breakeven")).price.value == 14014


def test_break_even_never_shows_negative_displayed_profit() -> None:
    base = _flipkart()
    r = solve_price(base, SolveTarget("breakeven"))
    shown = calculate_scenario(replace(base, selling_price=set_(r.price.value)))
    assert shown.per_kept.contribution.value >= 0


def test_whole_bands_with_a_jump_report_both_feasible_ranges() -> None:
    bands = [(500, 1000), (1000, 9500), (None, 1000)]
    r = solve_price(_simple(200, {"commission": tiers("whole", bands), **_OTHER}), SolveTarget("breakeven"))
    assert r.kind == "price" and r.price.value == 223
    assert [(x.from_price, x.to_price) for x in r.ranges] == [(223, 500), (1001, None)]


def test_margin_target_can_hit_a_single_price_window_then_jump() -> None:
    bands = [(500, 1000), (1000, 9500), (None, 1000)]
    r = solve_price(_simple(200, {"commission": tiers("whole", bands), **_OTHER}), SolveTarget("margin", 5000))
    assert r.price.value == 500
    assert [(x.from_price, x.to_price) for x in r.ranges] == [(500, 500), (1001, None)]


def test_degenerate_solver_cases() -> None:
    assert solve_price(_simple(200, {"commission": pct(10000), **_OTHER}), SolveTarget("breakeven")).kind == "unreachable"
    no_kept = replace(_simple(200, {"commission": pct(1000), **_OTHER}), rto_bps=set_(10000))
    r = solve_price(no_kept, SolveTarget("breakeven"))
    assert (r.kind, r.reason) == ("unavailable", "no_kept_orders")
    r = solve_price(ScenarioInputs(marketplace="amazon", mode="quick"), SolveTarget("breakeven"))
    assert (r.kind, r.reason) == ("unavailable", "incomplete")
    assert solve_price(_simple(200, {"commission": pct(1000)}), SolveTarget("breakeven")).excludes_missing_costs is True
    assert solve_price(_simple(0, {"commission": pct(1000), **_OTHER}), SolveTarget("breakeven")).kind == "always"


def _exact_g(inputs: ScenarioInputs, target: SolveTarget, price: int) -> Fraction:
    p = pnl_model.prepare(inputs).prepared
    t = pnl_model.evaluate(p, price)
    m = pnl_model.from_bps(target.bps) if target.kind == "margin" else Fraction(0)
    return t.contribution - m * t.revenue


@settings(max_examples=40, deadline=None)
@given(
    edges=st.lists(st.integers(20, 600), min_size=1, max_size=3, unique=True),
    rates=st.lists(st.integers(0, 9500), min_size=4, max_size=4),
    basis=st.sampled_from(["price_incl_gst", "price_excl_gst"]),
    cost=st.integers(0, 300),
    margin=st.integers(0, 6000),
    registered=st.booleans(),
)
def test_solver_equals_an_exhaustive_paisa_scan(edges, rates, basis, cost, margin, registered) -> None:
    ordered = sorted(edges)
    bands = [(e, rates[i]) for i, e in enumerate(ordered)] + [(None, rates[len(ordered)])]
    base = replace(
        _simple(cost, {"commission": tiers("whole", bands, basis), **_OTHER}),
        gst_status="registered_no_itc" if registered else "unregistered",
        gst_rate_bps=set_(1800) if registered else EMPTY, services_gst_rate_bps=set_(1800),
    )
    target = SolveTarget("margin", margin)
    feasible = [pr for pr in range(1, 801) if _exact_g(base, target, pr) >= 0]
    r = solve_price(base, target)
    for pr in range(1, 801):
        got = r.kind == "always" or (r.kind == "price" and any(pr >= x.from_price and (x.to_price is None or pr <= x.to_price) for x in r.ranges))
        assert (pr in feasible) == got, (pr, r)
    if r.kind == "price":
        assert (r.price.value > 800) if not feasible else (r.price.value == feasible[0])
    if r.kind == "unreachable":
        assert not feasible


# ---- structure: purity ------------------------------------------------------------------------------------------------------------

_PKG = pathlib.Path(pnl_model.__file__).parent


def test_package_has_no_float_and_no_io() -> None:
    """N-AC1/N-AC3: no float anywhere in the arithmetic, and the module imports no repository, DB or network layer."""
    banned_imports = ("sqlalchemy", "psycopg", "httpx", "requests", "calc_engine.repositories", "backend", "random", "datetime", "time")
    for path in _PKG.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                pytest.fail(f"{path.name}: float literal {node.value}")
            if isinstance(node, ast.Name) and node.id == "float":
                pytest.fail(f"{path.name}: float() used")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for n in names:
                    assert not n.startswith(banned_imports), f"{path.name} imports {n}"


# ---- where each rupee goes (calculator.md §14.8) ----------------------------------------------------------------------------------

def test_breakdown_a1_matches_the_hand_calculation() -> None:
    """Per kept order revenue 1,000: product 300 (30.00%), packaging 20 (2.00%), referral 118 (11.80%), closing 20 (2.00%), shipping 50 (5.00%), profit 492 (49.20%)."""
    b = calculate_scenario(base_detailed()).breakdown
    assert b is not None
    shares = {ln.id: ln.share_bps for ln in b.lines}
    assert shares == {"product": 3000, "stock_loss": 0, "packaging": 200, "fee_referral": 1180, "fee_closing": 200, "fee_shipping": 500, "advertising": 0}
    assert b.profit_share_bps == 4920
    assert [(t.id, t.amount.value, t.share_bps) for t in b.top_costs] == [("product", 30000, 3000), ("fee_referral", 11800, 1180), ("fee_shipping", 5000, 500)]
    assert b.segments is not None and b.chart_unavailable_reason is None
    assert [(s.id, s.start_bps, s.end_bps) for s in b.segments] == [
        ("product", 0, 3000), ("packaging", 3000, 3200), ("fee_referral", 3200, 4380), ("fee_closing", 4380, 4580), ("fee_shipping", 4580, 5080), ("profit", 5080, 10000),
    ]
    assert b.segments[-1].amount.value == 49200  # the profit slice is the ledger's profit


def test_breakdown_shares_do_not_depend_on_which_view_is_read() -> None:
    """Shares are exact ratios, so the same scenario with 1 or 100 orders gives the same percentages."""
    one = calculate_scenario(base_detailed(monthly_orders=set_(1))).breakdown
    many = calculate_scenario(base_detailed(monthly_orders=set_(100))).breakdown
    assert one is not None and many is not None
    assert [(ln.id, ln.share_bps) for ln in one.lines] == [(ln.id, ln.share_bps) for ln in many.lines]


def test_breakdown_without_a_chart_when_a_fee_refund_credit_exists() -> None:
    r = calculate_scenario(
        base_detailed(
            return_bps=set_(2000), return_recovery=Recovery(set_(10000), set_(0)),
            fees={"referral": pct(1000, set_(10000)), "closing": flat(2000), "shipping": flat(5000)},
        )
    )
    b = r.breakdown
    assert b is not None and b.segments is None and "credit" in (b.chart_unavailable_reason or "")
    assert any(ln.id == "fee_refunds" and ln.share_bps < 0 for ln in b.lines)  # the shares are still there, the credit as a negative share
    assert all(t.amount.value > 0 for t in b.top_costs)  # a credit is never a "biggest cost"


def test_breakdown_without_a_chart_when_costs_exceed_revenue_but_top_costs_remain() -> None:
    b = calculate_scenario(base_detailed(product_cost=set_(rupees(2000)))).breakdown
    assert b is not None and b.segments is None and b.profit_share_bps < 0
    assert b.top_costs and b.top_costs[0].id == "product"


def test_there_is_no_breakdown_when_nothing_is_kept_or_the_result_is_incomplete() -> None:
    assert calculate_scenario(base_detailed(rto_bps=set_(6000), return_bps=set_(4000))).breakdown is None
    assert calculate_scenario(ScenarioInputs(marketplace="amazon")).breakdown is None


def test_top_costs_are_the_largest_three_positive_costs_in_order() -> None:
    b = calculate_scenario(base_detailed(ad_spend=set_(5_000_000))).breakdown  # a big ad budget becomes a top cost
    assert b is not None
    amounts = [t.amount.value for t in b.top_costs]
    assert len(b.top_costs) == 3 and amounts == sorted(amounts, reverse=True)
    assert "advertising" in [t.id for t in b.top_costs]


@settings(max_examples=60, deadline=None)
@given(
    price=st.integers(1000, 500000), cost=st.integers(0, 300000), referral=st.integers(0, 3000), ship=st.integers(0, 30000),
    rto=st.integers(0, 3000), ret=st.integers(0, 3000), orders=st.integers(1, 2000),
)
def test_breakdown_slices_always_tile_the_whole_circle(price, cost, referral, ship, rto, ret, orders) -> None:
    r = calculate_scenario(
        base_detailed(
            selling_price=set_(price), product_cost=set_(cost), monthly_orders=set_(orders), rto_bps=set_(rto), return_bps=set_(ret),
            rto_recovery=Recovery(set_(5000), set_(0)), return_recovery=Recovery(set_(5000), set_(0)),
            fees={"referral": pct(referral), "closing": flat(2000), "shipping": flat(ship)},
        )
    )
    b = r.breakdown
    assert b is not None
    assert b.profit_share_bps == r.metrics.contribution_margin_bps
    if b.segments is not None:
        assert b.segments[0].start_bps == 0 and b.segments[-1].end_bps == 10000 and b.segments[-1].id == "profit"
        for a, c in zip(b.segments, b.segments[1:]):
            assert a.end_bps == c.start_bps and a.start_bps <= a.end_bps
