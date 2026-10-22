"""Minimum-coverage rule applied PER MARKETPLACE (cfo-query-planner.md V-CMP-1, owner decision 2026-10-21): the 95% threshold is kept, but each
marketplace is judged on its own. A marketplace that qualifies keeps its result; one that does not is shown as unavailable with its coverage and
reason; a consolidated total built from fewer than all marketplaces is labelled partial; and the evidence packet carries the percentages, the
excluded gross sales and the reasons. Boundary cases: exactly at the threshold passes, one line below fails, nothing measured fails, never defaulted."""

from __future__ import annotations

import json
from fractions import Fraction
from typing import Any
from uuid import UUID

import pytest

from cfo.planner.evidence import EvidencePacket, percent_text
from cfo.planner.executor import EngineValue
from cfo.planner.pipeline import MockPlannerProvider, PlannerAnswer
from cfo.planner.plan import parse_plan
from cfo.planner.sql_executor import Grouping, Scope, SetResult, SetRow
from cfo.planner.validator import DataStats, ValidatorLimits, validate

from .test_planner_pipeline import CONFIG, LIMITS, SEP, FakeBackend, T, ask, pj

NRR_INPUTS = ("sales_lines", "cancellation_state", "return_status", "rto_status")
THRESHOLD = Fraction(95, 100)


def cov(share: Fraction, **override: Fraction | None) -> dict[str, Fraction]:
    c = {k: share for k in LIMITS.min_coverage}
    for k, v in override.items():
        if v is None:
            c.pop(k)
        else:
            c[k] = v
    return c


class PerMarketplaceBackend(FakeBackend):
    """Gross sales and engine values per marketplace; coverage as configured."""

    def __init__(self, coverage: dict[str, dict[str, Fraction]], nrr: dict[str, int | None], gross: dict[str, int]) -> None:
        super().__init__()
        self.coverage = coverage
        self.nrr = nrr
        self.gross_by_mp = gross
        self.scopes_run: list[tuple[str, ...] | None] = []
        self.engine_scopes: list[tuple[str, ...] | None] = []

    def collect_stats(self, tenant_id: UUID, plan: Any) -> DataStats:
        return DataStats(coverage_by_marketplace=self.coverage, input_coverage={}, estimated_rows=100, estimated_groups=3)

    def _gross(self, scope: Scope) -> SetRow:
        mps = scope.marketplaces or tuple(self.gross_by_mp)
        return SetRow((), sum(self.gross_by_mp[m] for m in mps if m in self.gross_by_mp), 4, ())

    def run_set_metric(self, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, limit: int) -> SetResult:
        self.set_calls += 1
        self.scopes_run.append(scope.marketplaces)
        mps = scope.marketplaces or tuple(self.gross_by_mp)
        rows = tuple(SetRow((("marketplace", m),), self.gross_by_mp[m], 2, ()) for m in sorted(mps) if m in self.gross_by_mp) if group.dimensions else ()
        return SetResult(metric_id, rows, self._gross(scope), False, len(rows))

    def reference_row(self, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, keys: tuple[tuple[str, str], ...]) -> SetRow | None:
        if keys == ():
            return self._gross(scope)
        mp = dict(keys)["marketplace"]
        return SetRow(keys, self.gross_by_mp[mp], 2, ())

    def run_engine_metrics(self, tenant_id: UUID, period: Any, scope: Scope) -> dict[str, EngineValue]:
        self.engine_calls += 1
        self.engine_scopes.append(scope.marketplaces)
        mps = scope.marketplaces or tuple(self.nrr)
        vals = [self.nrr[m] for m in mps if m in self.nrr]
        if not vals or any(v is None for v in vals):
            return {"NET_REALIZED_REVENUE": EngineValue("NET_REALIZED_REVENUE", False, reason="no value")}
        return {"NET_REALIZED_REVENUE": EngineValue("NET_REALIZED_REVENUE", True, value_paise=sum(vals), engine_result_ref=f"nrr-{'+'.join(sorted(mps))}", confidence="PROVISIONAL")}  # type: ignore[arg-type]


