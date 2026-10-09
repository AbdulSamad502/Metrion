"""Spec §6.32: decision cards. Built by code from real candidates; recommended first by a stated rule; exactly four options when at least three real candidates exist
and never a filler; choosing an option or typing "Other" resumes the pending intent with NO model call; a forged or foreign reply is refused."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.ceo import clarification, orchestrator
from backend.repositories import agent_run_repo, investigation_repo as repo
from tests.integration.ceo_support import ctx_for, save_metric
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, health_config, runtime, seed_books, start  # noqa: F401

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]

ASK_CI = "price vs acme"
CI = decision(route="ACTION", route_key="ci.request_price_scenario", slots={"competitor": "acme", "amount": "499"})
NO_MODEL = lambda: runtime(Scripted({}), Grounded())  # noqa: E731  an EMPTY classifier table: any classifier call would raise and fail the turn


def _card_turn(ctx, rt, text):
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, text)
    return inv, res


def _competitors(a, seed, n, *, captured=None):
    out = []
    for i in range(n):
        uid = seed.url(a, f"Acme {['Steel', 'Copper', 'Brass', 'Tin', 'Iron', 'Zinc'][i]}")
        if captured is not None and captured[i] is not None:
            seed.snapshot(a, uid, 40000 + 1000 * i, captured_at=captured[i])
        out.append(uid)
    return out


# --------------------------------------------------------------------------------------------- the card
def test_an_ambiguous_competitor_gets_a_card_recommended_by_most_recent_capture(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    ids = _competitors(a, seed, 3, captured=[NOW - timedelta(days=30), NOW, NOW - timedelta(days=5)])
    ctx = ctx_for(a, user_id=app_user)
    inv, res = _card_turn(ctx, runtime(Scripted({ASK_CI: CI}), Grounded()), ASK_CI)
    assert res.status == "CLARIFIED" and res.clarify_for == "competitor" and res.choices is not None
    card = res.choices
    assert card["kind"] == "AMBIGUOUS" and card["slot"] == "competitor"
    assert [o["kind"] for o in card["options"]] == ["RECOMMENDED", "ALTERNATIVE", "ALTERNATIVE", "OTHER"]  # exactly four with >= 3 real candidates
    assert [o["label"] for o in card["options"][:3]] == ["Acme Copper", "Acme Brass", "Acme Steel"]  # newest capture first
    assert card["options"][0]["reason"].startswith("Most recent capture") and card["options"][3]["label"] == "Other"
    assert card["pending"]["route"] == "ACTION" and card["pending"]["key"] == "ci.request_price_scenario"
    saved = repo.get_message(a, inv, res.message_id)
    assert saved["kind"] == "CLARIFICATION" and saved["choices"]["options"] == card["options"]  # persisted with the message, so a reload shows the same card
    assert agent_run_repo.list_children(a, repo.get_turn(a, res.turn_id)["agent_run_id"]) == []  # nothing was dispatched


@pytest.mark.parametrize("n,expected_kinds", [
    (2, ["RECOMMENDED", "ALTERNATIVE", "OTHER"]),  # fewer than three real candidates: the real ones plus Other, no filler
    (3, ["RECOMMENDED", "ALTERNATIVE", "ALTERNATIVE", "OTHER"]),
    (5, ["RECOMMENDED", "ALTERNATIVE", "ALTERNATIVE", "OTHER"]),  # never more than four
])
def test_the_number_of_options_follows_the_real_candidates_never_a_filler(two_tenants, app_user, seed, n, expected_kinds):  # noqa: F811
    a, _ = two_tenants
    _competitors(a, seed, n)
    ctx = ctx_for(a, user_id=app_user)
    _, res = _card_turn(ctx, runtime(Scripted({ASK_CI: CI}), Grounded()), ASK_CI)
    assert [o["kind"] for o in res.choices["options"]] == expected_kinds


def test_no_real_candidate_means_no_card_just_a_plain_question(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    _, res = _card_turn(ctx, runtime(Scripted({ASK_CI: CI}), Grounded()), ASK_CI)
    assert res.status == "CLARIFIED" and res.choices is None and "No competitors are being tracked" in res.answer


def test_the_recommendation_follows_the_stated_rule_and_changes_with_the_data(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    _competitors(a, seed, 3, captured=[NOW, NOW - timedelta(days=9), NOW - timedelta(days=2)])
    ctx = ctx_for(a, user_id=app_user)
    _, res = _card_turn(ctx, runtime(Scripted({ASK_CI: CI}), Grounded()), ASK_CI)
    assert res.choices["options"][0]["label"] == "Acme Steel"  # the one captured most recently here
    assert res.choices["options"][0]["reason"] == f"Most recent capture: {NOW.date().isoformat()}"


# --------------------------------------------------------------------------------------------- choosing and "Other": no model call
def test_choosing_an_option_resumes_the_intent_with_no_model_call(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    ids = _competitors(a, seed, 3, captured=[NOW, NOW - timedelta(days=3), NOW - timedelta(days=6)])
    ctx = ctx_for(a, user_id=app_user)
    inv, first = _card_turn(ctx, runtime(Scripted({ASK_CI: CI}), Grounded()), ASK_CI)
    alt = first.choices["options"][1]
    res = orchestrator.run_turn(ctx, NO_MODEL(), inv, alt["label"], clarification=orchestrator.ClarificationReply(first.message_id, alt["key"]))
    assert res.status == "DELIVERED" and res.route_key == "ci.request_price_scenario"
    assert f"Competitor: {alt['label']}." in res.notes and "Your current price taken as ₹499.00." in res.notes
    turn = repo.get_turn(a, res.turn_id)
    assert turn["route_source"] == "UI_ACTION" and turn["classifier_result"]["clarificationId"] == str(first.message_id)
    assert turn["classifier_result"]["clarificationOption"] == alt["key"]
    assert ids and any(f["action_key"] == "ci.request_price_scenario" for f in repo.list_findings(a, inv))


def test_typing_other_is_resolved_by_the_same_resolvers_and_can_ask_again(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    _competitors(a, seed, 3, captured=[NOW, NOW, NOW])
    ctx = ctx_for(a, user_id=app_user)
    inv, first = _card_turn(ctx, runtime(Scripted({ASK_CI: CI}), Grounded()), ASK_CI)
    ok = orchestrator.run_turn(ctx, NO_MODEL(), inv, "Acme Brass", clarification=orchestrator.ClarificationReply(first.message_id, None))
    assert ok.status == "DELIVERED" and "Competitor: Acme Brass." in ok.notes
    inv2, first2 = _card_turn(ctx, runtime(Scripted({ASK_CI: CI}), Grounded()), ASK_CI)
    bad = orchestrator.run_turn(ctx, NO_MODEL(), inv2, "Globex", clarification=orchestrator.ClarificationReply(first2.message_id, None))
    assert bad.status == "CLARIFIED" and bad.clarify_for == "competitor" and bad.choices is not None  # a new card; nothing guessed
    assert repo.list_findings(a, inv2) == []


# --------------------------------------------------------------------------------------------- forged and foreign replies
def test_a_forged_unknown_or_foreign_reply_is_refused(two_tenants, app_user, seed):  # noqa: F811
    a, b = two_tenants
    _competitors(a, seed, 3, captured=[NOW, NOW, NOW])
    ctx_a, ctx_b = ctx_for(a, user_id=app_user), ctx_for(b, user_id=app_user)
    inv, first = _card_turn(ctx_a, runtime(Scripted({ASK_CI: CI}), Grounded()), ASK_CI)
    reply = lambda cid, opt: orchestrator.ClarificationReply(cid, opt)  # noqa: E731
    bad = [
        (ctx_a, inv, reply(uuid.uuid4(), "other")),  # no such message
        (ctx_a, inv, reply(first.message_id, "competitor-does-not-exist")),  # not an option of this card
        (ctx_a, inv, reply(first.message_id, "other")),  # "Other" is a typed answer, not a selectable value
    ]
    user_msg = repo.list_messages(a, inv)[0]["id"]
    bad.append((ctx_a, inv, reply(user_msg, None)))  # a USER message is not a decision card
    other_inv = start(ctx_a, NO_MODEL())
    bad.append((ctx_a, other_inv, reply(first.message_id, first.choices["options"][0]["key"])))  # a card of a different investigation
    for ctx, i, r in bad:
        with pytest.raises(orchestrator.InvalidClarification):
            orchestrator.run_turn(ctx, NO_MODEL(), i, "x", clarification=r)
    inv_b = start(ctx_b, NO_MODEL())
    with pytest.raises(orchestrator.InvalidClarification):  # tenant B cannot answer tenant A's card
        orchestrator.run_turn(ctx_b, NO_MODEL(), inv_b, "x", clarification=reply(first.message_id, first.choices["options"][0]["key"]))
    assert repo.list_findings(a, inv) == [] and repo.list_findings(b, inv_b) == []


def test_a_reference_to_another_tenants_competitor_is_never_used(two_tenants, app_user, seed):  # noqa: F811
    a, b = two_tenants
    (theirs,) = _competitors(a, seed, 1, captured=[NOW])
    ctx_b = ctx_for(b, user_id=app_user)
    rt = runtime(Scripted({}), Grounded())
    inv = start(ctx_b, rt)
    res = orchestrator.run_turn(ctx_b, rt, inv, "compare", ui_action=orchestrator.UiAction(
        "ACTION", "ci.request_price_scenario", {"competitor": "Acme Steel", "amount": "499"}, {"competitor_url_id": str(theirs)}))
    assert res.status == "CLARIFIED" and res.clarify_for == "competitor" and repo.list_findings(b, inv) == []  # A's competitor does not exist for B


def test_a_malformed_reference_is_ignored_not_trusted(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    _competitors(a, seed, 1, captured=[NOW])
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded())
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "compare", ui_action=orchestrator.UiAction(
        "ACTION", "ci.request_price_scenario", {"competitor": "Nobody", "amount": "499"}, {"competitor_url_id": "not-a-uuid"}))
    assert res.status == "CLARIFIED" and res.clarify_for == "competitor"


# --------------------------------------------------------------------------------------------- the period card
def _periods(a):
    for p in ("2026-07-01/2026-07-31", "2026-08-01/2026-08-31", "2026-09-01/2026-09-30", "2026-06-01/2026-06-30"):
        save_metric(a, "NET_REALIZED_REVENUE", period=p, value_paise=100000)


def test_a_missing_period_offers_the_latest_persisted_periods_with_the_newest_recommended(two_tenants, app_user, health_config):  # noqa: F811
    a, _ = two_tenants
    _periods(a)
    ask = "Check my financial health"
    d = decision(route="ACTION", route_key="cfo.financial_health", slots={})
    ctx = ctx_for(a, user_id=app_user)
    inv, res = _card_turn(ctx, runtime(Scripted({ask: d}), Grounded()), ask)
    card = res.choices
    assert res.status == "CLARIFIED" and res.clarify_for == "period" and card["kind"] == "MISSING_INPUT"
    assert [o["label"] for o in card["options"][:3]] == ["September 2026", "August 2026", "July 2026"] and card["options"][0]["kind"] == "RECOMMENDED"
    assert card["options"][0]["reason"] == "Latest period with saved results" and card["options"][-1]["kind"] == "OTHER"
    assert agent_run_repo.list_children(a, repo.get_turn(a, res.turn_id)["agent_run_id"]) == []
    chosen = orchestrator.run_turn(ctx, NO_MODEL(), inv, "September 2026", clarification=orchestrator.ClarificationReply(res.message_id, card["options"][0]["key"]))
    assert chosen.status == "DELIVERED" and chosen.route_key == "cfo.financial_health"


def test_a_missing_period_with_no_saved_results_is_a_plain_question(two_tenants, app_user):
    a, _ = two_tenants
    ask = "Check my financial health"
    ctx = ctx_for(a, user_id=app_user)
    _, res = _card_turn(ctx, runtime(Scripted({ask: decision(route="ACTION", route_key="cfo.financial_health", slots={})}), Grounded()), ask)
    assert res.status == "CLARIFIED" and res.choices is None  # nothing real to offer: no filler card


def test_a_playbook_waiting_for_its_period_resumes_from_the_card(two_tenants, app_user, health_config):  # noqa: F811
    a, _ = two_tenants
    seed_books(a)
    ask = "Why did my profit drop?"
    d = decision(route="PLAYBOOK", route_key="PROFIT_DIAGNOSIS", slots={})
    ctx = ctx_for(a, user_id=app_user)
    inv, res = _card_turn(ctx, runtime(Scripted({ask: d}), Grounded()), ask)
    assert res.clarify_for == "period" and res.choices is not None
    out = orchestrator.run_turn(ctx, NO_MODEL(), inv, "that one", clarification=orchestrator.ClarificationReply(res.message_id, res.choices["options"][0]["key"]))
    assert out.status == "DELIVERED" and out.route == "PLAYBOOK"
    kids = agent_run_repo.list_children(a, repo.get_turn(a, out.turn_id)["agent_run_id"])
    assert sorted(k["trigger_ref"] for k in kids) == ["cfo.anomaly_check", "cfo.financial_health", "cfo.strategic_briefing"]


# --------------------------------------------------------------------------------------------- pure
@pytest.mark.parametrize("period,label", [
    ("2026-09-01/2026-09-30", "September 2026"), ("2026-02-01/2026-02-28", "February 2026"), ("2024-02-01/2024-02-29", "February 2024"),
    ("2026-09-01/2026-09-15", "1 Sep 2026 to 15 Sep 2026"), ("2026-12-01/2027-01-31", "1 Dec 2026 to 31 Jan 2027"),
])
def test_period_labels(period, label):
    assert clarification.period_label(period) == label


def test_resume_action_rejects_what_a_card_cannot_resume():
    card = {"slot": "period", "pending": {"route": "ACTION", "key": "cfo.financial_health", "slots": {}, "refs": {}},
            "options": [{"key": "p", "kind": "RECOMMENDED", "value": "2026-09-01 to 2026-09-30", "refs": {}}, {"key": "other", "kind": "OTHER", "value": None, "refs": {}}]}
    assert clarification.resume_action(card, option_key="p", other_text=None)[2] == {"period": "2026-09-01 to 2026-09-30"}
    assert clarification.resume_action(card, option_key=None, other_text=" last month ")[2] == {"period": "last month"}
    for kwargs in ({"option_key": "other", "other_text": None}, {"option_key": "nope", "other_text": None}, {"option_key": None, "other_text": "  "}, {"option_key": None, "other_text": None}):
        with pytest.raises(ValueError):
            clarification.resume_action(card, **kwargs)
    with pytest.raises(ValueError):
        clarification.resume_action({"slot": None, "pending": {}, "options": []}, option_key=None, other_text="x")


# --------------------------------------------------------------------------------------------- over HTTP
from tests.integration.test_ceo_api import api, clerk, start as api_start  # noqa: E402,F401  (fixtures + helper)


def test_the_api_exposes_the_card_accepts_the_reply_and_refuses_a_forged_one(api, seed):  # noqa: F811
    from backend.api.v1 import ceo as ceo_api
    from backend.main import app

    client, owner, other, a, b = api
    _competitors(a, seed, 3, captured=[NOW, NOW - timedelta(days=2), NOW - timedelta(days=4)])
    app.dependency_overrides[ceo_api.get_runtime] = lambda: runtime(Scripted({ASK_CI: CI}), Grounded())
    inv = api_start(client, owner)
    first = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": ASK_CI}, headers=owner)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "CLARIFIED" and body["clarificationId"] and len(body["choices"]["options"]) == 4
    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=owner).json()
    card_msg = next(m for m in detail["messages"] if m["id"] == body["clarificationId"])
    assert card_msg["kind"] == "CLARIFICATION" and card_msg["choices"]["options"] == body["choices"]["options"]  # a reload shows the same card

    app.dependency_overrides[ceo_api.get_runtime] = lambda: NO_MODEL()  # any model call would fail the turn
    url = f"/api/v1/ceo/investigations/{inv}/turns"
    forged = client.post(url, json={"message": "x", "clarification": {"id": body["clarificationId"], "option": "competitor-nope"}}, headers=owner)
    assert forged.status_code == 422 and forged.json()["detail"]["code"] == "INVALID_CLARIFICATION"
    unknown = client.post(url, json={"message": "x", "clarification": {"id": str(uuid.uuid4()), "option": None}}, headers=owner)
    assert unknown.status_code == 422
    assert client.post(url, json={"message": "x", "clarification": {"id": body["clarificationId"], "option": body["choices"]["options"][0]["key"]}}, headers=other).status_code == 404
    ok = client.post(url, json={"message": "that one", "clarification": {"id": body["clarificationId"], "option": body["choices"]["options"][0]["key"]}}, headers=owner)
    assert ok.status_code == 200 and ok.json()["status"] == "DELIVERED" and ok.json()["routeSource"] == "UI_ACTION"


def test_a_quick_action_may_only_carry_declared_references(api):  # noqa: F811
    client, owner, *_ = api
    inv = api_start(client, owner)
    bad = client.post(f"/api/v1/ceo/investigations/{inv}/turns", headers=owner, json={"message": "x", "action": {
        "kind": "ACTION", "key": "ci.request_price_scenario", "slots": {}, "refs": {"tenant_id": str(uuid.uuid4())}}})
    assert bad.status_code == 422  # only declared reference kinds, and never a tenant id
