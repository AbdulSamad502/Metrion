"""Hardening Fix 4: a CEO turn whose process died is settled safely; a turn that is still running is never touched.

Ownership, not age: a turn holds the investigation's Postgres advisory lock for its whole life, on a session that ends when the process does. So a RUNNING conversational CEO run
whose investigation lock is FREE has no owner (abandoned), and one whose lock is HELD is alive however long it has been running. No age threshold exists or is needed.
Recovery takes that same lock while it settles, which makes it idempotent and race-free across workers and restarts, and blocks a new turn from starting mid-recovery.

Evidence labels: tests marked SIMULATED craft the post-crash rows directly; the PROCESS DEATH test kills a real child process mid-leg (`os._exit`). Neither proves anything
about a hung leg inside a LIVE process (that cannot be told from a slow one without a deadline decision) nor about legs that finish after their turn ended."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import replace

import pytest
from sqlalchemy import text

from backend.ceo import orchestrator, recovery
from backend.ceo.dispatch import open_turn
from backend.ceo.registry import ActionRegistry
from backend.ceo.turn_lock import investigation_turn_lock
from backend.repositories import agent_run_repo, investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for
from tests.integration.test_ceo_campaign_routing_e2e import build
from tests.integration.test_ceo_turn import Scripted, fake_registry, runtime, start

pytestmark = pytest.mark.usefixtures("two_tenants")

from datetime import timedelta  # noqa: E402

PAST = T0 - timedelta(minutes=5)  # the crashed turn happened before the fake clock of later turns
REASON = "INTERRUPTED"
GST = "What GST rate applies to steel water bottles?"


def craft_abandoned(tenant, user):
    """SIMULATED: what a dead process leaves behind: a RUNNING turn run, one leg that finished, one leg still RUNNING, a finding, the seller's question, no answer."""
    inv = repo.create_investigation(tenant, created_by=user, attached_agents=tuple(ALL_AGENTS), detached_agents=(), now=PAST)
    ctx = ctx_for(tenant, user_id=user)
    turn = open_turn(ctx, investigation_id=inv, now=PAST)
    msg = repo.append_message(tenant, inv, role="USER", content="Why did my profit drop?", created_by=user, now=PAST)
    turn.turn_id = repo.create_turn(tenant, inv, user_message_id=msg, agent_run_id=turn.anchor_run_id, route="PLAYBOOK", route_key="PROFIT_DIAGNOSIS", status="DISPATCHED", now=PAST)

    def leg(key):
        return agent_run_repo.insert_run(tenant, agent_id="CFO", trigger_type="CONVERSATIONAL", trigger_ref=key, requested_by=user, permission_check="PASS",
                                         entitlement_check="PASS", status="RUNNING", started_at=PAST, parent_run_id=turn.anchor_run_id, investigation_id=inv)

    done = leg("cfo.financial_health")
    agent_run_repo.finish_run(tenant, done, status="COMPLETE", error_reason=None, finished_at=PAST)
    stuck = leg("cfo.anomaly_check")
    repo.insert_finding(tenant, inv, turn_id=turn.turn_id, source="CFO", action_key="cfo.financial_health", status="COMPLETE", agent_run_id=done, figure_refs=[], now=PAST)
    return inv, turn, done, stuck


def state(tenant, inv):
    with tenant_scope(tenant) as conn:
        runs = {str(r[0]): (r[1], r[2], r[3]) for r in conn.execute(text("SELECT id, status, error_reason, finished_at FROM agent_run WHERE investigation_id = :i"), {"i": str(inv)})}
        msgs = [(r[0], r[1]) for r in conn.execute(text("SELECT role, kind FROM investigation_message WHERE investigation_id = :i ORDER BY created_at, id"), {"i": str(inv)})]
        turns = [(r[0], r[1] is not None) for r in conn.execute(text("SELECT status, completed_at FROM investigation_turn WHERE investigation_id = :i"), {"i": str(inv)})]
        usage = conn.execute(text("SELECT count(*) FROM metered_event WHERE event_kind = 'ceo.chat_turn'")).scalar_one()
    return runs, msgs, turns, usage


