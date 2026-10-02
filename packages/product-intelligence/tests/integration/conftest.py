"""Integration fixtures — require a real Postgres reachable at DATABASE_URL_APP /
DATABASE_URL with product-intelligence's migrations already applied (see
migrations/README.md). Skipped automatically when those env vars aren't set, so
`pytest tests/unit` continues to need no database at all.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

_APP_URL = os.environ.get("DATABASE_URL_APP")
_MIGRATE_URL = os.environ.get("DATABASE_URL")

_SKIP_REASON = "DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres"


def pytest_collection_modifyitems(config, items):
    """`pytestmark` assigned at conftest.py module level does not apply to sibling test
    modules in this pytest version (only within the same file) — without this hook, tests
    in this directory error out (fixture ArgumentError) instead of skipping cleanly when no
    DB is configured, which silently breaks the "never live calls without a DB" contract this
    conftest's own docstring promises. Applied via the standard hook instead so every test
    collected under tests/integration/ is skipped, not just ones in this file."""
    if _APP_URL and _MIGRATE_URL:
        return
    skip_marker = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if "tests/integration" in str(item.fspath).replace("\\", "/") or "tests\\integration" in str(item.fspath):
            item.add_marker(skip_marker)

# Deletion order respects FK dependencies (children before parents) — same rationale/caveat as
# competitor-intelligence's own fixture: this DELETE runs via migrate_engine (metrion_migrate
# role, FORCE ROW LEVEL SECURITY'd, no BYPASSRLS), so an unscoped DELETE with no tenant context
# set matches zero rows in practice. Kept for parity with the CI/calc-engine pattern; test
# correctness doesn't depend on it actually deleting anything, since every test uses a fresh
# random tenant_id (two_tenants) and asserts only against rows it reads back by their own id.
_PI_TABLES: tuple[str, ...] = (
    "product_embedding",
    "supplier_lead",
    "product_review_insight",
    "product_candidate",
    "pi_research_run",
    "niche_brief",
    "pi_tenant_config",
)


@pytest.fixture
def app_engine():
    engine = create_engine(_APP_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def migrate_engine():
    engine = create_engine(_MIGRATE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def two_tenants():
    return uuid.uuid4(), uuid.uuid4()


@pytest.fixture(autouse=True)
def _clean_pi_tables(migrate_engine):
    """Each test starts and ends with empty PI-owned tables — as the table owner, so RLS
    itself never gets in the way of test cleanup."""
    with migrate_engine.begin() as conn:
        for t in _PI_TABLES:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in _PI_TABLES:
            conn.execute(text(f"DELETE FROM {t}"))


# --- Tenant-scoped cleanup of everything a test created --------------------------------------
# The `DELETE FROM <table>` fixtures in this suite never removed tenant-owned rows: every such
# table is FORCE ROW LEVEL SECURITY, which applies to the table owner too, so a DELETE with no
# tenant context matches nothing and silently deletes zero rows. This fixture instead purges the
# tenants the code under test actually touched, through RLS, one tenant at a time — see
# tools/testkit/tenant_cleanup.py for the mechanism and why it cannot touch another tenant.
import pathlib  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "tools"))
from testkit.tenant_cleanup import TRACKER as _tenant_tracker  # noqa: E402

_tenant_tracker.install()


@pytest.fixture(autouse=True)
def _purge_tenants_created_by_test(migrate_engine):
    _tenant_tracker.reset()
    yield
    _tenant_tracker.purge(migrate_engine)
