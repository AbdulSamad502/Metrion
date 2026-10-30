"""CMO 3.0 M4 against a real Postgres, end to end through the real CEO chat: the listing preview card is built from the seller's saved titles, facts, M3 analysis and their own photo; it is free;
it is tenant-isolated; its cut-offs are labelled illustrative unless a verified, sourced, fresh display rule is configured; and the image route serves only the seller's own pictures."""

from __future__ import annotations

import json
import os
import re
import uuid

import pytest
from sqlalchemy import text

from backend.services import cmo_preview
from tests.integration.test_ceo_cmo_delegation import approve, ask_for_titles, chat, cmo_counts, messages, new_investigation, say  # noqa: F401
from tests.integration.test_ceo_cmo_image_handoff import SECRET, jpeg, photo, read_the_photo  # noqa: F401
from tests.integration.test_cmo_api import AMAZON, FLIPKART, TITLES, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

NAME = "AquaNest 1 Litre Stainless Steel Water Bottle"
SKU = "aquanest-1-litre-stainless-steel-water-bottle"
BANNED = ("price", "rating", "reviews", "sold", "bestseller", "sales")


def seed_titles(env, mps=(AMAZON,), key="m4"):
    for mp in mps:
        r = env.post("title-sets", {"request_key": f"{key}-{mp}", "sku": SKU, "product_name": NAME, "brand": "AquaNest", "marketplaces": [mp],
                                    "attributes": [{"name": "Size", "value": "1 litre"}, {"name": "Material", "value": "stainless steel"}, {"name": "Color", "value": "silver"}]})
        assert r.status_code == 200, r.text


def card_for(env, inv=None):
    return cmo_preview.build_card(env.tenant, env.user_id, inv or uuid.uuid4())


# ---------------------------------------------------------------- the card
def test_the_card_holds_every_option_for_both_screens_with_score_coverage_and_compliance(env):
    seed_titles(env)
    card = card_for(env)
    assert card["kind"] == "PREVIEW" and card["marketplaces"] == [AMAZON] and card["missingMarketplaces"] == [FLIPKART, "MEESHO"] and card["defaultMode"] == "mobile"
    assert "illustrative simulation" in card["notice"] and card["product"]["name"] == NAME and card["product"]["brand"] == "AquaNest"
    [s] = card["sets"]
    assert [o["text"] for o in s["options"]] == TITLES
    for o in s["options"]:
        assert set(o["modes"]) == {"mobile", "desktop"}
        assert o["score"]["status"] in ("ASSESSED", "NOT_ASSESSED") and "assessablePoints" in o["score"]
        assert o["compliance"]["status"] in ("PASS", "FAIL", "NOT_ASSESSED")
        for m in o["modes"].values():
            assert m["limitBasis"] == "ILLUSTRATIVE" and "not an official limit" in m["limitNote"]
            assert (m["visible"] + " " + m["hidden"]).split() == o["text"].split()  # nothing is lost between the shown and the hidden part
    insulated = next(o for o in s["options"] if "Insulated" in o["text"])
    assert insulated["hardFailures"] and insulated["score"]["band"] == "NOT_USABLE"
    assert s["recommendedOptionId"] != insulated["optionId"]


def test_the_card_carries_no_price_rating_review_or_sales_figure(env):
    seed_titles(env)
    blob = json.dumps(card_for(env)).lower()
    for phrase in ("price, rating and reviews are not simulated", "sales prediction"):  # the two honest disclaimers are the only place these words appear
        blob = blob.replace(phrase, "")
    for word in BANNED:
        assert not re.search(rf"{re.escape(word)}", blob), word


def test_it_is_free_no_unit_no_reservation_no_model_call(env):
    seed_titles(env)
    events, calls = len(env.events()), env.provider.calls
    card_for(env)
    assert len(env.events()) == events and env.reservations() == [] and env.provider.calls == calls


def test_asking_again_reuses_the_saved_analysis_and_a_changed_fact_makes_a_new_one(env):
    seed_titles(env)
    first = card_for(env)
    again = card_for(env)
    assert again["sets"][0]["analysisId"] == first["sets"][0]["analysisId"] and env.n("cmo_title_analysis") == 1
    assert env.n("agent_run", "trigger_ref = 'cmo.listing_preview'") == 1
    env.post("title-sets", {"request_key": "m4-new", "sku": SKU, "product_name": NAME, "brand": "AquaNest", "marketplaces": [AMAZON], "attributes": [{"name": "Color", "value": "blue"}]})
    assert card_for(env)["sets"][0]["analysisId"] != first["sets"][0]["analysisId"]


def test_all_three_marketplaces_appear_when_each_has_saved_titles(env):
    seed_titles(env, (AMAZON, FLIPKART, "MEESHO"))
    card = card_for(env)
    assert sorted(card["marketplaces"]) == sorted([AMAZON, FLIPKART, "MEESHO"]) and card["missingMarketplaces"] == []
    assert {s["marketplace"] for s in card["sets"]} == {AMAZON, FLIPKART, "MEESHO"}


def test_no_saved_titles_gives_no_card(env):
    assert card_for(env) is None


def test_another_tenant_never_sees_this_tenants_titles(env):
    seed_titles(env)
    other, _headers = env.other_tenant()
    assert cmo_preview.build_card(other, env.user_id, uuid.uuid4()) is None


