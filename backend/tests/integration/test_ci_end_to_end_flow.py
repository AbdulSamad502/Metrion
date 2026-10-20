"""The owner's acceptance flow, through the real CEO API and a real Postgres, with persistent state checked at every step (not just the wording):

discovery -> approval -> leads shown by what they are -> track one -> screenshot -> partial confirmation -> price comparison -> monitoring -> stop -> restore.

The search provider returns fixed, realistic leads (the live Tavily call was tested separately) and the vision model is scripted; everything else is the shipped code."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.repositories import accounting_cutover_repo, investigation_repo as repo
from backend.services import ci_search
from competitor_intelligence.discovery.mock_search_provider import MockSearchProvider
from competitor_intelligence.discovery.search_provider import SearchResult
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import ci_candidate_repo, ci_search_result_repo, competitor_snapshot_repo, competitor_url_repo, seller_product_profile_repo
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import _png, api, env, say, start, upload, vision, workspace  # noqa: F401
from sqlalchemy import text
from backend.tenant_context import tenant_scope

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"
LEADS = (
    ("https://www.amazon.in/dp/B0AAAAAAA1", "CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue"),
    ("https://www.amazon.in/dp/B0BBBBBBB2", "MILTON Aqua 1000 Stainless Steel Water Bottle, 1 Litre"),
    ("https://www.flipkart.com/cult-1l-stainless-steel-water-bottle/p/itmcult0001?pid=BOTCULT0001", "Cult 1L Stainless Steel Insulated Water Bottle"),
)


def _provider():
    now = datetime.now(timezone.utc)
    results = [SearchResult(rank=i, url=u, title=t, snippet=f"{t} - leakproof, 24h hot and cold", source="MOCK", retrieved_at=now, provider_response_ref=None) for i, (u, t) in enumerate(LEADS, start=1)]
    return ci_search.SelectedProvider(provider=MockSearchProvider(default_results=results), provider_name="MOCK")


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setenv("CEO_APPROVAL_ENABLED", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    from backend import config

    config.tavily_api_key.cache_clear()
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: datetime(2025, 1, 1, tzinfo=timezone.utc))
    from backend.services import ci_actions

    monkeypatch.setattr(ci_actions, "select_search_provider", lambda tenant_id: _provider())
    yield
    config.tavily_api_key.cache_clear()


def _last_ceo(client, h, inv):
    return [m for m in client.get(f"/api/v1/ceo/investigations/{inv}", headers=h).json()["messages"] if m["role"] == "CEO"][-1]["content"]


def _listing():
    return ExtractionResult(fields=(
        ExtractedField("listed_price_paise", 32900), ExtractedField("availability", "IN_STOCK"), ExtractedField("rating", "4.3"), ExtractedField("rating_count", 254),
        ExtractedField("title", "CASPIAN Astra"), ExtractedField("visible_discount_paise", 3900), ExtractedField("delivery_charge_paise", 0),
        ExtractedField("offers", [{"kind": "BANK_OFFER", "amount_paise": 300000, "condition_text": "SBI Credit Cards"}]),
    ))


def test_discovery_to_restore_with_the_state_checked_at_every_step(api, flow, vision, app_user):
    client, ha, hb, a, b = api
    seller_product_profile_repo.upsert_profile(a, SKU, category="Water Bottles", attributes=[{"key": "title", "value": TITLE}], keywords=None, price_paise=39900, fulfillment_type=None, updated_by=app_user)
    inv = start(client, ha)

    # 1. discovery -> a plan card; nothing has run or been stored
    r = say(client, ha, inv, "Find direct competitors for my Steel Water Bottle 1L (CI TEST) across Amazon, Flipkart and Meesho. Show the discovered listings and explain why they match.")
    assert r["status"] == "PLANNED", r["answer"]
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM ci_candidate")).scalar_one() == 0
    plan = r["plan"]

    # 2. approval -> the search runs, and the leads are shown right away by what they are called, with where, why and the link
    ok = client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/approve", json={"plan_hash": plan["planHash"]}, headers=ha)
    assert ok.status_code == 200, ok.text
    shown = _last_ceo(client, ha, inv)
    assert "CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue (Amazon)" in shown and "https://www.amazon.in/dp/B0AAAAAAA1" in shown and "MILTON Aqua" in shown, shown
    assert "not classified yet" not in shown.split("search leads", 1)[-1].split("1.", 1)[-1] or "I cannot tell if it is the same product" in shown  # a reason, not a blank
    assert "returned a partial result" not in shown and "ci.discover_competitors" not in shown
    from competitor_intelligence.repositories import ci_discovery_run_repo

    cands = ci_candidate_repo.list_candidates_for_run(a, ci_discovery_run_repo.latest_for_tenant(a)["id"])
    assert len(cands) == len(LEADS) and {c["candidate_url"] for c in cands} == {u for u, _ in LEADS}
    assert ci_search_result_repo.titles_by_url(a, [LEADS[0][0]])[LEADS[0][0]]["title"] == LEADS[0][1]  # the titles are what the search returned, stored, not invented

    # 3. track lead 1 -> a tracked competitor linked to the seller's SKU (never to its own name)
    t = say(client, ha, inv, "Track CASPIAN Astra 1L")  # by name: the leads are ranked by relevance, so a position is not stable
    assert "Tracking CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue" in t["answer"], t["answer"]
    rows = competitor_url_repo.list_active_by_linked_sku(a, SKU)
    assert len(rows) == 1 and rows[0]["linked_sku"] == SKU

    # 4. screenshot -> read, held; then a PARTIAL confirmation: price confirmed, delivery and offers left unknown
    name = "CASPIAN Astra Stainless Steel Water Bottle 1L"
    vision.queue.append(_listing())
    att = upload(client, ha, inv, _png(9))
    read = say(client, ha, inv, f"I am uploading a screenshot of my tracked competitor {name}. Ask me to confirm before saving verified values.", attachment_ids=[att])
    assert "until you confirm them" in read["answer"] and "already inside the listed price" in read["answer"], read["answer"]
    url_id = rows[0]["id"]
    assert competitor_snapshot_repo.latest_usable_snapshot(a, url_id) is None
    c = say(client, ha, inv, "Confirm the listed price as ₹329, in stock. The displayed 39% is a reference-price discount, not an additional discount. Keep delivery charges and offers as unknown.")
    assert "confirmed" in c["answer"].lower() and "stay unknown" in c["answer"], c["answer"]
    snap = competitor_snapshot_repo.latest_usable_snapshot(a, url_id)
    assert snap["listed_price_paise"] == 32900 and snap["availability"] == "IN_STOCK" and snap["price_confirmation"] == "CONFIRMED"
    ep = workspace(client, ha, SKU)["competitors"][0]["effectivePrice"]
    assert ep["effective"]["valuePaise"] == 32900 and not ep["buyerTotal"]["isAvailable"] and ep["buyerTotal"]["unavailableReason"] == "DELIVERY_CHARGE_NOT_OBSERVED"

    # 5. the buyer price from the SAME stored evidence: unavailable, and it says why (never routed to finance, never assumed free)
    q = say(client, ha, inv, "What is the total unconditional buyer price for CASPIAN Astra 1L, including confirmed delivery charges? Explain which offers are excluded.")
    assert "Listed price: ₹329.00" in q["answer"] and "not available, because the delivery charge is not confirmed" in q["answer"], q["answer"]

    # 6. comparison and monitoring are CI's own routes (not the finance form), and ask for no product again
    cmp_ = say(client, ha, inv, "My Steel Water Bottle 1L (CI TEST) sells at ₹399. Compare it with the verified CASPIAN Astra 1L price. Give the rupee and percentage differences. Do not calculate profit.")
    assert "(1 of" not in cmp_["answer"] and "Which of your tracked competitors" not in cmp_["answer"], cmp_["answer"]
    mon = say(client, ha, inv, "Check my tracked competitors using the evidence already stored. What verified changes, alerts and stale observations should I know about?")
    assert "Which product" not in mon["answer"] and "Which of your products" not in mon["answer"], mon["answer"]
    with tenant_scope(a) as conn:
        routes = [r_[0] for r_ in conn.execute(text("SELECT route_key FROM investigation_turn WHERE route_key IS NOT NULL ORDER BY created_at"))]
    assert "ci.request_price_scenario" in routes and "ci.monitor_competitors" in routes and not any(k and k.startswith("cfo.") or k == "COMPETITOR_PRICE_IMPACT" for k in routes)

    # 7. stop -> history kept; restore -> the same record, no duplicate
    with tenant_scope(a) as conn:
        before = conn.execute(text("SELECT count(*) FROM competitor_snapshot WHERE competitor_url_id = :u"), {"u": str(url_id)}).scalar_one()
    say(client, ha, inv, "Stop tracking CASPIAN Astra 1L for my Steel Water Bottle 1L (CI TEST). Preserve its historical evidence.")
    assert competitor_url_repo.list_active_by_linked_sku(a, SKU) == []
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM competitor_snapshot WHERE competitor_url_id = :u"), {"u": str(url_id)}).scalar_one() == before  # the evidence is kept
    back = say(client, ha, inv, "Start tracking CASPIAN Astra 1L again for my Steel Water Bottle 1L (CI TEST).")
    assert "tracked before" in back["answer"] or "Tracking" in back["answer"], back["answer"]
    again = competitor_url_repo.list_active_by_linked_sku(a, SKU)
    assert len(again) == 1 and again[0]["id"] == url_id
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM competitor_url WHERE url = :u"), {"u": LEADS[0][0]}).scalar_one() == 1  # no duplicate record

    # 8. another seller sees none of it
    assert workspace(client, hb)["competitors"] == [] and workspace(client, hb)["candidates"] == []
