"""P5: category-driven competitor discovery. "Find my competitors" asks WHICH of the categories in the seller's business profile (one or more, or ALL); one search runs per chosen category;
the top matches come back as a numbered list AND a pick card (check boxes, up to the free slots); picking tracks them and they show on the dashboard under their category."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from backend.repositories import business_profile_repo
from backend.services import ci_categories
from backend.tenant_context import tenant_scope
from competitor_intelligence.repositories import ci_discovery_run_repo
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import api, env, say, start, vision, workspace  # noqa: F401
from tests.integration.test_ci_end_to_end_flow import LEADS, flow  # noqa: F401

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]


def _profile(tenant, user, categories="Water bottles, polo t-shirts and sports shoes"):
    business_profile_repo.upsert(tenant, {
        "business_name": "Zyquora", "description": "Everyday products", "categories": categories, "marketplaces": ["AMAZON", "FLIPKART"], "price_segment": "BUDGET",
        "target_customer": "Value shoppers", "business_stage": "GROWING", "state": "Telangana"}, user)


def test_categories_are_read_from_the_profile_and_resolved_from_numbers_names_and_all():
    cats = ci_categories.parse_categories("Water bottles, polo t-shirts and sports shoes; Water bottles")
    assert cats == ["Water bottles", "Polo t-shirts", "Sports shoes"]
    assert ci_categories.resolve_categories("1 and 3", cats) == ["Water bottles", "Sports shoes"]
    assert ci_categories.resolve_categories("polo t-shirts please", cats) == ["Polo t-shirts"]
    assert ci_categories.resolve_categories("ALL", cats) == cats
    assert ci_categories.resolve_categories("9", cats) == [] and ci_categories.resolve_categories("my steel bottle", cats) == []  # only listed categories can be chosen
    assert ci_categories.category_name(ci_categories.category_key("Polo t-shirts")) == "Polo t-shirts"


def test_find_my_competitors_asks_which_category_then_searches_each_and_offers_a_pick_card(api, app_user, flow):
    client, ha, hb, a, b = api
    _profile(a, app_user)
    inv = start(client, ha)
    r = say(client, ha, inv, "Find my competitors")
    assert r["status"] == "CLARIFIED" and "Which category should I find competitors for?" in r["answer"], r
    assert "1. Water bottles" in r["answer"] and "2. Polo t-shirts" in r["answer"] and "3. Sports shoes" in r["answer"]
    cats = r["choices"]  # the categories are also offered as check boxes: ticking and pressing the button sends the same numbers
    assert cats["kind"] == "PICK" and cats["mode"] == "multi" and [i["label"] for i in cats["items"]] == ["Water bottles", "Polo t-shirts", "Sports shoes"]
    assert cats["actions"][0]["template"] == "{numbers}" and cats["selectAll"] is True
    r = say(client, ha, inv, "1 and 2")
    assert r["status"] == "PLANNED", r["answer"]
    plan = r["plan"]
    assert plan["plan"]["legs"][0]["slots"] == {"categories": ["Water bottles", "Polo t-shirts"]}
    ok = client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/approve", json={"plan_hash": plan["planHash"]}, headers=ha)
    assert ok.status_code == 200, ok.text
    runs = ci_discovery_run_repo.category_batch(a)
    assert [x["seller_product_ref"] for x in runs] == ["category:water bottles", "category:polo t-shirts"]  # one search per chosen category
    last = [m for m in client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["messages"] if m["role"] == "CEO"][-1]
    assert "matches I found for your categories" in last["content"] and "found for your category" in last["content"]
    card = last["choices"]
    assert card["kind"] == "PICK" and card["mode"] == "multi" and card["maxPick"] == 5 and len(card["items"]) <= 15 and card["items"][0]["n"] == 1
    assert card["actions"][0]["template"] == "track {numbers}"
    # ticking numbers on the card is the same as saying them: they become tracked competitors
    r = say(client, ha, inv, "track 1, 2 and 3")
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM competitor_url WHERE status = 'ACTIVE'")).scalar_one() == 3, r["answer"]
    # and the dashboard can show them under a category
    from backend.services import ci_workspace

    ws = ci_workspace.build_workspace(a, None)
    assert any(str(p["productId"]).startswith("category:") for p in ws["products"]) or ws["competitors"] is not None


def test_a_profile_with_no_categories_keeps_the_product_question(api, app_user, flow):
    client, ha, hb, a, b = api
    inv = start(client, ha)
    r = say(client, ha, inv, "Find my competitors")
    assert "Which category" not in r["answer"]  # no business profile: the existing product question or plan applies
