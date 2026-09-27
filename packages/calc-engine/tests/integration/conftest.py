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
    """Each test starts and ends with empty engine-owned tables — as the table owner, so
    RLS itself never gets in the way of test cleanup."""
    tables = (
        "metric_result",
        "manual_adjustment",
        "discount_bearer_config",
        "reconciliation_tolerance_config",
        "severity_config",
        "anomaly_detection_config",
        "gst_lookup_result",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
