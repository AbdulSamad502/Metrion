"""Integration fixtures — require a real Postgres reachable at DATABASE_URL_APP/DATABASE_URL
with data-foundation's migrations already applied. Skipped automatically otherwise, mirroring
packages/calc-engine/tests/integration/conftest.py."""

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

_TABLES = (
    "validation_finding",
    "line_component",
    "sales_line",
    "settlement_line",
    "report_period",
    "ingestion_run",
    "report_file",
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
def _clean_tables(migrate_engine):
    with migrate_engine.begin() as conn:
        for t in _TABLES:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in _TABLES:
            conn.execute(text(f"DELETE FROM {t}"))