NRR = pj([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])
NRR_BY_MP = pj([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])
GROSS_BY_MP = pj([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "GROSS_SALES"}}])


def packet(be: PerMarketplaceBackend, plan_json: str) -> EvidencePacket:
    r = ask(MockPlannerProvider([plan_json]), be)
    assert isinstance(r, PlannerAnswer), r
    return r.packet


def mixed() -> PerMarketplaceBackend:
    """Meesho fully covered; Amazon has no cancellation/RTO status at all (the real-world shape)."""
    return PerMarketplaceBackend(
        coverage={"MEESHO": cov(Fraction(1)), "AMAZON": cov(Fraction(1), cancellation_state=Fraction(0), rto_status=Fraction(0))},
        nrr={"MEESHO": 900, "AMAZON": None}, gross={"MEESHO": 1000, "AMAZON": 400})


# ------------------------------------------------------------------------------------------------ partial results
def test_a_qualifying_marketplace_keeps_its_result_and_the_total_is_labelled_partial() -> None:
    be = mixed()
    p = packet(be, NRR)
    consolidated = [f for f in p.figures if not f.dimension_keys][0]
    assert consolidated.value_paise == 900 and consolidated.status == "PROVISIONAL" and "PARTIAL_MARKETPLACE_COVERAGE" in consolidated.labels
    assert be.engine_scopes == [("MEESHO",)]  # the engine was asked about the qualifying marketplace only: Amazon is never silently folded in
    amazon = [f for f in p.figures if dict(f.dimension_keys).get("marketplace") == "AMAZON"][0]
    assert amazon.status == "UNAVAILABLE" and amazon.value_paise is None and "cancellation_state" in (amazon.unavailable_reason or "")
    assert "EXCLUDED_BY_COVERAGE" in amazon.labels and "PARTIAL_MARKETPLACE_COVERAGE" in p.labels


def test_a_verified_set_total_becomes_partial_and_each_marketplace_row_stays_independent() -> None:
    be = PerMarketplaceBackend(coverage={"MEESHO": cov(Fraction(1)), "AMAZON": cov(Fraction(1), sales_lines=Fraction(1, 2))}, nrr={}, gross={"MEESHO": 1000, "AMAZON": 400})
    p = packet(be, GROSS_BY_MP)
    by = {dict(f.dimension_keys).get("marketplace", "ALL"): f for f in p.figures}
    assert by["MEESHO"].value_paise == 1000 and by["MEESHO"].status == "VERIFIED" and "PARTIAL_MARKETPLACE_COVERAGE" not in by["MEESHO"].labels
    assert by["ALL"].value_paise == 1000 and by["ALL"].status == "PARTIAL" and "PARTIAL_MARKETPLACE_COVERAGE" in by["ALL"].labels  # Amazon's 400 is NOT in the total
    assert by["AMAZON"].status == "UNAVAILABLE"


def test_grouped_by_marketplace_shows_valid_rows_and_a_named_gap_for_the_rest() -> None:
    p = packet(mixed(), NRR_BY_MP)
    rows = {dict(f.dimension_keys)["marketplace"]: f for f in p.figures if f.dimension_keys}
    assert set(rows) == {"MEESHO", "AMAZON"} and rows["MEESHO"].value_paise == 900 and rows["AMAZON"].status == "UNAVAILABLE"


def test_every_marketplace_qualifying_leaves_no_partial_label() -> None:
    be = PerMarketplaceBackend(coverage={"MEESHO": cov(Fraction(1)), "FLIPKART": cov(Fraction(1))}, nrr={"MEESHO": 900, "FLIPKART": 100}, gross={"MEESHO": 1, "FLIPKART": 1})
    p = packet(be, NRR)
    f = p.figures[0]
    assert f.value_paise == 1000 and "PARTIAL_MARKETPLACE_COVERAGE" not in f.labels and "PARTIAL_MARKETPLACE_COVERAGE" not in p.labels
    assert all(c.included for c in p.coverage) and {c.marketplace for c in p.coverage} == {"MEESHO", "FLIPKART"}


