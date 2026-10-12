"""R2 end to end against a real Postgres: the CEO unit under CEO_UNIT_RULE_2.

INVARIANT: any failed required leg => no CEO unit, even when an optional leg succeeded; the decision is stored once with the turn; only the call that
finalised the turn writes the usage event. Legacy turns (before the cut-over) keep the old behaviour untouched."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import timedelta

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from backend import entitlement
from backend.ceo import orchestrator
from backend.ceo.contract import ActionSpec, AgentCode, Effect
from backend.ceo.registry import ActionRegistry
from backend.repositories import accounting_cutover_repo, investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import T0, ctx_for
from tests.integration.test_ceo_turn import Grounded, MSG_PROFIT, PROFIT, Scripted, decision, fake_registry, runtime, start

pytestmark = pytest.mark.usefixtures("two_tenants")

HEALTH_OK = {"overallBand": "GOOD", "perMetricBands": {}, "engineResultRefs": [], "unavailableReason": None}


@pytest.fixture
def rule2(monkeypatch):
    """CEO_UNIT_RULE_2 in effect for every turn the suite's fake clock creates (T0 is 2026-10-01; the real cut-over is the migration time)."""
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: T0 - timedelta(days=1))


def units(tenant):
    with tenant_scope(tenant) as conn:
        return [tuple(r) for r in conn.execute(text("SELECT agent_code, event_kind, quantity FROM metered_event ORDER BY occurred_at"))]


def billing(tenant, turn_id):
    return (repo.get_turn(tenant, turn_id).get("safety_result") or {}).get("billing")


def boom():
    raise RuntimeError("boom")


def profit_turn(a, app_user, handlers, *, message=MSG_PROFIT, script=PROFIT):
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({message: script}), Grounded(), registry=fake_registry(handlers))
    inv = start(ctx, rt)
    return ctx, rt, inv, orchestrator.run_turn(ctx, rt, inv, message)


