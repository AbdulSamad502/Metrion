"""Approval workflow schema, privileges and isolation (ceo-approval-workflow.md section 5, AC-A10, AC-A11, AC-A12; migration 20261012_0019).

Behavioural assertions connect as `metrion_app` (the role the application runs as) through `tenant_scope`; catalog assertions and the owner-role probes use the migration
role. A column-only grant makes `has_table_privilege(..., 'UPDATE')` false, so column privileges are asserted with `has_column_privilege`."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from backend.ceo import approval
from backend.ceo.registry import get_registry
from backend.ceo.runtime import CeoRuntime
from backend.ceo.dispatch import open_turn
from backend.repositories import accounting_cutover_repo, investigation_plan_repo as plan_repo, investigation_repo as repo
from backend.tenant_context import get_engine, tenant_scope
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

TABLES = ("investigation_plan", "investigation_plan_event")
FROZEN_COLUMNS = ("id", "tenant_id", "investigation_id", "planned_turn_id", "plan", "plan_hash", "requested_by", "created_at", "expires_at")
UPDATABLE_COLUMNS = ("status", "execution_turn_id", "decided_by", "decided_at", "decision_reason")
DENIED = (ProgrammingError, DBAPIError, IntegrityError)
HASHTAGS = {"request_key": "ceo-x", "product_name": "Steel bottle", "marketplace": "AMAZON"}


def new_plan(tenant: uuid.UUID, user: uuid.UUID, inv: uuid.UUID | None = None):
    """A real plan through the real planner (so the hash, the CREATED event and the PLAN message are exactly what production writes)."""
    ctx = ctx_for(tenant, user_id=user)
    inv = inv or repo.create_investigation(tenant, created_by=user, attached_agents=tuple(ALL_AGENTS), now=T0)
    msg = repo.append_message(tenant, inv, role="USER", content="plan", created_by=user, now=T0)
    t = open_turn(ctx, investigation_id=inv, now=T0)
    t.turn_id = repo.create_turn(tenant, inv, user_message_id=msg, agent_run_id=t.anchor_run_id, route="ACTION", route_key="cmo.generate_hashtags", status="PLAN_VALIDATED", now=T0)
    rt = CeoRuntime(classifier=object(), composer=None, leg_timeout_seconds=30, max_legs=5, clock=lambda: T0, registry=get_registry())
    import backend.ceo.approval as ap

    original = accounting_cutover_repo.effective_at
    accounting_cutover_repo.effective_at = lambda code: T0 - timedelta(days=1)  # type: ignore[assignment]
    try:
        built, _ = ap.create_plan(ctx, rt, investigation_id=inv, planned_turn_id=t.turn_id, anchor_run_id=t.anchor_run_id, route="ACTION", route_key="cmo.generate_hashtags",
                                  legs=[("cmo.generate_hashtags", HASHTAGS)], now=T0)
    finally:
        accounting_cutover_repo.effective_at = original  # type: ignore[assignment]
    t.close(status="COMPLETE", now=T0)
    return inv, built, t.turn_id


def app_exec(tenant: uuid.UUID, sql: str, **p):
    with tenant_scope(tenant) as conn:
        return conn.execute(text(sql), p)


# ------------------------------------------------------------------------------------------------ migration chain
def test_there_is_exactly_one_alembic_head_and_it_is_the_approval_revision_on_the_rag_foundation():
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads  # AC-D25: a single head, now and after any later migration stacked on this one
    assert script.get_revision("20261012_0019").down_revision == "20261012_0015"  # CD9
    assert "20261012_0019" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}  # the approval revision is on the head's lineage


# ------------------------------------------------------------------------------------------------ catalog
@pytest.mark.parametrize("table", TABLES)
def test_both_tables_are_force_rls_with_the_tenant_policy_on_read_and_write(migrate_engine, table):
    with migrate_engine.connect() as conn:
        rls = conn.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": table}).one()
        policies = conn.execute(text("SELECT policyname, qual, with_check FROM pg_policies WHERE tablename = :t"), {"t": table}).all()
        has_tenant = conn.execute(text("SELECT is_nullable FROM information_schema.columns WHERE table_name = :t AND column_name = 'tenant_id'"), {"t": table}).scalar_one()
    assert tuple(rls) == (True, True) and has_tenant == "NO"
    assert [p[0] for p in policies] == ["tenant_isolation"]
    assert "app.current_tenant_id" in policies[0][1] and "app.current_tenant_id" in policies[0][2]


@pytest.mark.parametrize("table", TABLES)
def test_the_app_role_can_neither_delete_nor_truncate(migrate_engine, table):
    with migrate_engine.connect() as conn:
        for priv in ("DELETE", "TRUNCATE"):
            assert not conn.execute(text("SELECT has_table_privilege('metrion_app', CAST(:t AS regclass), :p)"), {"t": table, "p": priv}).scalar_one()


def test_the_column_level_grant_is_exactly_the_five_decision_columns(migrate_engine):
    with migrate_engine.connect() as conn:
        def col(table: str, column: str, priv: str) -> bool:
            return bool(conn.execute(text("SELECT has_column_privilege('metrion_app', CAST(:t AS regclass), :c, :p)"), {"t": table, "c": column, "p": priv}).scalar_one())

        for c in UPDATABLE_COLUMNS:
            assert col("investigation_plan", c, "UPDATE"), c
        for c in FROZEN_COLUMNS:
            assert not col("investigation_plan", c, "UPDATE"), f"the app role can UPDATE {c}"
        assert col("investigation_plan", "plan", "SELECT") and col("investigation_plan", "plan_hash", "INSERT")
        # the event table is append-only: SELECT and INSERT, no UPDATE on any column
        cols = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'investigation_plan_event'")).scalars().all()
        assert cols and all(not col("investigation_plan_event", c, "UPDATE") for c in cols) and all(col("investigation_plan_event", c, "INSERT") for c in cols)
        for priv in ("SELECT", "INSERT"):
            assert conn.execute(text("SELECT has_table_privilege('metrion_app', 'investigation_plan_event', :p)"), {"p": priv}).scalar_one()
        assert not conn.execute(text("SELECT has_table_privilege('metrion_app', 'investigation_plan_event', 'UPDATE')")).scalar_one()
        # the existing tables' widened vocabulary
        defs = dict(conn.execute(text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conname IN ('investigation_turn_route_source_check', 'investigation_message_kind_check')")).all())
    assert "APPROVAL" in defs["investigation_turn_route_source_check"] and "PLAN" in defs["investigation_message_kind_check"]


# ------------------------------------------------------------------------------------------------ privileges, as the real app role
@pytest.mark.parametrize("column,value", [("plan_hash", "'" + "a" * 64 + "'"), ("requested_by", "gen_random_uuid()"), ("expires_at", "now() + interval '1 day'"), ("tenant_id", "gen_random_uuid()"),
                                          ("plan", "'{}'::jsonb"), ("investigation_id", "gen_random_uuid()"), ("created_at", "now()")])
def test_the_app_role_cannot_rewrite_the_frozen_plan_or_its_identity(two_tenants, app_user, column, value):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    with pytest.raises(DENIED):
        app_exec(a, f"UPDATE investigation_plan SET {column} = {value} WHERE id = :i", i=str(built.plan_id))
    row = plan_repo.get(a, inv, built.plan_id)
    assert row["plan_hash"] == built.plan_hash and row["plan"] == built.plan and row["requested_by"] == app_user and row["expires_at"] == built.expires_at


@pytest.mark.parametrize("sql", ["DELETE FROM investigation_plan", "DELETE FROM investigation_plan_event", "TRUNCATE investigation_plan", "TRUNCATE investigation_plan_event",
                                 "UPDATE investigation_plan_event SET reason_code = 'x'", "UPDATE investigation_plan_event SET plan_hash = 'x'"])
def test_the_app_role_cannot_delete_truncate_or_edit_history(two_tenants, app_user, sql):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    with pytest.raises(DENIED):
        app_exec(a, sql)
    assert plan_repo.get(a, inv, built.plan_id) is not None and len(plan_repo.events(a, built.plan_id)) == 1


def test_a_status_change_without_its_event_cannot_commit(two_tenants, app_user):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    with pytest.raises(DENIED):  # the app role HAS column UPDATE on status; the deferred trigger is what makes a bare change impossible (AC-A10)
        app_exec(a, "UPDATE investigation_plan SET status = 'DECLINED', decided_by = :u, decided_at = now() WHERE id = :i", u=str(app_user), i=str(built.plan_id))
    assert plan_repo.get(a, inv, built.plan_id)["status"] == "AWAITING_APPROVAL"
    with pytest.raises(DENIED):  # an event that does not match the change is not enough either
        with tenant_scope(a) as conn:
            conn.execute(text("UPDATE investigation_plan SET status = 'DECLINED', decided_by = :u, decided_at = now() WHERE id = :i"), {"u": str(app_user), "i": str(built.plan_id)})
            conn.execute(text("INSERT INTO investigation_plan_event (tenant_id, plan_id, event, from_status, to_status, actor_kind, plan_hash) "
                              "VALUES (:t, :i, 'EXPIRED', 'AWAITING_APPROVAL', 'EXPIRED', 'SYSTEM', :h)"), {"t": str(a), "i": str(built.plan_id), "h": built.plan_hash})
    assert plan_repo.get(a, inv, built.plan_id)["status"] == "AWAITING_APPROVAL"


def test_a_matching_event_in_the_same_transaction_is_what_makes_a_change_valid(two_tenants, app_user):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    with tenant_scope(a) as conn:
        conn.execute(text("UPDATE investigation_plan SET status = 'DECLINED', decided_by = :u, decided_at = now() WHERE id = :i"), {"u": str(app_user), "i": str(built.plan_id)})
        conn.execute(text("INSERT INTO investigation_plan_event (tenant_id, plan_id, event, from_status, to_status, actor_user_id, actor_kind, plan_hash) "
                          "VALUES (:t, :i, 'DECLINED', 'AWAITING_APPROVAL', 'DECLINED', :u, 'USER', :h)"), {"t": str(a), "i": str(built.plan_id), "h": built.plan_hash, "u": str(app_user)})
    assert plan_repo.get(a, inv, built.plan_id)["status"] == "DECLINED"


def test_every_terminal_status_is_final_even_against_a_direct_update(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    assert plan_repo.decline(a, plan_id=built.plan_id, investigation_id=inv, user_id=app_user, reason=None, note_content="n", now=T0 + timedelta(seconds=1))
    with pytest.raises(DENIED):  # the app role, with a forged event, cannot walk a terminal plan back
        with tenant_scope(a) as conn:
            conn.execute(text("UPDATE investigation_plan SET status = 'SUPERSEDED' WHERE id = :i"), {"i": str(built.plan_id)})
            conn.execute(text("INSERT INTO investigation_plan_event (tenant_id, plan_id, event, from_status, to_status, actor_kind, plan_hash) "
                              "VALUES (:t, :i, 'SUPERSEDED', 'AWAITING_APPROVAL', 'SUPERSEDED', 'SYSTEM', :h)"), {"t": str(a), "i": str(built.plan_id), "h": built.plan_hash})
    # and not even the table owner can edit the frozen plan, its hash or its expiry (the trigger guards the row, not just the role)
    for sql in ("UPDATE investigation_plan SET plan_hash = :h WHERE id = :i", "UPDATE investigation_plan SET expires_at = expires_at + interval '1 day' WHERE id = :i",
                "UPDATE investigation_plan SET plan = '{}'::jsonb WHERE id = :i", "UPDATE investigation_plan SET status = 'AWAITING_APPROVAL' WHERE id = :i"):
        owner = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)  # a private, unpooled connection: a tenant setting must never linger on the shared pool
        try:
            with pytest.raises(DENIED):
                with owner.begin() as conn:
                    conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(a)})
                    conn.execute(text(sql), {"h": "b" * 64, "i": str(built.plan_id)})
        finally:
            owner.dispose()
    assert plan_repo.get(a, inv, built.plan_id)["status"] == "DECLINED"


def test_a_plan_can_only_be_created_undecided_and_with_its_created_event(two_tenants, app_user):
    a, _ = two_tenants
    inv, built, first_turn = new_plan(a, app_user)

    def bare_turn() -> uuid.UUID:  # a real, unused turn to be the planned turn of the attempt
        from backend.repositories import agent_run_repo

        msg = repo.append_message(a, inv, role="USER", content="x", created_by=app_user, now=T0)
        run = agent_run_repo.insert_run(a, agent_id="CEO", trigger_type="CONVERSATIONAL", trigger_ref="ceo.chat_turn", requested_by=app_user, permission_check="PASS",
                                        entitlement_check="PASS", status="COMPLETE", started_at=T0, finished_at=T0, investigation_id=inv, inherit_parent=False)
        return repo.create_turn(a, inv, user_message_id=msg, agent_run_id=run, route="ACTION", route_key="cmo.generate_hashtags", status="PLANNED", now=T0)

    cols = "(tenant_id, investigation_id, planned_turn_id, plan, plan_hash, status, requested_by, created_at, expires_at{extra})"
    vals = "(:t, :inv, :turn, '{{}}'::jsonb, :h, '{status}', :u, now(), now() + interval '30 minutes'{more})"
    base = dict(t=str(a), inv=str(inv), u=str(app_user), h="c" * 64)
    with pytest.raises(DENIED):  # one planned turn, one plan (UNIQUE)
        app_exec(a, "INSERT INTO investigation_plan " + cols.format(extra="") + " VALUES " + vals.format(status="AWAITING_APPROVAL", more=""), turn=str(first_turn), **base)
    done = bare_turn()
    with pytest.raises(DENIED):  # born APPROVED (with every column the CHECK wants): the guard trigger refuses a plan that does not start AWAITING_APPROVAL
        app_exec(a, "INSERT INTO investigation_plan " + cols.format(extra=", execution_turn_id, decided_by, decided_at") + " VALUES "
                 + vals.format(status="APPROVED", more=", :turn, :u, now()"), turn=str(done), **base)
    with pytest.raises(DENIED):  # AWAITING_APPROVAL but no CREATED event in the transaction: the deferred constraint trigger fails the commit
        app_exec(a, "INSERT INTO investigation_plan " + cols.format(extra="") + " VALUES " + vals.format(status="AWAITING_APPROVAL", more=""), turn=str(done), **base)
    assert plan_repo.get_by_planned_turn(a, done) is None and len(plan_repo.list_for_investigation(a, inv)) == 1


def test_checks_reject_a_bad_hash_an_inverted_expiry_and_an_inconsistent_approval(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    for sql in ("UPDATE investigation_plan SET decision_reason = repeat('x', 201) WHERE id = :i",):
        with pytest.raises(DENIED):
            with tenant_scope(a) as conn:
                conn.execute(text(sql), {"i": str(built.plan_id)})
    with migrate_engine.connect() as conn:
        defs = {r[0]: r[1] for r in conn.execute(text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'investigation_plan'::regclass AND contype = 'c'"))}
    assert "expires_at > created_at" in defs["investigation_plan_expiry_check"]
    assert "execution_turn_id IS NOT NULL" in defs["investigation_plan_approved_check"] and "decided_by IS NOT NULL" in defs["investigation_plan_declined_check"]
    assert "0-9a-f" in defs["investigation_plan_hash_check"]


def test_only_one_plan_per_investigation_can_be_open(two_tenants, app_user):
    a, _ = two_tenants
    inv, first, _ = new_plan(a, app_user)
    # the repository supersedes the older plan when a newer one is made
    inv, second, _ = new_plan(a, app_user, inv)
    assert plan_repo.get(a, inv, first.plan_id)["status"] == "SUPERSEDED" and plan_repo.get(a, inv, second.plan_id)["status"] == "AWAITING_APPROVAL"
    # and the database refuses two open plans even if the repository were bypassed
    with get_engine().connect() as conn:
        idx = conn.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'investigation_plan_one_open'")).scalar_one()
    assert "UNIQUE" in idx and "AWAITING_APPROVAL" in idx


def test_event_rows_must_have_a_consistent_shape(two_tenants, app_user):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    bad = [
        ("CREATED", "'AWAITING_APPROVAL'", "'AWAITING_APPROVAL'", "'SYSTEM'", "NULL"),  # CREATED has no from-status
        ("APPROVED", "'AWAITING_APPROVAL'", "'DECLINED'", "'SYSTEM'", "NULL"),  # to-status must equal the event
        ("APPROVAL_REFUSED", "NULL", "'APPROVED'", "'SYSTEM'", "NULL"),  # a non-transition event has no statuses
        ("APPROVAL_REFUSED", "NULL", "NULL", "'USER'", "NULL"),  # a USER event names its user
        ("APPROVAL_REFUSED", "NULL", "NULL", "'SYSTEM'", f"'{app_user}'"),  # a SYSTEM event has no user
        ("BOGUS", "NULL", "NULL", "'SYSTEM'", "NULL"),
    ]
    for event, frm, to, kind, actor in bad:
        with pytest.raises(DENIED):
            app_exec(a, f"INSERT INTO investigation_plan_event (tenant_id, plan_id, event, from_status, to_status, actor_kind, actor_user_id, plan_hash) "
                        f"VALUES (:t, :i, '{event}', {frm}, {to}, {kind}, {actor}, :h)", t=str(a), i=str(built.plan_id), h=built.plan_hash)
    assert len(plan_repo.events(a, built.plan_id)) == 1


def test_a_non_status_event_cannot_be_used_to_fake_a_transition_through_the_repository(two_tenants, app_user):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    for ev in ("CREATED", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED"):
        with pytest.raises(ValueError):
            plan_repo.record_event(a, built.plan_id, event=ev, actor_user_id=app_user)


# ------------------------------------------------------------------------------------------------ tenant isolation, as the real app role (AC-A11)
def test_a_tenant_sees_only_its_own_plans_and_events(two_tenants, app_user):
    a, b = two_tenants
    inv, built, _ = new_plan(a, app_user)
    assert app_exec(b, "SELECT count(*) FROM investigation_plan").scalar_one() == 0
    assert app_exec(b, "SELECT count(*) FROM investigation_plan_event").scalar_one() == 0
    assert app_exec(a, "SELECT count(*) FROM investigation_plan").scalar_one() == 1
    assert plan_repo.get(b, inv, built.plan_id) is None and plan_repo.list_for_investigation(b, inv) == [] and plan_repo.events(b, built.plan_id) == []
    assert plan_repo.expire_if_due(b, built.plan_id, now=T0 + timedelta(days=1)) is False
    assert plan_repo.decline(b, plan_id=built.plan_id, investigation_id=inv, user_id=app_user, reason=None, note_content="n", now=T0) is False
    with pytest.raises(plan_repo.PlanNotFound):
        plan_repo.record_event(b, built.plan_id, event="APPROVAL_REFUSED", actor_user_id=app_user)
    assert plan_repo.get(a, inv, built.plan_id)["status"] == "AWAITING_APPROVAL"


def test_a_tenant_cannot_write_a_row_for_another_tenant_or_attach_an_event_to_a_foreign_plan(two_tenants, app_user):
    a, b = two_tenants
    inv, built, _ = new_plan(a, app_user)
    with pytest.raises(DENIED):  # an event for A's plan, written under B's context: the composite (tenant_id, plan_id) FK and the policy refuse it
        app_exec(b, "INSERT INTO investigation_plan_event (tenant_id, plan_id, event, actor_kind, plan_hash) VALUES (:t, :i, 'APPROVAL_REFUSED', 'SYSTEM', :h)",
                 t=str(b), i=str(built.plan_id), h=built.plan_hash)
    with pytest.raises(DENIED):  # an event stamped with A's tenant id under B's context
        app_exec(b, "INSERT INTO investigation_plan_event (tenant_id, plan_id, event, actor_kind, plan_hash) VALUES (:t, :i, 'APPROVAL_REFUSED', 'SYSTEM', :h)",
                 t=str(a), i=str(built.plan_id), h=built.plan_hash)
    assert len(plan_repo.events(a, built.plan_id)) == 1


def test_no_tenant_context_sees_nothing_and_writes_nothing(two_tenants, app_user):
    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    eng = create_engine(os.environ["DATABASE_URL_APP"], poolclass=NullPool)  # the app role on a fresh connection, no tenant context at all
    try:
        with eng.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM investigation_plan")).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM investigation_plan_event")).scalar_one() == 0
            with pytest.raises(DENIED):
                conn.execute(text("INSERT INTO investigation_plan_event (tenant_id, plan_id, event, actor_kind, plan_hash) VALUES (:t, :i, 'APPROVAL_REFUSED', 'SYSTEM', :h)"),
                             {"t": str(a), "i": str(built.plan_id), "h": built.plan_hash})
    finally:
        eng.dispose()


def test_the_tenant_cleanup_can_purge_the_new_tables_children_first(two_tenants, app_user, migrate_engine):
    """The fixtures purge every tenant a test touched (children before parents, read from the catalog); a plan with events and an execution turn must not block it."""
    from testkit.tenant_cleanup import purge_tenants  # (tools/ is on the path through tests/integration/conftest.py)

    a, _ = two_tenants
    inv, built, _ = new_plan(a, app_user)
    plan_repo.decline(a, plan_id=built.plan_id, investigation_id=inv, user_id=app_user, reason=None, note_content="n", now=T0 + timedelta(seconds=1))
    purge_tenants(migrate_engine, [a])
    assert app_exec(a, "SELECT count(*) FROM investigation_plan").scalar_one() == 0
