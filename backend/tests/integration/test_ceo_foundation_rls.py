"""Tenant isolation and integrity for the B1 CEO tables (spec §8 rule 5, R10, AC28, T12; auth.md §7.3).

Connected as `metrion_app` (the role the application runs as) so every policy is exercised against the real role; seeding
and catalog inspection use the owner. Mirrors `test_rls_isolation.py`'s approach.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from backend.repositories import agent_run_repo, investigation_repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ALL_AGENTS, T0

pytestmark = pytest.mark.usefixtures("two_tenants")

NEW_TABLES = ("investigation_turn", "investigation_finding", "investigation_agent")


def _investigation(tenant: uuid.UUID, user: uuid.UUID) -> uuid.UUID:
    return investigation_repo.create_investigation(tenant, created_by=user, attached_agents=("CFO",), now=T0)


def _turn(tenant: uuid.UUID, user: uuid.UUID, inv: uuid.UUID) -> uuid.UUID:
    msg = investigation_repo.append_message(tenant, inv, role="USER", content="why did profit drop?", created_by=user, now=T0)
    run = agent_run_repo.insert_run(tenant, agent_id="CEO", trigger_type="CONVERSATIONAL", trigger_ref="ceo.chat_turn", requested_by=user,
                                    permission_check="PASS", entitlement_check="PASS", status="RUNNING", started_at=T0, investigation_id=inv, inherit_parent=False)
    return investigation_repo.create_turn(tenant, inv, user_message_id=msg, agent_run_id=run, route="PLAYBOOK", route_key="PROFIT_DIAGNOSIS", now=T0)


# ------------------------------------------------------------------------------------------- catalog facts
@pytest.mark.parametrize("table", NEW_TABLES)
def test_new_tables_are_force_rls_with_a_tenant_policy(migrate_engine, table):
    with migrate_engine.connect() as conn:
        row = conn.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": table}).one()
        policies = conn.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": table}).scalar_one()
    assert row == (True, True) and policies == 1


@pytest.mark.parametrize("table", NEW_TABLES)
def test_the_app_role_cannot_delete_audit_evidence(two_tenants, app_user, table):
    tenant, _ = two_tenants
    with pytest.raises((ProgrammingError, DBAPIError)):
        with tenant_scope(tenant) as conn:
            conn.execute(text(f"DELETE FROM {table}"))


# ------------------------------------------------------------------------------------------- isolation
def test_a_tenant_cannot_see_another_tenants_ceo_rows(two_tenants, app_user):
    a, b = two_tenants
    inv = _investigation(a, app_user)
    turn = _turn(a, app_user, inv)
    investigation_repo.insert_finding(a, inv, turn_id=turn, source="CFO", action_key="cfo.financial_health", status="COMPLETE", now=T0)
    with tenant_scope(b) as conn:
        for table in ("investigation", "investigation_message", *NEW_TABLES):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
    assert investigation_repo.get_investigation(b, inv) is None
    assert investigation_repo.list_investigations(b) == [] and investigation_repo.list_findings(b, inv) == []
    assert investigation_repo.get_turn(b, turn) is None and investigation_repo.attached_agents(b, inv) == frozenset()


def test_rls_rejects_writing_a_row_for_another_tenant(two_tenants, app_user):
    a, b = two_tenants
    inv = _investigation(a, app_user)
    with pytest.raises((ProgrammingError, DBAPIError)):  # WITH CHECK violation
        with tenant_scope(b) as conn:
            conn.execute(
                text("INSERT INTO investigation_agent (investigation_id, tenant_id, agent_code, attached, changed_by) VALUES (:i, :t, 'CFO', true, :u)"),
                {"i": str(inv), "t": str(a), "u": str(app_user)},
            )


def test_missing_tenant_context_fails_closed():
    with pytest.raises(ValueError):
        with tenant_scope(None):
            pass


@pytest.mark.parametrize(
    "call",
    [
        lambda b, inv, user, turn, msg, run: investigation_repo.append_message(b, inv, role="USER", content="x", created_by=user),
        lambda b, inv, user, turn, msg, run: investigation_repo.create_turn(b, inv, user_message_id=msg, agent_run_id=run, route="ACTION"),
        lambda b, inv, user, turn, msg, run: investigation_repo.insert_finding(b, inv, turn_id=turn, source="CFO", action_key="k", status="COMPLETE"),
        lambda b, inv, user, turn, msg, run: investigation_repo.set_agent_attachment(b, inv, "CFO", attached=True, changed_by=user),
        lambda b, inv, user, turn, msg, run: investigation_repo.resolve_investigation(b, inv, resolved_by=user, resolution_note="done"),
        lambda b, inv, user, turn, msg, run: investigation_repo.archive_investigation(b, inv),
        lambda b, inv, user, turn, msg, run: investigation_repo.reopen_investigation(b, inv),
    ],
    ids=["append_message", "create_turn", "insert_finding", "set_attachment", "resolve", "archive", "reopen"],
)
def test_a_foreign_investigation_id_is_indistinguishable_from_a_missing_one(two_tenants, app_user, call):
    """A foreign key would accept another tenant's id (FKs are checked with owner privileges); the repository's own scoped check is
    what turns it into a 404 (spec T12)."""
    a, b = two_tenants
    inv = _investigation(a, app_user)
    turn = _turn(a, app_user, inv)
    msg = investigation_repo.append_message(a, inv, role="USER", content="m", created_by=app_user, now=T0)
    run = agent_run_repo.insert_run(a, agent_id="CEO", trigger_type="CONVERSATIONAL", trigger_ref="x", requested_by=app_user, permission_check="PASS",
                                    entitlement_check="PASS", status="RUNNING", started_at=T0, inherit_parent=False)
    before = investigation_repo.get_investigation(a, inv)
    with pytest.raises(investigation_repo.InvestigationNotFound):
        call(b, inv, app_user, turn, msg, run)
    assert investigation_repo.get_investigation(a, inv)["status"] == before["status"]  # and nothing changed for the owner


def test_a_turn_cannot_reference_another_tenants_agent_run_or_message(two_tenants, app_user):
    a, b = two_tenants
    inv_b = _investigation(b, app_user)
    msg_b = investigation_repo.append_message(b, inv_b, role="USER", content="m", created_by=app_user, now=T0)
    run_a = agent_run_repo.insert_run(a, agent_id="CEO", trigger_type="CONVERSATIONAL", trigger_ref="x", requested_by=app_user, permission_check="PASS",
                                      entitlement_check="PASS", status="RUNNING", started_at=T0, inherit_parent=False)
    with pytest.raises(investigation_repo.InvestigationNotFound):  # b's turn pointing at a's agent_run
        investigation_repo.create_turn(b, inv_b, user_message_id=msg_b, agent_run_id=run_a, route="ACTION")


def test_a_finding_must_belong_to_a_turn_of_the_same_investigation(two_tenants, app_user):
    a, _ = two_tenants
    inv1, inv2 = _investigation(a, app_user), _investigation(a, app_user)
    turn_of_1 = _turn(a, app_user, inv1)
    with pytest.raises(investigation_repo.InvestigationNotFound):
        investigation_repo.insert_finding(a, inv2, turn_id=turn_of_1, source="CFO", action_key="k", status="COMPLETE")


# ------------------------------------------------------------------------------------------- integrity (CHECKs)
@pytest.mark.parametrize(
    "sql, params",
    [
        ("UPDATE investigation SET status = 'WEIRD' WHERE id = :i", {}),
        ("UPDATE investigation SET origin = 'TELEPATHY' WHERE id = :i", {}),
        ("UPDATE investigation SET status = 'RESOLVED' WHERE id = :i", {}),  # RESOLVED needs a note, resolver and time
        ("UPDATE investigation SET status = 'RESOLVED', resolved_at = now(), resolved_by = created_by, resolution_note = '   ' WHERE id = :i", {}),
        ("UPDATE investigation_message SET kind = 'GOSSIP' WHERE investigation_id = :i", {}),
        ("INSERT INTO agent_run (id, tenant_id, agent_id, trigger_type, trigger_ref, requested_by, permission_check, entitlement_check, status) "
         "VALUES (gen_random_uuid(), :t, 'CEO', 'TELEPATHY', 'x', :u, 'PASS', 'PASS', 'RUNNING')", {}),
        ("INSERT INTO agent_run (id, tenant_id, agent_id, trigger_type, trigger_ref, requested_by, permission_check, entitlement_check, status) "
         "VALUES (gen_random_uuid(), :t, 'NOT_AN_AGENT', 'DIRECT', 'x', :u, 'PASS', 'PASS', 'RUNNING')", {}),
        ("INSERT INTO investigation_agent (investigation_id, tenant_id, agent_code, attached, changed_by) VALUES (:i, :t, 'CEO', true, :u)", {}),
    ],
    ids=["status", "origin", "resolved-no-note", "resolved-blank-note", "message-kind", "run-trigger", "run-agent", "agent-code-ceo"],
)
def test_check_constraints_reject_invalid_rows(two_tenants, app_user, sql, params):
    a, _ = two_tenants
    inv = _investigation(a, app_user)
    investigation_repo.append_message(a, inv, role="USER", content="m", created_by=app_user, now=T0)
    with pytest.raises(IntegrityError):
        with tenant_scope(a) as conn:
            conn.execute(text(sql), {"i": str(inv), "t": str(a), "u": str(app_user), **params})


@pytest.mark.parametrize(
    "column, value",
    [("route", "FREESTYLE"), ("route_source", "VIBES"), ("composition_mode", "MAGIC"), ("status", "LOST")],
)
def test_turn_checks(two_tenants, app_user, column, value):
    a, _ = two_tenants
    inv = _investigation(a, app_user)
    turn = _turn(a, app_user, inv)
    with pytest.raises(IntegrityError):
        with tenant_scope(a) as conn:
            conn.execute(text(f"UPDATE investigation_turn SET {column} = :v WHERE id = :id"), {"v": value, "id": str(turn)})


def test_finding_checks(two_tenants, app_user):
    a, _ = two_tenants
    inv = _investigation(a, app_user)
    turn = _turn(a, app_user, inv)
    with pytest.raises(IntegrityError):
        investigation_repo.insert_finding(a, inv, turn_id=turn, source="RANDOM_AGENT", action_key="k", status="COMPLETE")
    with pytest.raises(IntegrityError):
        investigation_repo.insert_finding(a, inv, turn_id=turn, source="CFO", action_key="k", status="MAYBE")


def test_figure_refs_must_be_a_json_array(two_tenants, app_user):
    a, _ = two_tenants
    inv = _investigation(a, app_user)
    turn = _turn(a, app_user, inv)
    investigation_repo.insert_finding(a, inv, turn_id=turn, source="CFO", action_key="k", status="COMPLETE", figure_refs=[], now=T0)  # control
    with pytest.raises(IntegrityError):
        with tenant_scope(a) as conn:
            conn.execute(
                text("INSERT INTO investigation_finding (tenant_id, investigation_id, turn_id, source, action_key, status, figure_refs) "
                     "VALUES (:t, :i, :turn, 'CFO', 'k', 'COMPLETE', '{}'::jsonb)"),
                {"t": str(a), "i": str(inv), "turn": str(turn)},
            )
