"""The CFO expense ledger as the CEO uses it (docs/specs/ceo-expense-tracker-chat.md, re-pointed 2026-10-23: the ledger is the authoritative expense source).

Registry handlers for `cfo.expense_summary` (READ) and the four chat-prepared writes `cfo.expense_add / _correct / _void / _paid`. Each write goes through the ledger's own
rules (`calc_engine.expense_ledger` validation, duplicate and overlap holds, append-only history, read-model version bump) and runs only from an approved plan; permission
(`financials.adjust`) and entitlement are checked by the registry gate before a handler is reached. Nothing here parses or computes a value: amounts, dates, categories and ids
arrive already parsed by code from the guided input session, frozen on the approved plan. Totals come from the planner's `EXPENSE_BY_CATEGORY` (Brain 1); this module only
chooses which periods to ask it for. An expense added in chat has no confirmed class, so it does not reduce Operating Profit until the seller confirms its class (suggest-only, OQ2).
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any, Literal
from uuid import UUID

from calc_engine.expense_ledger import LedgerRuleError, NewEntry, entry_identity, validate_new_entry
from calc_engine.repositories import expense_ledger_repo as ledger
from cfo.planner.pipeline import PlannerAnswer
from cfo.planner.plan import PeriodRef
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.context import AuthContext
from backend.services import cfo_expense_ledger
from backend.services import expense_bridge
from backend.services import expense_ledger_rules as rules

MAX_BUCKETS = 12
MAX_ENTRIES = 12

_MONTHLY = re.compile(r"\b(?:month[- ]?wise|monthly|(?:by|per|each|every) month|month by month|month[- ]on[- ]month)\b", re.IGNORECASE)
_DAILY = re.compile(r"\b(?:date[- ]?wise|day[- ]?wise|daily|(?:by|per|each|every) (?:day|date)|day by day|day[- ]on[- ]day)\b", re.IGNORECASE)


def breakdown_of(question: str) -> Literal["MONTH", "DAY", "TOTAL"]:
    """How the seller wants a range cut, decided by CODE from their words (a model never picks it)."""
    if _DAILY.search(question):
        return "DAY"
    if _MONTHLY.search(question):
        return "MONTH"
    return "TOTAL"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExpenseSummarySlots(_Strict):
    question: str = Field(min_length=3, max_length=500)
    period_start: date
    period_end: date
    as_of_date: date


class _Content(_Strict):
    effective_date: date
    category: str
    amount_paise: int = Field(ge=0)
    vendor: str | None = Field(default=None, max_length=rules.VENDOR_MAX)
    description: str | None = Field(default=None, max_length=rules.DESCRIPTION_MAX)
    request_key: str | None = Field(default=None, max_length=rules.IDEMPOTENCY_KEY_MAX)


class ExpenseAddSlots(_Content):
    pass


class ExpenseCorrectSlots(_Content):
    expense_id: UUID
    reason: str | None = Field(default=None, max_length=rules.REASON_MAX)


class ExpenseVoidSlots(_Strict):
    expense_id: UUID
    reason: str = Field(min_length=3, max_length=300)
    request_key: str | None = Field(default=None, max_length=rules.IDEMPOTENCY_KEY_MAX)


class ExpensePaidSlots(_Strict):
    expense_id: UUID
    status: Literal["unpaid", "partially_paid", "paid"]
    paid_amount_paise: int | None = Field(default=None, gt=0, le=rules.AMOUNT_MAX_PAISE)
    request_key: str | None = Field(default=None, max_length=rules.IDEMPOTENCY_KEY_MAX)


# ------------------------------------------------------------------------------------------------ shaping
def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None else None


def entry_view(row: dict[str, Any]) -> dict[str, Any]:
    """One ledger entry as the CEO's evidence needs it. The amount is the stored paise; it becomes a figure only through a reference to this very entry."""
    cid = expense_bridge.category_id(row["category"])
    cat = rules.CATEGORIES.get(cid)
    return {
        "id": str(row["id"]), "effectiveDate": _iso(row["entry_date"]), "category": cid, "categoryLabel": cat.label if cat else row["category"],
        "vendor": row["vendor"], "description": row["description"], "amountPaise": int(row["amount_paise"]), "onHold": row["hold"] != "NONE",
        "paymentStatus": row.get("payment_status"), "paidAmountPaise": row.get("paid_amount_paise"), "voidReason": row.get("void_reason"),
    }


