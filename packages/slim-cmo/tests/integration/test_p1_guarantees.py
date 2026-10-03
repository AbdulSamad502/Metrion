"""Repeatable form of the independent P1 verification (CP1 review): probes the REAL catalog and
the REAL application role rather than re-using the helper layer, so a regression in grants,
role attributes or concurrency behaviour is caught even if the seed helpers keep working."""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from slim_cmo.repositories.tenant_context import tenant_scope

from . import _seed

TENANT_TABLES = [
    "seller_image_asset", "product_image_analysis", "cmo_generation", "cmo_title_option",
    "cmo_title_approval", "seller_fact", "cmo_niche_term", "cmo_trend_report",
]
PLATFORM_TABLES = ["vision_eval_run", "format_constraint", "cmo_platform_config"]
ALL_TABLES = TENANT_TABLES + PLATFORM_TABLES

# The complete, exact privilege set metrion_app must hold. Anything else is a regression.
EXPECTED_APP_PRIVILEGES = {
    "seller_image_asset": {"INSERT", "SELECT", "UPDATE"},
    "cmo_niche_term": {"INSERT", "SELECT", "UPDATE"},
    "product_image_analysis": {"INSERT", "SELECT"},
    "cmo_generation": {"INSERT", "SELECT"},
    "cmo_title_option": {"INSERT", "SELECT"},
    "cmo_title_approval": {"INSERT", "SELECT"},
    "seller_fact": {"INSERT", "SELECT"},
    "cmo_trend_report": {"INSERT", "SELECT"},
    "vision_eval_run": {"SELECT"},
    "format_constraint": {"SELECT"},
    "cmo_platform_config": {"SELECT"},
}


def test_application_role_is_not_privileged(migrate_engine):
    with migrate_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = 'metrion_app'")
        ).one()
        owners = {r[0] for r in conn.execute(
            text("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = ANY(:t)"), {"t": ALL_TABLES})}
        memberships = conn.execute(text(
            "SELECT count(*) FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'metrion_app')"
        )).scalar_one()
    assert tuple(row) == (False, False, False, False), "metrion_app must be unprivileged and must NOT bypass RLS"
    assert "metrion_app" not in owners, "an owning role is not subject to RLS unless FORCE is on; the app must not own tables"
    assert memberships == 0, "metrion_app must not inherit any other role (e.g. the migration role)"


