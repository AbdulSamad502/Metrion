"""Market trends from chat, checkpoint 2 form (ceo-cmo-delegation.md CD11, CD12; supersedes the old spec 6.40 "yes" card). The CEO asks for the marketplace and the niche in the
conversation, saves the niche the seller typed (zero units, the seller's own record), prepares the zero-cost preview of the EXACT searches and puts them on the plan card. Nothing is
sent until the seller presses Approve on that card; a typed "yes" is just text. The run is bound to the preview by its digest; the report is shown quoted and labelled (public web,
not verified, attention not demand). No model is called (the classifier is EMPTY)."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from backend import config
from backend.ceo import approval_run, orchestrator
from backend.ceo.contract import ActionSpec
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import accounting_cutover_repo
from tests.integration.ceo_support import T0, ctx_for
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
    "generationId": "g" * 8 + "-0000-0000-0000-000000000000", "status": "COMPLETE", "reused": False, "unitsBilled": {"cmo": 1, "shared": 1},
    "report": {
        "sections": {
            "MARKET_NEWS": {"state": "COMPLETE", "reason": None, "findings": [{"theme": "Fee changes announced", "summary": "Two outlets report revised referral fees."}]},
            "NICHE": {"state": "UNAVAILABLE", "reason": "no confirmed niche terms", "findings": []},
        },
        "interpretation": {"label": "CMO's interpretation", "items": [{"statement": "Review your referral-fee assumptions."}]},
    },
}


def registry(calls, preview=None, report=None):
    real, specs = get_registry(), []
    outs = {"cmo.market_trends_preview": preview or preview_payload(), "cmo.market_trends": report or REPORT, "cmo.confirm_niche_terms": {"confirmed": [], "suggestions": [], "rejectedCount": 0, "unitsBilled": 0}}
    for k, out in outs.items():
        r = real.get(k)
        specs.append(ActionSpec(key=k, source=r.source, agent=r.agent, effect=r.effect, description=k, slot_model=r.slot_model, writes_own_run=False, required_permissions=r.required_permissions,
                                invoke=lambda s, ctx, leg, k=k, out=out: calls.setdefault(k, []).append(s) or out, fixed_params=r.fixed_params, effects=r.effects))
    return ActionRegistry(specs)


@pytest.fixture(autouse=True)
def _gates(monkeypatch):
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: T0 - timedelta(days=1))  # the CEO unit rule is in effect, as after migration 0017
    for k in ("TAVILY_API_KEY", "YOUTUBE_API_KEY"):
        monkeypatch.setenv(k, "test-key")
    for fn in (config.tavily_api_key, config.youtube_api_key):
        fn.cache_clear()
    yield
    for fn in (config.tavily_api_key, config.youtube_api_key):
        fn.cache_clear()


def say(ctx, rt, inv, text, *, prev=None, option=None):
    clar = orchestrator.ClarificationReply(prev.message_id, option) if prev is not None else None
    return orchestrator.run_turn(ctx, rt, inv, text or "(chose an option)", clarification=clar)


def test_the_niche_is_asked_in_chat_the_exact_searches_go_on_the_plan_card_and_nothing_runs_until_approved(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    inv = start(ctx, rt)
    q = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert q.status == "CLARIFIED" and q.clarify_for == "news_kind" and calls == {}  # one A/B/C choice first
    assert say(ctx, rt, inv, "a").clarify_for == "niche"  # no stored niche: asked IN CHAT (CD12)
    planned = say(ctx, rt, inv, "steel water bottle, insulated flask")
    assert planned.status == "PLANNED" and planned.plan_id is not None
    assert set(calls) == {"cmo.confirm_niche_terms", "cmo.market_trends_preview"}  # only the zero-unit record and the zero-cost preview ran: nothing was sent
    assert calls["cmo.confirm_niche_terms"][0].new_terms == ["steel water bottle", "insulated flask"]
    from backend.repositories import investigation_plan_repo as plan_repo

    row = plan_repo.get(a, inv, planned.plan_id)
    card = row["plan"]["summary_text"]
    assert "“amazon india seller news this month”" in card and "Exact searches that will be sent" in card and "1 CMO unit and 1 shared market-research unit" in card
    assert row["plan"]["legs"][0]["slots"]["plan_digest"] == DIGEST and "niche" not in row["plan"]["legs"][0]["slots"]  # the run is bound to the preview the seller saw
    again = say(ctx, rt, inv, "yes")  # a typed yes is just text: it approves nothing
    assert "cmo.market_trends" not in calls and plan_repo.get(a, inv, planned.plan_id)["status"] in ("AWAITING_APPROVAL", "SUPERSEDED") and again.plan_id is None
    done = approval_run.approve_plan(ctx, rt, inv, planned.plan_id, row["plan_hash"])
    assert done.result is not None and done.result.status == "DELIVERED"
    [run] = calls["cmo.market_trends"]
    assert run.plan_digest == DIGEST and run.request_key == f"ceo-plan-{planned.plan_id}" and [m.value for m in run.marketplaces] == [] and [x.value for x in run.sections] == ["NICHE"]
    ans = done.result.answer
    assert "Market trends: Marketplace news" in ans and "Fee changes announced" in ans and "not verified" in ans and "Written by Slim CMO" in ans
    assert "What the CMO makes of it" in ans and "Your niche: no confirmed niche terms" in ans  # a section that could not be built is a named gap
    assert "Slim CMO dashboard" in ans and "market-trend report" in ans


def test_cancel_runs_nothing(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    inv = start(ctx, rt)
    card = orchestrator.run_turn(ctx, rt, inv, ASK)
    stopped = say(ctx, rt, inv, "", prev=card, option="cancel")
    assert "Nothing was run" in stopped.answer and calls == {}


def test_the_marketplace_is_asked_when_not_given_and_nothing_to_search_is_said_plainly(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls, preview=preview_payload(queries=False)))
    inv = start(ctx, rt)
    q = orchestrator.run_turn(ctx, rt, inv, "show me the market trends")
    assert q.clarify_for == "news_kind" and calls == {}
    q2 = say(ctx, rt, inv, "c")
    assert q2.clarify_for == "niche"
    res = say(ctx, rt, inv, "skip")
    assert res.status == "FAILED" and "nothing to research" in res.answer and "cmo.market_trends" not in calls and res.plan_id is None


NEWS_REPORT = {
    **REPORT,
    "report": {
        "sections": {"MARKET_NEWS": {"state": "COMPLETE", "reason": None, "findings": [{
            "theme": "Fee changes announced", "summary": "Two outlets report revised referral fees.",
            "sources": [{"url": "https://news.example/fees", "title": "Fee change", "published_at": "2026-10-09T08:00:00+00:00"}, {"url": "https://news.example/undated", "title": "", "published_at": None}]}]}},
        "interpretation": {"items": []},
    },
}


def test_a_news_request_is_market_research_not_general_advice_and_every_item_shows_its_source_and_date(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls, report=NEWS_REPORT))  # the classifier is empty: the explicit rule routes it
    inv = start(ctx, rt)
    q = orchestrator.run_turn(ctx, rt, inv, "tell me the current news of the ecommerce")
    assert q.status == "CLARIFIED" and q.choices["pending"]["key"] == "cmo.market_trends" and calls == {}  # it started the market-research questions, not a general answer
    q = say(ctx, rt, inv, "c")
    assert q.clarify_for == "niche"  # the niche is asked in chat (a stored one is offered as a choice)
    planned = say(ctx, rt, inv, "steel water bottle")
    assert planned.status == "PLANNED" and "cmo.market_trends" not in calls
    from backend.repositories import investigation_plan_repo as plan_repo

    row = plan_repo.get(a, inv, planned.plan_id)
    assert any("searches" in l for l in row["plan"]["compact_lines"]) and len(row["plan"]["compact_lines"]) <= 5  # compact card; the exact queries are under Details
    assert "“amazon india seller news this month”" in row["plan"]["summary_text"]
    done = approval_run.approve_plan(ctx, rt, inv, planned.plan_id, row["plan_hash"])
    ans = done.result.answer
    assert "Fee change - https://news.example/fees (published 2026-10-09)" in ans and "https://news.example/undated (published date not given)" in ans


def test_without_the_search_keys_a_news_request_says_plainly_what_is_missing_and_runs_nothing(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    calls: dict = {}
    monkeypatch.setenv("TAVILY_API_KEY", "")
    config.tavily_api_key.cache_clear()
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, "latest news in ecommerce")
    say(ctx, rt, inv, "c")
    res = say(ctx, rt, inv, "steel water bottle")
    assert res.plan_id is None and "Tavily" in res.answer and "not set up on this server" in res.answer and "nothing was used up" in res.answer
    assert "cmo.market_trends" not in calls