def test_no_marketplace_qualifying_makes_the_metric_unavailable_with_each_reason() -> None:
    be = PerMarketplaceBackend(coverage={"MEESHO": cov(Fraction(9, 10)), "AMAZON": cov(Fraction(0))}, nrr={"MEESHO": 1, "AMAZON": 1}, gross={"MEESHO": 700, "AMAZON": 300})
    p = packet(be, NRR)
    f = p.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and "AMAZON:" in (f.unavailable_reason or "") and "MEESHO:" in (f.unavailable_reason or "")
    assert be.engine_calls == 0  # the engine is not asked about data that failed coverage
    assert all(not c.included for c in p.coverage)


# ------------------------------------------------------------------------------------------------ the evidence packet
def test_the_packet_carries_percentages_excluded_amounts_and_reasons() -> None:
    p = packet(mixed(), NRR)
    by = {c.marketplace: c for c in p.coverage}
    m, a = by["MEESHO"], by["AMAZON"]
    assert m.included and m.share == "1/1" and m.share_pct == "100.0" and m.threshold == "19/20" and m.threshold_pct == "95.0" and m.excluded_amount_paise is None
    assert not a.included and a.input_id == "cancellation_state" and a.share == "0/1" and a.share_pct == "0.0"
    assert "below the required 19/20" in (a.reason or "")
    assert a.excluded_amount_paise == 400 and a.excluded_line_count == 4 and a.excluded_basis == "GROSS_SALES_OF_EXCLUDED_MARKETPLACE" and a.excluded_ref
    assert len(p.data_requests) == 1  # one request for the excluded marketplace, not one per field
    again = EvidencePacket.from_json(p.to_json())
    assert again.coverage == p.coverage and again.content_json() == p.content_json()


def test_the_excluded_amount_is_cited_not_computed_here() -> None:
    p = packet(mixed(), NRR)
    amazon = [c for c in p.coverage if c.marketplace == "AMAZON"][0]
    assert amazon.excluded_ref and amazon.excluded_ref.startswith("mint-")  # minted through the backend like any other set result


# ------------------------------------------------------------------------------------------------ boundaries and missing data
@pytest.mark.parametrize("share,passes", [
    (Fraction(19, 20), True),        # exactly the threshold
    (Fraction(1), True),
    (Fraction(94999, 100000), False),  # a hair under
    (Fraction(18, 20), False),
    (Fraction(0), False),
])
def test_coverage_boundary_per_marketplace(share: Fraction, passes: bool) -> None:
    plan = parse_plan(json.loads(NRR))
    stats = DataStats(coverage_by_marketplace={"MEESHO": cov(share)})
    report = validate(plan, stats, LIMITS)
    assert ("NET_REALIZED_REVENUE" not in report.unavailable_metrics) is passes
    detail = report.coverage["NET_REALIZED_REVENUE"][0]
    assert detail.ok is passes and detail.marketplace == "MEESHO"


def test_each_marketplace_is_judged_independently_at_the_boundary() -> None:
    plan = parse_plan(json.loads(NRR))
    stats = DataStats(coverage_by_marketplace={"MEESHO": cov(Fraction(19, 20)), "FLIPKART": cov(Fraction(94, 100)), "AMAZON": cov(Fraction(1))})
    report = validate(plan, stats, LIMITS)
    ok = {d.marketplace: d.ok for d in report.coverage["NET_REALIZED_REVENUE"]}
    assert ok == {"AMAZON": True, "FLIPKART": False, "MEESHO": True}
    good, bad = report.partial_metrics()["NET_REALIZED_REVENUE"]
    assert good == ("AMAZON", "MEESHO") and [d.marketplace for d in bad] == ["FLIPKART"]


