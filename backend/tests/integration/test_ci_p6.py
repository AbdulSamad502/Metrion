"""P6: the CEO reads the conversation. "This competitor", "it" and "that screenshot" mean the competitor just discussed (no "which product / SKU?"), a screenshot of an unknown competitor
is answered with a pick card (or "none of these"), tracked competitors are a card with actions, "cancel" really cancels an open question, and a long new request is never swallowed by one."""

from __future__ import annotations

import os
import uuid

import pytest

from competitor_intelligence.discovery.lead_quality import is_junk
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import competitor_url_repo, seller_product_profile_repo
from competitor_intelligence.types import Marketplace
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import _png, api, env, say, start, upload, vision, workspace  # noqa: F401
from tests.integration.test_ci_p2 import _with_limits

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"


def _product(tenant, app_user):
    seller_product_profile_repo.upsert_profile(tenant, SKU, category="Water Bottles", attributes=[{"key": "title", "value": "Steel Water Bottle 1L (CI TEST)"}], keywords=None, price_paise=39900,
                                               fulfillment_type=None, updated_by=app_user)


def _category_competitor(tenant, n, label):
    """A competitor tracked from a category search: not linked to any of the seller's products."""
    return competitor_url_repo.create_url(tenant, marketplace=Marketplace.AMAZON, url=f"https://www.amazon.in/dp/B0FOCUS{n:04d}", added_by=uuid.uuid4(), label=label, linked_sku="category:shoes")


def _confirm(client, ha, inv, vision, label, price):
    vision.queue.append(ExtractionResult(fields=(ExtractedField("listed_price_paise", price * 100), ExtractedField("availability", "IN_STOCK"), ExtractedField("delivery_charge_paise", 0), ExtractedField("title", label))))
    att = upload(client, ha, inv, _png(len(label) + price))
    say(client, ha, inv, f"this is {label}", attachment_ids=[att])
    say(client, ha, inv, f"price is {price}, in stock, free delivery")


def test_this_competitor_means_the_one_just_discussed_and_needs_no_product(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _category_competitor(a, 1, "Budget Men's Shoes Size-6")
    _category_competitor(a, 2, "Rival Two Sports Shoes")
    inv = start(client, ha)
    _confirm(client, ha, inv, vision, "Budget Men's Shoes Size-6", 949)
    r = say(client, ha, inv, "What is the total price a buyer pays for this competitor, including delivery?")
    assert "Budget Men's Shoes Size-6" in r["answer"] and "₹949.00" in r["answer"] and "Which product" not in r["answer"] and "SKU" not in r["answer"], r["answer"]
    r = say(client, ha, inv, "Show the verified price, delivery charge, stock status and evidence date for this competitor.")
    assert "Verified price: ₹949.00" in r["answer"] and "Delivery: free delivery" in r["answer"] and "Stock: in stock" in r["answer"] and "Rival Two" not in r["answer"], r["answer"]
    r = say(client, ha, inv, "I am talking about this one, Budget Men's Shoes Size-6.")
    assert "Which product" not in r["answer"]


def test_a_screenshot_of_an_unknown_competitor_gets_a_pick_card_and_none_of_these_stores_nothing(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _category_competitor(a, 1, "Budget Men's Shoes Size-6")
    _category_competitor(a, 2, "Rival Two Sports Shoes")
    inv = start(client, ha)
    vision.queue.append(ExtractionResult(fields=(ExtractedField("listed_price_paise", 59900), ExtractedField("availability", "IN_STOCK"))))
    att = upload(client, ha, inv, _png(77))
    r = say(client, ha, inv, "Here is a screenshot of a competitor listing", attachment_ids=[att])
    card = r["choices"]
    assert card["kind"] == "PICK" and card["mode"] == "single" and {i["label"] for i in card["items"]} == {"Budget Men's Shoes Size-6", "Rival Two Sports Shoes"}
    assert any(x["id"] == "none" and x.get("noPick") for x in card["actions"]) and "link" not in r["answer"].lower()
    r = say(client, ha, inv, card["actions"][1]["template"])  # "None of these"
    assert "does not show any of your tracked competitors" in r["answer"] and "find my competitors" in r["answer"]
    assert vision.queue  # the screenshot was never read: nothing was stored


def test_tracked_competitors_are_a_card_with_actions_and_verify_says_what_to_attach(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _category_competitor(a, 1, "Budget Men's Shoes Size-6")
    _category_competitor(a, 2, "Rival Two Sports Shoes")
    inv = start(client, ha)
    r = say(client, ha, inv, "Track my competitors")
    card = r["choices"]
    assert card["kind"] == "PICK" and [x["id"] for x in card["actions"]] == ["details", "verify", "stop"] and all(x.get("exactly") == 1 for x in card["actions"] if x["id"] != "details")
    r = say(client, ha, inv, "verify Rival Two Sports Shoes")
    assert "attach a screenshot of its listing" in r["answer"] and "this is Rival Two Sports Shoes" in r["answer"]
    r = say(client, ha, inv, "details for Budget Men's Shoes Size-6 and Rival Two Sports Shoes")
    assert "Budget Men's Shoes Size-6" in r["answer"] and "Rival Two Sports Shoes" in r["answer"]


def test_cancel_closes_an_open_question_and_a_long_new_request_is_not_swallowed_by_it(api, app_user):
    client, ha, hb, a, b = api
    _with_limits()
    _product(a, app_user)
    _category_competitor(a, 1, "Budget Men's Shoes Size-6")
    inv = start(client, ha)
    r = say(client, ha, inv, "Should I reduce my bottle price from ₹399 to ₹349 to compete with my competitor?")
    assert r["status"] == "CLARIFIED"
    r = say(client, ha, inv, "Show my tracked competitors and their verified prices, please, I do not want a profit calculation now.")
    assert "Budget Men's Shoes Size-6" in r["answer"], r["answer"]  # a long new request is answered, not taken as an answer to the open finance question
    r = say(client, ha, inv, "Should I reduce my bottle price from ₹399 to ₹349 to compete with my competitor?")
    r = say(client, ha, inv, "cancel this calculation")
    assert "stopped" in r["answer"].lower() and "nothing was run" in r["answer"].lower()


def test_junk_leads_are_recognised():
    assert is_junk("These Cheap Ass Shoes eBook") and not is_junk("Reebok Men Stride Runner Running Shoes")
