"""R5 Stage A (audit L7): a run that already reached a terminal status is never overwritten by a late finisher.

No schema, no lease and no recovery here: only the guarded write and the choke point's use of it. Needs a real Postgres (use the scratch database)."""

from __future__ import annotations

import ast
import pathlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.ceo.contract import AgentCode, LegStatus
from backend.ceo.dispatch import dispatch, open_turn
from backend.ceo.registry import ActionRegistry
from backend.repositories import agent_run_repo, investigation_repo as repo
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for, later
from tests.unit.ceo_fakes import spec


def _run(tenant, user, status="RUNNING"):
    return agent_run_repo.insert_run(
        tenant, agent_id="CFO", trigger_type="CONVERSATIONAL", trigger_ref="cfo.test", requested_by=user,
        permission_check="PASS", entitlement_check="PASS", status=status, started_at=T0, inherit_parent=False,
    )


@pytest.mark.parametrize("start", ["QUEUED", "RUNNING"])
def test_an_unfinished_run_is_finished_once(two_tenants, app_user, start):
    a, _ = two_tenants
    rid = _run(a, app_user, start)
    won = agent_run_repo.finish_run_if_unfinished(a, rid, status="COMPLETE", error_reason=None, finished_at=later(1), output_refs=[{"k": 1}])
    assert won is True
    row = agent_run_repo.get_run(a, rid)
    assert row["status"] == "COMPLETE" and row["finished_at"] == later(1) and row["output_refs"] == [{"k": 1}]


@pytest.mark.parametrize("terminal", ["PARTIAL", "COMPLETE", "FAILED", "DENIED"])
def test_a_terminal_run_is_left_untouched(two_tenants, app_user, terminal):
    a, _ = two_tenants
    rid = _run(a, app_user)
    agent_run_repo.finish_run(a, rid, status=terminal, error_reason="first", finished_at=later(1), output_refs=[{"first": True}])
    won = agent_run_repo.finish_run_if_unfinished(a, rid, status="COMPLETE", error_reason=None, finished_at=later(9), output_refs=[{"late": True}])
    assert won is False
    row = agent_run_repo.get_run(a, rid)
    assert (row["status"], row["error_reason"], row["finished_at"], row["output_refs"]) == (terminal, "first", later(1), [{"first": True}])


def test_a_missing_run_is_not_an_error_and_not_a_write(two_tenants, app_user):
    import uuid

    a, _ = two_tenants
    assert agent_run_repo.finish_run_if_unfinished(a, uuid.uuid4(), status="FAILED", error_reason="x", finished_at=later(1)) is False


def test_a_status_only_finish_keeps_the_recorded_output_refs(two_tenants, app_user):
    a, _ = two_tenants
    rid = agent_run_repo.insert_run(a, agent_id="CFO", trigger_type="CONVERSATIONAL", trigger_ref="cfo.test", requested_by=app_user, permission_check="PASS",
                                    entitlement_check="PASS", status="RUNNING", started_at=T0, output_refs=[{"kept": 1}], inherit_parent=False)
    assert agent_run_repo.finish_run_if_unfinished(a, rid, status="FAILED", error_reason="boom", finished_at=later(1)) is True
    assert agent_run_repo.get_run(a, rid)["output_refs"] == [{"kept": 1}]


def test_two_concurrent_finishers_produce_exactly_one_winner(two_tenants, app_user):
    a, _ = two_tenants
    for _round in range(5):
        rid = _run(a, app_user)

        def finish(n):
            return agent_run_repo.finish_run_if_unfinished(a, rid, status="COMPLETE" if n else "FAILED", error_reason=None if n else "x", finished_at=later(n), output_refs=[{"by": n}])

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(finish, [0, 1]))
        assert sorted(results) == [False, True]
        row = agent_run_repo.get_run(a, rid)
        winner = results.index(True)
        assert row["output_refs"] == [{"by": winner}] and row["status"] == ("COMPLETE" if winner else "FAILED")


def test_a_leg_that_finishes_after_its_row_was_settled_does_not_overwrite_it(two_tenants, app_user, caplog):
    """The choke point's own leg write is guarded: the row someone else settled (a recovery mark, in the design) keeps its status."""
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv = repo.create_investigation(a, created_by=app_user, attached_agents=tuple(ALL_AGENTS), detached_agents=(), now=T0)
    msg = repo.append_message(a, inv, role="USER", content="x", created_by=app_user, now=T0)
    turn = open_turn(ctx, investigation_id=inv, now=T0)
    turn.turn_id = repo.create_turn(a, inv, user_message_id=msg, agent_run_id=turn.anchor_run_id, route="ACTION", route_key="cfo.test_read", now=T0)

    def settled_meanwhile(slots, c, leg):
        # Another actor marks this leg's row terminal while the call is still running; the call then returns normally.
        agent_run_repo.finish_run(a, leg.leg_run_id, status="FAILED", error_reason="marked by someone else", finished_at=later(1))
        return {"ok": True}

    reg = ActionRegistry([spec("cfo.test_read", agent=AgentCode.CFO, source="CFO", invoke=settled_meanwhile, slot_model=None)])
    with caplog.at_level("WARNING"):
        leg = dispatch(turn, "cfo.test_read", None, registry=reg, now=T0)
    assert leg.status is LegStatus.COMPLETE  # the caller still sees what its call returned
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert child["status"] == "FAILED" and child["error_reason"] == "marked by someone else" and child["finished_at"] == later(1)
    assert any("already terminal" in r.getMessage() for r in caplog.records)


def test_the_happy_path_still_ends_complete(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv = repo.create_investigation(a, created_by=app_user, attached_agents=tuple(ALL_AGENTS), detached_agents=(), now=T0)
    msg = repo.append_message(a, inv, role="USER", content="x", created_by=app_user, now=T0)
    turn = open_turn(ctx, investigation_id=inv, now=T0)
    turn.turn_id = repo.create_turn(a, inv, user_message_id=msg, agent_run_id=turn.anchor_run_id, route="ACTION", route_key="cfo.test_read", now=T0)
    reg = ActionRegistry([spec("cfo.test_read", agent=AgentCode.CFO, source="CFO", slot_model=None)])
    leg = dispatch(turn, "cfo.test_read", None, registry=reg, now=T0)
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert leg.status is LegStatus.COMPLETE and child["status"] == "COMPLETE" and child["finished_at"] is not None


def test_stage_a_adds_no_reconciler_lease_or_dispatch_of_flagged_actions():
    """Scope guard: this stage is the guarded write only. Nothing in the backend source tree may introduce a lease or a reconciler yet."""
    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "backend"
    names = {p.stem for p in root.rglob("*.py")}
    assert not names & {"reconcile", "reconciler", "leg_lease", "lease"}
    for path in (root / "repositories" / "agent_run_repo.py", root / "ceo" / "dispatch.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any("lease" in m or "reconcil" in m for m in imported)
