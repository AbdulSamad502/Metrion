"""Cash-view data access (docs/specs/cfo-phase3-scope.md 3c): settled pairs, unsettled lines and seller payables. Read-mostly; payables are
`payable.supplier` manual inputs (engine §7.2.1: append-only, superseding), never a bank balance.

The order-to-settlement match here is the **`line_ref` key only**. The caller passes only marketplaces whose join key has been validated against a
real export (today Meesho); for any other marketplace there is no match key, so there are no pairs and no unsettled lines — never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.repositories import manual_adjustment_repo
from calc_engine.repositories.manual_adjustment_repo import insert_adjustment
from calc_engine.repositories.tenant_context import tenant_scope

PAYABLE_FIELD = "payable.supplier"


class CashRuleError(ValueError):
    """A request the cash rules refuse; the message is safe to show the seller."""


@dataclass(frozen=True, slots=True)
class SettledPair:
    sales_line_id: str
    document_date: date
    gross_item_amount_paise: int
    settled_amount_paise: int
    settlement_date: date


@dataclass(frozen=True, slots=True)
class UnsettledLine:
    sales_line_id: str
    document_date: date
    gross_item_amount_paise: int


@dataclass(frozen=True, slots=True)
class PayableRow:
    payable_id: str  # the manual_adjustment id of the live row
    target_ref: str
    amount_paise: int
    due_date: date | None
    supplier_ref: str | None
    po_ref: str | None
    status: str  # OPEN | PAID


def settled_pairs(tenant_id: UUID, marketplace: str, as_of: date) -> list[SettledPair]:
    """Lines that have a settlement (matched on line_ref) dated on or before `as_of`, with the settled amount summed over that line's settlement rows."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(
            "SELECT s.id, coalesce(s.invoice_date, s.dispatch_date, s.order_date), s.gross_item_amount, sum(t.gross_settlement_amount), min(t.settlement_date) "
            "FROM sales_line s JOIN settlement_line t ON t.tenant_id = s.tenant_id AND t.marketplace = s.marketplace AND t.line_ref = s.line_ref "
            "WHERE s.tenant_id = :t AND s.marketplace = :m AND s.line_ref IS NOT NULL AND s.gross_item_amount IS NOT NULL "
            "AND t.gross_settlement_amount IS NOT NULL AND t.settlement_date IS NOT NULL AND t.settlement_date <= :asof "
            "AND coalesce(s.invoice_date, s.dispatch_date, s.order_date) IS NOT NULL GROUP BY s.id, s.invoice_date, s.dispatch_date, s.order_date, s.gross_item_amount"),
            {"t": str(tenant_id), "m": marketplace, "asof": as_of}).all()
    return [SettledPair(str(r[0]), r[1], int(r[2]), int(r[3]), r[4]) for r in rows]


def unsettled_lines(tenant_id: UUID, marketplace: str, start: date, end: date) -> tuple[list[UnsettledLine], int]:
    """Sold lines dated in [start, end] with no settlement row on the same line_ref. Second value: lines that cannot be matched at all (no line_ref
    or no amount), counted so they are disclosed rather than silently left out."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(
            "SELECT s.id, coalesce(s.invoice_date, s.dispatch_date, s.order_date), s.gross_item_amount, s.line_ref FROM sales_line s "
            "WHERE s.tenant_id = :t AND s.marketplace = :m AND coalesce(s.invoice_date, s.dispatch_date, s.order_date) BETWEEN :s AND :e "
            "AND NOT EXISTS (SELECT 1 FROM settlement_line t WHERE t.tenant_id = s.tenant_id AND t.marketplace = s.marketplace AND s.line_ref IS NOT NULL AND t.line_ref = s.line_ref)"),
            {"t": str(tenant_id), "m": marketplace, "s": start, "e": end}).all()
    usable = [UnsettledLine(str(r[0]), r[1], int(r[2])) for r in rows if r[3] is not None and r[2] is not None]
    return usable, len(rows) - len(usable)


# ------------------------------------------------------------------------------------------------ payables
def _row(r: Any) -> PayableRow:
    v = dict(r["value"])
    due = v.get("due_date")
    return PayableRow(str(r["id"]), r["target_ref"], int(v["amount_paise"]), date.fromisoformat(due) if due else None, v.get("supplier_ref"), v.get("po_ref"),
                      str(v.get("status", "OPEN")))


def add_payable(tenant_id: UUID, created_by: UUID, *, amount_paise: int, due_date: date | None = None, supplier_ref: str | None = None, po_ref: str | None = None) -> str:
    if isinstance(amount_paise, bool) or not isinstance(amount_paise, int) or amount_paise <= 0:
        raise CashRuleError("a payable must be a positive amount")
    from uuid import uuid4

    ref = f"payable:{uuid4()}"
    insert_adjustment(
        tenant_id, target_type="ACCOUNT", target_ref=ref, field=PAYABLE_FIELD, created_by=created_by, created_at=datetime.now().astimezone(),
        value={"amount_paise": amount_paise, "due_date": due_date.isoformat() if due_date else None, "supplier_ref": (supplier_ref or "").strip() or None,
               "po_ref": (po_ref or "").strip() or None, "status": "OPEN"})
    return ref


def list_payables(tenant_id: UUID, *, include_paid: bool = False) -> list[PayableRow]:
    rows = [_row(r) for r in manual_adjustment_repo.active_adjustments_by_field(tenant_id, field=PAYABLE_FIELD)]
    rows = rows if include_paid else [r for r in rows if r.status == "OPEN"]
    return sorted(rows, key=lambda p: (p.due_date or date.max, p.payable_id))


def mark_paid(tenant_id: UUID, created_by: UUID, target_ref: str) -> None:
    live = [r for r in manual_adjustment_repo.active_adjustments_by_field(tenant_id, field=PAYABLE_FIELD) if r["target_ref"] == target_ref]
    if not live:
        raise CashRuleError("that payable does not exist")
    row = live[0]
    if dict(row["value"]).get("status") == "PAID":
        raise CashRuleError("that payable is already marked paid")
    insert_adjustment(tenant_id, target_type="ACCOUNT", target_ref=target_ref, field=PAYABLE_FIELD, created_by=created_by, created_at=datetime.now().astimezone(),
                      value={**dict(row["value"]), "status": "PAID"}, supersedes_id=row["id"])
