"""Alert deduplication, quiet hours and delivery re-validation — competitor-intelligence-agent.md
§6.26 (C42). Pure functions; the persistence (`ci_alert_state`, `ci_held_alert`) lives in the
repositories.

**Deduplication (§6.26.1).** One alert per `(competitor, finding type, direction)`. A repeat of the
same condition is suppressed; a new alert needs a **new valid snapshot** whose value differs from the
**last alerted value** by at least the threshold. The percentage uses `Fraction`, never `float`, like
the delta it guards (B8).

**Quiet hours (§6.26.2).** A tenant window with a timezone. An alert raised inside it is *held, never
dropped* and becomes deliverable when the window ends. Windows may cross midnight.

**Re-validation (§6.26.2).** A held alert is checked again at delivery: if the evidence it rests on
has gone past the D6 ceiling in the meantime it is **not delivered as a confirmed alert** — the seller
gets the freshness request instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from fractions import Fraction
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from competitor_intelligence.delta.compute import is_stale


class DedupOutcome(str, Enum):
    FIRE = "FIRE"
    SUPPRESS = "SUPPRESS"


@dataclass(frozen=True, slots=True)
class LastAlert:
    value_paise: int | None
    snapshot_id: UUID | None
    alerted_at: datetime


@dataclass(frozen=True, slots=True)
class DedupDecision:
    outcome: DedupOutcome
    reason: str


def decide_dedup(
    previous: LastAlert | None,
    *,
    new_value_paise: int | None,
    new_snapshot_id: UUID | None,
    threshold_pct: Fraction,
    window_hours: int,
    now: datetime,
) -> DedupDecision:
    if previous is None:
        return DedupDecision(DedupOutcome.FIRE, "first alert for this condition")
    if now - previous.alerted_at > timedelta(hours=window_hours):
        return DedupDecision(DedupOutcome.FIRE, "dedup window elapsed")
    if new_snapshot_id is not None and new_snapshot_id == previous.snapshot_id:
        return DedupDecision(DedupOutcome.SUPPRESS, "same evidence already alerted")
    if previous.value_paise is None or new_value_paise is None or previous.value_paise <= 0:
        # Nothing numeric to compare (e.g. an availability alert): a new valid snapshot is new information.
        return DedupDecision(DedupOutcome.FIRE if new_snapshot_id is not None else DedupOutcome.SUPPRESS, "no comparable value")
    change_pct = Fraction(abs(new_value_paise - previous.value_paise), previous.value_paise) * 100
    if change_pct >= threshold_pct:
        return DedupDecision(DedupOutcome.FIRE, "moved past the threshold since the last alert")
    return DedupDecision(DedupOutcome.SUPPRESS, "within the threshold of the last alerted value")


@dataclass(frozen=True, slots=True)
class QuietWindow:
    start: time
    end: time
    tz: str

    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.tz)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone {self.tz!r}") from exc


def build_quiet_window(start: time | None, end: time | None, tz: str | None) -> QuietWindow | None:
    """All three unset means no quiet hours. A partial setting is a configuration error, never a guess."""
    if start is None and end is None and tz is None:
        return None
    if start is None or end is None or not tz:
        raise ValueError("quiet hours need a start, an end and a timezone together")
    window = QuietWindow(start, end, tz)
    window.zone()  # validates the zone name
    return window


def _local(window: QuietWindow, now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(window.zone())


def is_quiet(window: QuietWindow | None, now: datetime) -> bool:
    if window is None or window.start == window.end:
        return False
    t = _local(window, now).time()
    if window.start < window.end:
        return window.start <= t < window.end
    return t >= window.start or t < window.end  # crosses midnight


def quiet_window_end(window: QuietWindow, now: datetime) -> datetime:
    """The UTC instant the current quiet window ends. Only meaningful while `is_quiet`."""
    local = _local(window, now)
    end_today = local.replace(hour=window.end.hour, minute=window.end.minute, second=window.end.second, microsecond=0)
    if end_today <= local:
        end_today += timedelta(days=1)
    return end_today.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class DeliveryCheck:
    deliver_as_confirmed: bool
    reason: str


def revalidate_for_delivery(evidence_captured_at: datetime, *, now: datetime) -> DeliveryCheck:
    """A held alert is delivered as confirmed only if the evidence under it is still inside the D6 ceiling."""
    if is_stale(evidence_captured_at, now=now):
        return DeliveryCheck(False, "evidence is now older than the freshness ceiling; ask for a fresh screenshot instead")
    return DeliveryCheck(True, "evidence still within the freshness ceiling")
