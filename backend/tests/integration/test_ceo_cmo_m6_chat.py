"""CMO 3.0 M6 through the real CEO chat (N-05a-d, N-05h-i, N-05r, N-08a, N-15a, N-15g, R-08): "create my complete listing" is asked, refused in plain words BEFORE any plan card when it cannot be done,
planned on an exact card, never run by typed text, run once on approval with per-artefact billing, and answered with the LISTING card; the seller's own edit and "show my listing" are free; typed text
never approves a listing."""

from __future__ import annotations

import os

import pytest

from backend.ceo import cmo_chat
from slim_cmo.service.models import NewFact
from slim_cmo.types import SellerFactType as F
from tests.integration.test_ceo_cmo_delegation import approve, chat, messages, new_investigation, say  # noqa: F401
from tests.integration.test_ci_p3 import seed_competitor
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import FLAG_ON, ListingProvider, NAME, TITLE, ru_env

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

SKU = cmo_chat.product_sku(NAME)
ASK = "create my complete Amazon listing"


def seed(c, *extra: NewFact, with_facts=True):
    ru_env(c.env, ListingProvider())
    rows = [NewFact(F.ATTRIBUTE, SKU, "product_name", NAME), NewFact(F.BRAND, SKU, None, "AquaNest"), NewFact(F.ATTRIBUTE, SKU, "Size", "1 litre"),
            NewFact(F.ATTRIBUTE, SKU, "Material", "stainless steel"), NewFact(F.ATTRIBUTE, SKU, "Color", "silver")] if with_facts else []
    c.env.runtime.store.save_facts(c.env.tenant, c.env.user_id, [*rows, *extra])


def converse(c, inv, first=ASK, hashtags=False):
    """Answer each question the CEO asks until it plans (or refuses)."""
    r = say(c, inv, first)
    for _ in range(10):
        if r["status"] != "CLARIFIED":
            return r
        slot = str(r.get("clarifyFor", ""))
        answer = NAME if slot in ("product_name", "product") else "Amazon" if "marketplace" in slot else TITLE if "title" in slot else ("yes" if hashtags else "skip") if slot == "include_hashtags" else "skip"
        r = say(c, inv, answer)
    raise AssertionError(f"still asking: {r}")


def counts(c):
    e = c.env
    return {"gens": e.n("cmo_generation"), "cmo_events": e.n("metered_event", "agent_code = 'CMO'"), "audits": e.n("cmo_listing_audit"), "calls": e.provider.calls}


def plan_messages(c, inv):
    return [m for m in messages(c, inv) if m["kind"] == "PLAN"]


def last_answer(c, inv):
    return [m for m in messages(c, inv) if m["role"] == "CEO" and m["kind"] == "ANSWER"][-1]


# ---------------------------------------------------------------- the plan, the approval, the card
def test_the_request_is_planned_on_a_card_nothing_runs_typed_yes_does_nothing_and_approve_runs_once(chat):
    seed(chat)
    inv = new_investigation(chat)
    r = converse(chat, inv)
    assert r["status"] == "PLANNED", r
    plan = r["plan"]
    leg = plan["plan"]["legs"][0]
    assert leg["action_key"] == "cmo.generate_full_listing" and leg["slots"]["marketplace"] == "AMAZON" and leg["slots"]["seller_title"] == TITLE and "hashtags" not in str(leg["slots"]).lower()
    card = plan["plan"]["summary_text"]
    for line in ("The listing copy pack (description, bullet points, keywords): 1 CMO unit", "Amazon backend search terms: 1 CMO unit", "Total: up to 2 CMO units", "Hashtags are not included",
                 "The audit, the keyword map and the competitor notes are free", "Marketplace rules are not verified for Amazon", "lengths will be measured, not checked",
                 "Draft target: 3 bullets (not a marketplace requirement)", "Nothing is sent to a marketplace and nothing is published"):
        assert line in card, line
    assert any(l.startswith("Cost: up to 2 CMO units") for l in plan["plan"]["compact_lines"]) and any("not verified" in l for l in plan["plan"]["compact_lines"])
    assert "Competitor listing themes were not used" in card  # the existing competitor line is on the card (N-05c)
    assert "Nothing has run yet" in card and plan["status"] == "AWAITING_APPROVAL" and "typing yes does not approve" in plan_messages(chat, inv)[0]["content"]
    before = counts(chat)
    assert before["gens"] == 0 and before["cmo_events"] == 0 and before["calls"] == 0  # a plan card charges and generates nothing
    typed = say(chat, inv, "yes")
    assert counts(chat) == before and typed["status"] != "DELIVERED"  # typed text never approves (R-08)
    res = approve(chat, inv, plan)
    assert res.status_code == 200, res.text
    after = counts(chat)
    assert after["cmo_events"] == 2 and after["audits"] == 1 and after["gens"] == 2  # copy pack + Amazon backend terms; the audit is free
    msg = last_answer(chat, inv)
    card = msg["choices"]
    assert card["kind"] == "LISTING" and card["marketplace"] == "AMAZON" and card["rulesBasis"] == "UNVERIFIED" and "not verified" in card["banner"]
    assert card["sections"]["title"] == TITLE and card["audit"]["verdict"] != "BLOCKED"
    assert "published" not in msg["content"].lower().replace("nothing is published", "").replace("not published", "") or "Nothing is published" in msg["content"]
    again = approve(chat, inv, plan)
    assert counts(chat) == after, again.text  # a double approve runs and charges once