def test_simulated_an_abandoned_turn_is_settled_with_a_reason_and_finished_work_is_kept(two_tenants, app_user):
    a, _ = two_tenants
    inv, turn, done, stuck = craft_abandoned(a, app_user)
    rep = recovery.recover_investigation(a, inv)
    assert (rep.owned, rep.turns_settled, rep.legs_settled) == (False, 1, 1)
    anchor = agent_run_repo.get_run(a, turn.anchor_run_id)
    assert anchor["status"] == "FAILED" and str(anchor["error_reason"]).startswith(REASON) and anchor["finished_at"] is not None
    leg_done, leg_stuck = agent_run_repo.get_run(a, done), agent_run_repo.get_run(a, stuck)
    assert leg_done["status"] == "COMPLETE" and leg_done["error_reason"] is None  # finished work is not rewritten
    assert leg_stuck["status"] == "FAILED" and str(leg_stuck["error_reason"]).startswith(REASON)
    assert any(f["action_key"] == "cfo.financial_health" and f["status"] == "COMPLETE" for f in repo.list_findings(a, inv))  # persisted findings survive
    runs, msgs, turns, usage = state(a, inv)
    assert turns == [("FAILED", True)] and msgs == [("USER", "TEXT"), ("CEO", "ANSWER")] and usage == 0  # one honest answer, and the interrupted turn is never charged
    answer = repo.list_messages(a, inv)[-1]["content"]
    assert "interrupted" in answer and "did not finish" in answer and "ask again" in answer.lower()
    assert not any(v[0] in ("RUNNING", "QUEUED") for v in runs.values())


def test_a_turn_that_is_still_running_is_never_touched_however_long_it_takes(two_tenants, app_user):
    a, _ = two_tenants
    release, entered = threading.Event(), threading.Event()

    def slow(slots, c, leg):
        entered.set()
        release.wait(timeout=30)
        return {"result": None, "noMatch": None}

    rt, called, _ = build(None)
    rt = replace(rt, registry=ActionRegistry([replace(s, invoke=slow) if s.key == "cfo.gst_lookup" else s for s in rt.registry.specs()]))
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    out = []
    t = threading.Thread(target=lambda: out.append(orchestrator.run_turn(ctx, rt, inv, GST)))
    t.start()
    assert entered.wait(timeout=20)
    before = state(a, inv)
    rep = recovery.recover_investigation(a, inv)
    sweep = recovery.sweep_all(tenants=[a])
    assert rep.owned and rep.turns_settled == 0 and sweep.turns_settled == 0
    assert state(a, inv) == before and any(v[0] == "RUNNING" for v in before[0].values())  # it is RUNNING and stays RUNNING
    release.set()
    t.join(timeout=30)
    assert out[0].status == "DELIVERED"
    runs, msgs, turns, _ = state(a, inv)
    assert turns == [("DELIVERED", True)] and [m[0] for m in msgs] == ["USER", "CEO"] and not any(v[0] == "RUNNING" for v in runs.values())


def test_simulated_two_workers_recovering_at_once_settle_it_exactly_once(two_tenants, app_user):
    a, _ = two_tenants
    inv, turn, done, stuck = craft_abandoned(a, app_user)
    barrier, reports = threading.Barrier(2, timeout=20), []

    def worker():
        barrier.wait()
        reports.append(recovery.recover_investigation(a, inv))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert sum(r.turns_settled for r in reports) == 1 and sum(r.legs_settled for r in reports) == 1
    runs, msgs, turns, usage = state(a, inv)
    assert msgs == [("USER", "TEXT"), ("CEO", "ANSWER")] and turns == [("FAILED", True)] and usage == 0


