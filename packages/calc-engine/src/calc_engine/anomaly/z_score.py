"""Z_SCORE — docs/specs/anomaly-detection.md §6.3.

Baseline = x_1 .. x_{n-1}; point under test = x_n (always the latest). `mean`/`variance`
exact `Fraction` arithmetic (sample variance, `n-2` denominator — the baseline itself has
`n-1` points, so `n-1-1` degrees of freedom). `stdev = sqrt(variance)` via bounded-precision
`Decimal` (`_stats.decimal_stdev`) — the one irrational intermediate this method touches.
`fired = abs(z) >= z_score_threshold`. `severity` is binary in V1 (§6.3's closing note, P3,
Q5): HIGH when fired, NOT_ANOMALOUS otherwise — no graded severity for this method yet.
"""

from __future__ import annotations

from datetime import date, datetime
from fractions import Fraction
from typing import Sequence
from uuid import UUID, uuid4

from calc_engine.anomaly._stats import mean_and_sample_variance, decimal_stdev, z_score_value
from calc_engine.anomaly.types import (
    METHOD_Z_SCORE,
    SEVERITY_HIGH,
    SEVERITY_NOT_ANOMALOUS,
    AnomalyFlag,
    AnomalyInsufficientHistory,
    AnomalyThreshold,
    AnomalyZeroVariance,
    SeriesPoint,
)
from calc_engine.types import Confidence, Paise, combine_confidence

# §6.2 — the engine floor. Tenant configuration (`threshold.min_series_length`) may raise
# this but never lower it (B7, mirroring compute_price_band's rule 1 precedent).
ENGINE_MIN_SERIES_LENGTH = 8

FORMULA_VERSION = "ANOMALY_Z_SCORE.v1"


def _as_fraction(value: "Paise | Fraction") -> Fraction:
    return Fraction(value.value) if isinstance(value, Paise) else value


def z_score(
    series: Sequence[SeriesPoint],
    *,
    tenant_id: UUID,
    target_ref: str,
    threshold: AnomalyThreshold,
    computed_at: datetime,
    as_of_date: date,
) -> AnomalyFlag | AnomalyInsufficientHistory | AnomalyZeroVariance:
    """Pure statistics only (B8/AC12) — no database query of any kind. `threshold` is an
    already-resolved `AnomalyThreshold` (see `config_repo.resolve_anomaly_detection_config`);
    this function never invents a floor or a z_score_threshold of its own (AC10)."""
    effective_min = max(ENGINE_MIN_SERIES_LENGTH, threshold.min_series_length)
    n = len(series)

    if n < effective_min:
        return AnomalyInsufficientHistory(
            metric=threshold.metric,
            method=METHOD_Z_SCORE,
            target_ref=target_ref,
            series_length=n,
            min_series_length_required=effective_min,
        )

    baseline_points = series[:-1]
    tested_point = series[-1]
    baseline = [_as_fraction(p.value) for p in baseline_points]
    x_n = _as_fraction(tested_point.value)

    mean, variance = mean_and_sample_variance(baseline)
    if variance == 0:
        return AnomalyZeroVariance(
            metric=threshold.metric,
            method=METHOD_Z_SCORE,
            target_ref=target_ref,
            series_length=n,
        )

    stdev = decimal_stdev(variance)
    z = z_score_value(x_n, mean, stdev)

    assert threshold.z_score_threshold is not None, "AnomalyThreshold.z_score_threshold required for Z_SCORE"
    fired = abs(z) >= threshold.z_score_threshold
    severity = SEVERITY_HIGH if fired else SEVERITY_NOT_ANOMALOUS

    # §6.4 — floored at DERIVED: a statistical computation over already-computed figures is
    # itself never better than DERIVED, regardless of how strong every input's own confidence is.
    data_confidence = combine_confidence(*[p.confidence for p in series], Confidence.DERIVED)

    return AnomalyFlag(
        id=uuid4(),
        tenant_id=tenant_id,
        metric=threshold.metric,
        target_ref=target_ref,
        period=tested_point.period,
        method=METHOD_Z_SCORE,
        decorates_engine_result_ref=tested_point.engine_result_ref,
        source_engine_result_refs=tuple(p.engine_result_ref for p in series),
        score=z,
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
