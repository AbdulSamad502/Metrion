"""Monitoring Report — competitor-intelligence-agent.md §6.25 (C40, C41).

"Monitoring" is **re-evaluation of stored evidence**, never watching. This module takes rows CI already
holds and returns an as-of-stamped report; it performs no I/O and no fetch of any kind, and it cannot
produce a current-state claim for a competitor whose evidence is past the D6 ceiling.

Per competitor it states the evidence date, a freshness state (`FRESH` within 24 h, `STALE` up to the
7-day ceiling, `UNAVAILABLE` beyond it or with no usable evidence), the verified delta if one exists,
the number of open seller questions, and — where evidence is stale or missing — the action to request:
a fresh screenshot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from competitor_intelligence.delta.compute import STALE_SNAPSHOT_CEILING

FRESH_WINDOW = timedelta(hours=24)  # §6.16.2 price/availability `is_stale` threshold


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CompetitorStatus:
    competitor_url_id: str
    label: str
    marketplace: str
    evidence_date: datetime | None
    freshness: Freshness
    last_verified_price_paise: int | None
    verified_delta_pct: str | None
    delta_direction: str | None
    open_questions: int
    requested_action: str | None


@dataclass(frozen=True, slots=True)
class MonitoringReport:
    product_id: str
    as_of: datetime
    competitors: tuple[CompetitorStatus, ...]
    tracked_count: int
    fresh_count: int
    needs_evidence_count: int
    notes: tuple[str, ...] = field(default_factory=tuple)


def freshness_of(evidence_date: datetime | None, *, now: datetime) -> Freshness:
    if evidence_date is None:
        return Freshness.UNAVAILABLE
    age = now - evidence_date
    if age > STALE_SNAPSHOT_CEILING:
        return Freshness.UNAVAILABLE  # D6: beyond the ceiling the current answer is not given
    if age > FRESH_WINDOW:
        return Freshness.STALE
    return Freshness.FRESH


def build_monitoring_report(
    product_id: str,
    competitors: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> MonitoringReport:
    """Each input mapping: `id`, `label`, `marketplace`, optional `evidence_date`, `price_paise`,
    `delta_pct` (a string), `delta_direction`, `open_questions`. Values come from confirmed
    snapshots only — the caller reads them through `latest_usable_snapshot`, which already excludes
    pending and declined prices (C37)."""
    rows: list[CompetitorStatus] = []
    for c in competitors:
        evidence_date = c.get("evidence_date")
        freshness = freshness_of(evidence_date, now=now)
        label = c.get("label") or "this competitor"
        rows.append(
            CompetitorStatus(
                competitor_url_id=str(c["id"]),
                label=label,
                marketplace=str(c.get("marketplace", "")),
                evidence_date=evidence_date,
                freshness=freshness,
                # Beyond the ceiling the current price is not stated at all (D6).
                last_verified_price_paise=c.get("price_paise") if freshness is not Freshness.UNAVAILABLE else None,
                verified_delta_pct=c.get("delta_pct") if freshness is not Freshness.UNAVAILABLE else None,
                delta_direction=c.get("delta_direction") if freshness is not Freshness.UNAVAILABLE else None,
                open_questions=int(c.get("open_questions") or 0),
                requested_action=None if freshness is Freshness.FRESH else f"send a fresh screenshot of {label}",
            )
        )
    notes: list[str] = []
    if not rows:
        notes.append("No competitors are tracked for this product yet.")
    elif all(r.freshness is Freshness.UNAVAILABLE for r in rows):
        notes.append("None of the tracked competitors has current evidence.")
    return MonitoringReport(
        product_id=product_id,
        as_of=now,
        competitors=tuple(rows),
        tracked_count=len(rows),
        fresh_count=sum(1 for r in rows if r.freshness is Freshness.FRESH),
        needs_evidence_count=sum(1 for r in rows if r.requested_action is not None),
        notes=tuple(notes),
    )
