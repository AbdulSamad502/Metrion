"""Planner executor + pipeline + cache tests (cfo-query-planner.md §6.1, §6.4, §13, TP1–TP15). Mocked planner JSON, in-memory backend; no LLM,
no database. Adversarial model output is included on purpose."""

from __future__ import annotations

import json
from datetime import date
from fractions import Fraction
from typing import Any
from uuid import UUID, uuid4

import pytest

from cfo.planner import catalog as cat
from cfo.planner.cache import cache_key, tenant_prefix
from cfo.planner.cache_store import InMemoryEvidenceCache, RedisEvidenceCache
from cfo.planner.evidence import EvidencePacket, Figure, assert_no_raw_rows
from cfo.planner.executor import BridgeInputs, EngineValue, ExecutorConfig, ExpenseGroupView, ExpenseView
from cfo.planner.pipeline import (
    LlmPlannerProvider, MockPlannerProvider, PlannerAnswer, PlannerRefusal, build_prompt, catalog_summary, run_financial_query, PlannerRequest,
)
from cfo.planner.plan import PeriodRef
from cfo.planner.sql_executor import Grouping, Scope, SetResult, SetRow
from cfo.planner.validator import DataStats, ValidatorLimits

LIMITS = ValidatorLimits(
    max_rows_scanned=1_000_000, max_groups=5_000, max_limit=200,
    min_coverage={k: Fraction(95, 100) for k in (
        "sales_lines", "cogs_per_unit", "cancellation_state", "return_status", "rto_status", "rto_outcome", "fee_components", "settlement_lines", "settlement_history",
        "reconciliation_exceptions", "contribution_profit", "expense_entries", "expense_class", "ad_source")},
    low_explainability_share=Fraction(1, 10),
)
CONFIG = ExecutorConfig(statement_timeout_ms=5000, oracle_sample_size=3, max_ranking_groups=100)
GOOD = DataStats(input_coverage={k: Fraction(1) for k in LIMITS.min_coverage}, estimated_rows=1000, estimated_groups=5)
SEP = PeriodRef(date(2026, 9, 1), date(2026, 9, 30), date(2026, 10, 1))
OCT = PeriodRef(date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 1))
T = uuid4()


def row(mp: str | None, value: int | None, n: int = 3, excluded: tuple[tuple[str, int], ...] = ()) -> SetRow:
    return SetRow((("marketplace", mp),) if mp else (), value, n, excluded)


