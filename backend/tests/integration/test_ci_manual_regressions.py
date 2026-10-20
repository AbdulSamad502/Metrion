"""Regressions from the owner's manual test of 2026-10-18 (a 58-message conversation), through the real CEO API and a real Postgres.

Each test is a thing a seller said that the CEO got wrong: an open question swallowing every later message; "yes, confirm the price, keep the rest unknown" confirming the rest;
"show my tracked competitors", "what would a buyer pay", "compare at my price", "start tracking X again", "explain this finding" and "I have a newer screenshot" being sent to a small
model that guessed. Vision is scripted (no model); everything else is the shipped code."""

from __future__ import annotations

import os

import pytest

from backend.ceo import input_session
from backend.repositories import investigation_repo as repo
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import competitor_snapshot_repo, competitor_url_repo, seller_product_profile_repo
from competitor_intelligence.types import Marketplace
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import api, env, say, start, upload, vision, workspace, _png  # noqa: F401

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"
LINK = "https://www.amazon.in/dp/B0F2Y8WFPP"


def _product(tenant, app_user):
    seller_product_profile_repo.upsert_profile(tenant, SKU, category="Water Bottles", attributes=[{"key": "title", "value": TITLE}], keywords=None, price_paise=39900, fulfillment_type=None, updated_by=app_user)


def _track(tenant, label="The Better Home 1L", url=LINK):
    return competitor_url_repo.create_url(tenant, marketplace=Marketplace.AMAZON, url=url, added_by=__import__("uuid").uuid4(), label=label, linked_sku=SKU)


def _listing(price=51900, discount=4800):
    return ExtractionResult(fields=(
        ExtractedField("listed_price_paise", price), ExtractedField("availability", "IN_STOCK"), ExtractedField("rating", "4.0"), ExtractedField("title", "The Better Home"),
        ExtractedField("visible_discount_paise", discount), ExtractedField("delivery_charge_paise", 0),
        ExtractedField("offers", [{"kind": "BANK_OFFER", "amount_paise": 150000, "condition_text": "Valid on SBI Debit Card"}]),
    ))