def test_a_verified_sourced_fresh_display_rule_makes_the_cut_off_verified_and_nothing_else_does(env):
    seed_titles(env)
    rule = {AMAZON: {"mobile": {"visible_chars": 20, "source_url": "https://example.test/rule", "verified_at": "2026-10-29"}}}
    with env.engine.begin() as conn:
        conn.execute(text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, 'title_display_rules', CAST(:v AS jsonb), '2026-01-01')"), {"t": str(env.tenant), "v": json.dumps(rule)})
    o = card_for(env)["sets"][0]["options"][0]
    assert o["modes"]["mobile"]["limitBasis"] == "VERIFIED" and o["modes"]["mobile"]["limit"] == 20 and o["modes"]["mobile"]["limitSourceUrl"] == "https://example.test/rule"
    assert o["modes"]["desktop"]["limitBasis"] == "ILLUSTRATIVE"  # only the screen the rule states is verified


# ---------------------------------------------------------------- through the real CEO chat
def test_the_seller_asks_in_chat_and_the_visual_card_is_saved_on_the_answer(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    assert approve(c, inv, planned["plan"]).json()["status"] == "DELIVERED"
    before = cmo_counts(c)
    r = say(c, inv, "Show my listing preview")
    assert r["status"] == "DELIVERED" and "illustrative simulation" in r["answer"] and "Nothing is sent again and nothing is used up" in r["answer"]
    msg = [m for m in messages(c, inv) if m["role"] == "CEO" and m["kind"] == "ANSWER" and (m.get("choices") or {}).get("kind") == "PREVIEW"]
    assert len(msg) == 1
    card = msg[0]["choices"]
    assert card["investigationId"] == inv and len(card["sets"][0]["options"]) == len(TITLES) and card["image"] is None and "never generates a product picture" in card["imageNote"]
    after = cmo_counts(c)
    assert after["cmo_events"] == before["cmo_events"] and after["model_calls"] == before["model_calls"] and e.n("cmo_title_analysis") == 1


def test_a_second_ask_in_the_same_conversation_adds_no_second_analysis(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    approve(c, inv, planned["plan"])
    say(c, inv, "Show my listing preview")
    say(c, inv, "show the mobile preview")
    assert e.n("cmo_title_analysis") == 1


def test_with_no_titles_the_ceo_says_so_and_there_is_no_card(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "Show my listing preview")
    assert "no saved titles to preview" in r["answer"]
    assert not any((m.get("choices") or {}).get("kind") == "PREVIEW" for m in messages(c, inv))


def test_asking_to_write_titles_is_not_taken_for_a_preview_request(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "write titles for my steel bottle with a preview")
    assert r["status"] == "CLARIFIED" and r["choices"]["playbook"] == "cmo.generate_title_sets"


def test_the_preview_and_the_title_choice_work_together(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    approve(c, inv, planned["plan"])
    say(c, inv, "Show my listing preview")
    say(c, inv, "use option 2")
    assert say(c, inv, "2")["status"] == "DELIVERED" and e.n("cmo_title_approval") == 1


# ---------------------------------------------------------------- the seller's own photo
def test_the_card_uses_the_photo_the_seller_attached_for_this_product_and_the_image_route_serves_only_that_picture(photo):
    p, c, e = photo, photo.c, photo.c.env
    inv, att, _planned, _body = read_the_photo(p)
    from tests.integration.test_ceo_cmo_image_handoff import confirm_facts

    last, _asked = confirm_facts(p, inv)
    assert approve(c, inv, last["plan"]).json()["status"] == "DELIVERED"
    r = say(c, inv, "Show my listing preview")
    card = [m for m in messages(c, inv) if (m.get("choices") or {}).get("kind") == "PREVIEW"][0]["choices"]
    assert card["image"] == {"attachmentId": att, "filename": "shelf-photo.jpg"} and "Your photo" in card["imageNote"] and r["status"] == "DELIVERED"
    img = c.client.get(f"/api/v1/ceo/investigations/{inv}/attachments/{att}/image", headers=e.headers)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and img.headers["x-content-type-options"] == "nosniff" and img.content.startswith(b"\xff\xd8")
    other, other_headers = e.other_tenant()
    assert c.client.get(f"/api/v1/ceo/investigations/{inv}/attachments/{att}/image", headers=other_headers).status_code == 404  # another tenant: identical to a missing file
    assert c.client.get(f"/api/v1/ceo/investigations/{inv}/attachments/{att}/image").status_code in (401, 403)
    assert c.client.get(f"/api/v1/ceo/investigations/{inv}/attachments/{uuid.uuid4()}/image", headers=e.headers).status_code == 404


@pytest.fixture
def attachments_on(monkeypatch):
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_BYTES", "1000000")
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_FILES", "5")
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_PAGES", "5")


def test_another_picture_in_the_conversation_is_never_taken_for_the_product_photo(chat, attachments_on):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    approve(c, inv, planned["plan"])
    shot = c.client.post(f"/api/v1/ceo/investigations/{inv}/attachments", files={"file": ("competitor-screenshot.jpg", jpeg(exif=True), "image/jpeg")}, headers=e.headers)
    assert shot.status_code == 201, shot.text
    say(c, inv, "Show my listing preview")
    card = [m for m in messages(c, inv) if (m.get("choices") or {}).get("kind") == "PREVIEW"][0]["choices"]
    assert card["image"] is None  # it was never read as the product's photo, so it is not shown as one


def test_the_image_route_refuses_files_that_are_not_pictures(chat, attachments_on):
    c, e = chat, chat.env
    inv = new_investigation(c)
    up = c.client.post(f"/api/v1/ceo/investigations/{inv}/attachments", files={"file": ("notes.csv", b"a,b\n1,2\n", "text/csv")}, headers=e.headers)
    assert up.status_code == 201, up.text
    assert c.client.get(f"/api/v1/ceo/investigations/{inv}/attachments/{up.json()['id']}/image", headers=e.headers).status_code == 404
