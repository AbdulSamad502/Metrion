"""The Expense Tracker as the CEO uses it (docs/specs/ceo-expense-tracker-chat.md).

Registry handlers for `cfo.expense_summary` (READ) and the four chat-prepared writes `cfo.expense_add / _correct / _void / _paid`. Each handler is a thin wrapper over the
Expense Tracker's OWN route function (`api/v1/expense_ledger.py`), called with the real `AuthContext`, so the permission (`financials.adjust`), the CFO entitlement, the
validation, the idempotency, the append-only history, the audit row and the read-model version bump are exactly the tracker page's. Nothing here parses or computes a
value: amounts, dates, categories and ids arrive already parsed by code from the guided input session, frozen on an approved plan. Totals come from the engine
(`ledger_feed` -> `EXPENSE_*` results); this module only chooses which periods to ask it for.
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date
from typing import Any, Literal
from uuid import UUID

from calc_engine.repositories import expense_tracker_repo as ledger
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.context import AuthContext
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
    reason: str = Field(min_length=1, max_length=rules.REASON_MAX)
    request_key: str | None = Field(default=None, max_length=rules.IDEMPOTENCY_KEY_MAX)


class ExpensePaidSlots(_Strict):
    expense_id: UUID
    status: Literal["unpaid", "partially_paid", "paid", "unknown"]
    paid_amount_paise: int | None = Field(default=None, ge=0, le=rules.AMOUNT_MAX_PAISE)
    request_key: str | None = Field(default=None, max_length=rules.IDEMPOTENCY_KEY_MAX)


# ------------------------------------------------------------------------------------------------ shaping
def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None else None


def entry_view(row: dict[str, Any]) -> dict[str, Any]:
    """One tracker record as the CEO's evidence needs it. The amount is the stored paise; it becomes a figure only through a reference to this very record."""
    cat = rules.CATEGORIES.get(row["category"])
    return {
        "id": str(row["id"]), "effectiveDate": _iso(row["effective_date"]), "category": row["category"], "categoryLabel": cat.label if cat else row["category"],
        "vendor": row["vendor"], "description": row["description"], "amountPaise": int(row["amount_paise"]), "reviewState": row["review_state"],
        "paymentStatus": row["payment_status"], "paidAmountPaise": row["paid_amount_paise"],
    }


def _body(out: Any) -> dict[str, Any]:
    if isinstance(out, dict):
        return out
    return dict(json.loads(bytes(out.body)))  # a replay answers with a JSON response


