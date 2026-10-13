"""CHECKPOINT 2: the seller talks only to the CEO; the CEO delegates to the CMO (ceo-cmo-delegation.md CD1, CD2, CD4, CD11-CD13; AC-D2, D5, D6, D11, D12, D13, D18, D22).

Two layers, both over a real Postgres:
* HTTP end to end over the REAL registry, the REAL CMO handlers and generator (only the CMO's language model is a deterministic fake): ask -> the CEO asks -> plan card -> nothing
  ran -> a typed "yes" approves nothing -> the Approve call runs the CMO once -> the result is in the chat -> the same artefact is on the read-only dashboard API (and not on
  another tenant's); a double approve charges once; a failed run charges nothing and says so.
* The orchestrator with recording handlers for the bounded loop wired into the real conversation (limits, expiry, restart, CONFIG_INVALID, the remembered product)."""

from __future__ import annotations

import dataclasses
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.api.v1 import ceo as ceo_api
from backend.ceo import approval, orchestrator
from backend.ceo.registry import get_registry
from backend.ceo.runtime import CeoRuntime
from backend.repositories import accounting_cutover_repo, investigation_plan_repo as plan_repo, investigation_repo as repo
from tests.integration.ceo_support import T0, ctx_for
from tests.integration.test_ceo_approval_blocked_chat import recording_registry, side_effects
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

# fixtures of the CMO API suite (a tenant with verified-for-test marketplace rules, a deterministic fake CMO model, a login)
from .test_cmo_api import TITLES, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

ASK = "give me titles for my steel bottle"
PRODUCT = "steel bottle"


# ================================================================================================ HTTP end to end
@pytest.fixture
def chat(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: datetime(2020, 1, 1, tzinfo=timezone.utc))  # the CEO unit rule is in effect
    monkeypatch.setenv("CMO_SHOWCASE_PAGE_LIMIT", "50")
    monkeypatch.setenv("CMO_LLM_MODEL", "test-model")
    rt = CeoRuntime(classifier=Scripted({}).model(), composer=Grounded().model(), leg_timeout_seconds=30, max_legs=5, registry=get_registry())
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    client = TestClient(app)
    try:
        yield dataclasses.make_dataclass("Chat", ["env", "client", "rt"])(env, client, rt)
    finally:
        app.dependency_overrides.pop(ceo_api.get_runtime, None)


def say(c, inv, text, headers=None):
    r = c.client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": text}, headers=headers or c.env.headers)
    assert r.status_code == 200, r.text
    return r.json()


def new_investigation(c, headers=None) -> str:
    r = c.client.post("/api/v1/ceo/investigations", json={"title": "Listings"}, headers=headers or c.env.headers)
    assert r.status_code == 201, r.text
    return r.json()["investigationId"]


def approve(c, inv, plan, plan_hash=None, headers=None):
    return c.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/approve", json={"plan_hash": plan_hash or plan["planHash"]}, headers=headers or c.env.headers)


def skip_extras(c, inv, r):
    """The optional extra-detail questions (brand, size, features...) that follow the required ones: each is skipped."""
    while r["status"] == "CLARIFIED" and str(r.get("clarifyFor", "")).startswith("fact_"):
        r = say(c, inv, "skip")
    return r


def messages(c, inv):
    return repo.list_messages(c.env.tenant, uuid.UUID(inv))


def ask_for_titles(c) -> tuple[str, dict]:
    """The real path: the seller asks, the CEO asks what the CMO needs one question at a time, the seller answers, and the turn ends PLANNED."""
    inv = new_investigation(c)
    q1 = say(c, inv, ASK)
    assert q1["status"] == "CLARIFIED", q1
    skipped = say(c, inv, "skip")  # the optional category
    assert skipped["status"] == "CLARIFIED" and "Which marketplace" in skipped["answer"], skipped  # the CEO asks for the marketplace; it never defaults it
    planned = skip_extras(c, inv, say(c, inv, "Amazon"))
    assert planned["status"] == "PLANNED", planned
    return inv, planned


def cmo_counts(c) -> dict:
    e = c.env
    return {"generations": e.n("cmo_generation"), "cmo_events": e.n("metered_event", "agent_code = 'CMO'"), "ceo_events": e.n("metered_event", "agent_code = 'CEO'"),
            "model_calls": e.provider.calls}


