"""Expense templates: recurring, amortized and per-order / per-unit definitions (kickoff S4b; engine §5.18.1 / §5.18.2) under `/api/v1/cfo/expense-ledger/templates`.

A template is a standing instruction, not a ledger entry; nothing here is ever counted. `POST /materialise` turns the templates into `pending_review` ledger entries (X10),
one per calendar month, idempotently; the seller then confirms them like any other entry. Amounts come from the engine (`calc_engine.formulas.expense_templates`); this
module validates the shape of a request and routes it. Same gates as the ledger: `agent.cfo`, the CFO entitlement gate, and `financials.adjust` for every write (no new
permission key). One `agent_run` row per write that changed something; an idempotent replay writes none.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field, StrictInt, field_validator, model_validator

from calc_engine.formulas import expense_templates as engine
from calc_engine.repositories import expense_template_repo as repo
from calc_engine.repositories.expense_template_repo import NewTemplate

from backend.api.v1.expense_ledger import READ_CODE, Paise, _check, _iso, _log_write, _require_write, _Strict, _to_int
from backend.api.v1.cfo import _require_cfo_entitlement
from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CFO
from backend.services import expense_ledger_rules as rules

router = APIRouter(prefix="/api/v1/cfo/expense-ledger/templates")

MONTHS_MAX = 120  # PROPOSED: the longest amortization, and the most months one materialisation may span for a template
EARLIEST = date(2000, 1, 1)  # PROPOSED: no template starts before this


class TemplateRequest(_Strict):
    kind: Literal["MONTHLY", "AMORTIZED", "PER_ORDER", "PER_UNIT"]
    category: str
    effective_from: date
    effective_to: date | None = None
    cost_class: str | None = None
    treatment: str | None = None
    vendor: str | None = Field(default=None, max_length=rules.VENDOR_MAX)
    description: str | None = Field(default=None, max_length=rules.DESCRIPTION_MAX)
    channel_scope: str | None = None
    sku: str | None = Field(default=None, max_length=rules.SKU_MAX)
    amount_paise: Paise | None = None
    rate_paise: Paise | None = None
    amortization_months: StrictInt | None = None
    start_month: date | None = None

    @field_validator("amount_paise", "rate_paise", mode="after")
    @classmethod
    def _ints(cls, v: Any) -> Any:
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
    def _shape(self) -> "TemplateRequest":
        if self.effective_from < EARLIEST:
            raise ValueError("effective_from is too early")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to is before effective_from")
        if self.kind in ("MONTHLY", "AMORTIZED"):
            if self.amount_paise is None:
                raise ValueError("amount_paise is required")
            _check(rules.amount_error(self.amount_paise))
            _check(rules.cost_amount_error(self.amount_paise))
            if self.rate_paise is not None:
                raise ValueError("rate_paise applies only to per-order and per-unit templates")
        else:
            if self.rate_paise is None:
                raise ValueError("rate_paise is required")
            _check(rules.amount_error(self.rate_paise))
            _check(rules.cost_amount_error(self.rate_paise))
            if self.amount_paise is not None:
                raise ValueError("amount_paise applies only to monthly and amortized templates")
        if self.kind == "AMORTIZED":
            if self.amortization_months is None or not 1 <= self.amortization_months <= MONTHS_MAX:
                raise ValueError(f"amortization_months must be a whole number from 1 to {MONTHS_MAX}")
        elif self.amortization_months is not None or self.start_month is not None:
            raise ValueError("amortization_months and start_month apply only to amortized templates")
        return self


def _to_new(body: TemplateRequest, *, ended: bool = False) -> NewTemplate:
    category = rules.CATEGORIES[body.category]
    return NewTemplate(
        kind=body.kind, category=body.category, cost_class=body.cost_class or category.cost_class, treatment=body.treatment or category.treatment,
        effective_from=body.effective_from, effective_to=body.effective_to, vendor=body.vendor, description=body.description, amount_paise=body.amount_paise,
        rate_paise=body.rate_paise, amortization_months=body.amortization_months,
        start_month=(body.start_month or body.effective_from) if body.kind == "AMORTIZED" else None, channel_scope=body.channel_scope, sku=body.sku, ended=ended,
    )


def _template(row: dict[str, Any]) -> dict[str, object]:
    return {
        "templateKey": str(row["template_key"]), "version": row["version"], "kind": row["kind"], "vendor": row["vendor"], "description": row["description"],
        "category": row["category"], "categoryLabel": rules.CATEGORIES[row["category"]].label if row["category"] in rules.CATEGORIES else row["category"],
        "costClass": row["cost_class"], "treatment": row["treatment"], "amountPaise": row["amount_paise"], "ratePaise": row["rate_paise"],
        "amortizationMonths": row["amortization_months"], "startMonth": _iso(row["start_month"]), "channelScope": row["channel_scope"], "sku": row["sku"],
        "effectiveFrom": _iso(row["effective_from"]), "effectiveTo": _iso(row["effective_to"]), "ended": row["ended"], "createdAt": _iso(row["created_at"]),
    }


class MaterialiseRequest(_Strict):
    through_month: date


class EndRequest(_Strict):
    effective_to: date


@router.get("")
def list_templates(ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """The newest version of every template. A per-order or per-unit template says why it cannot yet produce an amount."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=READ_CODE)
    return {"templates": [_template(r) for r in repo.list_current(ctx.tenant_id)]}


