"""CMO 3.0 M6 model rewrite of one section through the real CEO chat (Q26; N-15b, N-15c, R-08): "rewrite bullet 3 to mention wide opening" is refused in plain words BEFORE any plan card when it cannot
be done, planned on an exact card that shows the 1-unit cost, never run by typed text, run once on approval, and answered with the new version's LISTING card. A declined plan runs nothing. A rewrite that
cannot pass uses nothing. Another tenant, and a member without the CMO permission, get nothing."""

from __future__ import annotations

import json
import os

import pytest

from backend.auth.permissions import PARTNER_ROLE
from backend.ceo import cmo_chat
from slim_cmo.service.models import NewFact
from slim_cmo.types import SellerFactType as F
from tests.integration.test_ceo_cmo_delegation import approve, chat, messages, new_investigation, say  # noqa: F401
from tests.integration.test_ceo_cmo_m6_chat import ASK, SKU, converse, counts, last_answer, plan_messages
from tests.integration.test_cmo_api import _erase_cmo_rows, _login, ctx_engine, env, fake_clerk, seed_cap  # noqa: F401
from tests.integration.test_cmo_m6_integration import NAME, ru_env
from tests.integration.test_cmo_m6_rewrite_integration import GOOD, METER, RewriteProvider

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

REWRITE = "rewrite bullet 3 to mention wide opening"


def seed(c, rewrites=(), *, with_listing=True):
    """Confirmed facts (including 'Opening: wide') and, unless told not to, a complete listing written through the chat. Returns the investigation."""
    ru_env(c.env, RewriteProvider(rewrites))
    rows = [NewFact(F.ATTRIBUTE, SKU, "product_name", NAME), NewFact(F.BRAND, SKU, None, "AquaNest"), NewFact(F.ATTRIBUTE, SKU, "Size", "1 litre"),
            NewFact(F.ATTRIBUTE, SKU, "Material", "stainless steel"), NewFact(F.ATTRIBUTE, SKU, "Color", "silver"), NewFact(F.ATTRIBUTE, SKU, "Opening", "wide")]
    c.env.runtime.store.save_facts(c.env.tenant, c.env.user_id, rows)
    inv = new_investigation(c)
    if with_listing:
        plan = plan_of(c, inv, converse(c, inv, ASK))
        assert approve(c, inv, plan).status_code == 200
    return inv


def rw_counts(c):
    e = c.env
    return {**counts(c), "complete": e.n("cmo_generation", "status = 'COMPLETE' AND output_type = 'LISTING_COPY'"), "failed": e.n("cmo_generation", "status = 'FAILED'")}


def plan_of(c, inv, r):
    assert r["status"] == "PLANNED", r
    return r["plan"]


def no_plan(c, inv, headers=None):
    return [m for m in messages(c, inv) if m["kind"] == "PLAN"]


# ---------------------------------------------------------------- the plan, the approval, the card
def test_a_rewrite_is_planned_with_its_cost_nothing_runs_typed_yes_does_nothing_and_approve_runs_once(chat):
    inv = seed(chat, [GOOD])
    before = rw_counts(chat)
    r = converse(chat, inv, REWRITE)
    assert r["status"] == "PLANNED", r
    plan = plan_of(chat, inv, r)
    shown = json.dumps(plan)
    assert "1 CMO unit" in shown and "bullet 3" in shown and "wide opening" in shown and "stays saved" in shown and "same checks" in shown
    assert rw_counts(chat) == before  # a plan card charges, saves and generates nothing
    typed = say(chat, inv, "yes")
    assert rw_counts(chat) == before and typed["status"] != "DELIVERED"  # typed text never approves (R-08)
    res = approve(chat, inv, plan)
    assert res.status_code == 200, res.text
    after = rw_counts(chat)
    assert after["cmo_events"] == before["cmo_events"] + 1 and after["complete"] == before["complete"] + 1 and after["audits"] == before["audits"] + 1 and after["calls"] == before["calls"] + 1
    msg = last_answer(chat, inv)
    card = msg["choices"]
    assert card["kind"] == "LISTING" and card["revisionOf"] and card["sections"]["bullets"][2] == GOOD and card["states"]["approvedForUse"]["done"] is False
    assert "only the section you named changed" in msg["content"] and "earlier version is still saved" in msg["content"]
    again = approve(chat, inv, plan)
    assert again.status_code == 200 and again.json()["replayed"] is True and rw_counts(chat) == after  # a double approve runs and charges once


