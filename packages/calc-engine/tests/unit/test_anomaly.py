"""calc_engine.anomaly — docs/specs/anomaly-detection.md §12 (T1-T11, T13, T16).

Pure-computation scenarios only (T12/T14/T15/T17 are config-repo/Brain-3/persistence
concerns covered elsewhere or structurally true by construction — see this checkpoint's
final report)."""

from __future__ import annotations

import inspect
from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import UUID, uuid4

import pytest

from calc_engine.anomaly import _stats, period_over_period_delta as pod_module
from calc_engine.anomaly import percentile_threshold as pct_module
from calc_engine.anomaly import z_score as z_module
from calc_engine.anomaly.percentile_threshold import percentile_threshold
from calc_engine.anomaly.period_over_period_delta import period_over_period_delta
from calc_engine.anomaly.types import (
    SEVERITY_HIGH,
    SEVERITY_NOT_ANOMALOUS,
    AnomalyFlag,
    AnomalyInsufficientHistory,
    AnomalyThreshold,
    AnomalyZeroVariance,
    SeriesPoint,
)
from calc_engine.anomaly.z_score import z_score
from calc_engine.types import Confidence

TENANT = uuid4()
TARGET_REF = "SKU-001"
NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)
AS_OF = date(2026, 9, 25)


def _points(values: list, confidence: "Confidence | list[Confidence]" = Confidence.VERIFIED) -> list[SeriesPoint]:
    confidences = confidence if isinstance(confidence, list) else [confidence] * len(values)
    assert len(confidences) == len(values)
    return [
        SeriesPoint(
            period=date(2025, 1, 1 + i) if i < 28 else date(2025, 2, i - 27),
            value=v,
            confidence=c,
            engine_result_ref=uuid4(),
        )
        for i, (v, c) in enumerate(zip(values, confidences))
    ]


def _z_threshold(min_series_length: int = 8, z_score_threshold: Fraction = Fraction(5, 2)) -> AnomalyThreshold:
    return AnomalyThreshold(
        metric="MARGIN_PCT",
        method="Z_SCORE",
        min_series_length=min_series_length,
        config_version=1,
        z_score_threshold=z_score_threshold,
    )


def _percentile_threshold_config(min_series_length: int = 10, low: Fraction = Fraction(10), high: Fraction = Fraction(90)) -> AnomalyThreshold:
    return AnomalyThreshold(
        metric="MARGIN_PCT",
        method="PERCENTILE_THRESHOLD",
        min_series_length=min_series_length,
        config_version=1,
        percentile_low=low,
        percentile_high=high,
    )


def _delta_threshold(min_series_length: int = 5, bands: dict | None = None) -> AnomalyThreshold:
    return AnomalyThreshold(
        metric="MARGIN_PCT",
        method="PERIOD_OVER_PERIOD_DELTA",
        min_series_length=min_series_length,
        config_version=1,
        delta_severity_bands=bands or {"high": Fraction(3), "medium": Fraction(2), "low": Fraction(1)},
    )


# --- T1 / T8 — below floor, and empty series -----------------------------------------------


def test_t1_z_score_below_floor_returns_insufficient_history():
    series = _points([Fraction(1), Fraction(2), Fraction(3)])
    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyInsufficientHistory)
    assert result.series_length == 3
    assert result.min_series_length_required == 8


def test_t4_percentile_below_floor_returns_insufficient_history():
    series = _points([Fraction(i) for i in range(9)])
    result = percentile_threshold(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_percentile_threshold_config(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyInsufficientHistory)
    assert result.series_length == 9
    assert result.min_series_length_required == 10


def test_t6_delta_below_floor_returns_insufficient_history():
    series = _points([Fraction(1), Fraction(2), Fraction(3), Fraction(4)])
    result = period_over_period_delta(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_delta_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyInsufficientHistory)
    assert result.series_length == 4
    assert result.min_series_length_required == 5


@pytest.mark.parametrize(
    "fn, threshold_factory, expected_floor",
    [
        (z_score, _z_threshold, 8),
        (percentile_threshold, _percentile_threshold_config, 10),
        (period_over_period_delta, _delta_threshold, 5),
    ],
)
def test_t8_empty_series_returns_insufficient_history(fn, threshold_factory, expected_floor):
    result = fn([], tenant_id=TENANT, target_ref=TARGET_REF, threshold=threshold_factory(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyInsufficientHistory)
    assert result.series_length == 0
    assert result.min_series_length_required == expected_floor


# --- T2 — z-score fires on a genuine outlier, exactly at the floor -------------------------


def test_t2_z_score_fires_on_outlier_at_exact_floor():
    baseline = [Fraction(100), Fraction(102), Fraction(98), Fraction(101), Fraction(99), Fraction(103), Fraction(97)]
    series = _points(baseline + [Fraction(1000)])
    assert len(series) == 8

    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyFlag)
    assert result.fired is True
    assert result.severity == SEVERITY_HIGH
    assert result.series_length == 8
    assert result.decorates_engine_result_ref == series[-1].engine_result_ref
    assert result.source_engine_result_refs == tuple(p.engine_result_ref for p in series)


def test_t2_z_score_does_not_fire_within_baseline_spread():
    baseline = [Fraction(100), Fraction(102), Fraction(98), Fraction(101), Fraction(99), Fraction(103), Fraction(97)]
    series = _points(baseline + [Fraction(100)])
    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyFlag)
    assert result.fired is False
    assert result.severity == SEVERITY_NOT_ANOMALOUS


# --- T3 — zero-variance baseline (Z_SCORE) --------------------------------------------------


def test_t3_z_score_zero_variance_baseline_returns_zero_variance():
    series = _points([Fraction(50)] * 8)
    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyZeroVariance)
    assert result.series_length == 8