def test_a_missing_fact_set_is_refused_in_plain_words_before_any_plan_card(chat):
    seed(chat, with_facts=False)
    inv = new_investigation(chat)
    r = converse(chat, inv)
    assert r["status"] != "PLANNED", r
    assert "Tell me" in r["answer"] and all(name in r["answer"] for name in ("Brand", "Size or capacity", "Material"))  # the missing details are NAMED (N-05f, N-05h)
    assert counts(chat) == {"gens": 0, "cmo_events": 0, "audits": 0, "calls": 0} and r.get("plan") is None and plan_messages(chat, inv) == []


def test_one_missing_required_detail_is_named_and_stops_the_request_before_any_plan_card(chat):
    ru_env(chat.env, ListingProvider())
    rows = [NewFact(F.ATTRIBUTE, SKU, "product_name", NAME), NewFact(F.BRAND, SKU, None, "AquaNest"), NewFact(F.ATTRIBUTE, SKU, "Size", "1 litre"), NewFact(F.ATTRIBUTE, SKU, "Color", "silver")]
    chat.env.runtime.store.save_facts(chat.env.tenant, chat.env.user_id, rows)  # no material
    inv = new_investigation(chat)
    r = converse(chat, inv)
    assert r.get("plan") is None and "Material" in r["answer"] and "Brand" not in r["answer"].split("Tell me:")[-1]
    assert counts(chat) == {"gens": 0, "cmo_events": 0, "audits": 0, "calls": 0} and plan_messages(chat, inv) == []


def test_saved_competitor_themes_are_named_on_the_plan_card_frozen_into_the_plan_and_used_only_after_approve(chat):
    seed(chat, NewFact(F.ATTRIBUTE, SKU, "Feature", "reusable"))  # a confirmed fact that carries one of the competitor themes
    insight = seed_competitor(chat.env, themes=["reusable", "insulated"])
    inv = new_investigation(chat)
    plan = converse(chat, inv)["plan"]
    leg = plan["plan"]["legs"][0]
    assert leg["slots"]["ci_insight_ids"] == [str(insight)]  # the seller approves exactly these insights; the ids reached CMO only through the CEO broker
    assert "Informed by themes from 1 of your tracked competitors' saved listings" in plan["plan"]["summary_text"]
    assert counts(chat)["gens"] == 0 and counts(chat)["calls"] == 0
    assert approve(chat, inv, plan).status_code == 200
    assert chat.env.q("SELECT input_mode FROM cmo_generation WHERE output_type = 'LISTING_COPY' AND status = 'COMPLETE'")[0][0] == "CEO_BROKERED_CI"


def test_declining_the_plan_generates_nothing_and_the_old_card_can_never_be_approved_later(chat):
    seed(chat)
    inv = new_investigation(chat)
    plan = converse(chat, inv)["plan"]
    d = chat.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/decline", json={"reason": "not now"}, headers=chat.env.headers)
    assert d.status_code == 200 and d.json()["status"] == "DECLINED"
    late = approve(chat, inv, plan)
    assert late.status_code in (409, 422) and counts(chat) == {"gens": 0, "cmo_events": 0, "audits": 0, "calls": 0}


def test_contradictory_confirmed_facts_are_refused_before_any_plan_card(chat):
    seed(chat, NewFact(F.ATTRIBUTE, SKU, "Capacity", "500 ml"))
    inv = new_investigation(chat)
    r = converse(chat, inv)
    assert r["status"] != "PLANNED" and "disagree" in r["answer"]
    assert counts(chat)["gens"] == 0 and r.get("plan") is None and plan_messages(chat, inv) == []


def test_the_copy_pack_and_titles_keep_their_own_routes(chat):
    seed(chat)
    inv = new_investigation(chat)
    r = say(chat, inv, "write a listing copy pack for my steel bottle")
    plan_keys = [p for p in [r.get("routeKey")] if p]
    assert "cmo.generate_full_listing" not in plan_keys and r["status"] in ("CLARIFIED", "PLANNED")


