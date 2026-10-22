"""Ledger CSV export for the seller's accountant (kickoff S5b; engine §5.18.4, Q34): `GET /api/v1/cfo/expense-ledger/export`.

Generated on demand and never stored (`Cache-Control: no-store`); the permission is the existing financial read gate (`agent.cfo` plus the CFO entitlement gate, code
`cfo.expense_ledger.read`). Read-only, no arithmetic: one row per ledger record state with every ledger field, in every review state (voided and draft included, with
their status, never dropped); amounts are the stored integer paise; an unknown value is exported blank, never 0; there is no totals row (a total would need an engine
result reference). A text cell starting with `=`, `+`, `-`, `@`, a tab or a carriage return is escaped against spreadsheet formula injection; the integer columns are
written from integers and need none. `?history=true` exports the full status-event history instead of the latest state. GST and ITC columns are not exported because the
ledger does not hold them (G5). Tenant scope comes from the authenticated context and RLS, never from the request.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from calc_engine.repositories import expense_ledger_repo as ledger

from backend.api.v1.cfo import _require_cfo_entitlement
from backend.api.v1.expense_ledger import READ_CODE, _iso
from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CFO

router = APIRouter(prefix="/api/v1/cfo/expense-ledger/export")

STATE_COLUMNS = (
    "expense_id", "effective_date", "vendor", "category", "cost_class", "treatment", "review_status", "void_status", "void_reason", "payment_status", "paid_amount_paise",
    "amount_paise", "channel_scope", "sku", "description", "source_reference", "origin", "corrects_expense_id", "refund_of_expense_id", "recurring", "recorded_at", "actor",
)
HISTORY_COLUMNS = ("event_seq", "expense_id", "kind", "review_status", "payment_status", "paid_amount_paise", "reason", "recorded_at", "actor")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def text_cell(value: Any) -> str:
    """A text cell: blank when unknown, and a leading formula character is neutralised with a single quote."""
    if value is None:
        return ""
    s = str(value)
    return "'" + s if s.startswith(_FORMULA_START) else s


def int_cell(value: Any) -> str:
    """An integer cell exactly as stored (paise), blank when unknown, never 0."""
    return "" if value is None else str(int(value))


def _state_row(r: dict[str, Any]) -> list[str]:
    voided = r["review_state"] == "voided"
    return [
        str(r["id"]), _iso(r["effective_date"]) or "", text_cell(r["vendor"]), text_cell(r["category"]), text_cell(r["cost_class"]), text_cell(r["treatment"]),
        text_cell(r["review_state"]), "VOIDED" if voided else "", text_cell(r["review_reason"]) if voided else "", text_cell(r["payment_status"]),
        int_cell(r["paid_amount_paise"]), int_cell(r["amount_paise"]), text_cell(r["channel_scope"]), text_cell(r["sku"]), text_cell(r["description"]),
        text_cell(r["source_reference"]), text_cell(r["origin"]), str(r["corrects_expense_id"] or ""), str(r["refund_of_expense_id"] or ""),
        "true" if r["recurring"] else "false", _iso(r["created_at"]) or "", str(r["created_by"]),
    ]


def _history_row(e: dict[str, Any]) -> list[str]:
    return [
        str(e["seq"]), str(e["expense_id"]), text_cell(e["kind"]), text_cell(e["review_state"]), text_cell(e["payment_status"]), int_cell(e["paid_amount_paise"]),
        text_cell(e["reason"]), _iso(e["created_at"]) or "", str(e["created_by"]),
    ]


def build_csv(header: tuple[str, ...], rows: list[list[str]]) -> str:
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue()


@router.get("")
def export_ledger(history: bool = False, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> Response:
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=READ_CODE)
    if history:
        body = build_csv(HISTORY_COLUMNS, [_history_row(e) for e in ledger.export_status_events(ctx.tenant_id)])
        name = "expense-ledger-history.csv"
    else:
        body = build_csv(STATE_COLUMNS, [_state_row(r) for r in ledger.export_records(ctx.tenant_id)])
        name = "expense-ledger.csv"
    return Response(content=body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
