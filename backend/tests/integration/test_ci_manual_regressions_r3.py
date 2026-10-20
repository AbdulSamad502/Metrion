"""Regressions from the owner's 94-message manual test (2026-10-18, 22:30-22:43), through the real CEO API and a real Postgres. Vision is scripted; everything else is the shipped code.

What the owner typed that the CEO got wrong: a "track this competitor" message with no link was read as candidate numbers; a confirmation that addressed every field was only half
accepted (a "39%" and a "1L" were read as amounts); a question mentioning "1L" could have changed a pending price; a competitor named in a shorter way than it was stored was not found;
"is it an exact match", "who confirmed it" and "show my tracked X" went to a small model that guessed; a threshold written with the percent first was dropped."""

from __future__ import annotations

import os

import pytest

from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import ci_info_request_repo, competitor_snapshot_repo, competitor_url_repo, seller_product_profile_repo
from competitor_intelligence.types import Marketplace
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import _png, api, env, say, start, upload, vision, workspace  # noqa: F401

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"
CASPIAN = "CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue"
CASPIAN_URL = "https://amzn.in/d/0dqJhf5C"
M11 = ("I am uploading a screenshot of my tracked competitor CASPIAN Astra Stainless Steel Water Bottle 1L. Extract the listed price, discount, delivery, stock, rating, offers and product variant. "
       "Ask me to confirm before saving verified values.")
Q_TOTAL = "What is the total unconditional buyer price for CASPIAN Astra 1L, including confirmed delivery charges? Explain which offers are excluded."


def _product(tenant, app_user):
    seller_product_profile_repo.upsert_profile(tenant, SKU, category="Water Bottles", attributes=[{"key": "title", "value": TITLE}], keywords=None, price_paise=39900, fulfillment_type=None, updated_by=app_user)


def _track(tenant, label=CASPIAN, url=CASPIAN_URL):
    return competitor_url_repo.create_url(tenant, marketplace=Marketplace.AMAZON, url=url, added_by=__import__("uuid").uuid4(), label=label, linked_sku=SKU)


def _caspian_listing():
    return ExtractionResult(fields=(
        ExtractedField("listed_price_paise", 32900), ExtractedField("availability", "IN_STOCK"), ExtractedField("rating", "4.3"), ExtractedField("rating_count", 254),
        ExtractedField("title", "CASPIAN Astra"), ExtractedField("visible_discount_paise", 3900), ExtractedField("delivery_charge_paise", 0),
        ExtractedField("offers", [{"kind": "COUPON", "amount_paise": 900, "condition_text": None}, {"kind": "BANK_OFFER", "amount_paise": 300000, "condition_text": "SBI Credit Cards"}]),
    ))


def _read(client, ha, a, inv, vision):
    url_id = _track(a)
    vision.queue.append(_caspian_listing())
    att = upload(client, ha, inv, _png(7))
    shot = say(client, ha, inv, M11, attachment_ids=[att])
    assert "I read your screenshot of CASPIAN" in shot["answer"] and "until you confirm them" in shot["answer"], shot["answer"]
    return url_id


