"""S0 scratch experiments (NOT part of the repo). Run only against the isolated scratch Postgres on :5544."""
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text

from backend.ceo import orchestrator
from backend.ceo.turn_lock import TurnInProgress, investigation_turn_lock
from backend.repositories import agent_run_repo, investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_turn import MSG_PROFIT, PROFIT, Grounded, Scripted, fake_registry, runtime, start

pytestmark = pytest.mark.usefixtures("two_tenants")

SCRATCH_PORT = "5544"


@pytest.fixture(autouse=True)
def _only_scratch():
    assert SCRATCH_PORT in os.environ["DATABASE_URL"] and SCRATCH_PORT in os.environ["DATABASE_URL_APP"], "refusing: not the scratch DB"


def events(tenant):
    with tenant_scope(tenant) as conn:
        return [tuple(r) for r in conn.execute(text("SELECT agent_code, event_kind, quantity FROM metered_event ORDER BY occurred_at"))]


def test_X1_a_failed_required_leg_still_delivers_and_consumes_one_ceo_unit(two_tenants, app_user):
    a, _ = two_tenants

    def explode():
        raise RuntimeError("boom")

    reg = fake_registry({"cfo.financial_health": explode, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=reg)
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    turn = repo.get_turn(a, res.turn_id)
    legs = {c["trigger_ref"]: c["status"] for c in agent_run_repo.list_children(a, turn["agent_run_id"])}
    print("\nX1 turn.status=", res.status, "| legs=", legs, "| anchor=", agent_run_repo.get_run(a, turn["agent_run_id"])["status"], "| metered_event=", events(a))
    assert legs["cfo.financial_health"] == "FAILED"
    assert events(a) == [("CEO", "ceo.chat_turn", 1)]  # CONFIRMED: the unit is consumed although the required leg failed


def test_X2_hard_crash_mid_leg_leaves_rows_stuck_and_the_next_turn_still_works(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=fake_registry({"cfo.financial_health": lambda: {}, "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}}))
    inv = start(ctx, rt)
    child = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "crash_child.py"), str(a), str(app_user), str(inv)],
        capture_output=True, text=True, cwd=r"C:\dev\Metrion\backend", env={**os.environ}, timeout=120,
    )
    print("\nX2 child exit code:", child.returncode, "| stdout:", child.stdout.strip().replace("\n", " / "))
    assert child.returncode == 137

    turns = repo.list_turns(a, inv) if hasattr(repo, "list_turns") else None
    with tenant_scope(a) as conn:
        turn_rows = [tuple(r) for r in conn.execute(text("SELECT status, completed_at IS NULL, route, route_key FROM investigation_turn WHERE investigation_id = :i"), {"i": str(inv)})]
        runs = [tuple(r) for r in conn.execute(text("SELECT agent_id, trigger_type, trigger_ref, status, finished_at IS NULL FROM agent_run ORDER BY started_at"))]
        msgs = [tuple(r) for r in conn.execute(text("SELECT role, kind FROM investigation_message WHERE investigation_id = :i ORDER BY created_at"), {"i": str(inv)})]
    print("X2 turn rows (status, completed_at is null, route, key):", turn_rows)
    print("X2 agent_run rows (agent, trigger, ref, status, finished_at is null):", runs)
    print("X2 messages (role, kind):", msgs)
    print("X2 metered_event after crash:", events(a))

    # the advisory lock died with the process: a new turn must not be blocked
    with investigation_turn_lock(inv, None):
        pass
    ok = fake_registry({"cfo.financial_health": lambda: {"overallBand": "GOOD", "perMetricBands": {}, "engineResultRefs": [], "unavailableReason": None},
                        "cfo.anomaly_check": lambda: {}, "cfo.strategic_briefing": lambda: {}})
    rt2 = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=ok)
    res2 = orchestrator.run_turn(ctx, rt2, inv, MSG_PROFIT)
    print("X2 second turn after crash:", res2.status)
    with tenant_scope(a) as conn:
        still = [tuple(r) for r in conn.execute(text("SELECT status FROM investigation_turn WHERE investigation_id = :i AND completed_at IS NULL"), {"i": str(inv)})]
        stuck_runs = [tuple(r) for r in conn.execute(text("SELECT trigger_ref, status FROM agent_run WHERE finished_at IS NULL"))]
    print("X2 after the next turn, turns still non-terminal:", still, "| runs still unfinished:", stuck_runs)
    assert res2.status == "DELIVERED"
    assert still and stuck_runs  # CONFIRMED: nothing reconciles them
    assert events(a) == [("CEO", "ceo.chat_turn", 1)]  # only the delivered second turn was metered; the crashed turn recorded nothing


@pytest.mark.parametrize("key", ["pi.discover", "pi.supplier_lookup", "ci.discover_competitors", "cmo.market_trends", "cmo.generate_title_sets", "cfo.pricing", "cfo.reconcile", "ci.request_price_scenario"])
def test_X3_reachability_from_ceo_chat_via_ui_action_against_the_REAL_registry(two_tenants, app_user, key):
    """Which registered actions can a CEO turn actually dispatch today? (UI actions go through the same closed catalog as the classifier.)"""
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded())
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "run it", ui_action=orchestrator.UiAction("ACTION", key, {}))
    turn = repo.get_turn(a, res.turn_id)
    legs = [c["trigger_ref"] for c in agent_run_repo.list_children(a, turn["agent_run_id"])]
    print(f"\nX3 {key:28} -> status={res.status} route={res.route} flags={turn['classifier_result'].get('flags') if turn['classifier_result'] else None} legs_dispatched={legs}")