class FakeBackend:
    """In-memory PlannerBackend. `reference_wrong` mutates the reference to simulate a broken fast path."""

    def __init__(self) -> None:
        self.dv = 1
        self.bump_on_run = False
        self.gross = SetResult("GROSS_SALES", (row("MEESHO", 700), row("FLIPKART", 300)), row(None, 1000, 6), False, 2)
        self.reference_wrong = False
        self.engine: dict[str, EngineValue] = {
            "NET_REALIZED_REVENUE": EngineValue("NET_REALIZED_REVENUE", True, value_paise=900, engine_result_ref="ref-nrr", confidence="PROVISIONAL"),
            "CONTRIBUTION_PROFIT": EngineValue("CONTRIBUTION_PROFIT", True, value_paise=400, engine_result_ref="ref-cp", confidence="PROVISIONAL"),
        }
        self.requests: list[tuple[str, str]] = []
        self.set_calls = 0
        self.engine_calls = 0
        self.bridge: dict[date, BridgeInputs] = {}
        self.minted = 0
        self.expenses = ExpenseView((ExpenseGroupView('Rent', 'OVERHEAD', 1_200, 1, 'ex-rent'), ExpenseGroupView('Misc', 'OTHER_UNCLASSIFIED', 300, 2, 'ex-misc')),
                                    (('POSSIBLE_DUPLICATE', 1_200, 1),), 1_500, 'ex-all', 3)
        self.operating = EngineValue('OPERATING_PROFIT', True, value_paise=2_500, confidence='PROVISIONAL', engine_result_ref='ref-op', labels=('BASED_ON_3_EXPENSE_ENTRIES',),
                                     exclusions=(('UNCLASSIFIED_EXPENSE', 2),))

    def data_version(self, tenant_id: UUID) -> int:
        return self.dv

    def collect_stats(self, tenant_id: UUID, plan: Any) -> DataStats:
        return GOOD

    def run_set_metric(self, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, limit: int) -> SetResult:
        self.set_calls += 1
        if self.bump_on_run:
            self.dv += 1
            self.bump_on_run = False
        return self.gross

    def reference_row(self, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, keys: tuple[tuple[str, str], ...]) -> SetRow | None:
        src = self.gross.consolidated if keys == () else next(r for r in self.gross.rows if r.keys == keys)
        if self.reference_wrong:
            return SetRow(src.keys, (src.value_paise or 0) + 1, src.line_count, src.excluded)
        return src

    def mint_set_result(self, tenant_id: UUID, metric_id: str, scope: Scope, row_: SetRow, data_version: int, period: PeriodRef) -> str:
        self.minted += 1
        return f"mint-{self.minted}"

    def run_engine_metrics(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> dict[str, EngineValue]:
        self.engine_calls += 1
        return dict(self.engine)

    def run_bridge_inputs(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> BridgeInputs:
        return self.bridge[period.start]

    def run_expense_breakdown(self, tenant_id: UUID, period: Any) -> ExpenseView:
        return self.expenses

    def run_operating_profit(self, tenant_id: UUID, period: Any, scope: Scope) -> EngineValue:
        return self.operating

    def run_ad_metrics(self, tenant_id: UUID, period: Any, scope: Scope, by_marketplace: bool) -> dict:
        spend = EngineValue('AD_SPEND', True, value_paise=3_000, confidence='PROVISIONAL', engine_result_ref='ref-ad', labels=('AD_STATUS_KNOWN_SPEND',))
        roas = EngineValue('ROAS', True, value_fraction=Fraction(5), confidence='PROVISIONAL', engine_result_ref='ref-roas')
        unknown = EngineValue('AD_SPEND', False, reason='no advertising report', missing_inputs=('ad_source',))
        out: dict = {None: {'AD_SPEND': spend, 'ROAS': roas}}
        if by_marketplace:
            out['MEESHO'] = {'AD_SPEND': spend, 'ROAS': roas}
            out['AMAZON'] = {'AD_SPEND': unknown}
        return out

    def raise_data_request(self, tenant_id: UUID, metric_id: str, reason: str, missing_inputs: Any) -> str:
        self.requests.append((metric_id, reason))
        return f"dr-{len(self.requests)}"


def pj(steps: list[dict[str, Any]], periods: list[PeriodRef] | None = None, intent: str = "METRIC_BY_DIMENSION", limit: int = 50) -> str:
    ps = periods or [SEP]
    return json.dumps({"plan_version": "1", "intent": intent, "limit": limit, "steps": steps,
                       "periods": [{"start": p.start.isoformat(), "end": p.end.isoformat(), "as_of_date": p.as_of_date.isoformat()} for p in ps]})


GROSS_BY_MP = pj([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "GROSS_SALES"}}])


def ask(provider: MockPlannerProvider, backend: FakeBackend, periods: list[PeriodRef] | None = None, cache: Any = None, on_stage: Any = None):
    return run_financial_query("how much did I sell?", periods or [SEP], tenant_id=T, provider=provider, backend=backend, cache=cache, limits=LIMITS,
                               config=CONFIG, on_stage=on_stage)


# ----------------------------------------------------------------------------------------------- happy paths
def test_set_metric_by_marketplace_returns_refs_and_ties_out() -> None:
    be = FakeBackend()
    r = ask(MockPlannerProvider([GROSS_BY_MP]), be)
    assert isinstance(r, PlannerAnswer)
    figs = {dict(f.dimension_keys).get("marketplace", "ALL"): f for f in r.packet.figures}
    assert {k: f.value_paise for k, f in figs.items()} == {"MEESHO": 700, "FLIPKART": 300, "ALL": 1000}
    assert all(f.engine_result_ref for f in r.packet.figures)  # every figure cites its result (AC-P10 / V-DET-2)
    assert "CONSOLIDATED" in figs["ALL"].labels and r.packet.drilldown and r.packet.rows_examined == 6


