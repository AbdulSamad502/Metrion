"""The hard leg deadline (`CEO_LEG_ABANDON_SECONDS`, `ceo/deadlines.py`): a leg that hangs inside a LIVE process is eventually settled, honestly, without being mistaken for a dead process
and without ever being re-run.

Layers: (1) SOFT deadline `CEO_LEG_TIMEOUT_SECONDS` - the turn answers without a slow leg and names it (now also for a turn with ONE leg); the leg keeps running and its finding lands as
before. (2) HARD deadline - a still-open leg of an already-answered turn is settled FAILED with a distinct reason: `TIMED_OUT_REPEATABLE` (only reads/computes saved data: asking again is
safe) or `TIMED_OUT_UNCERTAIN` (outside call, meter, or a recorded choice: it may still be running or may already have had its effect; never re-run automatically). (3) process death -
unchanged: ownership-based recovery (`INTERRUPTED`).

Evidence labels. SIMULATED: a handler that blocks on an event stands in for a hung external call, and crafted rows stand in for an old leg (a thread cannot be killed, so a real multi-minute hang
is not reproduced). PROCESS DEATH: a real child process is killed mid-leg. No test here calls a model or an external service."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from backend.ceo import deadlines, orchestrator, recovery
from backend.ceo.dispatch import open_turn
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import agent_run_repo, investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for
from tests.integration.test_ceo_campaign_routing_e2e import build
from tests.integration.test_ceo_turn import MSG_PROFIT, Scripted, fake_registry, runtime, start

pytestmark = pytest.mark.usefixtures("two_tenants")

GST = "What GST rate applies to steel water bottles?"
HARD = 600
PAST = T0 - timedelta(minutes=30)


@pytest.fixture(autouse=True)
def _deadlines(monkeypatch):
    monkeypatch.setenv("CEO_LEG_ABANDON_SECONDS", str(HARD))
    monkeypatch.delenv("CEO_LEG_TIMEOUT_SECONDS", raising=False)


def hung_turn(tenant, user, handler, *, soft=1):
    """A real turn through the orchestrator whose single GST leg is `handler`. Returns (ctx, runtime, calls, investigation)."""
    rt, called, _ = build(None)
    rt = replace(rt, registry=ActionRegistry([replace(s, invoke=handler) if s.key == "cfo.gst_lookup" else s for s in rt.registry.specs()]), leg_timeout_seconds=soft)
    ctx = ctx_for(tenant, user_id=user)
    return ctx, rt, called, start(ctx, rt)


def legs(tenant, inv):
    with tenant_scope(tenant) as conn:
        return [dict(r._mapping) for r in conn.execute(text("SELECT id, status, error_reason, started_at, finished_at FROM agent_run WHERE investigation_id = :i AND trigger_ref = 'cfo.gst_lookup' ORDER BY started_at"), {"i": str(inv)})]


def findings(tenant, inv):
    return [(f["action_key"], f["status"], f["gap_reason"]) for f in repo.list_findings(tenant, inv)]


def notes(tenant, inv):
    return [m["content"] for m in repo.list_messages(tenant, inv) if m["kind"] == "SYSTEM_NOTE"]


def overdue(tenant, inv):
    """`now` far enough past the oldest open leg to be beyond the hard deadline."""
    return min(l["started_at"] for l in repo.list_late_legs(tenant, inv)) + timedelta(seconds=HARD)


class Hang:
    """SIMULATED hung external call: blocks until released, counts how many times it was invoked."""

    def __init__(self):
        self.entered, self.release, self.calls = threading.Event(), threading.Event(), []

    def __call__(self, slots, c, leg):
        self.calls.append(1)
        self.entered.set()
        self.release.wait(timeout=30)
        return {"result": None, "noMatch": None}


# ------------------------------------------------------------------------------------------------ the classification
def test_every_registered_action_is_classified_and_anything_with_an_outside_effect_is_uncertain():
    reg = get_registry()
    by = {s.key: deadlines.classify(s) for s in reg.specs()}
    repeatable = {k for k, v in by.items() if v is deadlines.LegClass.REPEATABLE}
    assert {"cfo.financial_health", "cfo.anomaly_check", "cfo.strategic_briefing", "pi.report"} <= repeatable
    assert "ci.discover_competitors" not in repeatable  # it sends the seller search terms to Tavily (CI spec C34): an outside call is never assumed repeatable
    for k in ("ci.discover_competitors", "cfo.gst_lookup", "service.gst_lookup", "cfo.period_comparison", "pi.discover", "pi.supplier_lookup", "cmo.market_trends", "cmo.generate_title_sets", "cmo.generate_hashtags"):
        assert by[k] is deadlines.LegClass.UNCERTAIN, k  # outside call, model call or metered artefact
    for k in ("cmo.approve_title", "cmo.confirm_image_hint", "cmo.confirm_niche_terms"):
        assert by[k] is deadlines.LegClass.UNCERTAIN, k  # records a seller choice: whether it was recorded is exactly what is unknown
    assert deadlines.classify(None) is deadlines.LegClass.UNCERTAIN
    assert deadlines.classify(replace(reg.get("cfo.financial_health"), effects=None)) is deadlines.LegClass.UNCERTAIN  # unclassified: never assumed harmless


# ------------------------------------------------------------------------------------------------ soft deadline: a live slow leg is not a dead one
def test_simulated_a_leg_that_finishes_before_its_deadline_is_untouched(two_tenants, app_user):
    a, _ = two_tenants
    ctx, rt, called, inv = hung_turn(a, app_user, lambda slots, c, leg: {"result": None, "noMatch": None}, soft=30)
    res = orchestrator.run_turn(ctx, rt, inv, GST)
    assert res.status == "DELIVERED" and [l["status"] for l in legs(a, inv)] == ["COMPLETE"]
    assert deadlines.settle_overdue_legs_locked(a, inv, now=T0 + timedelta(days=30), registry=rt.registry).settled == 0
    assert [l["status"] for l in legs(a, inv)] == ["COMPLETE"]


def test_simulated_a_single_slow_leg_no_longer_holds_the_turn_open_and_is_named_not_failed(two_tenants, app_user):
    """Before: a turn with ONE leg ran it inline with no deadline at all (the turn, its lock and the HTTP request hung with it)."""
    a, _ = two_tenants
    h = Hang()
    ctx, rt, called, inv = hung_turn(a, app_user, h, soft=1)
    res = orchestrator.run_turn(ctx, rt, inv, GST)  # returns after the soft deadline although the leg is still blocked
    assert h.entered.is_set() and not h.release.is_set()
    assert "still running" in res.answer
    assert [l["status"] for l in legs(a, inv)] == ["RUNNING"]  # a slow leg in a live process stays RUNNING
    assert deadlines.settle_overdue_legs_locked(a, inv, now=overdue(a, inv) - timedelta(seconds=1), registry=rt.registry).settled == 0  # inside the hard deadline: untouched
    h.release.set()


def test_simulated_a_late_result_inside_the_hard_deadline_lands_as_before(two_tenants, app_user):
    a, _ = two_tenants
    h = Hang()
    ctx, rt, called, inv = hung_turn(a, app_user, h, soft=1)
    orchestrator.run_turn(ctx, rt, inv, GST)
    h.release.set()
    for _ in range(100):
        if legs(a, inv)[0]["status"] != "RUNNING":
            break
        threading.Event().wait(0.1)
    assert [l["status"] for l in legs(a, inv)] == ["COMPLETE"] and [f[1] for f in findings(a, inv)] == ["COMPLETE"]


# ------------------------------------------------------------------------------------------------ hard deadline
def test_simulated_a_leg_past_the_hard_deadline_with_an_outside_effect_is_settled_as_uncertain_and_never_rerun(two_tenants, app_user):
    a, _ = two_tenants
    h = Hang()
    ctx, rt, called, inv = hung_turn(a, app_user, h, soft=1)
    orchestrator.run_turn(ctx, rt, inv, GST)
    rep = deadlines.settle_overdue_legs_locked(a, inv, now=overdue(a, inv), registry=rt.registry)
    assert (rep.uncertain, rep.repeatable) == (1, 0)
    [leg] = legs(a, inv)
    assert leg["status"] == "FAILED" and leg["error_reason"].startswith("TIMED_OUT_UNCERTAIN") and "not run again" in leg["error_reason"]
    assert [f for f in findings(a, inv) if f[0] == "cfo.gst_lookup"] == [("cfo.gst_lookup", "FAILED", leg["error_reason"])]
    [note] = notes(a, inv)
    assert "may still be running" in note and "already have done its work" in note and "I have not run it again" in note
    assert "did not happen" not in note and "nothing happened" not in note.lower()  # never claims the effect did not occur
    assert len(h.calls) == 1  # nothing re-invoked it
    h.release.set()


def test_simulated_a_repeatable_leg_past_the_hard_deadline_is_settled_as_safe_to_ask_again(two_tenants, app_user):
    a, _ = two_tenants
    inv, anchor, run = craft_late_leg(a, app_user, "cfo.financial_health", "CFO")
    rep = deadlines.settle_overdue_legs_locked(a, inv, now=PAST + timedelta(seconds=HARD), registry=get_registry())
    assert (rep.repeatable, rep.uncertain) == (1, 0)
    got = agent_run_repo.get_run(a, run)
    assert got["status"] == "FAILED" and got["error_reason"].startswith("TIMED_OUT_REPEATABLE") and "safe to ask again" in notes(a, inv)[0]


def test_simulated_an_unknown_action_is_treated_as_uncertain(two_tenants, app_user):
    a, _ = two_tenants
    inv, anchor, run = craft_late_leg(a, app_user, "somebody.new_action", "CFO")
    rep = deadlines.settle_overdue_legs_locked(a, inv, now=PAST + timedelta(seconds=HARD), registry=get_registry())
    assert (rep.repeatable, rep.uncertain) == (0, 1)


def test_nothing_is_ever_settled_by_age_unless_a_hard_deadline_is_configured(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    monkeypatch.delenv("CEO_LEG_ABANDON_SECONDS", raising=False)
    inv, anchor, run = craft_late_leg(a, app_user, "cfo.financial_health", "CFO")
    assert deadlines.effective_abandon_seconds() is None
    assert deadlines.settle_overdue_legs_locked(a, inv, now=T0 + timedelta(days=365), registry=get_registry()).settled == 0
    assert recovery.recover_investigation(a, inv, now=T0 + timedelta(days=365)).legs_timed_out == 0
    assert agent_run_repo.get_run(a, run)["status"] == "RUNNING"


def test_the_hard_deadline_is_never_shorter_than_the_soft_deadline(monkeypatch):
    monkeypatch.setenv("CEO_LEG_ABANDON_SECONDS", "10")
    monkeypatch.setenv("CEO_LEG_TIMEOUT_SECONDS", "90")
    assert deadlines.effective_abandon_seconds() == 90
    monkeypatch.setenv("CEO_LEG_ABANDON_SECONDS", "900")
    assert deadlines.effective_abandon_seconds() == 900


# ------------------------------------------------------------------------------------------------ late results and races
def test_simulated_a_late_result_after_the_timeout_cannot_overwrite_it_and_writes_no_finding(two_tenants, app_user):
    a, _ = two_tenants
    h = Hang()
    ctx, rt, called, inv = hung_turn(a, app_user, h, soft=1)
    orchestrator.run_turn(ctx, rt, inv, GST)
    deadlines.settle_overdue_legs_locked(a, inv, now=overdue(a, inv), registry=rt.registry)
    before_findings, before_notes = findings(a, inv), notes(a, inv)
    h.release.set()  # the hung call finally returns a perfectly good result
    for _ in range(50):
        threading.Event().wait(0.1)
    [leg] = legs(a, inv)
    assert leg["status"] == "FAILED" and leg["error_reason"].startswith("TIMED_OUT_UNCERTAIN")  # not overwritten with COMPLETE
    assert findings(a, inv) == before_findings and notes(a, inv) == before_notes  # and no contradicting COMPLETE finding appeared


def test_simulated_an_unguarded_late_finisher_cannot_overwrite_a_settled_state_either(two_tenants, app_user):
    a, _ = two_tenants
    inv, anchor, run = craft_late_leg(a, app_user, "cfo.financial_health", "CFO")
    deadlines.settle_overdue_legs_locked(a, inv, now=PAST + timedelta(seconds=HARD), registry=get_registry())
    agent_run_repo.finish_run(a, run, status="COMPLETE", error_reason=None, finished_at=T0)  # the plain (unguarded) writer some specialists use
    got = agent_run_repo.get_run(a, run)
    assert got["status"] == "FAILED" and got["error_reason"].startswith("TIMED_OUT")


def test_simulated_a_completed_leg_is_never_overwritten_by_the_timeout(two_tenants, app_user):
    a, _ = two_tenants
    inv, anchor, run = craft_late_leg(a, app_user, "cfo.financial_health", "CFO")
    agent_run_repo.finish_run(a, run, status="COMPLETE", error_reason=None, finished_at=T0)
    assert deadlines.settle_overdue_legs_locked(a, inv, now=PAST + timedelta(seconds=HARD), registry=get_registry()).settled == 0
    assert agent_run_repo.get_run(a, run)["status"] == "COMPLETE"


def test_simulated_concurrent_settlers_produce_exactly_one_settlement_and_one_note(two_tenants, app_user):
    a, _ = two_tenants
    inv, anchor, run = craft_late_leg(a, app_user, "cfo.gst_lookup", "GST_LOOKUP")
    now = PAST + timedelta(seconds=HARD)
    out, barrier = [], threading.Barrier(6, timeout=20)

    def go():
        barrier.wait()
        out.append(deadlines.settle_overdue_legs_locked(a, inv, now=now, registry=get_registry()))

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    assert sum(r.settled for r in out) == 1 and len(notes(a, inv)) == 1 and len(findings(a, inv)) == 1


def test_simulated_concurrent_recovery_passes_settle_once_and_a_repeat_changes_nothing(two_tenants, app_user):
    a, _ = two_tenants
    inv, anchor, run = craft_late_leg(a, app_user, "cfo.gst_lookup", "GST_LOOKUP")
    now = PAST + timedelta(seconds=HARD)
    out, barrier = [], threading.Barrier(4, timeout=20)

    def go():
        barrier.wait()
        out.append(recovery.recover_investigation(a, inv, now=now))

    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    assert sum(r.legs_timed_out for r in out) == 1 and len(notes(a, inv)) == 1
    again = recovery.recover_investigation(a, inv, now=now)
    assert (again.legs_timed_out, again.turns_settled, again.legs_settled) == (0, 0, 0) and len(notes(a, inv)) == 1


def test_simulated_a_late_completion_racing_the_settler_leaves_one_consistent_outcome(two_tenants, app_user):
    """Release the hung call and run the settler at the same instant, several times. Either the leg wins (COMPLETE + its COMPLETE finding, no timeout note) or the settler wins (TIMED_OUT +
    its FAILED finding, no COMPLETE finding). Never a mixture."""
    a, _ = two_tenants
    outcomes = set()
    for _ in range(6):
        h = Hang()
        ctx, rt, called, inv = hung_turn(a, app_user, h, soft=1)
        orchestrator.run_turn(ctx, rt, inv, GST)
        now = overdue(a, inv)
        barrier = threading.Barrier(2, timeout=20)

        def late():
            barrier.wait()
            h.release.set()

        def settle():
            barrier.wait()
            deadlines.settle_overdue_legs_locked(a, inv, now=now, registry=rt.registry)

        ts = [threading.Thread(target=late), threading.Thread(target=settle)]
        [t.start() for t in ts]
        [t.join(timeout=60) for t in ts]
        for _ in range(60):  # the late leg's own write may still be in flight
            if legs(a, inv)[0]["status"] != "RUNNING":
                break
            threading.Event().wait(0.1)
        threading.Event().wait(0.5)
        [leg] = legs(a, inv)
        fs = [f[1] for f in findings(a, inv) if f[0] == "cfo.gst_lookup"]
        if leg["status"] == "COMPLETE":
            assert fs == ["COMPLETE"] and notes(a, inv) == []
            outcomes.add("leg")
        else:
            assert leg["status"] == "FAILED" and leg["error_reason"].startswith("TIMED_OUT_UNCERTAIN") and fs == ["FAILED"] and len(notes(a, inv)) == 1
            outcomes.add("settler")
    assert outcomes  # (which side wins is a race; consistency is the claim)


# ------------------------------------------------------------------------------------------------ preservation and visibility
def test_simulated_a_completed_sibling_leg_and_its_finding_survive_and_the_partial_result_stays_visible(two_tenants, app_user):
    a, _ = two_tenants
    hang = Hang()
    reg = fake_registry({"cfo.financial_health": lambda: {"methods": []}, "cfo.anomaly_check": lambda: hang(None, None, None), "cfo.strategic_briefing": lambda: {"signals": []}})
    ctx = ctx_for(a, user_id=app_user)
    from tests.integration.test_ceo_turn import PROFIT

    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), registry=reg, leg_timeout=1)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    assert "still running" in res.answer or "Anomaly" in res.answer or res.status in ("DELIVERED", "PARTIAL")
    done_before = {f[0]: f[1] for f in findings(a, inv)}
    assert done_before.get("cfo.financial_health") == "COMPLETE" and done_before.get("cfo.strategic_briefing") == "COMPLETE"
    rep = deadlines.settle_overdue_legs_locked(a, inv, now=overdue(a, inv), registry=reg)
    assert rep.settled == 1
    after = {f[0]: f[1] for f in findings(a, inv)}
    assert after["cfo.financial_health"] == "COMPLETE" and after["cfo.strategic_briefing"] == "COMPLETE" and after["cfo.anomaly_check"] == "FAILED"  # completed work kept, the timeout visible
    hang.release.set()


def test_simulated_a_retry_with_the_same_submission_id_after_an_uncertain_timeout_does_not_repeat_the_effect(two_tenants, app_user):
    a, _ = two_tenants
    h = Hang()
    ctx, rt, called, inv = hung_turn(a, app_user, h, soft=1)
    key = str(uuid.uuid4())
    first = orchestrator.run_turn(ctx, rt, inv, GST, request_key=key)
    deadlines.settle_overdue_legs_locked(a, inv, now=overdue(a, inv), registry=rt.registry)
    retry = orchestrator.run_turn(ctx, rt, inv, GST, request_key=key)
    assert retry.replayed and retry.turn_id == first.turn_id and len(h.calls) == 1  # the stored outcome, not a second lookup
    assert len(legs(a, inv)) == 1
    h.release.set()


def test_simulated_a_sweep_never_touches_another_tenants_late_leg(two_tenants, app_user):
    a, b = two_tenants
    inv_b, _, run_b = craft_late_leg(b, app_user, "cfo.gst_lookup", "GST_LOOKUP")
    rep = recovery.sweep_all(now=PAST + timedelta(seconds=HARD), tenants=[a])
    assert rep.legs_timed_out == 0 and agent_run_repo.get_run(b, run_b)["status"] == "RUNNING"
    rep = recovery.sweep_all(now=PAST + timedelta(seconds=HARD), tenants=[b])
    assert rep.legs_timed_out == 1 and agent_run_repo.get_run(b, run_b)["status"] == "FAILED"


def test_simulated_the_next_turn_in_an_investigation_settles_what_is_overdue_before_it_starts(two_tenants, app_user):
    a, _ = two_tenants
    inv, anchor, run = craft_late_leg(a, app_user, "cfo.gst_lookup", "GST_LOOKUP")
    rt, called, _ = build(None)
    ticking = rt.clock
    rt = replace(rt, clock=lambda: PAST + timedelta(seconds=HARD + 5))
    orchestrator.run_turn(ctx_for(a, user_id=app_user), rt, inv, GST)
    assert agent_run_repo.get_run(a, run)["error_reason"].startswith("TIMED_OUT_UNCERTAIN")


# ------------------------------------------------------------------------------------------------ process death keeps its own, different mark
def test_process_death_is_still_an_interruption_not_a_timeout(two_tenants, app_user):
    """PROCESS DEATH: a real child dies mid-leg. Ownership recovery marks it INTERRUPTED (the process is gone); the hard deadline plays no part in it, and a second pass changes nothing."""
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, runtime(Scripted({}), registry=fake_registry({})))
    child = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "ceo_recovery_child.py"), str(a), str(app_user), str(inv)],
                           capture_output=True, text=True, timeout=120, env={**os.environ})
    assert child.returncode == 137, (child.returncode, child.stdout[-300:], child.stderr[-600:])
    far = datetime.now(timezone.utc) + timedelta(days=2)
    rep = recovery.recover_investigation(a, inv, now=far)
    assert (rep.owned, rep.turns_settled, rep.legs_settled, rep.legs_timed_out) == (False, 1, 1, 0)
    with tenant_scope(a) as conn:
        reasons = [r[0] for r in conn.execute(text("SELECT error_reason FROM agent_run WHERE investigation_id = :i AND status = 'FAILED'"), {"i": str(inv)})]
    assert reasons and all(str(r).startswith("INTERRUPTED") for r in reasons)
    assert recovery.recover_investigation(a, inv, now=far) == recovery.RecoveryReport()


# ------------------------------------------------------------------------------------------------ helpers
def craft_late_leg(tenant, user, action_key: str, agent_id: str):
    """SIMULATED: a turn that already ended (anchor COMPLETE, answered) whose leg `action_key` is still RUNNING since PAST - what a hung call leaves behind."""
    inv = repo.create_investigation(tenant, created_by=user, attached_agents=tuple(ALL_AGENTS), detached_agents=(), now=PAST)
    ctx = ctx_for(tenant, user_id=user)
    turn = open_turn(ctx, investigation_id=inv, now=PAST)
    msg = repo.append_message(tenant, inv, role="USER", content="question", created_by=user, now=PAST)
    turn.turn_id = repo.create_turn(tenant, inv, user_message_id=msg, agent_run_id=turn.anchor_run_id, route="ACTION", route_key=action_key, status="DISPATCHED", now=PAST)
    run = agent_run_repo.insert_run(tenant, agent_id=agent_id, trigger_type="CONVERSATIONAL", trigger_ref=action_key, requested_by=user, permission_check="PASS", entitlement_check="PASS",
                                    status="RUNNING", started_at=PAST, parent_run_id=turn.anchor_run_id, investigation_id=inv)
    answer = repo.append_message(tenant, inv, role="CEO", kind="ANSWER", content="It is still running.", agent_run_id=turn.anchor_run_id, turn_id=turn.turn_id, now=PAST)
    repo.update_turn(tenant, turn.turn_id, status="DELIVERED", ceo_message_id=answer, completed_at=PAST)
    agent_run_repo.finish_run(tenant, turn.anchor_run_id, status="COMPLETE", error_reason=None, finished_at=PAST)
    return inv, turn.anchor_run_id, run
