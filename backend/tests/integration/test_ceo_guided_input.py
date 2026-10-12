"""Spec 6.34: guided input. The CEO asks for what a decision playbook needs one question at a time; every answer, typed or chosen, is parsed BY CODE against the
one question asked (no model is called: the classifier here is EMPTY and would fail the turn if it were); a bad answer re-asks with the reason and keeps the state;
the same validated inputs as the form (6.33) are built at the end and the playbook runs; cancel stops with nothing run."""

from __future__ import annotations

import dataclasses
import os

import pytest

from backend.ceo import orchestrator
from backend.repositories import investigation_repo as repo
from backend.services import cfo_actions
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_decision_playbooks import recording_registry, save_cogs
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

ASK = "A competitor cut their price"
UI = orchestrator.UiAction


def rt_for(calls, *, classifier=None, max_prices=5):
    rt = runtime(classifier or Scripted({}), Grounded(), registry=recording_registry(calls))  # an EMPTY classifier: any model call would fail the turn
    return dataclasses.replace(rt, max_candidate_prices=max_prices)


def say(ctx, rt, inv, text, *, card=None, option=None):
    clar = orchestrator.ClarificationReply(card, option) if card is not None else None
    return orchestrator.run_turn(ctx, rt, inv, text or "(chose an option)", clarification=clar)  # the real UI sends the option label as the message text


def option_key(res, label):
    return next(o["key"] for o in res.choices["options"] if o["label"] == label)


def test_a_chip_or_typed_chat_starts_a_conversation_about_inputs_not_a_form_and_runs_nothing(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    seed.url(a, "Acme Steel")
    seed.url(a, "Acme Copper")
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls, classifier=Scripted({ASK: decision(route="PLAYBOOK", route_key="COMPETITOR_PRICE_IMPACT")}))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert res.status == "CLARIFIED" and res.clarify_for == "competitor" and calls == {}
    assert res.choices["kind"] == "INPUT" and res.answer.startswith("(1 of 11)") and "Which competitor" in res.answer
    labels = [o["label"] for o in res.choices["options"]]
    assert set(labels[:2]) == {"Acme Copper", "Acme Steel"}  # real tracked competitors, never invented
    assert labels[-2:] == ["Other", "Cancel"] and sum(1 for o in res.choices["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")) <= 3
    chip = orchestrator.run_turn(ctx, rt, start(ctx, rt), "New product", ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION"))
    assert chip.status == "CLARIFIED" and chip.clarify_for == "sku" and chip.answer.startswith("(1 of 8)")


def test_a_bad_answer_is_asked_again_with_the_reason_and_keeps_the_state(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, "New product", ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION"))
    r = orchestrator.run_turn(ctx, rt, inv, "SKU-1")  # a TYPED reply to the open question: it is the answer, no classifier
    assert r.clarify_for == "quantity" and r.answer.startswith("(2 of 8)")
    bad = orchestrator.run_turn(ctx, rt, inv, "a lot")
    assert bad.clarify_for == "quantity" and "whole number above zero" in bad.answer
    assert bad.choices["pending"]["collected"] == {"sku": "SKU-1"}  # nothing was lost or guessed
    good = orchestrator.run_turn(ctx, rt, inv, "200")
    assert good.clarify_for == "window" and good.choices["pending"]["collected"] == {"sku": "SKU-1", "quantity": 200}
    assert calls == {}


def test_the_whole_price_impact_conversation_builds_the_same_inputs_as_the_form_and_runs(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    comp = seed.url(a, "Acme Steel")
    seed.snapshot(a, comp, 52000)
    save_cogs(a, app_user)
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "Price impact", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    res = say(ctx, rt, inv, "Acme Steel")  # 1 competitor, typed
    res = say(ctx, rt, inv, "SKU-1")  # 2 sku
    assert res.clarify_for == "fee"
    res = say(ctx, rt, inv, "", card=res.message_id, option=res.choices["options"][0]["key"])  # 3 fee reference: an option (the seeded fee row)
    assert res.clarify_for == "basis"
    res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "Prices exclude GST"))  # 4 basis: an option
    res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "I do not know"))  # 5 GST unknown: an option
    res = say(ctx, rt, inv, "₹499")  # 6 current price
    res = say(ctx, rt, inv, "449, 479")  # 7 candidates
    assert res.clarify_for == "shipping" and [o["label"] for o in res.choices["options"][:2]] == ["None (0), I confirm", "Unknown"]
    assert [o["label"] for o in res.choices["options"] if o.get("skip")] == ["Unknown"] and any(o["kind"] == "BACK" for o in res.choices["options"])  # only the deliberate "unknown" is skippable
    res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "None (0), I confirm"))  # 8 shipping confirmed zero
    res = say(ctx, rt, inv, "5")  # 9 advertising typed amount
    res = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "Unknown"))  # 10 return/RTO unknown
    res = say(ctx, rt, inv, "0")  # 11 other: a bare zero is refused, it must be confirmed on purpose
    assert res.clarify_for == "other" and "on purpose" in res.answer and calls == {}
    final = say(ctx, rt, inv, "", card=res.message_id, option=option_key(res, "None (0), I confirm"))
    assert final.status == "DELIVERED" and final.composition_mode == "TEMPLATE"
    [pricing] = calls["cfo.pricing"]
    assert pricing.candidate_prices_paise == [44900, 47900] and pricing.cogs_paise == 30000 and pricing.basis == "EXCLUSIVE" and pricing.gst_rate_pct is None
    assert (pricing.shipping_logistics_paise, pricing.advertising_costs_paise, pricing.return_rto_losses_paise, pricing.other_allocated_costs_paise) == (0, 500, None, 0)
    [scenario] = calls["ci.request_price_scenario"]
    assert scenario.competitor_url_id == comp and scenario.seller_price_paise == 49900
    assert repo.get_turn(a, final.turn_id)["classifier_result"]["inputs"]["competitor_url_id"] == str(comp)  # auditable, as for the form