def test_track_this_competitor_without_a_link_asks_for_the_link_and_is_not_candidate_numbers(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    r = say(client, ha, inv, "Track this Amazon competitor for my Steel Water Bottle 1L (CI TEST). Competitor name: CASPIAN Astra Stainless Steel Water Bottle 1L, Royal Blue. Listing URL: [PASTE ACTUAL AMAZON URL].")
    assert "Which ones?" not in r["answer"] and "find my competitors" in r["answer"] and "link" not in r["answer"].lower(), r["answer"]  # no link is asked for; the find-and-tick flow is offered
    assert competitor_url_repo.list_active_by_linked_sku(a, SKU) == []


def test_the_confirmation_the_owner_typed_is_fully_accepted(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    url_id = _read(client, ha, a, inv, vision)
    r = say(client, ha, inv, "Confirm the listed price as ₹329, free delivery and in-stock status. The displayed 39% is a reference-price discount, not an additional discount to subtract from ₹329. "
                             "Do not count cashback or conditional bank offers in the unconditional buyer price.")
    assert "confirmed" in r["answer"].lower() and "still not using" not in r["answer"], r["answer"]
    snap = competitor_snapshot_repo.latest_usable_snapshot(a, url_id)
    assert snap["listed_price_paise"] == 32900 and snap["availability"] == "IN_STOCK"
    ep = workspace(client, ha, SKU)["competitors"][0]["effectivePrice"]
    assert ep["effective"]["valuePaise"] == 32900  # the 39% reference discount is not subtracted
    assert ep["buyerTotal"]["isAvailable"] and ep["buyerTotal"]["valuePaise"] == 32900  # free delivery was confirmed: a real zero


def test_a_question_that_mentions_a_size_never_changes_a_pending_confirmation(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    url_id = _read(client, ha, a, inv, vision)
    open_before = sorted(r["field_name"] for r in ci_info_request_repo.list_open(a))
    q = say(client, ha, inv, Q_TOTAL)
    assert "cannot say what a buyer pays" in q["answer"], q["answer"]  # nothing is confirmed yet, and "1L" was not read as a price
    assert sorted(r["field_name"] for r in ci_info_request_repo.list_open(a)) == open_before
    assert competitor_snapshot_repo.latest_usable_snapshot(a, url_id) is None


def test_a_shorter_name_finds_the_competitor_for_every_kind_of_question(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    _read(client, ha, a, inv, vision)
    say(client, ha, inv, "price is 329, discount 0, free delivery, in stock, do not count the offers")
    r = say(client, ha, inv, Q_TOTAL)
    assert "Listed price: ₹329.00" in r["answer"] and "With delivery: ₹329.00" in r["answer"] and "no offer is counted" in r["answer"], r["answer"]
    one = say(client, ha, inv, "Show my tracked CASPIAN Astra competitor and its verified price instead.")
    assert "1 competitor on your list" in one["answer"] and "verified price ₹329.00" in one["answer"] and "evidence is fresh" in one["answer"], one["answer"]


def test_relationship_and_provenance_are_answered_from_what_is_stored(api, app_user, vision):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    _read(client, ha, a, inv, vision)
    rel = say(client, ha, inv, "Is CASPIAN Astra 1L an exact match, a variant, a direct cross-brand competitor or a functional alternative to my Steel Water Bottle 1L (CI TEST)? Explain the evidence and any missing attributes.")
    assert "I have not classified" in rel["answer"] and "(1 of" not in rel["answer"], rel["answer"]
    q = "Show me the source and confirmation history for CASPIAN Astra 1L's ₹329 price. When was it observed and who confirmed it?"
    before = say(client, ha, inv, q)
    assert "no verified price yet" in before["answer"] and "nobody has confirmed" in before["answer"], before["answer"]
    say(client, ha, inv, "price is 329, discount 0, free delivery, in stock, do not count the offers")
    after = say(client, ha, inv, q)
    assert "comes from a screenshot you sent" in after["answer"] and "you confirmed or corrected" in after["answer"], after["answer"]


def test_stop_and_start_tracking_work_with_the_short_name(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    _track(a)
    inv = start(client, ha)
    say(client, ha, inv, "Stop tracking CASPIAN Astra 1L for my Steel Water Bottle 1L (CI TEST). Preserve its historical evidence.")
    assert competitor_url_repo.list_active_by_linked_sku(a, SKU) == []
    r = say(client, ha, inv, "Start tracking CASPIAN Astra 1L again for my Steel Water Bottle 1L (CI TEST).")
    assert "tracked before" in r["answer"] or "Tracking" in r["answer"], r["answer"]
    assert len(competitor_url_repo.list_active_by_linked_sku(a, SKU)) == 1


def test_a_threshold_written_with_the_percent_first_is_saved_with_the_quiet_hours(api, app_user):
    client, ha, hb, a, b = api
    _product(a, app_user)
    inv = start(client, ha)
    r = say(client, ha, inv, "Set a 5% verified price-change alert threshold for my tracked competitors, with quiet hours from 10 PM to 7 AM Asia/Kolkata.")
    assert "5.00%" in r["answer"] and "22:00 to 07:00" in r["answer"], r["answer"]
