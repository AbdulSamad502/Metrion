"""Integration fixtures — require a real Postgres reachable at DATABASE_URL_APP /
DATABASE_URL with calc-engine's migrations already applied (see migrations/README.md).
Skipped automatically when those env vars aren't set, so `pytest tests/unit` continues to
need no database at all.
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
def _clean_engine_tables(migrate_engine):
    """Clears the PLATFORM-DEFAULT rows (NULL tenant_id) these config tables hold, which are the
    only rows an unscoped DELETE can reach: FORCE ROW LEVEL SECURITY applies to the table owner
    too, so for tenant-owned rows this DELETE matches nothing. Tenant-owned rows are removed by
    `_purge_tenants_created_by_test` below, which deletes through each tenant's RLS context."""
    tables = (
        "metric_result",
        "manual_adjustment",
        "discount_bearer_config",
        "reconciliation_tolerance_config",
        "severity_config",
        "anomaly_detection_config",
        "gst_lookup_result",
        "product_feasibility_estimate",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
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
