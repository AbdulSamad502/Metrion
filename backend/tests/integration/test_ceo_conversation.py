"""Conversation quality, found in the owner's first real session (2026-10-10):

* a plain statement about the business is acknowledged and remembered, with no model call (and no "safety check" notice);
* a short answer to the CEO's plain question resumes the task that asked it (instead of being routed as a brand-new, unrelated message), while a question or a long
  message is still routed normally;
* the "general advice" line is written by code after the answer, never placed by the model;
* Product Intelligence results show names and plain limits only: no internal labels, no developer notes, no foreign footers."""

from __future__ import annotations

import os

import pytest

from backend.ceo import orchestrator
from backend.ceo.contract import ActionSpec
from backend.ceo.registry import ActionRegistry, get_registry
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]


def reg(calls, keys=("cfo.reconcile",)):
    real, specs = get_registry(), []
    for k in keys:
        r = real.get(k)
        specs.append(ActionSpec(key=k, source=r.source, agent=r.agent, effect=r.effect, description=k, slot_model=r.slot_model, writes_own_run=False,
                                invoke=lambda s, ctx, leg, k=k: calls.setdefault(k, []).append(s) or {"ok": True}, fixed_params=r.fixed_params))
    return ActionRegistry(specs)


def test_a_plain_statement_is_acknowledged_and_remembered_with_no_model_and_no_safety_notice(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    comp = Grounded()
    rt = runtime(Scripted({}), comp)  # an EMPTY classifier: any model call would fail the turn
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), "my business name is Zyquora")
    assert res.status == "DELIVERED" and res.composition_mode is None and comp.calls == 0
    assert res.answer.startswith("Noted.") and "I'll remember your business name: Zyquora" in res.answer


def test_a_short_answer_to_a_plain_question_resumes_the_task_that_asked(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    msg = "check what the marketplace paid me for september"
    rt = runtime(Scripted({msg: decision(route="ACTION", route_key="cfo.reconcile", slots={"period": "September"})}), Grounded(), registry=reg(calls))
    inv = start(ctx, rt)
    q = orchestrator.run_turn(ctx, rt, inv, msg)
    assert q.status == "CLARIFIED" and q.clarify_for == "marketplace" and calls == {}
    done = orchestrator.run_turn(ctx, rt, inv, "Amazon")  # "Amazon" alone is not a request: it answers the question that was asked
    [slots] = calls["cfo.reconcile"]
    assert done.status == "DELIVERED" and str(getattr(slots.marketplace, "value", slots.marketplace)) == "AMAZON" and str(slots.period_start).startswith("2026-09")  # the earlier period was kept


def test_a_question_or_a_long_message_is_a_new_request_not_an_answer(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    msg, other = "check what the marketplace paid me for september", "how do I price a new product for my shop?"
    cls = Scripted({msg: decision(route="ACTION", route_key="cfo.reconcile", slots={"period": "September"}), other: decision(route="ADVISORY")})
    rt = runtime(cls, Grounded(), registry=reg(calls))
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, msg)
    res = orchestrator.run_turn(ctx, rt, inv, other)
    assert calls == {} and res.route == "ADVISORY" and cls.calls == 1  # the general-question rule routes it (no model call); it is not swallowed as the marketplace


def test_the_general_advice_line_is_written_by_code_after_the_answer(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    q = "what should I focus on this month"
    comp = Grounded()
    rt = runtime(Scripted({q: decision(route="ADVISORY")}), comp)
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), q)
    assert res.answer.rstrip().endswith("This is general advice, not derived from your data.")
    assert "{{" not in res.answer and not any("GENERAL_GUIDANCE" in p for p in comp.prompts)  # the model was never asked to place it


