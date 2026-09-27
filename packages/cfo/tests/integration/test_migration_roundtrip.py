"""upgrade -> downgrade -> upgrade leaves a clean schema. Mirrors
`competitor-intelligence/tests/integration/test_migration_roundtrip.py`'s shape exactly, for
CFO's `20260923_0001_cfo_tables.py` migration (`leak_finding`, `agent_data_request`).
"""

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


_CFO_TABLE_NAMES = (
    "leak_finding",
    "agent_data_request",
)


def test_upgrade_downgrade_upgrade_round_trip(migrate_engine) -> None:
    _run_alembic("downgrade", "base")
    with migrate_engine.connect() as conn:
        for table in _CFO_TABLE_NAMES:
            exists = conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
            ).scalar()
            assert not exists, f"{table} should not exist after downgrade to base"

    _run_alembic("upgrade", "head")
    with migrate_engine.connect() as conn:
        for table in _CFO_TABLE_NAMES:
            exists = conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
            ).scalar()
            assert exists, f"{table} should exist after upgrade to head"
