"""§6.24–§6.26 — alert dedup, quiet hours, monitoring report, wording rule, watchlist management."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from fractions import Fraction
from types import SimpleNamespace
from uuid import uuid4

import pytest

from competitor_intelligence.alerts.hardening import (
    DedupOutcome,
    LastAlert,
    build_quiet_window,
    decide_dedup,
    is_quiet,
    quiet_window_end,
    revalidate_for_delivery,
)
from competitor_intelligence.monitor.report import Freshness, build_monitoring_report, freshness_of
from competitor_intelligence.monitor.wording import assert_no_currency_claim, currency_claims
from competitor_intelligence.watchlist import manage
from competitor_intelligence.watchlist.manage import ManageStatus

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
SNAP_A, SNAP_B = uuid4(), uuid4()
FIVE = Fraction(5)


# ---- dedup --------------------------------------------------------------------------
def _last(value=269900, snap=SNAP_A, hours_ago=1) -> LastAlert:
    return LastAlert(value_paise=value, snapshot_id=snap, alerted_at=NOW - timedelta(hours=hours_ago))


def test_first_alert_fires() -> None:
    assert decide_dedup(None, new_value_paise=100, new_snapshot_id=SNAP_A, threshold_pct=FIVE, window_hours=24, now=NOW).outcome is DedupOutcome.FIRE


def test_the_same_evidence_is_never_alerted_twice() -> None:
    d = decide_dedup(_last(), new_value_paise=269900, new_snapshot_id=SNAP_A, threshold_pct=FIVE, window_hours=24, now=NOW)
    assert d.outcome is DedupOutcome.SUPPRESS and "same evidence" in d.reason


def test_a_new_snapshot_within_the_threshold_of_the_last_alert_is_suppressed() -> None:
    # last alerted at Rs 2,699; a new snapshot at Rs 2,672 is -1.0% against the LAST ALERTED value
    d = decide_dedup(_last(), new_value_paise=267200, new_snapshot_id=SNAP_B, threshold_pct=FIVE, window_hours=24, now=NOW)
    assert d.outcome is DedupOutcome.SUPPRESS


def test_a_new_snapshot_past_the_threshold_of_the_last_alert_fires() -> None:
    d = decide_dedup(_last(), new_value_paise=256000, new_snapshot_id=SNAP_B, threshold_pct=FIVE, window_hours=24, now=NOW)  # -5.1%
    assert d.outcome is DedupOutcome.FIRE


def test_the_threshold_is_inclusive_and_uses_exact_arithmetic() -> None:
    # exactly 5.000...% of 200000 is 10000
    assert decide_dedup(_last(200000), new_value_paise=190000, new_snapshot_id=SNAP_B, threshold_pct=FIVE, window_hours=24, now=NOW).outcome is DedupOutcome.FIRE
    assert decide_dedup(_last(200000), new_value_paise=190001, new_snapshot_id=SNAP_B, threshold_pct=FIVE, window_hours=24, now=NOW).outcome is DedupOutcome.SUPPRESS


def test_after_the_window_a_new_valid_snapshot_fires_again() -> None:
    d = decide_dedup(_last(hours_ago=30), new_value_paise=269900, new_snapshot_id=SNAP_B, threshold_pct=FIVE, window_hours=24, now=NOW)
    assert d.outcome is DedupOutcome.FIRE


def test_a_non_numeric_alert_such_as_availability_fires_on_new_evidence_only() -> None:
    prev = LastAlert(value_paise=None, snapshot_id=SNAP_A, alerted_at=NOW - timedelta(hours=1))
    assert decide_dedup(prev, new_value_paise=None, new_snapshot_id=SNAP_B, threshold_pct=FIVE, window_hours=24, now=NOW).outcome is DedupOutcome.FIRE
    assert decide_dedup(prev, new_value_paise=None, new_snapshot_id=SNAP_A, threshold_pct=FIVE, window_hours=24, now=NOW).outcome is DedupOutcome.SUPPRESS


# ---- quiet hours --------------------------------------------------------------------
IST = "Asia/Kolkata"


def _ist(h: int, m: int = 0, day: int = 18) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def test_no_window_means_never_quiet() -> None:
    assert build_quiet_window(None, None, None) is None and not is_quiet(None, NOW)


def test_a_partial_window_is_a_configuration_error_not_a_guess() -> None:
    with pytest.raises(ValueError):
        build_quiet_window(time(22), None, IST)
    with pytest.raises(ValueError):
        build_quiet_window(time(22), time(7), "Not/AZone")


def test_a_midnight_crossing_window_is_evaluated_in_the_tenants_timezone() -> None:
    w = build_quiet_window(time(22), time(7), IST)
    assert is_quiet(w, _ist(23)) and is_quiet(w, _ist(2)) and is_quiet(w, _ist(6, 59))
    assert not is_quiet(w, _ist(7)) and not is_quiet(w, _ist(12)) and not is_quiet(w, _ist(21, 59))


def test_a_same_day_window() -> None:
    w = build_quiet_window(time(13), time(15), IST)
    assert is_quiet(w, _ist(13)) and is_quiet(w, _ist(14, 59)) and not is_quiet(w, _ist(15))


def test_a_held_alert_is_delivered_when_the_window_ends() -> None:
    w = build_quiet_window(time(22), time(7), IST)
    end = quiet_window_end(w, _ist(23))  # 23:00 IST on the 18th -> 07:00 IST on the 19th
    assert end == _ist(7, day=19).astimezone(timezone.utc)
    end2 = quiet_window_end(w, _ist(2))  # 02:00 IST -> 07:00 IST the same day
    assert end2 == _ist(7).astimezone(timezone.utc)


def test_a_held_alert_is_revalidated_for_freshness_at_delivery() -> None:
    assert revalidate_for_delivery(NOW - timedelta(days=2), now=NOW).deliver_as_confirmed
    stale = revalidate_for_delivery(NOW - timedelta(days=8), now=NOW)
    assert not stale.deliver_as_confirmed and "fresh screenshot" in stale.reason


# ---- monitoring report --------------------------------------------------------------
def test_freshness_follows_the_24h_and_7_day_rules() -> None:
    assert freshness_of(NOW - timedelta(hours=3), now=NOW) is Freshness.FRESH
    assert freshness_of(NOW - timedelta(days=3), now=NOW) is Freshness.STALE
    assert freshness_of(NOW - timedelta(days=7, seconds=1), now=NOW) is Freshness.UNAVAILABLE
    assert freshness_of(None, now=NOW) is Freshness.UNAVAILABLE


def test_the_report_is_as_of_stamped_and_asks_for_evidence_only_where_needed() -> None:
    rep = build_monitoring_report(
        "SKU-1",
        [
            {"id": uuid4(), "label": "Titan Octane", "marketplace": "AMAZON", "evidence_date": NOW - timedelta(hours=2), "price_paise": 269900, "delta_pct": "-9.2", "delta_direction": "DECREASE"},
            {"id": uuid4(), "label": "Fossil Grant", "marketplace": "FLIPKART", "evidence_date": NOW - timedelta(days=3), "price_paise": 349500},
            {"id": uuid4(), "label": "Casio", "marketplace": "AMAZON", "evidence_date": NOW - timedelta(days=12), "price_paise": 219500, "delta_pct": "1.0", "delta_direction": "INCREASE"},
            {"id": uuid4(), "label": "Sonata", "marketplace": "MEESHO"},
        ],
        now=NOW,
    )
    assert rep.as_of == NOW and rep.tracked_count == 4 and rep.fresh_count == 1 and rep.needs_evidence_count == 3
    titan, fossil, casio, sonata = rep.competitors
    assert titan.freshness is Freshness.FRESH and titan.requested_action is None and titan.verified_delta_pct == "-9.2"
    assert fossil.freshness is Freshness.STALE and fossil.requested_action == "send a fresh screenshot of Fossil Grant"
    # past the ceiling: no current price and no delta is stated at all (D6)
    assert casio.freshness is Freshness.UNAVAILABLE and casio.last_verified_price_paise is None and casio.verified_delta_pct is None
    assert sonata.freshness is Freshness.UNAVAILABLE and sonata.requested_action


def test_an_empty_watchlist_is_stated_plainly() -> None:
    rep = build_monitoring_report("SKU-1", [], now=NOW)
    assert rep.tracked_count == 0 and rep.notes == ("No competitors are tracked for this product yet.",)


def test_when_nothing_is_current_the_report_says_so() -> None:
    rep = build_monitoring_report("SKU-1", [{"id": uuid4(), "label": "A"}], now=NOW)
    assert "None of the tracked competitors has current evidence." in rep.notes


# ---- wording rule (AC47) ------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "I'm tracking Titan in real time.",
        "Your competitors are continuously monitored.",
        "Titan is currently priced at Rs 2,699.",
        "I am watching these three for you",
        "Always up to date, 24/7",
        "Live prices for your rivals",
    ],
)
def test_currency_claims_are_caught(text: str) -> None:
    assert currency_claims(text)
    with pytest.raises(ValueError):
        assert_no_currency_claim(text)


@pytest.mark.parametrize(
    "text",
    [
        "As of the screenshot you sent on 17 October, Titan was Rs 2,699.",
        "I have no current evidence for Fossil. Send a fresh screenshot and I will compare it.",
        "Here is the live listing link you shared.",
    ],
)
def test_honest_wording_passes(text: str) -> None:
    assert currency_claims(text) == []


# ---- watchlist management -----------------------------------------------------------
TENANT, USER = uuid4(), uuid4()


class _Urls:
    def __init__(self) -> None:
        self.rows: dict = {}
        self.active_cap_count = 0

    def find_by_url(self, t, url):
        return next((r for r in self.rows.values() if r["url"] == url), None)

    def count_active(self, t):
        return sum(1 for r in self.rows.values() if r["status"] == "ACTIVE")

    def set_label_if_blank(self, t, url_id, label):
        row = self.rows.get(url_id)
        if row is not None and not row.get("label"):
            row["label"] = label
            return True
        return False

    def create_url(self, t, *, marketplace, url, added_by, label=None, linked_sku=None):
        uid = uuid4()
        self.rows[uid] = {"id": uid, "url": url, "status": "ACTIVE", "linked_sku": linked_sku, "label": label}
        return uid

    def get_any_by_id(self, t, uid):
        return self.rows.get(uid)

    def soft_remove(self, t, uid, *, removed_by, reason):
        self.rows[uid].update(status="ARCHIVED", removed_by=removed_by, removal_reason=reason)

    def restore_url(self, t, uid, *, linked_sku):
        self.rows[uid].update(status="ACTIVE")


@pytest.fixture()
def world(monkeypatch):
    urls, events = _Urls(), []
    monkeypatch.setattr(manage, "competitor_url_repo", urls)
    monkeypatch.setattr(manage, "ci_event_repo", SimpleNamespace(record=lambda t, ev, **kw: events.append((ev.value, kw.get("detail")))))
    return SimpleNamespace(urls=urls, events=events)


AMZ = "https://www.amazon.in/dp/B09ABC1234"


def _add(url=AMZ, max_active=5, **kw):
    return manage.add_competitor(TENANT, url=url, product_id="SKU-1", label="Titan", added_by=USER, max_active=max_active, **kw)


def test_add_tracks_a_marketplace_url_and_audits_it(world) -> None:
    r = _add()
    assert r.status is ManageStatus.OK and r.competitor_url_id and world.events == [("COMPETITOR_ADDED", {"marketplace": "AMAZON"})]


def test_add_refuses_a_host_off_the_allowlist(world) -> None:
    r = _add(url="https://www.indiamart.com/x")
    assert r.status is ManageStatus.NOT_ALLOWLISTED and world.urls.rows == {} and world.events == []


def test_add_is_refused_at_the_entitlement_cap_before_any_write(world) -> None:
    _add(url="https://www.amazon.in/dp/B09AAAAAA1", max_active=1)
    r = _add(url="https://www.amazon.in/dp/B09AAAAAA2", max_active=1)
    assert r.status is ManageStatus.CAP_REACHED and len(world.urls.rows) == 1


def test_add_does_not_duplicate_an_already_tracked_url(world) -> None:
    first = _add()
    again = _add()
    assert again.status is ManageStatus.ALREADY_TRACKED and again.competitor_url_id == first.competitor_url_id and len(world.urls.rows) == 1


def test_remove_is_soft_audited_and_idempotent_and_re_adding_restores(world) -> None:
    uid = _add().competitor_url_id
    r = manage.remove_competitor(TENANT, uid, removed_by=USER, reason="not a real rival")
    assert r.status is ManageStatus.OK and world.urls.rows[uid]["status"] == "ARCHIVED" and uid in world.urls.rows  # never deleted
    assert world.urls.rows[uid]["removal_reason"] == "not a real rival"
    manage.remove_competitor(TENANT, uid, removed_by=USER)  # idempotent: no second event
    assert [e[0] for e in world.events].count("COMPETITOR_REMOVED") == 1
    back = _add()
    assert back.status is ManageStatus.RESTORED and back.competitor_url_id == uid and world.urls.rows[uid]["status"] == "ACTIVE"


def test_removing_an_unknown_competitor_is_not_found(world) -> None:
    assert manage.remove_competitor(TENANT, uuid4(), removed_by=USER).status is ManageStatus.NOT_FOUND


def test_a_restore_does_not_count_against_a_cap_it_already_fits_within(world) -> None:
    uid = _add(max_active=1).competitor_url_id
    manage.remove_competitor(TENANT, uid, removed_by=USER)
    assert _add(max_active=1).status is ManageStatus.RESTORED
