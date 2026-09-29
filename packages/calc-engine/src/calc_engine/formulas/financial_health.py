"""financial_health — cfo-agent.md §6.15 (Financial Health Band).

**What this is, and what it deliberately is not.** This is a deterministic CLASSIFICATION —
banding an already-computed metric against configured thresholds — never a new derived
financial figure. It mirrors `severity.py`'s own established pattern (`finding_severity`:
"ranking is not judgement... computed deterministically in Brain 1") exactly: config-driven
thresholds, `Unavailable` (never a default GOOD band) when no metric could be classified, and
full provenance carried through via each input's own `engine_result_ref` so a seller can trace
which already-persisted `MetricResult` drove which band. No arithmetic on money happens here —
every value classified in is a `Fraction` percentage `compute_metric.py` already computed
(`CONTRIBUTION_MARGIN_PCT`/`FEE_RATIO_PCT`/`RETURN_RATE_PCT`), never re-derived.

**Why `direction` exists, unlike `severity_config`'s single "higher = more severe" model.**
Financial-health metrics point both ways: a LOW `CONTRIBUTION_MARGIN_PCT` is the bad direction
(`LOWER_IS_WORSE`), but a HIGH `FEE_RATIO_PCT`/`RETURN_RATE_PCT` is (`HIGHER_IS_WORSE`).
Thresholds are compared as exact `Fraction`s (both the metric's own `value_fraction` and the
config's `at_risk_threshold_pct`/`watch_threshold_pct`, parsed via `Decimal` — never a float),
on the SAME "percent number" scale `compute_metric.py` already uses for `value_fraction`
(e.g. `12.5` meaning 12.5%, not `0.125`) — no rounding or basis-point conversion anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from typing import Sequence
from uuid import UUID

from calc_engine.types import Unavailable

_BAND_RANK = {"GOOD": 0, "WATCH": 1, "AT_RISK": 2}


class HealthBand(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    AT_RISK = "AT_RISK"


@dataclass(frozen=True, slots=True)
class FinancialHealthConfigRow:
    metric: str  # CONTRIBUTION_MARGIN_PCT | FEE_RATIO_PCT | RETURN_RATE_PCT
    direction: str  # HIGHER_IS_WORSE | LOWER_IS_WORSE
    at_risk_threshold_pct: Decimal | None
    watch_threshold_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class FinancialHealthInput:
    """One already-computed metric to classify. `value_fraction` and `engine_result_ref` come
    straight from the `MetricResult` this input represents (`compute_metric.py`'s own
    `CONTRIBUTION_MARGIN_PCT`/`FEE_RATIO_PCT`/`RETURN_RATE_PCT`) — this module never computes
    either, only classifies the figure it is handed."""

    metric: str
    value_fraction: Fraction
    engine_result_ref: UUID


@dataclass(frozen=True, slots=True)
class FinancialHealthResult:
    overall_band: HealthBand
    # Only metrics that actually had BOTH a config row and a supplied input — a metric with
    # neither is simply absent here, never defaulted to GOOD (mirrors finding_severity's own
    # "never silently ignoring" discipline, applied to the ABSENCE of a metric rather than a
    # HIGH band being outranked).
    per_metric_bands: dict[str, HealthBand]
    engine_result_refs: tuple[UUID, ...]  # provenance for every classified input, order-preserved
    # Exact per-metric provenance (added for the Strategic Insight layer, cfo-agent.md §7.5) —
    # `engine_result_refs` above stays as the flat, order-preserved tuple every existing caller
    # already reads; this dict lets a NEW caller cite the one ref that actually classified a
    # given metric, without relying on `per_metric_bands`/`engine_result_refs` sharing insertion
    # order (true today because both are built in the same loop below, but never guaranteed by
    # either field's own type — this makes the correct pairing explicit and typed).
    per_metric_refs: dict[str, UUID]
    # Same rationale as `per_metric_refs`: the Strategic Insight layer (cfo-agent.md §7.5) needs
    # to cite the actual classified value as evidence (e.g. "FEE_RATIO_PCT = 40%"), not just the
    # band it produced — never re-derived, the exact `Fraction` each input already carried.
    per_metric_values: dict[str, Fraction]


def _threshold_to_fraction(value: Decimal | None) -> Fraction | None:
    return Fraction(value) if value is not None else None


def _band_for(value: Fraction, row: FinancialHealthConfigRow) -> HealthBand | None:
    """`None` = this row's thresholds don't cover the metric at all (both absent) — the metric
    is skipped, never defaulted to GOOD, mirroring `severity._band_for_metric`'s identical
    "both thresholds absent -> None" rule."""
    at_risk = _threshold_to_fraction(row.at_risk_threshold_pct)
    watch = _threshold_to_fraction(row.watch_threshold_pct)
    if at_risk is None and watch is None:
        return None

    if row.direction == "HIGHER_IS_WORSE":
        if at_risk is not None and value >= at_risk:
            return HealthBand.AT_RISK
        if watch is not None and value >= watch:
            return HealthBand.WATCH
        return HealthBand.GOOD
    if row.direction == "LOWER_IS_WORSE":
        if at_risk is not None and value <= at_risk:
            return HealthBand.AT_RISK
        if watch is not None and value <= watch:
            return HealthBand.WATCH
        return HealthBand.GOOD
    raise ValueError(f"unknown financial_health_config direction {row.direction!r}")


def assemble_financial_health(
    inputs: Sequence[FinancialHealthInput], config_rows: Sequence[FinancialHealthConfigRow]
) -> FinancialHealthResult | Unavailable:
    """Classifies every input whose `metric` has a config row, then takes the single WORST band
    among them (`AT_RISK` > `WATCH` > `GOOD`) as `overall_band` — a business is only as healthy
    as its worst tracked signal, the same "most severe band wins" rule `finding_severity` already
    established for Leak Shield findings. Returns `Unavailable` (never a fabricated GOOD band)
    when NOT ONE input could be classified — e.g. every metric was itself `UNAVAILABLE` upstream
    (cascaded, per net_realized_revenue's own tri-state contract) or no config row exists for
    any metric supplied."""
    config_by_metric = {row.metric: row for row in config_rows}

    per_metric: dict[str, HealthBand] = {}
    per_metric_refs: dict[str, UUID] = {}
    per_metric_values: dict[str, Fraction] = {}
    refs: list[UUID] = []
    for inp in inputs:
        row = config_by_metric.get(inp.metric)
        if row is None:
            continue
        band = _band_for(inp.value_fraction, row)
        if band is None:
            continue
        per_metric[inp.metric] = band
        per_metric_refs[inp.metric] = inp.engine_result_ref
        per_metric_values[inp.metric] = inp.value_fraction
        refs.append(inp.engine_result_ref)

    if not per_metric:
        return Unavailable(
            reason=(
                "no financial_health_config metric had both a config row and a supplied, "
                "classifiable input"
            ),
            missing_inputs=("financial_health_config",),
        )

    overall_band = max(per_metric.values(), key=lambda b: _BAND_RANK[b.value])
    return FinancialHealthResult(
        overall_band=overall_band,
        per_metric_bands=per_metric,
        engine_result_refs=tuple(refs),
        per_metric_refs=per_metric_refs,
        per_metric_values=per_metric_values,
    )