# ---- an open question never swallows the seller's next request ---------------------------------------------------------------------------------------------
def test_an_open_numeric_question_does_not_swallow_a_new_request(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _track(a)
    inv = start(client, ha)
    ctx = input_session.Ctx(a, __import__("datetime").date(2026, 10, 18), 5)
    card = input_session._card("dr.cogs_per_unit", input_session.DR_COGS[1], ctx, {"sku": SKU})
    repo.append_message(a, inv, role="CEO", kind="CLARIFICATION", content="What does one unit cost you, in rupees?", choices=card)
    # a real answer is still an answer
    ok = say(client, ha, inv, "250")
    assert "Is that right" in ok["answer"] or "confirm" in ok["answer"].lower() or "250" in ok["answer"], ok["answer"]
    # a new open question again, then a sentence that is plainly a new request
    repo.append_message(a, inv, role="CEO", kind="CLARIFICATION", content="What does one unit cost you, in rupees?", choices=card)
    r = say(client, ha, inv, "Show all competitors tracked for my Steel Water Bottle 1L (CI TEST).")
    assert "could not read that as an amount" not in r["answer"], r["answer"]
    assert "You have 1 competitor on your list" in r["answer"] and "The Better Home 1L" in r["answer"], r["answer"]


def test_the_session_questions_mention_how_to_leave(api, app_user):
    ctx = input_session.Ctx(__import__("uuid").uuid4(), __import__("datetime").date(2026, 10, 18), 5)
    card = input_session._card("dr.cogs_per_unit", input_session.DR_COGS[1], ctx, {"sku": SKU})
    out = input_session.advance(card, option_key=None, text="abc", ctx=ctx)
    assert "cancel" in out.text.lower()
    assert input_session.is_unrelated_to_open_question(card, "What is the total amount a customer would pay for The Better Home 1L, including delivery?", ctx)
    assert not input_session.is_unrelated_to_open_question(card, "499", ctx) and not input_session.is_unrelated_to_open_question(card, "cancel", ctx)
    assert not input_session.is_unrelated_to_open_question(card, "no idea", ctx)  # short: still an answer attempt


# ---- confirming the price and leaving other fields unknown does exactly that --------------------------------------------------------------------------------
def test_confirm_the_price_and_keep_the_rest_unknown(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    url_id = _track(a)
    inv = start(client, ha)
    vision.queue.append(_listing())
    att = upload(client, ha, inv, _png(1))
    first = say(client, ha, inv, "This is a screenshot of The Better Home 1L competitor listing. Read the price, delivery charge, stock status and offers.", attachment_ids=[att])
    assert "until you confirm them" in first["answer"] and "₹519.00" in first["answer"]
    assert competitor_snapshot_repo.latest_usable_snapshot(a, url_id) is None
    r = say(client, ha, inv, "Yes, confirm the competitor price as ₹279. Keep delivery charges, offers and stock status as unknown unless they are clearly visible.")
    # the discount was not mentioned, so it is still open and the CEO asks: a "yes" is not a blanket confirmation of what the seller did not address
    assert "still not using the discount" in r["answer"], r["answer"]
    assert competitor_snapshot_repo.latest_usable_snapshot(a, url_id) is None
    r2 = say(client, ha, inv, "no discount")
    assert "confirmed" in r2["answer"].lower() and "I am not using" in r2["answer"] and "delivery charge" in r2["answer"] and "stay unknown" in r2["answer"], r2["answer"]
    snap = competitor_snapshot_repo.latest_usable_snapshot(a, url_id)
    assert snap["listed_price_paise"] == 27900 and snap["availability"] is None  # the price the seller confirmed; the stock status they left out is unknown, not what the model read
    comp = workspace(client, ha, SKU)["competitors"][0]
    ep = comp["effectivePrice"]
    assert comp["priceStatus"] == "VERIFIED" and comp["listedPricePaise"] == 27900
    assert ep["effective"]["valuePaise"] == 27900  # no discount, no conditional offer subtracted
    assert not ep["buyerTotal"]["isAvailable"] and ep["buyerTotal"]["unavailableReason"] == "DELIVERY_CHARGE_NOT_OBSERVED"  # delivery was left out: unknown, never assumed free


# ---- questions CI answers itself, from the same stored results as the Competitors page ------------------------------------------------------------------------
def test_show_tracked_competitors_matches_the_page(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    empty = say(client, ha, inv, "Show all competitors tracked for my Steel Water Bottle 1L (CI TEST).")
    assert "no competitors on your list" in empty["answer"], empty["answer"]
    _track(a)
    _track(a, label="Milton Aqua", url="https://www.amazon.in/dp/B079R9W1B6")
    r = say(client, ha, inv, "Show all competitors tracked for my Steel Water Bottle 1L (CI TEST).")
    assert "2 competitors on your list" in r["answer"] and "The Better Home 1L" in r["answer"] and "Milton Aqua" in r["answer"] and "no verified price yet" in r["answer"]
    other = say(client, hb, start(client, hb), "show my tracked competitors")
    assert "The Better Home 1L" not in other["answer"]


def test_what_a_buyer_pays_comes_from_the_stored_engine_result(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _track(a)
    inv = start(client, ha)
    q = "What is the total amount a customer would pay for The Better Home 1L, including delivery and confirmed discounts?"
    nope = say(client, ha, inv, q)
    assert "cannot say what a buyer pays" in nope["answer"], nope["answer"]
    vision.queue.append(_listing(price=27900, discount=0))
    att = upload(client, ha, inv, _png(2))
    say(client, ha, inv, "this is The Better Home 1L", attachment_ids=[att])
    say(client, ha, inv, "price is 279, discount 0, delivery is 40, in stock")
    say(client, ha, inv, "yes")
    r = say(client, ha, inv, q)
    ws = workspace(client, ha, SKU)["competitors"][0]["effectivePrice"]
    assert "Listed price: ₹279.00" in r["answer"] and f"With delivery: ₹{ws['buyerTotal']['valuePaise'] / 100:,.2f}" in r["answer"], r["answer"]
    assert "not counted" in r["answer"] and "I do not know what it costs today" in r["answer"]


def test_compare_my_price_with_a_competitor_is_the_price_comparison_not_a_form(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _track(a)
    inv = start(client, ha)
    r = say(client, ha, inv, "Compare my Steel Water Bottle 1L (CI TEST) at ₹399 with The Better Home 1L. How much cheaper is the competitor?")
    turn = repo.get_turn(a, r["turnId"]) if "turnId" in r else None
    assert "(1 of" not in r["answer"] and "Which competitor changed" not in r["answer"], r["answer"]
    if turn is not None:
        assert turn["route_key"] == "ci.request_price_scenario"


def test_start_tracking_again_restores_a_stopped_competitor_by_name(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    url_id = _track(a)
    inv = start(client, ha)
    competitor_url_repo.soft_remove(a, url_id, removed_by=__import__("uuid").uuid4(), reason="test")
    assert competitor_url_repo.list_active_by_linked_sku(a, SKU) == []
    r = say(client, ha, inv, "Start tracking The Better Home 1L again for my Steel Water Bottle 1L (CI TEST).")
    assert "tracked before" in r["answer"] or "Tracking" in r["answer"], r["answer"]
    assert len(competitor_url_repo.list_active_by_linked_sku(a, SKU)) == 1
    unknown = say(client, ha, inv, "Start tracking Nobody Special again.")
    assert "could not find" in unknown["answer"] and "tracked before" in unknown["answer"]


def test_a_newer_screenshot_that_is_not_attached_is_said_plainly(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _track(a)
    inv = start(client, ha)
    r = say(client, ha, inv, "I have a newer screenshot of The Better Home 1L. Compare it with the previous screenshot and tell me the price change.")
    assert "I do not see a screenshot attached" in r["answer"] and "paperclip" in r["answer"], r["answer"]


def test_explain_this_finding_without_an_id_uses_the_newest_or_says_there_is_none(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _track(a)
    inv = start(client, ha)
    none = say(client, ha, inv, "Explain this competitor finding, including the exact price change and which screenshots support it.")
    assert "no competitor findings to explain yet" in none["answer"], none["answer"]
    for price, png in ((27900, 3), (24900, 4)):
        vision.queue.append(_listing(price=price, discount=0))
        att = upload(client, ha, inv, _png(png))
        say(client, ha, inv, "this is The Better Home 1L, a new capture", attachment_ids=[att])
        say(client, ha, inv, f"price is {price // 100}, discount 0, delivery is 40, in stock")
        say(client, ha, inv, "yes")
    r = say(client, ha, inv, "Explain this competitor finding, including the exact price change and which screenshots support it.")
    assert "₹279.00 to ₹249.00" in r["answer"] and "rests on" in r["answer"], r["answer"]


# ---- a competitor the seller names with "Competitor name: ..." is found by that name when its screenshot arrives (manual test, 22:24) ----------------------------
M9 = "Track this Amazon competitor for my Steel Water Bottle 1L (CI TEST). Competitor name: CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue. Listing URL: https://amzn.in/d/0dqJhf5C"
M11 = ("I am uploading a screenshot of my tracked competitor CASPIAN Astra Stainless Steel Water Bottle 1L. Extract the listed price, discount, delivery, stock, rating, offers and product variant. "
       "Ask me to confirm before saving verified values.")


def test_a_competitor_named_with_competitor_name_colon_is_recognised_for_its_screenshot(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _track(a)  # another competitor, so the screenshot's competitor must be told apart by name
    inv = start(client, ha)
    r = say(client, ha, inv, M9)
    assert "Tracking amzn.in/d/0dqJhf5C" in r["answer"]
    rows = {c["label"]: c for c in competitor_url_repo.list_active_by_linked_sku(a, SKU)}
    assert "CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue" in rows
    vision.queue.append(_listing(price=79900, discount=0))
    att = upload(client, ha, inv, _png(5))
    shot = say(client, ha, inv, M11, attachment_ids=[att])
    assert "I read your screenshot of CASPIAN Astra" in shot["answer"] and "until you confirm them" in shot["answer"], shot["answer"]


def test_sending_the_link_again_with_a_name_names_an_unnamed_competitor_and_never_renames_a_named_one(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    say(client, ha, inv, "track https://amzn.in/d/0dqJhf5C for my Steel Water Bottle 1L (CI TEST)")
    row = competitor_url_repo.list_active_by_linked_sku(a, SKU)[0]
    assert not row["label"]
    r = say(client, ha, inv, "track https://amzn.in/d/0dqJhf5C called CASPIAN Astra for my Steel Water Bottle 1L (CI TEST)")
    assert "already tracked; I have named it “CASPIAN Astra”" in r["answer"], r["answer"]
    r2 = say(client, ha, inv, "track https://amzn.in/d/0dqJhf5C called Something Else for my Steel Water Bottle 1L (CI TEST)")
    assert "named it" not in r2["answer"] and competitor_url_repo.list_active_by_linked_sku(a, SKU)[0]["label"] == "CASPIAN Astra"