# --- T5 — percentile-threshold edge case ----------------------------------------------------


def test_t5_percentile_threshold_latest_point_is_series_minimum_fires():
    series = _points([Fraction(20), Fraction(30), Fraction(40), Fraction(50), Fraction(60), Fraction(70), Fraction(80), Fraction(90), Fraction(100), Fraction(5)])
    result = percentile_threshold(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_percentile_threshold_config(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyFlag)
    assert result.fired is True
    assert result.severity == SEVERITY_HIGH


def test_t5_percentile_threshold_interior_point_does_not_fire():
    series = _points([Fraction(v) for v in range(10, 110, 10)])  # 10..100, last=100 interior-ish boundary
    # Use a genuinely interior latest point instead of the series max/min.
    series = _points([Fraction(100), Fraction(20), Fraction(30), Fraction(40), Fraction(50), Fraction(60), Fraction(70), Fraction(80), Fraction(90), Fraction(55)])
    result = percentile_threshold(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_percentile_threshold_config(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyFlag)
    assert result.fired is False
    assert result.severity == SEVERITY_NOT_ANOMALOUS


# --- T7 — delta method zero-variance baseline deltas ----------------------------------------


def test_t7_delta_zero_variance_baseline_deltas_returns_zero_variance():
    series = _points([Fraction(10), Fraction(10), Fraction(10), Fraction(10), Fraction(50)])
    result = period_over_period_delta(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_delta_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyZeroVariance)
    assert result.series_length == 5


def test_delta_fires_on_genuine_outlier_delta():
    # deltas = [5, 20, 5, 960]; baseline=[5, 20, 5] (non-zero variance), tested=960.
    series = _points([Fraction(10), Fraction(15), Fraction(35), Fraction(40), Fraction(1000)])
    result = period_over_period_delta(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_delta_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyFlag)
    assert result.fired is True
    assert result.severity == SEVERITY_HIGH


# --- T10 — mixed confidence -> weakest wins --------------------------------------------------


def test_t10_mixed_confidence_data_confidence_is_weakest():
    baseline = [Fraction(100), Fraction(102), Fraction(98), Fraction(101), Fraction(99), Fraction(103), Fraction(97)]
    confidences = [Confidence.VERIFIED, Confidence.DERIVED, Confidence.VERIFIED, Confidence.MANUAL, Confidence.VERIFIED, Confidence.DERIVED, Confidence.VERIFIED, Confidence.VERIFIED]
    series = _points(baseline + [Fraction(100)], confidence=confidences)
    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyFlag)
    assert result.data_confidence == "MANUAL"


def test_all_verified_confidence_floors_at_derived():
    baseline = [Fraction(100), Fraction(102), Fraction(98), Fraction(101), Fraction(99), Fraction(103), Fraction(97)]
    series = _points(baseline + [Fraction(100)], confidence=Confidence.VERIFIED)
    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyFlag)
    # §6.4 — floored at DERIVED even though every input is VERIFIED (stronger than DERIVED).
    assert result.data_confidence == "DERIVED"


# --- T11 — no float anywhere in the computation path -----------------------------------------


@pytest.mark.parametrize("module", [z_module, pct_module, pod_module, _stats])
def test_t11_no_float_literal_or_cast_in_module_source(module):
    source = inspect.getsource(module)
    assert "float(" not in source
    assert " float " not in source


# --- T13 — determinism -------------------------------------------------------------------------


def test_t13_z_score_deterministic_for_fixed_inputs():
    baseline = [Fraction(100), Fraction(102), Fraction(98), Fraction(101), Fraction(99), Fraction(103), Fraction(97)]
    series = _points(baseline + [Fraction(1000)])
    threshold = _z_threshold()

    result_1 = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=threshold, computed_at=NOW, as_of_date=AS_OF)
    result_2 = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=threshold, computed_at=NOW, as_of_date=AS_OF)

    assert isinstance(result_1, AnomalyFlag) and isinstance(result_2, AnomalyFlag)
    assert result_1.score == result_2.score
    assert result_1.fired == result_2.fired
    assert result_1.severity == result_2.severity
    assert result_1.data_confidence == result_2.data_confidence
    assert result_1.id != result_2.id  # D3 — fresh uuid4() per computation, not stable identity


# --- T16 — insufficient-history / zero-variance are distinct, explicit outcomes ---------------


def test_t16_insufficient_history_is_not_a_flag_and_names_the_gap():
    series = _points([Fraction(1), Fraction(2)])
    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyInsufficientHistory)
    assert not isinstance(result, AnomalyFlag)
    assert result.reason == "INSUFFICIENT_HISTORY"


def test_t16_zero_variance_is_not_a_flag_and_names_the_gap():
    series = _points([Fraction(50)] * 8)
    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyZeroVariance)
    assert not isinstance(result, AnomalyFlag)
    assert result.reason == "ZERO_VARIANCE_BASELINE"


# --- AC6 provenance --------------------------------------------------------------------------


def test_decorates_and_source_refs_trace_real_series_points():
    baseline = [Fraction(100), Fraction(102), Fraction(98), Fraction(101), Fraction(99), Fraction(103), Fraction(97)]
    series = _points(baseline + [Fraction(1000)])
    result = z_score(series, tenant_id=TENANT, target_ref=TARGET_REF, threshold=_z_threshold(), computed_at=NOW, as_of_date=AS_OF)
    assert isinstance(result, AnomalyFlag)
    assert result.decorates_engine_result_ref == series[-1].engine_result_ref
    assert set(result.source_engine_result_refs) == {p.engine_result_ref for p in series}
    assert all(isinstance(r, UUID) for r in result.source_engine_result_refs)
