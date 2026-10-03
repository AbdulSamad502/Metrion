"""trends.budget and trends.report: budget exhaustion is a recorded state; a report is COMPLETE
iff at least one section has a cited finding (AC32, E25)."""

from __future__ import annotations

import dataclasses

import pytest

from slim_cmo.trends import budget as bd
from slim_cmo.trends import report as rp
from slim_cmo.trends.budget import BudgetDenial as D
from slim_cmo.trends.report import SectionOutcome as O, SectionState as St, Verdict
from slim_cmo.types import TrendSection as S

from ..factories import trend_config

ALL = list(S)


class TestQueryBudget:
    def test_sections_are_served_in_configured_priority_order(self):
        b = bd.QueryBudget(trend_config(), ALL)
        assert [s.value for s in b.ordered_sections()] == ["NICHE", "MARKET_NEWS", "NEW_PRODUCTS_BUZZ", "REPORTED_TACTICS", "ADJACENT"]

    def test_only_requested_sections_are_served(self):
        b = bd.QueryBudget(trend_config(), [S.ADJACENT, S.NICHE])
        assert [s.value for s in b.ordered_sections()] == ["NICHE", "ADJACENT"]
        assert b.try_spend(S.MARKET_NEWS).denial is D.SECTION_NOT_REQUESTED

    def test_a_section_spends_exactly_its_budget(self):
        b = bd.QueryBudget(trend_config(), ALL)
        results = [b.try_spend(S.REPORTED_TACTICS).allowed for _ in range(6)]  # budget is 4
        assert results == [True, True, True, True, False, False]
        assert b.try_spend(S.REPORTED_TACTICS).denial is D.SECTION_BUDGET_EXHAUSTED
        assert b.spent(S.REPORTED_TACTICS) == 4 and b.spent_total == 4

    def test_one_sections_exhaustion_does_not_starve_another(self):
        b = bd.QueryBudget(trend_config(), ALL)
        for _ in range(10):
            b.try_spend(S.ADJACENT)
        assert b.try_spend(S.NICHE).allowed

    def test_zero_section_budget_is_always_denied(self):
        cfg = trend_config(section_query_budgets={"NICHE": 0, "MARKET_NEWS": 5, "REPORTED_TACTICS": 4, "NEW_PRODUCTS_BUZZ": 3, "ADJACENT": 3})
        assert bd.QueryBudget(cfg, ALL).try_spend(S.NICHE).denial is D.SECTION_BUDGET_EXHAUSTED

    def test_total_never_exceeds_the_report_cap(self):
        b = bd.QueryBudget(trend_config(), ALL)
        n = sum(b.try_spend(s).allowed for s in ALL for _ in range(50))
        assert n == 20 == b.spent_total and b.remaining_total == 0

    def test_report_cap_binds_even_when_section_budgets_would_allow_more(self):
        """Defensive: a cap lowered after the budgets were set (config validation normally
        forbids sum(budgets) > cap, so this bypasses the loader on purpose)."""
        cfg = dataclasses.replace(trend_config(), max_queries_per_report=3)
        b = bd.QueryBudget(cfg, ALL)
        assert [b.try_spend(S.NICHE).allowed for _ in range(5)] == [True, True, True, False, False]
        assert b.try_spend(S.MARKET_NEWS).denial is D.REPORT_BUDGET_EXHAUSTED

    def test_usage_snapshot_for_the_evidence_section(self):
        b = bd.QueryBudget(trend_config(), ALL)
        b.try_spend(S.NICHE)
        b.try_spend(S.NICHE)
        usage = b.usage()
        assert usage["queries_used"] == 2 and usage["queries_allowed"] == 20
        assert usage["by_section"]["NICHE"] == {"used": 2, "allowed": 5}  # type: ignore[index]


class TestLimitSources:
    def test_cap_is_applied_in_priority_order_keeping_each_sections_order(self):
        cfg = dataclasses.replace(trend_config(), max_sources_per_report=5)
        per = {S.NICHE: list("abc"), S.MARKET_NEWS: list("def"), S.NEW_PRODUCTS_BUZZ: list("gh"), S.REPORTED_TACTICS: list("ij"), S.ADJACENT: list("kl")}
        kept, dropped = bd.limit_sources(per, cfg)
        assert kept[S.NICHE] == ("a", "b", "c") and kept[S.MARKET_NEWS] == ("d", "e")
        assert kept[S.NEW_PRODUCTS_BUZZ] == () and kept[S.ADJACENT] == ()
        assert dropped == 12 - 5

    def test_under_the_cap_nothing_is_dropped(self):
        kept, dropped = bd.limit_sources({S.NICHE: [1, 2]}, trend_config())
        assert kept[S.NICHE] == (1, 2) and dropped == 0 and kept[S.ADJACENT] == ()

    def test_findings_cap_keeps_the_first_n(self):
        kept, dropped = bd.cap_findings(list(range(9)), trend_config())  # cap is 4
        assert kept == (0, 1, 2, 3) and dropped == 5


