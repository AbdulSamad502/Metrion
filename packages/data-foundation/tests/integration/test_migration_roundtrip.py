"""Alembic migration round-trip — downgrade then upgrade must restore every table and RLS."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

_TABLES = {"report_file", "ingestion_run", "sales_line", "line_component", "report_period", "validation_finding"}


def _alembic_config() -> Config:
    cfg = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PACKAGE_ROOT / "migrations"))
    return cfg


def test_downgrade_then_upgrade_restores_all_tables_and_rls(migrate_engine):
    cfg = _alembic_config()

    command.downgrade(cfg, "base")
    inspector = inspect(migrate_engine)
    assert not (_TABLES & set(inspector.get_table_names())), "downgrade left tables behind"

    command.upgrade(cfg, "head")
    inspector = inspect(migrate_engine)
    assert _TABLES <= set(inspector.get_table_names()), "upgrade did not recreate every table"

    with migrate_engine.connect() as conn:
        forced = conn.execute(
            text("SELECT relname FROM pg_class WHERE relforcerowsecurity = true AND relname = ANY(:names)").bindparams(
                names=list(_TABLES)
            )
        ).fetchall()
    assert {r[0] for r in forced} == _TABLES
