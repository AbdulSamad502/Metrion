"""Spec 6.36 (C1): "is <idea> worth stocking?" from chat. The CEO asks for the supplier quote and budget ONLY when none is stored, shows a confirm card that says exactly
what will be saved, saves through the CFO's own write path only after "yes", and then the real engine legs run. Cancel saves nothing; a member who may not write saves
nothing and nothing runs; no model is called anywhere (the classifier here is EMPTY and would fail the turn if it were)."""

from __future__ import annotations

import dataclasses
import os

import pytest

from backend.auth.permissions import AGENT_CEO, AGENT_CFO, INVESTIGATION_CREATE, INVESTIGATION_VIEW
from backend.ceo import orchestrator
from backend.services import ceo_reads, cfo_actions
from tests.integration.ceo_support import ctx_for, partner_ctx
from tests.integration.test_ceo_decision_playbooks import PRODUCT_LEGS, recording_registry
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

ASK = "is Leather Formal Shoes worth stocking?"


def rt_for(calls):
    return dataclasses.replace(runtime(Scripted({}), Grounded(), registry=recording_registry(calls)), max_candidate_prices=5)


def say(ctx, rt, inv, text, *, prev=None, option=None):
    clar = orchestrator.ClarificationReply(prev.message_id, option) if prev is not None else None
    return orchestrator.run_turn(ctx, rt, inv, text or "(chose an option)", clarification=clar)


def key_of(res, label):
    return next(o["key"] for o in res.choices["options"] if o["label"] == label)


def ask_through_to_confirm(ctx, rt, inv):
    res = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert res.clarify_for == "quantity" and res.choices["pending"]["collected"] == {"sku": "Leather Formal Shoes"}  # the idea's name was taken as the product
    res = say(ctx, rt, inv, "200")
    res = say(ctx, rt, inv, "", prev=res, option=key_of(res, "Last 90 days"))
    assert res.clarify_for == "supplier_name"
    res = say(ctx, rt, inv, "Sunrise Traders")
    res = say(ctx, rt, inv, "250")
    res = say(ctx, rt, inv, "5000")  # order shipping
    assert res.clarify_for == "moq"  # live run 2026-10-14: a never-sold product's batch size needs the MOQ or the lead time, so both are asked (each skippable)
    res = say(ctx, rt, inv, "50")
    assert res.clarify_for == "lead_time_days"
    res = say(ctx, rt, inv, "21")
    assert res.clarify_for == "budget"
    res = say(ctx, rt, inv, "1,00,000")
    assert res.clarify_for == "confirm"
    return res


def test_nothing_is_saved_or_run_until_the_seller_confirms_and_then_the_real_legs_run(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    card = ask_through_to_confirm(ctx, rt, inv)
    assert "Sunrise Traders" in card.answer and "₹250.00 per unit" in card.answer and "₹100,000.00" in card.answer  # the card says exactly what will be saved
    assert ceo_reads.stored_quotes(a, "Leather Formal Shoes") == [] and ceo_reads.stored_budget(a) == [] and calls == {}  # asking saved and ran nothing
    done = say(ctx, rt, inv, "yes")
    assert done.status == "DELIVERED" and set(calls) == set(PRODUCT_LEGS) and done.composition_mode == "TEMPLATE"
    [quote] = ceo_reads.stored_quotes(a, "Leather Formal Shoes")
    assert quote["value"]["unit_cost_paise"] == 25000 and quote["value"]["shipping_paise"] == 500000 and quote["value"]["supplier_name"] == "Sunrise Traders"
    assert quote["value"]["moq"] == 50 and quote["value"]["lead_time_days"] == 21  # the supplier's own terms, as the seller stated them
    [budget] = ceo_reads.stored_budget(a)
    assert budget["value"]["amount_paise"] == 10000000
    [landed] = calls["cfo.landed_cost"]
    assert (landed.sku, landed.supplier_quote_target_ref, landed.quantity) == ("Leather Formal Shoes", "Leather Formal Shoes", 200)
    assert any("Saved the supplier quote from Sunrise Traders" in n for n in done.notes)


def test_cancel_at_the_confirm_card_saves_nothing_and_runs_nothing(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    card = ask_through_to_confirm(ctx, rt, inv)
    stopped = say(ctx, rt, inv, "", prev=card, option="cancel")
    assert "Nothing was run" in stopped.answer and calls == {}
    assert ceo_reads.stored_quotes(a, "Leather Formal Shoes") == [] and ceo_reads.stored_budget(a) == []


def test_a_stored_quote_and_budget_are_used_not_asked_for_and_not_overwritten(two_tenants, app_user):
    a, _ = two_tenants
    cfo_actions.enter_expense(a, target_type="SKU", target_ref="Leather Formal Shoes", field="supplier.quote", value={"supplier_name": "Old Co", "unit_cost_paise": 20000}, created_by=app_user)
    cfo_actions.enter_expense(a, target_type="ACCOUNT", target_ref=str(a), field="batch.budget", value={"amount_paise": 5000000}, created_by=app_user)
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK)
    res = say(ctx, rt, inv, "200")
    assert res.clarify_for == "window" and res.answer.startswith("(3 of 3)")  # nothing else is asked
    done = say(ctx, rt, inv, "", prev=res, option=key_of(res, "Last 90 days"))
    assert done.status == "DELIVERED" and set(calls) == set(PRODUCT_LEGS)
    [quote] = ceo_reads.stored_quotes(a, "Leather Formal Shoes")
    assert quote["value"]["supplier_name"] == "Old Co"


def test_a_member_who_may_not_write_saves_nothing_and_nothing_runs(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = partner_ctx(a, AGENT_CEO, AGENT_CFO, INVESTIGATION_VIEW, INVESTIGATION_CREATE)
    ctx = dataclasses.replace(ctx, app_user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    card = ask_through_to_confirm(ctx, rt, inv)
    res = say(ctx, rt, inv, "yes")
    assert "permission" in res.answer and calls == {}
    assert ceo_reads.stored_quotes(a, "Leather Formal Shoes") == [] and ceo_reads.stored_budget(a) == []


def test_a_bad_amount_is_asked_again_never_guessed(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for({})
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK)
    res = say(ctx, rt, inv, "200")
    res = say(ctx, rt, inv, "", prev=res, option=key_of(res, "Last 90 days"))
    res = say(ctx, rt, inv, "Sunrise Traders")
    bad = say(ctx, rt, inv, "cheap")
    assert bad.clarify_for == "unit_cost" and "amount in rupees" in bad.answer
    assert bad.choices["pending"]["collected"]["supplier_name"] == "Sunrise Traders"
