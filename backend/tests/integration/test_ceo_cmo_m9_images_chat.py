"""CMO 3.0 M9 through the real CEO chat: the seller asks about their product images (analyse, main image, lowest, image N, missing photos, suitability for a marketplace) and gets a structured card. Free: no
model, not even the vision model, no unit, no credit. A photo attached in the chat is never added to a product by itself: only the card's button (the images-page route) adds it. Persisted state is asserted."""

from __future__ import annotations

import os

import pytest

from tests.integration.test_ceo_cmo_delegation import chat, cmo_counts, messages, new_investigation, say  # noqa: F401
from tests.integration.test_ceo_cmo_image_handoff import photo  # noqa: F401
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m5_integration import NAME as M5_NAME, SKU as M5_SKU, card as readiness_card, item, market, seed as m5_seed
from tests.integration.test_cmo_m9_images import AMAZON, FLIPKART, SKU, distinct, good_set, known_product, picture, upload

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def ask(c, inv, text):
    say(c, inv, text)
    last = [m for m in messages(c, inv) if m["role"] == "CEO"][-1]
    return last["content"], last.get("choices"), last["kind"]


def card(choices, view):
    assert choices and choices["kind"] == "IMAGE_QUALITY" and choices["view"] == view, choices
    assert choices["aiCredits"] == 0
    return choices


def footprint(p):
    counts = {k: v for k, v in cmo_counts(p.c).items() if k != "ceo_events"}  # the CEO conversation itself meters its own turns; what must not change is the CMO side
    return {**counts, "vision_calls": p.vision.calls, "analyses": p.c.env.n("product_image_analysis")}


def seeded(p, n=3):
    e = p.c.env
    known_product(e)
    good_set(e, n)
    return new_investigation(p.c)


def test_every_listed_request_gets_a_structured_card_for_the_right_product_at_zero_cost(photo):
    inv = seeded(photo, 4)
    before = footprint(photo)
    cases = [("Analyze my product images.", "REPORT"), ("Check my main product image.", "IMAGE"), ("Which image has the lowest quality?", "IMAGE"), ("What is wrong with image 2?", "IMAGE"),
             ("What additional product photos should I upload?", "MISSING"), ("Are my images suitable for Amazon?", "REPORT"), ("Show my image quality report.", "REPORT")]
    for text, view in cases:
        reply, choices, kind = ask(photo.c, inv, text)
        c = card(choices, view)
        assert kind == "ANSWER" and c["product"]["sku"] == SKU and c["marketplace"] == AMAZON and c["compliance"]["status"] == "NOT_ASSESSED", (text, choices)
        assert c["dimensions"] and c["images"] and c["link"].startswith("/dashboard/cmo/images?sku=") and reply
    assert footprint(photo) == before  # no generation, unit, model call or vision call
    assert photo.c.env.n("cmo_image_review") == 1  # the same set reviewed seven times is one stored review


def test_the_answers_are_specific_to_what_was_asked(photo):
    inv = seeded(photo, 3)
    _, c, _ = ask(photo.c, inv, "Check my main product image.")
    assert c["focus"]["imageNumber"] == 1 and "Main image" in c["focus"]["label"]
    _, c, _ = ask(photo.c, inv, "What is wrong with image 2?")
    assert c["focus"]["imageNumber"] == 2
    text, c, _ = ask(photo.c, inv, "Which image has the lowest quality?")
    assert c["focus"]["isLowest"] is True and "lowest-quality image" in text
    text, c, _ = ask(photo.c, inv, "What additional product photos should I upload?")
    assert {m["shotType"] for m in c["missingShots"]} == {"SIZE", "USAGE"} and "not marketplace requirements" in text
    text, c, _ = ask(photo.c, inv, "Are my images suitable for Amazon?")
    assert "cannot say whether your images meet Amazon" in text and "NOT_ASSESSED" in text and c["compliance"]["checks"] == []