def test_a_title_request_goes_ask_plan_card_nothing_ran_typed_yes_does_nothing_approve_runs_once_and_the_dashboard_shows_it(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    plan = planned["plan"]
    # ---- the plan card: exact, stored, nothing has run, nothing is used
    assert cmo_counts(c) == {"generations": 0, "cmo_events": 0, "ceo_events": 0, "model_calls": 0}
    leg = plan["plan"]["legs"][0]
    assert leg["action_key"] == "cmo.generate_title_sets" and leg["slots"]["product_name"] == PRODUCT and leg["slots"]["marketplaces"] == ["AMAZON"]
    assert "category_hint" not in leg["slots"]  # a skipped optional field is absent, never defaulted
    card = plan["plan"]["summary_text"]
    assert "Slim CMO (recommend-only) will write listing title options for steel bottle on Amazon" in card
    assert "Model: test-model, on Metrion's own language-model server (operator-controlled)" in card
    assert "Quota effect: 1 CMO unit" in card and "Nothing has run yet" in card and plan["status"] == "AWAITING_APPROVAL" and plan["viewerIsRequester"] is True
    plan_msgs = [m for m in messages(c, inv) if m["kind"] == "PLAN"]
    assert len(plan_msgs) == 1 and plan_msgs[0]["role"] == "CEO" and "typing yes does not approve" in plan_msgs[0]["content"]
    assert plan_msgs[0]["content"] == approval.PLAN_MESSAGE_LEAD and "recommend-only" not in plan_msgs[0]["content"]  # the chat message does not repeat the plan
    compact = plan["plan"]["compact_lines"]  # the card: a few short lines; the complete text above stays in the stored plan
    assert 3 <= len(compact) <= 5 and compact[0] == "Write listing titles for steel bottle on Amazon." and "Cost: 1 CMO unit, only if it completes." in compact
    assert any("Thin input" in l for l in compact) and plan["plan"]["title"] == "Write listing titles for steel bottle on Amazon"
    # ---- a typed yes (any wording) is only text
    for typed in ("yes", "go ahead", "approve it"):
        say(c, inv, typed)
    assert cmo_counts(c) == {"generations": 0, "cmo_events": 0, "ceo_events": 0, "model_calls": 0}
    assert plan_repo.get(e.tenant, uuid.UUID(inv), uuid.UUID(plan["id"]))["status"] == "AWAITING_APPROVAL"
    # ---- the Approve button: the plan id and the plan hash
    r = approve(c, inv, plan)
    assert r.status_code == 200, r.text
    body = r.json()
    print("PLANCARD\n" + card + "\nANSWER\n" + body["answer"])
    assert body["status"] == "DELIVERED" and body["routeSource"] == "APPROVAL" and body["plan"]["status"] == "APPROVED" and body["replayed"] is False
    assert cmo_counts(c) == {"generations": 1, "cmo_events": 1, "ceo_events": 1, "model_calls": 1}  # the CMO ran once; one CMO unit; one CEO conversation unit
    answer = body["answer"]
    for title in TITLES:
        assert title in answer and "characters)" not in answer  # clean text in chat; counts live on the dashboard
    assert "Written by Slim CMO (recommend-only)" in answer and "Saved as: title set (Amazon)" in answer
    assert "Used from your plan: 1 CMO unit." in answer and "also appear on the Slim CMO dashboard" in answer and "Written by the specialist" in answer
    assert "NOT a verified marketplace rule" in answer and "Fitted to the marketplace rule" not in answer  # a test-fixture length rule is never presented as a real marketplace rule
    assert "Thin input - add brand/size/features for stronger titles." in answer  # the seller skipped every extra detail
    # ---- the saved artefact is the one the read-only dashboard lists, for this tenant only
    shown = c.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=e.headers).json()["items"]
    assert [i["titleText"] for i in shown] == TITLES and all(i["charCount"] == len(i["titleText"]) for i in shown)
    other_id, other_headers = e.other_tenant()
    assert c.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=other_headers).json()["items"] == []
    assert e.n("cmo_generation", tenant=other_id) == 0


def test_the_dashboard_shows_results_from_every_conversation_of_the_tenant(chat):
    c, e = chat, chat.env
    inv1, p1 = ask_for_titles(c)
    assert approve(c, inv1, p1["plan"]).status_code == 200
    inv2 = new_investigation(c)  # a second conversation, a different product
    say(c, inv2, "give me titles for my copper mug")
    say(c, inv2, "skip")
    p2 = skip_extras(c, inv2, say(c, inv2, "Amazon"))["plan"]
    assert approve(c, inv2, p2).status_code == 200
    assert e.n("cmo_generation") == 2
    shown = c.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=e.headers).json()["items"]
    assert len(shown) == 2 * len(TITLES)  # both conversations' results, no investigation filter


def test_a_double_approve_runs_and_charges_once(chat):
    c = chat
    inv, planned = ask_for_titles(c)
    first = approve(c, inv, planned["plan"]).json()
    second = approve(c, inv, planned["plan"])
    assert second.status_code == 200 and second.json()["replayed"] is True and second.json()["turnId"] == first["turnId"]
    assert cmo_counts(c) == {"generations": 1, "cmo_events": 1, "ceo_events": 1, "model_calls": 1}
    third = approve(c, inv, planned["plan"])
    assert third.json()["replayed"] is True and cmo_counts(c)["cmo_events"] == 1


