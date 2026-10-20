"""P1 of the CI completion plan: compare with all competitors (CI, engine-computed, no finance), the seller-price-relative percentage with labelled denominators, a safe answer for a
competitor request nothing recognises, and unbranded discovery leads ranked by what is visible with identity left UNCONFIRMED."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.tenant_context import tenant_scope
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import ci_candidate_repo, ci_discovery_run_repo, competitor_url_repo, seller_product_profile_repo
from competitor_intelligence.types import Marketplace
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import _png, api, env, say, start, upload, vision, workspace  # noqa: F401
from tests.integration.test_ci_end_to_end_flow import LEADS, _last_ceo, flow  # noqa: F401

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"


def _product(tenant, app_user, price=39900):
    seller_product_profile_repo.upsert_profile(tenant, SKU, category="Water Bottles", attributes=[{"key": "title", "value": TITLE}], keywords=None, price_paise=price, fulfillment_type=None, updated_by=app_user)


def _verified(client, ha, a, inv, vision, label, url, price_rupees):
    competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url=url, added_by=uuid.uuid4(), label=label, linked_sku=SKU)
    vision.queue.append(ExtractionResult(fields=(ExtractedField("listed_price_paise", price_rupees * 100), ExtractedField("availability", "IN_STOCK"), ExtractedField("title", label))))
    att = upload(client, ha, inv, _png(len(label)))  # a different image for each competitor (the same image twice is a duplicate)
    say(client, ha, inv, f"this is {label}", attachment_ids=[att])
    say(client, ha, inv, f"price is {price_rupees}, in stock")


def test_compare_my_price_with_all_competitors_is_ci_engine_work_with_both_percentages_labelled(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)  # the seller's own profile price is ₹399
    inv = start(client, ha)
    _verified(client, ha, a, inv, vision, "CASPIAN Astra", "https://www.amazon.in/dp/B0CASPIAN1", 329)
    _verified(client, ha, a, inv, vision, "The Better Home", "https://www.amazon.in/dp/B0BETTERH1", 279)
    competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url="https://www.amazon.in/dp/B0NOPRICE9", added_by=uuid.uuid4(), label="Milton Aqua", linked_sku=SKU)  # no verified price
    r = say(client, ha, inv, "Compare my bottle price with all my competitors and give me the insights.")
    ans = r["answer"]
    assert "Your price for Steel Water Bottle 1L (CI TEST) is ₹399.00" in ans and "2 competitors that have a verified price" in ans, ans
    assert "CASPIAN Astra: ₹329.00, which is ₹70.00 below your price (17.54% of your price, 21.28% of theirs)" in ans, ans  # the owner's ₹70 example, both denominators named
    assert "The Better Home: ₹279.00, which is ₹120.00 below your price (30.08% of your price, 43.01% of theirs)" in ans
    assert "Cheapest: The Better Home" in ans and "2 of 2 are cheaper than you" in ans and "Milton Aqua" in ans and "say nothing about profit" in ans
    with tenant_scope(a) as conn:  # CI's own engine route, never finance
        routes = [r_[0] for r_ in conn.execute(text("SELECT route_key FROM investigation_turn WHERE route_key IS NOT NULL"))]
    assert "ci.request_price_scenario" in routes and not any(k.startswith("cfo.") or k == "COMPETITOR_PRICE_IMPACT" for k in routes)
    typed = say(client, ha, inv, "My price is ₹350. Compare it with all my competitors.")
    assert "Your price for Steel Water Bottle 1L (CI TEST) is ₹350.00" in typed["answer"] and "₹21.00 below your price" in typed["answer"]  # a price the seller states wins over the profile


def test_compare_with_all_asks_for_what_is_missing_and_never_guesses(api, app_user, vision):
    client, ha, hb, a, b = api
    inv = start(client, ha)
    none = say(client, ha, inv, "Compare my price with all my competitors")
    assert "do not have any of your products" in none["answer"]
    _product(a, app_user, price=None)
    no_price = say(client, ha, inv, "Compare my price with all my competitors")
    assert "I need your selling price" in no_price["answer"] and "never guess" in no_price["answer"]
    no_comp = say(client, ha, inv, "Compare my price at ₹399 with all my competitors")
    assert "no competitors on your list" in no_comp["answer"]
    competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url="https://www.amazon.in/dp/B0NOPRICE9", added_by=uuid.uuid4(), label="Milton Aqua", linked_sku=SKU)
    unverified = say(client, ha, inv, "Compare my price at ₹399 with all my competitors")
    assert "None of your competitors has a verified price yet" in unverified["answer"] and "Milton Aqua" in unverified["answer"]


def test_a_competitor_request_nothing_recognises_gets_the_menu_not_a_guess(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url="https://www.amazon.in/dp/B0CASPIAN1", added_by=uuid.uuid4(), label="CASPIAN Astra", linked_sku=SKU)
    inv = start(client, ha)
    r = say(client, ha, inv, "What is the situation with my competitor landscape these days?")
    assert "I am not sure which of these you want" in r["answer"] and "Show my tracked competitors" in r["answer"] and "CASPIAN Astra" in r["answer"], r["answer"]
    assert "(1 of" not in r["answer"]


def test_unbranded_leads_are_ranked_by_what_is_visible_while_identity_stays_unconfirmed(api, app_user, flow):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    r = say(client, ha, inv, "Find my competitors")
    assert r["status"] == "PLANNED", r["answer"]
    plan = r["plan"]
    assert client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/approve", json={"plan_hash": plan["planHash"]}, headers=ha).status_code == 200
    run = ci_discovery_run_repo.latest_for_tenant(a)["id"]
    rows = ci_candidate_repo.list_candidates_for_run(a, run)
    assert len(rows) == len(LEADS)
    with tenant_scope(a) as conn:
        scored = conn.execute(text("SELECT count(*) FROM ci_candidate_relevance")).scalar_one()
    assert scored == len(LEADS)  # every lead was scored from what is visible
    assert {c["identity_match"] for c in rows} == {"UNCERTAIN"}  # never promoted to a match
    assert {c["relationship_class"] for c in rows} == {"UNKNOWN"}
    with tenant_scope(a) as conn:
        bands = [tuple(r_) for r_ in conn.execute(text("SELECT band, total_score FROM ci_candidate_relevance ORDER BY total_score DESC"))]
    assert any(c["tier"] == "RECOMMENDED" for c in rows), (bands, [c["tier"] for c in rows])  # the relevant ones are surfaced first
    shown = _last_ceo(client, ha, inv)
    assert "I cannot tell if it is the same product as yours: your product has no brand recorded" in shown
    assert "verified" not in shown.split("search leads")[-1].split("1.")[-1].lower() or "not verified" in shown