@router.post("", status_code=201)
def create_template(body: TemplateRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    tenant = _require_write(ctx)
    key = repo.create(tenant, _to_new(body), created_by=ctx.app_user_id)
    _log_write(ctx)
    return {"templateKey": str(key), "version": 1}


@router.post("/materialise")
def materialise(body: MaterialiseRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """Creates the `pending_review` entries up to and including the month. Safe to repeat: an entry is never created twice, and a voided one is not recreated."""
    tenant = _require_write(ctx)
    through = engine.first_of_month(body.through_month)
    if through > engine.add_months(engine.first_of_month(datetime.now(timezone.utc).date()), 1):
        raise HTTPException(status_code=422, detail="through_month may be at most next month")
    for t in repo.list_current(tenant):
        begin = engine.first_of_month(t["start_month"] or t["effective_from"])
        if len(engine.months_inclusive(begin, through)) > MONTHS_MAX + 1 and t["kind"] in ("MONTHLY", "AMORTIZED"):
            raise HTTPException(status_code=422, detail=f"a template would span more than {MONTHS_MAX} months; end it or choose an earlier through_month")
    result = repo.materialise(tenant, through_month=through, created_by=ctx.app_user_id)
    if result.created:
        _log_write(ctx)
    return {
        "created": [str(i) for i in result.created], "alreadyMaterialised": result.replayed,
        "skipped": [{"templateKey": k, "reason": r} for k, r in result.skipped],
    }


@router.post("/{template_key}/version", status_code=201)
def new_version(template_key: UUID, body: TemplateRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """A change of rate or amount is a NEW version; earlier versions, and the entries already made from them, are untouched."""
    tenant = _require_write(ctx)
    try:
        version = repo.new_version(tenant, template_key, _to_new(body), created_by=ctx.app_user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="template not found") from None
    _log_write(ctx)
    return {"templateKey": str(template_key), "version": version}


@router.post("/{template_key}/end", status_code=201)
def end_template(template_key: UUID, body: EndRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """Ends the template: a new version carrying the same terms with an end date. Entries already made stay."""
    tenant = _require_write(ctx)
    versions = repo.versions(tenant, template_key)
    if not versions:
        raise HTTPException(status_code=404, detail="template not found")
    latest = versions[-1]
    if body.effective_to < latest["effective_from"]:
        raise HTTPException(status_code=422, detail="effective_to is before the template starts")
    version = repo.new_version(
        tenant, template_key,
        NewTemplate(
            kind=latest["kind"], category=latest["category"], cost_class=latest["cost_class"], treatment=latest["treatment"], effective_from=latest["effective_from"],
            effective_to=body.effective_to, vendor=latest["vendor"], description=latest["description"], amount_paise=latest["amount_paise"], rate_paise=latest["rate_paise"],
            amortization_months=latest["amortization_months"], start_month=latest["start_month"], channel_scope=latest["channel_scope"], sku=latest["sku"], ended=True,
        ),
        created_by=ctx.app_user_id,
    )
    _log_write(ctx)
    return {"templateKey": str(template_key), "version": version}
