"""HTTP boundary for the hypothetical P&L scenario (`POST /api/v1/cfo/pnl-scenario`, docs/specs/calculator.md §14).

Pure translation, no arithmetic of its own: request JSON -> `calc_engine.formulas.pnl_scenario` inputs, engine result -> response JSON. Money, basis
points and counts cross the wire as integer STRINGS (a JavaScript client cannot hold a large paise amount in a number), `empty` / `na` / `set` are the
only states a client can send (`invalid` is a parse failure the client resolves before submitting), and the request carries no `tenant_id`.

The result is a hypothetical ESTIMATE. It carries `estimateRef` (traceable to the audit `agent_run`, never an `engine_result_ref`), is never written
to `metric_result` and is never part of a CFO total.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, StrictBool

from calc_engine.formulas.pnl_scenario import (
    EMPTY,
    NA,
    MARKETPLACE_FIELDS,
    Band,
    Breakdown,
    Entry,
    FeeAmount,
    FeeInput,
    LineShare,
    Recovery,
    ScenarioInputs,
    ScenarioResult,
    SolveResult,
    SolveTarget,
    View,
    set_,
)
from calc_engine.rounding import round_half_up_paise

FORMULA_VERSION = "PNL_SCENARIO.v1"
ESTIMATE_REF_PREFIX = "pnl-scenario:"

MONEY_CAP = 10**13  # paise (Rs 100 billion)
COUNT_CAP = 10**9
BPS_CAP = 10_000  # 100%
MAX_BANDS = 12
MAX_TARGETS = 4

_DIGITS = re.compile(r"^(0|[1-9][0-9]{0,15})$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EntryIn(_Strict):
    """`empty` (nothing entered — never zero), `na` (a confirmed zero) or `set` with an integer-string value."""

    state: Literal["empty", "na", "set"] = "empty"
    value: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "_EntryIn":
        if self.state == "set":
            if self.value is None or not _DIGITS.match(self.value):
                raise ValueError("a 'set' value must be a non-negative integer string with no sign, decimal point or exponent")
            cap = type(self)._cap()
            if int(self.value) > cap:
                raise ValueError(f"value exceeds the allowed maximum of {cap}")
        elif self.value is not None:
            raise ValueError(f"state '{self.state}' must not carry a value")
        return self

    @classmethod
    def _cap(cls) -> int:  # overridden
        return MONEY_CAP

    def to_entry(self) -> Entry:
        if self.state == "set":
            return set_(int(self.value))  # type: ignore[arg-type]
        return NA if self.state == "na" else EMPTY


class MoneyEntry(_EntryIn):
    """Paise."""

    @classmethod
    def _cap(cls) -> int:
        return MONEY_CAP


class BpsEntry(_EntryIn):
    """Basis points, 0..10000."""

    @classmethod
    def _cap(cls) -> int:
        return BPS_CAP


class CountEntry(_EntryIn):
    @classmethod
    def _cap(cls) -> int:
        return COUNT_CAP


class BandIn(_Strict):
    up_to: str | None = None
    amount: str

    @field_validator("up_to", "amount")
    @classmethod
    def _digits(cls, v: str | None) -> str | None:
        if v is not None and not _DIGITS.match(v):
            raise ValueError("must be a non-negative integer string")
        return v


class FeeAmountIn(_Strict):
    kind: Literal["single", "tiers"]
    amount: str | None = None
    mode: Literal["whole", "marginal"] | None = None
    bands: list[BandIn] | None = Field(default=None, max_length=MAX_BANDS)

    @model_validator(mode="after")
    def _shape(self) -> "FeeAmountIn":
        if self.kind == "single":
            if self.amount is None or not _DIGITS.match(self.amount) or self.mode is not None or self.bands is not None:
                raise ValueError("a single fee needs only an integer-string 'amount'")
        else:
            if self.amount is not None or self.mode is None or not self.bands:
                raise ValueError("a tiered fee needs 'mode' and at least one band, and no 'amount'")
        return self

    def to_amount(self) -> FeeAmount:
        if self.kind == "single":
            return FeeAmount("single", amount=int(self.amount))  # type: ignore[arg-type]
        return FeeAmount(
            "tiers", mode=self.mode, bands=tuple(Band(None if b.up_to is None else int(b.up_to), int(b.amount)) for b in self.bands or [])  # type: ignore[arg-type]
        )


class FeeEntryIn(_Strict):
    state: Literal["empty", "na", "set"] = "empty"
    value: FeeAmountIn | None = None

    @model_validator(mode="after")
    def _check(self) -> "FeeEntryIn":
        if (self.state == "set") != (self.value is not None):
            raise ValueError("a fee carries a value if and only if its state is 'set'")
        return self


class FeeIn(_Strict):
    amount: FeeEntryIn = Field(default_factory=FeeEntryIn)
    refund_bps: BpsEntry = Field(default_factory=BpsEntry)
    basis: Literal["price_incl_gst", "price_excl_gst"] | None = None


class RecoveryIn(_Strict):
    sellable_bps: BpsEntry = Field(default_factory=BpsEntry)
    damaged_bps: BpsEntry = Field(default_factory=BpsEntry)


class TargetIn(_Strict):
    kind: Literal["breakeven", "margin"]
    bps: str = Field(default="0", pattern=r"^(0|[1-9][0-9]{0,3})$")  # integer string, 0..9999 (a target margin is below 100%)
    basis: Literal["contribution", "operating"] = "contribution"


class PnlScenarioHttpRequest(_Strict):
    """No `tenant_id` field exists: the tenant is the session's, and `extra="forbid"` rejects any client attempt to supply one."""

    marketplace: Literal["amazon", "flipkart", "meesho"]
    mode: Literal["quick", "detailed"] = "detailed"
    amazon_fulfilment: Literal["easy_ship", "seller_flex", "fba", "self_ship"] = "easy_ship"
    selling_price: MoneyEntry = Field(default_factory=MoneyEntry)
    gst_rate_bps: BpsEntry = Field(default_factory=BpsEntry)
    gst_status: Literal["registered_itc", "registered_no_itc", "unregistered"] = "registered_itc"
    product_cost: MoneyEntry = Field(default_factory=MoneyEntry)
    purchase_gst_rate_bps: BpsEntry = Field(default_factory=BpsEntry)
    services_gst_rate_bps: BpsEntry = Field(default_factory=BpsEntry)
    packaging_cost: MoneyEntry = Field(default_factory=MoneyEntry)
    fees: dict[str, FeeIn] = Field(default_factory=dict, max_length=12)
    monthly_orders: CountEntry = Field(default_factory=CountEntry)
    rto_bps: BpsEntry = Field(default_factory=BpsEntry)
    return_bps: BpsEntry = Field(default_factory=BpsEntry)
    rto_recovery: RecoveryIn = Field(default_factory=RecoveryIn)
    return_recovery: RecoveryIn = Field(default_factory=RecoveryIn)
    salvage_bps: BpsEntry = Field(default_factory=BpsEntry)
    ad_spend: MoneyEntry = Field(default_factory=MoneyEntry)
    ad_revenue: MoneyEntry = Field(default_factory=MoneyEntry)
    operating_expenses: MoneyEntry = Field(default_factory=MoneyEntry)
    targets: list[TargetIn] = Field(default_factory=list, max_length=MAX_TARGETS)
    # True only when the page filled the form with its fictional example numbers: the result then carries the standing "example data" label. It changes no figure.
    is_example: StrictBool = False

    @model_validator(mode="after")
    def _fees_belong_to_the_marketplace(self) -> "PnlScenarioHttpRequest":
        known = {f.id: f for f in MARKETPLACE_FIELDS[self.marketplace]}
        for fee_id, fee in self.fees.items():
            definition = known.get(fee_id)
            if definition is None:
                raise ValueError(f"unknown fee '{fee_id}' for {self.marketplace}")
            v = fee.amount.value
            if v is None:
                continue
            amounts = [int(v.amount or "0")] if v.kind == "single" else [int(b.amount) for b in v.bands or []]
            limits = [int(b.up_to) for b in (v.bands or []) if b.up_to is not None]
            cap = BPS_CAP if definition.unit == "percent" else MONEY_CAP
            if any(a > cap for a in amounts) or any(x > MONEY_CAP for x in limits):
                raise ValueError(f"fee '{fee_id}' is above the allowed maximum")
            if v.kind == "tiers" and not definition.tierable:
                raise ValueError(f"fee '{fee_id}' does not support price bands")
        return self


