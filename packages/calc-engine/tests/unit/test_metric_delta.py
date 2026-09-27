"""metric_delta.py / compute_metric_delta — deterministic-engine.md §9."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from calc_engine.api.compute_metric import MetricResult, compute_metric_delta
from calc_engine.formulas.metric_delta import metric_delta
from calc_engine.types import RecognitionState, Unavailable

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def _result(**overrides: object) -> MetricResult:
    base = dict(
        id=uuid4(),
        metric_code="CONTRIBUTION_PROFIT",
        value_paise=1_000,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="VERIFIED",
        calculation_basis="test fixture",
        formula_version="CONTRIBUTION_PROFIT.v1",
        canonical_data_version="v1",
        as_of_date=None,
        input_refs=(),
        exclusions=(),
        computed_at=NOW,
        is_available=True,
        manual_adjustment_set=(),
        unavailable_reason=None,
    )
    base.update(overrides)
    return MetricResult(**base)  # type: ignore[arg-type]


# --- metric_delta -------------------------------------------------------------------------------


def test_metric_delta_mismatched_metric_code_raises():
    a = _result(metric_code="CONTRIBUTION_PROFIT")
    b = _result(metric_code="NET_REALIZED_REVENUE")
    with pytest.raises(ValueError) as exc_info:
        metric_delta(a, b)
    assert "CONTRIBUTION_PROFIT" in str(exc_info.value)
    assert "NET_REALIZED_REVENUE" in str(exc_info.value)


def test_metric_delta_positive():
    a = _result(value_paise=1_000)
    b = _result(value_paise=2_500)
    assert metric_delta(a, b) == 1_500


def test_metric_delta_negative():
    a = _result(value_paise=2_500)
    b = _result(value_paise=1_000)
    assert metric_delta(a, b) == -1_500


def test_metric_delta_zero():
    a = _result(value_paise=1_000)
    b = _result(value_paise=1_000)
    assert metric_delta(a, b) == 0


def test_metric_delta_result_a_unavailable():
    a = _result(is_available=False, value_paise=None, unavailable_reason="no NRR")
    b = _result(value_paise=2_500)
    result = metric_delta(a, b)
    assert isinstance(result, Unavailable)
    assert "result_a" in result.reason
    assert "no NRR" in result.reason


def test_metric_delta_result_b_unavailable():
    a = _result(value_paise=1_000)
    b = _result(is_available=False, value_paise=None, unavailable_reason="no NRR")
    result = metric_delta(a, b)
    assert isinstance(result, Unavailable)
    assert "result_b" in result.reason
    assert "no NRR" in result.reason


def test_metric_delta_both_unavailable():
    a = _result(is_available=False, value_paise=None, unavailable_reason="reason A")
    b = _result(is_available=False, value_paise=None, unavailable_reason="reason B")
    result = metric_delta(a, b)
    assert isinstance(result, Unavailable)
    assert "result_a" in result.reason
    assert "result_b" in result.reason
    assert "reason A" in result.reason
    assert "reason B" in result.reason


# --- compute_metric_delta ------------------------------------------------------------------------


def test_compute_metric_delta_result_shape():
    a = _result(value_paise=1_000)
    b = _result(value_paise=2_500)
    result = compute_metric_delta(a, b, computed_at=NOW)
    assert result.metric_code.endswith("_DELTA")
    assert result.metric_code == "CONTRIBUTION_PROFIT_DELTA"
    assert result.input_refs == (a.id, b.id)
    assert result.canonical_data_version == b.canonical_data_version
    assert result.value_paise == 1_500
    assert result.is_available is True
    assert isinstance(result.id, UUID)


def test_compute_metric_delta_confidence_combines_to_weakest():
    a = _result(confidence="VERIFIED")
    b = _result(confidence="MANUAL")
    result = compute_metric_delta(a, b, computed_at=NOW)
    assert result.confidence == "MANUAL"


def test_compute_metric_delta_unavailable_path():
    a = _result(is_available=False, value_paise=None, unavailable_reason="no NRR")
    b = _result(value_paise=2_500, canonical_data_version="v2")
    result = compute_metric_delta(a, b, computed_at=NOW)
    assert result.is_available is False
    assert result.value_paise is None
    assert result.unavailable_reason
    assert "result_a" in result.unavailable_reason
    assert result.metric_code == "CONTRIBUTION_PROFIT_DELTA"
    assert result.canonical_data_version == "v2"


def test_compute_metric_delta_mismatched_metric_code_propagates_value_error():
    a = _result(metric_code="CONTRIBUTION_PROFIT")
    b = _result(metric_code="NET_REALIZED_REVENUE")
    with pytest.raises(ValueError):
        compute_metric_delta(a, b, computed_at=NOW)


# --- Hypothesis property test -------------------------------------------------------------------


@given(
    value_a=st.integers(min_value=-10_000_000, max_value=10_000_000),
    value_b=st.integers(min_value=-10_000_000, max_value=10_000_000),
)
def test_compute_metric_delta_matches_arithmetic_when_both_available(value_a, value_b):
    a = _result(value_paise=value_a)
    b = _result(value_paise=value_b)
    result = compute_metric_delta(a, b, computed_at=NOW)
    assert result.value_paise == value_b - value_a
