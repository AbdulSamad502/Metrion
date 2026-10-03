"""RLS fail-closed verification — auth.md §7.3, spec AC19 / matrix B.

For EVERY tenant-owned table: (1) cross-tenant SELECT sees nothing, (2) an unset tenant context
sees nothing, (3) a cross-tenant INSERT is rejected by the policy's WITH CHECK (the four
tables that need no parents — enough to prove the mechanism end to end; the FK-dependent
tables are covered by the composite-FK tests in test_schema_constraints.py), (4)
`tenant_scope(None)` raises before any query runs. Plus the platform-config policy: platform
default rows are readable by every tenant but writable by none of them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from slim_cmo.repositories.tenant_context import tenant_scope

from . import _seed


def _chain(tenant: uuid.UUID) -> dict[str, uuid.UUID]:
    """One row in every tenant-owned table, FK parents first, all under `tenant`."""
    asset = _seed.insert_asset(tenant)
    analysis = _seed.insert_analysis(tenant, asset)
    constraint = _seed.insert_format_constraint(_MIGRATE[0], marketplace="AMAZON", version=_next_version())
    generation = _seed.insert_generation(tenant, format_constraint_ref=constraint, image_analysis_id=analysis)
    option = _seed.insert_option(tenant, generation)
    approval = _seed.insert_approval(tenant, generation, option_id=option)
    fact = _seed.insert_fact(tenant, cmo_generation_id=generation)
    term = _seed.insert_niche_term(tenant)
    trend_generation = _seed.insert_generation(
        tenant, output_type="TREND_REPORT", marketplace=None, status="COMPLETE"
    )
    report = _seed.insert_trend_report(tenant, trend_generation)
    return {
        "seller_image_asset": asset,
        "product_image_analysis": analysis,
        "cmo_generation": generation,
        "cmo_title_option": option,
        "cmo_title_approval": approval,
        "seller_fact": fact,
        "cmo_niche_term": term,
        "cmo_trend_report": report,
    }


_MIGRATE: list = []  # the per-test migrate engine, set by the autouse fixture below
_VERSION = [0]


def _next_version() -> int:
    _VERSION[0] += 1
    return _VERSION[0]


@pytest.fixture(autouse=True)
def _bind_migrate_engine(migrate_engine):
    _MIGRATE.clear()
    _MIGRATE.append(migrate_engine)
    yield
    _MIGRATE.clear()


TENANT_TABLES = [
    "seller_image_asset",
    "product_image_analysis",
    "cmo_generation",
    "cmo_title_option",
    "cmo_title_approval",
    "seller_fact",
    "cmo_niche_term",
    "cmo_trend_report",
]


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_cross_tenant_select_is_isolated(two_tenants, table):
    tenant_a, tenant_b = two_tenants
    rows_a = _chain(tenant_a)

    with tenant_scope(tenant_a) as conn:
        own = conn.execute(text(f"SELECT id FROM {table} WHERE id = :id"), {"id": str(rows_a[table])}).all()
    assert len(own) == 1, f"tenant A must see its own {table} row"

    with tenant_scope(tenant_b) as conn:
        seen = conn.execute(text(f"SELECT id FROM {table} WHERE id = :id"), {"id": str(rows_a[table])}).all()
        total = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    assert seen == [], f"tenant B must not see tenant A's {table} row"
    assert total == 0, f"tenant B has no {table} rows of its own, so must see zero"


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_unset_tenant_context_yields_zero_rows(two_tenants, app_engine, table):
    tenant_a, _ = two_tenants
    _chain(tenant_a)
    # Brand-new connection (NullPool) with NO set_config at all: current_setting(..., true) is NULL.
    with app_engine.connect() as conn:
        count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    assert count == 0


def test_tenant_scope_none_fails_closed():
    with pytest.raises(ValueError, match="tenant_id=None"):
        with tenant_scope(None):
            pytest.fail("no query may run without tenant context")


_CROSS_INSERTS: dict[str, Callable[[uuid.UUID], str]] = {
    "seller_image_asset": lambda t: (
        "INSERT INTO seller_image_asset (tenant_id, storage_uri, sha256, content_type, byte_size, uploaded_by, status) "
        f"VALUES ('{t}', 'file:///x', '{'a' * 64}', 'image/jpeg', 10, '{uuid.uuid4()}', 'ACTIVE')"
    ),
    "cmo_niche_term": lambda t: (
        f"INSERT INTO cmo_niche_term (tenant_id, term, origin, status) VALUES ('{t}', 'bottle', 'SELLER_STATED', 'SUGGESTED')"
    ),
    "seller_fact": lambda t: (
        f"INSERT INTO seller_fact (tenant_id, fact_type, fact_value, provided_by) VALUES ('{t}', 'BRAND', 'x', '{uuid.uuid4()}')"
    ),
    "cmo_generation": lambda t: (
        "INSERT INTO cmo_generation (tenant_id, output_type, marketplace, input_mode, status, failure_reason, request_key, generated_by) "
        f"VALUES ('{t}', 'TITLE_SET', 'AMAZON', 'INDEPENDENT', 'FAILED', 'x', 'k', '{uuid.uuid4()}')"
    ),
}


@pytest.mark.parametrize("table", sorted(_CROSS_INSERTS))
def test_cross_tenant_insert_is_rejected_by_policy(two_tenants, table):
    tenant_a, tenant_b = two_tenants
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_scope(tenant_a) as conn:  # context says A ...
            conn.execute(text(_CROSS_INSERTS[table](tenant_b)))  # ... row claims B


def test_platform_config_default_is_readable_but_not_writable_by_tenants(two_tenants, migrate_engine):
    tenant_a, tenant_b = two_tenants
    key = f"test_key_{uuid.uuid4().hex[:8]}"
    with migrate_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (NULL, :k, '1'::jsonb, '2026-10-01')"),
            {"k": key},
        )
    for tenant in (tenant_a, tenant_b):
        with tenant_scope(tenant) as conn:
            seen = conn.execute(text("SELECT value FROM cmo_platform_config WHERE key = :k"), {"k": key}).all()
        assert len(seen) == 1, "a platform default is visible to every tenant"

    # The application role has no write grant at all on this table ...
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, :k, '2'::jsonb, '2026-10-01')"),
                {"t": str(tenant_a), "k": f"test_{uuid.uuid4().hex[:8]}"},
            )


def test_tenant_override_is_invisible_to_other_tenants(two_tenants, migrate_engine):
    tenant_a, tenant_b = two_tenants
    key = f"test_override_{uuid.uuid4().hex[:8]}"
    with migrate_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant_a)})
        conn.execute(
            text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, :k, '9'::jsonb, '2026-10-01')"),
            {"t": str(tenant_a), "k": key},
        )
    with tenant_scope(tenant_a) as conn:
        assert len(conn.execute(text("SELECT 1 FROM cmo_platform_config WHERE key = :k"), {"k": key}).all()) == 1
    with tenant_scope(tenant_b) as conn:
        assert conn.execute(text("SELECT 1 FROM cmo_platform_config WHERE key = :k"), {"k": key}).all() == []
