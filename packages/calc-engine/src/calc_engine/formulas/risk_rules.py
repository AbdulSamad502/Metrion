"""Deterministic rules behind the proactive CFO scan (docs/specs/cfo-phase3-scope.md 3f). Pure: no I/O, no clock, no model.

Each rule returns a plain result the caller turns into a signal with fixed wording. Thresholds are configuration with no defaults here; a `None`
threshold means the rule cannot run and says so (CONFIG_MISSING) rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from calc_engine.types import Unavailable


@dataclass(frozen=True, slots=True)
class MarginDrop:
    previous_pct: Fraction
    current_pct: Fraction
    drop_points: Fraction  # percentage points the margin fell (positive = worse)
    severity: str  # HIGH | MEDIUM | LOW


def margin_drop(
    previous_pct: Fraction | None, current_pct: Fraction | None, threshold_points: Fraction | None, high_points: Fraction | None
) -> MarginDrop | None | Unavailable:
    """Contribution-margin percentages for two periods. None when the margin did not fall by at least `threshold_points`; `Unavailable` when an input
    or the configuration is missing (never treated as no drop). Severity HIGH from `high_points`, MEDIUM from twice the threshold, else LOW."""
    if threshold_points is None or high_points is None:
        return Unavailable(reason="CONFIG_MISSING: margin-drop thresholds are not configured", missing_inputs=("margin_drop_points",))
    if threshold_points <= 0 or high_points < threshold_points:
        raise ValueError("thresholds must be positive and high_points must not be below threshold_points")
    if previous_pct is None or current_pct is None:
        return Unavailable(reason="a contribution margin is unavailable for one of the two periods", missing_inputs=("CONTRIBUTION_MARGIN_PCT",))
    drop = previous_pct - current_pct
    if drop < threshold_points:
        return None
    sev = "HIGH" if drop >= high_points else "MEDIUM" if drop >= 2 * threshold_points else "LOW"
    return MarginDrop(previous_pct, current_pct, drop, sev)


def data_age_days(newest_document_date: date | None, as_of: date) -> int | None:
    """Whole days between the newest order document and `as_of`; None when there is no order data at all (reported as such, never as 0)."""
    if newest_document_date is None:
        return None
    return max(0, (as_of - newest_document_date).days)


def is_stale(age_days: int | None, stale_after_days: int | None) -> bool | Unavailable:
    """True when the newest data is older than `stale_after_days` (equality is NOT stale). No data at all is stale."""
    if stale_after_days is None:
        return Unavailable(reason="CONFIG_MISSING: no stale-data threshold is configured", missing_inputs=("stale_days",))
    if stale_after_days < 1:
        raise ValueError("stale_after_days must be at least 1")
    return True if age_days is None else age_days > stale_after_days