class PnlScenarioCompareHttpRequest(_Strict):
    """A base scenario and a what-if variant of it, each a complete scenario request. The page builds the variant from the same form with a few values replaced; the
    difference between the two results is computed by the engine (`calc_engine.formulas.pnl_scenario.compare`)."""

    base: PnlScenarioHttpRequest
    what_if: PnlScenarioHttpRequest


def to_inputs(body: PnlScenarioHttpRequest) -> ScenarioInputs:
    return ScenarioInputs(
        marketplace=body.marketplace,
        mode=body.mode,
        amazon_fulfilment=body.amazon_fulfilment,
        selling_price=body.selling_price.to_entry(),
        gst_rate_bps=body.gst_rate_bps.to_entry(),
        gst_status=body.gst_status,
        product_cost=body.product_cost.to_entry(),
        purchase_gst_rate_bps=body.purchase_gst_rate_bps.to_entry(),
        services_gst_rate_bps=body.services_gst_rate_bps.to_entry(),
        packaging_cost=body.packaging_cost.to_entry(),
        fees={
            fee_id: FeeInput(
                amount=(set_(fee.amount.value.to_amount()) if fee.amount.value is not None else (NA if fee.amount.state == "na" else EMPTY)),
                refund_bps=fee.refund_bps.to_entry(),
                basis=fee.basis,
            )
            for fee_id, fee in body.fees.items()
        },
        monthly_orders=body.monthly_orders.to_entry(),
        rto_bps=body.rto_bps.to_entry(),
        return_bps=body.return_bps.to_entry(),
        rto_recovery=Recovery(body.rto_recovery.sellable_bps.to_entry(), body.rto_recovery.damaged_bps.to_entry()),
        return_recovery=Recovery(body.return_recovery.sellable_bps.to_entry(), body.return_recovery.damaged_bps.to_entry()),
        salvage_bps=body.salvage_bps.to_entry(),
        ad_spend=body.ad_spend.to_entry(),
        ad_revenue=body.ad_revenue.to_entry(),
        operating_expenses=body.operating_expenses.to_entry(),
        is_example=body.is_example,
    )


