"""R4 (approval prerequisites): the turn status vocabulary, including PLANNED, is one list in code and one CHECK in the database.

PLANNED is vocabulary only: nothing produces it yet. These tests prove it can be stored faithfully (never coerced to FAILED),
is never metered, and that the Python constants and the DB constraint cannot drift apart silently."""

from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.ceo import orchestrator
from backend.ceo.contract import IN_FLIGHT_TURN_STATUSES, TERMINAL_TURN_STATUSES, TURN_STATUSES
from backend.ceo.dispatch import open_turn
from backend.repositories import investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import T0, ctx_for, row_counts
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = pytest.mark.usefixtures("two_tenants")


def _constraint_statuses(migrate_engine) -> set[str]:
    with migrate_engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'investigation_turn_status_check'")
        ).scalar_one()
    return set(re.findall(r"'([A-Z_]+)'", definition))


def test_the_python_status_constants_equal_the_database_check_constraint(migrate_engine):
    assert _constraint_statuses(migrate_engine) == set(TURN_STATUSES)  # fails if either side gains a value alone
    assert len(TURN_STATUSES) == len(set(TURN_STATUSES))
    assert set(IN_FLIGHT_TURN_STATUSES).isdisjoint(TERMINAL_TURN_STATUSES)
    assert "PLANNED" in TERMINAL_TURN_STATUSES and "PLANNED" not in IN_FLIGHT_TURN_STATUSES


def _make_turn(a, app_user):
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded())
    inv = start(ctx, rt)
    msg = repo.append_message(a, inv, role="USER", content="plan something", created_by=app_user, now=T0)
    anchor = open_turn(ctx, investigation_id=inv, now=T0).anchor_run_id
    turn_id = repo.create_turn(a, inv, user_message_id=msg, agent_run_id=anchor, route="ACTION", route_key="cfo.reconcile", status="PLAN_VALIDATED", now=T0)
    return ctx, rt, inv, turn_id


def test_planned_round_trips_and_is_never_stored_as_failed(two_tenants, app_user):
    a, _ = two_tenants
    _, _, _, turn_id = _make_turn(a, app_user)
    repo.update_turn(a, turn_id, status="PLANNED", completed_at=T0)
    assert repo.get_turn(a, turn_id)["status"] == "PLANNED"


def test_the_orchestrator_finalisation_keeps_a_planned_result_and_meters_nothing(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    ctx, rt, inv, turn_id = _make_turn(a, app_user)
    monkeypatch.setattr(orchestrator, "_run_admitted", lambda *args, **kw: orchestrator.TurnResult("PLANNED", "ACTION", "plan ready", turn_id=turn_id))
    before = row_counts(a, "metered_event")
    res = orchestrator.run_turn(ctx, rt, inv, "something that would be planned")
    assert res.status == "PLANNED"
    assert repo.get_turn(a, turn_id)["status"] == "PLANNED"  # the whitelist at the end of run_turn no longer coerces it to FAILED
    assert row_counts(a, "metered_event") == before  # a planned turn is never metered


def test_an_unknown_status_is_still_refused_by_the_database(two_tenants, app_user):
    a, _ = two_tenants
    _, _, _, turn_id = _make_turn(a, app_user)
    with pytest.raises(DBAPIError):
        with tenant_scope(a) as conn:
            conn.execute(text("UPDATE investigation_turn SET status = 'APPROVED' WHERE id = :i"), {"i": str(turn_id)})


def _alembic(*args: str):
    import os
    import subprocess
    import sys

    assert os.environ["DATABASE_URL"]  # the migration chain runs against whatever DATABASE_URL points at (CI / scratch)
    return subprocess.run([sys.executable, "-m", "alembic", *args], capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), "..", ".."), timeout=180)


@pytest.mark.skipif(
    os.environ.get("METRION_ALLOW_DOWNGRADE_TESTS") != "1",
    reason="runs alembic downgrade/upgrade against DATABASE_URL: opt in with METRION_ALLOW_DOWNGRADE_TESTS=1, only on a scratch/CI database, never the dev DB",
)
def test_the_downgrade_refuses_while_a_planned_row_exists_and_round_trips_otherwise(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    _, _, _, turn_id = _make_turn(a, app_user)
    repo.update_turn(a, turn_id, status="PLANNED", completed_at=T0)
    refused = _alembic("downgrade", "20261011_0015")
    assert refused.returncode != 0 and "PLANNED" in (refused.stderr + refused.stdout)
    assert repo.get_turn(a, turn_id)["status"] == "PLANNED"  # nothing was rewritten
    assert _constraint_statuses(migrate_engine) == set(TURN_STATUSES)  # and the constraint is untouched
    repo.update_turn(a, turn_id, status="FAILED", completed_at=T0)  # no PLANNED row any more: the downgrade may proceed
    try:
        assert _alembic("downgrade", "20261011_0015").returncode == 0
        assert "PLANNED" not in _constraint_statuses(migrate_engine)
    finally:
        assert _alembic("upgrade", "head").returncode == 0
    assert "PLANNED" in _constraint_statuses(migrate_engine)