def test_engine_metrics_flow_through_unchanged_with_their_confidence() -> None:
    be = FakeBackend()
    plan = pj([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}])
    r = ask(MockPlannerProvider([plan]), be)
    assert isinstance(r, PlannerAnswer)
    assert {f.metric_id: (f.value_paise, f.status, f.engine_result_ref) for f in r.packet.figures} == {
        "NET_REALIZED_REVENUE": (900, "PROVISIONAL", "ref-nrr"), "CONTRIBUTION_PROFIT": (400, "PROVISIONAL", "ref-cp")}
    assert be.engine_calls == 1  # one engine run serves both metrics of the period


def test_ranking_sorts_and_cuts_without_touching_values() -> None:
    be = FakeBackend()
    plan = pj([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "GROSS_SALES"}},
               {"op": "rank", "params": {"metric": "GROSS_SALES", "direction": "asc", "top_n": 1}}])
    r = ask(MockPlannerProvider([plan]), be)
    assert isinstance(r, PlannerAnswer)
    grouped = [f for f in r.packet.figures if f.dimension_keys]
    assert [(dict(f.dimension_keys)["marketplace"], f.value_paise) for f in grouped] == [("FLIPKART", 300)]


# ----------------------------------------------------------------------------------------------- the profit bridge (TP1 / AC-P7)
def _bridge_inputs(cp: int, nrr: int, fees: int, logistics: int = 0, ads: int = 0, rto: int = 0, cogs: int = 0, other: int = 0) -> BridgeInputs:
    comps = {"NET_REALIZED_REVENUE": nrr, "COGS": cogs, "MARKETPLACE_FEES": fees, "SHIPPING_LOGISTICS": logistics, "ADVERTISING_COSTS": ads,
             "RETURN_RTO_LOSSES": rto, "OTHER_ALLOCATED_COSTS": other}
    return BridgeInputs(EngineValue("CONTRIBUTION_PROFIT", True, value_paise=cp, engine_result_ref=f"cp-{cp}"), comps, {k: f"r-{k}" for k in comps})


BRIDGE = pj([{"op": "metric", "params": {"metric": "PROFIT_BRIDGE"}}, {"op": "compare", "params": {"kind": "period_over_period", "metric": "PROFIT_BRIDGE"}}],
            periods=[SEP, OCT], intent="PROFIT_BRIDGE")


def test_profit_bridge_drivers_plus_other_equal_the_delta_exactly() -> None:
    be = FakeBackend()
    be.bridge = {SEP.start: _bridge_inputs(cp=1000, nrr=5000, fees=800, logistics=600, cogs=2000, ads=300, rto=200, other=100),
                 OCT.start: _bridge_inputs(cp=550, nrr=4800, fees=900, logistics=650, cogs=1950, ads=350, rto=300, other=100)}
    r = ask(MockPlannerProvider([BRIDGE]), be, periods=[SEP, OCT])
    assert isinstance(r, PlannerAnswer) and r.packet.bridge is not None
    b = r.packet.bridge
    assert b.delta_paise == -450 and b.other_paise == 0 and b.reconciles
    assert sum(d.delta_paise for d in b.drivers) + b.other_paise == b.delta_paise


def test_a_bridge_with_a_missing_component_is_unavailable_with_one_data_request() -> None:
    be = FakeBackend()
    a = _bridge_inputs(cp=1000, nrr=5000, fees=800)
    broken = BridgeInputs(a.cp, {**a.components, "COGS": None}, a.component_refs)
    be.bridge = {SEP.start: broken, OCT.start: _bridge_inputs(cp=900, nrr=4000, fees=700)}
    r = ask(MockPlannerProvider([BRIDGE]), be, periods=[SEP, OCT])
    assert isinstance(r, PlannerAnswer) and r.packet.bridge is None
    f = r.packet.figures[-1]
    assert f.status == "UNAVAILABLE" and "COGS" in (f.unavailable_reason or "") and f.value_paise is None
    assert len(be.requests) == 1 and len(r.packet.data_requests) == 1