def test_a_required_leg_that_raised_means_no_unit_even_though_the_answer_was_delivered(two_tenants, app_user, rule2):
    a, _ = two_tenants
    _, _, _, res = profit_turn(a, app_user, {"cfo.financial_health": boom, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
    assert res.status == "DELIVERED" and res.outcome == "FAILED"  # the answer names the gap; the execution did not succeed
    assert units(a) == []
    assert billing(a, res.turn_id) == {"rule": 2, "ceoUnit": "NOT_DUE", "reason": "REQUIRED_LEG_FAILED", "outcome": "FAILED"}


def test_a_failed_required_leg_is_not_rescued_by_successful_optional_legs_and_the_optional_results_are_still_returned(two_tenants, app_user, rule2):
    a, _ = two_tenants
    _, _, inv, res = profit_turn(a, app_user, {"cfo.financial_health": boom, "cfo.anomaly_check": lambda: {"methods": []}, "cfo.strategic_briefing": lambda: {"signals": []}})
    assert units(a) == []
    done = {f["action_key"]: f["status"] for f in repo.list_findings(a, inv, turn_id=res.turn_id)}
    assert done["cfo.anomaly_check"] == "COMPLETE" and done["cfo.strategic_briefing"] == "COMPLETE"  # returned, with the failure represented


def test_all_required_legs_ok_and_an_optional_failure_is_one_unit_with_a_partial_outcome(two_tenants, app_user, rule2):
    a, _ = two_tenants
    _, _, _, res = profit_turn(a, app_user, {"cfo.financial_health": lambda: HEALTH_OK, "cfo.anomaly_check": boom, "cfo.strategic_briefing": lambda: {"signals": []}})
    assert res.status == "DELIVERED" and res.outcome == "PARTIAL"
    assert units(a) == [("CEO", "ceo.chat_turn", 1)]
    assert billing(a, res.turn_id)["ceoUnit"] == "DUE"


def test_full_success_is_exactly_one_unit(two_tenants, app_user, rule2):
    a, _ = two_tenants
    _, _, _, res = profit_turn(a, app_user, {"cfo.financial_health": lambda: HEALTH_OK, "cfo.anomaly_check": lambda: {"methods": []}, "cfo.strategic_briefing": lambda: {"signals": []}})
    assert res.outcome == "SUCCEEDED" and units(a) == [("CEO", "ceo.chat_turn", 1)]


def test_a_required_leg_waiting_for_the_seller_is_pending_input_and_is_not_charged(two_tenants, app_user, rule2):  # F6
    a, _ = two_tenants
    _, _, _, res = profit_turn(a, app_user, {"cfo.financial_health": lambda: {"dataRequestId": "req-1"}, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
    assert res.status == "DELIVERED" and res.outcome == "PENDING_INPUT"
    assert units(a) == [] and billing(a, res.turn_id)["reason"] == "REQUIRED_LEG_PENDING_INPUT"


class _MarketSlots(BaseModel):
    model_config = {"extra": "forbid"}
    period_start: str
    period_end: str
    as_of_date: str
    marketplace: str


def _two_required_registry(cash, reconcile):
    return ActionRegistry([
        ActionSpec(key=k, source="CFO", agent=AgentCode.CFO, effect=Effect.READ, description=k, slot_model=_MarketSlots, invoke=lambda s, c, l, fn=fn: fn())
        for k, fn in (("cfo.cash_reconciliation", cash), ("cfo.reconcile", reconcile))
    ])


def test_when_one_of_two_required_legs_fails_there_is_no_unit(two_tenants, app_user, rule2):
    a, _ = two_tenants
    msg = "Am I being paid what I am owed on Amazon in September?"
    script = decision(route="PLAYBOOK", route_key="CASH_AND_LEAK_CHECK", slots={"marketplace": "AMAZON", "period": "September"})
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({msg: script}), Grounded(), registry=_two_required_registry(lambda: {"cashReceived": {}}, boom))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, msg)
    assert res.status == "DELIVERED" and res.outcome == "FAILED" and units(a) == []
    ok = runtime(Scripted({msg: script}), Grounded(), registry=_two_required_registry(lambda: {"cashReceived": {}}, lambda: {"leaks": []}))
    inv2 = start(ctx, ok)
    assert orchestrator.run_turn(ctx, ok, inv2, msg).outcome == "SUCCEEDED"
    assert units(a) == [("CEO", "ceo.chat_turn", 1)]


def test_a_delivered_informational_answer_from_saved_data_keeps_its_charge_even_when_the_data_is_not_available_yet(two_tenants, app_user, rule2):  # F7
    a, _ = two_tenants
    msg = "How did last month go?"
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({msg: decision(route="BUSINESS_STATE", route_key="BS_PNL_LATEST")}), Grounded(), registry=fake_registry({}))
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), msg)
    assert res.status == "DELIVERED" and res.route == "BUSINESS_STATE" and res.outcome == "SUCCEEDED"
    assert units(a) == [("CEO", "ceo.chat_turn", 1)] and billing(a, res.turn_id)["reason"] == "NO_LEGS"


def test_a_delivered_out_of_scope_explanation_is_chargeable_and_marked_declined(two_tenants, app_user, rule2):  # F2
    a, _ = two_tenants
    msg = "Publish this listing on Amazon for me"
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({msg: decision(route="OUT_OF_SCOPE")}), Grounded(), registry=fake_registry({}))
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), msg)
    assert res.status == "DELIVERED" and res.outcome == "DECLINED"
    assert units(a) == [("CEO", "ceo.chat_turn", 1)] and billing(a, res.turn_id)["reason"] == "OUT_OF_SCOPE_DELIVERED"


def test_clarified_and_failed_turns_are_never_charged(two_tenants, app_user, rule2):
    a, _ = two_tenants
    msg = "Why did my profit drop last quarter?"
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({msg: decision(route="PLAYBOOK", route_key="PROFIT_DIAGNOSIS", slots={"period": "last quarter"})}), Grounded(), registry=fake_registry({}))
    clarified = orchestrator.run_turn(ctx, rt, start(ctx, rt), msg)
    assert clarified.status == "CLARIFIED" and billing(a, clarified.turn_id)["reason"] == "TURN_NOT_DELIVERED"
    unconfigured = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=fake_registry({"cfo.financial_health": lambda: HEALTH_OK}), leg_timeout=None)
    failed = orchestrator.run_turn(ctx, unconfigured, start(ctx, unconfigured), MSG_PROFIT)
    assert failed.status == "FAILED" and billing(a, failed.turn_id)["ceoUnit"] == "NOT_DUE"
    assert units(a) == []


