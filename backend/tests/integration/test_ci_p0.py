"""P0 of the CI completion plan, through the real CEO API and a real Postgres, with stored state checked:

* the competitor limit (five ACTIVE competitors per seller, across every product and marketplace), enforced inside the write, atomically, on every path
* ALL / "track 1 and 3" never adds part of a request that does not fit
* "track my competitors" -> names to choose from, with ALL
* "track CASPIAN Astra 1L and The Better Home 1L" -> each name resolved to the discovered listing's own id
* a single product is the product; a screenshot with no readable price is asked about again."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.tenant_context import tenant_scope
from competitor_intelligence.discovery.search_provider import SearchResult
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import (
    ci_candidate_repo, ci_discovery_run_repo, ci_info_request_repo, ci_search_query_repo, ci_search_result_repo, competitor_snapshot_repo, competitor_url_repo, seller_product_profile_repo,
)
from competitor_intelligence.types import Marketplace
from competitor_intelligence.watchlist import manage
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import _png, api, env, say, start, upload, vision, workspace  # noqa: F401

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"


def _product(tenant, app_user, sku=SKU, title=TITLE):
    seller_product_profile_repo.upsert_profile(tenant, sku, category="Water Bottles", attributes=[{"key": "title", "value": title}], keywords=None, price_paise=39900, fulfillment_type=None, updated_by=app_user)


def _add(tenant, n, sku=SKU, market="amazon.in", label=None):
    return manage.add_competitor(tenant, url=f"https://www.{market}/dp/B0CAP{n:05d}", product_id=sku, label=label or f"Rival {n}", added_by=uuid.uuid4(), max_active=None)


def _active(tenant):
    with tenant_scope(tenant) as conn:
        return conn.execute(text("SELECT count(*) FROM competitor_url WHERE status = 'ACTIVE'")).scalar_one()


def _leads(tenant, titles, sku=SKU):
    """Discovery leads as a search would have stored them: the run, its query, the results (with titles) and one candidate per result."""
    run = ci_discovery_run_repo.create_run(tenant, seller_product_ref=sku, requested_by=uuid.uuid4(), provider_name="MOCK")
    q = ci_search_query_repo.insert_query(tenant, discovery_run_id=run, query_text_value="steel water bottle", query_kind="PRODUCT_TERM", provider_name="MOCK", sent_at=datetime.now(timezone.utc))
    now = datetime.now(timezone.utc)
    urls = []
    for i, t in enumerate(titles, start=1):
        url = f"https://www.amazon.in/dp/B0LEAD{i:05d}"
        urls.append(url)
        ci_search_result_repo.insert_results(tenant, search_query_id=q, fetched_at=now, ttl_hours=24, results=[SearchResult(rank=i, url=url, title=t, snippet=t, source="MOCK", retrieved_at=now, provider_response_ref=None)])
        ci_candidate_repo.create_candidate(tenant, discovery_run_id=run, candidate_url=url, origin="DISCOVERED", marketplace="AMAZON", tier="ANALYZED")
    return run, urls


# ============================================================ the limit
def test_the_limit_is_five_across_every_product_and_marketplace_and_names_who_holds_the_slots(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    for n in range(1, 4):
        assert _add(a, n).status.value == "OK"
    for n in range(4, 6):  # another product and another marketplace: the same seller, the same five slots
        assert _add(a, n, sku="SKU-2", market="flipkart.com").status.value == "OK"
    inv = start(client, ha)
    r = say(client, ha, inv, "track https://www.amazon.in/dp/B0NEWSIX01 for my Steel Water Bottle 1L (CI TEST)")
    assert "list is full" in r["answer"] and "5 of 5" in r["answer"] and "stop tracking Rival 1" in r["answer"], r["answer"]
    assert _active(a) == 5 and workspace(client, ha, SKU)["watchlist"] == {"limit": 5, "used": 5, "free": 0}
    assert _active(b) == 0  # another seller has their own five


def test_stopped_competitors_and_pending_leads_do_not_count_and_a_restore_takes_a_slot(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    ids = [_add(a, n).competitor_url_id for n in range(1, 6)]
    _leads(a, ["Cult 1L Steel Bottle", "Milton Aqua 1L"])  # pending leads: not tracked, not counted
    assert _active(a) == 5
    manage.remove_competitor(a, ids[0], removed_by=uuid.uuid4(), reason=None)
    assert _active(a) == 4 and _add(a, 6).status.value == "OK" and _active(a) == 5  # the freed slot is usable at once
    assert manage.add_competitor(a, url="https://www.amazon.in/dp/B0CAP00001", product_id=SKU, label="Rival 1", added_by=uuid.uuid4(), max_active=None).status.value == "CAP_REACHED"  # restoring needs a slot
    assert competitor_url_repo.find_by_url(a, "https://www.amazon.in/dp/B0CAP00001")["status"] == "ARCHIVED"


def test_approving_a_lead_into_a_full_list_leaves_the_lead_undecided(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    for n in range(1, 6):
        _add(a, n)
    run, urls = _leads(a, ["Cult 1L Steel Bottle"])
    inv = start(client, ha)
    r = say(client, ha, inv, "track 1")
    assert "list is full" in r["answer"], r["answer"]
    cand = ci_candidate_repo.list_candidates_for_run(a, run)[0]
    assert cand["seller_decision"] == "NONE" and cand["competitor_url_id"] is None and _active(a) == 5


def test_two_adds_at_once_can_never_take_the_last_slot_twice(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    for n in range(1, 5):
        _add(a, n)
    results: list[str] = []

    def worker(n: int) -> None:
        results.append(_add(a, 100 + n).status.value)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results).count("OK") == 1 and results.count("CAP_REACHED") == 7 and _active(a) == 5


def test_a_tenant_own_limit_overrides_the_default(api, app_user, migrate_engine):
    from tests.integration.test_ceo_state_specialists import _scope

    client, ha, hb, a, b = api
    _product(a, app_user)
    with _scope(migrate_engine, a) as conn:
        conn.execute(text("INSERT INTO ci_tenant_config (tenant_id, max_active_competitors) VALUES (:t, 2) ON CONFLICT (tenant_id) DO UPDATE SET max_active_competitors = 2"), {"t": str(a)})
    assert _add(a, 1).status.value == "OK" and _add(a, 2).status.value == "OK" and _add(a, 3).status.value == "CAP_REACHED"


# ============================================================ ALL and bulk respect the limit
def test_track_all_and_bulk_add_never_add_part_of_a_request_that_does_not_fit(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    for n in range(1, 4):
        _add(a, n)  # 3 used, 2 free
    _leads(a, [f"Lead bottle {i}" for i in range(1, 7)])
    inv = start(client, ha)
    r = say(client, ha, inv, "track all")
    assert "have 2 free competitor slots of 5" in r["answer"] and "Nothing has been added yet" in r["answer"], r["answer"]
    assert _active(a) == 3
    bulk = say(client, ha, inv, "track https://www.amazon.in/dp/B0BULK0001 and https://www.amazon.in/dp/B0BULK0002 and https://www.amazon.in/dp/B0BULK0003 for my Steel Water Bottle 1L (CI TEST)")
    assert "3 links but have 2 free" in bulk["answer"] and _active(a) == 3
    ok = say(client, ha, inv, "track 1 and 2")
    assert "Now tracking 1, 2" in ok["answer"] and _active(a) == 5


# ============================================================ the picker
def test_track_my_competitors_offers_the_names_with_all(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    none = say(client, ha, inv, "track my competitors")
    assert "not tracking any competitor yet" in none["answer"]
    for n in range(1, 4):
        _add(a, n)
    ask = say(client, ha, inv, "Track my competitors")
    assert "list has 3 of 5 competitors" in ask["answer"] and ask["choices"]["kind"] == "PICK" and [i["label"] for i in ask["choices"]["items"]] == ["Rival 1", "Rival 2", "Rival 3"] and "1. Rival 1" in ask["answer"] and "3. Rival 3" in ask["answer"] and "ALL" in ask["answer"] and "Reply with a number, a name, or ALL." in ask["answer"]
    two = say(client, ha, inv, "2")
    assert "Rival 2" in two["answer"] and "Rival 1" not in two["answer"], two["answer"]
    ask2 = say(client, ha, inv, "check my competitors")
    everyone = say(client, ha, inv, "ALL")
    assert all(f"Rival {n}" in everyone["answer"] for n in (1, 2, 3)), everyone["answer"]
    name = say(client, ha, inv, "check my competitors")
    by_name = say(client, ha, inv, "Rival 3")
    assert "Rival 3" in by_name["answer"] and "Rival 1" not in by_name["answer"]


# ============================================================ track by name -> the listing's own id
def test_tracking_by_discovered_name_resolves_the_listing_id_and_never_uses_the_name_as_the_sku(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    run, urls = _leads(a, ["CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue", "The Better Home 1000 Stainless Steel Water Bottle 1 Litre", "MILTON Aqua 1000 Steel Bottle"])
    inv = start(client, ha)
    r = say(client, ha, inv, "Track CASPIAN Astra 1L and The Better Home 1L.")
    assert "Tracking CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue" in r["answer"] and "Tracking The Better Home 1000" in r["answer"], r["answer"]
    rows = {c["url"]: c for c in competitor_url_repo.list_active_by_linked_sku(a, SKU)}
    assert set(rows) == {urls[0], urls[1]} and all(c["linked_sku"] == SKU for c in rows.values())  # the leads' own listing links, linked to the SKU
    decisions = {c["candidate_url"]: c["seller_decision"] for c in ci_candidate_repo.list_candidates_for_run(a, run)}
    assert decisions[urls[0]] == decisions[urls[1]] == "APPROVED" and decisions[urls[2]] == "NONE"
    again = say(client, ha, inv, "Track CASPIAN Astra 1L")
    assert "already on your list" in again["answer"] and _active(a) == 2
    none = say(client, ha, inv, "Track Nobody Special Bottle")
    assert "could not find" in none["answer"] and _active(a) == 2


def test_a_name_that_fits_two_leads_is_asked_about_and_a_name_that_does_not_fit_the_list_adds_nothing(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _leads(a, ["Cult 1L Steel Water Bottle Black", "Cult 1L Steel Water Bottle Blue"])
    inv = start(client, ha)
    r = say(client, ha, inv, "Track Cult 1L Steel")
    assert "matches more than one" in r["answer"] and _active(a) == 0, r["answer"]
    for n in range(1, 5):
        _add(a, n)
    r2 = say(client, ha, inv, "Track Cult 1L Steel Water Bottle Black and Cult 1L Steel Water Bottle Blue")
    assert "have 1 free competitor slot of 5" in r2["answer"] and _active(a) == 4


# ============================================================ the product
def test_a_single_product_is_the_product_but_several_or_a_named_stranger_are_asked_about(api, app_user, monkeypatch):
    from backend import config
    from backend.repositories import accounting_cutover_repo

    monkeypatch.setenv("CEO_APPROVAL_ENABLED", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    config.tavily_api_key.cache_clear()
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: datetime(2025, 1, 1, tzinfo=timezone.utc))
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    r = say(client, ha, inv, "Find my competitors")
    assert r["status"] == "PLANNED", r["answer"]
    plan = client.get(f"/api/v1/ceo/investigations/{inv}/plans/{r['plan']['id']}", headers=ha).json()
    assert plan["plan"]["legs"][0]["slots"]["product_id"] == SKU
    stranger = say(client, ha, inv, "Find competitors for my yoga mat")
    assert stranger["status"] == "CLARIFIED" and "could not find" in stranger["answer"].lower(), stranger["answer"]
    _product(a, app_user, sku="SKU-2", title="Yoga Mat 6mm")
    two = say(client, ha, inv, "Find my competitors")
    assert two["status"] == "CLARIFIED" and TITLE in two["answer"] and "Yoga Mat 6mm" in two["answer"], two["answer"]
    config.tavily_api_key.cache_clear()


# ============================================================ a screenshot with no readable price
def test_a_screenshot_without_a_readable_price_asks_for_a_clearer_one_and_is_not_used(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    url_id = competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url="https://www.amazon.in/dp/B0NOPRICE1", added_by=uuid.uuid4(), label="Blurry Rival", linked_sku=SKU)
    inv = start(client, ha)
    vision.queue.append(ExtractionResult(fields=(ExtractedField("availability", "IN_STOCK"), ExtractedField("rating", "4.1"), ExtractedField("title", "Blurry Rival"))))
    att = upload(client, ha, inv, _png(11))
    r = say(client, ha, inv, "this is Blurry Rival's listing", attachment_ids=[att])
    assert "could not read the price" in r["answer"] and "clearer, full-page screenshot" in r["answer"], r["answer"]
    assert "Nothing in it needed your confirmation" not in r["answer"]
    assert competitor_snapshot_repo.latest_usable_snapshot(a, url_id) is None
    assert "listed_price_paise" in [q["field_name"] for q in ci_info_request_repo.list_open(a)]
    ok = say(client, ha, inv, "price is 329, in stock")
    assert "confirmed" in ok["answer"].lower() and competitor_snapshot_repo.latest_usable_snapshot(a, url_id)["listed_price_paise"] == 32900


# ============================================================ top 15, pick up to the free slots
def test_the_top_fifteen_are_shown_the_seller_picks_up_to_their_free_slots_and_must_make_room_first(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _add(a, 1)
    _add(a, 2)
    run, urls = _leads(a, [f"Steel Water Bottle {i} Litre Brand {i}" for i in range(1, 19)])  # 18 leads: only the top 15 are listed
    inv = start(client, ha)
    r = say(client, ha, inv, "show me what you found")
    ans = r["answer"]
    assert "top 15 matches" in ans and "You can track 3 more (of 5)" in ans and "Rival 1" in ans and "stop tracking one first" in ans, ans
    assert "15. " in ans and "16. " not in ans
    # more than the free slots in one request: nothing is added, the seller is told what to do
    r = say(client, ha, inv, "track 1, 2, 3 and 4")
    assert "have 3 free competitor slot" in r["answer"] and _active(a) == 2, r["answer"]
    # a fitting pick is added and appears in the tracked list
    r = say(client, ha, inv, "track 1 and 2")
    assert _active(a) == 4, r["answer"]
    # fill the list, then picking another asks the seller to stop tracking one first
    _add(a, 3)
    r = say(client, ha, inv, "track 3")
    assert "list is full" in r["answer"] and _active(a) == 5, r["answer"]
