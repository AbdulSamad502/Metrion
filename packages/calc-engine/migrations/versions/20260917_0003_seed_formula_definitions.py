"""seed formula_definition from src/calc_engine/definitions/seed_definitions.py's
SEED_DEFINITIONS — deterministic-engine.md §4.1 (F1-F6). The Python objects have existed
since Category A; this migration is the first time they're actually written into the table
they're meant to back, closing a real gap between "the definitions exist in code" and "the
definitions are queryable via formula_definition" (Category E, item 4).

The definitions below are inlined as a literal snapshot, deliberately not imported from
`calc_engine.definitions.seed_definitions` — a migration must remain a truthful historical
record of what was seeded at this point in time (F2: "changing a formula creates a new
version"); importing the live module would make this migration's behavior silently drift if
that module is edited later, which is exactly the kind of non-reproducibility F1-F6 exist to
prevent. `tests/unit/test_seed_definitions_migration_snapshot.py` asserts this snapshot
matches the live source exactly, so drift is caught rather than silently accepted — if that
test ever fails, the fix is a NEW migration adding the new version, never editing this one.

`effective_from` is seeded as this engine's own creation date (2026-01-01) — a technical
sequencing value for "the version has been current since the engine started operating", not a
business or marketplace fact.

Revision ID: 20260917_0003
Revises: 20260917_0002
Create Date: 2026-09-17
"""
from __future__ import annotations

import json
from typing import Any

from alembic import op
import sqlalchemy as sa

revision = "20260917_0003"
down_revision = "20260917_0002"
branch_labels = None
depends_on = None

# Verbatim snapshot of calc_engine.definitions.seed_definitions.SEED_DEFINITIONS as of this
# migration's authoring — see this file's docstring for why it is not imported live.
SEED_DEFINITIONS: dict[str, dict[str, Any]] = {
    "GROSS_ORDER_VALUE.v1": {
        "type": "call",
        "function": "gross_order_value",
    },
    "SELLER_FUNDED_DISCOUNTS.v1": {
        "type": "op",
        "op": "ADD",
        "terms": [
            {
                "required": True,
                "term": {
                    "type": "component_sum",
                    "component_codes": ["SELLER_DISCOUNT"],
                    "component_kind": "DISCOUNT",
                    "side": "INVOICE",
                },
            },
            {
                "required": True,
                "term": {
                    "type": "component_sum",
                    "component_codes": ["SHIPPING_DISCOUNT"],
                    "component_kind": "DISCOUNT",
                    "side": "INVOICE",
                    "bearer": "SELLER",
                },
            },
            {
                "required": True,
                "term": {
                    "type": "component_sum",
                    "component_codes": ["PLATFORM_DISCOUNT"],
                    "component_kind": "DISCOUNT",
                    "side": "INVOICE",
                    "bearer": "SELLER",
                },
            },
            {
                "required": True,
                "term": {
                    "type": "component_sum",
                    "component_codes": ["CASHBACK_DISCOUNT"],
                    "component_kind": "DISCOUNT",
                    "side": "INVOICE",
                    "bearer": "SELLER",
                },
            },
            {
                "required": True,
                "term": {
                    "type": "component_sum",
                    "component_codes": None,
                    "component_kind": "DISCOUNT",
                    "side": "INVOICE",
                    "bearer": "UNKNOWN",
                    "exclude_codes": ["SELLER_DISCOUNT"],
                },
            },
        ],
    },
    "NET_REALIZED_REVENUE.v1": {
        "type": "call",
        "function": "net_realized_revenue",
    },
    "CONTRIBUTION_PROFIT.v1": {
        "type": "call",
        "function": "contribution_profit",
    },
}

_EFFECTIVE_FROM = "2026-01-01"

_INSERT_SQL = sa.text(
    """
    INSERT INTO formula_definition (metric_code, formula_version, definition, effective_from)
    VALUES (:metric_code, :formula_version, CAST(:definition AS jsonb), :effective_from)
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    for formula_version, definition in SEED_DEFINITIONS.items():
        metric_code = formula_version.rsplit(".", 1)[0]
        bind.execute(
            _INSERT_SQL,
            {
                "metric_code": metric_code,
                "formula_version": formula_version,
                "definition": json.dumps(definition),
                "effective_from": _EFFECTIVE_FROM,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for formula_version in SEED_DEFINITIONS:
        metric_code = formula_version.rsplit(".", 1)[0]
        bind.execute(
            sa.text("DELETE FROM formula_definition WHERE metric_code = :metric_code AND formula_version = :formula_version"),
            {"metric_code": metric_code, "formula_version": formula_version},
        )
