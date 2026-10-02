"""Integration fixtures — require a real Postgres reachable at DATABASE_URL_APP /
DATABASE_URL with competitor-intelligence's migrations already applied (see
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

pytestmark = pytest.mark.skipif(
    not _APP_URL or not _MIGRATE_URL,
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

# Deletion order respects FK dependencies (children before parents). NOTE: this DELETE runs
# via migrate_engine (metrion_migrate role), which is FORCE ROW LEVEL SECURITY'd like every
# tenant table here and has no BYPASSRLS — an unscoped DELETE with no tenant context set
# matches zero rows, so this fixture is a documented no-op in practice (verified directly
# against the container). It's kept for parity with calc-engine's/data-foundation's identical
# pattern rather than removed; test correctness doesn't depend on it actually deleting
# anything, since every test uses a fresh random tenant_id (two_tenants) and asserts only
# against rows it reads back by their own returned id.
_CI_TABLES: tuple[str, ...] = (
    "ci_candidate_relevance",
    "ci_candidate",
    "ci_discovery_run",
    "ci_search_result",
    "ci_search_query",
    "competitor_snapshot_field",
    "competitor_price_event",
    "ci_digest_subscription",
    "ci_tenant_config",
    "competitor_listing_insight",
    "competitor_review_insight",
    "competitor_evidence",
    "competitor_snapshot",
    "ci_capture_run",
    "competitor_url",
    "seller_product_profile",
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
def _clean_ci_tables(migrate_engine):
    """Each test starts and ends with empty CI-owned tables — as the table owner, so RLS
    itself never gets in the way of test cleanup."""
    with migrate_engine.begin() as conn:
        for t in _CI_TABLES:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in _CI_TABLES:
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
