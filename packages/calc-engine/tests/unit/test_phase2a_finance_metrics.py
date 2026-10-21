"""Phase 2a golden and property tests: expenses/operating profit, settlement receipts, ad status/ratios, portfolio analytics, cash forecast.
Every expected value is a hand-computed integer paise or exact fraction (deterministic-engine.md §5.17.1)."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest
from hypothesis import given, strategies as st

from calc_engine.formulas.ad_spend import AdCoverage, AdCoverageSource as Src, AdSpendStatus as S, ad_ratios, ad_spend_status
from calc_engine.formulas.cash_forecast import (
    Payable, ShortfallStatus, UnsettledLine, cash_shortfall_status, expected_receipts, lower_median,
)
from calc_engine.formulas.completeness import Completeness
from calc_engine.formulas.expense_accounting import (
    PNL_TREATMENT, ExpenseClass as C, ExpenseHold as H, ExpenseLine, OperatingProfitStatus, OverheadCoverage as OC,
    effective_class, expense_breakdown, operating_profit,
)
from calc_engine.formulas.portfolio_analytics import BreakEvenKind, break_even_bracket, margin_stability, sku_concentration
from calc_engine.formulas.settlement_receipts import SettlementLineInput as SL, settlement_receipts, settlement_receipts_by_marketplace
from calc_engine.types import Unavailable

D = date
P0, P1 = D(2026, 10, 1), D(2026, 10, 31)


def ex(i: str, amt: int, klass: C | None, cat: str = "x", hold: H = H.NONE, d: date = D(2026, 10, 5), suggested: C | None = None) -> ExpenseLine:
    return ExpenseLine(i, cat, amt, d, confirmed_class=klass, suggested_class=suggested, hold=hold)


# ------------------------------------------------------------------------------------------ expenses / operating profit
ONE_OF_EACH = [ex("a", 10_000, C.OVERHEAD), ex("b", 20_000, C.ALLOCATED_COST), ex("c", 30_000, C.OWNER_DRAWING), ex("d", 40_000, C.INVENTORY_PURCHASE),
               ex("e", 50_000, C.CAPITAL), ex("f", 60_000, C.TAX_ASSET)]


@pytest.mark.parametrize("klass", [k for k in C if k is not C.OVERHEAD])
def test_only_overhead_reduces_operating_profit(klass: C) -> None:
    r = operating_profit(1_000_000, [ex("x", 77_700, klass)], OC.SOURCE_PRESENT)
    assert not isinstance(r, Unavailable) and r.value_paise == 1_000_000 and r.overhead_total_paise == 0


def test_operating_profit_is_contribution_profit_minus_overhead_with_all_classes_present() -> None:
    r = operating_profit(1_000_000, ONE_OF_EACH, OC.SOURCE_PRESENT)
    assert not isinstance(r, Unavailable)
    assert r.value_paise == 990_000 and r.status is OperatingProfitStatus.FINAL and r.completeness is Completeness.COMPLETE
    assert r.allocated_cost_total_paise == 20_000  # informational: already inside CP, never subtracted twice
    assert {k: t for k, t, _ in r.non_pnl_totals} == {C.OWNER_DRAWING: 30_000, C.INVENTORY_PURCHASE: 40_000, C.CAPITAL: 50_000, C.TAX_ASSET: 60_000}


def test_treatment_matrix_has_exactly_one_profit_reducing_class() -> None:
    assert [k for k, t in PNL_TREATMENT.items() if t.subtracted_in_operating_profit] == [C.OVERHEAD]
    assert all(not t.subtracted_in_operating_profit for k, t in PNL_TREATMENT.items() if t.in_contribution_profit)  # no double count
    assert PNL_TREATMENT[C.TAX_ASSET].reduces_receipts and not PNL_TREATMENT[C.TAX_ASSET].cash_outflow


def test_suggestion_never_counts_only_confirmation_does() -> None:
    line = ex("s", 5_000, None, suggested=C.OVERHEAD)
    assert effective_class(line) is C.OTHER_UNCLASSIFIED
    r = operating_profit(100_000, [line], OC.SOURCE_PRESENT)
    assert not isinstance(r, Unavailable) and r.value_paise == 100_000 and r.status is OperatingProfitStatus.PROVISIONAL
    assert r.unclassified.total_paise == 5_000 and r.unclassified.entry_ids == ("s",)


def test_held_lines_are_excluded_listed_and_make_the_figure_provisional() -> None:
    r = operating_profit(100_000, [ex("o", 1_000, C.OVERHEAD), ex("h", 9_000, C.OVERHEAD, hold=H.POSSIBLE_DUPLICATE)], OC.SOURCE_PRESENT)
    assert not isinstance(r, Unavailable)
    assert r.value_paise == 99_000 and r.held.entry_ids == ("h",) and r.status is OperatingProfitStatus.PROVISIONAL


def test_refund_of_an_overhead_expense_reduces_it() -> None:
    r = operating_profit(100_000, [ex("o", 10_000, C.OVERHEAD), ex("r", -4_000, C.OVERHEAD)], OC.SOURCE_PRESENT)
    assert not isinstance(r, Unavailable) and r.value_paise == 94_000


def test_missing_overhead_information_is_unavailable_never_equal_to_contribution_profit() -> None:
    assert isinstance(operating_profit(100_000, [], OC.NONE), Unavailable)
    assert isinstance(operating_profit(100_000, [ex("x", 1, C.ALLOCATED_COST)], OC.NONE), Unavailable)  # entries exist but coverage unestablished
    assert isinstance(operating_profit(None, [ex("o", 1, C.OVERHEAD)], OC.SOURCE_PRESENT), Unavailable)


def test_declared_no_overhead_is_a_verified_zero_but_contradicting_entries_are_refused() -> None:
    r = operating_profit(100_000, [], OC.DECLARED_NONE)
    assert not isinstance(r, Unavailable) and r.value_paise == 100_000 and r.status is OperatingProfitStatus.FINAL
    assert isinstance(operating_profit(100_000, [ex("o", 1, C.OVERHEAD)], OC.DECLARED_NONE), Unavailable)


def test_period_filter_applies_to_every_figure() -> None:
    r = operating_profit(100_000, [ex("in", 1_000, C.OVERHEAD), ex("out", 9_000, C.OVERHEAD, d=D(2026, 9, 30))], OC.SOURCE_PRESENT, period_start=P0, period_end=P1)
    assert not isinstance(r, Unavailable) and r.value_paise == 99_000


def test_breakdown_groups_by_category_and_class_and_separates_held() -> None:
    b = expense_breakdown([ex("1", 100, C.OVERHEAD, "rent"), ex("2", 50, C.OVERHEAD, "rent"), ex("3", 70, None, "misc"),
                           ex("4", 900, C.OVERHEAD, "rent", hold=H.MAY_OVERLAP_UNCONFIRMED)])
    assert [(g.category, g.klass, g.total_paise, g.line_count) for g in b.groups] == [("misc", C.OTHER_UNCLASSIFIED, 70, 1), ("rent", C.OVERHEAD, 150, 2)]
    assert [(e.hold, e.total_paise) for e in b.excluded] == [(H.MAY_OVERLAP_UNCONFIRMED, 900)]


_classes = st.sampled_from([None, *C])
_holds = st.sampled_from(list(H))


@given(st.lists(st.tuples(st.integers(-10**6, 10**6), _classes, st.sampled_from(["a", "b", "c"]), _holds), max_size=40))
def test_property_breakdown_is_a_partition_of_all_in_scope_lines(rows) -> None:
    lines = [ex(str(i), a, k, cat, h) for i, (a, k, cat, h) in enumerate(rows)]
    b = expense_breakdown(lines)
    assert b.grouped_total_paise + b.excluded_total_paise == sum(a for a, *_ in rows)


@given(st.integers(-10**9, 10**9), st.lists(st.tuples(st.integers(-10**6, 10**6), _classes), max_size=30))
def test_property_operating_profit_identity(cp, rows) -> None:
    lines = [ex(str(i), a, k) for i, (a, k) in enumerate(rows)]
    r = operating_profit(cp, lines, OC.SOURCE_PRESENT)
    assert not isinstance(r, Unavailable)
    assert r.value_paise == cp - sum(a for a, k in rows if k is C.OVERHEAD)


# ------------------------------------------------------------------------------------------ settlement receipts
def test_settlement_receipts_sums_by_settlement_date_in_period() -> None:
    r = settlement_receipts([SL("1", "MEESHO", D(2026, 10, 3), 100_000), SL("2", "MEESHO", D(2026, 10, 31), 50_000), SL("3", "MEESHO", D(2026, 11, 1), 999)], P0, P1)
    assert not isinstance(r, Unavailable) and r.value_paise == 150_000 and r.line_count == 2 and r.completeness is Completeness.COMPLETE


def test_settlement_negative_amounts_net_and_exclusions_are_counted() -> None:
    r = settlement_receipts([SL("1", "M", D(2026, 10, 3), 100), SL("2", "M", D(2026, 10, 4), -30), SL("3", "M", None, 5), SL("4", "M", D(2026, 10, 5), None),
                             SL("5", "M", D(2026, 10, 6), 7, held=True)], P0, P1)
    assert not isinstance(r, Unavailable)
    assert (r.value_paise, r.excluded_undated, r.excluded_no_amount, r.excluded_held, r.completeness) == (70, 1, 1, 1, Completeness.PARTIAL)


def test_settlement_unavailable_cases() -> None:
    assert isinstance(settlement_receipts([], P0, P1), Unavailable)
    assert isinstance(settlement_receipts([SL("1", "AMAZON", D(2026, 10, 3), None)], P0, P1), Unavailable)  # Amazon lines arrive amount-less
    assert isinstance(settlement_receipts([SL("1", "M", D(2026, 12, 3), 5)], P0, P1), Unavailable)  # nothing in this period
    with pytest.raises(ValueError):
        settlement_receipts([SL("1", "M", D(2026, 10, 3), 5)], P1, P0)


def test_receipts_reconcile_across_marketplaces_and_name_the_unavailable_one() -> None:
    lines = [SL("1", "MEESHO", D(2026, 10, 3), 100_000), SL("2", "FLIPKART", D(2026, 10, 4), 40_000), SL("3", "AMAZON", D(2026, 10, 5), None)]
    r = settlement_receipts_by_marketplace(lines, P0, P1)
    assert r.value_paise == 140_000 == sum(v.value_paise for v in r.per_marketplace.values())  # Σ marketplaces = consolidated
    assert set(r.unavailable) == {"AMAZON"} and r.completeness is Completeness.PARTIAL  # Amazon is named, never summed as zero
    none = settlement_receipts_by_marketplace([SL("3", "AMAZON", D(2026, 10, 5), None)], P0, P1)
    assert none.value_paise is None and none.completeness is Completeness.UNAVAILABLE


# ------------------------------------------------------------------------------------------ ad spend status / ratios
def cov(mp: str, a: date, b: date, s: Src = Src.REPORT) -> AdCoverage:
    return AdCoverage(mp, a, b, s)


def status(coverage, spend, mp="AMAZON"):
    return ad_spend_status(marketplace=mp, period_start=P0, period_end=P1, coverage=coverage, spend_paise=spend)


def test_ad_status_rules() -> None:
    assert status([], None) is S.UNKNOWN and status([], 0) is S.UNKNOWN  # no source: zero rows is not a verified zero
    assert status([cov("AMAZON", P0, D(2026, 10, 15))], 5_000) is S.MISSING_COVERAGE  # does not cover the period
    assert status([cov("AMAZON", P0, P1)], 5_000) is S.KNOWN_SPEND
    assert status([cov("AMAZON", P0, P1)], 0) is S.VERIFIED_ZERO
    assert status([cov("AMAZON", P0, P1, Src.DECLARATION_NO_ADS)], None) is S.VERIFIED_ZERO
    assert status([cov("AMAZON", P0, P1)], None) is S.MISSING_COVERAGE  # a covering report with no amount is not a verified zero
    assert status([cov("FLIPKART", P0, P1)], 5_000) is S.UNKNOWN  # another marketplace's coverage does not count
    with pytest.raises(ValueError):
        status([cov("AMAZON", P0, P1)], -1)


def test_adjacent_coverage_intervals_join_and_a_gap_breaks_coverage() -> None:
    assert status([cov("AMAZON", P0, D(2026, 10, 15)), cov("AMAZON", D(2026, 10, 16), P1)], 1) is S.KNOWN_SPEND
    assert status([cov("AMAZON", P0, D(2026, 10, 15)), cov("AMAZON", D(2026, 10, 17), P1)], 1) is S.MISSING_COVERAGE
    assert status([cov("AMAZON", D(2026, 9, 1), D(2026, 11, 30))], 1) is S.KNOWN_SPEND  # a wider report still covers


def test_ad_ratios_are_exact_fractions() -> None:
    r = ad_ratios(status=S.KNOWN_SPEND, spend_paise=10_000, attributed_sales_paise=40_000, total_sales_paise=100_000)
    assert (r.roas, r.acos, r.tacos, r.completeness) == (Fraction(4), Fraction(1, 4), Fraction(1, 10), Completeness.COMPLETE)


def test_ad_ratios_unavailable_cases() -> None:
    for st_ in (S.UNKNOWN, S.MISSING_COVERAGE):
        r = ad_ratios(status=st_, spend_paise=None, attributed_sales_paise=1, total_sales_paise=1)
        assert (r.roas, r.acos, r.tacos, r.completeness) == (None, None, None, Completeness.UNAVAILABLE)
    z = ad_ratios(status=S.VERIFIED_ZERO, spend_paise=0, attributed_sales_paise=0, total_sales_paise=100_000)
    assert z.roas is None and z.acos is None and z.tacos == 0 and "roas" in z.unavailable  # zero spend: TACOS is a true 0, ROAS undefined
    n = ad_ratios(status=S.KNOWN_SPEND, spend_paise=500, attributed_sales_paise=None, total_sales_paise=None)
    assert n.roas is None and n.acos is None and n.tacos is None
    with pytest.raises(ValueError):
        ad_ratios(status=S.KNOWN_SPEND, spend_paise=0, attributed_sales_paise=1, total_sales_paise=1)
    with pytest.raises(ValueError):
        ad_ratios(status=S.VERIFIED_ZERO, spend_paise=5, attributed_sales_paise=1, total_sales_paise=1)


# ------------------------------------------------------------------------------------------ portfolio analytics
def test_sku_concentration_golden() -> None:
    r = sku_concentration({"A": 600, "B": 300, "C": 100, "D": -50, "E": None}, top_n=2)
    assert not isinstance(r, Unavailable)
    assert [s.sku for s in r.ranked] == ["A", "B", "C"] and r.top_share == Fraction(9, 10) and r.total_nrr_paise == 1000
    assert r.excluded_non_positive == ("D",) and r.excluded_unavailable == ("E",) and r.completeness is Completeness.PARTIAL
    assert sum(s.share for s in r.ranked) == 1


def test_sku_concentration_ties_break_by_sku_and_unavailable_cases() -> None:
    r = sku_concentration({"B": 5, "A": 5}, top_n=1)
    assert not isinstance(r, Unavailable) and r.top[0].sku == "A" and r.top_share == Fraction(1, 2)
    assert isinstance(sku_concentration({"A": 0, "B": None}, 1), Unavailable)
    with pytest.raises(ValueError):
        sku_concentration({"A": 1}, 0)


@given(st.dictionaries(st.text("ABCDEFG", min_size=1, max_size=3), st.integers(1, 10**9), min_size=1, max_size=8), st.integers(1, 10))
def test_property_concentration_shares_sum_to_one(d, n) -> None:
    r = sku_concentration(d, n)
    assert not isinstance(r, Unavailable) and sum(s.share for s in r.ranked) == 1 and r.top_share <= 1


def test_margin_stability_golden_and_unavailable() -> None:
    r = margin_stability([Fraction(1, 5), Fraction(3, 10), Fraction(1, 10)], min_periods=3)
    assert not isinstance(r, Unavailable) and r.mean == Fraction(1, 5) and r.mad == Fraction(2, 30)  # |0|,|.1|,|.1| / 3
    flat = margin_stability([Fraction(1, 4)] * 4, 2)
    assert not isinstance(flat, Unavailable) and flat.mad == 0
    assert isinstance(margin_stability([Fraction(1, 5)], 2), Unavailable)
    assert isinstance(margin_stability([Fraction(1, 5), None], 2), Unavailable)
    assert isinstance(margin_stability([Fraction(1, 5)] * 3, None), Unavailable)  # CONFIG_MISSING
    with pytest.raises(ValueError):
        margin_stability([Fraction(1)] * 3, 1)


def test_break_even_bracket_cases() -> None:
    r = break_even_bracket([(100, -50), (200, -10), (300, 40), (400, 90)])
    assert not isinstance(r, Unavailable) and (r.kind, r.low_price_paise, r.high_price_paise, r.non_monotonic) == (BreakEvenKind.BRACKET, 200, 300, False)
    below = break_even_bracket([(100, 5), (200, 50)])
    assert not isinstance(below, Unavailable) and below.kind is BreakEvenKind.BELOW_GRID
    above = break_even_bracket([(100, -5), (200, -1)])
    assert not isinstance(above, Unavailable) and above.kind is BreakEvenKind.ABOVE_GRID
    zero = break_even_bracket([(100, -5), (200, 0)])  # exactly zero margin counts as break-even reached
    assert not isinstance(zero, Unavailable) and zero.high_price_paise == 200
    wobble = break_even_bracket([(100, -5), (200, 5), (300, -5), (400, 5)])
    assert not isinstance(wobble, Unavailable) and wobble.non_monotonic and (wobble.low_price_paise, wobble.high_price_paise) == (100, 200)


def test_break_even_unavailable_and_input_order_independence() -> None:
    assert isinstance(break_even_bracket([(100, 1)]), Unavailable)
    assert isinstance(break_even_bracket([(100, 1), (100, 1)]), Unavailable)
    assert isinstance(break_even_bracket([(100, None), (200, None)]), Unavailable)
    assert isinstance(break_even_bracket([(100, -5), (200, None), (300, 5)]), Unavailable)  # an unknown point precedes the crossing
    with pytest.raises(ValueError):
        break_even_bracket([(100, 1), (100, 2)])
    a = break_even_bracket([(300, 40), (100, -50), (200, -10)])
    b = break_even_bracket([(100, -50), (200, -10), (300, 40)])
    assert a == b


# ------------------------------------------------------------------------------------------ cash forecast
def test_lower_median_is_an_observed_value() -> None:
    assert lower_median([7]) == 7 and lower_median([1, 9]) == 1 and lower_median([9, 1, 5]) == 5 and lower_median([4, 1, 3, 2]) == 2
    with pytest.raises(ValueError):
        lower_median([])


AS_OF = D(2026, 10, 10)


def ul(i: str, mp: str, d: date, amt: int | None) -> UnsettledLine:
    return UnsettledLine(i, mp, d, amt)


def test_expected_receipts_projects_future_and_separates_overdue() -> None:
    lines = [ul("a", "MEESHO", D(2026, 10, 5), 1_000), ul("b", "MEESHO", D(2026, 10, 8), 2_000), ul("c", "MEESHO", D(2026, 10, 8), 500), ul("old", "MEESHO", D(2026, 9, 1), 9_000)]
    r = expected_receipts(lines, {"MEESHO": [7, 7, 9]}, AS_OF, min_samples=3)  # lag = 7
    assert not isinstance(r, Unavailable)
    assert [(b.expected_date, b.total_paise, b.line_count) for b in r.buckets] == [(D(2026, 10, 12), 1_000, 1), (D(2026, 10, 15), 2_500, 2)]
    assert (r.overdue_total_paise, r.overdue_line_count, r.completeness) == (9_000, 1, Completeness.COMPLETE)


def test_expected_on_the_as_of_day_is_future_not_overdue() -> None:
    r = expected_receipts([ul("a", "MEESHO", D(2026, 10, 3), 100)], {"MEESHO": [7]}, AS_OF, 1)
    assert not isinstance(r, Unavailable) and r.overdue_line_count == 0 and r.buckets[0].expected_date == AS_OF


def test_insufficient_samples_for_one_marketplace_is_partial_and_named() -> None:
    lines = [ul("a", "MEESHO", D(2026, 10, 5), 100), ul("b", "AMAZON", D(2026, 10, 5), 700)]
    r = expected_receipts(lines, {"MEESHO": [5, 5, 5], "AMAZON": [9]}, AS_OF, 3)
    assert not isinstance(r, Unavailable) and "AMAZON" in r.unprojected and r.completeness is Completeness.PARTIAL
    assert sum(b.total_paise for b in r.buckets) + r.overdue_total_paise == 100  # the Amazon amount is not guessed in
    assert isinstance(expected_receipts([ul("b", "AMAZON", D(2026, 10, 5), 700)], {"AMAZON": [9]}, AS_OF, 3), Unavailable)


def test_receipts_unavailable_and_validation() -> None:
    assert isinstance(expected_receipts([ul("a", "M", D(2026, 10, 5), 1)], {"M": [1]}, AS_OF, None), Unavailable)  # CONFIG_MISSING
    assert isinstance(expected_receipts([], {"M": [1]}, AS_OF, 1), Unavailable)
    assert isinstance(expected_receipts([ul("a", "M", D(2026, 10, 5), None)], {"M": [1]}, AS_OF, 1), Unavailable)
    part = expected_receipts([ul("a", "M", D(2026, 10, 5), None), ul("b", "M", D(2026, 10, 5), 5)], {"M": [1]}, AS_OF, 1)
    assert not isinstance(part, Unavailable) and part.excluded_no_amount == 1 and part.completeness is Completeness.PARTIAL
    with pytest.raises(ValueError):
        expected_receipts([ul("a", "M", D(2026, 10, 5), 1)], {"M": [-1]}, AS_OF, 1)
    with pytest.raises(ValueError):
        expected_receipts([ul("a", "M", D(2026, 10, 5), 1)], {"M": [1]}, AS_OF, 0)


def _receipts():
    r = expected_receipts([ul("a", "M", D(2026, 10, 8), 1_000), ul("b", "M", D(2026, 10, 12), 2_000)], {"M": [5]}, AS_OF, 1)  # due 13th and 17th
    assert not isinstance(r, Unavailable)
    return r


def test_shortfall_status_uses_cumulative_cover_and_equality_is_covered() -> None:
    out = cash_shortfall_status([Payable("p1", 1_000, D(2026, 10, 13)), Payable("p2", 2_001, D(2026, 10, 17)), Payable("p3", 5, None)], _receipts())
    assert not isinstance(out, Unavailable)
    by = {s.payable_id: s for s in out}
    assert by["p1"].status is ShortfallStatus.COVERED and by["p1"].cumulative_cover_paise == 1_000  # equality
    assert by["p2"].status is ShortfallStatus.AT_RISK and (by["p2"].cumulative_payables_paise, by["p2"].cumulative_cover_paise) == (3_001, 3_000)
    assert by["p3"].status is ShortfallStatus.UNKNOWN and by["p3"].cumulative_cover_paise is None  # no due date: listed, not compared


def test_a_past_due_payable_has_no_future_cover_and_earlier_payables_count_against_later_ones() -> None:
    out = cash_shortfall_status([Payable("past", 1, D(2026, 10, 9)), Payable("later", 1_000, D(2026, 10, 13))], _receipts())
    assert not isinstance(out, Unavailable)
    by = {s.payable_id: s for s in out}
    assert by["past"].status is ShortfallStatus.AT_RISK
    assert by["later"].cumulative_payables_paise == 1_001 and by["later"].cumulative_cover_paise == 1_000  # 1_001 due by the 13th against 1_000 of cover
    assert by["later"].status is ShortfallStatus.AT_RISK


def test_shortfall_inherits_unavailability_and_rejects_negative_payables() -> None:
    assert isinstance(cash_shortfall_status([Payable("p", 1, D(2026, 10, 13))], Unavailable(reason="x", missing_inputs=("y",))), Unavailable)
    with pytest.raises(ValueError):
        cash_shortfall_status([Payable("p", -1, D(2026, 10, 13))], _receipts())
