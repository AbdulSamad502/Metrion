"""Expense ledger routes — `/api/v1/cfo/expense-ledger` (kickoff S3b; expense-tracker.md §5–§8; Round 9).

The dedicated Expense Tracker dashboard's data surface, under the CFO. `agent.cfo` is required on every route; every WRITE additionally needs `financials.adjust`
(EXP-05: no new permission key; checked in the handler, as `put_expense` does) and passes the existing CFO entitlement gate (X9). Reads need only `agent.cfo` and the
gate. No route accepts a `tenant_id` (the body rejects unknown fields); the tenant is the session's. One `agent_run` row (`trigger_type = DIRECT`) is written per
write that actually changes the ledger (X3); an idempotent replay writes nothing and no run.

Nothing is ever updated or deleted: an edit is a linked correction (a new record; the original is voided), a refund is a new negative linked record, a void is a
review-state event with a reason. The legacy `PUT/GET /cfo/expenses` is untouched. This module does no money arithmetic.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator, model_validator

from calc_engine.api.expense_metrics import mint_ledger_feed_metrics
from calc_engine.formulas.ledger_feed import ledger_feed
from calc_engine.repositories import expense_ledger_repo as ledger
from calc_engine.repositories import metric_result_repo
from calc_engine.repositories.expense_ledger_repo import NewRecord

from backend.api.v1.cfo import _require_cfo_entitlement
from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CFO, FINANCIALS_ADJUST, has_permission
from backend.repositories import agent_run_repo
from backend.services import expense_ledger_rules as rules

router = APIRouter(prefix="/api/v1/cfo/expense-ledger")

WRITE_CODE = "cfo.expense_ledger.write"  # direct-action / meter code: no cap is configured, so it passes until the owner configures one
READ_CODE = "cfo.expense_ledger.read"
TRIGGER_REF = "cfo.expense_ledger"


_DIGITS = r"^(0|-?[1-9][0-9]{0,15})$"

# Money may cross the wire as an integer or as an integer STRING of digits (the Profit Calculator convention: a browser number cannot hold a large paise amount and
# the browser never parses money). The OpenAPI schema says so (integer or a digit string), a float, a bool, an exponent or a decimal string is refused, and the
# validators below turn an accepted string into the integer the rules and the ledger use.
Paise = StrictInt | Annotated[str, StringConstraints(pattern=_DIGITS)]


def _to_int(value: Any) -> Any:
    return int(value) if isinstance(value, str) else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check(message: str | None) -> None:
    if message:
        raise ValueError(message)


class _Content(_Strict):
    effective_date: date
    category: str
    amount_paise: Paise
    vendor: str | None = Field(default=None, max_length=rules.VENDOR_MAX)
    description: str | None = Field(default=None, max_length=rules.DESCRIPTION_MAX)
    cost_class: str | None = None
    treatment: str | None = None
    channel_scope: str | None = None
    sku: str | None = Field(default=None, max_length=rules.SKU_MAX)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=rules.IDEMPOTENCY_KEY_MAX)

    @field_validator("amount_paise", mode="after")
    @classmethod
    def _amount_int(cls, v: Any) -> Any:
        return _to_int(v)

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        if v not in rules.CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(sorted(rules.CATEGORIES))}")
        return v

    @field_validator("cost_class")
    @classmethod
    def _cost_class(cls, v: str | None) -> str | None:
        if v is not None and v not in rules.COST_CLASSES:
            raise ValueError(f"cost_class must be one of: {', '.join(sorted(rules.COST_CLASSES))}")
        return v

    @field_validator("treatment")
    @classmethod
    def _treatment(cls, v: str | None) -> str | None:
        if v is not None and v not in rules.TREATMENTS:
            raise ValueError(f"treatment must be one of: {', '.join(sorted(rules.TREATMENTS))}")
        return v

    @field_validator("channel_scope")
    @classmethod
    def _channel(cls, v: str | None) -> str | None:
        if v is not None and v not in rules.CHANNEL_TAGS:
            raise ValueError(f"channel_scope must be one of: {', '.join(sorted(rules.CHANNEL_TAGS))}")
        return v

    @field_validator("vendor")
    @classmethod
    def _vendor(cls, v: str | None) -> str | None:
        if v:
            _check(rules.vendor_error(v))
        return v or None

    @model_validator(mode="after")
    def _amount(self) -> "_Content":
        _check(rules.amount_error(self.amount_paise))
        _check(rules.cost_amount_error(self.amount_paise))
        return self


class CreateRequest(_Content):
    state: Literal["draft", "pending_review", "confirmed"] = "confirmed"


class CorrectRequest(_Content):
    reason: str | None = Field(default=None, max_length=rules.REASON_MAX)


class RefundRequest(_Strict):
    effective_date: date
    amount_paise: Paise
    description: str | None = Field(default=None, max_length=rules.DESCRIPTION_MAX)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=rules.IDEMPOTENCY_KEY_MAX)

    @field_validator("amount_paise", mode="after")
    @classmethod
    def _amount_int(cls, v: Any) -> Any:
        return _to_int(v)

    @model_validator(mode="after")
    def _amount(self) -> "RefundRequest":
        _check(rules.amount_error(self.amount_paise))
        _check(rules.refund_amount_error(self.amount_paise))
        return self


class VoidRequest(_Strict):
    reason: str = Field(min_length=1, max_length=rules.REASON_MAX)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=rules.IDEMPOTENCY_KEY_MAX)


class ReviewRequest(_Strict):
    state: Literal["draft", "pending_review", "confirmed"]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=rules.IDEMPOTENCY_KEY_MAX)


class PaymentRequest(_Strict):
    status: Literal["unpaid", "partially_paid", "paid", "unknown"]
    paid_amount_paise: Paise | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=rules.IDEMPOTENCY_KEY_MAX)

    @field_validator("paid_amount_paise", mode="after")
    @classmethod
    def _paid(cls, v: Any) -> Any:
        v = _to_int(v)
        if v is not None and not 0 <= v <= rules.AMOUNT_MAX_PAISE:
            raise ValueError("paid amount must be between 0 and the amount limit")
        return v


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _record(row: dict[str, Any]) -> dict[str, object]:
    out: dict[str, object] = {
        "id": str(row["id"]),
        "effectiveDate": _iso(row["effective_date"]),
        "vendor": row["vendor"],
        "description": row["description"],
        "category": row["category"],
        "categoryLabel": rules.CATEGORIES[row["category"]].label if row["category"] in rules.CATEGORIES else row["category"],
        "costClass": row["cost_class"],
        "treatment": row["treatment"],
        "amountPaise": row["amount_paise"],
        "channelScope": row["channel_scope"],
        "sku": row["sku"],
        "origin": row["origin"],
        "sourceValidated": row["source_validated"],
        "identifier": row["identifier"],
        "sourceReference": row["source_reference"],
        "correctsExpenseId": str(row["corrects_expense_id"]) if row["corrects_expense_id"] else None,
        "refundOfExpenseId": str(row["refund_of_expense_id"]) if row["refund_of_expense_id"] else None,
        "recurring": row["recurring"],
        "createdAt": _iso(row["created_at"]),
        "reviewState": row["review_state"],
        "reviewReason": row["review_reason"],
        "paymentStatus": row["payment_status"],
        "paidAmountPaise": row["paid_amount_paise"],
    }
    if "history" in row:
        out["history"] = [
            {
                "seq": h["seq"], "kind": h["kind"], "reviewState": h["review_state"], "paymentStatus": h["payment_status"],
                "paidAmountPaise": h["paid_amount_paise"], "reason": h["reason"], "createdAt": _iso(h["created_at"]),
            }
            for h in row["history"]
        ]
    return out


def _require_write(ctx: AuthContext) -> UUID:
    """`financials.adjust` (EXP-05) and the CFO entitlement gate; returns the tenant id."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=WRITE_CODE)
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=FINANCIALS_ADJUST):
        raise HTTPException(status_code=403, detail="financials.adjust permission required")
    return ctx.tenant_id


