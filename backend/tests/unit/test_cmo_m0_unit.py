"""CMO 3.0 M0 (docs/CMO-3.0/CMO_IMPLEMENTATION_MAP.md): the chat steps that were missing around Slim CMO. Pure code with the database reads replaced by fakes:

* product identity: one name -> one stable sku, saved facts are found again, a loosely named product resolves only when exactly one saved product fits;
* choosing a title in chat: a click / number / the seller's own words are a choice; "yes" and a question are not; two marketplaces ask which one first;
* the approved title grounds the copy; a typed different title stays a seller-supplied title;
* a confirmed photo hint becomes an input for recording; an unconfirmed one does not;
* yes/no property questions are answered from the seller's own facts, else "not confirmed" (never a guess);
* "copied" / "marked used" is never "published";
* routing: "use option 2" is a title choice, "write 5 titles" still writes, and "show my selected title" reads history.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.ceo import business_state, classifier, cmo_chat, evidence, intent_router, question_types
from backend.ceo import input_session as ins
from backend.ceo.plans import ACTIONS, PLAYBOOKS

TENANT = uuid.uuid4()
CTX = ins.Ctx(TENANT, datetime(2026, 10, 30, tzinfo=timezone.utc).date(), None)
AT = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)


def _set(mp, *texts):
    return {"generationId": str(uuid.uuid4()), "marketplace": mp, "sku": "aquanest", "createdAt": AT,
            "options": [{"id": str(uuid.uuid4()), "rank": i, "text": t} for i, t in enumerate(texts, start=1)]}


AMAZON = _set("AMAZON", "AquaNest 1 Litre Stainless Steel Water Bottle, Silver", "AquaNest 1L Steel Bottle, Reusable", "AquaNest Reusable Steel Bottle 1 Litre", "AquaNest Silver Steel Bottle",
              "AquaNest Steel Bottle for Drinking Water")
FLIPKART = _set("FLIPKART", "AquaNest Stainless Steel Bottle 1 Litre Silver")


@pytest.fixture
def fake_db(monkeypatch):
    state = {"sets": [AMAZON], "facts": [], "names": [("aquanest-1-litre-stainless-steel-water-bottle", "AquaNest 1 Litre Stainless Steel Water Bottle")], "approved": []}
    monkeypatch.setattr(cmo_chat.cmo_chat_repo, "recent_title_sets", lambda t, **k: list(state["sets"]))
    monkeypatch.setattr(cmo_chat.cmo_chat_repo, "saved_facts", lambda t, sku: list(state["facts"]))
    monkeypatch.setattr(cmo_chat.cmo_chat_repo, "product_names", lambda t: list(state["names"]))
    monkeypatch.setattr(cmo_chat.cmo_chat_repo, "approved_titles", lambda t, **k: list(state["approved"]))
    return state


# ------------------------------------------------------------------------------------------------ product identity (M0.1)
def test_the_same_product_name_always_gives_the_same_sku():
    assert cmo_chat.product_sku("AquaNest 1 Litre Stainless Steel Water Bottle") == cmo_chat.product_sku("  aquanest 1 litre  STAINLESS steel water bottle ")
    assert cmo_chat.product_sku("AquaNest 1 Litre Stainless Steel Water Bottle") == "aquanest-1-litre-stainless-steel-water-bottle"


def test_different_products_do_not_share_a_sku_and_a_useless_name_has_none():
    assert cmo_chat.product_sku("AquaNest 500 ml bottle") != cmo_chat.product_sku("AquaNest 750 ml bottle")
    assert cmo_chat.product_sku("!") is None and cmo_chat.product_sku(None) is None and cmo_chat.product_sku("") is None
    assert len(cmo_chat.product_sku("x" * 500)) <= cmo_chat.SKU_MAX


def test_a_finished_cmo_session_carries_the_product_identity_into_its_inputs():
    done = ins.Done("cmo.generate_description", ins._to_inputs("cmo.generate_description", {"product_name": "steel bottle", "marketplace": "AMAZON", "seller_title": "Steel Bottle 1L"}))
    assert done.inputs["sku"] == "steel-bottle"
    trends = ins._to_inputs("cmo.market_trends", {"niche": "steel bottles", "news_kind": "NICHE", "marketplaces": ["AMAZON"]})
    assert "sku" not in trends  # market research is not about one product


def test_saved_facts_come_back_as_answers_with_the_newest_statement_winning(fake_db):
    fake_db["facts"] = [
        {"type": "BRAND", "name": None, "value": "AquaNest", "at": AT},
        {"type": "ATTRIBUTE", "name": "Size", "value": "1 litre", "at": AT},
        {"type": "ATTRIBUTE", "name": "Size", "value": "1.5 litre", "at": AT},
        {"type": "ATTRIBUTE", "name": "product_name", "value": "AquaNest 1 Litre Stainless Steel Water Bottle", "at": AT},
        {"type": "ATTRIBUTE", "name": "Key Features", "value": "reusable", "at": AT},
        {"type": "CATEGORY", "name": None, "value": "drinkware", "at": AT},
        {"type": "FREE_TEXT", "name": None, "value": "a note", "at": AT},
    ]
    answers, canonical = cmo_chat.saved_answers(TENANT, "AquaNest 1 Litre Stainless Steel Water Bottle")
    assert answers == {"fact_brand": "AquaNest", "fact_size": "1.5 litre", "fact_key_features": "reusable", "category_hint": "drinkware"}
    assert canonical == "AquaNest 1 Litre Stainless Steel Water Bottle"


def test_a_loosely_named_product_resolves_only_when_exactly_one_saved_product_fits(fake_db):
    assert cmo_chat.resolve_product(TENANT, "AquaNest bottle")[1].startswith("AquaNest 1 Litre")
    fake_db["names"].append(("aquanest-glass-bottle", "AquaNest Glass Bottle"))
    assert cmo_chat.resolve_product(TENANT, "AquaNest bottle") is None  # two fit: the seller is asked, nothing is guessed
    assert cmo_chat.resolve_product(TENANT, "AquaNest glass bottle")[0] == "aquanest-glass-bottle"
    assert cmo_chat.resolve_product(TENANT, "a kettle") is None


def test_nothing_is_carried_for_an_unknown_product(fake_db):
    assert cmo_chat.saved_answers(TENANT, "brand new kettle") == ({}, None)
    assert cmo_chat.saved_answers_note("x", {}) is None
    assert "brand" in cmo_chat.saved_answers_note("AquaNest bottle", {"fact_brand": "AquaNest"})


# ------------------------------------------------------------------------------------------------ choosing a title (M0.2)
@pytest.mark.parametrize("text,expected", [("2", 2), ("option 3", 3), ("use title 4", 4), ("I like option one", 1), ("number five", 5), ("#2", 2), ("the third", None), ("7", None), ("0", None), ("yes", None)])
def test_pick_index(text, expected):
    assert cmo_chat.pick_index(text, 5) == expected


def test_the_seller_can_pick_an_option_or_type_their_own_title_but_yes_and_questions_are_not_titles():
    opts = AMAZON["options"]
    assert cmo_chat.parse_choice("2", opts) == ("OPTION", opts[1])
    kind, text = cmo_chat.parse_choice("AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use", opts)
    assert kind == "EDIT" and text.startswith("AquaNest 1 Litre")
    for not_a_title in ("yes", "ok", "approve", "which one is best?", "go on", "hmm"):
        assert cmo_chat.parse_choice(not_a_title, opts) is None


def _run_pick(fake_db, *answers, sets=None):
    fake_db["sets"] = [AMAZON] if sets is None else sets
    out = ins.start("cmo.approve_title", CTX)
    for a in answers:
        assert isinstance(out, ins.Ask), out
        out = ins.advance(out.card, option_key=None, text=a, ctx=CTX)
    return out


def test_choosing_an_option_ends_with_the_option_id_and_no_text(fake_db):
    first = ins.start("cmo.approve_title", CTX)
    assert isinstance(first, ins.Ask) and first.card["slot"] == "title_pick"
    assert all(f"{o['rank']}. {o['text']}" in first.text for o in AMAZON["options"])  # the seller sees all five, numbered, as saved
    done = ins.advance(first.card, option_key=None, text="2", ctx=CTX)
    assert isinstance(done, ins.Done) and done.playbook == "cmo.approve_title"
    assert done.inputs == {"generation_id": AMAZON["generationId"], "option_id": AMAZON["options"][1]["id"]}


def test_a_typed_title_is_the_sellers_own_wording(fake_db):
    done = _run_pick(fake_db, "AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use")
    assert isinstance(done, ins.Done)
    assert done.inputs == {"generation_id": AMAZON["generationId"], "edited_text": "AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use"}


def test_yes_does_not_choose_a_title(fake_db):
    again = _run_pick(fake_db, "yes")
    assert isinstance(again, ins.Ask) and again.card["slot"] == "title_pick" and "Say the number" in again.text


def test_two_marketplaces_ask_which_one_first(fake_db):
    first = _run_pick(fake_db, sets=[AMAZON, FLIPKART])
    assert isinstance(first, ins.Ask) and first.card["slot"] == "title_marketplace"
    second = ins.advance(first.card, option_key=None, text="Flipkart", ctx=CTX)
    assert isinstance(second, ins.Ask) and second.card["slot"] == "title_pick" and "Flipkart" in second.text and "Stainless Steel Bottle 1 Litre Silver" in second.text
    done = ins.advance(second.card, option_key=None, text="1", ctx=CTX)
    assert done.inputs["generation_id"] == FLIPKART["generationId"]


def test_no_title_options_means_nothing_to_choose_and_nothing_runs(fake_db):
    blocked = _run_pick(fake_db, sets=[])
    assert isinstance(blocked, ins.Blocked) and "no title options" in blocked.text.lower()


def test_the_title_pick_is_a_free_text_field_so_typing_a_title_is_never_dropped_as_a_new_request():
    assert "title_pick" in ins._FREE_TEXT_FIELDS


# ------------------------------------------------------------------------------------------------ the approved title grounds the copy
def test_a_title_equal_to_the_approved_one_is_grounded_on_the_approval(fake_db):
    fake_db["approved"] = [{"approvalId": "8f1c0000-0000-0000-0000-000000000001", "text": "AquaNest 1L Steel Bottle, Reusable", "approvedAt": AT, "marketplace": "AMAZON", "copied": 0, "markedUsed": 0,
                            "editedBySeller": False, "sku": "x", "label": "x", "generationId": "g"}]
    assert cmo_chat.matching_approval(TENANT, "AquaNest bottle", "AMAZON", " aquanest 1L  steel bottle, reusable ") == "8f1c0000-0000-0000-0000-000000000001"
    assert cmo_chat.matching_approval(TENANT, "AquaNest bottle", "AMAZON", "A different title the seller typed") is None
    assert cmo_chat.matching_approval(TENANT, "AquaNest bottle", None, "x") is None


def test_the_title_question_offers_the_approved_title_first(fake_db):
    fake_db["approved"] = [{"approvalId": "a", "text": "AquaNest 1L Steel Bottle, Reusable", "approvedAt": AT, "marketplace": "AMAZON", "copied": 0, "markedUsed": 0, "editedBySeller": False,
                            "sku": "x", "label": "x", "generationId": "g"}]
    opts = ins._seller_title_options(CTX, {"product_name": "AquaNest bottle", "marketplace": "AMAZON"})
    assert opts[0].text == "AquaNest 1L Steel Bottle, Reusable" and "approved" in opts[0].label


# ------------------------------------------------------------------------------------------------ a confirmed photo hint (M0.3)
def test_a_photo_hint_the_seller_confirmed_is_listed_for_recording_and_one_they_skipped_is_not():
    c = {"product_name": "steel bottle", "marketplace": "AMAZON", "seller_title": "Steel Bottle", "_obs": {"color": "silver", "material": "steel"}, "_attachment": {"id": "a", "sha256": "s", "analysis_id": "an-1"},
         "fact_color": "silver", "fact_material": None}
    out = ins._to_inputs("cmo.generate_description", c)
    assert out["image_hints"] == [{"attribute": "color", "value": "silver"}] and out["hint_analysis_id"] == "an-1"
    assert {"image_hints", "hint_analysis_id"} <= ins.CEO_ONLY_INPUTS  # never part of the CMO action's own slots
    assert out["attributes"] == [{"name": "Color", "value": "silver"}]


def test_nothing_is_recorded_without_a_reading_a_product_and_a_confirmation():
    class C:
        tenant_id, app_user_id = TENANT, uuid.uuid4()

    assert cmo_chat.record_image_hints(C, {}) == []
    assert cmo_chat.record_image_hints(C, {"image_hints": [{"attribute": "color", "value": "silver"}]}) == []  # no reading id


# ------------------------------------------------------------------------------------------------ catalog Q&A (M0.4)
def test_the_catalog_session_asks_for_details_and_ends_with_the_closed_attribute_names():
    first = ins.start("cmo.catalog_answer", CTX, prefill={"product": "AquaNest bottle"})
    assert isinstance(first, ins.Ask)
    ask = first
    for _ in range(6):
        if ask.card["slot"] == "catalog_questions":
            break
        ask = ins.advance(ask.card, option_key=None, text="skip", ctx=CTX)
    assert ask.card["slot"] == "catalog_questions"
    bad = ins.advance(ask.card, option_key=None, text="banana", ctx=CTX)
    assert isinstance(bad, ins.Ask) and bad.card["slot"] == "catalog_questions"
    assert ins._catalog_questions("colour and material", CTX, {}) == "COLOR,MATERIAL"
    assert ins._catalog_questions("all", CTX, {}) == ",".join(ins.CATALOG_ALL)
    out = ins._to_inputs("cmo.catalog_answer", {"product_name": "steel bottle", "catalog_questions": "COLOR,SIZE"})
    assert out["questions"] == ["COLOR", "SIZE"] and "catalog_questions" not in out and out["sku"] == "steel-bottle"


def test_catalog_lines_always_say_how_sure_each_answer_is():
    assert evidence._catalog_item({"attribute": "COLOR", "value": "silver", "basis": "SELLER_PROVIDED"}) == "Color: silver (you told me)"
    unknown = evidence._catalog_item({"attribute": "WEIGHT", "value": None, "basis": "UNKNOWN", "requiresSellerInput": True})
    assert "not known yet" in unknown and "Tell me this" in unknown and "0" not in unknown
    assert "estimate" in evidence._catalog_item({"attribute": "SIZE", "value": "1 litre", "basis": "ESTIMATED"})


# ------------------------------------------------------------------------------------------------ property questions (M0.4 / Scene 4)
def test_a_property_the_seller_never_confirmed_is_not_confirmed(fake_db):
    fake_db["facts"] = [{"type": "ATTRIBUTE", "name": "Material", "value": "stainless steel", "at": AT}]
    reply = cmo_chat.property_reply(TENANT, "bottle", "dishwasher safe")
    assert "has not been confirmed" in reply and "AquaNest 1 Litre" in reply and "will not state it" in reply


def test_a_property_the_seller_did_confirm_is_reported_as_their_own_statement(fake_db):
    fake_db["facts"] = [{"type": "ATTRIBUTE", "name": "Care", "value": "dishwasher safe, top rack, tested", "at": AT}]
    reply = cmo_chat.property_reply(TENANT, "bottle", "dishwasher safe")
    assert "you told me" in reply and "top rack" in reply and "not checked" in reply


def test_an_unclear_or_unknown_product_is_asked_about_not_guessed(fake_db):
    fake_db["names"].append(("aquanest-glass-bottle", "AquaNest Glass Bottle"))
    assert "Which product" in cmo_chat.property_reply(TENANT, "bottle", "insulated")
    fake_db["names"].clear()
    assert "no saved product details" in cmo_chat.property_reply(TENANT, "bottle", "insulated")


@pytest.mark.parametrize("q,prop", [("Is my bottle dishwasher safe?", "dishwasher safe"), ("is the AquaNest bottle leakproof", "leakproof"), ("Is it insulated?", "insulated")])
def test_property_questions_are_recognised(q, prop):
    assert cmo_chat.property_question(q)[1] == prop


@pytest.mark.parametrize("q", ["write titles for my bottle", "is my profit up this month?", "how do I make it insulated", "what is insulated"])
def test_other_messages_are_not_property_questions(q):
    assert cmo_chat.property_question(q) is None


def test_copying_or_marking_used_is_never_publication():
    class C:
        tenant_id = TENANT

    r = cmo_chat.direct_reply(C, "If I copy a title or mark it used, does that mean it was published on Amazon?")
    assert r.startswith("No.") and "does not prove" in r and "never publishes" in r
    assert cmo_chat.direct_reply(C, "I copied my title") is None


# ------------------------------------------------------------------------------------------------ history (M0.5)
def test_chosen_titles_are_listed_with_what_was_recorded_and_never_called_published(fake_db):
    fake_db["approved"] = [{"approvalId": "a", "text": "AquaNest 1L Steel Bottle, Reusable", "approvedAt": AT, "marketplace": "AMAZON", "copied": 3, "markedUsed": 1, "editedBySeller": True,
                            "sku": "x", "label": "AquaNest bottle", "generationId": "g"}]
    title, items, note = cmo_chat.approved_history_artefact(TENANT)
    assert title == "Titles you chose" and "copied 3 times, marked used 1 time" in items[0] and "worded by you" in items[0] and "2026-10-29" in items[0]
    assert "published" in note and "does not prove" in note


def test_no_chosen_titles_means_no_history_block(fake_db):
    assert cmo_chat.approved_history_artefact(TENANT) is None


def test_the_content_read_puts_the_chosen_titles_first(fake_db, monkeypatch):
    fake_db["approved"] = [{"approvalId": "a", "text": "AquaNest 1L Steel Bottle, Reusable", "approvedAt": AT, "marketplace": "AMAZON", "copied": 0, "markedUsed": 0, "editedBySeller": False,
                            "sku": "x", "label": "x", "generationId": "g"}]
    monkeypatch.setattr(business_state.ceo_reads, "recent_cmo_content", lambda t, limit: [{"output_type": "DESCRIPTION", "sku": "x", "marketplace": "AMAZON", "created_at": AT, "items": ["text"]}])

    class Ctx:
        tenant_id = TENANT

    read = business_state._load_cmo_content_latest(Ctx, AT)
    assert read.artefacts[0][0] == "Titles you chose" and read.artefacts[1][0].startswith("Written by Slim CMO")


# ------------------------------------------------------------------------------------------------ routing
def _decide(text):
    cat = classifier.build_catalog(list(ACTIONS), list(PLAYBOOKS), question_types.descriptions())
    return intent_router.route(text, cat)


@pytest.mark.parametrize("text", ["use option 2", "I like title 3", "I choose option one", "approve option 4 please", "let's go with number 2", "approve this title"])
def test_choosing_a_title_is_routed_to_the_title_choice(text):
    d = _decide(text)
    assert d is not None and d.key == "cmo.approve_title", (text, d)


@pytest.mark.parametrize("text", ["write 5 titles for my bottle on amazon", "give me title options for steel bottle", "write titles, I want 3 options", "generate a title"])
def test_asking_for_titles_still_writes_titles(text):
    d = _decide(text)
    assert d is not None and d.key == "cmo.generate_title_sets", (text, d)


@pytest.mark.parametrize("text", ["Show my previously selected Amazon title and description", "which title did I choose?", "what title did I approve", "show my approved titles"])
def test_asking_for_what_was_chosen_reads_the_saved_history(text):
    d = _decide(text)
    assert d is not None and (d.route, d.key) == ("BUSINESS_STATE", "QT_LISTING_CONTENT"), (text, d)
