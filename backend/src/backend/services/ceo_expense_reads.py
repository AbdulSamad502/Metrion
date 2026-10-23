"""The ONE declared seam through which the CEO package reads the seller's expense-ledger entries (docs/specs/ceo-expense-tracker-chat.md).

Tenant-scoped and read-only; no calculation (totals come from the planner's `EXPENSE_BY_CATEGORY` through `ceo_expense_ops.summary`). The CEO package may not import a repository
directly (`tests/unit/test_ceo_architecture.py`), so its guided conversations read the seller's own entries here, to offer them as choices and to find the one the seller means.
Rows are given the field names the guided conversation already uses; a category the chat wrote reads back as its closed-list id, any other text stays as written.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from calc_engine.repositories import expense_ledger_repo as ledger

from backend.services import cfo_expense_ledger, expense_bridge


def _shape(r: dict[str, Any]) -> dict[str, Any]:
    gone = bool(r.get("is_void") or r.get("superseded"))
    return {**r, "effective_date": r["entry_date"], "category": expense_bridge.category_id(r["category"]), "review_state": "voided" if gone else "confirmed"}


def live_entries(tenant_id: UUID) -> list[dict[str, Any]]:
    """The seller's active entries (not removed, not replaced by a correction), newest first."""
    rows = cfo_expense_ledger.entries_view(tenant_id, None, None)
    return [_shape(r) for r in sorted(rows, key=lambda r: (r["entry_date"], str(r["id"])), reverse=True)]


def get_entry(tenant_id: UUID, expense_id: UUID) -> dict[str, Any] | None:
    """One entry of THIS tenant (removed or replaced ones included, so the caller can say so), or None."""
    row = ledger.get_entry(tenant_id, expense_id)
    return None if row is None else _shape(row)