# ---------------------------------------------------------------- free replies in the chat
def listed(chat):
    seed(chat)
    inv = new_investigation(chat)
    plan = converse(chat, inv)["plan"]
    assert approve(chat, inv, plan).status_code == 200
    return inv


def test_the_seller_edits_one_bullet_in_chat_for_free_and_the_new_version_comes_back_as_a_card(chat):
    inv = listed(chat)
    before = counts(chat)
    r = say(chat, inv, "Change bullet 3 to: Wide mouth makes filling and cleaning easy.")
    assert r["status"] == "DELIVERED" or r.get("answer")
    msg = last_answer(chat, inv)
    assert msg["choices"]["kind"] == "LISTING" and msg["choices"]["sections"]["bullets"][2].startswith("Wide mouth") and msg["choices"]["revisionOf"]
    assert "Nothing was charged" in msg["content"]
    now = counts(chat)
    assert now["cmo_events"] == before["cmo_events"] and now["gens"] == before["gens"] + 1 and now["audits"] == before["audits"] + 1 and now["calls"] == before["calls"]


def test_a_refused_edit_says_why_in_plain_words_and_saves_nothing(chat):
    inv = listed(chat)
    before = counts(chat)
    for bad in ("Change bullet 2 to: Keeps drinks cold for 24 hours", "Change bullet 9 to: x", "Change title to: Something else", "Change keywords to: cheap flask"):
        say(chat, inv, bad)
        msg = last_answer(chat, inv)
        assert msg["choices"] is None and msg["content"], bad
    assert counts(chat) == before


def test_show_my_listing_returns_the_latest_card_and_typed_approval_records_nothing(chat):
    inv = listed(chat)
    say(chat, inv, "show my listing")
    assert last_answer(chat, inv)["choices"]["kind"] == "LISTING"
    for typed in ("approve this listing", "I approve it for use", "yes, approved"):
        say(chat, inv, typed)
    assert chat.env.n("cmo_result_usage_event", "event_kind = 'APPROVED'") == 0  # approval is a click on the card, never typed text


def test_another_tenant_cannot_see_or_edit_my_listing_in_chat(chat):
    listed(chat)
    other_tenant, headers = chat.env.other_tenant()
    inv2 = new_investigation(chat, headers=headers)
    for text in ("show my listing", "Change bullet 1 to: Hijacked"):
        r = say(chat, inv2, text, headers=headers)
        assert "do not have a complete listing" in r["answer"], r
    assert chat.env.n("cmo_generation", tenant=other_tenant) == 0
    assert chat.env.n("cmo_generation") == 2  # mine are untouched


# ---------------------------------------------------------------- optional hashtags, rules shown on the card, refusal before any plan
def test_hashtags_are_added_only_when_the_seller_says_yes_and_cost_one_more_unit(chat):
    seed(chat)
    inv = new_investigation(chat)
    plan = converse(chat, inv, hashtags=True)["plan"]
    assert "Total: up to 3 CMO units" in plan["plan"]["summary_text"] and "Hashtags are included" in plan["plan"]["summary_text"]
    assert plan["plan"]["legs"][0]["slots"]["include_hashtags"] is True
    assert approve(chat, inv, plan).status_code == 200
    assert chat.env.n("metered_event", "agent_code = 'CMO'") == 3 and chat.env.n("cmo_generation", "output_type = 'HASHTAGS'") == 1


def test_with_unverified_drafts_not_enabled_the_request_is_refused_before_any_plan_card(chat):
    seed(chat)
    ru_env(chat.env, ListingProvider(), config={**FLAG_ON, "listing_unverified_rules_enabled": False})
    inv = new_investigation(chat)
    r = converse(chat, inv)
    assert r["status"] != "PLANNED" and "unverified drafts are not enabled" in r["answer"]
    assert r.get("plan") is None and counts(chat)["gens"] == 0 and counts(chat)["cmo_events"] == 0


def test_a_verified_rule_is_named_on_the_card_and_the_listing_is_not_labelled_unverified(chat):
    seed(chat)
    with chat.env.engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("INSERT INTO format_constraint (marketplace, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type, description_max_chars, keywords_max_count, "
                          "keywords_max_chars, backend_terms_max_bytes, count_rule, source_url, verified_at, version, row_kind) VALUES ('AMAZON', 200, 3, 3, 200, 'plain', 900, 10, 40, 249, "
                          "'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture', now(), 1, 'TEST_FIXTURE')"))
    inv = new_investigation(chat)
    plan = converse(chat, inv)["plan"]
    assert "the verified Amazon rule" in plan["plan"]["summary_text"] and "not verified for Amazon" not in plan["plan"]["summary_text"]
    assert approve(chat, inv, plan).status_code == 200
    card = last_answer(chat, inv)["choices"]
    assert card["rulesBasis"] == "VERIFIED" and card["banner"] is None