def _echo(tenant: UUID, entry_id: UUID | None, extra: dict[str, Any]) -> dict[str, Any]:
    row = ledger.get_entry(tenant, entry_id) if entry_id is not None else None
    return {"status": "OK", "expenseId": None if entry_id is None else str(entry_id), "record": entry_view(row) if row is not None else None, **extra}


def _new_entry(slots: _Content) -> NewEntry:
    return NewEntry(entry_date=slots.effective_date, amount_paise=slots.amount_paise, category=expense_bridge.category_name(slots.category), vendor=slots.vendor,
                    description=slots.description, source="MANUAL")


def _refuse(exc: LedgerRuleError) -> dict[str, Any]:
    """A ledger rule said no: the seller is told the ledger's own safe message, and nothing was saved."""
    return {"status": "REFUSED", "message": str(exc)}


# ------------------------------------------------------------------------------------------------ reads
def _month_buckets(start: date, end: date) -> list[tuple[str, date, date]]:
    out: list[tuple[str, date, date]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first, last = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        out.append((f"{y:04d}-{m:02d}", max(first, start), min(last, end)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _bucket(tenant: UUID, user: UUID, label: str, start: date, end: date, as_of: date) -> dict[str, Any] | None:
    """The planner's expense breakdown for one period (Brain 1, with a result reference per figure), or None when the period has no entries."""
    from backend.services.cfo_dashboard import FixedPlan
    from backend.services.cfo_query import answer_financial_query

    periods = [PeriodRef(start, end, as_of)]
    steps: list[dict[str, Any]] = [{"op": "group_by", "params": {"dimensions": ["expense_category", "expense_class"]}}, {"op": "aggregate", "params": {"metric": "EXPENSE_BY_CATEGORY"}}]
    res = answer_financial_query(tenant, requested_by=user, question="expenses", periods=periods, provider=FixedPlan(steps, periods, "EXPENSE_BREAKDOWN"))
    if not isinstance(res, PlannerAnswer):
        return {"label": label, "periodStart": start.isoformat(), "periodEnd": end.isoformat(), "refused": True, "figures": []}
    figs = []
    for f in res.packet.figures:
        if f.engine_result_ref is None:
            continue
        dims = dict(f.dimension_keys)
        figs.append({"engineResultRef": f.engine_result_ref, "isTotal": not dims, "category": dims.get("expense_category"), "expenseClass": dims.get("expense_class"), "status": f.status})
    if not figs:
        return None
    return {"label": label, "periodStart": start.isoformat(), "periodEnd": end.isoformat(), "figures": figs}


def summary(slots: ExpenseSummarySlots, ctx: AuthContext) -> dict[str, Any]:
    """The ledger's expenses for the period, optionally cut by month or by day (only days that have entries), plus the newest entries. Every total is the engine's own result
    with its `engineResultRef`; an empty period is said to be empty, never zero."""
    assert ctx.tenant_id is not None and ctx.app_user_id is not None
    tenant, user = ctx.tenant_id, ctx.app_user_id
    cut = breakdown_of(slots.question)
    rows = cfo_expense_ledger.entries_view(tenant, slots.period_start, slots.period_end)
    rows = sorted(rows, key=lambda r: (r["entry_date"], str(r["id"])), reverse=True)
    if cut == "MONTH":
        buckets = _month_buckets(slots.period_start, slots.period_end)
    elif cut == "DAY":
        days = sorted({r["entry_date"] for r in rows}, reverse=True)
        buckets = [(d.isoformat(), d, d) for d in sorted(days[:MAX_BUCKETS])]
    else:
        buckets = [(f"{slots.period_start.isoformat()}/{slots.period_end.isoformat()}", slots.period_start, slots.period_end)]
    truncated = len(buckets) > MAX_BUCKETS
    buckets = buckets[-MAX_BUCKETS:]
    out_buckets = []
    if rows:
        for label, s, e in buckets:
            b = _bucket(tenant, user, label, s, e, slots.as_of_date)
            if b is not None:
                out_buckets.append(b)
    newest = rows[:MAX_ENTRIES] if cut != "MONTH" else []
    return {
        "status": "ANSWERED", "breakdown": cut, "periodStart": slots.period_start.isoformat(), "periodEnd": slots.period_end.isoformat(), "entryCount": len(rows),
        "heldCount": sum(1 for r in rows if r["hold"] != "NONE"), "buckets": out_buckets, "entries": [entry_view(r) for r in newest],
        "truncated": truncated or (cut != "MONTH" and len(rows) > MAX_ENTRIES),
    }


# ------------------------------------------------------------------------------------------------ writes (each runs only from an approved plan)
def _changed(ctx: AuthContext) -> None:
    from backend.api.v1.cfo import _changed as changed  # noqa: PLC0415

    changed(ctx)


def add(slots: ExpenseAddSlots, ctx: AuthContext) -> dict[str, Any]:
    assert ctx.tenant_id is not None and ctx.app_user_id is not None
    try:
        new = validate_new_entry(_new_entry(slots))
        out = cfo_expense_ledger.add_entries(ctx.tenant_id, ctx.app_user_id, [new])
    except LedgerRuleError as exc:
        return _refuse(exc)
    if out.inserted:
        _changed(ctx)
        held = bool(out.held_possible_duplicates or out.held_overlap)
        return _echo(ctx.tenant_id, out.entry_ids[0], {"action": "ADDED", "replayed": False, "held": held, "heldReason": "POSSIBLE_DUPLICATE" if out.held_possible_duplicates else ("MAY_OVERLAP" if out.held_overlap else None)})
    existing = ledger.find_active_by_identity(ctx.tenant_id, entry_identity(new))  # an exact repeat (for example the same approval replayed): nothing was added
    return _echo(ctx.tenant_id, None if existing is None else existing, {"action": "ADDED", "replayed": True, "held": False, "heldReason": None})


def correct(slots: ExpenseCorrectSlots, ctx: AuthContext) -> dict[str, Any]:
    assert ctx.tenant_id is not None and ctx.app_user_id is not None
    try:
        new_id = ledger.supersede_entry(ctx.tenant_id, slots.expense_id, _new_entry(slots), ctx.app_user_id)
    except LedgerRuleError as exc:
        return _refuse(exc)
    _changed(ctx)
    return _echo(ctx.tenant_id, new_id, {"action": "CORRECTED", "replayed": False, "correctedId": str(slots.expense_id)})


def void(slots: ExpenseVoidSlots, ctx: AuthContext) -> dict[str, Any]:
    assert ctx.tenant_id is not None and ctx.app_user_id is not None
    before = ledger.get_entry(ctx.tenant_id, slots.expense_id)
    try:
        ledger.void_entry(ctx.tenant_id, slots.expense_id, ctx.app_user_id, slots.reason)
    except LedgerRuleError as exc:
        if before is not None and (before.get("superseded") or before.get("is_void")):
            return {"status": "OK", "expenseId": str(slots.expense_id), "action": "VOIDED", "changed": False, "record": entry_view(before)}  # already removed or replaced: nothing to do twice
        return _refuse(exc)
    _changed(ctx)
    return {"status": "OK", "expenseId": str(slots.expense_id), "action": "VOIDED", "changed": True, "record": entry_view({**(before or {}), "void_reason": slots.reason}) if before else None}


def paid(slots: ExpensePaidSlots, ctx: AuthContext) -> dict[str, Any]:
    assert ctx.tenant_id is not None and ctx.app_user_id is not None
    try:
        changed = ledger.set_payment(ctx.tenant_id, slots.expense_id, slots.status, slots.paid_amount_paise, ctx.app_user_id)
    except LedgerRuleError as exc:
        return _refuse(exc)
    after = ledger.get_entry(ctx.tenant_id, slots.expense_id)
    return {"status": "OK", "expenseId": str(slots.expense_id), "action": "PAYMENT", "changed": bool(changed), "record": entry_view(after) if after is not None else None}