def to_targets(body: PnlScenarioHttpRequest) -> list[tuple[TargetIn, SolveTarget]]:
    return [(t, SolveTarget(t.kind, int(t.bps))) for t in body.targets]


# ---- response -----------------------------------------------------------------------------------------------------------------------


def _s(n: int | None) -> str | None:
    return None if n is None else str(n)


def _count_text(x: Fraction) -> tuple[str, bool]:
    """A display string for an order count: exact when it terminates within four decimals (an order count times a basis-point share always does),
    else rounded half-up to two decimals and flagged inexact."""
    for k in range(5):
        scaled = x * 10**k
        if scaled.denominator == 1:
            n = int(scaled)
            if k == 0:
                return str(n), True
            digits = str(n).rjust(k + 1, "0")
            return f"{digits[:-k]}.{digits[-k:]}", True
    hundredths = round_half_up_paise(x * 100).value
    return f"{hundredths // 100}.{hundredths % 100:02d}", False


def _count(x: Fraction) -> dict[str, Any]:
    text, exact = _count_text(x)
    return {"num": str(x.numerator), "den": str(x.denominator), "text": text, "exact": exact}


def _view(v: View | None) -> dict[str, Any] | None:
    if v is None:
        return None
    return {
        "revenue": str(v.revenue.value),
        "lines": [{"id": ln.id, "label": ln.label, "group": ln.group, "amount": str(ln.amount.value)} for ln in v.lines],
        "contribution": str(v.contribution.value),
        "operatingExpenses": _s(v.operating_expenses.value) if v.operating_expenses is not None else None,
        "operatingProfit": _s(v.operating_profit.value) if v.operating_profit is not None else None,
    }


