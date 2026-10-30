"""CMO 3.0 M5 against a real Postgres, end to end through the real CEO chat (N-10, N-11, N-12): buyer questions answered only from the seller's confirmed facts, the seller's own answers saved
as their statements, the listing-readiness checklist for all three marketplaces, free, tenant-isolated, and never READY without verified marketplace evidence."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import NullPool

from backend.services import cmo_hints, cmo_readiness
from tests.integration.test_ceo_cmo_delegation import approve, ask_for_titles, chat, cmo_counts, messages, new_investigation, say  # noqa: F401
from tests.integration.test_cmo_api import AMAZON, FLIPKART, PACK, TITLES, _erase_cmo_rows, ctx_engine, env, fake_clerk, seed_analysis  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

NAME = "AquaNest 1 Litre Stainless Steel Water Bottle"
SKU = "aquanest-1-litre-stainless-steel-water-bottle"


class Ctx:  # what the CEO passes: the seller's own authenticated context
    def __init__(self, env):
        from backend.auth.context import AuthContext

        self._c = AuthContext(env.user_id, "t", True, env.tenant, "ACTIVE", "OWNER", {}, "COMPLETE")
        self.tenant_id, self.app_user_id, self.role, self.permissions = env.tenant, env.user_id, "OWNER", {}


def seed(env, mps=(AMAZON,), attrs=None, key="m5"):
    for mp in mps:
        r = env.post("title-sets", {"request_key": f"{key}-{mp}", "sku": SKU, "product_name": NAME, "brand": "AquaNest", "marketplaces": [mp],
                                    "attributes": attrs if attrs is not None else [{"name": "Size", "value": "1 litre"}, {"name": "Material", "value": "stainless steel"}, {"name": "Color", "value": "silver"}]})
        assert r.status_code == 200, r.text


def card(env, view="readiness"):
    return cmo_readiness.build_card(Ctx(env), uuid.uuid4(), SKU, NAME, view)


def market(c, mp):
    return next(m for m in c["readiness"]["marketplaces"] if m["marketplace"] == mp)


def item(m, iid):
    return next(i for cat in m["categories"] for i in cat["items"] if i["id"] == iid)


def q(c, qid):
    return next(x for x in c["questions"]["questions"] if x["id"] == qid)


# ---------------------------------------------------------------- the card
def test_the_card_reuses_the_confirmed_facts_titles_and_marks_what_is_missing_for_each_marketplace(env):
    seed(env)
    c = card(env)
    assert c["kind"] == "READINESS" and [m["marketplace"] for m in c["readiness"]["marketplaces"]] == ["AMAZON", "FLIPKART", "MEESHO"] and c["defaultMarketplace"] == AMAZON
    amazon, flipkart = market(c, AMAZON), market(c, FLIPKART)
    assert item(amazon, "fact_brand")["status"] == "DONE" and item(amazon, "fact_size")["status"] == "DONE" and item(amazon, "fact_category")["status"] == "MISSING"
    assert item(amazon, "title_written")["status"] == "DONE" and item(flipkart, "title_written")["status"] == "MISSING" and "write titles for Flipkart" in item(flipkart, "title_written")["action"]
    assert item(amazon, "content_title")["status"] == "MISSING" and item(amazon, "content_copy")["status"] == "MISSING" and item(amazon, "photo_present")["status"] == "MISSING"
    assert amazon["score"]["status"] == "ASSESSED" and amazon["score"]["assessablePoints"] <= 100 and amazon["score"]["score"] > flipkart["score"]["score"]


def test_with_no_verified_marketplace_rule_the_rule_is_not_assessed_and_the_verdict_is_never_ready(env):
    seed(env)
    for mp in ("AMAZON", "FLIPKART", "MEESHO"):
        m = market(card(env), mp)
        assert item(m, "market_title_rule")["status"] == "NOT_ASSESSED" and item(m, "market_title_rule")["earned"] is None and item(m, "market_attrs")["status"] == "NOT_ASSESSED"
        assert m["verdict"] != "READY"


def test_the_buyer_questions_are_answered_only_from_confirmed_facts(env):
    seed(env)
    c = card(env, "questions")
    assert c["view"] == "questions"
    assert q(c, "material")["status"] == "CONFIRMED" and q(c, "material")["answer"] == "stainless steel" and q(c, "material")["source"]["origin"] == "you told me"
    for qid in ("insulated", "leakproof", "dishwasher", "bpa", "warranty"):
        assert q(c, qid)["status"] == "NOT_CONFIRMED" and q(c, qid)["answer"] is None
    assert "not drawn from search, review or marketplace q&a data" in " ".join(c["questions"]["limits"]).lower()


def test_it_is_free_no_unit_no_reservation_no_model_call_and_the_result_is_saved_once(env):
    seed(env)
    events, calls = len(env.events()), env.provider.calls
    first, again = card(env), card(env)
    assert len(env.events()) == events and env.reservations() == [] and env.provider.calls == calls
    assert first["questionsId"] == again["questionsId"] and first["readinessId"] == again["readinessId"]
    assert env.n("cmo_buyer_question_set") == 1 and env.n("cmo_readiness_assessment") == 1 and env.n("cmo_title_analysis") == 1  # the title analysis is the one the M4 preview shares
    assert env.n("agent_run", "trigger_ref IN ('cmo.buyer_questions', 'cmo.listing_readiness')") == 2


def test_a_new_fact_makes_a_new_saved_assessment_and_the_old_one_is_kept(env):
    seed(env)
    first = card(env)
    cmo_readiness.save_fact(env.tenant, env.user_id, SKU, "Dishwasher safe", "yes, top rack, tested by me")
    second = card(env)
    assert second["questionsId"] != first["questionsId"] and env.n("cmo_buyer_question_set") == 2
    assert q(second, "dishwasher")["status"] == "CONFIRMED" and "top rack" in q(second, "dishwasher")["answer"] and q(first, "dishwasher")["status"] == "NOT_CONFIRMED"


# ---------------------------------------------------------------- the seller's own answers
def test_a_seller_answer_is_saved_as_their_own_statement_append_only_for_zero_units(env):
    seed(env)
    events = len(env.events())
    cmo_readiness.save_fact(env.tenant, env.user_id, SKU, "Warranty", "1 year from AquaNest")
    rows = env.q("SELECT fact_type, attribute_name, fact_value FROM seller_fact WHERE sku = :s AND attribute_name = 'Warranty'", s=SKU)
    assert [tuple(r) for r in rows] == [("ATTRIBUTE", "Warranty", "1 year from AquaNest")] and len(env.events()) == events
    assert env.n("agent_run", "trigger_ref = 'cmo.confirm_fact'") == 1


def test_not_tested_is_a_settled_do_not_claim_and_the_listing_never_claims_it(env):
    seed(env)
    cmo_readiness.save_fact(env.tenant, env.user_id, SKU, "Insulated", "not tested")
    c = card(env, "questions")
    assert q(c, "insulated")["status"] == "SELLER_UNKNOWN" and q(c, "insulated")["answer"] is None and "I will not claim it" in q(c, "insulated")["ask"]
    kw = env.post("keyword-intelligence", {"request_key": "kw-m5", "sku": SKU}).json()
    assert not any("insulated" in k["keyword"] for k in kw["candidates"])


@pytest.mark.parametrize("value,why", [("", "I need your answer"), ("x" * 201, "200 characters"), ("only at a price of 499 rupees, GST included", "cannot put in a listing")])
def test_an_unusable_answer_is_refused_and_nothing_is_saved(env, value, why):
    seed(env)
    before = env.n("seller_fact")
    with pytest.raises(ValueError, match=why):
        cmo_readiness.save_fact(env.tenant, env.user_id, SKU, "Warranty", value)
    assert env.n("seller_fact") == before


# ---------------------------------------------------------------- the other readiness inputs
def test_a_chosen_title_saved_copy_and_a_photo_confirmation_each_turn_their_items_done(env):
    seed(env)
    ts = env.post("title-sets", {"request_key": "m5-pick", "sku": SKU, "product_name": NAME, "marketplaces": [AMAZON]}).json()["artefacts"][0]
    ok = env.post("title-approvals", {"generation_id": ts["id"], "option_id": ts["options"][0]["id"]})
    copy = env.post("listing-copy", {"request_key": "m5-copy", "sku": SKU, "product_name": NAME, "marketplace": AMAZON, "approval_id": ok.json()["approvalId"]})
    assert copy.status_code == 200, copy.text
    analysis = seed_analysis(env.cengine, env.tenant, [{"name": "color", "value": "silver", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}])
    assert cmo_hints.record_confirmed_hints(env.tenant, env.user_id, analysis_id=str(analysis), sku=SKU, hints=[{"attribute": "color", "value": "matte silver"}]) == ["color"]  # a NEW statement (an identical one is a replay)
    m = market(card(env), AMAZON)
    assert item(m, "content_title")["status"] == "DONE" and item(m, "content_copy")["status"] == "DONE" and item(m, "photo_present")["status"] == "DONE"
    assert "quality is not assessed" in item(m, "photo_present")["detail"]


def test_a_title_set_written_for_another_product_is_never_counted(env):
    seed(env)
    env.post("title-sets", {"request_key": "other-p", "sku": "other-product", "product_name": "Garden Hose Reel", "marketplaces": [FLIPKART]})
    assert item(market(card(env), FLIPKART), "title_written")["status"] == "MISSING"


# ---------------------------------------------------------------- tenant isolation and storage
def test_another_tenant_never_sees_this_tenants_answers_titles_or_assessments(env):
    seed(env)
    cmo_readiness.save_fact(env.tenant, env.user_id, SKU, "Warranty", "1 year")
    own = card(env)
    other, _headers = env.other_tenant()

    class Other(Ctx):
        def __init__(self):
            self.tenant_id, self.app_user_id, self.role, self.permissions = other, env.user_id, "OWNER", {}

    theirs = cmo_readiness.build_card(Other(), uuid.uuid4(), SKU, NAME, "readiness")
    assert q(theirs, "warranty")["status"] == "NOT_CONFIRMED" and item(market(theirs, AMAZON), "title_written")["status"] == "MISSING" and item(market(theirs, AMAZON), "fact_brand")["status"] == "MISSING"
    assert theirs["questionsId"] != own["questionsId"] and env.n("cmo_readiness_assessment", tenant=other) == 1


def test_the_application_role_cannot_change_or_delete_a_saved_assessment(env):
    seed(env)
    card(env)
    app = create_engine(os.environ["DATABASE_URL_APP"], poolclass=NullPool)
    try:
        for sql in ("UPDATE cmo_readiness_assessment SET method = 'x'", "DELETE FROM cmo_readiness_assessment", "UPDATE cmo_buyer_question_set SET method = 'x'", "DELETE FROM cmo_buyer_question_set"):
            with pytest.raises(ProgrammingError):
                with app.begin() as conn:
                    conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
                    conn.execute(text(sql))
    finally:
        app.dispose()


# ---------------------------------------------------------------- through the real CEO chat
def test_the_seller_asks_what_buyers_will_ask_and_gets_the_card_with_supported_answers_and_gaps(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    assert approve(c, inv, planned["plan"]).json()["status"] == "DELIVERED"
    before = cmo_counts(c)
    r = say(c, inv, "What questions will buyers ask?")
    assert r["status"] == "DELIVERED" and "questions buyers commonly ask" in r["answer"] and "NOT CONFIRMED" in r["answer"] and "Nothing is used up and nothing is published" in r["answer"]
    cards = [m["choices"] for m in messages(c, inv) if (m.get("choices") or {}).get("kind") == "READINESS"]
    assert len(cards) == 1 and cards[0]["view"] == "questions" and cards[0]["product"]["sku"] == "steel-bottle"
    after = cmo_counts(c)
    assert after["cmo_events"] == before["cmo_events"] and after["model_calls"] == before["model_calls"]


def test_the_seller_answers_a_question_in_chat_and_the_next_answer_uses_it(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    approve(c, inv, planned["plan"])
    saved = say(c, inv, "For my steel bottle, dishwasher safe is: yes, top rack, tested by me")
    assert "Saved: Dishwasher safe: yes, top rack, tested by me" in saved["answer"] and "your own statement" in saved["answer"]
    assert e.n("seller_fact", "sku = 'steel-bottle' AND attribute_name = 'Dishwasher safe'") == 1
    say(c, inv, "What questions will buyers ask about my steel bottle?")
    card = [m["choices"] for m in messages(c, inv) if (m.get("choices") or {}).get("kind") == "READINESS"][-1]
    d = next(x for x in card["questions"]["questions"] if x["id"] == "dishwasher")
    assert d["status"] == "CONFIRMED" and "top rack" in d["answer"]


def test_an_answer_for_an_unknown_question_or_product_saves_nothing(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    approve(c, inv, planned["plan"])
    before = e.n("seller_fact")
    assert "could not tell which saved product" in say(c, inv, "For my garden hose, dishwasher safe is: yes")["answer"]
    assert e.n("seller_fact") == before
    r = say(c, inv, "For my steel bottle, the colour of the moon is: blue")
    assert e.n("seller_fact") == before and "colour of the moon" not in e.q("SELECT string_agg(attribute_name, ',') FROM seller_fact")[0][0].lower()


def test_is_my_bottle_ready_to_list_gives_the_checklist_for_all_three_marketplaces_and_never_ready(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    approve(c, inv, planned["plan"])
    r = say(c, inv, "Is my steel bottle ready to list?")
    assert r["status"] == "DELIVERED" and "listing readiness checklist" in r["answer"] and "assessable points" in r["answer"]
    card = [m["choices"] for m in messages(c, inv) if (m.get("choices") or {}).get("kind") == "READINESS"][0]
    assert card["view"] == "readiness" and [m["marketplace"] for m in card["readiness"]["marketplaces"]] == ["AMAZON", "FLIPKART", "MEESHO"]
    assert all(m["verdict"] != "READY" for m in card["readiness"]["marketplaces"])
    amazon = market(card, "AMAZON")
    assert item(amazon, "title_written")["status"] == "DONE" and item(amazon, "market_title_rule")["status"] == "NOT_ASSESSED"
    assert e.n("cmo_readiness_assessment") == 1


def test_with_no_product_or_several_products_the_ceo_says_so_or_asks_which(chat):
    c, e = chat, chat.env
    inv = new_investigation(c)
    assert "no saved product details" in say(c, inv, "Is my bottle ready to list?")["answer"]
    seed_two = e.post("title-sets", {"request_key": "p1", "sku": "steel-bottle", "product_name": "steel bottle", "marketplaces": [AMAZON]})
    e.post("title-sets", {"request_key": "p2", "sku": "glass-jar", "product_name": "glass jar", "marketplaces": [AMAZON]})
    assert seed_two.status_code == 200
    assert "Which product do you mean" in say(c, inv, "What questions will buyers ask?")["answer"]
    r = say(c, inv, "Is my glass jar ready to list?")
    assert "glass jar" in [m["choices"] for m in messages(c, inv) if (m.get("choices") or {}).get("kind") == "READINESS"][0]["product"]["name"] and r["status"] == "DELIVERED"


def test_asking_to_write_something_is_not_taken_for_a_readiness_request(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "write titles for my steel bottle with a readiness check")
    assert r["status"] == "CLARIFIED" and r["choices"]["playbook"] == "cmo.generate_title_sets"
    assert not any((m.get("choices") or {}).get("kind") == "READINESS" for m in messages(c, inv))
