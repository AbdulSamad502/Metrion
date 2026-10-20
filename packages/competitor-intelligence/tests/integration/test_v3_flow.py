"""CI V3 against a real Postgres: the CEO-Hub intake pipeline, seller confirmation, alert dedup / quiet hours, persistent findings, housekeeping, watchlist and tenant isolation.
No vision model and no network: a scripted extractor answers each screenshot."""

from __future__ import annotations

import io
import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from competitor_intelligence.direct_path.evidence_intake import IntakeStatus, intake_screenshot, settle_confirmation
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.evidence.image_store import LocalDiskImageStore
from competitor_intelligence.findings import build
from competitor_intelligence.intake.events import CiEvent
from competitor_intelligence.repositories import (
    ci_event_repo,
    ci_finding_repo,
    ci_info_request_repo,
    competitor_price_event_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.scheduler.cycle import run_tenant_cycle
from competitor_intelligence.types import Marketplace
from competitor_intelligence.watchlist import manage

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def _png(seed: int) -> bytes:
    img = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(img)
    for i in range(0, 800, 10 + seed * 3):
        d.rectangle([i, 0, i + 4, 600], fill="black")
    for i in range(0, 600, 30 + seed * 7):
        d.rectangle([0, i, 800, i + 3], fill="gray")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class Scripted:
    """Returns the next scripted extraction for whichever image it is asked to read."""

    def __init__(self, *results) -> None:
        self.results = list(results)

    def extract(self, image_ref: str):
        return self.results.pop(0)


def _listing(price: int, stock: str = "IN_STOCK") -> ExtractionResult:
    return ExtractionResult(fields=(ExtractedField("listed_price_paise", price), ExtractedField("availability", stock), ExtractedField("rating", "4.2"), ExtractedField("title", "Titan Octane")))


@pytest.fixture
def store(tmp_path):
    return LocalDiskImageStore(str(tmp_path))


def _tracked(tenant, sku="SKU-1", url="https://www.amazon.in/dp/B09ABC1234"):
    user = uuid.uuid4()
    return competitor_url_repo.create_url(tenant, marketplace=Marketplace.AMAZON, url=url, added_by=user, label="Titan Octane", linked_sku=sku), user


def _intake(tenant, user, url_id, extractor, store, image, now, **kw):
    return intake_screenshot(tenant, requested_by=user, image_bytes=image, competitor_url_id=url_id, extractor=extractor, image_store=store, max_bytes=5_000_000, now=now, **kw)


def _confirm_all(tenant, user, outcome, now, price=None):
    answers = {q.info_request_id: (price if (q.field_name == "listed_price_paise" and price is not None) else q.proposed_value) for q in outcome.questions}
    return settle_confirmation(tenant, answered_by=user, answers=answers, now=now)


# ---- schema guarantees ----------------------------------------------------------------
def test_ci_event_is_append_only_for_the_app_role(two_tenants):
    tenant, _ = two_tenants
    event_id = ci_event_repo.record(tenant, CiEvent.MONITOR_RUN, detail={"tracked": 1})
    with pytest.raises(DBAPIError):
        with tenant_scope(tenant) as conn:
            conn.execute(text("UPDATE ci_event SET event_type = 'X' WHERE id = :id"), {"id": str(event_id)})
    with pytest.raises(DBAPIError):
        with tenant_scope(tenant) as conn:
            conn.execute(text("DELETE FROM ci_event WHERE id = :id"), {"id": str(event_id)})
    assert [e["id"] for e in ci_event_repo.list_recent(tenant)] == [event_id]


def test_event_detail_cannot_carry_free_text(two_tenants):
    tenant, _ = two_tenants
    from competitor_intelligence.intake.events import UnsafeEventDetail

    with pytest.raises(UnsafeEventDetail):
        ci_event_repo.record(tenant, CiEvent.MONITOR_RUN, detail={"snippet": "Leather feels like cardboard out of the box, cracked in 2 weeks"})


# ---- intake -> confirmation -> verified ------------------------------------------------
def test_a_vision_price_is_held_pending_until_the_seller_confirms_it(two_tenants, store):
    tenant, _ = two_tenants
    url_id, user = _tracked(tenant)
    now = datetime.now(timezone.utc)
    out = _intake(tenant, user, url_id, Scripted(_listing(269900)), store, _png(1), now)
    assert out.status is IntakeStatus.NEEDS_CONFIRMATION and {q.field_name for q in out.questions} == {"listed_price_paise", "availability"}
    snap = competitor_snapshot_repo.get_by_id(tenant, out.snapshot_id)
    assert snap["price_confirmation"] == "PENDING"
    assert competitor_snapshot_repo.latest_usable_snapshot(tenant, url_id) is None  # a pending price never reaches a consequential read

    settle_confirmation(tenant, answered_by=user, answers={out.questions[0].info_request_id: 289900}, now=now)  # price corrected, stock still open
    assert competitor_snapshot_repo.get_by_id(tenant, out.snapshot_id)["price_confirmation"] == "PENDING"
    settle_confirmation(tenant, answered_by=user, answers={out.questions[1].info_request_id: "IN_STOCK"}, now=now)
    usable = competitor_snapshot_repo.latest_usable_snapshot(tenant, url_id)
    assert usable is not None and usable["listed_price_paise"] == 289900  # the seller's value won, not the vision read
    names = [e["event_type"] for e in ci_event_repo.list_recent(tenant)]
    assert {"EVIDENCE_RECEIVED", "FIELD_CONFIRMATION_REQUESTED", "FIELD_CONFIRMED"} <= set(names)


def test_declining_keeps_the_snapshot_out_of_every_read(two_tenants, store):
    tenant, _ = two_tenants
    url_id, user = _tracked(tenant)
    now = datetime.now(timezone.utc)
    out = _intake(tenant, user, url_id, Scripted(_listing(269900)), store, _png(2), now)
    settle_confirmation(tenant, answered_by=user, answers={}, declined=tuple(q.info_request_id for q in out.questions), now=now)
    assert competitor_snapshot_repo.get_by_id(tenant, out.snapshot_id)["price_confirmation"] == "DECLINED"
    assert competitor_snapshot_repo.latest_usable_snapshot(tenant, url_id) is None
    assert competitor_snapshot_repo.latest_comparable_snapshot(tenant, competitor_url_id=url_id, variant_key=None) is None


def test_duplicate_and_unreadable_images_store_nothing(two_tenants, store):
    tenant, _ = two_tenants
    url_id, user = _tracked(tenant)
    now = datetime.now(timezone.utc)
    img = _png(3)
    first = _intake(tenant, user, url_id, Scripted(_listing(269900)), store, img, now)
    assert first.status is IntakeStatus.NEEDS_CONFIRMATION
    again = _intake(tenant, user, url_id, Scripted(), store, img, now)
    assert again.status is IntakeStatus.DUPLICATE and again.duplicate_of == first.evidence_id
    blurry = io.BytesIO()
    Image.new("RGB", (800, 600), "#dddddd").save(blurry, "PNG")
    assert _intake(tenant, user, url_id, Scripted(), store, blurry.getvalue(), now).status is IntakeStatus.REJECTED_QUALITY
    with tenant_scope(tenant) as conn:
        assert conn.execute(text("SELECT count(*) FROM competitor_evidence")).scalar_one() == 1


def test_another_tenants_competitor_cannot_be_used_for_intake(two_tenants, store):
    a, b = two_tenants
    url_id, user = _tracked(a)
    out = _intake(b, uuid.uuid4(), url_id, Scripted(_listing(100)), store, _png(4), datetime.now(timezone.utc))
    assert out.status is IntakeStatus.COMPETITOR_NOT_FOUND
    assert ci_info_request_repo.list_open(b) == [] and ci_event_repo.list_recent(b) == []


# ---- a verified change: price event, alert, finding with evidence ----------------------
def _two_confirmed_snapshots(tenant, user, url_id, store, now, first=297000, second=269900):
    o1 = _intake(tenant, user, url_id, Scripted(_listing(first)), store, _png(5), now - timedelta(hours=5))
    _confirm_all(tenant, user, o1, now - timedelta(hours=5))
    o2 = _intake(tenant, user, url_id, Scripted(_listing(second)), store, _png(6), now - timedelta(hours=1))
    _confirm_all(tenant, user, o2, now - timedelta(hours=1))
    return o1, o2


def test_a_confirmed_second_screenshot_raises_one_alert_and_a_finding_that_cites_its_evidence(two_tenants, store):
    tenant, _ = two_tenants
    url_id, user = _tracked(tenant)
    now = datetime.now(timezone.utc)
    _, o2 = _two_confirmed_snapshots(tenant, user, url_id, store, now)
    events = competitor_price_event_repo.list_recent_for_tenant(tenant, since=now - timedelta(days=1))
    assert len(events) == 1 and events[0]["delta_paise"] == -27100 and events[0]["threshold_breached"]
    findings = ci_finding_repo.list_for_product(tenant, "SKU-1")
    assert len(findings) == 1 and findings[0]["finding_type"] == "PRICE_CHANGE" and findings[0]["seller_confirmation"] == "CONFIRMED"
    assert list(findings[0]["evidence_refs"]) == [o2.evidence_id] and findings[0]["payload"]["toPricePaise"] == 269900
    names = [e["event_type"] for e in ci_event_repo.list_recent(tenant)]
    assert "ALERT_RAISED" in names and "FINDING_CREATED" in names


def test_the_same_evidence_pair_never_raises_a_second_alert(two_tenants, store):
    tenant, _ = two_tenants
    url_id, user = _tracked(tenant)
    now = datetime.now(timezone.utc)
    _, o2 = _two_confirmed_snapshots(tenant, user, url_id, store, now)
    # re-confirming (a correction applied again) re-runs detection for the same snapshot pair
    from competitor_intelligence.direct_path.research_run import submit_manual_correction

    submit_manual_correction(tenant, o2.snapshot_id, manual_fields={"listed_price_paise": 269900}, now=now)
    visible = competitor_price_event_repo.list_recent_for_tenant(tenant, since=now - timedelta(days=1))
    assert len(visible) == 1  # the repeat was recorded as an observation but suppressed as an alert (DEDUP)
    assert "ALERT_SUPPRESSED_DEDUP" in [e["event_type"] for e in ci_event_repo.list_recent(tenant)]


def test_findings_are_persistent_unique_per_observation_and_tenant_scoped(two_tenants, store):
    a, b = two_tenants
    url_id, user = _tracked(a)
    now = datetime.now(timezone.utc)
    _two_confirmed_snapshots(a, user, url_id, store, now)
    finding = ci_finding_repo.list_for_product(a, "SKU-1")[0]
    again, created = ci_finding_repo.upsert(a, product_id="SKU-1", competitor_url_id=url_id, finding_type="PRICE_CHANGE", dedup_key=finding["dedup_key"],
                                            evidence_refs=list(finding["evidence_refs"]), confidence="DERIVED", freshness="FRESH", payload={"x": 1})
    assert again == finding["id"] and created is False
    assert ci_finding_repo.get(a, finding["id"]) is not None
    assert ci_finding_repo.get(b, finding["id"]) is None  # another tenant's id is simply absent (RLS)
    assert ci_finding_repo.list_for_product(b, "SKU-1") == []


def test_a_finding_without_evidence_cannot_exist(two_tenants):
    tenant, _ = two_tenants
    with pytest.raises(ci_finding_repo.FindingWithoutEvidence):
        ci_finding_repo.upsert(tenant, product_id="SKU-1", competitor_url_id=None, finding_type="FRESHNESS", dedup_key="k", evidence_refs=[], confidence="DERIVED", freshness="STALE", payload={})
    with pytest.raises(DBAPIError):  # and the database refuses it even if the application did not
        with tenant_scope(tenant) as conn:
            conn.execute(text("INSERT INTO ci_finding (tenant_id, product_id, finding_type, dedup_key, evidence_refs, confidence, freshness, created_at) "
                              "VALUES (:t, 'S', 'FRESHNESS', 'k2', '{}', 'DERIVED', 'STALE', now())"), {"t": str(tenant)})


# ---- quiet hours, held alerts, housekeeping ---------------------------------------------
def _set_quiet_hours(tenant, start, end, tz):
    with tenant_scope(tenant) as conn:
        conn.execute(text("INSERT INTO ci_tenant_config (tenant_id, quiet_hours_start, quiet_hours_end, quiet_hours_tz, updated_at) VALUES (:t, :s, :e, :z, now())"),
                     {"t": str(tenant), "s": start, "e": end, "z": tz})


def test_an_alert_in_quiet_hours_is_held_hidden_then_released_with_a_finding(two_tenants, store):
    tenant, _ = two_tenants
    url_id, user = _tracked(tenant)
    _set_quiet_hours(tenant, time(0, 0), time(23, 59, 59), "UTC")  # always quiet in UTC
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _two_confirmed_snapshots(tenant, user, url_id, store, now)
    names = [e["event_type"] for e in ci_event_repo.list_recent(tenant)]
    assert "ALERT_HELD_QUIET_HOURS" in names and "ALERT_RAISED" not in names
    assert competitor_price_event_repo.list_recent_for_tenant(tenant, since=now - timedelta(days=1)) == []  # held: not shown
    assert ci_finding_repo.list_for_product(tenant, "SKU-1") == []
    counts = run_tenant_cycle(tenant, now=now + timedelta(days=1))  # the window has ended (hold_until passed)
    assert counts["delivered"] == 1 and counts["withheld"] == 0
    assert len(competitor_price_event_repo.list_recent_for_tenant(tenant, since=now - timedelta(days=1))) == 1
    assert len(ci_finding_repo.list_for_product(tenant, "SKU-1")) == 1


def test_a_held_alert_whose_evidence_went_stale_is_withheld_not_delivered(two_tenants, store):
    tenant, _ = two_tenants
    url_id, user = _tracked(tenant)
    _set_quiet_hours(tenant, time(0, 0), time(23, 59, 59), "UTC")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _two_confirmed_snapshots(tenant, user, url_id, store, now)
    counts = run_tenant_cycle(tenant, now=now + timedelta(days=9))  # past the 7-day ceiling by delivery time
    assert counts["withheld"] == 1 and counts["delivered"] == 0
    assert competitor_price_event_repo.list_recent_for_tenant(tenant, since=now - timedelta(days=30)) == []
    assert "ALERT_WITHHELD_STALE" in [e["event_type"] for e in ci_event_repo.list_recent(tenant)]


def test_housekeeping_expires_unanswered_questions_and_adds_one_freshness_reminder(two_tenants, store):
    tenant, _ = two_tenants
    url_id, user = _tracked(tenant)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    out = _intake(tenant, user, url_id, Scripted(_listing(269900)), store, _png(7), now - timedelta(days=20))
    assert ci_info_request_repo.list_open(tenant)
    counts = run_tenant_cycle(tenant, now=now)
    assert counts["expired"] == len(out.questions) and ci_info_request_repo.list_open(tenant) == []
    assert counts["reminders"] == 1
    again = run_tenant_cycle(tenant, now=now + timedelta(hours=1))
    assert again["reminders"] == 1 and len(ci_finding_repo.list_for_product(tenant, "SKU-1")) == 1  # the same screenshot is one reminder, not two
    f = ci_finding_repo.list_for_product(tenant, "SKU-1")[0]
    assert f["finding_type"] == "FRESHNESS" and len(f["evidence_refs"]) == 1 and f["freshness"] in ("STALE", "UNAVAILABLE")
    # a snapshot whose question expired is still not usable for any price read
    assert competitor_snapshot_repo.latest_usable_snapshot(tenant, url_id) is None


# ---- watchlist ----------------------------------------------------------------------
def test_watchlist_add_remove_restore_with_history_and_isolation(two_tenants):
    a, b = two_tenants
    user = uuid.uuid4()
    r = manage.add_competitor(a, url="https://www.amazon.in/dp/B09ZZZ0001", product_id="SKU-1", label="Rival", added_by=user, max_active=None)
    assert r.status is manage.ManageStatus.OK
    assert manage.add_competitor(a, url="https://www.amazon.in/dp/B09ZZZ0001", product_id="SKU-1", label=None, added_by=user, max_active=None).status is manage.ManageStatus.ALREADY_TRACKED
    assert manage.remove_competitor(b, r.competitor_url_id, removed_by=user).status is manage.ManageStatus.NOT_FOUND  # another tenant cannot remove it
    assert manage.remove_competitor(a, r.competitor_url_id, removed_by=user, reason="not a rival").status is manage.ManageStatus.OK
    assert competitor_url_repo.list_active_by_linked_sku(a, "SKU-1") == []
    row = competitor_url_repo.get_any_by_id(a, r.competitor_url_id)
    assert row["status"] == "ARCHIVED"
    again = manage.add_competitor(a, url="https://www.amazon.in/dp/B09ZZZ0001", product_id="SKU-1", label=None, added_by=user, max_active=None)
    assert again.status is manage.ManageStatus.RESTORED and again.competitor_url_id == r.competitor_url_id
    assert [e["event_type"] for e in ci_event_repo.list_recent(a)][:3] == ["COMPETITOR_ADDED", "COMPETITOR_REMOVED", "COMPETITOR_ADDED"]
    assert ci_event_repo.list_recent(b) == []