def _line_share(x: LineShare) -> dict[str, Any]:
    return {"id": x.id, "label": x.label, "group": x.group, "amount": str(x.amount.value), "shareBps": str(x.share_bps)}


def _breakdown(b: Breakdown | None) -> dict[str, Any] | None:
    """Where each rupee goes, per order kept: shares of revenue, the chart slices (None with a reason when they cannot be drawn) and the biggest costs.
    Every number is the engine's; the browser only draws what it is given."""
    if b is None:
        return None
    return {
        "lines": [_line_share(x) for x in b.lines],
        "profitShareBps": str(b.profit_share_bps),
        "segments": None
        if b.segments is None
        else [
            {"id": g.id, "label": g.label, "group": g.group, "amount": str(g.amount.value), "shareBps": str(g.share_bps), "startBps": str(g.start_bps), "endBps": str(g.end_bps)}
            for g in b.segments
        ],
        "chartUnavailableReason": b.chart_unavailable_reason,
        "topCosts": [_line_share(x) for x in b.top_costs],
    }


def _solution(target: TargetIn, r: SolveResult) -> dict[str, Any]:
    return {
        "target": {"kind": target.kind, "bps": target.bps, "basis": target.basis},
        "outcome": r.kind,
        "price": _s(r.price.value) if r.price is not None else None,
        "ranges": [{"from": str(x.from_price), "to": _s(x.to_price)} for x in r.ranges],
        "excludesMissingCosts": r.excludes_missing_costs,
        "reason": r.reason,
    }


def to_response(result: ScenarioResult, solutions: list[dict[str, Any]], *, estimate_ref: str) -> dict[str, Any]:
    m = result.metrics
    return {
        "kind": "hypothetical_estimate",
        "verification": "unverified_estimate",
        "persisted": False,
        "estimateRef": estimate_ref,
        "formulaVersion": FORMULA_VERSION,
        "status": result.status,
        "isExample": result.is_example,
        "issues": [{"code": i.code, "severity": i.severity, "message": i.message, "field": i.field} for i in result.issues],
        "missingCosts": list(result.missing_costs),
        "assumptions": [{"code": a.code, "label": a.label} for a in result.assumptions],
        "scopeNote": result.scope_note,
        "noKeptOrders": result.no_kept_orders,
        "orders": None
        if result.orders is None
        else {
            "placed": _count(result.orders.placed),
            "kept": _count(result.orders.kept),
            "rto": _count(result.orders.rto),
            "returned": _count(result.orders.returned),
        },
        "perKept": _view(result.per_kept),
        "perPlaced": _view(result.per_placed),
        "monthly": _view(result.monthly),
        "metrics": None
        if m is None
        else {
            "contributionMarginBps": _s(m.contribution_margin_bps),
            "operatingMarginBps": _s(m.operating_margin_bps),
            "effectiveFeeBps": _s(m.effective_fee_bps),
            "acosBps": _s(m.acos_bps),
            "tacosBps": _s(m.tacos_bps),
            "roasBps": _s(m.roas_bps),
            "breakEvenRoasBps": _s(m.break_even_roas_bps),
            "maxCac": _s(m.max_cac.value) if m.max_cac is not None else None,
            "gstRecoveredPerKept": _s(m.gst_recovered_per_kept.value) if m.gst_recovered_per_kept is not None else None,
            "gstRecoveredMonthly": _s(m.gst_recovered_monthly.value) if m.gst_recovered_monthly is not None else None,
        },
        "breakdown": _breakdown(result.breakdown),
        "solutions": solutions,
    }


def solution_dict(target: TargetIn, r: SolveResult) -> dict[str, Any]:
    return _solution(target, r)


def comparison_dict(c: Any) -> dict[str, Any]:
    """The engine's what-if-minus-base changes; a figure that was not available on either side is None, never zero."""
    return {
        "perKeptChange": _s(c.per_kept_change.value) if c.per_kept_change is not None else None,
        "perPlacedChange": _s(c.per_placed_change.value) if c.per_placed_change is not None else None,
        "monthlyChange": _s(c.monthly_change.value) if c.monthly_change is not None else None,
        "marginChangeBps": _s(c.margin_change_bps),
    }
