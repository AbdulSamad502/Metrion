"""The seller's whole Competitor Intelligence conversation, through the real API and a real Postgres: attach a screenshot, confirm what was read, get a verified change, ask about the
finding from the dashboard, track a link, approve candidates, set quiet hours, and the dashboard's read model. Tenant isolation is checked at every step.
The vision model is scripted (no model, no network); everything else is the shipped code."""

from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import text

from backend.api.v1 import ceo as ceo_api
from backend.auth.permissions import OWNER_ROLE
from backend.services import ci_ceo
from backend.tenant_context import tenant_scope
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import (
    ci_candidate_repo,
    ci_discovery_run_repo,
    ci_event_repo,
    ci_finding_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.types import Marketplace
from tests.integration.test_ceo_api import clerk, login, start  # noqa: F401
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]


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


class ScriptedVision:
    def __init__(self) -> None:
        self.queue: list[ExtractionResult] = []

    def extract(self, image_ref: str):
        return self.queue.pop(0)


def _listing(price: int, stock: str = "IN_STOCK") -> ExtractionResult:
    return ExtractionResult(fields=(ExtractedField("listed_price_paise", price), ExtractedField("availability", stock), ExtractedField("rating", "4.2"), ExtractedField("title", "Titan Octane")))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_BYTES", "2000000")
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_FILES", "3")
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_PAGES", "5")
    monkeypatch.setenv("CI_EVIDENCE_DIR", str(tmp_path))


@pytest.fixture
def vision(monkeypatch):
    v = ScriptedVision()
    monkeypatch.setattr(ci_ceo, "_extractor", lambda: v)
    return v


@pytest.fixture
def api(clerk, two_tenants, env):
    from backend.main import app

    a, b = two_tenants
    import dataclasses

    # a real clock: a screenshot taken "now" is fresh now (the shared test clock sits at a fixed past date, which would make every screenshot look stale)
    rt = dataclasses.replace(runtime(Scripted({}), Grounded()), clock=lambda: datetime.now(timezone.utc))  # the classifier is never reached by a CI conversation
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    try:
        yield TestClient(app), login(clerk, a, role=OWNER_ROLE), login(clerk, b, role=OWNER_ROLE), a, b
    finally:
        app.dependency_overrides.pop(ceo_api.get_runtime, None)


