"""Metric codes and definitions for the expense tracker — deterministic-engine.md §9.3 (Round 6) — all INACTIVE.

Nothing here is seeded into `formula_definition` (that needs a migration — Step 3) and none of it is in `SEED_DEFINITIONS`, whose migration-snapshot
test must keep passing. `ACTIVE_FORMULA_VERSIONS` records what is live today and is NOT changed by adding these versions: the new versions only become
active when the formula release date (Q15) is set by a deliberate, separate change.
"""

from __future__ import annotations

EXPENSE_METRIC_CODES: tuple[str, ...] = (
    "EXPENSE_TOTAL",
    "EXPENSE_BY_CATEGORY",
    "EXPENSE_BY_COST_CLASS",
    "EXPENSE_RECURRING_TOTAL",
    "EXPENSE_REVIEW_QUEUE_AMOUNT",
    "EXPENSE_INCLUDING_UNRESOLVED",
    "UNALLOCATED_ADVERTISING",
    "UNALLOCATED_STORAGE",
    "UNALLOCATED_OVERHEAD",
    "ALLOCATED_OVERHEAD",
    "FULLY_ALLOCATED_PROFIT",
    "TOTAL_PROFIT",
)

# metric_code -> the (inactive) formula version that would produce it
INACTIVE_FORMULA_VERSIONS: dict[str, str] = {
    **{code: f"{code}.v1" for code in EXPENSE_METRIC_CODES},
    "CONTRIBUTION_PROFIT": "CONTRIBUTION_PROFIT.v2",
}

# Every new definition is a `call` node onto a pure engine function (closed schema, definitions/schema.py).
INACTIVE_DEFINITIONS: dict[str, dict[str, object]] = {
    **{f"{code}.v1": {"type": "call", "function": "ledger_feed"} for code in EXPENSE_METRIC_CODES if code.startswith("EXPENSE_")},
    **{
        f"{code}.v1": {"type": "call", "function": "compute_profit_statement"}
        for code in EXPENSE_METRIC_CODES
        if not code.startswith("EXPENSE_")
    },
    "CONTRIBUTION_PROFIT.v2": {"type": "call", "function": "contribution_profit_v2"},
}

# What is live today. Adding the inactive versions above does not change a single entry here.
ACTIVE_FORMULA_VERSIONS: dict[str, str] = {
    "GROSS_ORDER_VALUE": "GROSS_ORDER_VALUE.v1",
    "SELLER_FUNDED_DISCOUNTS": "SELLER_FUNDED_DISCOUNTS.v1",
    "NET_REALIZED_REVENUE": "NET_REALIZED_REVENUE.v1",
    "CONTRIBUTION_PROFIT": "CONTRIBUTION_PROFIT.v1",
}
