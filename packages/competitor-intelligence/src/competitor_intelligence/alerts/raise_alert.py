"""Deciding what happens to a newly recorded price event — competitor-intelligence-agent.md §6.26 (C42).

A price event is a recorded *observation*. Whether it becomes an alert the seller sees is decided here,
once, when the event is written:

1. **Not alertable** — below threshold, or backed by stale/pending evidence (the existing §6.3 gates,
   stored on the event): nothing to do, it never was an alert.
2. **Dedup** — the same condition already alerted, or a new snapshot still within the threshold of the
   last alerted value: the event is marked suppressed (`alert_suppressed_reason`), an
   `ALERT_SUPPRESSED_DEDUP` event is written, and the Layer 1 list never shows it.
3. **Quiet hours** — inside the tenant's window: a `ci_held_alert` row is written and an
   `ALERT_HELD_QUIET_HOURS` event; the Layer 1 list hides it until delivered. **Held, never dropped.**
4. Otherwise the alert is **raised** (`ALERT_RAISED`), and the dedup memory is updated.

`deliver_due_held_alerts` is what a scheduler calls: it releases held alerts whose window has ended,
**re-validating freshness first** — an alert whose evidence has meanwhile gone past the D6 ceiling is
withheld (`ALERT_WITHHELD_STALE`), not delivered as confirmed; the seller gets the freshness request
instead (§6.25).

Layer 1 only (C26): nothing here states margin, contribution or break-even.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from fractions import Fraction
from decimal import Decimal
from uuid import UUID

from competitor_intelligence.alerts.hardening import (
    DedupOutcome,
    LastAlert,
    build_quiet_window,
    decide_dedup,
    is_quiet,
    quiet_window_end,
    revalidate_for_delivery,
)
from competitor_intelligence.findings import build
from competitor_intelligence.intake.events import CiEvent
from competitor_intelligence.repositories import (
    ci_alert_state_repo,
    ci_event_repo,
    ci_held_alert_repo,
    ci_tenant_config_repo,
    competitor_price_event_repo,
    competitor_snapshot_repo,
)

FINDING_PRICE = "PRICE_CHANGE"
FINDING_AVAILABILITY = "AVAILABILITY_CHANGE"


class AlertOutcome(str, Enum):
    NOT_ALERTABLE = "NOT_ALERTABLE"
    RAISED = "RAISED"
    SUPPRESSED = "SUPPRESSED"
    HELD = "HELD"


@dataclass(frozen=True, slots=True)
class PriceEventFacts:
    event_id: UUID
    competitor_url_id: UUID
    to_snapshot_id: UUID
    new_value_paise: int | None
    direction: str
    price_changed: bool
    threshold_breached: bool
    alert_eligible: bool
    threshold_pct: Decimal


def _fraction(value: Decimal) -> Fraction:
    return Fraction(value)


def process_price_event(tenant_id: UUID, facts: PriceEventFacts, *, now: datetime | None = None, actor: str = "SYSTEM") -> AlertOutcome:
    now = now or datetime.now(timezone.utc)
    if not (facts.threshold_breached and facts.alert_eligible):
        return AlertOutcome.NOT_ALERTABLE

    finding_type = FINDING_PRICE if facts.price_changed else FINDING_AVAILABILITY
    config = ci_tenant_config_repo.get_alert_settings(tenant_id)
    previous_row = ci_alert_state_repo.get(tenant_id, facts.competitor_url_id, finding_type, facts.direction)
    previous = (
        LastAlert(previous_row["last_alerted_value_paise"], previous_row["last_alerted_snapshot_id"], previous_row["last_alerted_at"])
        if previous_row
        else None
    )
    decision = decide_dedup(
        previous,
        new_value_paise=facts.new_value_paise,
        new_snapshot_id=facts.to_snapshot_id,
        threshold_pct=_fraction(facts.threshold_pct),
        window_hours=int(config["alert_dedup_window_hours"]),
        now=now,
    )
    if decision.outcome is DedupOutcome.SUPPRESS:
        competitor_price_event_repo.set_suppressed(tenant_id, facts.event_id, "DEDUP")
        ci_event_repo.record(tenant_id, CiEvent.ALERT_SUPPRESSED_DEDUP, actor=actor, object_type="competitor_price_event",
                             object_id=facts.event_id, detail={"finding": finding_type}, occurred_at=now)
        return AlertOutcome.SUPPRESSED

    # Dedup memory is updated when the alert is raised OR held, so a second event for the same condition is suppressed while the first waits.
    ci_alert_state_repo.upsert(tenant_id, facts.competitor_url_id, finding_type, facts.direction,
                               value_paise=facts.new_value_paise, snapshot_id=facts.to_snapshot_id, at=now)

    window = build_quiet_window(config.get("quiet_hours_start"), config.get("quiet_hours_end"), config.get("quiet_hours_tz"))
    if is_quiet(window, now):
        assert window is not None
        ci_held_alert_repo.insert(tenant_id, finding_id=facts.event_id, hold_until=quiet_window_end(window, now))
        ci_event_repo.record(tenant_id, CiEvent.ALERT_HELD_QUIET_HOURS, actor=actor, object_type="competitor_price_event",
                             object_id=facts.event_id, detail={"finding": finding_type}, occurred_at=now)
        return AlertOutcome.HELD

    ci_event_repo.record(tenant_id, CiEvent.ALERT_RAISED, actor=actor, object_type="competitor_price_event",
                         object_id=facts.event_id, detail={"finding": finding_type}, occurred_at=now)
    build.record_price_finding(tenant_id, facts.event_id, now=now)  # the alert is a persistent, addressable finding (C46)
    return AlertOutcome.RAISED


def deliver_due_held_alerts(tenant_id: UUID, *, now: datetime | None = None) -> dict[str, int]:
    """Releases held alerts whose quiet window has ended. Returns counts: delivered / withheld."""
    now = now or datetime.now(timezone.utc)
    counts = {"delivered": 0, "withheld": 0}
    for held in ci_held_alert_repo.list_due(tenant_id, now=now):
        event_id = held["finding_id"]
        event = competitor_price_event_repo.get_event(tenant_id, event_id)
        snapshot = competitor_snapshot_repo.get_by_id(tenant_id, event["to_snapshot_id"]) if event else None
        ci_held_alert_repo.mark_delivered(tenant_id, held["id"], at=now)
        if snapshot is None or not revalidate_for_delivery(snapshot["captured_at"], now=now).deliver_as_confirmed:
            competitor_price_event_repo.set_suppressed(tenant_id, event_id, "STALE_AT_DELIVERY")
            ci_event_repo.record(tenant_id, CiEvent.ALERT_WITHHELD_STALE, object_type="competitor_price_event", object_id=event_id, occurred_at=now)
            counts["withheld"] += 1
        else:
            ci_event_repo.record(tenant_id, CiEvent.ALERT_RAISED, object_type="competitor_price_event", object_id=event_id,
                                 detail={"after": "quiet_hours"}, occurred_at=now)
            build.record_price_finding(tenant_id, event_id, now=now)
            counts["delivered"] += 1
    return counts