def test_a_poor_main_image_is_reported_with_severity_reason_and_advice(photo):
    e = photo.c.env
    known_product(e)
    upload(e, [("b.png", picture(300, blur=3), "image/png", "PRIMARY", "FRONT")])
    inv = new_investigation(photo.c)
    text, c, _ = ask(photo.c, inv, "Check my main product image.")
    top = card(c, "IMAGE")["findings"][0]
    assert top["severity"] == "HIGH" and top["whyItMatters"] and top["recommendation"] and top["isMarketplaceRequirement"] is False and top["imageLabel"].startswith("Main image 1")
    assert c["scoreState"] == "PARTIAL" and "withheld" in c["scoreText"] and "issue(s)" in text


def test_with_no_images_the_answer_says_so_and_nothing_is_reviewed_or_passed(photo):
    e = photo.c.env
    known_product(e)
    inv = new_investigation(photo.c)
    text, c, _ = ask(photo.c, inv, "Analyze my product images.")
    card(c, "EMPTY")
    assert "no images uploaded" in text or "not uploaded images" in text
    assert e.n("cmo_image_review") == 0 and photo.vision.calls == 0
    inv2 = new_investigation(photo.c)
    text2, c2, _ = ask(photo.c, inv2, "Show my image quality report.")
    assert card(c2, "EMPTY")["message"]


def test_an_unknown_image_number_or_an_ambiguous_product_gets_one_short_question(photo):
    e = photo.c.env
    known_product(e)
    good_set(e, 2)
    inv = new_investigation(photo.c)
    q, c, kind = ask(photo.c, inv, "What is wrong with image 9?")
    assert kind == "ANSWER" and card(c, "CLARIFY")["options"][0]["imageNumber"] == 1 and "Which image number" in q
    ask(photo.c, inv, "image 2")
    # a second product with images: the CEO has to ask which one
    known_product(e, "OTHER-9")
    upload(e, [("o.png", distinct(77), "image/png", "PRIMARY", "FRONT")], sku="OTHER-9")
    inv2 = new_investigation(photo.c)
    q2, c2, _ = ask(photo.c, inv2, "Analyze my product images.")
    clar = card(c2, "CLARIFY")
    assert "Which product" in q2 and {o["sku"] for o in clar["options"]} == {SKU, "OTHER-9"}


def test_a_marketplace_without_images_is_reported_not_guessed(photo):
    inv = seeded(photo, 2)
    text, c, _ = ask(photo.c, inv, "Are my images suitable for Flipkart?")
    card(c, "EMPTY")
    assert c["marketplace"] == FLIPKART and "no images uploaded" in text


def test_competitor_images_and_unrelated_requests_are_not_taken_for_the_sellers_images(photo):
    inv = seeded(photo, 2)
    before = footprint(photo)
    for t in ("What is wrong with my competitor image?", "Show my listing preview", "hello"):
        _, c, _ = ask(photo.c, inv, t)
        assert not (c and c.get("kind") == "IMAGE_QUALITY"), t
    assert photo.c.env.n("cmo_image_review") == 0
    assert footprint(photo)["vision_calls"] == before["vision_calls"]


