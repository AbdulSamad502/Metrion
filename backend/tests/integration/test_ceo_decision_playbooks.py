"""Spec §6.33: the two decision playbooks run from a form's structured inputs only.

What is proved here: (1) typed chat or a chip never runs them and never reads a number from chat, it offers the form; (2) the form's inputs reach the real CFO / CI
request models exactly (each leg's slots are validated by the SAME models the HTTP routes use), with the stored cost read back by code and every cost carrying its
explicit state; (3) a missing bound (no default), too many prices, a foreign competitor and a malformed form each stop the run with a plain answer and dispatch nothing;
(4) the answer is the deterministic layout, with no model call.
"""

from __future__ import annotations

import dataclasses
import os
import uuid
from datetime import date

import pytest

from backend.ceo import orchestrator
from backend.ceo.contract import ActionSpec
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import investigation_repo as repo
from backend.services import cfo_actions
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, start

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]

PRICE_LEGS = ("ci.request_price_scenario", "cfo.pricing")
PRODUCT_LEGS = ("cfo.landed_cost", "cfo.supplier_ranking", "cfo.batch_size")
ASK_PRICE = "A competitor cut their price, what does it do to me?"
ASK_PRODUCT = "Should I stock this product?"
UI = orchestrator.UiAction


def recording_registry(calls: dict[str, list]):
    """The real registry's slot models (so every leg's slots are validated by the SAME model the HTTP route uses), with a recorder in place of the handler."""
    real, specs = get_registry(), []
    for key in (*PRICE_LEGS, *PRODUCT_LEGS):
        r = real.get(key)
        specs.append(ActionSpec(key=key, source=r.source, agent=r.agent, effect=r.effect, description=key, slot_model=r.slot_model,
                                invoke=lambda s, ctx, leg, k=key: calls.setdefault(k, []).append(s) or {"ok": True}, fixed_params=r.fixed_params))
    return ActionRegistry(specs)


def rt_with(calls, *, max_prices: int | None = 5, classifier: Scripted | None = None):
    rt = runtime(classifier or Scripted({}), Grounded(), registry=recording_registry(calls))
    return dataclasses.replace(rt, max_candidate_prices=max_prices)


def price_inputs(competitor_id, **over):
    base = {
        "competitor_url_id": str(competitor_id), "sku": "SKU-1", "marketplace": "AMAZON", "category": "Home", "fee_type": "referral", "basis": "INCLUSIVE",
        "gst_rate_pct": "18", "current_price_paise": 49900, "candidate_prices_paise": [44900, 47900],
        "shipping": {"state": "NONE_CONFIRMED"}, "advertising": {"state": "UNKNOWN", "reason": "not tracked yet"},
        "return_rto": {"state": "AMOUNT", "amount_paise": 1200}, "other": {"state": "AMOUNT", "amount_paise": 0},
    }
    return {**base, **over}


def save_cogs(tenant, user, paise=30000):
    cfo_actions.enter_expense(tenant, target_type="SKU", target_ref="SKU-1", field="cogs_per_unit", value={"amount_paise": paise, "effective_from": "2026-01-01"}, created_by=user)


