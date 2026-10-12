"""Task 3 memory campaign, tier 2: the shared findings ledger (`shared_finding`). Persistence, lifecycle under concurrency, tenant isolation and restart behaviour, against
the real table on the scratch Postgres. The database gate and the writer's rules are covered by test_ceo_findings.py; this file adds what that one does not: simultaneous
operations and survival across processes."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from backend.ceo import findings
from backend.repositories import shared_finding_repo as repo
from tests.integration.test_ceo_findings import message_id, pi_idea, real  # noqa: F401  (fixtures and helpers)

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]
BACKEND = Path(__file__).resolve().parents[2]
ALL = findings.AGENTS


def rows(tenant, **where) -> int:
    engine = create_engine(os.environ["DATABASE_URL_APP"])
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            clause = "".join(f" AND {k} = :{k}" for k in where)
            return conn.execute(text(f"SELECT count(*) FROM shared_finding WHERE true{clause}"), where).scalar_one()  # noqa: S608 - keys are literals in this file
    finally:
        engine.dispose()


def race(fns):
    barrier = threading.Barrier(len(fns))

    def run(fn):
        barrier.wait()
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - a refused operation is an outcome to assert on, not a crash of the harness
            return exc

    with ThreadPoolExecutor(max_workers=len(fns)) as pool:
        return list(pool.map(run, fns))


def test_each_step_is_committed_and_visible_to_an_independent_connection(two_tenants, app_user):
    a, _ = two_tenants
    fid = pi_idea(a)
    assert rows(a) == 1 and rows(a, status="ACTIVE") == 1
    assert findings.forget(a, fid, visible_agents=ALL, created_by=app_user) is True
    assert rows(a) == 2 and rows(a, status="FORGOTTEN") == 1  # appended, never rewritten
    assert findings.list_visible(a, ALL).items == []


def test_findings_survive_a_restart_and_a_forgotten_one_stays_gone(two_tenants, app_user):
    a, _ = two_tenants
    keep, gone = pi_idea(a, subject="Keep me"), pi_idea(a, subject="Forget me")
    findings.forget(a, gone, visible_agents=ALL, created_by=app_user)
    code = (
        "from uuid import UUID; from backend.ceo import findings; "
        f"print([i['subject'] for i in findings.list_visible(UUID('{a}'), findings.AGENTS).items])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(BACKEND), env=dict(os.environ), timeout=120)
    assert out.returncode == 0 and out.stdout.strip() == "['Keep me']", out.stderr[-500:]
    assert keep is not None


def test_the_same_source_recorded_at_the_same_moment_is_stored_once(two_tenants):
    a, _ = two_tenants
    source = real(a)
    results = race([lambda: findings.record(a, agent="PI", kind="PRODUCT_IDEA", text="Reported.", subject="Steel bottle", source_ref=source)] * 8)
    assert sum(1 for r in results if r is not None and not isinstance(r, Exception)) == 1 and not [r for r in results if isinstance(r, Exception)]
    assert rows(a) == 1 and len(repo.list_active(a)) == 1


def test_of_several_simultaneous_forgets_exactly_one_succeeds(two_tenants, app_user):
    a, _ = two_tenants
    fid = pi_idea(a)
    results = race([lambda: findings.forget(a, fid, visible_agents=ALL, created_by=app_user)] * 6)
    assert [r for r in results if isinstance(r, Exception)] == []
    assert sum(1 for r in results if r is True) == 1
    assert rows(a, status="FORGOTTEN") == 1 and findings.list_visible(a, ALL).items == []


def test_a_correction_racing_a_forget_cannot_leave_a_forgotten_finding_visible(two_tenants, app_user, message_id):
    """Both operations target the same active finding. Whatever order they land in, a finding the seller was told is forgotten must not be visible afterwards, and at
    most one of the two may succeed (the second would be acting on a finding that is no longer active)."""
    a, _ = two_tenants
    fid = pi_idea(a)
    results = race([
        lambda: findings.forget(a, fid, visible_agents=ALL, created_by=app_user),
        lambda: findings.correct(a, fid, text="my own words", message_id=message_id, visible_agents=ALL, created_by=app_user),
    ])
    assert [r for r in results if isinstance(r, Exception)] == []
    forgot, corrected = results
    assert not (forgot is True and corrected is not None), "both succeeded on one finding"
    visible = findings.list_visible(a, ALL).items
    if forgot is True:
        assert visible == []
    else:
        assert [i["text"] for i in visible] == ["my own words"]


def test_two_tenants_race_without_crossing(two_tenants, app_user):
    a, b = two_tenants
    sa, sb = real(a), real(b)
    race([lambda: findings.record(a, agent="PI", kind="PRODUCT_IDEA", text="Reported.", subject="A", source_ref=sa),
          lambda: findings.record(b, agent="PI", kind="PRODUCT_IDEA", text="Reported.", subject="B", source_ref=sb)] * 3)
    assert [i["subject"] for i in findings.list_visible(a, ALL).items] == ["A"] and [i["subject"] for i in findings.list_visible(b, ALL).items] == ["B"]
    assert rows(a) == 1 and rows(b) == 1