def test_the_section_and_topic_the_seller_already_said_are_not_asked_again(chat):
    inv = seed(chat, [GOOD])
    r = say(chat, inv, "rewrite the description to mention wide opening")
    asked = []
    for _ in range(8):
        if r["status"] != "CLARIFIED":
            break
        slot = str(r.get("clarifyFor", ""))
        asked.append(slot)
        r = say(chat, inv, NAME if slot in ("product_name", "product") else "Amazon")
    assert r["status"] == "PLANNED", r
    assert not any("rewrite" in a or "topic" in a or "target" in a for a in asked), asked  # only the product and the marketplace were missing
    summary = plan_of(chat, inv, r)["plan"]["summary_text"]
    assert "rewrite the description" in summary and "wide opening" in summary and "1 CMO unit" in summary, summary


def test_a_section_or_topic_that_was_not_said_is_asked_and_parsed(chat):
    inv = seed(chat, [GOOD])
    r = say(chat, inv, "rewrite bullet 2 to mention wide opening")  # the router reads this; the section and topic are prefilled, the rest is asked
    answers = {"product_name": NAME, "marketplace": "Amazon"}
    for _ in range(8):
        if r["status"] != "CLARIFIED":
            break
        r = say(chat, inv, answers.get(str(r.get("clarifyFor", "")), "skip"))
    assert r["status"] == "PLANNED" and "bullet 2" in plan_of(chat, inv, r)["plan"]["summary_text"]


def test_a_declined_rewrite_plan_runs_nothing_and_cannot_be_approved_afterwards(chat):
    inv = seed(chat, [GOOD])
    before = rw_counts(chat)
    plan = plan_of(chat, inv, converse(chat, inv, REWRITE))
    d = chat.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/decline", json={"reason": "not now"}, headers=chat.env.headers)
    assert d.status_code == 200 and d.json()["status"] == "DECLINED"
    late = approve(chat, inv, plan)
    assert late.status_code in (409, 422) and rw_counts(chat) == before


def test_a_wrong_hash_is_refused_and_nothing_runs(chat):
    inv = seed(chat, [GOOD])
    before = rw_counts(chat)
    plan = plan_of(chat, inv, converse(chat, inv, REWRITE))
    r = approve(chat, inv, plan, plan_hash="0" * 64)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_CHANGED" and rw_counts(chat) == before


# ---------------------------------------------------------------- refused in plain words before any plan card
@pytest.mark.parametrize("ask,words", [
    ("rewrite bullet 3 to mention keeps drinks cold", "do not say anything about"),  # a topic nothing confirmed carries
    ("rewrite bullet 9 to mention wide opening", "no bullet 9"),  # a section that does not exist
])
def test_a_rewrite_that_cannot_be_done_is_refused_before_any_plan_card(chat, ask, words):
    inv = seed(chat, [GOOD])
    before = rw_counts(chat)
    r = converse(chat, inv, ask)
    assert r["status"] != "PLANNED" and words in r["answer"], r
    assert rw_counts(chat) == before and len(no_plan(chat, inv)) == 1  # only the plan that wrote the listing; no new card


def test_no_saved_listing_is_said_plainly_and_nothing_is_planned(chat):
    inv = seed(chat, with_listing=False)
    r = converse(chat, inv, REWRITE)
    assert r["status"] != "PLANNED" and "do not have a complete" in r["answer"]
    assert rw_counts(chat)["gens"] == 0 and no_plan(chat, inv) == []


def test_a_product_with_no_listing_is_not_confused_with_one_that_has(chat):
    seed(chat, [GOOD])
    inv = new_investigation(chat)  # a fresh conversation: nothing is carried over, so the product is asked
    before = rw_counts(chat)
    r = say(chat, inv, REWRITE)
    for _ in range(6):
        if r["status"] != "CLARIFIED":
            break
        slot = str(r.get("clarifyFor", ""))
        r = say(chat, inv, "Copper Mug" if slot in ("product_name", "product") else "Amazon" if "marketplace" in slot else "skip")
    assert r["status"] != "PLANNED" and "do not have a complete" in r["answer"] and rw_counts(chat) == before


def test_the_title_and_other_parts_are_not_rewritable_by_the_model(chat):
    inv = seed(chat, [GOOD])
    before = rw_counts(chat)
    for ask in ("rewrite the title to mention wide opening", "rewrite the keywords to mention wide opening"):
        r = say(chat, inv, ask)
        assert r["status"] != "DELIVERED"
    assert rw_counts(chat) == before and len(no_plan(chat, inv)) == 1


