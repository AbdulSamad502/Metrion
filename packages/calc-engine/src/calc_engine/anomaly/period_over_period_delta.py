"""PERIOD_OVER_PERIOD_DELTA — docs/specs/anomaly-detection.md §6.3.

Deltas `d_i = x_{i+1} - x_i` for `i = 1..n-1` (`n-1` deltas total). Baseline deltas =
`d_1..d_{n-2}`; delta under test = `d_{n-1}` (the most recent). `baseline_mean`/
`baseline_stdev` computed over the baseline deltas exactly as `z_score.py` computes them over
the raw baseline (same `_stats.mean_and_sample_variance`/`decimal_stdev` helpers, same
zero-variance guard). `score = (d_{n-1} - baseline_mean) / baseline_stdev` — a z-score
computed on the delta series, not the raw series. `fired`/`severity` derive from
`delta_severity_bands` (§5.3, the one method whose severity is graded in V1, not binary).
"""

from __future__ import annotations

from datetime import date, datetime
from fractions import Fraction
from typing import Sequence
from uuid import UUID, uuid4

from calc_engine.anomaly._stats import decimal_stdev, mean_and_sample_variance, z_score_value
from calc_engine.anomaly.types import (
    METHOD_PERIOD_OVER_PERIOD_DELTA,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SEVERITY_NOT_ANOMALOUS,
    AnomalyFlag,
    AnomalyInsufficientHistory,
    AnomalyThreshold,
    AnomalyZeroVariance,
    SeriesPoint,
)
from calc_engine.types import Confidence, Paise, combine_confidence

# §6.2 — the engine floor: 5 raw points -> 4 deltas (3 baseline + 1 tested). Tenant
# configuration (`threshold.min_series_length`) may raise this but never lower it (B7).
ENGINE_MIN_SERIES_LENGTH = 5

FORMULA_VERSION = "ANOMALY_PERIOD_OVER_PERIOD_DELTA.v1"


def _as_fraction(value: "Paise | Fraction") -> Fraction:
    return Fraction(value.value) if isinstance(value, Paise) else value


def _severity_from_bands(abs_score: Fraction, bands: dict[str, Fraction]) -> str:
    """§6.3: `|score| >= bands.high` -> HIGH; `>= bands.medium` -> MEDIUM;
    `>= bands.low` -> LOW; else NOT_ANOMALOUS. Checked strongest-first so a score meeting
    more than one band's threshold reports its highest applicable severity."""
    if abs_score >= bands["high"]:
        return SEVERITY_HIGH
    if abs_score >= bands["medium"]:
        return SEVERITY_MEDIUM
    if abs_score >= bands["low"]:
        return SEVERITY_LOW
    return SEVERITY_NOT_ANOMALOUS


def period_over_period_delta(
    series: Sequence[SeriesPoint],
    *,
    tenant_id: UUID,
    target_ref: str,
    threshold: AnomalyThreshold,
    computed_at: datetime,
    as_of_date: date,
) -> AnomalyFlag | AnomalyInsufficientHistory | AnomalyZeroVariance:
    """Pure statistics only (B8/AC12). `threshold` is an already-resolved `AnomalyThreshold`
    (`config_repo.resolve_anomaly_detection_config`) — this function never invents a floor
    or severity bands of its own (AC10)."""
    effective_min = max(ENGINE_MIN_SERIES_LENGTH, threshold.min_series_length)
    n = len(series)

    if n < effective_min:
        return AnomalyInsufficientHistory(
            metric=threshold.metric,
            method=METHOD_PERIOD_OVER_PERIOD_DELTA,
            target_ref=target_ref,
            series_length=n,
            min_series_length_required=effective_min,
        )

    values = [_as_fraction(p.value) for p in series]
    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]  # n-1 deltas
    baseline_deltas = deltas[:-1]  # d_1 .. d_{n-2}
    tested_delta = deltas[-1]  # d_{n-1}
    tested_point = series[-1]

    mean, variance = mean_and_sample_variance(baseline_deltas)
    if variance == 0:
        return AnomalyZeroVariance(
            metric=threshold.metric,
            method=METHOD_PERIOD_OVER_PERIOD_DELTA,
            target_ref=target_ref,
            series_length=n,
        )

    stdev = decimal_stdev(variance)
    score = z_score_value(tested_delta, mean, stdev)

    assert threshold.delta_severity_bands is not None, (
        "AnomalyThreshold.delta_severity_bands required for PERIOD_OVER_PERIOD_DELTA"
    )
    severity = _severity_from_bands(abs(score), threshold.delta_severity_bands)
    fired = severity != SEVERITY_NOT_ANOMALOUS

    data_confidence = combine_confidence(*[p.confidence for p in series], Confidence.DERIVED)

    return AnomalyFlag(
        id=uuid4(),
        tenant_id=tenant_id,
        metric=threshold.metric,
        target_ref=target_ref,
        period=tested_point.period,
        method=METHOD_PERIOD_OVER_PERIOD_DELTA,
        decorates_engine_result_ref=tested_point.engine_result_ref,
        source_engine_result_refs=tuple(p.engine_result_ref for p in series),
        score=score,
        threshold_used=threshold,
        fired=fired,
        severity=severity,
        data_confidence=data_confidence.value,
        series_length=n,
        min_series_length_required=effective_min,
        config_version=threshold.config_version,
        formula_version=FORMULA_VERSION,
        as_of_date=as_of_date,
        computed_at=computed_at,
    )
