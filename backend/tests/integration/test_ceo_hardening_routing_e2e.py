"""Hardening Fix 2 (end to end): the price-scenario and hashtag routing through the real `run_turn`, with a real tracked competitor and spy handlers."""

from __future__ import annotations

from dataclasses import replace

import pytest
from competitor_intelligence.repositories import competitor_url_repo
from competitor_intelligence.types import Marketplace

from backend.ceo import orchestrator
from backend.ceo.registry import ActionRegistry
from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_campaign_routing_e2e import build
from tests.integration.test_ceo_turn import start

pytestmark = pytest.mark.usefixtures("two_tenants")


def go(text, two_tenants, app_user, *, track=True):
    a, _ = two_tenants
    url_id = competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url="https://www.amazon.in/dp/B000TEST01", added_by=app_user, label="Acme") if track else None
    rt, called, _ = build(None)
    seen: list = []

    def capture(slots, c, leg):
        seen.append(slots.model_dump())
        return {"pricePositioning": [], "repricingScenario": None}

    rt = replace(rt, registry=ActionRegistry([replace(s, invoke=capture) if s.key == "ci.request_price_scenario" else s for s in rt.registry.specs()]))
    ctx = ctx_for(a, user_id=app_user)
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), text)
    return a, res, seen, url_id


def test_a_price_scenario_for_a_named_tracked_competitor_runs_the_scenario_action_with_exactly_the_stated_inputs(two_tenants, app_user):
    a, res, seen, url_id = go("Show me a price scenario for Acme at 499", two_tenants, app_user)
    turn = repo.get_turn(a, res.turn_id)
    assert (turn["route"], turn["route_key"]) == ("ACTION", "ci.request_price_scenario") and turn["classifier_result"]["model"] == "rules"
    assert len(seen) == 1 and seen[0]["competitor_url_id"] == url_id and seen[0]["seller_price_paise"] == 49900
    assert res.status == "DELIVERED"


@pytest.mark.parametrize("text,asks", [("Show me the competitor price scenario at 499", "competitor"), ("Show me a price scenario for Acme", "amount")])
def test_missing_essential_inputs_are_asked_for_never_assumed(text, asks, two_tenants, app_user):
    a, res, seen, _ = go(text, two_tenants, app_user)
    assert seen == [] and res.status == "CLARIFIED" and res.clarify_for == asks
    assert repo.get_turn(a, res.turn_id)["route_key"] is None  # nothing was run on a guess


def test_the_saved_competitor_price_list_is_unchanged(two_tenants, app_user):
    a, res, seen, _ = go("What are my competitors charging?", two_tenants, app_user)
    assert seen == [] and repo.get_turn(a, res.turn_id)["route_key"] == "QT_COMPETITORS_PRICES" and res.status == "DELIVERED"


@pytest.mark.parametrize("text", ["Tell me about hashtags.", "What makes a good product hashtag?", "Were those hashtags any good?"])
def test_a_question_about_hashtags_does_not_start_generation_or_claim_approval_is_needed(text, two_tenants, app_user):
    a, _ = two_tenants
    rt, called, _ = build('{"route":"ADVISORY","route_key":null,"slots":{},"needs_agent":null,"clarify_for":null}')
    ctx = ctx_for(a, user_id=app_user)
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), text)
    turn = repo.get_turn(a, res.turn_id)
    assert called == [] and turn["route_key"] != "cmo.generate_hashtags" and "approved first" not in res.answer
    assert "approvalRequiredFor" not in (turn["classifier_result"] or {}) and res.status == "DELIVERED"


@pytest.mark.parametrize("text", ["Generate hashtags for my product.", "Give me 20 hashtags for this product."])
def test_an_explicit_hashtag_request_is_still_stopped_by_the_approval_gate(text, two_tenants, app_user):
    a, _ = two_tenants
    rt, called, _ = build(None)
    ctx = ctx_for(a, user_id=app_user)
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), text)
    assert called == [] and res.status == "DENIED" and repo.get_turn(a, res.turn_id)["classifier_result"]["approvalRequiredFor"] == "cmo.generate_hashtags"