def _log_write(ctx: AuthContext) -> None:
    now = datetime.now(timezone.utc)
    agent_run_repo.insert_run(
        ctx.tenant_id, agent_id="CFO", trigger_type="DIRECT", trigger_ref=TRIGGER_REF, requested_by=ctx.app_user_id, permission_check="PASS",
        entitlement_check="PASS", status="COMPLETE", started_at=now, finished_at=now,
    )


def _existing(tenant: UUID, expense_id: UUID) -> dict[str, Any]:
    row = ledger.get_record(tenant, expense_id)
    if row is None:
        raise HTTPException(status_code=404, detail="expense not found")
    return row


def _new_record(body: _Content, **links: Any) -> NewRecord:
    category = rules.CATEGORIES[body.category]
    return NewRecord(
        effective_date=body.effective_date, category=body.category, cost_class=body.cost_class or category.cost_class,
        treatment=body.treatment or category.treatment, amount_paise=body.amount_paise, vendor=body.vendor, description=body.description,
        channel_scope=body.channel_scope, sku=body.sku, origin="MANUAL", source_validated=False, identifier=None, source_reference="manual", **links,
    )


@router.get("/categories")
def get_categories(ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """The closed category list with each category's default cost class and treatment, the enumerations and the proposed limits (no tenant data)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=READ_CODE)
    return {
        "categories": [{"id": k, "label": c.label, "costClass": c.cost_class, "treatment": c.treatment} for k, c in rules.CATEGORIES.items()],
        "costClasses": sorted(rules.COST_CLASSES),
        "treatments": sorted(rules.TREATMENTS),
        "channelTags": sorted(rules.CHANNEL_TAGS),
        "reviewStates": list(rules.REVIEW_STATES),
        "paymentStatuses": list(rules.PAYMENT_STATUSES),
        "limits": {
            "amountMaxPaise": rules.AMOUNT_MAX_PAISE, "vendorMax": rules.VENDOR_MAX, "descriptionMax": rules.DESCRIPTION_MAX,
            "reasonMax": rules.REASON_MAX, "pageSizeDefault": rules.PAGE_SIZE_DEFAULT, "pageSizeMax": rules.PAGE_SIZE_MAX,
        },
    }


@router.post("", status_code=201)
def create_expense(body: CreateRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)):  # noqa: ANN201
    tenant = _require_write(ctx)
    result = ledger.insert_record(tenant, _new_record(body), review_state=body.state, created_by=ctx.app_user_id, idempotency_key=body.idempotency_key)
    if result.replayed:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=200, content={"expenseId": str(result.expense_id), "replayed": True})
    _log_write(ctx)
    return {"expenseId": str(result.expense_id), "replayed": False}


@router.get("")
def list_expenses(
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    cost_class: str | None = None,
    review_state: Literal["draft", "pending_review", "confirmed", "voided"] | None = None,
    payment_status: Literal["unpaid", "partially_paid", "paid", "unknown"] | None = None,
    channel_scope: str | None = None,
    include_voided: bool = False,
    limit: int = Query(default=rules.PAGE_SIZE_DEFAULT, ge=1, le=rules.PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = require_auth(permission=AGENT_CFO),
) -> dict[str, object]:
    """Records, newest first, with their current review state and payment status. `total` is a row count; no amount is summed here (totals come from the engine)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=READ_CODE)
    rows, total = ledger.list_records(
        ctx.tenant_id, date_from=date_from, date_to=date_to, category=category, cost_class=cost_class, review_state=review_state,
        payment_status=payment_status, channel_scope=channel_scope, include_voided=include_voided, limit=limit, offset=offset,
    )
    return {"records": [_record(r) for r in rows], "total": total, "limit": limit, "offset": offset}


