"""Integration fixtures — require a real Postgres reachable at DATABASE_URL_APP /
DATABASE_URL with cfo's migrations already applied (see `migrations/README.md`). Skipped
automatically when those env vars aren't set, so `pytest tests/unit` continues to need no
database at all. Mirrors `competitor-intelligence/tests/integration/conftest.py` exactly.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

_APP_URL = os.environ.get("DATABASE_URL_APP")
_MIGRATE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _APP_URL or not _MIGRATE_URL,
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

_CFO_TABLES: tuple[str, ...] = (
    "leak_finding",
    "agent_data_request",
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
def _clean_cfo_tables(migrate_engine):
    """Each test starts and ends with empty CFO-owned tables — as the table owner, so RLS
    itself never gets in the way of test cleanup."""
    with migrate_engine.begin() as conn:
        for t in _CFO_TABLES:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in _CFO_TABLES:
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
