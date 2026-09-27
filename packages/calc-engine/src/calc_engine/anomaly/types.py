"""SeriesPoint / AnomalyFlag / AnomalyInsufficientHistory / AnomalyZeroVariance /
AnomalyConfigurationGap / AnomalyThreshold — docs/specs/anomaly-detection.md §5.1, §5.2, §5.3.

All frozen, slots dataclasses, matching this package's house style (`calc_engine.types`,
`calc_engine.formulas.price_band`). No `float` anywhere (B9/AC4) — `Paise` for
money-denominated series points, `Fraction` for percentage/day-count series points and for
every derived statistic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction
from uuid import UUID

from calc_engine.types import Confidence, Paise

# §5.2 — HIGH | MEDIUM | LOW | NOT_ANOMALOUS. A distinct vocabulary from `Confidence` (§6.4,
# AC9) — never blended into the same field.
AnomalySeverity = str
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITY_NOT_ANOMALOUS = "NOT_ANOMALOUS"

# §6.1 — the four named metric series. A fifth is out of scope for V1 (B4).
METRIC_MARGIN_PCT = "MARGIN_PCT"
METRIC_FEE_RATIO_PCT = "FEE_RATIO_PCT"
METRIC_SETTLEMENT_LAG_DAYS = "SETTLEMENT_LAG_DAYS"
METRIC_RETURN_RATE_PCT = "RETURN_RATE_PCT"

# §5.2 — Z_SCORE | PERCENTILE_THRESHOLD | PERIOD_OVER_PERIOD_DELTA.
METHOD_Z_SCORE = "Z_SCORE"
METHOD_PERCENTILE_THRESHOLD = "PERCENTILE_THRESHOLD"
METHOD_PERIOD_OVER_PERIOD_DELTA = "PERIOD_OVER_PERIOD_DELTA"


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    """§5.1 — the only input Brain 2 accepts. A period absent from the series is not a
    SeriesPoint with value=0 (B2/E6) — the caller simply omits it."""

    period: date
    value: Paise | Fraction
    confidence: Confidence
    engine_result_ref: UUID


@dataclass(frozen=True, slots=True)
class AnomalyThreshold:
    """§5.3 / §5.2's `threshold_used` — the exact config values a flag actually applied,
    never a hardcoded constant in the computation path (AC10). Fields not relevant to a
    given `method` are simply `None` (e.g. `z_score_threshold` is None for
    PERCENTILE_THRESHOLD)."""

    metric: str
    method: str
    min_series_length: int
    config_version: int
    z_score_threshold: Fraction | None = None
    percentile_low: Fraction | None = None
    percentile_high: Fraction | None = None
    # {"high": Fraction, "medium": Fraction, "low": Fraction} — multiples of baseline-delta
    # stdev (§5.3). A plain dict, not a frozen mapping: `AnomalyThreshold` itself is frozen
    # (attribute reassignment is blocked), but nothing here ever mutates this dict in place.
    delta_severity_bands: "dict[str, Fraction] | None" = None


@dataclass(frozen=True, slots=True)
class AnomalyFlag:
    """§5.2 — the output contract. NOT a `MetricResult` (B6) and never carries its own
    `engine_result_ref`; it *cites* `decorates_engine_result_ref` instead."""

    id: UUID
    tenant_id: UUID
    metric: str
    target_ref: str
    period: date
    method: str
    decorates_engine_result_ref: UUID
    source_engine_result_refs: tuple[UUID, ...]
    score: Fraction
    threshold_used: AnomalyThreshold
    fired: bool
    severity: str
    data_confidence: str
    series_length: int
    min_series_length_required: int
    config_version: int
    formula_version: str
    as_of_date: date
    computed_at: datetime


@dataclass(frozen=True, slots=True)
class AnomalyInsufficientHistory:
    """§5.2 — a distinguished non-flag outcome. Below the method's floor, this is returned
    instead of an AnomalyFlag; never coerced into a `fired=false` flag (B5, AC2)."""

    metric: str
    method: str
    target_ref: str
    series_length: int
    min_series_length_required: int
    reason: str = "INSUFFICIENT_HISTORY"


@dataclass(frozen=True, slots=True)
class AnomalyZeroVariance:
    """§5.2 — Z_SCORE and PERIOD_OVER_PERIOD_DELTA only (§7 E4). The baseline has no spread;
    a z-score is mathematically undefined, not "no anomaly found" (AC3)."""

    metric: str
    method: str
    target_ref: str
    series_length: int
    reason: str = "ZERO_VARIANCE_BASELINE"


@dataclass(frozen=True, slots=True)
class AnomalyConfigurationGap:
    """E9/AC13 — no `anomaly_detection_config` row (tenant or platform) covers this
    `(metric, method)` pair. Not named as a distinct dataclass in spec §5.2's own two
    "distinguished non-flag outcomes" (those cover series-shape edge cases only), but §6.5
    and AC13 both require an explicit, structurally-distinct configuration-gap outcome —
    "never a silently-assumed threshold." Judgment call: modelled as a third outcome type
    here, sibling to AnomalyInsufficientHistory/AnomalyZeroVariance, rather than an
    exception, so a caller can pattern-match all three non-flag outcomes uniformly."""

    metric: str
    method: str
    target_ref: str
    reason: str = "NO_CONFIG_FOR_METHOD"
