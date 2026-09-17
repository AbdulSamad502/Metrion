"""Migration 20260917_0003 inlines a literal snapshot of SEED_DEFINITIONS rather than
importing it live (see that migration's docstring for why: a migration must stay a truthful
historical record). This test is the drift detector that claim depends on — if
`calc_engine.definitions.seed_definitions.SEED_DEFINITIONS` ever changes without a new
migration being added, this fails loudly instead of the mismatch going unnoticed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from calc_engine.definitions.seed_definitions import SEED_DEFINITIONS as LIVE_SEED_DEFINITIONS

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "versions" / "20260917_0003_seed_formula_definitions.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("seed_formula_definitions_migration", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_snapshot_matches_live_seed_definitions():
    migration = _load_migration_module()
    assert migration.SEED_DEFINITIONS == LIVE_SEED_DEFINITIONS