def test_simulated_a_restart_sweeps_every_tenant_and_a_second_pass_changes_nothing(two_tenants, app_user):
    a, b = two_tenants
    inv_a, *_ = craft_abandoned(a, app_user)
    inv_b, *_ = craft_abandoned(b, app_user)
    first = recovery.sweep_all(tenants=[a, b])
    assert first.turns_settled == 2 and first.legs_settled == 2
    snapshot = (state(a, inv_a), state(b, inv_b))
    again = recovery.sweep_all(tenants=[a, b])
    assert again.turns_settled == 0 and again.legs_settled == 0 and (state(a, inv_a), state(b, inv_b)) == snapshot  # idempotent: repeated passes are no-ops
    assert all(v[0] != "RUNNING" for v in state(a, inv_a)[0].values())


def test_simulated_a_sweep_never_touches_another_tenants_live_turn(two_tenants, app_user):
    a, b = two_tenants
    craft_abandoned(a, app_user)
    ctx_b = ctx_for(b, user_id=app_user)
    inv_b = repo.create_investigation(b, created_by=app_user, attached_agents=tuple(ALL_AGENTS), detached_agents=(), now=T0)
    live = open_turn(ctx_b, investigation_id=inv_b, now=T0)  # B has a RUNNING anchor whose lock is HELD by a live turn
    with investigation_turn_lock(inv_b, None):
        before = state(b, inv_b)
        total = recovery.sweep_all(tenants=[a, b])
        assert state(b, inv_b) == before and agent_run_repo.get_run(b, live.anchor_run_id)["status"] == "RUNNING"
    assert total.turns_settled == 1  # only A's abandoned turn


def test_simulated_a_recovered_turn_followed_by_a_retry_runs_only_the_retry(two_tenants, app_user):
    a, _ = two_tenants
    inv, turn, done, stuck = craft_abandoned(a, app_user)
    recovery.recover_investigation(a, inv)
    rt, called, _ = build(None)
    res = orchestrator.run_turn(ctx_for(a, user_id=app_user), rt, inv, GST)
    assert res.status == "DELIVERED" and called == ["cfo.gst_lookup"]  # the interrupted turn's legs were not run again
    assert agent_run_repo.get_run(a, turn.anchor_run_id)["status"] == "FAILED" and agent_run_repo.get_run(a, done)["status"] == "COMPLETE"
    statuses = [t[0] for t in state(a, inv)[2]]
    assert statuses.count("FAILED") == 1 and statuses.count("DELIVERED") == 1


def test_simulated_the_next_turn_settles_what_an_earlier_crash_left_behind_even_without_a_sweep(two_tenants, app_user):
    a, _ = two_tenants
    inv, turn, done, stuck = craft_abandoned(a, app_user)
    rt, called, _ = build(None)
    orchestrator.run_turn(ctx_for(a, user_id=app_user), rt, inv, GST)  # the turn lock this call holds proves nobody else owns the old run
    assert agent_run_repo.get_run(a, turn.anchor_run_id)["status"] == "FAILED" and agent_run_repo.get_run(a, stuck)["status"] == "FAILED"
    assert [m[0] for m in state(a, inv)[1]] == ["USER", "CEO", "USER", "CEO"]


def test_what_recovery_deliberately_does_not_touch(two_tenants, app_user):
    a, _ = two_tenants
    inv = repo.create_investigation(a, created_by=app_user, attached_agents=tuple(ALL_AGENTS), detached_agents=(), now=T0)
    system = open_turn(ctx_for(a, user_id=app_user), investigation_id=inv, trigger_type="SYSTEM", now=T0)  # not a seller turn: not this recovery's business
    late = agent_run_repo.insert_run(a, agent_id="CFO", trigger_type="SYSTEM", trigger_ref="cfo.strategic_briefing", requested_by=app_user, permission_check="PASS",
                                     entitlement_check="PASS", status="RUNNING", started_at=T0, parent_run_id=system.anchor_run_id, investigation_id=inv)
    rep = recovery.recover_investigation(a, inv)
    assert rep.turns_settled == 0 and rep.legs_settled == 0 and agent_run_repo.get_run(a, system.anchor_run_id)["status"] == "RUNNING" and agent_run_repo.get_run(a, late)["status"] == "RUNNING"
    agent_run_repo.finish_run(a, system.anchor_run_id, status="COMPLETE", error_reason=None, finished_at=T0)  # a finished turn whose late leg is still running in a live process
    rep = recovery.recover_investigation(a, inv)
    assert rep.legs_settled == 0 and agent_run_repo.get_run(a, late)["status"] == "RUNNING"