class SummaryRequest(_Strict):
    period_start: date
    period_end: date
    as_of_date: date | None = None

    @model_validator(mode="after")
    def _period(self) -> "SummaryRequest":
        if self.period_end < self.period_start:
            raise ValueError("period_end is before period_start")
        return self


SUMMARY_CONFIG_VERSION = "EXPENSE_LEDGER_FEED.v1"
_CLASS_ORDER = ("ADVERTISING", "STORAGE", "OVERHEAD", "DIRECT")


@router.post("/summary")
def post_summary(body: SummaryRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """Dashboard totals for a period, produced by the engine's ledger feed (`calc_engine.formulas.ledger_feed`) and stamped as `EXPENSE_*` metric results: every
    figure here carries the `engineResultRef` of the stored result, and nothing in this handler adds or compares an amount (AC17). Only confirmed, non-voided,
    `incremental` rows count; `pending_review` rows appear in the review queue and the "including unresolved" figure; a cost class with no row is "not entered",
    never zero. The release-gated profit lines (unallocated, total profit) are NOT produced here."""
    assert ctx.tenant_id is not None
    tenant = ctx.tenant_id
    _require_cfo_entitlement(tenant, direct_action_code=READ_CODE)
    now = datetime.now(timezone.utc)
    events = ledger.feed_events(tenant, period_start=body.period_start, period_end=body.period_end)
    catalog = {sku: sku for sku in ledger.known_skus(tenant)}
    feed = ledger_feed(events, period_start=body.period_start, period_end=body.period_end, channel_scope=None, catalog=catalog)
    minted = mint_ledger_feed_metrics(
        feed, ingestion_run_ids=[], adapter_versions=[], active_adjustment_ids=[], computed_at=now, as_of_date=body.as_of_date or now.date()
    )
    period = f"{body.period_start.isoformat()}/{body.period_end.isoformat()}"
    metric_result_repo.save_many(
        tenant,
        [(m.result, {"grain": m.grain, "target_ref": str(tenant) if m.target_ref == "tenant" else m.target_ref, "period": period,
                     "config_version": SUMMARY_CONFIG_VERSION}) for m in minted],
    )
    by_code: dict[str, list[Any]] = {}
    for m in minted:
        by_code.setdefault(m.result.metric_code, []).append(m)

    def one(code: str) -> Any:
        return by_code[code][0].result

    def fig(result: Any, key: str = "paise") -> dict[str, object]:
        return {key: result.value_paise, "engineResultRef": str(result.id), "asOfDate": _iso(result.as_of_date)}

    return {
        "periodStart": body.period_start.isoformat(),
        "periodEnd": body.period_end.isoformat(),
        "asOfDate": _iso(body.as_of_date or now.date()),
        "watermark": feed.watermark,
        "expenseTotal": fig(one("EXPENSE_TOTAL")),
        "includingUnresolved": fig(one("EXPENSE_INCLUDING_UNRESOLVED")),
        "recurringTotal": fig(one("EXPENSE_RECURRING_TOTAL")),
        "reviewQueue": {
            **fig(one("EXPENSE_REVIEW_QUEUE_AMOUNT"), "amountPaise"),
            "items": [{"expenseId": i.expense_id, "reason": i.reason, "amountPaise": i.amount.value} for i in feed.review_queue],
        },
        "byCostClass": [{"costClass": m.target_ref, **fig(m.result)} for m in sorted(by_code.get("EXPENSE_BY_COST_CLASS", []), key=lambda x: _CLASS_ORDER.index(x.target_ref))],
        "byCategory": [
            {"category": m.target_ref, "label": rules.CATEGORIES[m.target_ref].label if m.target_ref in rules.CATEGORIES else m.target_ref, **fig(m.result)}
            for m in sorted(by_code.get("EXPENSE_BY_CATEGORY", []), key=lambda x: x.target_ref)
        ],
        "notEntered": [c for c in _CLASS_ORDER if not feed.pools[c].entered],
        "gaps": list(feed.gaps),
    }


@router.get("/{expense_id}")
def get_expense(expense_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=READ_CODE)
    return _record(_existing(ctx.tenant_id, expense_id))


@router.post("/{expense_id}/correct", status_code=201)
def correct_expense(expense_id: UUID, body: CorrectRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)):  # noqa: ANN201
    """An edit is a linked correction: a NEW record that points at the original, which is voided in the same transaction. Nothing is overwritten."""
    tenant = _require_write(ctx)
    original = _existing(tenant, expense_id)
    if original["review_state"] == "voided":
        raise HTTPException(status_code=409, detail="a voided record cannot be corrected")
    result = ledger.insert_record(
        tenant, _new_record(body, corrects_expense_id=expense_id), review_state=original["review_state"], created_by=ctx.app_user_id,
        payment_status=original["payment_status"] or "unknown", paid_amount_paise=original["paid_amount_paise"], idempotency_key=body.idempotency_key,
        void_original=(expense_id, body.reason or "corrected"),
    )
    if result.replayed:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=200, content={"expenseId": str(result.expense_id), "replayed": True})
    _log_write(ctx)
    return {"expenseId": str(result.expense_id), "replayed": False}