def test_cancel_stops_everything(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    seed.url(a, "Acme Steel")
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, "x", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    stopped = say(ctx, rt, inv, "cancel")
    assert stopped.status == "DELIVERED" and "Nothing was run" in stopped.answer and calls == {}
    r2 = orchestrator.run_turn(ctx, rt, inv, "y", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    stopped2 = say(ctx, rt, inv, "", card=r2.message_id, option="cancel")
    assert "Nothing was run" in stopped2.answer and calls == {}


def test_nothing_to_choose_from_is_said_plainly_and_a_missing_bound_refuses_up_front(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    none_tracked = orchestrator.run_turn(ctx, rt, inv, "x", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    assert none_tracked.choices is None and "No competitors are being tracked" in none_tracked.answer
    seed.url(a, "Acme Steel")
    unbounded = orchestrator.run_turn(ctx, rt_for(calls, max_prices=None), start(ctx, rt), "y", ui_action=UI("PLAYBOOK", "COMPETITOR_PRICE_IMPACT"))
    assert unbounded.status == "FAILED" and "not been configured" in unbounded.answer and calls == {}


def test_new_product_conversation_runs_with_the_collected_inputs(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    cfo_actions.enter_expense(a, target_type="SKU", target_ref="SKU-1", field="supplier.quote", value={"supplier_name": "S", "unit_cost_paise": 20000}, created_by=app_user)
    cfo_actions.enter_expense(a, target_type="ACCOUNT", target_ref=str(a), field="batch.budget", value={"amount_paise": 5000000}, created_by=app_user)  # stored: not asked again (6.36)
    res = orchestrator.run_turn(ctx, rt, inv, "x", ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION"))
    res = say(ctx, rt, inv, "SKU-1")
    res = say(ctx, rt, inv, "200")
    assert [o["label"] for o in res.choices["options"][:3]] == ["Last 90 days", "Last 180 days", "Last 365 days"]
    final = say(ctx, rt, inv, "", card=res.message_id, option=res.choices["options"][0]["key"])
    assert final.status == "DELIVERED" and set(calls) == {"cfo.landed_cost", "cfo.supplier_ranking", "cfo.batch_size"}
    assert calls["cfo.batch_size"][0].period_end.isoformat() == "2026-10-01"  # the chosen window ends on the test clock's day


def test_back_re_asks_the_previous_question_without_a_model_call_and_the_seller_can_answer_it_differently(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, "New product", ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION"))
    assert first.clarify_for == "sku" and all(o["kind"] != "BACK" for o in first.choices["options"])  # nothing to go back to on the first question
    second = say(ctx, rt, inv, "SKU-1")
    assert second.clarify_for == "quantity" and second.choices["pending"]["collected"] == {"sku": "SKU-1"}
    assert [o["key"] for o in second.choices["options"]][-2:] == ["back", "cancel"]
    again = say(ctx, rt, inv, "", card=second.message_id, option="back")
    assert again.clarify_for == "sku" and again.answer.startswith("(1 of 8)") and again.choices["pending"]["collected"] == {}  # the answer is dropped from the session, not guessed
    fixed = say(ctx, rt, inv, "SKU-2")
    assert fixed.clarify_for == "quantity" and fixed.choices["pending"]["collected"] == {"sku": "SKU-2"}
    assert calls == {}


def test_back_removes_only_the_last_answer_by_field_order_not_by_stored_key_order(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls)
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, "New product", ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION"))
    say(ctx, rt, inv, "SKU-1")
    third = say(ctx, rt, inv, "200")
    assert third.clarify_for == "window"
    back = say(ctx, rt, inv, "", card=third.message_id, option="back")
    assert back.clarify_for == "quantity" and back.choices["pending"]["collected"] == {"sku": "SKU-1"}


def test_a_back_reply_on_the_first_question_is_refused_not_ignored(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for({})
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, "New product", ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION"))
    with pytest.raises(orchestrator.InvalidClarification):
        say(ctx, rt, inv, "", card=first.message_id, option="back")


def test_only_options_that_record_unknown_on_purpose_are_flagged_skippable(two_tenants, app_user):
    a, _ = two_tenants
    comp_ctx = ctx_for(a, user_id=app_user)
    rt = rt_for({})
    inv = start(comp_ctx, rt)
    res = orchestrator.run_turn(comp_ctx, rt, inv, "New product", ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION"))
    assert not any(o.get("skip") for o in res.choices["options"])  # the SKU question has nothing that can be skipped
