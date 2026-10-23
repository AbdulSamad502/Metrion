"""Expense Tracker -> CFO ledger: the one explicit mapping between the two expense models (docs/specs/cfo-expense-ledger.md 14.4).

The CFO ledger is the authoritative expense source for Operating Profit and the planner. The Expense Tracker stays usable; its entries reach the ledger only when the
seller asks for it (`sync`), never silently. Each bridged entry carries `payment_ref = "tracker:<expense id>"`, which makes the bridge idempotent and stops double counting:
an entry already in the ledger (even if later voided there) is never added again. Amounts pass through unchanged; nothing here adds, rounds or converts money.
A Tracker entry that is not a plain incremental cost (voided, draft, "already in settlement", "informational", zero) is not bridged, and the reason is shown.
The ledger's own duplicate and overlap holds still apply to what is added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from calc_engine.expense_ledger import LedgerRuleError, NewEntry
from calc_engine.repositories import expense_ledger_repo as ledger_repo
from calc_engine.repositories import expense_tracker_repo as tracker

from backend.services import cfo_expense_ledger, expense_ledger_rules as rules

PREFIX = "tracker:"
PAGE = 200
MARKETPLACES = frozenset({"AMAZON", "FLIPKART", "MEESHO"})


@dataclass(frozen=True)
class Skip:
    expense_id: str
    reason: str


def ref_of(expense_id: Any) -> str:
    return f"{PREFIX}{expense_id}"


def category_name(tracker_category: str) -> str:
    """The ledger category is the Tracker category's plain label (so the ledger's own class suggestions can read it); an unknown id is kept as it is."""
    c = rules.CATEGORIES.get(tracker_category)
    return c.label.split(" (")[0] if c else tracker_category


_ID_BY_NAME = {category_name(k).casefold(): k for k in rules.CATEGORIES}


def category_id(ledger_category: str) -> str:
    """The reverse of `category_name`: a ledger category that is one of the Tracker's plain labels maps back to its id; any other text is kept as the seller wrote it."""
    return _ID_BY_NAME.get(" ".join((ledger_category or "").casefold().split()), ledger_category)


def to_entry(row: dict[str, Any]) -> NewEntry | Skip:
    eid = str(row["id"])
    if row["review_state"] == "voided":
        return Skip(eid, "Removed in the Expense Tracker.")
    if row["review_state"] == "draft":
        return Skip(eid, "Still a draft in the Expense Tracker.")
    if row["treatment"] != "incremental":
        return Skip(eid, "Marked as already in a settlement or informational only, so it is not an extra cost.")
    if int(row["amount_paise"]) <= 0:
        return Skip(eid, "The amount is zero.")
    return NewEntry(entry_date=row["effective_date"], amount_paise=int(row["amount_paise"]), category=category_name(row["category"]), vendor=row.get("vendor"),
                    description=row.get("description"), payment_ref=ref_of(eid), marketplace=row["channel_scope"] if row.get("channel_scope") in MARKETPLACES else None, source="MANUAL")


def _tracker_rows(tenant_id: UUID) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        rows, total = tracker.list_records(tenant_id, include_voided=True, limit=PAGE, offset=offset)
        out += rows
        offset += PAGE
        if offset >= total or not rows:
            return out


def _already(tenant_id: UUID) -> set[str]:
    return {r["payment_ref"] for r in cfo_expense_ledger.entries_view(tenant_id, None, None) if str(r.get("payment_ref") or "").startswith(PREFIX)}


_PAYMENT = {"unpaid": "UNPAID", "partially_paid": "PARTIALLY_PAID", "paid": "PAID"}  # the Tracker's "unknown" has no ledger equivalent: it stays "not stated"


def plan(tenant_id: UUID) -> tuple[list[NewEntry], int, list[Skip]]:
    """(entries still to bring over, how many are already in the ledger, entries not bridged with the reason)."""
    todo, already, skipped, _pay = _plan(tenant_id)
    return todo, already, skipped


def _plan(tenant_id: UUID) -> tuple[list[NewEntry], int, list[Skip], dict[str, tuple[str, int | None]]]:
    done = _already(tenant_id)
    todo: list[NewEntry] = []
    skipped: list[Skip] = []
    pay: dict[str, tuple[str, int | None]] = {}
    already = 0
    for row in _tracker_rows(tenant_id):
        if ref_of(row["id"]) in done:
            already += 1
            continue
        got = to_entry(row)
        if isinstance(got, Skip):
            skipped.append(got)
            continue
        todo.append(got)
        status = _PAYMENT.get(str(row.get("payment_status") or ""))
        if status:
            pay[ref_of(row["id"])] = (status, row.get("paid_amount_paise") if status == "PARTIALLY_PAID" else None)
    return todo, already, skipped, pay


def preview(tenant_id: UUID) -> dict[str, Any]:
    todo, already, skipped = plan(tenant_id)
    return {"toBring": len(todo), "alreadyInLedger": already, "notBridged": [{"expenseId": s.expense_id, "reason": s.reason} for s in skipped],
            "entries": [{"entryDate": e.entry_date.isoformat(), "amountPaise": e.amount_paise, "category": e.category, "vendor": e.vendor, "trackerRef": e.payment_ref} for e in todo]}


def _carry_payment(tenant_id: UUID, created_by: UUID, pay: dict[str, tuple[str, int | None]]) -> int:
    """The Tracker's payment statement travels with the entry it was made about. A statement the ledger will not accept (for example a partial payment that is not below the amount) is left out."""
    carried = 0
    for r in cfo_expense_ledger.entries_view(tenant_id, None, None):
        got = pay.get(str(r.get("payment_ref") or ""))
        if got is None or r.get("payment_status") is not None:
            continue
        try:
            carried += 1 if ledger_repo.set_payment(tenant_id, UUID(str(r["id"])), got[0], got[1], created_by) else 0
        except LedgerRuleError:
            continue
    return carried


def sync(tenant_id: UUID, created_by: UUID) -> dict[str, Any]:
    todo, already, skipped, pay = _plan(tenant_id)
    out = cfo_expense_ledger.add_entries(tenant_id, created_by, todo) if todo else None
    if out and out.inserted and pay:
        _carry_payment(tenant_id, created_by, pay)
    return {"brought": out.inserted if out else 0, "heldForReview": (out.held_possible_duplicates + out.held_overlap) if out else 0,
            "skippedExactDuplicates": out.skipped_exact_duplicates if out else 0, "alreadyInLedger": already,
            "notBridged": [{"expenseId": s.expense_id, "reason": s.reason} for s in skipped]}
