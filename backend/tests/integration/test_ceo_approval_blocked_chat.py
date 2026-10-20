"""D-8 (chat execution safety): the six approval-required actions that chat used to reach (pi.discover, cmo.market_trends, cmo.generate_title_sets,
cmo.generate_hashtags, cmo.generate_description, cmo.generate_keywords) are NOT run from chat without a stored approval plan.

CHECKPOINT 2 (ceo-cmo-delegation.md) CHANGE: the five CMO actions no longer get the blanket refusal. From chat they are classified, the missing inputs are collected through the
bounded loop, and a stored approval plan is created for the seller to approve on its card; nothing runs until the approve call (tests/integration/test_ceo_cmo_delegation.py).
Product Intelligence (`pi.discover`) keeps this refusal exactly as it was while CEO_APPROVAL_ENABLED is off. The `dispatch()` backstop still refuses ALL six when called without
an approval grant, which is what the last section proves.

A confirmation card (pi.discover, cmo.market_trends) or a completed input session (the four cmo.generate_* actions) is an in-conversation answer; by decision C3 it is
NOT approval. Two layers are proved here: the orchestrator refuses on the decision, before any question, save, preview or dispatch (every way of arriving at the decision);
and `dispatch()` itself refuses any action whose registry metadata says it needs approval (the backstop). A refusal runs no handler, so it calls no provider and records no usage.

This does NOT implement approval and does not make these paths compliant with it: it only closes them. Unrelated actions are unchanged (last tests)."""

from __future__ import annotations

import dataclasses
import os
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from backend.ceo import orchestrator
from backend.ceo.contract import Denial, LegStatus
from backend.ceo.dispatch import dispatch, open_turn
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import agent_run_repo, investigation_repo as repo
from backend.services import pi_actions
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for
from tests.integration.test_ceo_dispatch_integration import _open
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, MSG_PROFIT, PROFIT, Scripted, decision, fake_registry, runtime, start
from tests.integration.test_ceo_unit_billing import HEALTH_OK

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SIX = ("pi.discover", "cmo.market_trends", "cmo.generate_title_sets", "cmo.generate_hashtags", "cmo.generate_description", "cmo.generate_keywords")
REFUSED_IN_CHAT = ("pi.discover",)  # the CMO five go to a plan card instead (checkpoint 2)
PREVIEW = {"digest": "a" * 64, "sections": ["MARKET_NEWS"], "marketplaces": ["AMAZON"], "queries": [{"section": "MARKET_NEWS", "provider": "TAVILY", "query": "amazon india seller news"}],
           "unavailableSections": {}, "unresearchedTerms": [], "skippedByBudget": [], "budget": {}}


def recording_registry(calls: dict) -> ActionRegistry:
    """The REAL specs (so their R1 effects metadata is attached) with every handler replaced by a recorder: a call here means a provider would have been reached."""
    real = get_registry()
    specs = []
    for k in (*SIX, "cmo.market_trends_preview", "pi.report"):
        r = real.get(k)
        out = PREVIEW if k == "cmo.market_trends_preview" else {}
        specs.append(dataclasses.replace(r, invoke=lambda s, ctx, leg, k=k, out=out: calls.setdefault(k, []).append(s) or out, entitlement=None))
    return ActionRegistry(specs)


def side_effects(tenant):
    """Everything a run would leave behind: leg rows, findings (via the investigation), usage events, saved briefs, agent memory."""
    with tenant_scope(tenant) as conn:
        runs = [r[0] for r in conn.execute(text("SELECT trigger_ref FROM agent_run ORDER BY started_at"))]
        usage = [tuple(r) for r in conn.execute(text("SELECT agent_code, event_kind, quantity FROM metered_event"))]
        memory = conn.execute(text("SELECT count(*) FROM agent_memory")).scalar()
    return runs, usage, memory, pi_actions.list_niche_briefs(tenant)