# ----------------------------------------------------------------------------------------------- unavailable is never zero
def test_unbuilt_metric_is_an_honest_unavailable_figure_with_one_request_not_a_zero() -> None:
    be = FakeBackend()
    plan = pj([{"op": "metric", "params": {"metric": "SETTLEMENT_LAG_DAYS"}}])
    r = ask(MockPlannerProvider([plan]), be)
    assert isinstance(r, PlannerAnswer)
    f = r.packet.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and "not yet computable" in (f.unavailable_reason or "")
    assert len(r.packet.data_requests) == 1


def test_an_unavailable_engine_metric_keeps_its_reason_and_raises_a_request() -> None:
    be = FakeBackend()
    be.engine["CONTRIBUTION_PROFIT"] = EngineValue("CONTRIBUTION_PROFIT", False, reason="no cost price for SKU-1", missing_inputs=("cogs_per_unit",))
    r = ask(MockPlannerProvider([pj([{"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}])]), be)
    assert isinstance(r, PlannerAnswer)
    f = r.packet.figures[0]
    assert f.status == "UNAVAILABLE" and f.unavailable_reason == "no cost price for SKU-1" and f.missing_inputs == ("cogs_per_unit",)
    assert be.requests == [("CONTRIBUTION_PROFIT", "no cost price for SKU-1")]


def test_low_coverage_makes_the_metric_unavailable_without_failing_the_plan() -> None:
    class Thin(FakeBackend):
        def collect_stats(self, tenant_id: UUID, plan: Any) -> DataStats:
            return DataStats(input_coverage={**{k: Fraction(1) for k in LIMITS.min_coverage}, "sales_lines": Fraction(1, 2)}, estimated_rows=10, estimated_groups=1)

    r = ask(MockPlannerProvider([GROSS_BY_MP]), Thin())
    assert isinstance(r, PlannerAnswer) and all(f.status == "UNAVAILABLE" for f in r.packet.figures)


# ----------------------------------------------------------------------------------------------- refusals (adversarial planner output)
BAD_INJECT = json.dumps({"plan_version": "1", "intent": "METRIC_BY_DIMENSION", "limit": 5, "tenant_id": str(uuid4()),
                         "periods": [{"start": "2026-09-01", "end": "2026-09-30", "as_of_date": "2026-10-01"}],
                         "steps": [{"op": "metric", "params": {"metric": "GROSS_SALES"}}]})
BAD_METRIC = pj([{"op": "metric", "params": {"metric": "TOTAL_PROFIT_MAGIC"}}])


def test_tp2_an_injected_tenant_id_is_refused_and_never_executed() -> None:
    be = FakeBackend()
    r = ask(MockPlannerProvider([BAD_INJECT, BAD_INJECT]), be)
    assert isinstance(r, PlannerRefusal) and r.code == "PLAN_MALFORMED" and "V-SCH-3" in r.rule_ids
    assert be.set_calls == 0 and be.engine_calls == 0


def test_tp3_unknown_metric_is_refused_after_exactly_one_retry_that_shows_the_errors() -> None:
    be = FakeBackend()
    prov = MockPlannerProvider([BAD_METRIC, BAD_METRIC])
    r = ask(prov, be)
    assert isinstance(r, PlannerRefusal) and r.code == "PLAN_INVALID" and "V-SCH-1" in r.rule_ids
    assert len(prov.requests) == 2 and prov.requests[0].errors == () and any("V-SCH-1" in e for e in prov.requests[1].errors)
    assert be.set_calls == 0


def test_a_valid_second_attempt_is_accepted() -> None:
    prov = MockPlannerProvider([BAD_METRIC, GROSS_BY_MP])
    r = ask(prov, FakeBackend())
    assert isinstance(r, PlannerAnswer) and r.attempts == 2


def test_tp15_malformed_json_is_an_honest_failure_not_a_guess() -> None:
    r = ask(MockPlannerProvider(["I think you sold a lot!", "still not json"]), FakeBackend())
    assert isinstance(r, PlannerRefusal) and r.code == "PLAN_MALFORMED"
    assert not any(ch.isdigit() for ch in r.message)  # a refusal never carries a figure


def test_a_model_failure_is_reported_not_papered_over() -> None:
    r = ask(MockPlannerProvider([TimeoutError("ollama down")]), FakeBackend())
    assert isinstance(r, PlannerRefusal) and r.code == "PLANNER_ERROR"


def test_the_planner_may_not_widen_or_change_the_period() -> None:
    wide = PeriodRef(date(2026, 1, 1), date(2026, 9, 30), date(2026, 10, 1))
    r = ask(MockPlannerProvider([pj([{"op": "metric", "params": {"metric": "GROSS_SALES"}}], periods=[wide])] * 2), FakeBackend())
    assert isinstance(r, PlannerRefusal) and "V-PIPE-1" in r.rule_ids


def test_a_fan_out_join_is_refused_before_any_execution() -> None:
    class FanOut(FakeBackend):
        def collect_stats(self, tenant_id: UUID, plan: Any) -> DataStats:
            from cfo.planner.validator import JoinFacts
            return DataStats(input_coverage=GOOD.input_coverage, joins={"sales_to_components": JoinFacts(100, 80, 5000, 9000, False)}, estimated_rows=10, estimated_groups=1)

    plan = pj([{"op": "join", "params": {"join_id": "sales_to_components"}}, {"op": "metric", "params": {"metric": "GROSS_SALES"}}])
    be = FanOut()
    r = ask(MockPlannerProvider([plan, plan]), be)
    assert isinstance(r, PlannerRefusal) and any(x.startswith("V-JOIN") for x in r.rule_ids) and be.set_calls == 0


# ----------------------------------------------------------------------------------------------- post-execution checks
def test_tp14_a_mutated_fast_path_fails_the_oracle_spot_check() -> None:
    be = FakeBackend()
    be.reference_wrong = True
    r = ask(MockPlannerProvider([GROSS_BY_MP]), be)
    assert isinstance(r, PlannerRefusal) and r.code == "PLAN_CHECK_FAILED" and "V-DET-3" in r.rule_ids


def test_marketplaces_that_do_not_add_up_fail_v_acc_2() -> None:
    be = FakeBackend()
    be.gross = SetResult("GROSS_SALES", (row("MEESHO", 700), row("FLIPKART", 300)), row(None, 1001, 6), False, 2)
    r = ask(MockPlannerProvider([GROSS_BY_MP]), be)
    assert isinstance(r, PlannerRefusal) and "V-ACC-2" in r.rule_ids


def test_a_figure_without_a_ref_is_a_post_execution_error() -> None:
    be = FakeBackend()
    be.engine["NET_REALIZED_REVENUE"] = EngineValue("NET_REALIZED_REVENUE", True, value_paise=900, engine_result_ref=None)
    r = ask(MockPlannerProvider([pj([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])]), be)
    assert isinstance(r, PlannerRefusal) and "V-DET-2" in r.rule_ids


def test_tp12_data_changing_mid_query_reruns_once_then_succeeds() -> None:
    be = FakeBackend()
    be.bump_on_run = True
    r = ask(MockPlannerProvider([GROSS_BY_MP]), be)
    assert isinstance(r, PlannerAnswer) and r.packet.data_version == 2 and be.set_calls == 2


def test_data_that_keeps_changing_is_reported_not_served() -> None:
    class Churn(FakeBackend):
        def run_set_metric(self, *a: Any, **k: Any) -> SetResult:
            self.dv += 1
            return self.gross

    r = ask(MockPlannerProvider([GROSS_BY_MP]), Churn())
    assert isinstance(r, PlannerRefusal) and r.code == "DATA_CHANGED"


# ----------------------------------------------------------------------------------------------- cache (AC-P8)
def test_identical_plan_hits_and_any_data_change_misses_and_tenants_never_share() -> None:
    cache = InMemoryEvidenceCache()
    be = FakeBackend()
    first = ask(MockPlannerProvider([GROSS_BY_MP]), be, cache=cache)
    assert isinstance(first, PlannerAnswer) and not first.packet.cached and be.set_calls == 1
    second = ask(MockPlannerProvider([GROSS_BY_MP]), be, cache=cache)
    assert isinstance(second, PlannerAnswer) and second.packet.cached and be.set_calls == 1  # served from cache: nothing re-queried
    assert second.packet.content_json() == first.packet.content_json()  # V-DET-1
    be.dv += 1  # a late upload / adjustment bumps the version
    third = ask(MockPlannerProvider([GROSS_BY_MP]), be, cache=cache)
    assert isinstance(third, PlannerAnswer) and not third.packet.cached and be.set_calls == 2
    other = run_financial_query("q", [SEP], tenant_id=uuid4(), provider=MockPlannerProvider([GROSS_BY_MP]), backend=be, cache=cache, limits=LIMITS, config=CONFIG)
    assert isinstance(other, PlannerAnswer) and not other.packet.cached  # another tenant never hits our entry
    assert all(k.startswith("cfo:ev:") for k in cache.keys()) and len({k.split(":")[2] for k in cache.keys()}) == 2


def test_a_mis_keyed_or_foreign_cache_entry_is_a_miss_never_a_wrong_answer() -> None:
    cache = InMemoryEvidenceCache()
    be = FakeBackend()
    ok = ask(MockPlannerProvider([GROSS_BY_MP]), be, cache=cache)
    assert isinstance(ok, PlannerAnswer)
    key = cache.keys()[0]
    assert cache.get(uuid4(), key, plan_hash=ok.packet.plan_hash, catalog_version=cat.CATALOG_VERSION, data_version=1) is None  # wrong tenant prefix
    assert cache.get(T, key, plan_hash="x" * 64, catalog_version=cat.CATALOG_VERSION, data_version=1) is None
    assert cache.get(T, key, plan_hash=ok.packet.plan_hash, catalog_version="stale", data_version=1) is None
    with pytest.raises(ValueError):
        cache.put(uuid4(), key, ok.packet)


def test_redis_cache_round_trips_survives_outages_and_requires_a_ttl() -> None:
    class Fake:
        def __init__(self) -> None:
            self.d: dict[str, str] = {}
            self.ex: int | None = None
            self.down = False

        def get(self, name: str) -> str | None:
            if self.down:
                raise ConnectionError("down")
            return self.d.get(name)

        def set(self, name: str, value: str, ex: int | None = None) -> None:
            if self.down:
                raise ConnectionError("down")
            self.d[name] = value
            self.ex = ex

    client = Fake()
    cache = RedisEvidenceCache(client, ttl_seconds=3600)
    be = FakeBackend()
    ask(MockPlannerProvider([GROSS_BY_MP]), be, cache=cache)
    assert client.ex == 3600 and len(client.d) == 1
    again = ask(MockPlannerProvider([GROSS_BY_MP]), be, cache=cache)
    assert isinstance(again, PlannerAnswer) and again.packet.cached
    client.down = True  # an outage is a miss, not a failed answer
    cold = ask(MockPlannerProvider([GROSS_BY_MP]), FakeBackend(), cache=cache)
    assert isinstance(cold, PlannerAnswer) and not cold.packet.cached
    with pytest.raises(ValueError):
        RedisEvidenceCache(client, ttl_seconds=0)


def test_cache_key_binds_tenant_data_version_catalog_and_formulas() -> None:
    from cfo.planner.plan import parse_plan
    plan = parse_plan(json.loads(GROSS_BY_MP))
    base = dict(tenant_id=T, data_version=1, formula_versions={"GROSS_SALES": "v1"})
    k = cache_key(plan, **base)
    assert k.startswith(tenant_prefix(T))
    assert cache_key(plan, **{**base, "data_version": 2}) != k
    assert cache_key(plan, **{**base, "formula_versions": {"GROSS_SALES": "v2"}}) != k
    assert cache_key(plan, **{**base, "catalog_version": "other"}) != k
    assert cache_key(plan, **{**base, "tenant_id": uuid4()}) != k


# ----------------------------------------------------------------------------------------------- packet hygiene, streaming, prompt
def test_packet_has_no_raw_rows_round_trips_and_is_deterministic() -> None:
    r = ask(MockPlannerProvider([GROSS_BY_MP]), FakeBackend())
    assert isinstance(r, PlannerAnswer)
    assert assert_no_raw_rows(r.packet, ["source_row_json", "order_ref", "sales_line_id", "tenant_id", "line_ref"]) == []
    assert EvidencePacket.from_json(r.packet.to_json()).content_json() == r.packet.content_json()
    r2 = ask(MockPlannerProvider([GROSS_BY_MP]), FakeBackend())
    assert isinstance(r2, PlannerAnswer) and r2.packet.content_json() == r.packet.content_json()


def test_figure_invariants_unavailable_never_carries_a_value() -> None:
    with pytest.raises(ValueError):
        Figure("GROSS_SALES", "UNAVAILABLE", value_paise=0)
    with pytest.raises(ValueError):
        Figure("GROSS_SALES", "VERIFIED")
    with pytest.raises(ValueError):
        Figure("GROSS_SALES", "VERIFIED", value_paise=1, engine_result_ref="a", estimate_ref="b")


def test_stage_events_stream_and_carry_no_figures() -> None:
    seen: list[str] = []
    cache = InMemoryEvidenceCache()
    be = FakeBackend()
    ask(MockPlannerProvider([GROSS_BY_MP]), be, cache=cache, on_stage=seen.append)
    assert seen[:2] == ["PLANNING", "VALIDATING"] and "QUERYING" in seen and seen[-1] == "FINALIZING"
    assert all(s.isalpha() and s.isupper() for s in seen)
    seen.clear()
    ask(MockPlannerProvider([GROSS_BY_MP]), be, cache=cache, on_stage=seen.append)
    assert seen[-1] == "CACHED" and "QUERYING" not in seen


def test_the_prompt_carries_the_catalog_and_the_question_but_no_tenant_or_figures() -> None:
    p = build_prompt(PlannerRequest("which marketplace earns most?", (SEP,)))
    assert "GROSS_SALES" in p and "which marketplace earns most?" in p and "2026-09-01" in p
    assert "tenant" not in json.dumps(catalog_summary()).lower()
    assert "rejected" not in p
    assert "rejected" in build_prompt(PlannerRequest("q", (SEP,), errors=("V-SCH-1: x",)))


def test_the_llm_adapter_is_text_in_text_out_and_uses_the_given_model() -> None:
    calls: list[tuple[str, str]] = []

    class Llm:
        def complete(self, *, model: str, prompt: str) -> str:
            calls.append((model, prompt))
            return GROSS_BY_MP

    r = ask(LlmPlannerProvider(Llm(), "local-planner"), FakeBackend())  # type: ignore[arg-type]
    assert isinstance(r, PlannerAnswer) and calls[0][0] == "local-planner" and "Question:" in calls[0][1]


def test_unsupported_grouping_and_filters_become_unavailable_figures_not_silent_drops() -> None:
    be = FakeBackend()
    r = ask(MockPlannerProvider([pj([{"op": "group_by", "params": {"dimensions": ["sku"]}}, {"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])]), be)
    assert isinstance(r, PlannerAnswer) and r.packet.figures[0].status == "UNAVAILABLE" and "not built yet" in (r.packet.figures[0].unavailable_reason or "")