def _echo(tenant: UUID, expense_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    row = ledger.get_record(tenant, UUID(expense_id))
    return {"status": "OK", "expenseId": expense_id, "record": entry_view(row) if row is not None else None, **extra}


# ------------------------------------------------------------------------------------------------ reads
def _month_buckets(start: date, end: date) -> list[tuple[str, date, date]]:
    out: list[tuple[str, date, date]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first, last = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        out.append((f"{y:04d}-{m:02d}", max(first, start), min(last, end)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def summary(slots: ExpenseSummarySlots, ctx: AuthContext) -> dict[str, Any]:
    """The Expense Tracker's engine summary for the period, optionally cut by month or by day (only days that have entries), plus the newest entries. Every total is
    the engine's own result with its `engineResultRef`; an empty period is said to be empty, never zero."""
    from backend.api.v1 import expense_ledger as ex

    assert ctx.tenant_id is not None
    tenant = ctx.tenant_id
    cut = breakdown_of(slots.question)
    rows, total = ledger.list_records(tenant, date_from=slots.period_start, date_to=slots.period_end, category=None, cost_class=None, review_state=None, payment_status=None,
                                      channel_scope=None, include_voided=False, limit=rules.PAGE_SIZE_MAX, offset=0)
    if cut == "MONTH":
        buckets = _month_buckets(slots.period_start, slots.period_end)
    elif cut == "DAY":
        days = sorted({r["effective_date"] for r in rows}, reverse=True)
        buckets = [(d.isoformat(), d, d) for d in sorted(days[:MAX_BUCKETS])]
    else:
        buckets = [(f"{slots.period_start.isoformat()}/{slots.period_end.isoformat()}", slots.period_start, slots.period_end)]
    truncated = len(buckets) > MAX_BUCKETS
    buckets = buckets[-MAX_BUCKETS:]
    out_buckets = []
    if total > 0:
        for label, s, e in buckets:
            res = ex.post_summary(ex.SummaryRequest(period_start=s, period_end=e, as_of_date=slots.as_of_date), ctx)
            out_buckets.append({"label": label, "periodStart": s.isoformat(), "periodEnd": e.isoformat(), "summary": res})
    newest = sorted(rows, key=lambda r: (r["effective_date"], str(r["id"])), reverse=True)[:MAX_ENTRIES] if cut != "MONTH" else []
    return {
        "status": "ANSWERED", "breakdown": cut, "periodStart": slots.period_start.isoformat(), "periodEnd": slots.period_end.isoformat(), "entryCount": total,
        "buckets": out_buckets, "entries": [entry_view(r) for r in newest], "truncated": truncated or (cut != "MONTH" and total > MAX_ENTRIES),
    }


# ------------------------------------------------------------------------------------------------ writes (each runs only from an approved plan)
def _create(slots: _Content) -> Any:
    from backend.api.v1 import expense_ledger as ex

    return ex.CreateRequest(effective_date=slots.effective_date, category=slots.category, amount_paise=slots.amount_paise, vendor=slots.vendor,
                            description=slots.description, idempotency_key=slots.request_key, state="confirmed")


def add(slots: ExpenseAddSlots, ctx: AuthContext) -> dict[str, Any]:
    from backend.api.v1 import expense_ledger as ex

    out = _body(ex.create_expense(_create(slots), ctx))
    return _echo(ctx.tenant_id, str(out["expenseId"]), {"action": "ADDED", "replayed": bool(out.get("replayed"))})  # type: ignore[arg-type]


def correct(slots: ExpenseCorrectSlots, ctx: AuthContext) -> dict[str, Any]:
    from backend.api.v1 import expense_ledger as ex

    req = ex.CorrectRequest(effective_date=slots.effective_date, category=slots.category, amount_paise=slots.amount_paise, vendor=slots.vendor,
                            description=slots.description, idempotency_key=slots.request_key, reason=slots.reason)
    out = _body(ex.correct_expense(slots.expense_id, req, ctx))
    return _echo(ctx.tenant_id, str(out["expenseId"]), {"action": "CORRECTED", "replayed": bool(out.get("replayed")), "correctedId": str(slots.expense_id)})  # type: ignore[arg-type]


def void(slots: ExpenseVoidSlots, ctx: AuthContext) -> dict[str, Any]:
    from backend.api.v1 import expense_ledger as ex

    before = ledger.get_record(ctx.tenant_id, slots.expense_id)  # type: ignore[arg-type]
    out = ex.void_expense(slots.expense_id, ex.VoidRequest(reason=slots.reason, idempotency_key=slots.request_key), ctx)
    return {"status": "OK", "expenseId": str(slots.expense_id), "action": "VOIDED", "changed": bool(out.get("changed")), "record": entry_view(before) if before is not None else None}


def paid(slots: ExpensePaidSlots, ctx: AuthContext) -> dict[str, Any]:
    from backend.api.v1 import expense_ledger as ex

    out = ex.set_payment_status(slots.expense_id, ex.PaymentRequest(status=slots.status, paid_amount_paise=slots.paid_amount_paise, idempotency_key=slots.request_key), ctx)
    after = ledger.get_record(ctx.tenant_id, slots.expense_id)  # type: ignore[arg-type]
    return {"status": "OK", "expenseId": str(slots.expense_id), "action": "PAYMENT", "changed": bool(out.get("changed")), "record": entry_view(after) if after is not None else None}
