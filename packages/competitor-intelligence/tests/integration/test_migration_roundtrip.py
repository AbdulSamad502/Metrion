"""upgrade -> downgrade -> upgrade leaves a clean schema. Mirrors calc-engine's/
data-foundation's own migration-roundtrip test shape."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _run_alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"


_CI_TABLE_NAMES = (
    "competitor_url",
    "ci_capture_run",
    "competitor_snapshot",
    "competitor_review_insight",
    "competitor_listing_insight",
    "ci_tenant_config",
    "competitor_price_event",
    "ci_search_query",
    "ci_search_result",
    "ci_discovery_run",
    "ci_candidate",
    "ci_candidate_relevance",
)


def test_upgrade_downgrade_upgrade_round_trip(migrate_engine) -> None:
    _run_alembic("downgrade", "base")
    with migrate_engine.connect() as conn:
        for table in _CI_TABLE_NAMES:
            exists = conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
            ).scalar()
            assert not exists, f"{table} should not exist after downgrade to base"

    _run_alembic("upgrade", "head")
    with migrate_engine.connect() as conn:
        for table in _CI_TABLE_NAMES:
            exists = conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
            ).scalar()
            assert exists, f"{table} should exist after upgrade to head"