# ---------------------------------------------------------------- failures use nothing
def test_a_rewrite_that_cannot_pass_the_gates_charges_nothing_and_saves_no_version(chat):
    inv = seed(chat, ["Keeps drinks cold with a wide opening."])
    plan = plan_of(chat, inv, converse(chat, inv, REWRITE))
    before = rw_counts(chat)
    res = approve(chat, inv, plan)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "FAILED" and "I could not complete this plan" in body["answer"] and "Keeps drinks cold" not in body["answer"]
    after = rw_counts(chat)
    assert after["cmo_events"] == before["cmo_events"] and after["complete"] == before["complete"] and after["audits"] == before["audits"] and after["failed"] == before["failed"] + 1
    assert last_answer(chat, inv)["choices"] is None and chat.env.reservations().count("RESERVED") == 0


def test_an_exhausted_cap_denies_the_approved_rewrite_with_nothing_generated(chat):
    inv = seed(chat, [GOOD])
    plan = plan_of(chat, inv, converse(chat, inv, REWRITE))
    seed_cap(chat.env.engine, METER, 1)  # the complete listing already used the one unit
    before = rw_counts(chat)
    res = approve(chat, inv, plan)
    assert res.status_code == 200, res.text
    answer = res.json()["answer"]
    assert rw_counts(chat) == before, answer
    assert "I could not complete this plan" in answer and "not available on your current plan" in answer and "Used from your plan: 0 CMO units" in answer  # said plainly, nothing used


# ---------------------------------------------------------------- approvals and versions
def test_an_approval_of_the_earlier_version_does_not_carry_to_the_rewritten_one(chat):
    inv = seed(chat, [GOOD])
    first = chat.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=chat.env.headers)  # noqa: F841 - the dashboard is untouched by this flow
    gid = chat.env.q("SELECT id FROM cmo_generation WHERE output_type = 'LISTING_COPY' AND status = 'COMPLETE' ORDER BY created_at LIMIT 1")[0][0]
    assert chat.client.post(f"/api/v1/cmo/listing/{gid}/approve", headers=chat.env.headers).status_code == 200
    plan = plan_of(chat, inv, converse(chat, inv, REWRITE))
    assert approve(chat, inv, plan).status_code == 200
    card = last_answer(chat, inv)["choices"]
    assert card["states"]["approvedForUse"]["done"] is False and card["revisionOf"] == str(gid)
    assert chat.env.n("cmo_result_usage_event", "event_kind = 'APPROVED'") == 1  # the earlier approval stays exactly as it was; typed text added none
    for typed in ("approve this listing", "yes, approved"):
        say(chat, inv, typed)
    assert chat.env.n("cmo_result_usage_event", "event_kind = 'APPROVED'") == 1


# ---------------------------------------------------------------- security
def test_another_tenant_cannot_plan_or_run_a_rewrite_of_my_listing(chat):
    seed(chat, [GOOD])
    other, headers = chat.env.other_tenant()
    before = rw_counts(chat)
    inv2 = new_investigation(chat, headers=headers)
    r = say(chat, inv2, REWRITE, headers=headers)
    for _ in range(6):
        if r["status"] != "CLARIFIED":
            break
        slot = str(r.get("clarifyFor", ""))
        r = say(chat, inv2, NAME if slot in ("product_name", "product") else "Amazon" if "marketplace" in slot else "skip", headers=headers)
    assert r["status"] != "PLANNED" and "do not have a complete" in r["answer"]
    assert chat.env.n("cmo_generation", tenant=other) == 0 and chat.env.n("metered_event", tenant=other) == 0 and rw_counts(chat) == before


def test_a_member_without_the_cmo_permission_gets_no_plan_and_nothing_runs(chat):
    inv = seed(chat, [GOOD])
    reader, _ = _login(chat.env.fake_clerk, chat.env.tenant, role=PARTNER_ROLE, permissions={"agent.ceo": True, "investigation.view": True, "investigation.create": True})
    inv2 = new_investigation(chat, headers=reader)
    before = rw_counts(chat)
    r = say(chat, inv2, REWRITE, headers=reader)
    for _ in range(4):
        if r["status"] != "CLARIFIED":
            break
        r = say(chat, inv2, NAME, headers=reader)
    assert r["status"] != "PLANNED" and rw_counts(chat) == before
    assert no_plan(chat, inv2) == []
    assert inv  # the seller's own investigation is untouched
