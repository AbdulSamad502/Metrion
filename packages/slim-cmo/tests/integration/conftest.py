"""Integration fixtures — require a real Postgres reachable at DATABASE_URL_APP / DATABASE_URL
with slim-cmo's migrations already applied (see migrations/README.md). Skipped automatically
(not errored) when those env vars aren't set, so `pytest tests/unit` needs no database.

Cleanup uses `tools/testkit/tenant_cleanup.py`: every tenant-owned table is FORCE ROW LEVEL
SECURITY, which applies to the table owner too, so an unscoped `DELETE` removes nothing. The
tracker records each tenant the code under test touched (via its `set_config` call) and purges
exactly those, through RLS, children before parents. The three platform tables (no RLS) are
cleaned here by their test-only markers — `row_kind = 'TEST_FIXTURE'`, `run_by = 'pytest'`,
`key LIKE 'test\\_%'` — so a real VERIFIED constraint or a real evaluation can never be removed.
"""

from __future__ import annotations

import os
import pathlib
import sys
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

_APP_URL = os.environ.get("DATABASE_URL_APP")
_MIGRATE_URL = os.environ.get("DATABASE_URL")

_SKIP_REASON = "DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres"


def pytest_collection_modifyitems(config, items):
    """`pytestmark` at conftest level does not propagate to sibling modules; skip every test
    under tests/integration/ explicitly when no database is configured."""
    if _APP_URL and _MIGRATE_URL:
        return
    skip_marker = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if "tests/integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip_marker)


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "tools"))
from testkit.tenant_cleanup import TRACKER as _tenant_tracker  # noqa: E402

_tenant_tracker.install()


@pytest.fixture
def app_engine():
    # NullPool: `set_config(..., true)` leaves '' (not unset) on a pooled connection after the
    # transaction, which would make a later unscoped statement fail on `''::uuid`.
    engine = create_engine(_APP_URL, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def migrate_engine():
    engine = create_engine(_MIGRATE_URL, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def two_tenants():
    return uuid.uuid4(), uuid.uuid4()


_CMO_TENANT_TABLES = (
    "cmo_trend_report",
    "seller_fact",
    "cmo_niche_term",
    "cmo_title_approval",
    "cmo_title_option",
    "cmo_generation",
    "product_image_analysis",
    "seller_image_asset",
)


def _erase_cmo_rows(migrate_engine, tenants) -> None:
    """Erase slim-cmo's rows for the tenants a test touched, in ONE transaction per tenant with
    constraints deferred: `cmo_generation` and `cmo_title_approval` reference each other at the
    table level (rows are acyclic), which the generic FK-ordering in `testkit.tenant_cleanup`
    cannot order. Scoped by tenant context + an explicit WHERE, so no other tenant is touched."""
    for tenant in sorted(set(tenants), key=str):
        with migrate_engine.begin() as conn:
            conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            for table in _CMO_TENANT_TABLES:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": str(tenant)})


@pytest.fixture(autouse=True)
def _cleanup_everything_the_test_created(migrate_engine):
    """slim-cmo rows first (deferred, see above), then anything else the tracker saw, then the
    test-marked platform rows (which tenant rows reference)."""
    _tenant_tracker.reset()
    yield
    _erase_cmo_rows(migrate_engine, _tenant_tracker.tenants)
    _tenant_tracker.purge(migrate_engine)
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM format_constraint WHERE row_kind = 'TEST_FIXTURE'"))
        conn.execute(text("DELETE FROM vision_eval_run WHERE run_by = 'pytest'"))
        conn.execute(text("DELETE FROM cmo_platform_config WHERE key LIKE 'test\\_%'"))