def test_every_tenant_table_has_row_level_security_forced(migrate_engine):
    with migrate_engine.connect() as conn:
        flags = {r[0]: (r[1], r[2]) for r in conn.execute(
            text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = ANY(:t)"), {"t": TENANT_TABLES})}
        no_tenant_col = [t for t in TENANT_TABLES if not conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name='tenant_id' AND is_nullable='NO'"), {"t": t}).first()]
    assert flags == {t: (True, True) for t in TENANT_TABLES}
    assert no_tenant_col == []


def test_application_privileges_are_exactly_the_documented_set(migrate_engine):
    with migrate_engine.connect() as conn:
        for table, expected in EXPECTED_APP_PRIVILEGES.items():
            rows = conn.execute(text(
                "SELECT grantee, privilege_type FROM information_schema.role_table_grants "
                "WHERE table_name = :t AND grantee IN ('metrion_app','PUBLIC')"), {"t": table}).all()
            app = {p for g, p in rows if g == "metrion_app"}
            public = {p for g, p in rows if g == "PUBLIC"}
            assert app == expected, f"{table}: app privileges {sorted(app)} != {sorted(expected)}"
            assert public == set(), f"{table}: PUBLIC must hold nothing, has {sorted(public)}"
        column_acls = conn.execute(text(
            "SELECT count(*) FROM pg_attribute a JOIN pg_class t ON t.oid = a.attrelid "
            "WHERE t.relname = ANY(:t) AND a.attacl IS NOT NULL"), {"t": ALL_TABLES}).scalar_one()
    assert column_acls == 0, "column-level ACLs could bypass the table-level REVOKEs"


def test_no_binary_float_or_money_columns_and_only_one_money_field(migrate_engine):
    """AC7 (no image bytes) and the no-float / paise-only money rule, checked on the catalog."""
    with migrate_engine.connect() as conn:
        bad_types = conn.execute(text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ANY(:t) AND data_type IN ('bytea','real','double precision','numeric','money','oid')"),
            {"t": ALL_TABLES}).all()
        money_like = conn.execute(text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ANY(:t) AND column_name ~* '(^|_)(gst|price|fee|rate|amount|paise|tax)(_|$)'"),
            {"t": ALL_TABLES}).all()
    assert bad_types == []
    assert [tuple(r) for r in money_like] == [("seller_fact", "value_paise", "bigint")]


@pytest.mark.parametrize(
    "statement",
    [
        "SET ROLE metrion_migrate",
        "SET ROLE metrion",
        "TRUNCATE cmo_generation",
        "ALTER TABLE cmo_generation DISABLE ROW LEVEL SECURITY",
        "DROP POLICY tenant_isolation ON cmo_generation",
        "CREATE TABLE zz_probe (id int)",
        "SET LOCAL row_security = off; SELECT count(*) FROM cmo_generation",
    ],
)
def test_application_role_cannot_escalate_or_bypass_rls(two_tenants, statement):
    tenant, _ = two_tenants
    with pytest.raises(DBAPIError):
        with tenant_scope(tenant) as conn:
            for part in statement.split(";"):
                if part.strip():
                    conn.execute(text(part))


def test_reused_pooled_connection_fails_closed_without_leaking_rows(two_tenants):
    """After a tenant transaction ends, the pooled connection carries `app.current_tenant_id = ''`
    (not unset). A later unscoped query must ERROR (loud) or see nothing - never see tenant data."""
    from sqlalchemy import create_engine
    import os

    tenant, _ = two_tenants
    _seed.insert_asset(tenant)
    pooled = create_engine(os.environ["DATABASE_URL_APP"], pool_size=1, max_overflow=0)
    try:
        with pooled.connect() as conn, conn.begin():
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            assert conn.execute(text("SELECT count(*) FROM seller_image_asset")).scalar_one() == 1
        try:
            with pooled.connect() as conn:  # same physical connection, no context
                assert conn.execute(text("SELECT count(*) FROM seller_image_asset")).scalar_one() == 0
        except DBAPIError:
            pass  # an error is also fail-closed
    finally:
        pooled.dispose()


def test_a_verified_evaluation_cannot_be_unpassed_or_edited_while_an_analysis_relies_on_it(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    asset = _seed.insert_asset(tenant)
    run = _seed.insert_vision_eval_run(migrate_engine, provider="p", model="m", schema_version="v1", passed=True)
    _seed.insert_analysis(
        tenant, asset,
        attributes=[{"name": "c", "value": "b", "basis": "IMAGE_OBSERVED", "trust_state": "EVAL_PASSED"}],
        eval_gate_ref=run, provider="p", model="m", schema_version="v1",
    )
    for statement in (
        "UPDATE vision_eval_run SET passed = false WHERE id = :i",
        "UPDATE vision_eval_run SET model = 'other' WHERE id = :i",
        "UPDATE vision_eval_run SET schema_version = 'v9' WHERE id = :i",
        "DELETE FROM vision_eval_run WHERE id = :i",
    ):
        with pytest.raises(DBAPIError):
            with migrate_engine.begin() as conn:
                conn.execute(text(statement), {"i": str(run)})


# ---------------------------------------------------------------------------------------------
# Real concurrency
# ---------------------------------------------------------------------------------------------


def test_sixteen_racing_identical_completions_produce_exactly_one_artefact(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _seed.insert_format_constraint(migrate_engine, marketplace="AMAZON", version=7001)
    barrier = threading.Barrier(16)

    def racer(_: int) -> str:
        barrier.wait()
        try:
            _seed.insert_generation(tenant, request_key="race", marketplace="AMAZON", format_constraint_ref=constraint)
            return "ok"
        except DBAPIError as exc:
            return "duplicate" if "unique" in str(exc).lower() else f"other: {exc}"

    with ThreadPoolExecutor(16) as pool:
        outcome = Counter(pool.map(racer, range(16)))
    with tenant_scope(tenant) as conn:
        stored = conn.execute(text("SELECT count(*) FROM cmo_generation WHERE request_key = 'race' AND status = 'COMPLETE'")).scalar_one()
    assert outcome == {"ok": 1, "duplicate": 15}
    assert stored == 1


def test_racing_failures_never_block_the_eventual_success(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    constraint = _seed.insert_format_constraint(migrate_engine, marketplace="AMAZON", version=7002)
    kw = dict(request_key="retry-race", marketplace="AMAZON", format_constraint_ref=constraint)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: _seed.insert_generation(tenant, status="FAILED", **kw), range(8)))
    _seed.insert_generation(tenant, **kw)
    with tenant_scope(tenant) as conn:
        counts = dict(conn.execute(text("SELECT status, count(*) FROM cmo_generation WHERE request_key = 'retry-race' GROUP BY status")).all())
    assert counts == {"FAILED": 8, "COMPLETE": 1}