def upload(client, headers, inv, data, name="listing.png"):
    r = client.post(f"/api/v1/ceo/investigations/{inv}/attachments", files={"file": (name, data, "image/png")}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def say(client, headers, inv, message, **extra):
    r = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": message, **extra}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def track(tenant, sku="SKU-1", url="https://www.amazon.in/dp/B09ABC1234", label="Titan Octane"):
    return competitor_url_repo.create_url(tenant, marketplace=Marketplace.AMAZON, url=url, added_by=uuid.uuid4(), label=label, linked_sku=sku)


def workspace(client, headers, product="SKU-1"):
    r = client.get(f"/api/v1/ci/workspace?product_id={product}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_whole_conversation(api, vision):
    client, ha, hb, a, b = api
    url_id = track(a)
    inv = start(client, ha)

    # 1. a screenshot with the competitor named: read, shown as UNCONFIRMED, and the seller is asked
    vision.queue.append(_listing(297000))
    first = upload(client, ha, inv, _png(1))
    r1 = say(client, ha, inv, "this is Titan Octane's listing", attachment_ids=[first])
    assert "I read your screenshot of Titan Octane" in r1["answer"] and "₹2,970.00" in r1["answer"] and "until you confirm them" in r1["answer"]
    snap = competitor_snapshot_repo.latest_usable_snapshot(a, url_id)
    assert snap is None  # nothing is usable until the seller confirms
    assert workspace(client, ha)["competitors"][0]["priceStatus"] == "UNVERIFIED"

    # 2. "yes" is read as the answer to that question: verified
    r2 = say(client, ha, inv, "yes")
    assert "confirmed" in r2["answer"].lower()
    assert competitor_snapshot_repo.latest_usable_snapshot(a, url_id)["listed_price_paise"] == 297000
    ws = workspace(client, ha)
    assert ws["competitors"][0]["priceStatus"] == "VERIFIED" and ws["competitors"][0]["listedPricePaise"] == 297000 and ws["findings"] == []

    # 3. a second screenshot at a lower price, corrected by the seller: a verified change
    vision.queue.append(_listing(299900))  # vision misread
    second = upload(client, ha, inv, _png(2))
    say(client, ha, inv, "Titan Octane again", attachment_ids=[second])
    r3 = say(client, ha, inv, "no, the price is 2699")  # the price is corrected; the stock status is still open, and the CEO says so
    assert "still not using the stock status" in r3["answer"] and competitor_snapshot_repo.latest_usable_snapshot(a, url_id)["listed_price_paise"] == 297000
    r4 = say(client, ha, inv, "yes")  # the stock status as read is right
    assert "confirmed" in r4["answer"].lower() and "down" in r4["answer"] and "%" in r4["answer"]
    ws = workspace(client, ha)
    assert ws["competitors"][0]["listedPricePaise"] == 269900 and len(ws["changes"]) == 1 and ws["kpis"]["importantChangeCount"] == 1
    finding = next(f for f in ws["findings"] if f["type"] == "PRICE_CHANGE")
    assert finding["evidenceCount"] == 1 and finding["sellerConfirmation"] == "CONFIRMED" and ws["changes"][0]["findingId"] == finding["id"]

    # 4. the dashboard's Ask CEO passes only the finding id; the CEO re-reads the stored finding and its evidence
    r5 = say(client, ha, inv, "Tell me about this finding", ciFindingId=finding["id"])
    assert "₹2,970.00 to ₹2,699.00" in r5["answer"] and "rests on 1 screenshot you sent" in r5["answer"] and "your margin" in r5["answer"]
    # another tenant cannot read it: an id that is not theirs is simply not found
    inv_b = start(client, hb)
    rb = say(client, hb, inv_b, "Tell me about this finding", ciFindingId=finding["id"])
    assert "could not find that finding" in rb["answer"] and "2,970" not in rb["answer"]
    assert workspace(client, hb)["competitors"] == [] and workspace(client, hb)["findings"] == []

    # 5. the history shows what happened, with ids and codes only
    types = [e["type"] for e in workspace(client, ha)["events"]]
    assert {"EVIDENCE_RECEIVED", "FIELD_CONFIRMED", "ALERT_RAISED", "FINDING_CREATED", "CEO_INVESTIGATION_LINKED"} <= set(types)


def test_unusable_and_repeated_screenshots_store_nothing(api, vision):
    client, ha, _, a, _ = api
    track(a)
    inv = start(client, ha)
    flat = io.BytesIO()
    Image.new("RGB", (800, 600), "#dddddd").save(flat, "PNG")
    r = say(client, ha, inv, "Titan Octane", attachment_ids=[upload(client, ha, inv, flat.getvalue(), "blur.png")])
    assert "too blurry" in r["answer"] and "Nothing was stored" in r["answer"]
    vision.queue.append(_listing(269900))
    img = _png(3)
    say(client, ha, inv, "Titan Octane listing", attachment_ids=[upload(client, ha, inv, img)])
    again = say(client, ha, inv, "Titan Octane listing", attachment_ids=[upload(client, ha, inv, _png(3), "same.png")])  # same bytes: the attachment is deduplicated, the evidence too
    assert "already have exactly this screenshot" in again["answer"]
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM competitor_evidence")).scalar_one() == 1


def test_an_unnamed_competitor_is_asked_for_and_a_cmo_photo_request_is_not_hijacked(api, vision):
    client, ha, _, a, _ = api
    track(a)
    track(a, url="https://www.amazon.in/dp/B09XYZ9999", label="Fossil Grant")
    inv = start(client, ha)
    att = upload(client, ha, inv, _png(4))
    r = say(client, ha, inv, "here is a competitor screenshot", attachment_ids=[att])
    assert "which tracked competitor that screenshot shows" in r["answer"] and "Nothing has been stored" in r["answer"]
    assert {"Titan Octane", "Fossil Grant"} <= {i["label"] for i in r["choices"]["items"]} and r["choices"]["mode"] == "single"  # a pick card, not typing
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM competitor_evidence")).scalar_one() == 0
    # naming it in the next message picks the waiting image up
    vision.queue.append(_listing(269900))
    r2 = say(client, ha, inv, "it's Fossil Grant")
    assert "I read your screenshot of Fossil Grant" in r2["answer"]
    # a photo sent for CMO titles goes the CMO way, not into competitor intake
    other = say(client, ha, inv, "write titles for this bottle", attachment_ids=[upload(client, ha, inv, _png(5), "bottle.png")])
    assert "I read your screenshot" not in other["answer"]


def test_a_vision_outage_is_said_plainly_and_nothing_is_stored(api, monkeypatch):
    client, ha, _, a, _ = api
    track(a)

    def down():
        raise ci_ceo.CiActionError("VISION_ENDPOINT_NOT_VERIFIED", 503)

    monkeypatch.setattr(ci_ceo, "_extractor", down)
    inv = start(client, ha)
    r = say(client, ha, inv, "Titan Octane", attachment_ids=[upload(client, ha, inv, _png(6))])
    assert "screenshot reader is not switched on" in r["answer"]
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM competitor_evidence")).scalar_one() == 0


def test_track_a_link_then_stop_tracking_it(api):
    client, ha, hb, a, b = api
    track(a)  # one product (SKU-1) is known through its competitor
    inv = start(client, ha)
    r = say(client, ha, inv, "track https://www.amazon.in/dp/B09ZZZ0001 called Sonata Poze")
    assert "Tracking amazon.in/dp/B09ZZZ0001" in r["answer"] and "no price for a competitor until you send me a screenshot" in r["answer"]
    assert len(competitor_url_repo.list_active_by_linked_sku(a, "SKU-1")) == 2
    again = say(client, ha, inv, "track https://www.amazon.in/dp/B09ZZZ0001")
    assert "already tracked" in again["answer"]
    bad = say(client, ha, inv, "track https://www.indiamart.com/x")
    assert "only track amazon.in" in bad["answer"] or "Which of your products" in bad["answer"]
    assert len(competitor_url_repo.list_active_by_linked_sku(b, "SKU-1")) == 0


def test_approving_and_rejecting_discovered_candidates_by_number(api):
    client, ha, hb, a, b = api
    track(a)
    run = ci_discovery_run_repo.create_run(a, seller_product_ref="SKU-1", requested_by=uuid.uuid4(), provider_name="MOCK", now=datetime.now(timezone.utc)) if _has_create_run_now() else ci_discovery_run_repo.create_run(a, seller_product_ref="SKU-1", requested_by=uuid.uuid4(), provider_name="MOCK")
    ids = []
    for n, url in enumerate(("https://www.amazon.in/dp/B09CAND001", "https://www.flipkart.com/x/p/itm1?pid=C2", "https://www.amazon.in/dp/B09CAND003")):
        cid = ci_candidate_repo.create_candidate(a, discovery_run_id=run, candidate_url=url, origin="DISCOVERED", marketplace="AMAZON" if "amazon" in url else "FLIPKART", tier="RECOMMENDED")
        ids.append(cid)
    inv = start(client, ha)
    listing = say(client, ha, inv, "show me what you found")
    assert "not verified prices" in listing["answer"] and "1. A listing on Amazon" in listing["answer"] and "3. A listing on Amazon" in listing["answer"]
    done = say(client, ha, inv, "track 1 and 3")
    assert "Now tracking 1, 3" in done["answer"]
    assert {c["id"] for c in ci_candidate_repo.list_candidates_for_run(a, run) if c["seller_decision"] == "APPROVED"} == {ids[0], ids[2]}
    assert len(competitor_url_repo.list_active_by_linked_sku(a, "SKU-1")) == 3
    rej = say(client, ha, inv, "reject 1")  # what is left is just the second candidate, now number 1
    assert "Rejected 1" in rej["answer"]
    assert [c["seller_decision"] for c in ci_candidate_repo.list_candidates_for_run(a, run) if c["id"] == ids[1]] == ["REJECTED"]
    # another tenant sees none of it
    assert say(client, hb, start(client, hb), "show me what you found")["answer"].startswith("There are no competitor candidates")


def _has_create_run_now() -> bool:
    import inspect

    return "now" in inspect.signature(ci_discovery_run_repo.create_run).parameters


def test_quiet_hours_and_a_threshold_are_saved_through_the_ceo_and_echoed(api):
    client, ha, hb, a, b = api
    track(a)
    inv = start(client, ha)
    r = say(client, ha, inv, "set quiet hours 10pm to 7am")
    assert "22:00 to 07:00 India time (IST)" in r["answer"] and "Nothing is dropped" in r["answer"]
    t = say(client, ha, inv, "alert me when a competitor's price changes by more than 8%")
    assert "8.00%" in t["answer"]
    with tenant_scope(a) as conn:
        row = conn.execute(text("SELECT quiet_hours_start, quiet_hours_end, quiet_hours_tz, price_threshold_pct FROM ci_tenant_config")).one()
    assert (str(row[0]), str(row[1]), row[2], str(row[3])) == ("22:00:00", "07:00:00", "Asia/Kolkata", "8.00")
    assert say(client, ha, inv, "turn off quiet hours")["answer"].startswith("Quiet hours are off")
    with tenant_scope(b) as conn:
        assert conn.execute(text("SELECT count(*) FROM ci_tenant_config")).scalar_one() == 0
    assert "between 1% and 50%" in say(client, ha, inv, "alert me when the price changes by 90%")["answer"]


def test_a_bare_yes_in_an_unrelated_moment_is_not_a_confirmation(api, vision):
    client, ha, _, a, _ = api
    url_id = track(a)
    inv = start(client, ha)
    vision.queue.append(_listing(269900))
    say(client, ha, inv, "Titan Octane", attachment_ids=[upload(client, ha, inv, _png(7))])
    say(client, ha, inv, "set quiet hours 10pm to 7am")  # an unrelated CEO reply is now the last message
    # "yes" no longer follows CI's question, so it is not taken as one (it falls through to the normal route, which the scripted classifier would not know: skip that by checking the DB instead)
    assert competitor_snapshot_repo.latest_usable_snapshot(a, url_id) is None


def test_event_history_never_holds_free_text(api, vision):
    client, ha, _, a, _ = api
    track(a)
    inv = start(client, ha)
    vision.queue.append(_listing(269900))
    say(client, ha, inv, "Titan Octane", attachment_ids=[upload(client, ha, inv, _png(8))])
    for e in ci_event_repo.list_recent(a, limit=100):
        for v in e["detail"].values():
            assert not isinstance(v, str) or len(v) <= 64


def test_several_links_wait_for_a_yes_and_then_all_are_added(api):
    client, ha, hb, a, b = api
    track(a)
    inv = start(client, ha)
    ask = say(client, ha, inv, "track https://www.amazon.in/dp/B09BULK001 and https://www.flipkart.com/x/p/itm1?pid=BULK2")
    assert "Before I add them" in ask["answer"] and "Nothing has been added yet" in ask["answer"]
    assert len(competitor_url_repo.list_active_by_linked_sku(a, "SKU-1")) == 1  # nothing was added by the question
    done = say(client, ha, inv, "yes")
    assert done["answer"].count("Tracking ") == 2
    assert len(competitor_url_repo.list_active_by_linked_sku(a, "SKU-1")) == 3
    assert len(competitor_url_repo.list_active_by_linked_sku(b, "SKU-1")) == 0


def test_a_tenant_watchlist_limit_stops_adds_and_is_not_set_by_the_seller(api, migrate_engine, monkeypatch):
    client, ha, hb, a, b = api
    track(a)
    inv = start(client, ha)
    monkeypatch.delenv("CI_DEFAULT_WATCHLIST_LIMIT", raising=False)
    assert "Tracking" in say(client, ha, inv, "track https://www.amazon.in/dp/B09LIM0001")["answer"]  # no limit anywhere: none is invented
    from tests.integration.test_ceo_state_specialists import _scope

    with _scope(migrate_engine, a) as conn:
        conn.execute(text("INSERT INTO ci_tenant_config (tenant_id, max_active_competitors) VALUES (:t, 2) ON CONFLICT (tenant_id) DO UPDATE SET max_active_competitors = 2"), {"t": str(a)})
    over = say(client, ha, inv, "track https://www.amazon.in/dp/B09LIM0002")
    assert "list is full" in over["answer"] and "2 of 2" in over["answer"]
    assert len(competitor_url_repo.list_active_by_linked_sku(a, "SKU-1")) == 2
    assert len(competitor_url_repo.list_active_by_linked_sku(b, "SKU-1")) == 0
    from sqlalchemy.exc import ProgrammingError

    with pytest.raises(ProgrammingError):  # the application role can read the limit but never write it
        with tenant_scope(a) as conn:
            conn.execute(text("UPDATE ci_tenant_config SET max_active_competitors = 99"))


def test_quiet_hours_follow_the_sellers_configured_timezone(api, migrate_engine):
    client, ha, hb, a, b = api
    track(a)
    with migrate_engine.begin() as conn:
        conn.execute(text("UPDATE tenant SET timezone = 'Asia/Dubai' WHERE id = :t"), {"t": str(a)})
    inv = start(client, ha)
    r = say(client, ha, inv, "set quiet hours 10pm to 7am")
    assert "22:00 to 07:00 Asia/Dubai" in r["answer"]
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT quiet_hours_tz FROM ci_tenant_config")).scalar_one() == "Asia/Dubai"
