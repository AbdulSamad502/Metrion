"""Spec 6.40 (C5): CMO market trends from chat. The CEO first prepares the zero-cost preview and shows the EXACT outbound searches; nothing is sent until the seller says
yes; the run is bound to the preview by its digest; cancel runs nothing; the report is shown quoted and labelled (public web, not verified, attention not demand). No model
is called (the classifier is EMPTY)."""

from __future__ import annotations

import os

import pytest

from backend.ceo import orchestrator
from backend.ceo.contract import ActionSpec
from backend.ceo.registry import ActionRegistry, get_registry
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

DIGEST = "a" * 64
ASK = "what are the market trends in my niche on Amazon?"


def preview_payload(queries=True):
    return {
        "digest": DIGEST, "sections": ["MARKET_NEWS"], "marketplaces": ["AMAZON"],
        "queries": [{"section": "MARKET_NEWS", "provider": "TAVILY", "query": "amazon india seller news this month"}] if queries else [],
        "unavailableSections": {"NICHE": "no confirmed niche terms", "ADJACENT": "no confirmed niche terms"}, "unresearchedTerms": [], "skippedByBudget": [], "budget": {},
    }


REPORT = {
    "generationId": "g", "status": "COMPLETE", "reused": False, "unitsBilled": {"cmo": 1, "shared": 1},
    "report": {
        "sections": {
            "MARKET_NEWS": {"state": "COMPLETE", "reason": None, "findings": [{"theme": "Fee changes announced", "summary": "Two outlets report revised referral fees."}]},
            "NICHE": {"state": "UNAVAILABLE", "reason": "no confirmed niche terms", "findings": []},
        },
        "interpretation": {"label": "CMO's interpretation", "items": [{"statement": "Review your referral-fee assumptions."}]},
    },
}


def registry(calls, preview=None):
    real, specs = get_registry(), []
    outs = {"cmo.market_trends_preview": preview or preview_payload(), "cmo.market_trends": REPORT}
    for k, out in outs.items():
        r = real.get(k)
        specs.append(ActionSpec(key=k, source=r.source, agent=r.agent, effect=r.effect, description=k, slot_model=r.slot_model, writes_own_run=False, required_permissions=r.required_permissions,
                                invoke=lambda s, ctx, leg, k=k, out=out: calls.setdefault(k, []).append(s) or out, fixed_params=r.fixed_params))
    return ActionRegistry(specs)


def say(ctx, rt, inv, text, *, prev=None, option=None):
    clar = orchestrator.ClarificationReply(prev.message_id, option) if prev is not None else None
    return orchestrator.run_turn(ctx, rt, inv, text or "(chose an option)", clarification=clar)


def test_the_exact_searches_are_shown_first_and_nothing_runs_until_the_seller_confirms(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    inv = start(ctx, rt)
    card = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert card.status == "CLARIFIED" and card.choices["kind"] == "INPUT" and card.clarify_for == "confirm"
    assert "“amazon india seller news this month”" in card.answer and "Not covered" in card.answer and "one market-research run" in card.answer
    assert set(calls) == {"cmo.market_trends_preview"}  # only the preview ran: nothing was sent
    done = say(ctx, rt, inv, "yes")
    assert done.status == "DELIVERED" and done.composition_mode == "TEMPLATE"
    [run] = calls["cmo.market_trends"]
    assert run.plan_digest == DIGEST and run.request_key.startswith("ceo-") and [m.value for m in run.marketplaces] == ["AMAZON"]  # bound to the preview the seller saw
    assert "Market trends: Marketplace news" in done.answer and "Fee changes announced" in done.answer and "not verified" in done.answer
    assert "What the CMO makes of it" in done.answer and "Your niche: no confirmed niche terms" in done.answer  # a section that could not be built is a named gap


def test_cancel_runs_nothing(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    inv = start(ctx, rt)
    card = orchestrator.run_turn(ctx, rt, inv, ASK)
    stopped = say(ctx, rt, inv, "", prev=card, option="cancel")
    assert "Nothing was run" in stopped.answer and "cmo.market_trends" not in calls


def test_the_marketplace_is_asked_when_not_given_and_nothing_to_search_is_said_plainly(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls, preview=preview_payload(queries=False)))
    inv = start(ctx, rt)
    q = orchestrator.run_turn(ctx, rt, inv, "show me the market trends")
    assert q.clarify_for == "marketplaces" and calls == {}
    res = say(ctx, rt, inv, "skip")
    assert res.status == "FAILED" and "confirm your niche terms" in res.answer and "cmo.market_trends" not in calls