def run_price(ctx, rt, inputs, text=ASK_PRICE):
    inv = start(ctx, rt)
    return inv, orchestrator.run_turn(ctx, rt, inv, text, ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT", inputs=inputs))


# ------------------------------------------------------------------------------------------------ price impact
def test_price_impact_sends_the_forms_values_to_the_real_request_models_with_the_stored_cost_read_back(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    save_cogs(a, app_user)
    calls: dict[str, list] = {}
    ctx = ctx_for(a, user_id=app_user)
    inv, res = run_price(ctx, rt_with(calls), price_inputs(comp))
    assert res.status == "DELIVERED" and res.composition_mode == "TEMPLATE"  # the deterministic layout: no model wrote the answer
    [pricing] = calls["cfo.pricing"]
    assert pricing.candidate_prices_paise == [44900, 47900] and pricing.sku == "SKU-1" and pricing.basis == "INCLUSIVE" and pricing.gst_rate_pct == "18"
    assert pricing.cogs_paise == 30000 and pricing.cogs_unavailable_reason is None  # read back from the saved cost, never typed per run
    assert (pricing.shipping_logistics_paise, pricing.advertising_costs_paise, pricing.return_rto_losses_paise, pricing.other_allocated_costs_paise) == (0, None, 1200, 0)
    assert pricing.advertising_costs_unavailable_reason == "not tracked yet"  # "unknown" stays unknown and carries the seller's reason
    assert pricing.as_of_date == date(2026, 10, 1) and len(pricing.active_adjustment_ids) == 1  # the day of the request; the saved cost is cited
    [scenario] = calls["ci.request_price_scenario"]
    assert scenario.competitor_url_id == comp and scenario.seller_price_paise == 49900
    assert any("marked unknown" in n for n in res.notes) and any("Cost per unit taken from your saved cost" in n for n in res.notes)
    turn = repo.get_turn(a, res.turn_id)
    assert turn["classifier_result"]["inputs"]["candidate_prices_paise"] == [44900, 47900]  # the run is auditable: what was entered is recorded with the turn


def test_no_saved_cost_means_the_cost_is_unavailable_not_zero(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    calls: dict[str, list] = {}
    _, res = run_price(ctx_for(a, user_id=app_user), rt_with(calls), price_inputs(comp))
    [pricing] = calls["cfo.pricing"]
    assert pricing.cogs_paise is None and "no cogs_per_unit adjustment" in (pricing.cogs_unavailable_reason or "")
    assert any("No saved cost per unit was found" in n for n in res.notes)


def test_a_missing_candidate_price_bound_refuses_the_run_and_dispatches_nothing(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    calls: dict[str, list] = {}
    _, res = run_price(ctx_for(a, user_id=app_user), rt_with(calls, max_prices=None), price_inputs(comp))
    assert res.status == "FAILED" and "not been configured" in res.answer and calls == {}


def test_more_candidate_prices_than_the_bound_is_refused_in_plain_words(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    calls: dict[str, list] = {}
    _, res = run_price(ctx_for(a, user_id=app_user), rt_with(calls, max_prices=2), price_inputs(comp, candidate_prices_paise=[40000, 41000, 42000]))
    assert res.status == "FAILED" and "at most 2 candidate prices" in res.answer and calls == {}


def test_another_tenants_competitor_is_asked_about_never_used(two_tenants, app_user, seed):  # noqa: F811
    a, b = two_tenants
    theirs = seed.url(b, "Their Rival")
    calls: dict[str, list] = {}
    _, res = run_price(ctx_for(a, user_id=app_user), rt_with(calls), price_inputs(theirs))
    assert res.status == "CLARIFIED" and res.clarify_for == "competitor" and calls == {}


def test_a_cost_with_no_state_is_a_malformed_form_not_a_zero(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    calls: dict[str, list] = {}
    bad = price_inputs(comp)
    del bad["shipping"]
    _, res = run_price(ctx_for(a, user_id=app_user), rt_with(calls), bad)
    assert res.status == "FAILED" and "could not be used" in res.answer and calls == {}


# ------------------------------------------------------------------------------------------------ new product
def product_inputs(**over):
    return {"sku": "SKU-1", "quantity": 100, "period_start": "2026-07-01", "period_end": "2026-09-30", **over}


def test_new_product_reads_the_quote_budget_and_assembled_history_by_code(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict[str, list] = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_with(calls)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK_PRODUCT, ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION", inputs=product_inputs()))
    assert res.status == "DELIVERED" and res.composition_mode == "TEMPLATE" and set(calls) == set(PRODUCT_LEGS)
    [landed] = calls["cfo.landed_cost"]
    assert (landed.sku, landed.supplier_quote_target_type, landed.supplier_quote_target_ref, landed.quantity) == ("SKU-1", "SKU", "SKU-1", 100)  # Q29: quotes live at (SKU, sku)
    [batch] = calls["cfo.batch_size"]
    assert (batch.budget_target_type, batch.budget_target_ref) == ("ACCOUNT", str(a)) and batch.canonical_lines == [] and batch.lines == []  # nothing sold: "never sold", not an error
    assert (batch.period_start, batch.period_end) == (date(2026, 7, 1), date(2026, 9, 30))
    [rank] = calls["cfo.supplier_ranking"]
    assert (rank.sku, rank.quantity) == ("SKU-1", 100)
    assert any("Sales history: 0 lines" in n for n in res.notes)


def test_a_future_history_period_is_refused(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict[str, list] = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_with(calls)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK_PRODUCT, ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION", inputs=product_inputs(period_end="2027-01-01")))
    assert res.status == "FAILED" and "future" in res.answer and calls == {}


def test_a_member_without_the_cfo_permission_cannot_run_the_cfo_legs(two_tenants, app_user):
    a, _ = two_tenants
    from tests.integration.ceo_support import partner_ctx

    calls: dict[str, list] = {}
    ctx = partner_ctx(a, "agent.ceo", "investigation.view", "investigation.create")
    rt = rt_with(calls)
    inv = orchestrator.start_investigation(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK_PRODUCT, ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION", inputs=product_inputs()))
    assert calls == {} and res.status in ("DENIED", "CLARIFIED", "FAILED")  # the choke point refuses; no CFO leg ran


# ------------------------------------------------------------------------------------------------ the real engine, end to end
def test_new_product_end_to_end_on_the_real_engine_shows_labelled_stored_results(two_tenants, app_user):
    a, _ = two_tenants
    cfo_actions.enter_expense(a, target_type="SKU", target_ref="SKU-1", field="supplier.quote", created_by=app_user,
                              value={"supplier_name": "Acme Traders", "unit_cost_paise": 10000, "shipping_paise": 3000, "duties_paise": 5000, "moq": 50, "lead_time_days": 21})
    cfo_actions.enter_expense(a, target_type="ACCOUNT", target_ref=str(a), field="batch.budget", created_by=app_user, value={"amount_paise": 2_000_000})
    ctx = ctx_for(a, user_id=app_user)
    rt = dataclasses.replace(runtime(Scripted({}), Grounded()), max_candidate_prices=5)  # the REAL registry and engine
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK_PRODUCT, ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION", inputs=product_inputs()))
    assert res.status == "DELIVERED" and res.composition_mode == "TEMPLATE"
    # landed cost at 100 units: 10000 + (3000 shipping + 5000 duties) / 100 = 10080 paise, labelled with the supplier it is for
    assert "Landed cost per unit (Acme Traders): ₹100.80" in res.answer
    # batch size is a unit COUNT shown as units, never as rupees: floor(2,000,000 / landed cost at the MOQ reference quantity of 50 = 10160) = 196
    assert "Most units your budget allows: 196 units" in res.answer
    assert "₹196" not in res.answer
    assert {f["action_key"] for f in res.findings if f["source"] == "CFO"} >= {"cfo.landed_cost", "cfo.batch_size", "cfo.supplier_ranking"}


def test_price_impact_end_to_end_on_the_real_engine_labels_each_candidate_and_never_invents_an_unknown_cost(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    seed.snapshot(a, comp, 52000)
    save_cogs(a, app_user)  # 30000 paise per unit
    ctx = ctx_for(a, user_id=app_user)
    rt = dataclasses.replace(runtime(Scripted({}), Grounded()), max_candidate_prices=5)  # the REAL registry and engine
    known = price_inputs(comp, marketplace="meesho", category="*", fee_type="COMMISSION", basis="EXCLUSIVE", gst_rate_pct=None,
                         advertising={"state": "AMOUNT", "amount_paise": 500})
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK_PRICE, ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT", inputs=known))
    assert res.status == "DELIVERED" and res.composition_mode == "TEMPLATE"
    # 0% seeded commission: price - cost 30000 - shipping 0 - ads 500 - return/RTO 1200 - other 0
    assert "Margin if you sell at ₹449.00: ₹132.00" in res.answer and "Margin if you sell at ₹479.00: ₹162.00" in res.answer
    unknown = price_inputs(comp, marketplace="meesho", category="*", fee_type="COMMISSION", basis="EXCLUSIVE", gst_rate_pct=None)  # advertising UNKNOWN
    res2 = orchestrator.run_turn(ctx, rt, inv, ASK_PRICE, ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT", inputs=unknown))
    assert "₹132.00" not in res2.answer and "₹162.00" not in res2.answer  # an unknown cost never produces a margin
    assert "marked unknown" in " ".join(res2.notes)
