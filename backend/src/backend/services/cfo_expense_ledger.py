"""Service layer for the expense ledger (docs/specs/cfo-expense-ledger.md): policy on top of `calc_engine.repositories.expense_ledger_repo`.

Policy lives here, not in the repository: which classes a seller may confirm today, the rule-based class *suggestions* (suggest-only: they change
no figure, E3), and the plain-language messages. No money arithmetic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from calc_engine.expense_ledger import LedgerRuleError, NewEntry
from calc_engine.formulas.expense_accounting import ExpenseClass
from calc_engine.repositories import expense_ledger_repo as repo

# OQ-L3 (recommendation, pending owner confirmation): a small starter table of unambiguous words. Every hit is only ever a SUGGESTION (state SUGGESTED,
# suggested_by RULE) shown with its reason; nothing changes until the seller confirms. A category that matches nothing stays without a suggestion.
_SUGGESTIONS: tuple[tuple[tuple[str, ...], ExpenseClass, str], ...] = (
    (("rent", "salary", "salaries", "wages", "software", "subscription", "accountant", "accounting", "legal fee", "audit fee", "electricity", "internet"),
     ExpenseClass.OVERHEAD, "a running cost of the business, not tied to individual orders"),
    (("owner draw", "drawings", "owner withdrawal", "personal"), ExpenseClass.OWNER_DRAWING, "money taken out by the owner, not a business cost"),
    (("stock purchase", "inventory", "goods purchase", "raw material"), ExpenseClass.INVENTORY_PURCHASE, "stock bought for resale; its cost reaches profit only when units are sold"),
    (("laptop", "equipment", "machinery", "furniture", "computer"), ExpenseClass.CAPITAL, "a long-lived item bought for the business"),
    (("tcs", "tds"), ExpenseClass.TAX_ASSET, "tax collected or deducted at source, which reduces what the marketplace pays out"),
)

# ALLOCATED_COST (ads, packaging, storage, logistics, other pools) reaches Contribution Profit. A ledger entry confirmed as one names its cost pool; the cost-ownership
# arbitration (cfo_costs) then makes sure the same cost is not also counted from the Expense Tracker's pool or a report.


def suggest_for_category(category: str) -> tuple[ExpenseClass, str] | None:
    folded = category.casefold()
    for words, klass, why in _SUGGESTIONS:
        hit = next((w for w in words if w in folded), None)
        if hit is not None:
            return klass, f"“{hit}” {why}"
    return None


@dataclass(frozen=True, slots=True)
class AddOutcome:
    inserted: int
    skipped_exact_duplicates: int
    held_possible_duplicates: int
    held_overlap: int
    suggestions_recorded: int
    entry_ids: tuple[UUID, ...]
    held_ids: tuple[UUID, ...]


def add_entries(tenant_id: UUID, created_by: UUID, entries: Sequence[NewEntry]) -> AddOutcome:
    res = repo.add_entries(tenant_id, entries, created_by)
    suggested = 0
    if res.inserted_ids:
        known = repo.categories_with_assignment(tenant_id)
        for category in sorted({e.category.strip() for e in entries}):
            if category in known:
                continue
            hit = suggest_for_category(category)
            if hit is not None:
                repo.suggest_class(tenant_id, klass=hit[0], suggested_by="RULE", reason=hit[1], category=category)
                suggested += 1
    return AddOutcome(len(res.inserted_ids), res.skipped_exact_duplicates, res.held_possible_duplicates, res.held_overlap, suggested, res.inserted_ids, res.held_ids)


def confirm_class(tenant_id: UUID, confirmed_by: UUID, klass: ExpenseClass, *, entry_id: UUID | None = None, category: str | None = None,
                  allocated_component: str | None = None) -> UUID:
    return repo.confirm_class(tenant_id, klass=klass, confirmed_by=confirmed_by, entry_id=entry_id, category=category,
                              allocated_component=None if allocated_component is None else allocated_component.strip().upper())


def entries_view(tenant_id: UUID, start: date | None, end: date | None) -> list[dict[str, Any]]:
    return repo.list_entries(tenant_id, start, end)
