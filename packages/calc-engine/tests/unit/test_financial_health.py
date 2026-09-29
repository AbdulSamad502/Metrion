"""financial_health.py — cfo-agent.md §6.15 (Financial Health Band).

Covers `assemble_financial_health`'s classification rule: per-metric banding by direction
(HIGHER_IS_WORSE/LOWER_IS_WORSE), "both thresholds absent -> metric skipped" (never a default
GOOD), overall band is the worst among classified metrics, and the real Unavailable outcome
when nothing could be classified at all.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from uuid import uuid4

from calc_engine.formulas.financial_health import (
    FinancialHealthConfigRow,
    FinancialHealthInput,
    HealthBand,
    assemble_financial_health,
)
from calc_engine.types import Unavailable

_MARGIN_ROW = FinancialHealthConfigRow(
    metric="CONTRIBUTION_MARGIN_PCT",
    direction="LOWER_IS_WORSE",
    at_risk_threshold_pct=Decimal("5.00"),
    watch_threshold_pct=Decimal("10.00"),
)
_FEE_ROW = FinancialHealthConfigRow(
    metric="FEE_RATIO_PCT",
    direction="HIGHER_IS_WORSE",
    at_risk_threshold_pct=Decimal("35.00"),
    watch_threshold_pct=Decimal("25.00"),
)
_RETURN_RATE_ROW = FinancialHealthConfigRow(
    metric="RETURN_RATE_PCT",
    direction="HIGHER_IS_WORSE",
    at_risk_threshold_pct=Decimal("20.00"),
    watch_threshold_pct=Decimal("10.00"),
)


def _input(metric: str, value: str) -> FinancialHealthInput:
    return FinancialHealthInput(metric=metric, value_fraction=Fraction(Decimal(value)), engine_result_ref=uuid4())


# --- per-metric direction ------------------------------------------------------------------


def test_lower_is_worse_margin_below_at_risk_threshold_is_at_risk():
    result = assemble_financial_health([_input("CONTRIBUTION_MARGIN_PCT", "3.00")], [_MARGIN_ROW])
    assert not isinstance(result, Unavailable)
    assert result.per_metric_bands["CONTRIBUTION_MARGIN_PCT"] == HealthBand.AT_RISK
    assert result.overall_band == HealthBand.AT_RISK


def test_lower_is_worse_margin_between_thresholds_is_watch():
    result = assemble_financial_health([_input("CONTRIBUTION_MARGIN_PCT", "7.50")], [_MARGIN_ROW])
    assert not isinstance(result, Unavailable)
    assert result.per_metric_bands["CONTRIBUTION_MARGIN_PCT"] == HealthBand.WATCH


def test_lower_is_worse_margin_above_watch_threshold_is_good():
    result = assemble_financial_health([_input("CONTRIBUTION_MARGIN_PCT", "15.00")], [_MARGIN_ROW])
    assert not isinstance(result, Unavailable)
    assert result.per_metric_bands["CONTRIBUTION_MARGIN_PCT"] == HealthBand.GOOD


def test_higher_is_worse_fee_ratio_above_at_risk_threshold_is_at_risk():
    result = assemble_financial_health([_input("FEE_RATIO_PCT", "40.00")], [_FEE_ROW])
    assert not isinstance(result, Unavailable)
    assert result.per_metric_bands["FEE_RATIO_PCT"] == HealthBand.AT_RISK


def test_higher_is_worse_fee_ratio_below_watch_threshold_is_good():
    result = assemble_financial_health([_input("FEE_RATIO_PCT", "10.00")], [_FEE_ROW])
    assert not isinstance(result, Unavailable)
    assert result.per_metric_bands["FEE_RATIO_PCT"] == HealthBand.GOOD


# --- overall band = worst among classified metrics ----------------------------------------


def test_overall_band_is_the_worst_among_classified_metrics():
    result = assemble_financial_health(
        [
            _input("CONTRIBUTION_MARGIN_PCT", "15.00"),  # GOOD
            _input("FEE_RATIO_PCT", "40.00"),  # AT_RISK
            _input("RETURN_RATE_PCT", "5.00"),  # GOOD
        ],
        [_MARGIN_ROW, _FEE_ROW, _RETURN_RATE_ROW],
    )
    assert not isinstance(result, Unavailable)
    assert result.overall_band == HealthBand.AT_RISK
    assert result.per_metric_bands == {
        "CONTRIBUTION_MARGIN_PCT": HealthBand.GOOD,
        "FEE_RATIO_PCT": HealthBand.AT_RISK,
        "RETURN_RATE_PCT": HealthBand.GOOD,
    }
    assert len(result.engine_result_refs) == 3
    assert set(result.per_metric_refs) == {"CONTRIBUTION_MARGIN_PCT", "FEE_RATIO_PCT", "RETURN_RATE_PCT"}
    assert result.per_metric_refs["FEE_RATIO_PCT"] in result.engine_result_refs


# --- absence handling: skipped, never defaulted --------------------------------------------


def test_metric_with_no_config_row_is_skipped_not_defaulted():
    result = assemble_financial_health(
        [_input("CONTRIBUTION_MARGIN_PCT", "15.00"), _input("FEE_RATIO_PCT", "40.00")],
        [_MARGIN_ROW],  # no FEE_RATIO_PCT row supplied
    )
    assert not isinstance(result, Unavailable)
    assert "FEE_RATIO_PCT" not in result.per_metric_bands
    assert result.overall_band == HealthBand.GOOD


def test_config_row_with_both_thresholds_absent_skips_the_metric():
    empty_row = FinancialHealthConfigRow(
        metric="CONTRIBUTION_MARGIN_PCT",
        direction="LOWER_IS_WORSE",
        at_risk_threshold_pct=None,
        watch_threshold_pct=None,
    )
    result = assemble_financial_health([_input("CONTRIBUTION_MARGIN_PCT", "3.00")], [empty_row])
    assert isinstance(result, Unavailable)


def test_no_input_could_be_classified_returns_unavailable_never_a_fabricated_good_band():
    result = assemble_financial_health([], [_MARGIN_ROW, _FEE_ROW])
    assert isinstance(result, Unavailable)
    assert result.missing_inputs == ("financial_health_config",)


def test_unknown_direction_raises_rather_than_silently_misclassifying():
    bad_row = FinancialHealthConfigRow(
        metric="CONTRIBUTION_MARGIN_PCT",
        direction="SIDEWAYS",
        at_risk_threshold_pct=Decimal("5.00"),
        watch_threshold_pct=Decimal("10.00"),
    )
    try:
        assemble_financial_health([_input("CONTRIBUTION_MARGIN_PCT", "3.00")], [bad_row])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "SIDEWAYS" in str(exc)
