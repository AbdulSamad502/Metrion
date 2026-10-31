"""CMO 3.0 M7 through the real CEO chat (M7-54..M7-60, M7-65, M7-70): the seller asks about their listing history in plain words; the CEO works out the product, marketplace and versions, asks one short
question when that is open and remembers the question, delegates the exact comparison to the CMO, and answers with a listing-history card. Free: no model, no unit, nothing generated or changed. The
older chat flows are unchanged ("show my listing" is still the M6 listing card; unrelated questions are not intercepted). Persisted state (the stored card) is asserted, not just the reply text."""

from __future__ import annotations

import os

import pytest
from tests.integration.test_ceo_cmo_delegation import chat, messages, new_investigation, say  # noqa: F401
from tests.integration.test_cmo_api import FLIPKART, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import ListingProvider, body, ru_env

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

EDIT2 = "Change bullet 2 to: Holds 1 litre of water"
EDIT3 = "Change description to: A reusable stainless steel bottle that holds 1 litre. Easy to carry and easy to clean."


def edit(env, gid, message):
    r = env.client().post(f"/api/v1/cmo/listing/{gid}/edit", json={"message": message}, headers=env.headers)
    assert r.status_code == 200, r.text
    return r.json()["generationId"]


def versions(c, n=3):
    env = c.env
    ru_env(env, ListingProvider())
    ids = [env.post("full-listing", body()).json()["card"]["generationId"]]
    for msg in (EDIT2, EDIT3)[: n - 1]:
        ids.append(edit(env, ids[-1], msg))
    return ids


def footprint(c):
    e = c.env
    return {"gens": e.n("cmo_generation"), "events": e.n("metered_event", "agent_code = 'CMO'"), "usage": e.n("cmo_result_usage_event"), "calls": e.provider.calls}


def ask(c, inv, text):
    say(c, inv, text)
    last = [m for m in messages(c, inv) if m["role"] == "CEO"][-1]
    return last["content"], last.get("choices"), last["kind"]


def card_of(choices, view):
    assert choices and choices["kind"] == "LISTING_HISTORY" and choices["view"] == view, choices
    return choices


