"""Planner parse + validator + cache tests (cfo-query-planner.md §6.2, §13). Fully deterministic; no LLM,
no database. Plans below stand in for (mocked) model output, including adversarial output."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from fractions import Fraction
from typing import Any
from uuid import uuid4

import pytest

from cfo.planner import catalog as cat
from cfo.planner.cache import cache_key, tenant_prefix
from cfo.planner.plan import PlanParseError, QueryPlan, canonical_plan_json, parse_plan, plan_hash
from cfo.planner.validator import (
    DataStats,
    FigureProvenance,
    JoinFacts,
    ValidatorLimits,
    check_additivity,
    check_bridge,
    check_figures_have_refs,
    check_oracle_sample,
    validate,
    validate_static,
)

LIMITS = ValidatorLimits(
    max_rows_scanned=1_000_000, max_groups=5_000, max_limit=200,
    min_coverage={k: Fraction(95, 100) for k in (
        "sales_lines", "cogs_per_unit", "cancellation_state", "return_status", "rto_status", "rto_outcome",
        "fee_components", "settlement_lines", "settlement_history", "reconciliation_exceptions", "contribution_profit",
        "expense_entries", "expense_class", "ad_source")},
    low_explainability_share=Fraction(1, 10),
)

GOOD_STATS = DataStats(
    input_coverage={k: Fraction(1) for k in LIMITS.min_coverage},
    estimated_rows=80_000, estimated_groups=40,
)


def period(start: str, end: str, asof: str | None = None) -> dict[str, str]:
    return {"start": start, "end": end, "as_of_date": asof or end}


def plan_obj(steps: list[dict[str, Any]], *, intent: str = "METRIC_BY_DIMENSION", periods: list[dict[str, str]] | None = None, limit: int = 50) -> dict[str, Any]:
    return {"plan_version": "1", "intent": intent, "periods": periods or [period("2026-10-01", "2026-10-31")], "steps": steps, "limit": limit}


def cp_by_marketplace() -> dict[str, Any]:
    return plan_obj([
        {"op": "filter", "params": {"dimension": "marketplace", "op": "in", "value": ["MEESHO", "FLIPKART"]}},
        {"op": "group_by", "params": {"dimensions": ["marketplace"]}},
        {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}},
        {"op": "rank", "params": {"metric": "CONTRIBUTION_PROFIT", "direction": "desc", "top_n": 3}},
    ])


def parsed(obj: dict[str, Any]) -> QueryPlan:
    return parse_plan(obj)


def rules(report_or_list: Any) -> set[str]:
    vs = report_or_list.violations if hasattr(report_or_list, "violations") else report_or_list
    return {v.rule_id for v in vs}


def errs(vs: list[Any]) -> set[str]:
    return {v.rule_id for v in vs if v.severity.value == "ERROR"}


# ------------------------------------------------------------------------------------------ parsing
def test_good_plan_parses_and_validates_clean() -> None:
    p = parsed(cp_by_marketplace())
    assert validate_static(p, LIMITS) == []
    assert validate(p, GOOD_STATS, LIMITS).ok


def test_injected_tenant_id_anywhere_is_rejected() -> None:
    for place in ("top", "step", "period"):
        o = cp_by_marketplace()
        if place == "top":
            o["tenant_id"] = str(uuid4())
        elif place == "step":
            o["steps"][0]["params"]["tenant_id"] = str(uuid4())
        else:
            o["periods"][0]["tenantId"] = "x"
        with pytest.raises(PlanParseError) as ei:
            parse_plan(o)
        assert "V-SCH-3" in {v.rule_id for v in ei.value.violations}


@pytest.mark.parametrize("mutate,rule", [
    (lambda o: o.update(sql="SELECT 1"), "V-SCH-2"),
    (lambda o: o.update(plan_version="2"), "V-SCH-2"),
    (lambda o: o["steps"].append({"op": "raw_sql", "params": {}}), "V-SCH-1"),
    (lambda o: o["steps"][1]["params"].update(having="1=1"), "V-SCH-2"),
    (lambda o: o["steps"][2].update(extra=1), "V-SCH-2"),
    (lambda o: o.update(limit=10.5), "V-UNIT-1"),
    (lambda o: o["periods"][0].update(as_of_date="soon"), "V-SCH-4"),
    (lambda o: o["periods"][0].pop("as_of_date"), "V-SCH-4"),
    (lambda o: o.update(periods=[]), "V-SCH-4"),
    (lambda o: o.update(steps=[]), "V-SCH-2"),
])
def test_malformed_or_adversarial_json_is_rejected_by_the_parser(mutate: Any, rule: str) -> None:
    o = cp_by_marketplace()
    mutate(o)
    with pytest.raises(PlanParseError) as ei:
        parse_plan(o)
    assert rule in {v.rule_id for v in ei.value.violations}


def test_non_object_plan_rejected() -> None:
    with pytest.raises(PlanParseError):
        parse_plan("DROP TABLE sales_line")
    with pytest.raises(PlanParseError):
        parse_plan([1, 2])


# ------------------------------------------------------------------------------ V-SCH static rules
@pytest.mark.parametrize("steps,rule", [
    ([{"op": "metric", "params": {"metric": "INVENTED_PROFIT"}}], "V-SCH-1"),
    ([{"op": "group_by", "params": {"dimensions": ["customer_pincode"]}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}], "V-SCH-1"),
    ([{"op": "filter", "params": {"dimension": "marketplace", "op": "like", "value": "A%"}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}], "V-SCH-1"),
    ([{"op": "filter", "params": {"dimension": "marketplace", "op": "eq", "value": "SNAPDEAL"}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}], "V-SCH-1"),
    ([{"op": "join", "params": {"join_id": "sales_to_anything"}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}], "V-JOIN-1"),
    ([{"op": "normalize", "params": {"kind": "multiply_by_1_18"}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}], "V-SCH-1"),
    ([{"op": "group_by", "params": {"dimensions": ["marketplace"], "period_granularity": "fortnight"}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}], "V-SCH-1"),
    ([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}], "V-SCH-5"),
    ([{"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}, {"op": "group_by", "params": {"dimensions": ["marketplace"]}}], "V-SCH-6"),
    ([{"op": "aggregate", "params": {"metric": "CONTRIBUTION_PROFIT"}}], "V-SCH-6"),
    ([{"op": "metric", "params": {"metric": "EXPENSE_BY_CATEGORY"}}], "V-SCH-6"),
])
def test_static_schema_rules_reject(steps: list[dict[str, Any]], rule: str) -> None:
    p = parsed(plan_obj(steps))
    assert rule in errs(validate_static(p, LIMITS))


def test_unknown_intent_rejected() -> None:
    p = parsed(plan_obj([{"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}], intent="DELETE_EVERYTHING"))
    assert "V-SCH-1" in errs(validate_static(p, LIMITS))


def test_period_rules() -> None:
    p = parsed(plan_obj([{"op": "metric", "params": {"metric": "GROSS_SALES"}}], periods=[period("2026-10-31", "2026-10-01")]))
    assert "V-SCH-4" in errs(validate_static(p, LIMITS))
    p = parsed(plan_obj([{"op": "metric", "params": {"metric": "GROSS_SALES"}}], periods=[period("2026-10-01", "2026-10-31", "2026-09-01")]))
    assert "V-SCH-4" in errs(validate_static(p, LIMITS))


def test_limit_bounds() -> None:
    for bad in (0, 201, -1):
        p = parsed(plan_obj([{"op": "metric", "params": {"metric": "GROSS_SALES"}}], limit=bad))
        assert "V-RES-2" in errs(validate_static(p, LIMITS))
    p = parsed(plan_obj([{"op": "metric", "params": {"metric": "GROSS_SALES"}}], limit=200))
    assert "V-RES-2" not in errs(validate_static(p, LIMITS))


# ----------------------------------------------------------------------------------------- V-GRN
def test_grain_rules() -> None:
    # CP at SKU grain is fine (line-grain metric).
    ok = parsed(plan_obj([{"op": "group_by", "params": {"dimensions": ["sku"]}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}]))
    assert validate_static(ok, LIMITS) == []
    # Settlement lag is a marketplace-level measure: cannot be cut by SKU (not an allowed dimension, and too fine).
    bad = parsed(plan_obj([{"op": "group_by", "params": {"dimensions": ["sku"]}}, {"op": "metric", "params": {"metric": "SETTLEMENT_LAG_DAYS"}}]))
    assert {"V-GRN-1", "V-GRN-2"} <= errs(validate_static(bad, LIMITS))
    # Account-level ad pool by marketplace is an allocation: allowed, labelled DERIVED, never an error.
    alloc = parsed(plan_obj([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "ROAS"}}]))
    vs = validate_static(alloc, LIMITS)
    assert errs(vs) == set()
    assert any(v.subject == "DERIVED_ALLOCATION" for v in vs)


# ---------------------------------------------------------------------------------------- V-PER
def test_period_comparison_rules() -> None:
    steps = [{"op": "group_by", "params": {"dimensions": ["marketplace"]}},
             {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}},
             {"op": "compare", "params": {"kind": "period_over_period", "metric": "CONTRIBUTION_PROFIT"}}]
    one = parsed(plan_obj(steps))
    assert "V-PER-2" in errs(validate_static(one, LIMITS))
    overlapping = parsed(plan_obj(steps, periods=[period("2026-09-01", "2026-09-30"), period("2026-09-15", "2026-10-15")]))
    assert "V-PER-5" in errs(validate_static(overlapping, LIMITS))
    unequal = parsed(plan_obj(steps, periods=[period("2026-09-01", "2026-09-30"), period("2026-10-01", "2026-10-15")]))
    vs = validate_static(unequal, LIMITS)
    assert errs(vs) == set() and any(v.subject == "UNEQUAL_PERIODS" for v in vs)
    equal = parsed(plan_obj(steps, periods=[period("2026-09-01", "2026-09-30"), period("2026-10-01", "2026-10-30")]))
    assert validate_static(equal, LIMITS) == []


def test_mixed_basis_is_labelled_not_hidden() -> None:
    p = parsed(plan_obj([{"op": "group_by", "params": {"dimensions": ["marketplace"]}},
                         {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}},
                         {"op": "metric", "params": {"metric": "SETTLEMENT_RECEIPTS"}}]))
    vs = validate_static(p, LIMITS)
    assert errs(vs) == set() and any(v.subject == "MIXED_BASIS" for v in vs)


def test_partial_period_labelled() -> None:
    p = parsed(cp_by_marketplace())
    stats = DataStats(input_coverage=GOOD_STATS.input_coverage, data_coverage_end={"MEESHO": date(2026, 10, 31), "FLIPKART": date(2026, 10, 12)})
    r = validate(p, stats, LIMITS)
    assert r.ok and "PARTIAL_PERIOD" in r.labels


# --------------------------------------------------------------------------------------- V-ACC-4
@pytest.mark.parametrize("cls", ["OWNER_DRAWING", "INVENTORY_PURCHASE", "CAPITAL", "TAX_ASSET"])
def test_non_pnl_classes_never_feed_a_profit_metric(cls: str) -> None:
    p = parsed(plan_obj([{"op": "filter", "params": {"dimension": "expense_class", "op": "eq", "value": cls}},
                         {"op": "metric", "params": {"metric": "OPERATING_PROFIT"}}]))
    assert "V-ACC-4" in errs(validate_static(p, LIMITS))


def test_owner_drawings_are_viewable_through_the_expense_breakdown() -> None:
    p = parsed(plan_obj([{"op": "filter", "params": {"dimension": "expense_class", "op": "eq", "value": "OWNER_DRAWING"}},
                         {"op": "group_by", "params": {"dimensions": ["expense_category"]}},
                         {"op": "aggregate", "params": {"metric": "EXPENSE_BY_CATEGORY"}}], intent="EXPENSE_BREAKDOWN"))
    assert validate_static(p, LIMITS) == []


# ---------------------------------------------------------------------------------------- V-JOIN
def joined_plan(join_id: str) -> QueryPlan:
    return parsed(plan_obj([{"op": "join", "params": {"join_id": join_id}},
                            {"op": "group_by", "params": {"dimensions": ["marketplace"]}},
                            {"op": "metric", "params": {"metric": "SETTLEMENT_RECEIPTS"}}]))


def good_join(**kw: Any) -> JoinFacts:
    base: dict[str, Any] = dict(unique_side_rows=1000, unique_side_distinct_keys=1000, control_total_before=5_000_000,
                                control_total_after=5_000_000, many_side_preaggregated=True)
    base.update(kw)
    return JoinFacts(**base)


def stats_with(jid: str, facts: JoinFacts | None) -> DataStats:
    return DataStats(joins={jid: facts} if facts else {}, input_coverage=GOOD_STATS.input_coverage, estimated_rows=10, estimated_groups=3)


def test_legitimate_one_to_many_executes() -> None:
    # An order with several fee/refund/adjustment rows: aggregate-then-join, control total ties, orders may match several lines.
    p = joined_plan("meesho_orders_to_settlement")
    r = validate(p, stats_with("meesho_orders_to_settlement", good_join(orders_matching_multiple_settlement_lines=312)), LIMITS)
    assert r.ok, r.errors


def test_fan_out_is_rejected_before_execution() -> None:
    p = joined_plan("meesho_orders_to_settlement")
    r = validate(p, stats_with("meesho_orders_to_settlement", good_join(control_total_after=7_300_000)), LIMITS)
    assert "V-JOIN-3" in rules(r) and not r.ok


def test_non_unique_one_side_rejected() -> None:
    p = joined_plan("meesho_orders_to_settlement")
    r = validate(p, stats_with("meesho_orders_to_settlement", good_join(unique_side_distinct_keys=990)), LIMITS)
    assert "V-JOIN-2" in rules(r) and not r.ok


def test_one_to_many_without_preaggregation_rejected() -> None:
    p = joined_plan("meesho_orders_to_settlement")
    r = validate(p, stats_with("meesho_orders_to_settlement", good_join(many_side_preaggregated=False)), LIMITS)
    assert "V-JOIN-4" in rules(r) and not r.ok


def test_settlement_line_matching_two_orders_rejected_unless_declared() -> None:
    p = joined_plan("meesho_orders_to_settlement")
    bad = validate(p, stats_with("meesho_orders_to_settlement", good_join(settlement_lines_matching_multiple_orders=2)), LIMITS)
    assert "V-JOIN-5" in rules(bad) and not bad.ok
    declared = validate(p, stats_with("meesho_orders_to_settlement", good_join(settlement_lines_matching_multiple_orders=2, declared_many_to_one_reason="one payout per batch")), LIMITS)
    assert declared.ok


def test_missing_join_facts_fail_closed() -> None:
    r = validate(joined_plan("meesho_orders_to_settlement"), stats_with("meesho_orders_to_settlement", None), LIMITS)
    assert "V-JOIN-2" in rules(r) and not r.ok


def test_no_stats_at_all_fails_closed() -> None:
    r = validate(parsed(cp_by_marketplace()), None, LIMITS)
    assert "V-RES-3" in rules(r) and not r.ok


def test_unmatched_rows_are_disclosed_not_dropped() -> None:
    r = validate(joined_plan("meesho_orders_to_settlement"), stats_with("meesho_orders_to_settlement", good_join(unmatched_left_rows=17)), LIMITS)
    assert r.ok and "UNMATCHED_ROWS" in r.labels


def test_amazon_join_blocked_pending_match_key_verification() -> None:
    p = joined_plan("amazon_orders_to_settlement")
    errors = [v for v in validate_static(p, LIMITS) if v.severity.value == "ERROR"]
    assert errors and errors[0].rule_id == "V-JOIN-7" and "pending match-key verification" in errors[0].message


def test_flipkart_join_is_provisional_not_blocked() -> None:
    r = validate(joined_plan("flipkart_orders_to_settlement"), stats_with("flipkart_orders_to_settlement", good_join()), LIMITS)
    assert r.ok and "PROVISIONAL_JOIN" in r.labels


# ---------------------------------------------------------------------------------------- V-DUP
def test_duplicate_natural_keys_rejected() -> None:
    s = DataStats(input_coverage=GOOD_STATS.input_coverage, natural_key_rows={"sales_line": (80_000, 79_850)})
    assert "V-DUP-1" in rules(validate(parsed(cp_by_marketplace()), s, LIMITS))


def test_two_active_cost_owners_rejected_until_seller_resolves() -> None:
    s = DataStats(input_coverage=GOOD_STATS.input_coverage, cost_owners={("advertising", "MEESHO:2026-10"): frozenset({"ADVERTISING_REPORT", "SELLER_EXPENSE"})})
    r = validate(parsed(cp_by_marketplace()), s, LIMITS)
    assert "V-DUP-2" in rules(r) and not r.ok


def test_single_owner_passes_and_unconfirmed_overlap_is_labelled() -> None:
    s = DataStats(input_coverage=GOOD_STATS.input_coverage, cost_owners={("advertising", "MEESHO:2026-10"): frozenset({"ADVERTISING_REPORT"})}, unconfirmed_overlap_expenses=4)
    r = validate(parsed(cp_by_marketplace()), s, LIMITS)
    assert r.ok and "EXCLUDED_OVERLAP_EXPENSES" in r.labels


# ---------------------------------------------------------------------------------------- V-CMP
def test_missing_cogs_makes_cp_unavailable_not_zero() -> None:
    cov = dict(GOOD_STATS.input_coverage)
    cov["cogs_per_unit"] = Fraction(40, 100)
    r = validate(parsed(cp_by_marketplace()), DataStats(input_coverage=cov), LIMITS)
    assert r.ok  # not a plan error — an honest UNAVAILABLE for that metric
    assert "CONTRIBUTION_PROFIT" in r.unavailable_metrics and "cogs_per_unit" in r.unavailable_metrics["CONTRIBUTION_PROFIT"]


def test_unmeasured_coverage_is_unavailable_not_assumed_full() -> None:
    r = validate(parsed(cp_by_marketplace()), DataStats(), LIMITS)
    assert "CONTRIBUTION_PROFIT" in r.unavailable_metrics and "not measured" in r.unavailable_metrics["CONTRIBUTION_PROFIT"]


def test_unconfigured_threshold_is_config_missing_not_a_guess() -> None:
    lim = ValidatorLimits(max_rows_scanned=10**6, max_groups=100, max_limit=200, min_coverage={}, low_explainability_share=Fraction(1, 10))
    r = validate(parsed(cp_by_marketplace()), GOOD_STATS, lim)
    assert r.unavailable_metrics["CONTRIBUTION_PROFIT"].startswith("CONFIG_MISSING")


# ---------------------------------------------------------------------------------------- V-RES
def test_resource_caps() -> None:
    p = parsed(cp_by_marketplace())
    big = DataStats(input_coverage=GOOD_STATS.input_coverage, estimated_rows=2_000_000)
    assert "V-RES-1" in rules(validate(p, big, LIMITS))
    wide = DataStats(input_coverage=GOOD_STATS.input_coverage, estimated_groups=50_000)
    assert "V-RES-1" in rules(validate(p, wide, LIMITS))


# ------------------------------------------------------------------------------- post-execution
def test_additivity_ok_and_failures() -> None:
    assert check_additivity("CONTRIBUTION_PROFIT", {"AMAZON": 10, "MEESHO": 20}, 30) == []
    assert errs(check_additivity("CONTRIBUTION_PROFIT", {"AMAZON": 10, "MEESHO": 20}, 31)) == {"V-ACC-2"}
    assert errs(check_additivity("CONTRIBUTION_PROFIT", {"AMAZON": 10, "MEESHO": None}, 10)) == {"V-ACC-2"}
    assert check_additivity("CONTRIBUTION_MARGIN_PCT", {"A": 1}, 99) == []  # ratios are not additive


def test_bridge_checks() -> None:
    assert check_bridge(-117_000, 0, LIMITS) == []
    assert "V-ACC-3" in errs(check_bridge(-117_000, -10_000, LIMITS))
    vs = check_bridge(-100_000, 0, LIMITS)
    assert vs == []
    labelled = check_bridge(-100_000, 20_000, LIMITS)
    assert any(v.subject == "LOW_EXPLAINABILITY" for v in labelled)


def test_every_figure_must_carry_a_ref_and_estimates_never_an_engine_ref() -> None:
    assert check_figures_have_refs([FigureProvenance("CONTRIBUTION_PROFIT", "VERIFIED", engine_result_ref="r1"),
                                    FigureProvenance("PRICE_BAND", "ESTIMATED", estimate_ref="e1"),
                                    FigureProvenance("FEE_RATIO_PCT", "UNAVAILABLE")]) == []
    assert errs(check_figures_have_refs([FigureProvenance("CONTRIBUTION_PROFIT", "VERIFIED")])) == {"V-DET-2"}
    assert errs(check_figures_have_refs([FigureProvenance("PRICE_BAND", "ESTIMATED", estimate_ref="e1", engine_result_ref="r1")])) == {"V-DET-2"}
    assert errs(check_figures_have_refs([FigureProvenance("PRICE_BAND", "ESTIMATED")])) == {"V-DET-2"}


def test_oracle_sample_mismatch_is_a_defect() -> None:
    assert check_oracle_sample({"SKU-1": 100, "SKU-2": None}, {"SKU-1": 100, "SKU-2": None}) == []
    assert errs(check_oracle_sample({"SKU-1": 100}, {"SKU-1": 101})) == {"V-DET-3"}
    assert errs(check_oracle_sample({"SKU-1": 100}, {})) == {"V-DET-3"}
    assert errs(check_oracle_sample({"SKU-1": None}, {"SKU-1": 0})) == {"V-DET-3"}  # unavailable != zero


# ----------------------------------------------------------------------------- determinism + cache
def test_plan_hash_is_canonical_and_label_independent() -> None:
    a = parsed(cp_by_marketplace())
    o = deepcopy(cp_by_marketplace())
    o["periods"][0]["label"] = "October"
    b = parsed(o)
    assert plan_hash(a) == plan_hash(b) and canonical_plan_json(a) == canonical_plan_json(b)
    o["limit"] = 51
    assert plan_hash(parsed(o)) != plan_hash(a)


def test_cache_key_isolation_and_invalidation() -> None:
    p = parsed(cp_by_marketplace())
    t1, t2 = uuid4(), uuid4()
    fv = {"CONTRIBUTION_PROFIT": "CONTRIBUTION_PROFIT.v1"}
    k = cache_key(p, tenant_id=t1, data_version=7, formula_versions=fv)
    assert k == cache_key(p, tenant_id=t1, data_version=7, formula_versions=fv)  # identical plan hits
    assert k.startswith(tenant_prefix(t1))
    assert k != cache_key(p, tenant_id=t1, data_version=8, formula_versions=fv)  # any ingest/adjustment misses
    assert k != cache_key(p, tenant_id=t2, data_version=7, formula_versions=fv)  # never cross-tenant
    assert k != cache_key(p, tenant_id=t1, data_version=7, formula_versions={"CONTRIBUTION_PROFIT": "CONTRIBUTION_PROFIT.v2"})
    assert k != cache_key(p, tenant_id=t1, data_version=7, formula_versions=fv, catalog_version="other")


# ------------------------------------------------------------------------------- catalog integrity
def test_catalog_references_are_consistent() -> None:
    for m in cat.METRICS.values():
        assert m.allowed_dimensions <= set(cat.DIMENSIONS), m.id
        for d in m.explainable_by:
            assert d in cat.METRICS, (m.id, d)
    for j in cat.JOINS.values():
        assert j.cardinality in {"ONE_TO_ONE", "MANY_TO_ONE", "ONE_TO_MANY"}
    assert len(cat.CATALOG_VERSION) == 64


def test_existing_engine_refs_resolve_and_new_metrics_are_flagged() -> None:
    """A non-new metric's engine_ref must name something real in calc_engine; unbuilt ones are `is_new`.
    This is the guard against the catalog quietly advertising a metric Brain 1 cannot compute."""
    import importlib
    import pkgutil

    import calc_engine.formulas as formulas_pkg
    import calc_engine.api.compute_metric as api

    names: set[str] = set(dir(api))
    for mod in pkgutil.iter_modules(formulas_pkg.__path__):
        names |= set(dir(importlib.import_module(f"calc_engine.formulas.{mod.name}")))
    unresolved = sorted(m.id for m in cat.METRICS.values() if not m.is_new and m.engine_ref and m.engine_ref not in names)
    assert unresolved == [], f"engine_ref does not resolve in calc_engine for: {unresolved}"