def outcome(section, state=St.COMPLETE, n=1, reason=None):
    return O(section, state, n, reason)


def full(**overrides):
    base = {s: outcome(s) for s in S}
    base.update(overrides)
    return list(base.values())


class TestAssessReport:
    def test_all_sections_with_findings_is_complete_and_bills_one_unit(self):
        a = rp.assess_report(full())
        assert a.verdict is Verdict.COMPLETE and a.degraded == () and a.units_to_bill == 1 and a.failure_reason is None

    def test_one_section_with_one_finding_is_enough(self):
        outs = [outcome(s, St.UNAVAILABLE, 0, "BUDGET_EXHAUSTED") for s in S if s is not S.NICHE] + [outcome(S.NICHE)]
        a = rp.assess_report(outs)
        assert a.verdict is Verdict.COMPLETE and a.units_to_bill == 1
        assert [s for s, _ in a.degraded] == [S.MARKET_NEWS, S.REPORTED_TACTICS, S.NEW_PRODUCTS_BUZZ, S.ADJACENT]  # fixed enum order
        assert all(reason == "BUDGET_EXHAUSTED" for _, reason in a.degraded)

    def test_no_findings_anywhere_fails_and_bills_nothing(self):
        outs = [outcome(s, St.UNAVAILABLE, 0, "provider down") for s in S]
        a = rp.assess_report(outs)
        assert a.verdict is Verdict.FAILED and a.units_to_bill == 0 and a.failure_reason
        assert len(a.degraded) == 5

    def test_partial_sections_are_degraded_and_must_say_why(self):
        outs = full()
        outs[1] = outcome(S.MARKET_NEWS, St.PARTIAL, 2, "one provider timed out")
        a = rp.assess_report(outs)
        assert a.verdict is Verdict.COMPLETE and a.degraded == ((S.MARKET_NEWS, "one provider timed out"),)

    def test_every_section_must_be_accounted_for(self):
        with pytest.raises(ValueError, match="missing: ADJACENT"):
            rp.assess_report([outcome(s) for s in S if s is not S.ADJACENT])

    def test_a_section_cannot_appear_twice(self):
        with pytest.raises(ValueError, match="twice"):
            rp.assess_report(full() + [outcome(S.NICHE)])

    @pytest.mark.parametrize(
        "bad",
        [
            outcome(S.NICHE, St.UNAVAILABLE, 0, None),
            outcome(S.NICHE, St.UNAVAILABLE, 0, "  "),
            outcome(S.NICHE, St.UNAVAILABLE, 2, "x"),  # unavailable but claims findings
            outcome(S.NICHE, St.PARTIAL, 1, None),
            outcome(S.NICHE, St.COMPLETE, 0, None),  # complete with nothing cited
            outcome(S.NICHE, St.COMPLETE, -1, None),
        ],
    )
    def test_inconsistent_outcomes_are_programming_errors_not_silent_passes(self, bad):
        outs = [bad] + [outcome(s) for s in S if s is not S.NICHE]
        with pytest.raises(ValueError):
            rp.assess_report(outs)


class TestEvidenceNamesDegradedSections:
    def test_missing_mentions_are_reported(self):
        outs = [outcome(S.NICHE)] + [outcome(s, St.UNAVAILABLE, 0, "x") for s in S if s is not S.NICHE]
        a = rp.assess_report(outs)
        assert rp.undeclared_degraded_sections(a, [S.MARKET_NEWS, S.ADJACENT]) == (S.REPORTED_TACTICS, S.NEW_PRODUCTS_BUZZ)
        assert rp.undeclared_degraded_sections(a, list(S)) == ()

    def test_a_clean_report_has_nothing_to_declare(self):
        assert rp.undeclared_degraded_sections(rp.assess_report(full()), []) == ()
