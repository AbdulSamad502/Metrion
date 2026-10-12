"""R5 for the specialist packages' own run tables: `reconciliation_run` (calc-engine) and `ci_capture_run` (competitor-intelligence).

The packages never import the backend; the backend plugs ownership into their `ownership` hooks (`run_liveness.install_package_ownership`). Real child processes are killed:
the row stays RUNNING, its lock disappears with the session, and the sweep settles it FAILED exactly once. A live run is never touched, a late finisher cannot overwrite the
recovery mark, and an exception in a live process settles its own rows."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import date, datetime, timezone

import pytest
from calc_engine.repositories import reconciliation_repo
from competitor_intelligence.repositories import ci_capture_run_repo
from competitor_intelligence.types import RunStatus, Trigger
from sqlalchemy import text

from backend.ceo import recovery
from backend.repositories import run_liveness
from backend.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("two_tenants")
CHILD = os.path.join(os.path.dirname(__file__), "package_run_child.py")
NOW = datetime.now(timezone.utc)
TABLES = ("reconciliation_run", "ci_capture_run")


@pytest.fixture(autouse=True)
def _ownership_installed():
    run_liveness.install_package_ownership()


def status_of(tenant, table, run):
    with tenant_scope(tenant) as conn:
        return tuple(conn.execute(text(f"SELECT status, finished_at IS NOT NULL FROM {table} WHERE id = :i"), {"i": str(run)}).one())  # noqa: S608


def spawn(kind, tenant, user):
    proc = subprocess.Popen([sys.executable, CHILD, kind, str(tenant), str(user)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy())
    line = proc.stdout.readline()
    assert line.startswith("RUN "), f"child did not start: {line!r} {proc.stderr.read() if proc.poll() is not None else ''}"
    return proc, uuid.UUID(line.split()[1])


def kill(proc, kind, run):
    proc.kill()
    proc.wait(timeout=30)
    for _ in range(200):
        if not run_liveness.is_owned_elsewhere(run, kind):
            return
        time.sleep(0.1)
    raise AssertionError("the dead session's lock was never released")


def sweep(tenant):
    return recovery.sweep_orphan_runs(tenants=[tenant])


def _recon(a):
    return reconciliation_repo.insert_reconciliation_run(
        a, marketplace="AMAZON", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), as_of_date=date(2026, 10, 1), tolerance_config_version=0,
        formula_version="t", status="RUNNING", join_key_validated=True, started_at=NOW)


@pytest.mark.parametrize("kind", TABLES)
def test_hard_kill_leaves_running_and_the_sweep_settles_it_once(kind, two_tenants, app_user):
    a, _ = two_tenants
    proc, run = spawn(kind, a, app_user)
    try:
        assert run_liveness.is_owned_elsewhere(run, kind)
        assert sweep(a).package_runs_settled == 0 and status_of(a, kind, run)[0] == "RUNNING"  # alive: untouched however long it takes
    finally:
        kill(proc, kind, run)
    assert status_of(a, kind, run) == ("RUNNING", False)  # the stuck state
    assert sweep(a).package_runs_settled == 1
    assert status_of(a, kind, run) == ("FAILED", True)
    assert sweep(a).package_runs_settled == 0  # repeated recovery finds nothing


@pytest.mark.parametrize("kind", TABLES)
def test_competing_sweepers_settle_each_run_once(kind, two_tenants, app_user):
    a, _ = two_tenants
    children = [spawn(kind, a, app_user) for _ in range(3)]
    for proc, run in children:
        kill(proc, kind, run)
    results, gate = [], threading.Barrier(4)

    def go():
        gate.wait()
        results.append(sweep(a).package_runs_settled)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 3 and all(status_of(a, kind, r)[0] == "FAILED" for _p, r in children)


def test_late_finishers_cannot_overwrite_a_recovery_mark(two_tenants, app_user):
    a, _ = two_tenants
    rp, rrun = spawn("reconciliation_run", a, app_user)
    kill(rp, "reconciliation_run", rrun)
    cp, crun = spawn("ci_capture_run", a, app_user)
    kill(cp, "ci_capture_run", crun)
    assert sweep(a).package_runs_settled == 2
    reconciliation_repo.mark_reconciliation_run_finished(a, rrun, status="COMPLETE", finished_at=NOW, settlement_line_count=1, sales_line_count=1, match_count=1, exception_count=0)
    ci_capture_run_repo.finish_run(a, crun, status=RunStatus.COMPLETE, finished_at=NOW)
    assert status_of(a, "reconciliation_run", rrun)[0] == "FAILED" and status_of(a, "ci_capture_run", crun)[0] == "FAILED"


def test_a_live_run_is_owned_until_its_terminal_write_and_then_released(two_tenants, app_user):
    a, _ = two_tenants
    run = _recon(a)
    assert run_liveness.is_owned_elsewhere(run, "reconciliation_run") and sweep(a).package_runs_settled == 0
    reconciliation_repo.mark_reconciliation_run_finished(a, run, status="COMPLETE", finished_at=NOW, settlement_line_count=0, sales_line_count=0, match_count=0, exception_count=0)
    assert status_of(a, "reconciliation_run", run)[0] == "COMPLETE" and not run_liveness.is_owned_elsewhere(run, "reconciliation_run")


def test_an_exception_in_a_live_process_settles_the_runs_it_opened(two_tenants, app_user):
    a, _ = two_tenants
    opened = []

    @reconciliation_repo.settles_open_runs
    def reconcile_like():
        opened.append(_recon(a))
        raise RuntimeError("engine exploded")

    @ci_capture_run_repo.settles_open_runs
    def capture_like():
        opened.append(ci_capture_run_repo.create_run(a, trigger=list(Trigger)[0], requested_by=app_user, url_ids=[], started_at=NOW))
        raise RuntimeError("extractor exploded")

    for fn in (reconcile_like, capture_like):
        with pytest.raises(RuntimeError):
            fn()
    assert status_of(a, "reconciliation_run", opened[0]) == ("FAILED", True) and status_of(a, "ci_capture_run", opened[1]) == ("FAILED", True)
    assert not run_liveness.is_owned_elsewhere(opened[0], "reconciliation_run") and not run_liveness.is_owned_elsewhere(opened[1], "ci_capture_run")


def test_sweeps_are_tenant_scoped(two_tenants, app_user):
    a, b = two_tenants
    proc, run = spawn("ci_capture_run", a, app_user)
    kill(proc, "ci_capture_run", run)
    assert sweep(b).package_runs_settled == 0 and status_of(a, "ci_capture_run", run)[0] == "RUNNING"
    assert sweep(a).package_runs_settled == 1


def test_the_packages_expose_no_op_hooks_when_used_standalone():
    from calc_engine import ownership as calc_ownership
    from competitor_intelligence import ownership as ci_ownership

    assert callable(calc_ownership.claim) and callable(ci_ownership.release)