def assert_refused(res, tenant, inv, calls, *, remembered_niche=False):
    assert res.status == "DENIED" and res.route == "ADVISORY" and res.answer.startswith(orchestrator.APPROVAL_UNAVAILABLE_TEXT)
    if not remembered_niche:
        assert res.answer == orchestrator.APPROVAL_UNAVAILABLE_TEXT
    assert res.clarify_for is None and not res.choices  # no question, no card
    assert calls == {}, "a handler ran: a provider could have been reached"
    runs, usage, memory, briefs = side_effects(tenant)
    assert runs == ["ceo.chat_turn"], runs  # the CEO anchor only: no leg row
    # the CEO's own, separate "remember what the seller says about their business" feature may note a stated niche; the refused action itself saves nothing
    assert usage == [] and memory == (1 if remembered_niche else 0) and briefs == []  # no usage event (not even the CEO unit), no saved brief
    assert repo.list_findings(tenant, inv) == []
    turn = repo.get_turn(tenant, res.turn_id)
    assert turn["status"] == "DENIED" and turn["classifier_result"]["effectiveRoute"] == "ADVISORY"
    assert (turn.get("safety_result") or {}).get("billing", {}).get("ceoUnit") != "DUE"


@contextmanager
def refusal_off(monkeypatch):
    """Switch the orchestrator refusal off for a SETUP step only (a conversation that was started before this rule existed); it is restored on exit."""
    with monkeypatch.context() as m:
        m.setattr(orchestrator, "plan_required", lambda keys: False)
        yield


# ------------------------------------------------------------------------------------------------ every way of arriving at the decision (the agents still refused in chat)
@pytest.mark.parametrize("key", REFUSED_IN_CHAT)
def test_a_classifier_decision_for_each_of_the_six_is_refused_before_anything_is_asked_or_run(two_tenants, app_user, key):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    text_in = f"please run {key}"
    rt = runtime(Scripted({text_in: decision(route="ACTION", route_key=key, slots={})}), Grounded(), registry=recording_registry(calls))
    inv = start(ctx, rt)
    assert_refused(orchestrator.run_turn(ctx, rt, inv, text_in), a, inv, calls)


@pytest.mark.parametrize("key", REFUSED_IN_CHAT)
def test_a_chip_or_ui_action_for_each_of_the_six_is_refused_the_same_way(two_tenants, app_user, key):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=recording_registry(calls))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "run it", ui_action=orchestrator.UiAction("ACTION", key))
    assert_refused(res, a, inv, calls)


@pytest.mark.parametrize("text_in", ["ok now i want the top trending products to sell my nich is mens shoes"])
def test_the_explicit_intent_rules_are_stopped_too_with_no_model_called(two_tenants, app_user, text_in):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=recording_registry(calls))  # an EMPTY classifier would fail the turn if it were asked
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, text_in)
    assert_refused(res, a, inv, calls, remembered_niche="my nich is" in text_in)


# ------------------------------------------------------------------------------------------------ flows already in progress: a card / completed session is not approval
def test_pi_discover_the_confirmation_card_is_not_approval_nothing_is_saved_or_run(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=recording_registry(calls))
    inv = start(ctx, rt)
    ask = "ok now i want the top trending products to sell my nich is mens shoes"
    with refusal_off(monkeypatch):  # a conversation that reached the summary card before this rule
        res = orchestrator.run_turn(ctx, rt, inv, ask)
        for answer in ("20,000", "Amazon", "skip"):
            res = orchestrator.run_turn(ctx, rt, inv, answer)
        assert "Shall I go ahead" in res.answer and calls == {} and pi_actions.list_niche_briefs(a) == []
    before = side_effects(a)
    answered = orchestrator.run_turn(ctx, rt, inv, "yes", clarification=orchestrator.ClarificationReply(res.message_id, None))  # "Yes, run it"
    assert answered.status == "DENIED" and answered.answer == orchestrator.APPROVAL_UNAVAILABLE_TEXT
    runs, usage, memory, briefs = side_effects(a)
    assert calls == {} and briefs == [] and usage == [] and memory == before[2]  # no brief, no PI memory note, no run, no usage
    assert "pi.discover" not in runs and "pi.report" not in runs