# ---------------------------------------------------------------- M7-54 / M7-55: history and the latest version
def test_m7_54_show_my_listing_history_answers_with_the_history_card_and_changes_nothing(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    before = footprint(chat)
    text, choices, kind = ask(chat, inv, "Show my listing history.")
    card = card_of(choices, "HISTORY")
    assert kind == "ANSWER" and [v["id"] for v in card["versions"]] == [v3, v2, v1] and card["investigationId"] == inv
    assert "3 versions" in text and "latest is version 3" in text and "cannot see which version is live" in text
    assert footprint(chat) == before  # free: nothing generated, billed or called


def test_m7_55_show_my_latest_product_listing_opens_the_newest_version_with_its_own_audit(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "Show my latest AquaNest listing")
    card = card_of(choices, "VERSION")
    assert card["version"]["id"] == v3 and card["version"]["number"] == 3 and card["audit"]["verdict"] and "version 3 of 3" in text
    assert "not approved for use" in text and "Nothing is published by Metrion" in text
    _, prev, _ = ask(chat, inv, "Show my previous listing")
    assert card_of(prev, "VERSION")["version"]["id"] == v2
    _, orig, _ = ask(chat, inv, "Show my original listing")
    assert card_of(orig, "VERSION")["version"]["id"] == v1
    _, num, _ = ask(chat, inv, "Show version 2 of my listing")
    assert card_of(num, "VERSION")["version"]["number"] == 2


# ---------------------------------------------------------------- M7-56: comparison
def test_m7_56_compare_version_1_and_3_runs_the_exact_comparison_and_stores_the_card(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    before = footprint(chat)
    text, choices, _ = ask(chat, inv, "Compare version 1 and version 3")
    card = card_of(choices, "COMPARE")
    assert (card["older"]["id"], card["newer"]["id"]) == (v1, v3) and card["sectionsChanged"]["bullets"] and card["performance"]["state"] == "NOT_ASSESSED"
    assert "Version 1 → version 3" in text and "differences in the saved text" in text and "do not show a version performs better" in text
    stored = [m for m in messages(chat, inv) if m["role"] == "CEO" and m["kind"] == "ANSWER"][-1]["choices"]
    assert stored["older"]["number"] == 1 and stored["bullets"]["items"]  # the card is persisted in the conversation
    assert footprint(chat) == before


def test_m7_56_previous_against_latest_and_what_changed_use_the_version_it_came_from(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    _, choices, _ = ask(chat, inv, "Compare my previous AquaNest listing with the latest one")
    assert (card_of(choices, "COMPARE")["older"]["id"], choices["newer"]["id"]) == (v2, v3)
    text, ch2, _ = ask(chat, inv, "What changed in my latest listing?")
    assert (card_of(ch2, "COMPARE")["older"]["id"], ch2["newer"]["id"]) == (v2, v3) and "Changed:" in text and "description" in text


def test_m7_follow_ups_use_the_conversation_context_for_keywords_audit_claims_and_improvements(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    ask(chat, inv, "What changed in my latest listing?")
    t1, c1, _ = ask(chat, inv, "Which keywords were removed?")
    assert card_of(c1, "COMPARE")["focus"] == "KEYWORDS_REMOVED" and ("Removed:" in t1 or "No keyword was removed" in t1)
    t2, c2, _ = ask(chat, inv, "Which keywords did I add?")
    assert c2["focus"] == "KEYWORDS_ADDED" and ("Added:" in t2 or "No keyword was added" in t2)
    t3, c3, _ = ask(chat, inv, "Show me the audit changes")
    assert c3["focus"] == "AUDIT_CHANGES" and "Audit:" in t3
    t4, c4, _ = ask(chat, inv, "What claims were introduced in the latest revision?")
    assert c4["focus"] == "CLAIMS" and "claim" in t4.lower()
    t5, c5, _ = ask(chat, inv, "Why was this listing revised?")
    assert c5["focus"] == "WHY_REVISED" and "not your reason" in t5


def test_m7_60_what_should_i_improve_next_answers_with_suggestions_that_make_no_performance_promise(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    ask(chat, inv, "Show my listing history")
    before = footprint(chat)
    text, choices, _ = ask(chat, inv, "What should I improve next?")
    card = card_of(choices, "RECOMMEND")
    assert card["versionNumber"] == 3 and card["state"] in ("RECOMMENDATIONS", "NOTHING_TO_RECOMMEND", "NO_EVIDENCE")
    if card["state"] == "RECOMMENDATIONS":
        assert "suggestions for you to decide" in text and "say nothing about search volume, ranking, demand or sales" in text
    low = text.lower()
    assert "will increase" not in low and "boost" not in low and "rank higher" not in low
    assert footprint(chat) == before


def test_m7_approved_for_use_is_answered_from_the_recorded_decision_only(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "Which listing version is approved for use?")
    assert "None of your saved versions is approved" in text and "latest version is not assumed" in text and card_of(choices, "HISTORY")["focus"] == "APPROVED"
    assert chat.env.client().post(f"/api/v1/cmo/listing/{v2}/approve", headers=chat.env.headers).status_code == 200
    text, choices, _ = ask(chat, inv, "Which listing version is approved for use?")
    assert "version 2" in text and "version 3" not in text.split("Metrion cannot see")[0] and "Metrion cannot see which version, if any, is live" in text


# ---------------------------------------------------------------- M7-57..59: ambiguity is asked, remembered and answered
def test_m7_59_an_ambiguous_version_gets_one_short_question_and_the_next_message_answers_it(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    text, choices, kind = ask(chat, inv, "Compare my old and new listings")
    card = card_of(choices, "CLARIFY")
    assert kind == "ANSWER" and "Which two" in text and "3 versions" in text and card["ask"]["kind"] == "COMPARE" and card["options"]
    done_text, done, _ = ask(chat, inv, "version 1 and 3")
    assert (card_of(done, "COMPARE")["older"]["id"], done["newer"]["id"]) == (v1, v3) and "Version 1 → version 3" in done_text


def test_m7_59_a_version_that_does_not_exist_is_asked_about_not_guessed(chat):
    versions(chat)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "Compare version 1 and version 9")
    assert card_of(choices, "CLARIFY") and "not saved" in text and "1 to 3" in text
    t2, c2, _ = ask(chat, inv, "Compare version 2")
    assert card_of(c2, "CLARIFY") and "Which version do you want to compare with version 2" in t2


def test_m7_58_an_ambiguous_marketplace_is_asked_and_the_answer_continues_the_request(chat):
    v1, v2, v3 = versions(chat)
    flip = chat.env.post("full-listing", {**body("fk"), "marketplace": FLIPKART}).json()["card"]["generationId"]
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "What changed in my latest listing?")
    assert card_of(choices, "CLARIFY") and "Which marketplace" in text and {o["label"] for o in choices["options"]} == {"Amazon", "Flipkart"}
    done_text, done, _ = ask(chat, inv, "Amazon")
    assert card_of(done, "COMPARE")["marketplace"] == "AMAZON" and done["newer"]["id"] == v3
    assert flip not in str(done)  # the other marketplace never leaks into this answer
    t3, c3, _ = ask(chat, new_investigation(chat), "Show my Flipkart listing changes")
    assert "only one saved version" in t3 or c3 is None


def test_m7_59_a_new_topic_after_my_question_is_not_swallowed_as_the_answer(chat):
    versions(chat)
    inv = new_investigation(chat)
    ask(chat, inv, "Compare my old and new listings")
    for text in ("hello", "what are my Amazon sales for last month?", "show me my profit"):
        _, ch, _ = ask(chat, inv, text)
        assert not (ch and ch.get("kind") == "LISTING_HISTORY" and ch.get("view") in ("COMPARE", "VERSION")), text


def test_m7_57_an_unknown_product_is_asked_about_with_the_products_that_have_listings(chat):
    versions(chat)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "Show my latest Zorblax listing")
    assert card_of(choices, "CLARIFY") and "zorblax" in text.casefold() and "You have listings for" in text and choices["options"]


def test_m7_one_version_and_no_version_are_answered_plainly(chat):
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "Show my listing history")
    assert "do not have a saved listing yet" in text and choices is None
    versions(chat, n=1)
    inv2 = new_investigation(chat)
    t, c, _ = ask(chat, inv2, "Compare my old and new listings")
    assert "only one saved version" in t and c is None
    t2, c2, _ = ask(chat, inv2, "Why was this listing revised?")
    assert "only one version" in t2 and card_of(c2, "VERSION")


# ---------------------------------------------------------------- M7-65 / M7-70: the rest of the CEO is unchanged
def test_m7_70_other_requests_are_not_intercepted_and_the_m6_show_my_listing_is_unchanged(chat):
    v1, v2, v3 = versions(chat)
    inv = new_investigation(chat)
    _, choices, _ = ask(chat, inv, "Show my listing")
    assert choices and choices["kind"] == "LISTING" and choices["generationId"] == v3  # still the M6 card
    for text in ("hello", "what can you do?", "is my steel water bottle dishwasher safe?"):
        _, ch, _ = ask(chat, inv, text)
        assert not (ch and ch.get("kind") == "LISTING_HISTORY"), text
    _, edit_ch, _ = ask(chat, inv, "Change bullet 1 to: Holds 1 litre of water")
    assert edit_ch and edit_ch["kind"] == "LISTING"  # an edit sentence is still an edit


def test_m7_66_another_tenant_asking_sees_no_history(chat):
    versions(chat)
    other, headers = chat.env.other_tenant()
    inv = new_investigation(chat, headers=headers)
    r = chat.client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "Show my listing history"}, headers=headers)
    assert r.status_code == 200, r.text
    answer = r.json()
    ch = answer.get("choices") or {}
    assert not ch.get("versions") and "version 3" not in (answer.get("answer") or "").lower()  # the other seller's history never reaches this conversation
