"""§6.26 — what happens to a newly recorded price event: dedup, quiet hours, held-then-delivered, stale-at-delivery.
In-memory fakes behind every repository; no database."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from competitor_intelligence.alerts import raise_alert as ra
from competitor_intelligence.alerts.raise_alert import AlertOutcome, PriceEventFacts, deliver_due_held_alerts, process_price_event

TENANT, URL = uuid4(), uuid4()
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)  # 17:30 IST


class World:
    def __init__(self, monkeypatch, *, settings=None) -> None:
        self.state: dict = {}
        self.held: list = []
        self.events: list = []
        self.suppressed: dict = {}
        self.price_events: dict = {}
        self.snapshots: dict = {}
        self.settings = {"quiet_hours_start": None, "quiet_hours_end": None, "quiet_hours_tz": None, "alert_dedup_window_hours": 24, **(settings or {})}
        w = self
        monkeypatch.setattr(ra, "ci_tenant_config_repo", SimpleNamespace(get_alert_settings=lambda t: w.settings))
        monkeypatch.setattr(
            ra,
            "ci_alert_state_repo",
            SimpleNamespace(
                get=lambda t, u, ft, d: w.state.get((u, ft, d)),
                upsert=lambda t, u, ft, d, *, value_paise, snapshot_id, at: w.state.__setitem__(
                    (u, ft, d), {"last_alerted_value_paise": value_paise, "last_alerted_snapshot_id": snapshot_id, "last_alerted_at": at}
                ),
            ),
        )
        monkeypatch.setattr(
            ra,
            "ci_held_alert_repo",
            SimpleNamespace(
                insert=lambda t, *, finding_id, hold_until: w.held.append({"id": uuid4(), "finding_id": finding_id, "hold_until": hold_until, "delivered_at": None}),
                list_due=lambda t, *, now: [h for h in w.held if h["delivered_at"] is None and h["hold_until"] <= now],
                mark_delivered=lambda t, hid, *, at: [h.__setitem__("delivered_at", at) for h in w.held if h["id"] == hid],
            ),
        )
        monkeypatch.setattr(ra, "ci_event_repo", SimpleNamespace(record=lambda t, ev, **kw: w.events.append((ev.value, kw.get("object_id")))))
        monkeypatch.setattr(
            ra,
            "competitor_price_event_repo",
            SimpleNamespace(set_suppressed=lambda t, eid, reason: w.suppressed.__setitem__(eid, reason), get_event=lambda t, eid: w.price_events.get(eid)),
        )
        monkeypatch.setattr(ra, "competitor_snapshot_repo", SimpleNamespace(get_by_id=lambda t, sid: w.snapshots.get(sid)))
        w.findings = []
        monkeypatch.setattr(ra, "build", SimpleNamespace(record_price_finding=lambda t, eid, now=None: w.findings.append(eid)))

    def names(self):
        return [e[0] for e in self.events]


def facts(value=269900, snap=None, direction="DECREASE", **kw) -> PriceEventFacts:
    base = dict(event_id=uuid4(), competitor_url_id=URL, to_snapshot_id=snap or uuid4(), new_value_paise=value, direction=direction,
                price_changed=True, threshold_breached=True, alert_eligible=True, threshold_pct=Decimal("5.00"))
    base.update(kw)
    return PriceEventFacts(**base)


def test_an_event_below_threshold_or_on_stale_evidence_was_never_an_alert(monkeypatch) -> None:
    w = World(monkeypatch)
    assert process_price_event(TENANT, facts(threshold_breached=False), now=NOW) is AlertOutcome.NOT_ALERTABLE
    assert process_price_event(TENANT, facts(alert_eligible=False), now=NOW) is AlertOutcome.NOT_ALERTABLE
    assert w.events == [] and w.state == {}


def test_the_first_alert_is_raised_and_remembered(monkeypatch) -> None:
    w = World(monkeypatch)
    f = facts()
    assert process_price_event(TENANT, f, now=NOW) is AlertOutcome.RAISED
    assert w.names() == ["ALERT_RAISED"] and w.state[(URL, "PRICE_CHANGE", "DECREASE")]["last_alerted_value_paise"] == 269900
    assert f.event_id not in w.suppressed and w.findings == [f.event_id]  # a raised alert becomes a persistent finding (C46)


def test_a_repeat_on_the_same_evidence_is_suppressed_and_marked(monkeypatch) -> None:
    w = World(monkeypatch)
    snap = uuid4()
    process_price_event(TENANT, facts(snap=snap), now=NOW)
    second = facts(snap=snap)
    assert process_price_event(TENANT, second, now=NOW + timedelta(minutes=5)) is AlertOutcome.SUPPRESSED
    assert w.suppressed[second.event_id] == "DEDUP" and w.names() == ["ALERT_RAISED", "ALERT_SUPPRESSED_DEDUP"]


def test_a_new_snapshot_within_the_threshold_of_the_last_alert_is_suppressed_past_it_fires(monkeypatch) -> None:
    w = World(monkeypatch)
    process_price_event(TENANT, facts(value=269900), now=NOW)
    assert process_price_event(TENANT, facts(value=267200), now=NOW + timedelta(hours=2)) is AlertOutcome.SUPPRESSED  # -1.0% vs the last alerted value
    assert process_price_event(TENANT, facts(value=256000), now=NOW + timedelta(hours=3)) is AlertOutcome.RAISED  # -5.1%
    assert w.state[(URL, "PRICE_CHANGE", "DECREASE")]["last_alerted_value_paise"] == 256000


def test_a_different_direction_is_its_own_condition(monkeypatch) -> None:
    World(monkeypatch)
    process_price_event(TENANT, facts(direction="DECREASE"), now=NOW)
    assert process_price_event(TENANT, facts(direction="INCREASE"), now=NOW + timedelta(minutes=1)) is AlertOutcome.RAISED


QUIET = {"quiet_hours_start": time(22), "quiet_hours_end": time(7), "quiet_hours_tz": "Asia/Kolkata"}


def test_inside_quiet_hours_the_alert_is_held_not_dropped(monkeypatch) -> None:
    w = World(monkeypatch, settings=QUIET)
    night = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)  # 23:30 IST
    f = facts()
    assert process_price_event(TENANT, f, now=night) is AlertOutcome.HELD
    assert w.names() == ["ALERT_HELD_QUIET_HOURS"] and len(w.held) == 1
    assert w.held[0]["finding_id"] == f.event_id and w.held[0]["hold_until"] == datetime(2026, 10, 19, 1, 30, tzinfo=timezone.utc)  # 07:00 IST
    assert w.state  # dedup memory is already updated: a second event for the same condition is suppressed while this waits
    assert process_price_event(TENANT, facts(snap=f.to_snapshot_id), now=night) is AlertOutcome.SUPPRESSED


def test_outside_quiet_hours_the_alert_is_raised_normally(monkeypatch) -> None:
    w = World(monkeypatch, settings=QUIET)
    assert process_price_event(TENANT, facts(), now=NOW) is AlertOutcome.RAISED and w.held == []


def test_a_held_alert_is_delivered_when_the_window_ends_if_the_evidence_is_still_fresh(monkeypatch) -> None:
    w = World(monkeypatch, settings=QUIET)
    night = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
    f = facts()
    w.price_events[f.event_id] = {"to_snapshot_id": f.to_snapshot_id}
    w.snapshots[f.to_snapshot_id] = {"captured_at": night - timedelta(hours=3)}
    process_price_event(TENANT, f, now=night)
    assert deliver_due_held_alerts(TENANT, now=night + timedelta(hours=1)) == {"delivered": 0, "withheld": 0}  # window not over yet
    assert deliver_due_held_alerts(TENANT, now=datetime(2026, 10, 19, 1, 31, tzinfo=timezone.utc)) == {"delivered": 1, "withheld": 0}
    assert w.names() == ["ALERT_HELD_QUIET_HOURS", "ALERT_RAISED"] and w.held[0]["delivered_at"] is not None and w.findings == [f.event_id]  # the finding appears only at delivery
    assert deliver_due_held_alerts(TENANT, now=datetime(2026, 10, 19, 2, 0, tzinfo=timezone.utc)) == {"delivered": 0, "withheld": 0}  # not delivered twice


def test_a_held_alert_whose_evidence_went_stale_is_withheld_not_delivered_as_confirmed(monkeypatch) -> None:
    w = World(monkeypatch, settings=QUIET)
    night = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
    f = facts()
    w.price_events[f.event_id] = {"to_snapshot_id": f.to_snapshot_id}
    w.snapshots[f.to_snapshot_id] = {"captured_at": night - timedelta(days=7, hours=2)}  # past the D6 ceiling by delivery time
    process_price_event(TENANT, f, now=night)
    assert deliver_due_held_alerts(TENANT, now=datetime(2026, 10, 19, 1, 31, tzinfo=timezone.utc)) == {"delivered": 0, "withheld": 1}
    assert w.suppressed[f.event_id] == "STALE_AT_DELIVERY" and w.names()[-1] == "ALERT_WITHHELD_STALE"


def test_a_held_alert_with_a_missing_snapshot_is_withheld_never_assumed_fresh(monkeypatch) -> None:
    w = World(monkeypatch, settings=QUIET)
    night = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
    f = facts()
    process_price_event(TENANT, f, now=night)  # no snapshot/event rows registered
    assert deliver_due_held_alerts(TENANT, now=datetime(2026, 10, 19, 1, 31, tzinfo=timezone.utc)) == {"delivered": 0, "withheld": 1}
