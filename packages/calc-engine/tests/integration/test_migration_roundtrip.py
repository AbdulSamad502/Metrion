"""Alembic migration round-trip — downgrade then upgrade must leave the schema in the same
usable state, run against the real migrate role (metrion_migrate), not the app role."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

_ENGINE_TABLES = {
    "formula_definition",
    "metric_result",
    "manual_adjustment",
    "discount_bearer_config",
    "gst_slab_reference",
    "fee_reference",
    "reconciliation_tolerance_config",
    "severity_config",
}

_FORCED_RLS_TABLES = {
    "metric_result",
    "manual_adjustment",
    "discount_bearer_config",
    "reconciliation_tolerance_config",
    "severity_config",
}


def _alembic_config() -> Config:
    cfg = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PACKAGE_ROOT / "migrations"))
    return cfg


def test_downgrade_then_upgrade_restores_all_engine_tables(migrate_engine):
    cfg = _alembic_config()

    command.downgrade(cfg, "base")
    inspector = inspect(migrate_engine)
    assert not (_ENGINE_TABLES & set(inspector.get_table_names())), "downgrade left engine tables behind"

    command.upgrade(cfg, "head")
    inspector = inspect(migrate_engine)
    assert _ENGINE_TABLES <= set(inspector.get_table_names()), "upgrade did not recreate every engine table"

    # RLS survives the round-trip too — not just table existence
    with migrate_engine.connect() as conn:
        forced = conn.execute(
            text("SELECT relname FROM pg_class WHERE relforcerowsecurity = true AND relname = ANY(:names)")
            .bindparams(names=list(_FORCED_RLS_TABLES))
        ).fetchall()
    assert {r[0] for r in forced} == _FORCED_RLS_TABLES

    # Seed data (migration 20260917_0003) survives the round-trip too — not just the empty table
    with migrate_engine.connect() as conn:
        seeded_count = conn.execute(text("SELECT count(*) FROM formula_definition")).scalar_one()
    assert seeded_count == 4
