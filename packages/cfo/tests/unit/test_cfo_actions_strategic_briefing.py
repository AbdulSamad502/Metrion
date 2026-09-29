"""`backend.services.cfo_actions.assemble_strategic_briefing` — cfo-agent.md §7.5 (Strategic
Insight layer). Every underlying function this composition calls
(`assemble_financial_health`, `run_anomaly_check`, `check_expense_budget`,
`leak_finding_repo.list_for_tenant`, `agent_data_request_repo.list_for_tenant`,
`narrate_figures`) is monkeypatched — no live Postgres or Ollama in this session — so these
tests verify the WIRING (which functions get called, with what, and in what order signals come
out), not the underlying functions' own correctness (already covered by their own test files).

Covers:
  - signals are gathered from Financial Health + persisted leak findings + open data requests
    by default (no opt-in flags needed).
  - anomaly checks and expense-budget checks are genuinely opt-in — never run unless the
    caller's request names a target_ref / categories.
  - exactly ONE `narrate_figures` call happens when signals exist and narration is requested —
    never one call per signal.
  - zero signals -> no LLM call at all, `narrative is None`.
  - `include_narration=False` -> no LLM call even with signals present.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from fractions import Fraction
from uuid import UUID, uuid4

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    AnomalyCheckOutcome,
    AnomalyMethodOutcome,
    ExpenseBudgetStatus,
    FinancialHealthOutcome,
    HealthBand,
    StrategicBriefingRequest,
    assemble_strategic_briefing,
)
from types import SimpleNamespace

from calc_engine.anomaly.types import METHOD_Z_SCORE
from calc_engine.types import Paise

_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)
_AS_OF = date(2026, 9, 27)


def _empty_financial_health(*_a, **_k) -> FinancialHealthOutcome:
    return FinancialHealthOutcome(overall_band=None, per_metric_bands={}, engine_result_refs=(), unavailable_reason="no data")


def _at_risk_financial_health(*_a, **_k) -> FinancialHealthOutcome:
    ref = uuid4()
    return FinancialHealthOutcome(
        overall_band=HealthBand.AT_RISK,
        per_metric_bands={"FEE_RATIO_PCT": HealthBand.AT_RISK},
        engine_result_refs=(ref,),
        per_metric_refs={"FEE_RATIO_PCT": ref},
        per_metric_values={"FEE_RATIO_PCT": Fraction(40)},
    )


def _patch_common(monkeypatch, *, financial_health=_empty_financial_health, leak_rows=(), data_request_rows=()):
    monkeypatch.setattr(cfo_actions_module, "assemble_financial_health", financial_health)
    monkeypatch.setattr(cfo_actions_module.leak_finding_repo, "list_for_tenant", lambda tenant_id: list(leak_rows))
    monkeypatch.setattr(
        cfo_actions_module.agent_data_request_repo, "list_for_tenant", lambda tenant_id: list(data_request_rows)
    )


def test_zero_signals_means_no_llm_call_and_narrative_is_none(monkeypatch) -> None:
    _patch_common(monkeypatch)
    calls = []
    monkeypatch.setattr(cfo_actions_module, "narrate_figures", lambda *a, **k: calls.append(1) or "narration")

    outcome = assemble_strategic_briefing(
        uuid4(), StrategicBriefingRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4())
    )

    assert outcome.signals == ()
    assert outcome.narrative is None
    assert calls == []


def test_financial_health_signal_triggers_exactly_one_narration_call(monkeypatch) -> None:
    _patch_common(monkeypatch, financial_health=_at_risk_financial_health)
    calls = []

    def _fake_narrate(provider, *, model, context, figures, gst_context=False):
        calls.append(figures)
        return "the fee ratio signal matters most"

    monkeypatch.setattr(cfo_actions_module, "narrate_figures", _fake_narrate)

    outcome = assemble_strategic_briefing(
        uuid4(), StrategicBriefingRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4())
    )

    assert len(outcome.signals) == 1
    assert outcome.signals[0].category == "FEE_RATIO"
    assert outcome.narrative == "the fee ratio signal matters most"
    assert len(calls) == 1  # exactly one narrate_figures call, for the whole briefing


def test_include_narration_false_skips_the_llm_call_even_with_signals(monkeypatch) -> None:
    _patch_common(monkeypatch, financial_health=_at_risk_financial_health)
    calls = []
    monkeypatch.setattr(cfo_actions_module, "narrate_figures", lambda *a, **k: calls.append(1) or "x")

    outcome = assemble_strategic_briefing(
        uuid4(),
        StrategicBriefingRequest(
            period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4(),
            include_narration=False,
        ),
    )

    assert len(outcome.signals) == 1
    assert outcome.narrative is None
    assert calls == []


def test_anomaly_check_is_opt_in_never_run_without_a_target_ref(monkeypatch) -> None:
    _patch_common(monkeypatch)
    anomaly_calls = []
    monkeypatch.setattr(cfo_actions_module, "run_anomaly_check", lambda *a, **k: anomaly_calls.append(1))

    assemble_strategic_briefing(
        uuid4(), StrategicBriefingRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4())
    )

    assert anomaly_calls == []  # no anomaly_target_ref supplied -> never called


def test_anomaly_check_runs_for_all_three_metrics_when_target_ref_given(monkeypatch) -> None:
    _patch_common(monkeypatch)
    seen_metrics = []

    def _fake_run_anomaly_check(tenant_id, request):
        seen_metrics.append(request.metric)
        # A lightweight stand-in carrying only the attributes `assemble_strategic_briefing`
        # actually reads off a flag (`fired`/`metric`/`method`/`target_ref`/`severity`/`score`/
        # `decorates_engine_result_ref`) — the real `AnomalyFlag` dataclass has several more
        # required fields irrelevant to this wiring test.
        flag = SimpleNamespace(
            metric=request.metric, method=METHOD_Z_SCORE, target_ref=request.target_ref,
            severity="HIGH", score=Fraction(Decimal("3.1")), decorates_engine_result_ref=uuid4(),
            fired=True,
        )
        return AnomalyCheckOutcome(
            target_ref=request.target_ref, metric=request.metric, series_length=10,
            methods=(
                AnomalyMethodOutcome(method=METHOD_Z_SCORE, flag=flag),
                AnomalyMethodOutcome(method="PERCENTILE_THRESHOLD"),
                AnomalyMethodOutcome(method="PERIOD_OVER_PERIOD_DELTA"),
            ),
        )

    monkeypatch.setattr(cfo_actions_module, "run_anomaly_check", _fake_run_anomaly_check)
    monkeypatch.setattr(cfo_actions_module, "narrate_figures", lambda *a, **k: "ok")

    outcome = assemble_strategic_briefing(
        uuid4(),
        StrategicBriefingRequest(
            period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4(),
            anomaly_target_ref="ACCOUNT-1",
        ),
    )

    assert set(seen_metrics) == {"MARGIN_PCT", "FEE_RATIO_PCT", "RETURN_RATE_PCT"}
    assert len(outcome.signals) == 3  # one fired flag per metric
    assert all(s.category == "ANOMALY" for s in outcome.signals)


def test_expense_budget_check_is_opt_in_and_skips_no_budget_set(monkeypatch) -> None:
    _patch_common(monkeypatch)
    budget_calls = []

    def _fake_check_budget(tenant_id, *, category, period_start, period_end):
        budget_calls.append(category)
        return ExpenseBudgetStatus(
            category=category, period_start=period_start, period_end=period_end,
            spent_paise=Paise(1_000), no_budget_set=True,
        )

    monkeypatch.setattr(cfo_actions_module, "check_expense_budget", _fake_check_budget)

    outcome = assemble_strategic_briefing(
        uuid4(),
        StrategicBriefingRequest(
            period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4(),
            expense_budget_categories=("packaging",),
        ),
    )

    assert budget_calls == ["packaging"]
    assert outcome.signals == ()  # no_budget_set -> skipped, not a fabricated signal


def test_leak_finding_and_data_request_signals_are_gathered_by_default(monkeypatch) -> None:
    leak_row = {
        "id": uuid4(), "leak_category": "SETTLEMENT_SHORTFALL", "severity": "HIGH",
        "amount_paise": 5_000, "marketplace": "MEESHO", "engine_result_ref": uuid4(),
        "confidence": "VERIFIED", "status": "NEW",
    }
    data_request_row = {
        "requested_field": "rto_outcome", "reason": "not classified",
        "blocking_metric": "CONTRIBUTION_PROFIT", "status": "OPEN",
    }
    _patch_common(monkeypatch, leak_rows=[leak_row], data_request_rows=[data_request_row])
    monkeypatch.setattr(cfo_actions_module, "narrate_figures", lambda *a, **k: "ok")

    outcome = assemble_strategic_briefing(
        uuid4(), StrategicBriefingRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4())
    )

    categories = {s.category for s in outcome.signals}
    assert categories == {"LEAK", "DATA_GAP"}


def test_resolved_leak_findings_are_excluded(monkeypatch) -> None:
    resolved_row = {
        "id": uuid4(), "leak_category": "SETTLEMENT_SHORTFALL", "severity": "HIGH",
        "amount_paise": 5_000, "marketplace": "MEESHO", "engine_result_ref": uuid4(),
        "confidence": "VERIFIED", "status": "RESOLVED",
    }
    _patch_common(monkeypatch, leak_rows=[resolved_row])

    outcome = assemble_strategic_briefing(
        uuid4(), StrategicBriefingRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4())
    )

    assert outcome.signals == ()


def test_pricing_and_supplier_comparisons_pass_through_as_signals(monkeypatch) -> None:
    from fractions import Fraction

    from cfo.reasoning.signals import PricingCandidateInput, SupplierRankInput

    _patch_common(monkeypatch)
    outcome = assemble_strategic_briefing(
        uuid4(),
        StrategicBriefingRequest(
            period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF, requested_by=uuid4(),
            pricing_candidates=(
                PricingCandidateInput(sku="SKU-1", price_paise=1000, margin_pct=Fraction(10), engine_result_ref=uuid4()),
                PricingCandidateInput(sku="SKU-1", price_paise=1100, margin_pct=Fraction(15), engine_result_ref=uuid4()),
            ),
            supplier_ranking=(
                SupplierRankInput(sku="SKU-1", supplier_name="A", landed_cost_paise=500, engine_result_ref=uuid4()),
                SupplierRankInput(sku="SKU-1", supplier_name="B", landed_cost_paise=700, engine_result_ref=uuid4()),
            ),
            include_narration=False,
        ),
    )

    categories = {s.category for s in outcome.signals}
    assert categories == {"PRICING", "SUPPLIER"}
