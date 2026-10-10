"""Spec 6.35: product discovery from chat. "Top trending products, my niche is mens shoes" is recognised by an explicit rule (the classifier here is EMPTY and would fail
the turn if it were asked), the CEO asks for what Product Intelligence needs one question at a time, shows a summary, and only after the seller says yes saves the
research brief and runs the REAL registered actions (slots validated by PI's own request models). The candidates are read back from what the run saved and shown quoted,
labelled as unverified web findings. Also: a general question is answered, not met with "which area?"; a cancelled or detached flow writes and runs nothing.

The PI handlers are recorders returning payloads shaped like the real ones (test doubles); the research itself is covered by the PI tests."""

from __future__ import annotations

import dataclasses
import os
from uuid import uuid4

import pytest

from backend.ceo import orchestrator
from backend.ceo.contract import ActionSpec
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import investigation_repo as repo
from backend.services import pi_actions
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

RUN_ID = str(uuid4())
ASK = "ok now i want the top trending products to sell my nich is mens shoes"


def registry(calls):
    real = get_registry()
    discover = {"runId": RUN_ID, "agentRunId": str(uuid4()), "status": "COMPLETE", "candidateIds": [], "shortlistedCandidateIds": [], "partialReason": None, "failedReason": None}
    report = {"runId": RUN_ID, "status": "COMPLETE", "unavailable": [{"field": "demand_signal", "reason": "Google Ads API access pending brand verification"}],
              "candidates": [{"candidate": {"candidate_title": "Men's Running Shoes Lightweight", "opportunity_label": "RISING"}}, {"candidate": {"candidate_title": "Leather Formal Shoes"}}]}
    specs = []
    for k, out in (("pi.discover", discover), ("pi.report", report)):
        r = real.get(k)
        specs.append(ActionSpec(key=k, source=r.source, agent=r.agent, effect=r.effect, description=k, slot_model=r.slot_model, writes_own_run=False,
                                invoke=lambda s, ctx, leg, k=k, out=out: calls.setdefault(k, []).append(s) or out, fixed_params=r.fixed_params))
    return ActionRegistry(specs)


def rt_for(calls, classifier=None):
    return runtime(classifier or Scripted({}), Grounded(), registry=registry(calls))


def run_through(ctx, rt, inv, answers):
    res = orchestrator.run_turn(ctx, rt, inv, ASK)
    for a in answers:
        res = orchestrator.run_turn(ctx, rt, inv, a)
    return res


def test_the_niche_is_taken_from_the_message_and_only_the_rest_is_asked(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    q = orchestrator.run_turn(ctx, rt, start(ctx, rt), ASK)
    assert q.status == "CLARIFIED" and calls == {} and "budget" in q.answer.lower() and q.answer.startswith("(2 of 6)")  # the niche was already said
    assert q.choices["pending"]["collected"] == {"category": "mens shoes"} and q.choices["pending"]["key"] == "pi.discover"


def test_after_the_seller_confirms_the_brief_is_saved_pi_runs_and_the_ideas_are_shown_as_unverified(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    res = run_through(ctx, rt, inv, ["20,000", "Amazon", "skip", "quick"])
    assert res.status == "CLARIFIED" and "Shall I go ahead" in res.answer and "mens shoes" in res.answer and calls == {} and pi_actions.list_niche_briefs(a) == []  # nothing saved or run yet
    done = orchestrator.run_turn(ctx, rt, inv, "yes")
    assert done.status == "DELIVERED" and done.composition_mode == "TEMPLATE"
    [brief] = pi_actions.list_niche_briefs(a)
    assert brief["status"] == "READY" and brief["category_text"] == "mens shoes" and brief["budget_paise"] == 2000000 and list(brief["marketplaces"]) == ["AMAZON"]
    [slots] = calls["pi.discover"]
    assert str(slots.niche_brief_id) == str(brief["id"]) and slots.depth == "SHALLOW"
    [rep] = calls["pi.report"]
    assert str(rep.run_id) == RUN_ID
    assert "Men's Running Shoes Lightweight" in done.answer and "not verified" in done.answer and "Leather Formal Shoes" in done.answer
    assert "Real sales and demand numbers are not available" in done.answer and "Google Ads" not in done.answer  # the limit is said in plain words, not as PI's developer note
    [pi_finding] = [f for f in done.findings if f["action_key"] == "pi.report"]
    assert pi_finding["presentation"]["figures"] == [] and pi_finding["presentation"]["artefacts"][0]["items"][0].startswith("Men's Running Shoes")


def test_cancelling_at_the_summary_saves_and_runs_nothing(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    run_through(ctx, rt, inv, ["20000", "Amazon", "skip", "quick"])
    res = orchestrator.run_turn(ctx, rt, inv, "cancel")
    assert "stopped" in res.answer and calls == {} and pi_actions.list_niche_briefs(a) == []


def test_answering_the_same_confirmation_twice_reuses_the_brief(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    q = run_through(ctx, rt, inv, ["20000", "Amazon", "skip", "quick"])
    reply = orchestrator.ClarificationReply(q.message_id, None)
    orchestrator.run_turn(ctx, rt, inv, "yes", clarification=reply)
    orchestrator.run_turn(ctx, rt, inv, "yes", clarification=reply)
    assert len(pi_actions.list_niche_briefs(a)) == 1  # one saved brief, not two


def test_a_detached_pi_cannot_be_run_and_nothing_is_asked_or_saved(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    repo.set_agent_attachment(a, inv, "PI", attached=False, changed_by=app_user, now=NOW)
    res = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert calls == {} and res.choices is None and pi_actions.list_niche_briefs(a) == []


def test_a_general_question_is_answered_not_met_with_which_area(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    q = "WHAT IS MY BUSINESS NAME ?"
    comp = Grounded()
    rt = dataclasses.replace(runtime(Scripted({q: decision(route="CLARIFY", clarify_for="WHICH_AGENT", needs_agent="CMO")}), comp, registry=registry({})), composer=comp.model())
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), q)
    assert res.route == "ADVISORY" and res.status == "DELIVERED" and res.choices is None
    assert "cannot answer this from chat yet" not in res.answer and "No seller goal" not in res.answer  # no invented refusals or noise
