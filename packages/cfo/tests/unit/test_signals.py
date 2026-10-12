"""`cfo.reasoning.signals.compose_strategic_signals` — cfo-agent.md §7.5 (Strategic Insight
layer). Pure, no DB, no LLM — covers per-source signal building, the GOOD/on-track/non-fired
skip rule, the closed category->action-type mapping, and deterministic ranking/tiebreak.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from uuid import uuid4

import pytest

from cfo.reasoning.signals import (
    AnomalyFlagInput,
    DataRequestInput,
    ExpenseBudgetInput,
    FinancialHealthMetricInput,
    LeakFindingInput,
    compose_strategic_signals,
    signals_from_financial_health,
)


def test_good_band_financial_health_metric_produces_no_signal():
    signals = signals_from_financial_health(
        [FinancialHealthMetricInput(metric="CONTRIBUTION_MARGIN_PCT", band="GOOD", value_fraction=Fraction(15), engine_result_ref=uuid4())]
    )
    assert signals == []


def test_at_risk_margin_maps_to_profitability_category_and_action():
    ref = uuid4()
    signals = signals_from_financial_health(
        [FinancialHealthMetricInput(metric="CONTRIBUTION_MARGIN_PCT", band="AT_RISK", value_fraction=Fraction(3), engine_result_ref=ref)]
    )
    assert len(signals) == 1
    s = signals[0]
    assert s.category == "PROFITABILITY"
    assert s.recommended_action_type == "REVIEW_PRICING_OR_COGS"
    assert s.severity_rank == 3
    assert s.evidence[0].engine_result_ref == ref


def test_unknown_financial_health_metric_raises_rather_than_guessing():
    with pytest.raises(ValueError, match="no signal category"):
        signals_from_financial_health(
            [FinancialHealthMetricInput(metric="SOMETHING_ELSE_PCT", band="AT_RISK", value_fraction=Fraction(1), engine_result_ref=uuid4())]
        )


def test_on_track_expense_budget_produces_no_signal():
    signals = compose_strategic_signals(
        expense_budgets=[ExpenseBudgetInput(category="packaging", exceeded=False, remaining_paise=5_000)]
    )
    assert signals == []


def test_exceeded_expense_budget_produces_a_watch_signal():
    signals = compose_strategic_signals(
        expense_budgets=[ExpenseBudgetInput(category="packaging", exceeded=True, remaining_paise=-5_000)]
    )
    assert len(signals) == 1
    assert signals[0].category == "EXPENSE_BUDGET"
    assert signals[0].evidence[0].value_paise == -5_000


def test_open_data_request_produces_a_data_gap_signal():
    signals = compose_strategic_signals(
        data_requests=[DataRequestInput(requested_field="rto_outcome", reason="not classified", blocking_metric="CONTRIBUTION_PROFIT")]
    )
    assert len(signals) == 1
    assert signals[0].category == "DATA_GAP"
    assert "CONTRIBUTION_PROFIT" in signals[0].headline


def test_leak_finding_carries_amount_and_severity_through_unchanged():
    ref = uuid4()
    signals = compose_strategic_signals(
        leak_findings=[
            LeakFindingInput(
                leak_finding_id=uuid4(),
                leak_category="SETTLEMENT_SHORTFALL",
                severity="HIGH",
                amount_paise=125_00,
                marketplace="MEESHO",
                engine_result_ref=ref,
                confidence="VERIFIED",
            )
        ]
    )
    assert len(signals) == 1
    assert signals[0].severity_rank == 3
    assert signals[0].evidence[0].value_paise == 125_00
    assert signals[0].evidence[0].engine_result_ref == ref


def test_anomaly_flag_carries_score_through_unchanged():
    ref = uuid4()
    signals = compose_strategic_signals(
        anomaly_flags=[
            AnomalyFlagInput(
                metric="FEE_RATIO_PCT", method="Z_SCORE", target_ref="ACCOUNT-1",
                severity="MEDIUM", score=Fraction(Decimal("2.7")), decorates_engine_result_ref=ref,
            )
        ]
    )
    assert len(signals) == 1
    assert signals[0].category == "ANOMALY"
    assert signals[0].evidence[0].value_fraction == Fraction(Decimal("2.7"))


# --- deterministic ranking ------------------------------------------------------------------


def test_signals_are_ranked_at_risk_before_watch_before_open():
    signals = compose_strategic_signals(
        financial_health=[
            FinancialHealthMetricInput(metric="FEE_RATIO_PCT", band="AT_RISK", value_fraction=Fraction(40), engine_result_ref=uuid4()),
        ],
        expense_budgets=[ExpenseBudgetInput(category="storage", exceeded=True, remaining_paise=-100)],
        data_requests=[DataRequestInput(requested_field="rto_outcome", reason="x", blocking_metric=None)],
    )
    ranks = [s.severity_rank for s in signals]
    assert ranks == sorted(ranks, reverse=True)
    assert signals[0].category == "FEE_RATIO"  # AT_RISK (3) comes first


def test_ranking_is_deterministic_and_repeatable():
    kwargs = dict(
        financial_health=[
            FinancialHealthMetricInput(metric="FEE_RATIO_PCT", band="WATCH", value_fraction=Fraction(28), engine_result_ref=uuid4()),
            FinancialHealthMetricInput(metric="RETURN_RATE_PCT", band="WATCH", value_fraction=Fraction(15), engine_result_ref=uuid4()),
        ],
    )
    first = compose_strategic_signals(**kwargs)
    second = compose_strategic_signals(**kwargs)
    assert [s.headline for s in first] == [s.headline for s in second]


# --- Issue 20 (Metrion_24_Fixes): the same missing input listed twice ----------------------------------------------------------------------------------------------


def test_identical_open_data_requests_give_one_signal_each_distinct_one_is_kept():
    same = lambda: DataRequestInput(requested_field="supplier.quote", reason="No active quote exists for SKU-1.", blocking_metric="LANDED_COST")  # noqa: E731
    signals = compose_strategic_signals(
        data_requests=[
            same(),
            same(),  # a second failed run raised the same request again
            DataRequestInput(requested_field="supplier.quote", reason="No active quote exists for SKU-2.", blocking_metric="LANDED_COST"),  # another SKU: kept
            DataRequestInput(requested_field="supplier.quote", reason="No active quote exists for SKU-1.", blocking_metric="BATCH_SIZE"),  # another metric: kept
            DataRequestInput(requested_field="supplier.quote", reason="No active quote exists for SKU-1.", blocking_metric=None),  # none vs a metric: kept
        ]
    )
    headlines = sorted(s.headline for s in signals)
    assert headlines == [
        "Missing: supplier.quote",
        "Missing: supplier.quote (blocks BATCH_SIZE)",
        "Missing: supplier.quote (blocks LANDED_COST)",
        "Missing: supplier.quote (blocks LANDED_COST)",
    ]
    assert sorted(s.evidence[0].text_value for s in signals if s.headline.endswith("(blocks LANDED_COST)")) == [
        "No active quote exists for SKU-1.",
        "No active quote exists for SKU-2.",
    ]


def test_deduplication_keeps_the_first_occurrences_order_so_the_result_is_deterministic():
    reqs = [DataRequestInput(requested_field=f"f{i % 3}", reason="r", blocking_metric="M") for i in range(9)]
    assert [s.headline for s in compose_strategic_signals(data_requests=reqs)] == [f"Missing: f{i} (blocks M)" for i in range(3)]