@pytest.mark.usefixtures("approval_gate_bypassed")
def test_pi_results_show_names_and_plain_limits_only(two_tenants, app_user):
    from tests.integration.test_ceo_pi_chat import ASK, registry as pi_registry, run_through

    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    base = pi_registry(calls)
    # PI's own developer-facing notes, as it really returns them
    report = base.get("pi.report")
    spec = ActionSpec(key="pi.report", source=report.source, agent=report.agent, effect=report.effect, description="r", slot_model=report.slot_model, writes_own_run=False, fixed_params=report.fixed_params,
                      invoke=lambda s, c, leg: {"runId": s.run_id.hex, "status": "COMPLETE", "candidates": [{"candidate": {"candidate_title": "Hypercushion 01", "opportunity_label": "CANDIDATE_OPPORTUNITY"}}],
                                                "unavailable": [{"field": "marketplace_price_and_competition", "reason": "no marketplace-side integration exists in V1 (Amazon PA-API deprecated)"},
                                                                {"field": "demand_signal", "reason": "Google Ads API access pending brand verification"}]})
    rt = runtime(Scripted({}), Grounded(), registry=ActionRegistry([base.get("pi.discover"), spec]))
    inv = start(ctx, rt)
    res = run_through(ctx, rt, inv, ["20000", "Amazon", "skip", "yes"])
    assert "Hypercushion 01" in res.answer and "Here is what Product Intelligence found for your niche." in res.answer
    for internal in ("candidate opportunity", "PA-API", "Google Ads", "Written by the specialist", "V1"):
        assert internal not in res.answer, internal
    assert "not been checked against live marketplace listings" in res.answer and "Real sales and demand numbers are not available" in res.answer


@pytest.mark.usefixtures("approval_gate_bypassed")
def test_the_seller_can_follow_up_on_a_numbered_idea_and_the_next_agent_works_on_it(two_tenants, app_user):
    """The agents are connected through the conversation: PI lists ideas, then "write titles for #2" sends THAT idea to CMO (and "GST rate for #1" would send it to the
    lookup). The substitution is told to the seller and only happens when the list exists and the number is in range."""
    from tests.integration.test_ceo_pi_chat import registry as pi_registry, run_through
    from tests.integration.test_ceo_cmo_chat import registry as cmo_registry

    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    both = ActionRegistry([*pi_registry(calls).specs(), *cmo_registry(calls).specs()])
    rt = runtime(Scripted({}), Grounded(), registry=both)
    inv = start(ctx, rt)
    found = run_through(ctx, rt, inv, ["20000", "Amazon", "skip", "yes"])
    assert "Leather Formal Shoes" in found.answer and "write titles for #2" in found.answer  # how to continue is said
    q = orchestrator.run_turn(ctx, rt, inv, "write titles for #2")
    assert "Taking #2 as “Leather Formal Shoes”" in q.answer and q.choices["pending"]["collected"] == {"product_name": "Leather Formal Shoes"}
    assert q.choices["pending"]["key"] == "cmo.generate_title_sets"
    orchestrator.run_turn(ctx, rt, inv, "skip")  # category
    res = orchestrator.run_turn(ctx, rt, inv, "Amazon")
    while res.status == "CLARIFIED" and str(res.clarify_for).startswith("fact_"):  # the skippable extra details (brand, size, features...)
        res = orchestrator.run_turn(ctx, rt, inv, "skip")
    [slots] = calls["cmo.generate_title_sets"]
    assert slots.product_name == "Leather Formal Shoes"
    out_of_range = orchestrator.run_turn(ctx, rt, inv, "write titles for #99")
    assert "Taking #99" not in out_of_range.answer  # nothing is guessed: it is asked about like any other request


def test_the_same_fact_again_is_acknowledged_not_sent_to_the_model(two_tenants, app_user):
    """The owner's first live run: repeating "my business name is X" fell through to the classifier and produced a confusing answer."""
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded())  # an EMPTY classifier: any model call fails the turn
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, "my business name is Zyquora")
    again = orchestrator.run_turn(ctx, rt, inv, "my business name is Zyquora")
    assert "I'll remember your business name: Zyquora" in first.answer
    assert again.status == "DELIVERED" and "I already have your business name: Zyquora" in again.answer