@router.post("/{expense_id}/refund", status_code=201)
def refund_expense(expense_id: UUID, body: RefundRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)):  # noqa: ANN201
    """A refund or credit note: a NEW negative record linked to the original and dated in its own period (Q21, Q24)."""
    tenant = _require_write(ctx)
    original = _existing(tenant, expense_id)
    if original["review_state"] == "voided":
        raise HTTPException(status_code=409, detail="a voided record cannot be refunded")
    record = NewRecord(
        effective_date=body.effective_date, category=original["category"], cost_class=original["cost_class"], treatment=original["treatment"],
        amount_paise=body.amount_paise, vendor=original["vendor"], description=body.description or "Refund / credit note",
        channel_scope=original["channel_scope"], sku=original["sku"], origin="MANUAL", source_reference="manual", refund_of_expense_id=expense_id,
    )
    result = ledger.insert_record(tenant, record, review_state="confirmed", created_by=ctx.app_user_id, idempotency_key=body.idempotency_key)
    if result.replayed:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=200, content={"expenseId": str(result.expense_id), "replayed": True})
    _log_write(ctx)
    return {"expenseId": str(result.expense_id), "replayed": False}


@router.post("/{expense_id}/void")
def void_expense(expense_id: UUID, body: VoidRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    tenant = _require_write(ctx)
    current = _existing(tenant, expense_id)
    if current["review_state"] == "voided":
        return {"expenseId": str(expense_id), "changed": False}
    replay = ledger.append_review(tenant, expense_id, review_state="voided", reason=body.reason, created_by=ctx.app_user_id, idempotency_key=body.idempotency_key)
    if not replay:
        _log_write(ctx)
    return {"expenseId": str(expense_id), "changed": not replay}


@router.post("/{expense_id}/review")
def set_review_state(expense_id: UUID, body: ReviewRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    tenant = _require_write(ctx)
    current = _existing(tenant, expense_id)
    if not rules.review_transition_allowed(current["review_state"], body.state):
        raise HTTPException(status_code=409, detail=f"a {current['review_state']} record cannot move to {body.state}")
    if current["review_state"] == body.state:
        return {"expenseId": str(expense_id), "changed": False}
    replay = ledger.append_review(tenant, expense_id, review_state=body.state, reason=None, created_by=ctx.app_user_id, idempotency_key=body.idempotency_key)
    if not replay:
        _log_write(ctx)
    return {"expenseId": str(expense_id), "changed": not replay}


@router.post("/{expense_id}/payment")
def set_payment_status(expense_id: UUID, body: PaymentRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """Payment status is a separate field and never changes the economic margin (P3); it is display and filtering only."""
    tenant = _require_write(ctx)
    current = _existing(tenant, expense_id)
    if current["review_state"] == "voided":
        raise HTTPException(status_code=409, detail="a voided record's payment status cannot change")
    replay = ledger.append_payment(
        tenant, expense_id, payment_status=body.status, paid_amount_paise=body.paid_amount_paise, created_by=ctx.app_user_id, idempotency_key=body.idempotency_key
    )
    if not replay:
        _log_write(ctx)
    return {"expenseId": str(expense_id), "changed": not replay}