def test_a_wrong_hash_is_refused_and_nothing_runs(chat):
    c = chat
    inv, planned = ask_for_titles(c)
    r = approve(c, inv, planned["plan"], plan_hash="0" * 64)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_CHANGED"
    assert cmo_counts(c) == {"generations": 0, "cmo_events": 0, "ceo_events": 0, "model_calls": 0}


def test_a_failed_cmo_run_charges_nothing_and_the_message_says_so(chat):
    c, e = chat, chat.env
    e.provider.mode = "garbage"  # the CMO's model returns nonsense: every artefact fails
    inv, planned = ask_for_titles(c)
    r = approve(c, inv, planned["plan"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "FAILED"
    assert "I could not complete this plan" in body["answer"] and "Not available: Title options for Amazon could not be written" in body["answer"]
    assert "not charged to your plan" in body["answer"] and "Here is what Slim CMO wrote" not in body["answer"] and "Saved as" not in body["answer"]
    counts = cmo_counts(c)
    assert counts["cmo_events"] == 0 and counts["ceo_events"] == 0  # no CMO unit, no CEO conversation unit
    assert e.reservations() in ([], ["RELEASED"])  # nothing stays reserved against the cap
    assert c.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=e.headers).json()["items"] == []  # a failed artefact is never shown as a result


# ================================================================================================ the bounded loop wired into the real conversation
class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(milliseconds=1)
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def loop(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: T0 - timedelta(days=1))
    for v in ("CMO_DELEGATION_MAX_QUESTIONS", "CMO_DELEGATION_MAX_REASKS", "CMO_DELEGATION_IDLE_EXPIRY_SECONDS"):
        monkeypatch.delenv(v, raising=False)
    calls: dict = {}
    clock = Clock()
    rt = dataclasses.replace(runtime(Scripted({}), Grounded(), registry=recording_registry(calls)), clock=clock)
    ctx = ctx_for(a, user_id=app_user)
    return dataclasses.make_dataclass("Loop", ["a", "ctx", "rt", "calls", "clock", "inv", "monkeypatch"])(a, ctx, rt, calls, clock, start(ctx, rt), monkeypatch)


def chat_say(lp, text, *, prev=None, option=None):
    clar = orchestrator.ClarificationReply(prev.message_id, option) if prev is not None else None
    return orchestrator.run_turn(lp.ctx, lp.rt, lp.inv, text or "(chose an option)", clarification=clar)


HASHTAGS = "give me hashtags for my steel water bottle"


def skip_extras_lp(lp, res):
    """The optional extra-detail questions (brand, features) that follow the required ones: each is skipped."""
    while res.status == "CLARIFIED" and str(res.choices["slot"]).startswith("fact_"):
        res = chat_say(lp, "skip")
    return res


def test_limit_reached_in_the_conversation_explains_runs_nothing_and_restart_starts_afresh(loop):
    loop.monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "2")
    q1 = chat_say(loop, HASHTAGS)
    assert q1.status == "CLARIFIED" and q1.choices["delegation"]["questionCount"] == 1 and "Which marketplace" in q1.answer  # the product was said: only the marketplace is asked
    q2 = chat_say(loop, "the big one")  # unusable: asked again (question 2, allowed)
    assert q2.status == "CLARIFIED" and q2.choices["delegation"]["questionCount"] == 2 and q2.choices["slot"] == "marketplace"
    stopped = chat_say(loop, "whichever you like")  # a third question would be the 3rd of 2
    assert stopped.status == "CLARIFIED" and stopped.choices["slot"] == "restart" and "2 questions" in stopped.answer and "Nothing was run, sent or used up" in stopped.answer
    assert [o["key"] for o in stopped.choices["options"]] == ["restart", "cancel"]
    assert loop.calls == {} and side_effects(loop.a)[1] == []  # nothing ran, nothing metered (not even the CEO unit)
    restarted = chat_say(loop, "", prev=stopped, option="restart")
    assert restarted.status == "CLARIFIED" and restarted.choices["delegation"]["questionCount"] == 1 and restarted.choices["delegation"]["reaskCounts"] == {}
    assert restarted.choices["slot"] == "product_name"
    assert restarted.choices["options"][0]["key"] == "prev" and restarted.choices["options"][0]["value"] == "steel water bottle"  # offered back, not silently reused


def test_reask_limit_in_the_conversation(loop):
    loop.monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "40")
    chat_say(loop, HASHTAGS)
    for n in (1, 2):
        again = chat_say(loop, "blue ish")
        assert again.choices["slot"] == "marketplace" and again.choices["delegation"]["reaskCounts"] == {"marketplace": n}
    stopped = chat_say(loop, "green ish")
    assert stopped.choices["slot"] == "restart" and "3 tries" in stopped.answer and loop.calls == {}


