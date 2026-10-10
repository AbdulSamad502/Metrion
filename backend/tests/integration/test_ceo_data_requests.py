"""Spec 6.37 (C2): when the CFO says what it is missing, the CEO asks for exactly that, saves it only after a confirm card, and runs the same question again.

The CFO leg here behaves like the real one for a missing cost: with no stored cost per unit it opens an `agent_data_request` (cogs_per_unit) and returns its id; once a
cost is stored it returns a normal result. No model is called (the classifier is EMPTY)."""

from __future__ import annotations

import dataclasses
import os

import pytest

from backend.ceo import orchestrator
from backend.ceo.contract import ActionSpec
from backend.ceo.registry import ActionRegistry, get_registry
from backend.services import ceo_reads
from backend.services.cfo_actions import insert_data_request
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_decision_playbooks import PRICE_LEGS, price_inputs
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

UI = orchestrator.UiAction
ASK = "A competitor cut their price, what does it do to me?"


def registry(calls, tenant):
    real, specs = get_registry(), []

    def pricing(slots, ctx, leg):
        calls.setdefault("cfo.pricing", []).append(slots)
        if not ceo_reads.stored_cost(tenant, slots.sku):
            return {"dataRequestId": str(insert_data_request(tenant, requested_field="cogs_per_unit", reason="no cogs_per_unit adjustment", blocking_metric="MARGIN_AT_PRICE"))}
        return {"ok": True}

    for key in PRICE_LEGS:
        r = real.get(key)
        invoke = pricing if key == "cfo.pricing" else (lambda s, ctx, leg, k=key: calls.setdefault(k, []).append(s) or {"ok": True})
        specs.append(ActionSpec(key=key, source=r.source, agent=r.agent, effect=r.effect, description=key, slot_model=r.slot_model, invoke=invoke, fixed_params=r.fixed_params))
    return ActionRegistry(specs)


def setup(a, app_user, seed):  # noqa: F811
    comp = seed.url(a, "Acme Steel")
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = dataclasses.replace(runtime(Scripted({}), Grounded(), registry=registry(calls, a)), max_candidate_prices=5)
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, ASK, ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT", inputs=price_inputs(comp)))
    return ctx, rt, inv, calls, first


def say(ctx, rt, inv, text, *, prev=None, option=None):
    clar = orchestrator.ClarificationReply(prev.message_id, option) if prev is not None else None
    return orchestrator.run_turn(ctx, rt, inv, text or "(chose an option)", clarification=clar)


def test_the_missing_cost_is_asked_for_saved_after_confirm_and_the_same_question_runs_again(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    ctx, rt, inv, calls, first = setup(a, app_user, seed)
    assert first.choices["kind"] == "INPUT" and first.clarify_for == "cost" and "cost per unit for SKU-1" in first.answer  # exactly the missing field, for that product
    assert len(calls["cfo.pricing"]) == 1 and ceo_reads.stored_cost(a, "SKU-1") == []
    bad = say(ctx, rt, inv, "cheap")
    assert bad.clarify_for == "cost" and "amount in rupees" in bad.answer
    card = say(ctx, rt, inv, "300")
    assert card.clarify_for == "confirm" and "₹300.00" in card.answer and ceo_reads.stored_cost(a, "SKU-1") == [] and len(calls["cfo.pricing"]) == 1  # nothing saved or run yet
    done = say(ctx, rt, inv, "yes")
    assert done.status == "DELIVERED" and done.choices is None  # the question ran again and is answered: nothing more is asked
    [stored] = ceo_reads.stored_cost(a, "SKU-1")
    assert stored["value"]["amount_paise"] == 30000
    assert len(calls["cfo.pricing"]) == 2 and calls["cfo.pricing"][1].candidate_prices_paise == calls["cfo.pricing"][0].candidate_prices_paise  # the SAME request, re-validated
    assert any("Saved your cost per unit for SKU-1" in n for n in done.notes)
    assert all(r["status"] != "OPEN" or r["requested_field"] != "cogs_per_unit" for r in __import__("cfo.repositories.agent_data_request_repo", fromlist=["x"]).list_for_tenant(a))


def test_cancel_saves_nothing_and_does_not_run_again(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    ctx, rt, inv, calls, first = setup(a, app_user, seed)
    stopped = say(ctx, rt, inv, "", prev=first, option="cancel")
    assert "Nothing was run" in stopped.answer and ceo_reads.stored_cost(a, "SKU-1") == [] and len(calls["cfo.pricing"]) == 1


def test_a_field_the_ceo_cannot_collect_is_named_not_asked(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    ceo_reads.stored_cost  # noqa: B018
    from backend.services import cfo_actions

    cfo_actions.enter_expense(a, target_type="SKU", target_ref="SKU-1", field="cogs_per_unit", value={"amount_paise": 30000, "effective_from": "2026-01-01"}, created_by=app_user)
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    real = registry(calls, a)

    def other(slots, ctx_, leg):
        calls.setdefault("cfo.pricing", []).append(slots)
        return {"dataRequestId": str(insert_data_request(a, requested_field="rto_outcome", reason="not classified", blocking_metric="MARGIN_AT_PRICE"))}

    specs = [dataclasses.replace(s, invoke=other) if s.key == "cfo.pricing" else s for s in real.specs()]
    rt = dataclasses.replace(runtime(Scripted({}), Grounded(), registry=ActionRegistry(specs)), max_candidate_prices=5)
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), ASK, ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT", inputs=price_inputs(comp)))
    assert res.status == "DELIVERED" and res.choices is None  # not collectable in chat: said in the answer's gaps, no question
