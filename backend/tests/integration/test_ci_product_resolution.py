"""Regression: a seller names their own product ("Steel Water Bottle 1L (CI TEST)") and the CEO resolves it, through the real CEO API and a real Postgres.

The three messages are the exact ones from manual testing (2026-10-18). Before the fix the first two were answered "Which product?" because the product pattern could not read a name
containing parentheses, and the third was linked to the product only because it happened to be the tenant's only one."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from backend.repositories import accounting_cutover_repo
from competitor_intelligence.repositories import competitor_url_repo, seller_product_profile_repo
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import api, env, say, start  # noqa: F401

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"
M1 = "What products do I have? I want to research competitors for Steel Water Bottle 1L (CI TEST)."
M2 = "Find competitors for my Steel Water Bottle 1L (CI TEST) on Amazon, Flipkart and Meesho."
M3 = "Track https://www.amazon.in/dp/B0F2Y8WFPP called The Better Home 1L for my Steel Water Bottle 1L (CI TEST)."


def _product(tenant, app_user, sku=SKU, title=TITLE):
    seller_product_profile_repo.upsert_profile(tenant, sku, category="Water Bottles", attributes=[{"key": "title", "value": title}], keywords=None, price_paise=39900, fulfillment_type=None, updated_by=app_user)


@pytest.fixture
def approval_on(monkeypatch):
    monkeypatch.setenv("CEO_APPROVAL_ENABLED", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    from backend import config

    config.tavily_api_key.cache_clear()
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc) - timedelta(days=1))
    yield
    config.tavily_api_key.cache_clear()


def _plan_slots(client, headers, inv, r):
    assert r["status"] == "PLANNED", r["answer"]
    plan = client.get(f"/api/v1/ceo/investigations/{inv}/plans/{r['plan']['id']}", headers=headers).json()
    leg = plan["plan"]["legs"][0]
    return leg["action_key"], leg["slots"]


@pytest.mark.parametrize("message", [M1, M2])
def test_discovery_resolves_the_exact_product_name_and_ends_in_an_approval_card(api, app_user, approval_on, message):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    r = say(client, ha, inv, message)
    assert "Which product" not in r["answer"] and "Which of your products" not in r["answer"], r["answer"]
    key, slots = _plan_slots(client, ha, inv, r)
    assert key == "ci.discover_competitors" and slots.get("product_id") == SKU  # the intended seller product, by its id


def test_tracking_links_the_competitor_to_the_named_product_with_the_full_label(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    r = say(client, ha, inv, M3)
    assert "Tracking amazon.in/dp/B0F2Y8WFPP" in r["answer"]
    rows = competitor_url_repo.list_active_by_linked_sku(a, SKU)
    assert len(rows) == 1 and rows[0]["linked_sku"] == SKU and rows[0]["label"] == "The Better Home 1L"
    assert competitor_url_repo.list_active_by_linked_sku(b, SKU) == []


def test_tracking_never_silently_picks_a_product(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    # a product the seller named that is not theirs is NOT swapped for their only product
    r = say(client, ha, inv, "track https://www.amazon.in/dp/B0F2Y8WFPP for my yoga mat")
    assert "Nothing has been added yet" in r["answer"] and "yoga mat" in r["answer"] and TITLE in r["answer"]
    assert competitor_url_repo.list_active_by_linked_sku(a, SKU) == []
    # with two products and none named, it asks and lists both
    _product(a, app_user, sku="SKU-2", title="Yoga Mat 6mm")
    r2 = say(client, ha, inv, "track https://www.amazon.in/dp/B0F2Y8WFPP")
    assert "Nothing has been added yet" in r2["answer"] and TITLE in r2["answer"] and "Yoga Mat 6mm" in r2["answer"]
    assert competitor_url_repo.list_active_by_linked_sku(a, SKU) == [] and competitor_url_repo.list_active_by_linked_sku(a, "SKU-2") == []
    # naming it exactly works
    r3 = say(client, ha, inv, "track https://www.amazon.in/dp/B0F2Y8WFPP for my Yoga Mat 6mm")
    assert "Tracking" in r3["answer"] and len(competitor_url_repo.list_active_by_linked_sku(a, "SKU-2")) == 1


def test_a_missing_product_is_asked_for_by_listing_the_sellers_own_products(api, app_user, approval_on):
    client, ha, hb, a, b = api
    _product(a, app_user)
    seller_product_profile_repo.upsert_profile(a, "SKU-2", category=None, attributes=[{"key": "title", "value": "Yoga Mat 6mm"}], keywords=None, price_paise=None, fulfillment_type=None, updated_by=app_user)
    inv = start(client, ha)
    r = say(client, ha, inv, "find competitors for my products")  # with two products the seller is asked, listing both; with exactly one it would simply be that one
    assert r["status"] == "CLARIFIED" and TITLE in r["answer"] and "Yoga Mat 6mm" in r["answer"], r["answer"]


def test_a_tenant_with_no_products_is_told_so_and_nothing_is_added_or_searched(api, approval_on):
    client, ha, hb, a, b = api
    inv = start(client, ha)
    t = say(client, ha, inv, M3)
    assert "do not have any of your products" in t["answer"] and "Nothing has been added yet" in t["answer"]
    assert competitor_url_repo.list_active_by_linked_sku(a, SKU) == []
    for m in (M1, M2):
        d = say(client, ha, inv, m)
        assert d["status"] == "CLARIFIED" and "do not have any of your products" in d["answer"], d["answer"]