def test_86399_seconds_is_live_and_86400_is_expired_with_the_answers_kept_and_a_fresh_confirmation_required(loop):
    q1 = chat_say(loop, HASHTAGS)
    loop.clock.advance(86398)  # the next tick adds a millisecond: still under 86399 s
    live = chat_say(loop, "the big one")
    assert live.choices["delegation"]["status"] == "LIVE" and live.choices["slot"] == "marketplace"
    loop.clock.advance(86400)
    expired = chat_say(loop, "Amazon")
    assert expired.status == "CLARIFIED" and expired.choices["slot"] == "continue" and expired.choices["delegation"]["status"] == "EXPIRED"
    assert expired.choices["pending"]["collected"] == {"product_name": "steel water bottle"} and "Nothing has run" in expired.answer
    assert loop.calls == {} and plan_repo.list_for_investigation(loop.a, loop.inv) == []
    typed = chat_say(loop, "Amazon")  # an answer is not the confirmation
    assert typed.choices["slot"] == "continue" and plan_repo.list_for_investigation(loop.a, loop.inv) == []
    cont = chat_say(loop, "", prev=typed, option="continue")
    assert cont.choices["slot"] == "marketplace" and cont.choices["delegation"]["status"] == "LIVE"
    planned = skip_extras_lp(loop, chat_say(loop, "Amazon"))
    assert planned.status == "PLANNED" and loop.calls == {}  # the plan still needs its own approval (a separate, later step)
    assert plan_repo.get(loop.a, loop.inv, planned.plan_id)["plan"]["legs"][0]["slots"]["product_name"] == "steel water bottle"


def test_an_invalid_limit_setting_fails_closed_before_any_question(loop):
    loop.monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "0")
    res = chat_say(loop, HASHTAGS)
    assert res.status == "FAILED" and "CONFIG_INVALID" in res.answer and res.choices is None and res.plan_id is None
    assert loop.calls == {} and side_effects(loop.a)[1] == []
    loop.monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "8")
    ok = chat_say(loop, HASHTAGS)
    assert ok.status == "CLARIFIED"
    loop.monkeypatch.setenv("CMO_DELEGATION_IDLE_EXPIRY_SECONDS", "soon")  # broken while a task is open: the next answer is refused, not guessed
    blocked = chat_say(loop, "Amazon")
    assert blocked.status == "FAILED" and "CONFIG_INVALID" in blocked.answer and plan_repo.list_for_investigation(loop.a, loop.inv) == []


def test_a_confirmed_product_is_not_asked_again_in_a_follow_up_and_a_changed_answer_makes_a_new_plan(loop):
    first = chat_say(loop, HASHTAGS)
    assert "Which marketplace" in first.answer
    brand_q = chat_say(loop, "Amazon")
    assert brand_q.choices["slot"] == "fact_brand"
    p1 = skip_extras_lp(loop, chat_say(loop, "Acme"))  # the brand is given; the features are skipped
    assert p1.status == "PLANNED"
    follow = chat_say(loop, "write hashtags for it")  # "it": the product the seller already gave
    assert follow.status == "CLARIFIED" and follow.choices["slot"] == "marketplace" and follow.choices["pending"]["collected"] == {"product_name": "steel water bottle", "fact_brand": "Acme"}
    nxt = chat_say(loop, "Flipkart")  # the brand given earlier is carried and not asked again; the features were skipped, so they are asked
    assert nxt.choices["slot"] == "fact_key_features"
    p2 = skip_extras_lp(loop, nxt)  # a different marketplace: a different plan
    assert p2.status == "PLANNED" and p2.plan_id != p1.plan_id
    rows = {r["id"]: r for r in plan_repo.list_for_investigation(loop.a, loop.inv)}
    assert rows[p1.plan_id]["status"] == "SUPERSEDED" and rows[p2.plan_id]["status"] == "AWAITING_APPROVAL"
    slots = rows[p2.plan_id]["plan"]["legs"][0]["slots"]
    assert slots["product_name"] == "steel water bottle" and slots["marketplace"] == "FLIPKART" and slots["brand"] == "Acme"
    assert loop.calls == {}


def test_a_pronoun_with_nothing_to_refer_to_asks_for_the_product_never_guesses(loop):
    q = chat_say(loop, "write hashtags for it")
    assert q.status == "CLARIFIED" and q.choices["slot"] == "product_name" and q.choices["pending"]["collected"] == {}


def test_the_other_agents_still_get_the_old_refusal(loop):
    res = chat_say(loop, "ok now i want the top trending products to sell my nich is mens shoes")
    assert res.status == "DENIED" and res.answer.startswith(orchestrator.APPROVAL_UNAVAILABLE_TEXT)
    assert loop.calls == {}
