"""Privilege / RLS boundary for CEO-owned history and evidence (B1 privilege audit, 2026-10-07).

`docker/postgres-init/02-roles.sql` gives metrion_app full CRUD on every new table via ALTER DEFAULT PRIVILEGES, so
a table is deletable by the application unless its migration REVOKEs. These tests pin the CEO-owned tables, and add a
drift guard over the whole schema so a NEW table cannot silently become app-deletable.

Catalog assertions use the owner connection; behavioural assertions connect as `metrion_app`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from backend.repositories import investigation_repo
from backend.tenant_context import tenant_scope
from tests.integration.test_ceo_foundation_rls import _investigation, _turn

pytestmark = pytest.mark.usefixtures("two_tenants")

CEO_HISTORY_TABLES = (
    "investigation", "investigation_message", "investigation_turn", "investigation_finding", "investigation_agent", "agent_run",
)
APPEND_ONLY = ("investigation_finding",)  # evidence: no UPDATE either

# Tables where metrion_app STILL holds DELETE (pre-existing, owned by other specs; reported, not changed, in B1's
# privilege audit - see docs/planning/ceo-build-status.md). The guard fails both ways: a new deletable table not listed
# here fails (silent grant), and a listed table that has been tightened fails (stale list - remove it).
KNOWN_APP_DELETABLE = frozenset({
    "agent_data_request", "alembic_version", "alembic_version_backend", "alembic_version_cfo",
    "alembic_version_competitor_intelligence", "alembic_version_data_foundation", "alembic_version_product_intelligence",
    "alembic_version_slim_cmo", "app_user",
    "ci_candidate", "ci_candidate_relevance", "ci_capture_run", "ci_digest_subscription", "ci_discovery_run",
    "ci_search_query", "ci_search_result", "competitor_evidence", "competitor_listing_insight",
    "competitor_price_event", "competitor_review_insight", "competitor_snapshot", "competitor_snapshot_field",
    "competitor_url",
    "gst_lookup_result", "ingestion_run", "leak_finding",
    "line_component", "membership",
    "metric_result", "niche_brief", "pi_research_run", "pi_tenant_config", "product_candidate", "product_embedding",
    "product_feasibility_estimate", "product_review_insight", "reconciliation_exception", "reconciliation_match",
    "reconciliation_run", "report_file", "report_period", "sales_line",
    "seller_product_profile", "settlement_line", "supplier_lead", "tenant",
    "validation_finding",
    # RAG (rag-knowledge.md AC6, 20261012_0015): deleting a document must remove its servable content in the same transaction, so the app role holds DELETE on the derived
    # chunk/embedding tables ONLY. rag_source (tombstone), the retrieval log, usage counters and outbox are not deletable; test_rag_foundation_rls.py pins the full grant matrix.
    "rag_chunk", "rag_chunk_embedding",
})


def _priv(conn, table: str, priv: str) -> bool:
    return bool(conn.execute(text("SELECT has_table_privilege('metrion_app', CAST(:t AS regclass), :p)"), {"t": table, "p": priv}).scalar_one())


def test_the_app_role_is_not_privileged(migrate_engine):
    with migrate_engine.connect() as conn:
        row = conn.execute(text("SELECT rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolname = 'metrion_app'")).one()
        owners = conn.execute(text("SELECT DISTINCT tableowner FROM pg_tables WHERE tablename = ANY(:t)"), {"t": list(CEO_HISTORY_TABLES)}).scalars().all()
    assert tuple(row) == (False, False, False)
    assert owners == ["metrion_migrate"]  # the app role owns nothing: an owner could ignore its own grants


@pytest.mark.parametrize("table", CEO_HISTORY_TABLES)
def test_ceo_history_tables_grant_the_app_no_delete_or_truncate(migrate_engine, table):
    with migrate_engine.connect() as conn:
        assert not _priv(conn, table, "DELETE")
        assert not _priv(conn, table, "TRUNCATE")


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_findings_are_append_only(migrate_engine, table):
    with migrate_engine.connect() as conn:
        assert _priv(conn, table, "SELECT") and _priv(conn, table, "INSERT")
        assert not _priv(conn, table, "UPDATE")


@pytest.mark.parametrize("table", CEO_HISTORY_TABLES)
def test_ceo_history_tables_are_force_rls_with_a_tenant_policy(migrate_engine, table):
    with migrate_engine.connect() as conn:
        rls = conn.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": table}).one()
        quals = conn.execute(text("SELECT qual, with_check FROM pg_policies WHERE tablename = :t"), {"t": table}).all()
    assert tuple(rls) == (True, True)
    assert quals, f"{table} has no policy"
    for qual, check in quals:
        assert "app.current_tenant_id" in qual and "app.current_tenant_id" in (check or ""), "policy must be tenant-keyed on read AND write"


@pytest.mark.parametrize("table", CEO_HISTORY_TABLES)
def test_a_real_app_role_delete_is_refused(two_tenants, app_user, table):
    tenant, _ = two_tenants
    inv = _investigation(tenant, app_user)
    turn = _turn(tenant, app_user, inv)
    investigation_repo.insert_finding(tenant, inv, turn_id=turn, source="CFO", action_key="k", status="COMPLETE")
    with pytest.raises((ProgrammingError, DBAPIError)):
        with tenant_scope(tenant) as conn:
            conn.execute(text(f"DELETE FROM {table}"))
    with tenant_scope(tenant) as conn:  # the rows survived
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() >= 1


def test_a_real_app_role_update_of_a_finding_is_refused_and_the_finding_is_unchanged(two_tenants, app_user):
    tenant, _ = two_tenants
    inv = _investigation(tenant, app_user)
    turn = _turn(tenant, app_user, inv)
    fid = investigation_repo.insert_finding(tenant, inv, turn_id=turn, source="CFO", action_key="k", status="COMPLETE",
                                            figure_refs=[{"kind": "ENGINE", "id": str(uuid.uuid4())}])
    with pytest.raises((ProgrammingError, DBAPIError)):
        with tenant_scope(tenant) as conn:
            conn.execute(text("UPDATE investigation_finding SET status = 'FAILED', figure_refs = '[]'::jsonb WHERE id = :i"), {"i": str(fid)})
    with tenant_scope(tenant) as conn:
        status, n = conn.execute(text("SELECT status, jsonb_array_length(figure_refs) FROM investigation_finding WHERE id = :i"), {"i": str(fid)}).one()
    assert (status, n) == ("COMPLETE", 1)


@pytest.mark.parametrize("sql", ("TRUNCATE investigation_finding", "ALTER TABLE investigation_finding DISABLE ROW LEVEL SECURITY"))
def test_the_app_role_cannot_bypass_rls_by_truncating_or_disabling_it(two_tenants, app_user, sql):
    tenant, _ = two_tenants
    with pytest.raises((ProgrammingError, DBAPIError)):
        with tenant_scope(tenant) as conn:
            conn.execute(text(sql))


def test_no_new_table_silently_becomes_deletable_by_the_app_role(migrate_engine):
    with migrate_engine.connect() as conn:
        tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars().all()
        deletable = {t for t in tables if _priv(conn, t, "DELETE")}
    assert deletable - KNOWN_APP_DELETABLE == set(), "new app-deletable table: REVOKE DELETE in its migration (or, if truly required, list it in KNOWN_APP_DELETABLE with a reason)"
    assert KNOWN_APP_DELETABLE - deletable == set(), "KNOWN_APP_DELETABLE is stale: these tables are no longer deletable - remove them"
    assert not (deletable & set(CEO_HISTORY_TABLES))


# ---- approval workflow (20261012_0019): the plan is updatable ONLY in its five decision columns; its history is append-only; neither table is deletable ----
APPROVAL_TABLES = ("investigation_plan", "investigation_plan_event")


@pytest.mark.parametrize("table", APPROVAL_TABLES)
def test_approval_tables_are_force_rls_and_not_deletable_by_the_app_role(migrate_engine, table):
    with migrate_engine.connect() as conn:
        rls = conn.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": table}).one()
        quals = conn.execute(text("SELECT qual, with_check FROM pg_policies WHERE tablename = :t"), {"t": table}).all()
        assert tuple(rls) == (True, True) and quals and all("app.current_tenant_id" in q and "app.current_tenant_id" in (c or "") for q, c in quals)
        assert not _priv(conn, table, "DELETE") and not _priv(conn, table, "TRUNCATE")
    assert table not in KNOWN_APP_DELETABLE


def test_the_plan_table_grants_update_only_on_its_decision_columns_and_events_are_append_only(migrate_engine):
    with migrate_engine.connect() as conn:
        def col(table: str, column: str) -> bool:
            return bool(conn.execute(text("SELECT has_column_privilege('metrion_app', CAST(:t AS regclass), :c, 'UPDATE')"), {"t": table, "c": column}).scalar_one())

        columns = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'investigation_plan'")).scalars().all()
        assert {c for c in columns if col("investigation_plan", c)} == {"status", "execution_turn_id", "decided_by", "decided_at", "decision_reason"}
        assert not _priv(conn, "investigation_plan", "UPDATE")  # a column-only grant is not a table-level UPDATE
        events = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'investigation_plan_event'")).scalars().all()
        assert not any(col("investigation_plan_event", c) for c in events)
        assert _priv(conn, "investigation_plan_event", "SELECT") and _priv(conn, "investigation_plan_event", "INSERT") and not _priv(conn, "investigation_plan_event", "UPDATE")
