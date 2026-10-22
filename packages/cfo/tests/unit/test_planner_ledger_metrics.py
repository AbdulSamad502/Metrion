"""EXPENSE_BY_CATEGORY and OPERATING_PROFIT through the planner (docs/specs/cfo-expense-ledger.md AC-L11). In-memory backend; the real-database
proof is in backend/tests/integration/test_cfo_query_planner.py."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from cfo.planner.executor import EngineValue
from cfo.planner.pipeline import MockPlannerProvider, PlannerAnswer
from cfo.planner.validator import DataStats

from .test_planner_pipeline import LIMITS, FakeBackend, ask, pj

BREAKDOWN = pj([{"op": "aggregate", "params": {"metric": "EXPENSE_BY_CATEGORY"}}], intent="EXPENSE_BREAKDOWN")
BY_CAT = pj([{"op": "group_by", "params": {"dimensions": ["expense_category", "expense_class"]}}, {"op": "aggregate", "params": {"metric": "EXPENSE_BY_CATEGORY"}}], intent="EXPENSE_BREAKDOWN")
OWNER_VIEW = pj([{"op": "filter", "params": {"dimension": "expense_class", "op": "eq", "value": "OWNER_DRAWING"}},
                 {"op": "aggregate", "params": {"metric": "EXPENSE_BY_CATEGORY"}}], intent="EXPENSE_BREAKDOWN")
OPERATING = pj([{"op": "metric", "params": {"metric": "OPERATING_PROFIT"}}])


def answer(be: FakeBackend, plan: str) -> Any:
    r = ask(MockPlannerProvider([plan]), be)
    assert isinstance(r, PlannerAnswer), r
    return r.packet


def test_the_breakdown_lists_every_category_and_class_with_refs_and_a_partial_total_when_entries_are_held() -> None:
    p = answer(FakeBackend(), BY_CAT)
    rows = {dict(f.dimension_keys)["expense_category"]: f for f in p.figures if f.dimension_keys}
    assert rows["Rent"].value_paise == 1_200 and dict(rows["Rent"].dimension_keys)["expense_class"] == "OVERHEAD" and rows["Rent"].engine_result_ref == "ex-rent"
    assert "UNCLASSIFIED" in rows["Misc"].labels  # an unconfirmed class is visible as such
    total = [f for f in p.figures if not f.dimension_keys][0]
    assert total.value_paise == 1_500 and total.status == "PARTIAL" and total.exclusions == (("HELD_POSSIBLE_DUPLICATE", 1),) and "EXPENSES_ON_HOLD" in p.labels
    assert p.rows_excluded == 1


def test_an_empty_ledger_is_unavailable_with_one_data_request_never_zero() -> None:
    from cfo.planner.executor import ExpenseView

    be = FakeBackend()
    be.expenses = ExpenseView((), (), None, None, 0)
    p = answer(be, BREAKDOWN)
    f = p.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and len(p.data_requests) == 1


def test_the_owner_drawing_view_filters_by_class() -> None:
    be = FakeBackend()
    from cfo.planner.executor import ExpenseGroupView, ExpenseView
    be.expenses = ExpenseView((ExpenseGroupView("Owner draw", "OWNER_DRAWING", 700, 1, "ex-draw"), ExpenseGroupView("Rent", "OVERHEAD", 1_200, 1, "ex-rent")), (), 1_900, "ex-all", 2)
    p = answer(be, OWNER_VIEW)
    assert [(dict(f.dimension_keys)["expense_category"], f.value_paise) for f in p.figures] == [("Owner draw", 700)]


def test_operating_profit_carries_its_provisional_status_the_exposed_entries_and_the_entry_count() -> None:
    p = answer(FakeBackend(), OPERATING)
    f = p.figures[0]
    assert f.value_paise == 2_500 and f.status == "PROVISIONAL" and f.engine_result_ref == "ref-op"
    assert f.exclusions == (("UNCLASSIFIED_EXPENSE", 2),) and "BASED_ON_3_EXPENSE_ENTRIES" in f.labels


def test_operating_profit_without_expense_data_is_unavailable_and_asks_once() -> None:
    be = FakeBackend()
    be.operating = EngineValue("OPERATING_PROFIT", False, reason="no overhead expense data or declaration for the period", missing_inputs=("expense_overhead_coverage",))
    p = answer(be, OPERATING)
    f = p.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and f.missing_inputs == ("expense_overhead_coverage",) and len(p.data_requests) == 1


def test_operating_profit_is_account_level_it_is_never_split_or_narrowed() -> None:
    by_mp = pj([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "OPERATING_PROFIT"}}])
    p = answer(FakeBackend(), by_mp)
    assert p.figures[0].status == "UNAVAILABLE" and "account-level" in (p.figures[0].unavailable_reason or "")
    one = pj([{"op": "filter", "params": {"dimension": "marketplace", "op": "eq", "value": "MEESHO"}}, {"op": "metric", "params": {"metric": "OPERATING_PROFIT"}}])
    q = answer(FakeBackend(), one)
    assert q.figures[0].status == "UNAVAILABLE" and "attributed" in (q.figures[0].unavailable_reason or "")


def test_a_partial_marketplace_book_withholds_operating_profit_rather_than_subtracting_all_overhead_from_a_partial_cp() -> None:
    cov_ok = {k: Fraction(1) for k in LIMITS.min_coverage}
    cov_bad = {**cov_ok, "cancellation_state": Fraction(0)}

    class Mixed(FakeBackend):
        def collect_stats(self, tenant_id: Any, plan: Any) -> DataStats:
            return DataStats(coverage_by_marketplace={"MEESHO": cov_ok, "AMAZON": cov_bad}, estimated_rows=10, estimated_groups=1)

    p = answer(Mixed(), OPERATING)
    f = [x for x in p.figures if x.metric_id == "OPERATING_PROFIT"][0]
    assert f.status == "UNAVAILABLE" and "every marketplace" in (f.unavailable_reason or "") and "AMAZON" in (f.unavailable_reason or "")


# ------------------------------------------------------------------------------------------------ advertising metrics (Phase 3b)
ADS = pj([{"op": "metric", "params": {"metric": "AD_SPEND"}}, {"op": "metric", "params": {"metric": "ROAS"}}])
ADS_BY_MP = pj([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "AD_SPEND"}}])


def test_ad_metrics_carry_status_labels_refs_and_an_exact_fraction() -> None:
    p = answer(FakeBackend(), ADS)
    by = {f.metric_id: f for f in p.figures}
    assert by["AD_SPEND"].value_paise == 3_000 and "AD_STATUS_KNOWN_SPEND" in by["AD_SPEND"].labels and by["AD_SPEND"].engine_result_ref == "ref-ad"
    assert by["ROAS"].value_fraction == "5/1" and by["ROAS"].value_paise is None and by["ROAS"].engine_result_ref == "ref-roas"


def test_ad_metrics_by_marketplace_name_an_unknown_marketplace_and_ask_once() -> None:
    p = answer(FakeBackend(), ADS_BY_MP)
    rows = {dict(f.dimension_keys).get("marketplace", "ALL"): f for f in p.figures}
    assert rows["MEESHO"].value_paise == 3_000 and rows["AMAZON"].status == "UNAVAILABLE" and rows["AMAZON"].value_paise is None
    assert len(p.data_requests) == 1


def test_ad_metrics_refuse_a_sku_scope_and_other_groupings() -> None:
    sku = pj([{"op": "filter", "params": {"dimension": "sku", "op": "eq", "value": "A"}}, {"op": "metric", "params": {"metric": "AD_SPEND"}}])
    assert answer(FakeBackend(), sku).figures[0].status == "UNAVAILABLE"
    by_period = pj([{"op": "group_by", "params": {"dimensions": ["period"]}}, {"op": "metric", "params": {"metric": "AD_SPEND"}}])
    assert answer(FakeBackend(), by_period).figures[0].status == "UNAVAILABLE"
