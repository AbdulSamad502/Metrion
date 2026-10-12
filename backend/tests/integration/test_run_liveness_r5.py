"""R5: why jobs stayed RUNNING, and the proof they no longer can.

Root causes (docs/planning/r5-stuck-running-findings-2026-10-12.md): (1) a RUNNING `agent_run` carried no evidence of an owner, so after a process death nothing could tell a
dead run from a slow one, and only seller-turn CEO anchors had any recovery; (2) the CEO Hub's direct-dispatch functions wrote a RUNNING row and then called a specialist with
no exception handling, so an error left the row RUNNING in a process that was still alive.

Evidence labels: the HARD-KILL tests kill a real child process (a real session ends, a real advisory lock disappears). The CONNECTION-LOSS test terminates the liveness session
of a live process with `pg_terminate_backend`. Everything else drives the real repositories on the scratch database. Nothing here uses a timeout or an age."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import pytest
from product_intelligence.repositories import niche_brief_repo, pi_research_run_repo
from sqlalchemy import create_engine, text

from backend.ceo import recovery
from backend.repositories import agent_run_repo, run_liveness
from backend.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("two_tenants")

CHILD = os.path.join(os.path.dirname(__file__), "run_liveness_child.py")
NOW = datetime.now(timezone.utc)


def open_run(tenant, user, *, agent="CFO", ref="cfo.pnl"):
    return agent_run_repo.insert_run(tenant, agent_id=agent, trigger_type="DIRECT", trigger_ref=ref, requested_by=user, permission_check="PASS",
                                     entitlement_check="PASS", status="RUNNING", started_at=NOW)


def spawn_child(tenant, user):
    proc = subprocess.Popen([sys.executable, CHILD, str(tenant), str(user)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy())
    line = proc.stdout.readline()
    assert line.startswith("RUN "), f"child did not start: {line!r} {proc.stderr.read() if proc.poll() is not None else ''}"
    return proc, uuid.UUID(line.split()[1])


def kill_and_wait(*children):
    for proc, _run in children:
        proc.kill()
        proc.wait(timeout=30)
    for _ in range(200):  # the server notices a dead session asynchronously
        if not any(run_liveness.is_owned_elsewhere(r) for _p, r in children):
            return
        time.sleep(0.1)
    raise AssertionError("the dead session's lock was never released")


def sweep(tenant):
    return recovery.sweep_orphan_runs(tenants=[tenant])


def status(tenant, run):
    r = agent_run_repo.get_run(tenant, run)
    return r["status"], r["error_reason"]


def test_hard_killed_process_leaves_a_running_row_that_the_sweep_settles_once(two_tenants, app_user):
    a, _ = two_tenants
    proc, run = spawn_child(a, app_user)
    try:
        assert run_liveness.is_owned_elsewhere(run)  # alive: its session holds the lock
        assert sweep(a).orphans_settled == 0 and status(a, run)[0] == "RUNNING"  # a live owner is never touched, however long the run has taken
    finally:
        kill_and_wait((proc, run))
    assert status(a, run)[0] == "RUNNING"  # the kill itself wrote nothing: this is the stuck-RUNNING state R5 describes
    assert sweep(a).orphans_settled == 1
    st, why = status(a, run)
    assert st == "FAILED" and why.startswith("INTERRUPTED")
    assert sweep(a).orphans_settled == 0  # repeated recovery finds nothing


def test_a_live_owner_is_never_settled_and_its_real_result_is_kept(two_tenants, app_user):
    a, _ = two_tenants
    run = open_run(a, app_user)
    assert sweep(a).orphans_settled == 0 and status(a, run)[0] == "RUNNING"
    agent_run_repo.finish_run(a, run, status="COMPLETE", error_reason=None, finished_at=NOW)
    assert status(a, run) == ("COMPLETE", None)
    assert sweep(a).orphans_settled == 0 and status(a, run)[0] == "COMPLETE"
    assert not run_liveness.is_owned_elsewhere(run)  # released after the terminal write


def test_a_late_result_cannot_overwrite_a_recovery_mark(two_tenants, app_user):
    a, _ = two_tenants
    child = spawn_child(a, app_user)
    kill_and_wait(child)
    assert sweep(a).orphans_settled == 1
    run = child[1]
    agent_run_repo.finish_run(a, run, status="COMPLETE", error_reason=None, finished_at=NOW)  # an unguarded late finisher
    assert agent_run_repo.finish_run_if_unfinished(a, run, status="COMPLETE", error_reason=None, finished_at=NOW) is False  # and a guarded one
    st, why = status(a, run)
    assert st == "FAILED" and why.startswith("INTERRUPTED")


def test_competing_sweepers_settle_each_orphan_exactly_once(two_tenants, app_user):
    a, _ = two_tenants
    children = [spawn_child(a, app_user) for _ in range(3)]
    kill_and_wait(*children)
    results: list[int] = []
    gate = threading.Barrier(4)

    def go():
        gate.wait()
        results.append(sweep(a).orphans_settled)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 3  # four competing workers, three orphans: each settled once, by exactly one of them
    assert all(status(a, r)[0] == "FAILED" for _p, r in children)


def test_sweep_is_tenant_scoped(two_tenants, app_user):
    a, b = two_tenants
    child = spawn_child(a, app_user)
    kill_and_wait(child)
    assert sweep(b).orphans_settled == 0 and status(a, child[1])[0] == "RUNNING"  # B's pass cannot reach A's row
    assert sweep(a).orphans_settled == 1


def test_an_exception_in_a_direct_dispatch_never_leaves_the_row_running(two_tenants, app_user):
    a, _ = two_tenants
    opened = []

    @agent_run_repo.settles_open_runs
    def direct_route():
        opened.append(open_run(a, app_user))
        raise RuntimeError("specialist exploded: secret-looking text that must not be stored")

    with pytest.raises(RuntimeError):
        direct_route()
    st, why = status(a, opened[0])
    assert st == "FAILED" and why == "ERROR: RuntimeError"  # the class only: no internals reach the row
    assert not run_liveness.is_owned_elsewhere(opened[0])


def test_a_normal_exit_of_the_guard_leaves_the_rows_to_their_owner(two_tenants, app_user):
    a, _ = two_tenants

    @agent_run_repo.settles_open_runs
    def direct_route():
        run = open_run(a, app_user)
        agent_run_repo.finish_run(a, run, status="COMPLETE", error_reason=None, finished_at=NOW)
        return run

    assert status(a, direct_route()) == ("COMPLETE", None)


def test_losing_the_liveness_connection_of_a_live_process_is_survived(two_tenants, app_user):
    a, _ = two_tenants
    run = open_run(a, app_user)
    pid = run_liveness._connection().execute(text("SELECT pg_backend_pid()")).scalar_one()  # the liveness session of THIS process
    eng = create_engine(os.environ["DATABASE_URL_APP"])  # same role, so it may end that session
    try:
        with eng.begin() as conn:
            killed = int(bool(conn.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid}).scalar_one()))
    finally:
        eng.dispose()
    assert killed >= 1
    other = open_run(a, app_user)  # the next claim re-opens the connection and re-takes the locks of the runs still held
    assert run_liveness.is_owned_elsewhere(run) and run_liveness.is_owned_elsewhere(other)
    assert sweep(a).orphans_settled == 0
    for r in (run, other):
        agent_run_repo.finish_run(a, r, status="COMPLETE", error_reason=None, finished_at=NOW)


def test_one_failing_tenant_does_not_stop_the_pass(two_tenants, app_user, monkeypatch):
    a, b = two_tenants
    child = spawn_child(b, app_user)
    kill_and_wait(child)
    real = agent_run_repo.list_running_unconversational

    def flaky(tenant):
        if tenant == a:
            raise RuntimeError("database interrupted")
        return real(tenant)

    monkeypatch.setattr(agent_run_repo, "list_running_unconversational", flaky)
    assert recovery.sweep_orphan_runs(tenants=[a, b]).orphans_settled == 1  # A's failure is logged; B is still settled


def test_the_sweep_never_dispatches_anything():
    src = open(recovery.__file__, encoding="utf-8").read()
    body = src.split("def sweep_orphan_runs")[1]
    assert "registry" not in body and "invoke(" not in body and "dispatch(" not in body


def _brief_and_runs(a, user, n):
    brief = niche_brief_repo.create_draft(a, created_by=user, category_text="steel water bottle")
    return [pi_research_run_repo.create_run(a, niche_brief_id=brief, depth="SHALLOW", trigger="DIRECT_UI", candidate_cap=5) for _ in range(n)]


def test_orphaned_pi_research_runs_are_failed_when_no_pi_run_is_alive(two_tenants, app_user):
    a, _ = two_tenants
    runs = _brief_and_runs(a, app_user, 2)
    pi_research_run_repo.update_status(a, runs[0], status="RUNNING", started_at=NOW)
    assert sweep(a).pi_runs_settled == 2  # QUEUED and RUNNING alike: neither has an owner
    assert {pi_research_run_repo.get_run(a, r)["status"] for r in runs} == {"FAILED"}
    assert sweep(a).pi_runs_settled == 0


def test_a_pi_research_run_with_a_live_pi_owner_is_left_alone(two_tenants, app_user):
    a, _ = two_tenants
    (run,) = _brief_and_runs(a, app_user, 1)
    pi_research_run_repo.update_status(a, run, status="RUNNING", started_at=NOW)
    live = open_run(a, app_user, agent="PI", ref="pi.discover")  # the route's own RUNNING agent_run, lock held by this process
    assert sweep(a).pi_runs_settled == 0 and pi_research_run_repo.get_run(a, run)["status"] == "RUNNING"
    agent_run_repo.finish_run(a, live, status="COMPLETE", error_reason=None, finished_at=NOW)
    assert sweep(a).pi_runs_settled == 1


def test_a_pi_run_created_after_the_look_is_never_swept(two_tenants, app_user):
    a, _ = two_tenants
    (run,) = _brief_and_runs(a, app_user, 1)
    before = pi_research_run_repo.get_run(a, run)["created_at"]
    assert agent_run_repo.settle_orphan_pi_research_runs(a, finished_at=NOW, created_before=before) == 0  # created at/after the instant the caller looked
    assert pi_research_run_repo.get_run(a, run)["status"] != "FAILED"


def test_in_flight_rows_of_another_tenant_are_not_visible_to_a_tenant_scoped_listing(two_tenants, app_user):
    a, b = two_tenants
    open_run(a, app_user)
    with tenant_scope(b):
        pass
    assert agent_run_repo.list_running_unconversational(b) == []
