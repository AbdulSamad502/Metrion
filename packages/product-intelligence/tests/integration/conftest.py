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

pytestmark = pytest.mark.skipif(
    not _APP_URL or not _MIGRATE_URL,
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

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
