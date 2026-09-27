"""PERCENTILE_THRESHOLD — docs/specs/anomaly-detection.md §6.3, D4, AC11.

Percentile bounds (`p_low`/`p_high`) are computed over the FULL series (D4 — not a
leave-one-out baseline), via linear interpolation between closest ranks — the identical
convention `compute_price_band` already uses (`deterministic-engine.md` §5.15.1 rule 2,
`calc_engine.formulas.price_band._percentile`). That helper is reused here directly rather
than reimplemented (AC11's own requirement): it is written generically over any `Fraction`-
comparable sequence, even though its type annotation says `Sequence[int]` (price_band.py
calls it with a list of paise ints) — `Fraction` arithmetic composes with `Fraction` operands
identically, so the same function, same algorithm, same rounding convention applies unchanged
to a `Fraction`-valued series (§6.1's percentage/day-count series are all `Fraction`).

`fired = x_n <= p_low OR x_n >= p_high`. `score` = the tested point's own percentile rank
within the series, computed by running the same interpolation convention in reverse (its
position in the sorted series, expressed as a fraction of `(n-1)`).
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime
from fractions import Fraction
from typing import Sequence
from uuid import UUID, uuid4

from calc_engine.anomaly.types import (
    METHOD_PERCENTILE_THRESHOLD,
    SEVERITY_HIGH,
    SEVERITY_NOT_ANOMALOUS,
    AnomalyFlag,
    AnomalyInsufficientHistory,
    AnomalyThreshold,
    SeriesPoint,
)
from calc_engine.formulas.price_band import _percentile as _linear_interpolation_percentile
from calc_engine.types import Confidence, Paise, combine_confidence

# §6.2 — the engine floor: n >= 1/min(p, 1-p) for p=10% -> n >= 10. Tenant configuration
# (`threshold.min_series_length`) may raise this but never lower it (B7).
ENGINE_MIN_SERIES_LENGTH = 10

FORMULA_VERSION = "ANOMALY_PERCENTILE_THRESHOLD.v1"


def _as_fraction(value: "Paise | Fraction") -> Fraction:
    return Fraction(value.value) if isinstance(value, Paise) else value


def percentile_threshold(
    series: Sequence[SeriesPoint],
    *,
    tenant_id: UUID,
    target_ref: str,
    threshold: AnomalyThreshold,
    computed_at: datetime,
    as_of_date: date,
) -> AnomalyFlag | AnomalyInsufficientHistory:
    """Pure statistics only (B8/AC12). `threshold` is an already-resolved `AnomalyThreshold`
    (`config_repo.resolve_anomaly_detection_config`) — this function never invents a floor
    or a percentile band of its own (AC10)."""
    effective_min = max(ENGINE_MIN_SERIES_LENGTH, threshold.min_series_length)
    n = len(series)

    if n < effective_min:
        return AnomalyInsufficientHistory(
            metric=threshold.metric,
            method=METHOD_PERCENTILE_THRESHOLD,
            target_ref=target_ref,
            series_length=n,
            min_series_length_required=effective_min,
        )

    tested_point = series[-1]
    x_n = _as_fraction(tested_point.value)
    sorted_values = sorted(_as_fraction(p.value) for p in series)

    assert threshold.percentile_low is not None and threshold.percentile_high is not None, (
        "AnomalyThreshold.percentile_low/percentile_high required for PERCENTILE_THRESHOLD"
    )
    p_low = _linear_interpolation_percentile(sorted_values, threshold.percentile_low)
    p_high = _linear_interpolation_percentile(sorted_values, threshold.percentile_high)

    fired = x_n <= p_low or x_n >= p_high
    severity = SEVERITY_HIGH if fired else SEVERITY_NOT_ANOMALOUS

    # score = x_n's own percentile rank, the interpolation convention run in reverse: its
    # (leftmost, deterministic under duplicates) position in the sorted series, as a
    # fraction of (n-1), expressed on the 0-100 scale.
    idx = bisect_left(sorted_values, x_n)
    score = Fraction(idx, n - 1) * 100

    data_confidence = combine_confidence(*[p.confidence for p in series], Confidence.DERIVED)

    return AnomalyFlag(
        id=uuid4(),
        tenant_id=tenant_id,
        metric=threshold.metric,
        target_ref=target_ref,
        period=tested_point.period,
        method=METHOD_PERCENTILE_THRESHOLD,
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