def test_the_weakest_input_decides_and_is_named() -> None:
    plan = parse_plan(json.loads(NRR))
    stats = DataStats(coverage_by_marketplace={"MEESHO": cov(Fraction(1), rto_status=Fraction(9, 10))})
    d = validate(plan, stats, LIMITS).coverage["NET_REALIZED_REVENUE"][0]
    assert not d.ok and d.input_id == "rto_status" and d.share == Fraction(9, 10)


def test_an_unmeasured_input_is_a_failure_for_that_marketplace_only() -> None:
    plan = parse_plan(json.loads(NRR))
    stats = DataStats(coverage_by_marketplace={"MEESHO": cov(Fraction(1)), "AMAZON": cov(Fraction(1), return_status=None)})
    report = validate(plan, stats, LIMITS)
    by = {d.marketplace: d for d in report.coverage["NET_REALIZED_REVENUE"]}
    assert by["MEESHO"].ok and not by["AMAZON"].ok and "was not measured" in (by["AMAZON"].reason or "")


def test_a_missing_threshold_is_config_missing_for_everyone() -> None:
    plan = parse_plan(json.loads(NRR))
    limits = ValidatorLimits(LIMITS.max_rows_scanned, LIMITS.max_groups, LIMITS.max_limit, {k: v for k, v in LIMITS.min_coverage.items() if k != "rto_status"},
                             LIMITS.low_explainability_share)
    report = validate(plan, DataStats(coverage_by_marketplace={"MEESHO": cov(Fraction(1)), "AMAZON": cov(Fraction(1))}), limits)
    assert "NET_REALIZED_REVENUE" in report.unavailable_metrics and "CONFIG_MISSING" in report.unavailable_metrics["NET_REALIZED_REVENUE"]


def test_a_plan_filtered_to_one_marketplace_is_judged_on_that_marketplace_alone() -> None:
    plan = parse_plan(json.loads(pj([{"op": "filter", "params": {"dimension": "marketplace", "op": "eq", "value": "MEESHO"}},
                                     {"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])))
    report = validate(plan, DataStats(coverage_by_marketplace={"MEESHO": cov(Fraction(1)), "AMAZON": cov(Fraction(0))}), LIMITS)
    assert [d.marketplace for d in report.coverage["NET_REALIZED_REVENUE"]] == ["MEESHO"] and report.unavailable_metrics == {} and report.partial_metrics() == {}


def test_a_marketplace_with_no_data_is_simply_absent_not_a_zero_coverage_failure() -> None:
    be = PerMarketplaceBackend(coverage={"MEESHO": cov(Fraction(1))}, nrr={"MEESHO": 900}, gross={"MEESHO": 5})
    p = packet(be, NRR)
    assert {c.marketplace for c in p.coverage} == {"MEESHO"} and "PARTIAL_MARKETPLACE_COVERAGE" not in p.labels


def test_nothing_in_scope_at_all_is_unavailable_with_a_reason() -> None:
    be = PerMarketplaceBackend(coverage={}, nrr={}, gross={})
    be.collect_stats = lambda tenant_id, plan: DataStats(input_coverage=cov(Fraction(0)))  # type: ignore[method-assign]
    p = packet(be, NRR)
    f = p.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and "available for 0/1" in (f.unavailable_reason or "")


def test_old_whole_scope_callers_keep_the_old_rule() -> None:
    plan = parse_plan(json.loads(NRR))
    report = validate(plan, DataStats(input_coverage=cov(Fraction(1, 2))), LIMITS)
    assert "NET_REALIZED_REVENUE" in report.unavailable_metrics and report.coverage["NET_REALIZED_REVENUE"][0].marketplace == "ALL"


# ------------------------------------------------------------------------------------------------ percentages never flatter the data
@pytest.mark.parametrize("n,d,text", [(19, 20, "95.0"), (949, 1000, "94.9"), (94999, 100000, "94.9"), (1, 3, "33.3"), (0, 5, "0.0"), (5, 5, "100.0"), (0, 0, "0.0")])
def test_percent_text_truncates_and_never_rounds_up(n: int, d: int, text: str) -> None:
    assert percent_text(n, d) == text