# ------------------------------------------------------------------------------------------------ a photo attached in the chat
def test_an_attached_photo_is_not_added_until_the_button_is_pressed(photo):
    e = photo.c.env
    known_product(e)
    inv = new_investigation(photo.c)
    att = photo.upload(inv, data=picture(), name="bottle.png", ctype="image/png")
    r = photo.turn(inv, "Add this photo to my product images as the main image", [att])
    last = [m for m in messages(photo.c, inv) if m["role"] == "CEO"][-1]
    c = card(last["choices"], "ATTACH")
    assert c["attachment"]["id"] == att and c["preselect"]["role"] == "PRIMARY" and c["products"][0]["sku"] == SKU and "Typing yes does not add it" in last["content"]
    assert e.n("cmo_product_image") == 0 and e.n("seller_image_asset") == 0 and photo.vision.calls == 0
    ask(photo.c, inv, "yes")
    ask(photo.c, inv, "add it")
    assert e.n("cmo_product_image") == 0 and e.n("seller_image_asset") == 0
    pressed = e.post("product-images/from-chat", {"sku": SKU, "marketplace": AMAZON, "investigationId": inv, "attachmentId": att, "role": "PRIMARY", "shotType": "FRONT"})
    assert pressed.status_code == 200 and pressed.json()["assignmentsWritten"] == 1 and pressed.json()["unitsBilled"] == 0
    assert e.n("cmo_product_image") == 1 and e.n("seller_image_asset") == 1 and photo.vision.calls == 0 and e.n("product_image_analysis") == 0
    again = e.post("product-images/from-chat", {"sku": SKU, "marketplace": AMAZON, "investigationId": inv, "attachmentId": att, "role": "PRIMARY", "shotType": "FRONT"})
    assert again.status_code == 200 and again.json()["assignmentsWritten"] == 0 and e.n("cmo_product_image") == 1
    assert r is not None


def test_another_sellers_attachment_cannot_be_added_through_the_button(photo):
    e = photo.c.env
    known_product(e)
    inv = new_investigation(photo.c)
    att = photo.upload(inv, data=picture(), name="bottle.png", ctype="image/png")
    other, other_headers = e.other_tenant()
    e.post("title-sets", {"request_key": "o1", "sku": SKU, "product_name": "Theirs", "marketplaces": [AMAZON]}, headers=other_headers)
    r = e.post("product-images/from-chat", {"sku": SKU, "marketplace": AMAZON, "investigationId": inv, "attachmentId": att}, headers=other_headers)
    assert r.status_code == 404 and e.n("cmo_product_image", tenant=other) == 0 and e.n("seller_image_asset", tenant=other) == 0


def test_a_competitor_screenshot_attached_in_the_chat_is_never_offered_as_a_product_image(photo):
    e = photo.c.env
    known_product(e)
    inv = new_investigation(photo.c)
    att = photo.upload(inv, data=picture(), name="their.png", ctype="image/png")
    photo.turn(inv, "Add this competitor screenshot to my product images", [att])
    kinds = [(m.get("choices") or {}).get("kind") for m in messages(photo.c, inv) if m["role"] == "CEO"]
    assert "IMAGE_QUALITY" not in kinds and e.n("cmo_product_image") == 0


# ------------------------------------------------------------------------------------------------ readiness shows image quality beside the checklist
def test_readiness_shows_image_quality_separately_and_a_missing_image_is_not_a_pass(photo):
    e = photo.c.env
    m5_seed(e)
    m = market(readiness_card(e), AMAZON)
    assert m["imageQuality"]["state"] == "NOT_ASSESSED" and "not a pass" in m["imageQuality"]["message"] and item(m, "photo_present")["status"] == "MISSING"
    good_set_for = [("front.png", distinct(1), "image/png", "PRIMARY", "FRONT"), ("side.png", distinct(2), "image/png", "SECONDARY", "ANGLE")]
    assert upload(e, good_set_for, sku=M5_SKU).status_code == 200
    m = market(readiness_card(e), AMAZON)
    assert m["imageQuality"]["state"] == "NOT_REVIEWED" and item(m, "photo_present")["status"] == "DONE" and "images page" in item(m, "photo_present")["detail"]
    score_before = m["score"]
    assert e.post("product-images/review", {"sku": M5_SKU, "marketplace": AMAZON}).status_code == 200
    m = market(readiness_card(e), AMAZON)
    assert m["imageQuality"]["separateFromReadiness"] is True and m["imageQuality"]["state"] in ("REVIEWED", "PARTIAL")
    assert m["score"] == score_before and m["verdict"] in ("NOT_READY", "BLOCKED", "DRAFT_READY_NOT_VERIFIED") and m["verdict"] != "READY"
    assert market(readiness_card(e), "FLIPKART")["imageQuality"]["state"] == "NOT_ASSESSED"  # images are per marketplace
