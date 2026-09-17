"""rank_findings / severity / window_status — deterministic-engine.md §5.13.1, §5.14.1.

§5.12: "Ranking is not judgement... ordering by amount, age or window status is arithmetic
and is computed deterministically in Brain 1." This module is that arithmetic. Brain 3 (the
CFO agent) narrates the order this produces; it never produces the order itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from calc_engine.types import Unavailable

_SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class SeverityBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING_SOON = "CLOSING_SOON"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Finding:
    """The minimal shape rank_findings needs per exception_id — assembled by the caller from
    a reconciliation_exception (data-foundation-owned, not this module's concern)."""

    exception_id: str
    amount_paise: int
    age_days: int
    claim_window_days: int | None  # None = no claim window applies to this finding at all


@dataclass(frozen=True, slots=True)
class SeverityConfigRow:
    metric: str  # AMOUNT_PAISE | AGE_DAYS | WINDOW_DAYS_REMAINING
    high_threshold: int | None
    medium_threshold: int | None
    window_closing_soon_days: int = 14


def window_status(*, claim_window_days: int | None, closing_soon_days: int) -> WindowStatus:
    """§5.14.1: EXPIRED once elapsed, CLOSING_SOON inside the configured buffer, else OPEN.
    None (no claim window at all) is UNKNOWN, never OPEN — a finding this doesn't apply to is
    not the same fact as one with plenty of time left."""
    if claim_window_days is None:
        return WindowStatus.UNKNOWN
    if claim_window_days <= 0:
        return WindowStatus.EXPIRED
    if claim_window_days <= closing_soon_days:
        return WindowStatus.CLOSING_SOON
    return WindowStatus.OPEN


def _band_for_metric(value: int, row: SeverityConfigRow) -> SeverityBand | None:
    """None = this row's thresholds don't cover the value at all (both thresholds absent) —
    the metric is skipped, not defaulted to LOW (§5.14.1 amendment)."""
    if row.high_threshold is None and row.medium_threshold is None:
        return None
    if row.high_threshold is not None and value >= row.high_threshold:
        return SeverityBand.HIGH
    if row.medium_threshold is not None and value >= row.medium_threshold:
        return SeverityBand.MEDIUM
    return SeverityBand.LOW


def finding_severity(
    finding: Finding, *, as_of_date: date, config_rows: Sequence[SeverityConfigRow]
) -> SeverityBand | Unavailable:
    """§5.14.1, confirmed: the most severe band among whichever metrics actually had both a
    config row and applicable data on this finding — never a default LOW, and never silently
    ignoring one metric's HIGH just because another metric's band was lower."""
    bands: list[SeverityBand] = []

    for row in config_rows:
        if row.metric == "AMOUNT_PAISE":
            band = _band_for_metric(finding.amount_paise, row)
        elif row.metric == "AGE_DAYS":
            band = _band_for_metric(finding.age_days, row)
        elif row.metric == "WINDOW_DAYS_REMAINING":
            if finding.claim_window_days is None:
                band = None  # metric doesn't apply to this finding at all
            else:
                band = _band_for_metric(finding.claim_window_days, row)
        else:
            raise ValueError(f"unknown severity_config metric {row.metric!r}")

        if band is not None:
            bands.append(band)

    if not bands:
        return Unavailable(
            reason="no severity_config metric had both a config row and applicable data for this finding",
            missing_inputs=("severity_config",),
        )
    return max(bands, key=lambda b: _SEVERITY_RANK[b.value])


def rank_findings(
    findings: Sequence[Finding],
    *,
    as_of_date: date,
    config_rows: Sequence[SeverityConfigRow],
    ordering_basis: str,
    closing_soon_days: int = 14,
) -> list[tuple[Finding, SeverityBand | Unavailable, WindowStatus]]:
    """§5.13.1/§5.14.1: deterministic ordering, never left to dict/DB row order (AC1).

    - `ordering_basis = "WINDOW_THEN_AMOUNT"` (default): EXPIRED first, then CLOSING_SOON,
      then OPEN, then UNKNOWN; ties broken by amount descending.
    - `ordering_basis = "AMOUNT_ONLY"`: amount descending only.
    - A finding with `claim_window_days is None` always falls back to amount ordering within
      its UNKNOWN bucket (§5.14.1: "ordering falls back to amount").
    - Ties after all ordering keys are broken by `exception_id` (stable, deterministic —
      never insertion order), so the result is byte-identical across runs (AC1).
    """
    if ordering_basis not in ("WINDOW_THEN_AMOUNT", "AMOUNT_ONLY"):
        raise ValueError(f"unknown ordering_basis {ordering_basis!r} — must be WINDOW_THEN_AMOUNT or AMOUNT_ONLY")

    _window_rank = {
        WindowStatus.EXPIRED: 0,
        WindowStatus.CLOSING_SOON: 1,
        WindowStatus.OPEN: 2,
        WindowStatus.UNKNOWN: 3,
    }

    enriched = [
        (
            f,
            finding_severity(f, as_of_date=as_of_date, config_rows=config_rows),
            window_status(claim_window_days=f.claim_window_days, closing_soon_days=closing_soon_days),
        )
        for f in findings
    ]

    def _amount_only_key(item: tuple[Finding, SeverityBand | Unavailable, WindowStatus]) -> tuple[int, str]:
        return (-item[0].amount_paise, item[0].exception_id)

    def _window_then_amount_key(item: tuple[Finding, SeverityBand | Unavailable, WindowStatus]) -> tuple[int, int, str]:
        return (_window_rank[item[2]], -item[0].amount_paise, item[0].exception_id)

    if ordering_basis == "AMOUNT_ONLY":
        return sorted(enriched, key=_amount_only_key)
    return sorted(enriched, key=_window_then_amount_key)