def test_process_death_a_real_child_killed_mid_leg_leaves_a_turn_that_recovery_settles(two_tenants, app_user):
    """PROCESS DEATH: a separate Python process runs a real turn and `os._exit`s inside one leg. Its Postgres session dies with it, which is what frees the turn lock."""
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, runtime(Scripted({}), registry=fake_registry({})))
    child = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "ceo_recovery_child.py"), str(a), str(app_user), str(inv)],
                           capture_output=True, text=True, timeout=120, env={**os.environ})
    assert child.returncode == 137, (child.returncode, child.stdout[-300:], child.stderr[-600:])
    runs, msgs, turns, usage = state(a, inv)
    assert sorted(v[0] for v in runs.values()) == ["COMPLETE", "COMPLETE", "RUNNING", "RUNNING"]  # the dead process left the anchor and one leg open
    assert msgs == [("USER", "TEXT")]
    rep = recovery.recover_investigation(a, inv)
    assert (rep.owned, rep.turns_settled, rep.legs_settled) == (False, 1, 1)
    runs, msgs, turns, usage = state(a, inv)
    assert sorted(v[0] for v in runs.values()) == ["COMPLETE", "COMPLETE", "FAILED", "FAILED"] and msgs[-1] == ("CEO", "ANSWER") and turns == [("FAILED", True)] and usage == 0
    assert all(str(v[1]).startswith(REASON) for v in runs.values() if v[0] == "FAILED")


def test_application_start_up_runs_the_sweep_off_the_request_path(two_tenants, app_user):
    """The real app lifespan starts the sweep in a background thread: a turn abandoned before this start is settled without any request touching it."""
    import time

    from fastapi.testclient import TestClient

    from backend.main import app

    a, _ = two_tenants
    inv, turn, done, stuck = craft_abandoned(a, app_user)
    with TestClient(app):  # entering the context runs the lifespan (start-up)
        deadline = time.time() + 30
        while time.time() < deadline and agent_run_repo.get_run(a, turn.anchor_run_id)["status"] == "RUNNING":
            time.sleep(0.2)
    assert agent_run_repo.get_run(a, turn.anchor_run_id)["status"] == "FAILED" and agent_run_repo.get_run(a, stuck)["status"] == "FAILED"
    assert agent_run_repo.get_run(a, done)["status"] == "COMPLETE"


def test_a_leg_that_finishes_after_recovery_cannot_overwrite_the_recovered_state(two_tenants, app_user):
    """The guarantee `dispatch` relies on (`finish_run_if_unfinished`): once recovery has settled a leg, a late `COMPLETE` from a straggler is refused and the recovery mark stays."""
    a, _ = two_tenants
    inv, turn, done, stuck = craft_abandoned(a, app_user)
    recovery.recover_investigation(a, inv)
    late = agent_run_repo.finish_run_if_unfinished(a, stuck, status="COMPLETE", error_reason=None, finished_at=T0)
    assert late is False
    row = agent_run_repo.get_run(a, stuck)
    assert row["status"] == "FAILED" and str(row["error_reason"]).startswith(REASON)
    assert agent_run_repo.finish_run_if_unfinished(a, turn.anchor_run_id, status="COMPLETE", error_reason=None, finished_at=T0) is False  # nor the turn's own run