@pytest.mark.parametrize("key,text_in", [
    ("cmo.generate_hashtags", "give me hashtags for my steel water bottle"), ("cmo.generate_description", "write a product description for my steel water bottle"),
    ("cmo.generate_keywords", "write search keywords for my steel water bottle"), ("cmo.generate_title_sets", "write listing titles for my steel water bottle"),
    ("cmo.market_trends", "what are the market trends in my niche on Amazon?"),
])
def test_the_cmo_actions_are_no_longer_refused_they_start_the_question_loop_and_nothing_runs(two_tenants, app_user, key, text_in):
    """Checkpoint 2: the seller is ASKED what the CMO needs (no blanket refusal), and asking runs, sends and meters nothing."""
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=recording_registry(calls))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, text_in)
    assert res.status == "CLARIFIED" and res.choices["kind"] == "INPUT" and res.choices["delegation"]["questionCount"] == 1
    assert res.answer != orchestrator.APPROVAL_UNAVAILABLE_TEXT and calls == {}
    runs, usage, memory, briefs = side_effects(a)
    assert usage == [] and key not in runs


# ------------------------------------------------------------------------------------------------ the backstop: dispatch() itself
@pytest.mark.parametrize("key", SIX)
def test_dispatch_refuses_each_of_the_six_even_when_called_directly(two_tenants, app_user, key):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    inv, turn = _open(a, app_user, ctx)
    leg = dispatch(turn, key, None, registry=recording_registry(calls), attached=frozenset(ALL_AGENTS), now=T0)
    assert leg.status is LegStatus.DENIED and leg.denial is Denial.APPROVAL_REQUIRED and leg.payload is None and "approval required" in (leg.reason or "")
    assert calls == {}, "the handler ran"
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert child["trigger_ref"] == key and child["status"] == "DENIED" and child["error_reason"].startswith("approval required")  # audited like any refusal
    runs, usage, memory, briefs = side_effects(a)
    assert usage == []


def test_dispatch_decides_from_the_registry_metadata_not_from_a_second_list():
    """Every registered action is refused by dispatch iff its own R1 metadata says it requires approval; the six chat actions are among them."""
    flagged = {s.key for s in get_registry().specs() if s.effects is not None and s.effects.requires_approval}
    assert set(SIX) <= flagged
    for s in get_registry().specs():
        if s.key not in flagged:
            assert s.effects is not None and not s.effects.meters  # an unflagged action is never metered, so this rule never touches it


# ------------------------------------------------------------------------------------------------ unrelated chat keeps working
def test_a_playbook_with_no_approval_required_leg_still_runs_and_is_billed_as_before(two_tenants, app_user, monkeypatch):
    from backend.repositories import accounting_cutover_repo
    from datetime import timedelta

    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: T0 - timedelta(days=1))
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=fake_registry({"cfo.financial_health": lambda: HEALTH_OK, "cfo.anomaly_check": lambda: {"methods": []}, "cfo.strategic_briefing": lambda: {"signals": []}}))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    assert res.status == "DELIVERED" and res.outcome == "SUCCEEDED"
    runs, usage, memory, briefs = side_effects(a)
    assert usage == [("CEO", "ceo.chat_turn", 1)]  # the ordinary CEO unit, exactly as before
    assert {"cfo.financial_health", "cfo.anomaly_check", "cfo.strategic_briefing"} <= {f["action_key"] for f in repo.list_findings(a, inv)}


def test_an_unflagged_action_is_not_blocked_by_dispatch(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv, turn = _open(a, app_user, ctx)
    leg = dispatch(turn, "cfo.financial_health", {"period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-01"}, now=T0)
    assert leg.status is LegStatus.COMPLETE and leg.denial is None