def test_the_decision_is_stored_once_and_only_the_finalising_call_may_charge(two_tenants, app_user, rule2):
    a, _ = two_tenants
    _, _, _, res = profit_turn(a, app_user, {"cfo.financial_health": lambda: HEALTH_OK, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
    before = repo.get_turn(a, res.turn_id)
    again = repo.finalise_turn(a, res.turn_id, status="FAILED", billing={"rule": 2, "ceoUnit": "NOT_DUE", "reason": "X", "outcome": "FAILED"}, completed_at=T0)
    assert again is False  # a replay / race / recovery cannot finalise a second time, store a second decision or charge
    after = repo.get_turn(a, res.turn_id)
    assert (after["status"], after["safety_result"]) == (before["status"], before["safety_result"])
    assert units(a) == [("CEO", "ceo.chat_turn", 1)]


def test_a_metering_write_failure_never_blocks_the_answer_and_the_stored_decision_survives_for_repair(two_tenants, app_user, rule2, monkeypatch):
    a, _ = two_tenants
    monkeypatch.setattr(orchestrator, "meter_ceo_turn", lambda *args, **kw: None)  # the write "failed" (record_metered_event returns None)
    _, _, _, res = profit_turn(a, app_user, {"cfo.financial_health": lambda: HEALTH_OK, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
    assert res.status == "DELIVERED" and units(a) == []
    assert billing(a, res.turn_id)["ceoUnit"] == "DUE"  # a repair (R5, blocked on the staleness evidence) can rely on this and nothing else
    # the repair primitive is idempotent: repeated and concurrent writes for the same turn make exactly one event
    threads = [threading.Thread(target=entitlement.meter_ceo_turn, args=(a,), kwargs={"member_id": app_user, "turn_id": res.turn_id}) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    entitlement.meter_ceo_turn(a, member_id=app_user, turn_id=res.turn_id)
    assert units(a) == [("CEO", "ceo.chat_turn", 1)]


def test_legacy_turns_before_the_cutover_keep_the_old_behaviour_exactly(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: T0 + timedelta(days=1))  # the rule starts AFTER this turn
    _, _, _, res = profit_turn(a, app_user, {"cfo.financial_health": boom, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
    assert res.status == "DELIVERED" and res.outcome is None
    assert units(a) == [("CEO", "ceo.chat_turn", 1)]  # the old rule: a delivered turn is a unit; no refund, no re-evaluation
    assert billing(a, res.turn_id) is None  # and no decision is stored for a legacy turn


def test_without_a_cutover_row_the_rule_is_not_in_effect(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: None)
    _, _, _, res = profit_turn(a, app_user, {"cfo.financial_health": boom, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
    assert units(a) == [("CEO", "ceo.chat_turn", 1)] and billing(a, res.turn_id) is None


def test_the_investigation_detail_exposes_the_outcome_of_each_turn(two_tenants, app_user, rule2):
    a, _ = two_tenants
    ctx, _, inv, res = profit_turn(a, app_user, {"cfo.financial_health": boom, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})

    from backend.api.v1 import ceo as ceo_api

    body = ceo_api.get_investigation(inv, ctx)
    assert [t["outcome"] for t in body["turns"]] == ["FAILED"]


def test_a_process_killed_after_finalisation_but_before_the_usage_write_leaves_a_stored_decision_and_no_charge(two_tenants, app_user, rule2):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=fake_registry({}))
    inv = start(ctx, rt)
    child = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "ceo_billing_child.py"), str(a), str(app_user), str(inv)],
        capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), "..", ".."), env={**os.environ}, timeout=180,
    )
    assert child.returncode == 137, child.stdout + child.stderr
    [turn] = repo.list_turns(a, inv)
    assert turn["status"] == "DELIVERED" and turn["safety_result"]["billing"]["ceoUnit"] == "DUE"
    assert units(a) == []  # killed before the write: under-metered until a repair exists (R5), never over-charged
