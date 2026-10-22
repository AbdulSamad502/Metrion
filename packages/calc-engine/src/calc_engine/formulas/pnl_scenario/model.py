"""Input preparation (validation, missing-input tracking, assumptions) and exact evaluation at a selling price.

A faithful port of the reference calculator's `model.ts` semantics (Metrion-P-L-website `docs/CALCULATION.md`), used as the SPECIFICATION:
the arithmetic is exact `Fraction`s, never float. Nothing here assumes a marketplace fee or tax rate; the only defaults are the labelled
assumptions the original documents (80% of returned/RTO units resellable, 18% GST on services, no fee refunds on returns, purchase GST =
product GST) and each one is surfaced in `assumptions`, never applied silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from calc_engine.formulas.pnl_scenario.fields import FeeFieldDef, active_fields
from calc_engine.formulas.pnl_scenario.types import (
    Assumption,
    Entry,
    FeeAmount,
    Issue,
    LineGroup,
    PriceBasis,
    Recovery,
    ScenarioInputs,
)

ZERO = Fraction(0)
ONE = Fraction(1)
HUNDRED_PERCENT = 10000
DEFAULT_RECOVERY_BPS = 8000
DEFAULT_SERVICES_GST_BPS = 1800


def from_bps(bps: int) -> Fraction:
    return Fraction(bps, 10000)


@dataclass(frozen=True, slots=True)
class PreparedFee:
    definition: FeeFieldDef
    amount: FeeAmount
    refund: Fraction
    basis: PriceBasis


@dataclass(frozen=True, slots=True)
class RecoveryShares:
    sellable: Fraction
    damaged: Fraction
    lost: Fraction


@dataclass(frozen=True, slots=True)
class Prepared:
    registered: bool
    itc: bool
    gst: Fraction
    purchase_gst: Fraction
    services_gst: Fraction
    cost: Fraction
    packaging: Fraction | None
    fees: tuple[PreparedFee, ...]
    n: Fraction
    rto: Fraction
    returned: Fraction
    k: Fraction
    has_monthly_orders: bool
    rto_rec: RecoveryShares
    ret_rec: RecoveryShares
    salvage: Fraction
    ads: Fraction | None
    ad_revenue: Fraction | None
    opex: Fraction | None
    opex_answered: bool


@dataclass(frozen=True, slots=True)
class PrepareOutput:
    prepared: Prepared | None
    issues: tuple[Issue, ...]
    missing_costs: tuple[str, ...]
    assumptions: tuple[Assumption, ...]
    scope_note: str | None


def prepare(inputs: ScenarioInputs) -> PrepareOutput:
    issues: list[Issue] = []
    missing_costs: list[str] = []
    assumptions: list[Assumption] = []
    quick = inputs.mode == "quick"

    def block(code: str, message: str, field: str | None = None) -> None:
        issues.append(Issue(code, "blocking", message, field))

    def missing(code: str, name: str, field: str | None = None) -> None:
        issues.append(Issue(code, "missing", f"{name} not entered", field))
        missing_costs.append(name)

    def invalid(e: Entry, label: str, field: str) -> bool:
        if e.state == "invalid":
            block(f"invalid_{field}", f"{label}: {e.reason}", field)
            return True
        return False

    registered = inputs.gst_status != "unregistered"
    itc = inputs.gst_status == "registered_itc"

    # ---- Required inputs ----
    price: int | None = None
    sp = inputs.selling_price
    if sp.state == "set":
        if sp.value > 0:
            price = sp.value
        else:
            block("price_zero", "Selling price must be above zero", "selling_price")
    elif not invalid(sp, "Selling price", "selling_price"):
        block("price_missing", "Enter the selling price", "selling_price")

    gst_bps = 0
    if registered:
        g = inputs.gst_rate_bps
        if g.state == "set":
            gst_bps = g.value
        elif g.state == "na":
            gst_bps = 0
        elif not invalid(g, "GST rate", "gst_rate_bps"):
            block("gst_missing", "Choose the product GST rate", "gst_rate_bps")

    cost = 0
    pc = inputs.product_cost
    if pc.state == "set":
        cost = pc.value
    elif pc.state == "na":
        cost = 0
    elif not invalid(pc, "Product cost", "product_cost"):
        block("cost_missing", "Enter the product cost per unit", "product_cost")

    # ---- Optional GST rates ----
    purchase_gst_bps = gst_bps
    pg = inputs.purchase_gst_rate_bps
    if registered and pg.state == "set":
        purchase_gst_bps = pg.value
    elif registered and pg.state == "empty":
        if itc:
            assumptions.append(Assumption("purchase_gst_default", "Purchase GST assumed equal to the product GST rate"))
    else:
        invalid(pg, "Purchase GST rate", "purchase_gst_rate_bps")

    services_gst_bps = DEFAULT_SERVICES_GST_BPS
    sg = inputs.services_gst_rate_bps
    if sg.state == "set":
        services_gst_bps = sg.value
    elif sg.state == "na":
        services_gst_bps = 0
    elif not invalid(sg, "GST on services", "services_gst_rate_bps"):
        assumptions.append(Assumption("services_gst_default", "18% GST assumed on marketplace charges, packaging and advertising"))

    # ---- Order outcomes ----
    def rate(e: Entry, label: str, field: str, name: str) -> int:
        if e.state == "set":
            return int(e.value)
        if e.state == "na":
            return 0
        if e.state == "invalid":
            invalid(e, label, field)
            return 0
        missing(f"missing_{field}", name, field)
        return 0

    rto_bps = rate(inputs.rto_bps, "RTO %", "rto_bps", "RTO rate (losses from RTO orders)")
    ret_bps = rate(inputs.return_bps, "Return %", "return_bps", "Customer return rate (losses from returns)")
    if rto_bps + ret_bps > HUNDRED_PERCENT:
        block("outcomes_exceed", "RTO % and return % together cannot be more than 100%", "rto_bps")

    n = ONE
    has_monthly_orders = False
    mo = inputs.monthly_orders
    if mo.state == "set":
        n = Fraction(mo.value)
        has_monthly_orders = mo.value > 0
        if not has_monthly_orders:
            n = ONE
    else:
        invalid(mo, "Monthly orders", "monthly_orders")

    rto = n * from_bps(rto_bps)
    returned = n * from_bps(ret_bps)
    k = n - (rto + returned)

    # ---- Return recovery ----
    def shares(rec: Recovery, field: str) -> RecoveryShares:
        if rec.sellable_bps.state == "set":
            sellable = rec.sellable_bps.value
        elif rec.sellable_bps.state == "na":
            sellable = 0
        else:
            invalid(rec.sellable_bps, "Share resold", f"{field}_sellable")
            sellable = DEFAULT_RECOVERY_BPS
        damaged = 0
        if rec.damaged_bps.state == "set":
            damaged = rec.damaged_bps.value
        else:
            invalid(rec.damaged_bps, "Share damaged", f"{field}_damaged")
        if sellable + damaged > HUNDRED_PERCENT:
            block(f"recovery_exceeds_{field}", "Resold + damaged share cannot be more than 100%", field)
        lost = HUNDRED_PERCENT - sellable - damaged
        return RecoveryShares(from_bps(sellable), from_bps(damaged), from_bps(0 if lost < 0 else lost))

    uses_default_recovery = (rto_bps > 0 and inputs.rto_recovery.sellable_bps.state == "empty") or (
        ret_bps > 0 and inputs.return_recovery.sellable_bps.state == "empty"
    )

    def effective(rec: Recovery) -> Recovery:
        if rec.sellable_bps.state == "empty":
            return Recovery(Entry("set", DEFAULT_RECOVERY_BPS), rec.damaged_bps)
        return rec

    rto_rec = shares(effective(inputs.rto_recovery), "rto")
    ret_rec = shares(effective(inputs.return_recovery), "return")
    if uses_default_recovery:
        assumptions.append(Assumption("recovery_default", "80% of returned and RTO units assumed resellable; the rest treated as lost"))
    salvage_bps = 0
    if inputs.salvage_bps.state == "set":
        salvage_bps = inputs.salvage_bps.value
    else:
        invalid(inputs.salvage_bps, "Salvage value", "salvage_bps")

    # ---- Packaging, advertising, operating expenses ----
    packaging: Fraction | None = None
    pk = inputs.packaging_cost
    if pk.state == "set":
        packaging = Fraction(pk.value)
    elif pk.state == "na":
        packaging = ZERO
    elif not invalid(pk, "Packaging", "packaging_cost") and not quick:
        missing("missing_packaging", "Packaging cost", "packaging_cost")

    ads: Fraction | None = None
    ad = inputs.ad_spend
    if ad.state == "set":
        ads = Fraction(ad.value)
    elif ad.state == "na":
        ads = ZERO
    elif not invalid(ad, "Advertising spend", "ad_spend") and not quick:
        missing("missing_ads", "Advertising spend", "ad_spend")
    if ads is not None and ads != 0 and not has_monthly_orders:
        ads = None
        missing("ads_need_orders", "Advertising spend (needs monthly orders to allocate)", "ad_spend")

    ad_revenue: Fraction | None = None
    if inputs.ad_revenue.state == "set":
        ad_revenue = Fraction(inputs.ad_revenue.value)
    else:
        invalid(inputs.ad_revenue, "Ad-attributed revenue", "ad_revenue")

    opex: Fraction | None = None
    opex_answered = False
    ox = inputs.operating_expenses
    if ox.state == "set":
        opex = Fraction(ox.value)
        opex_answered = True
    elif ox.state == "na":
        opex = ZERO
        opex_answered = True
    else:
        invalid(ox, "Operating expenses", "operating_expenses")
    if opex is not None and opex != 0 and not has_monthly_orders:
        opex = None
        opex_answered = False
        issues.append(Issue("opex_need_orders", "info", "Enter monthly orders to see operating profit", "operating_expenses"))

    # ---- Marketplace fees ----
    fees: list[PreparedFee] = []
    any_returns = rto_bps > 0 or ret_bps > 0
    refund_assumed = False
    for definition in active_fields(inputs.marketplace, inputs.amazon_fulfilment):
        if quick and not definition.quick:
            continue
        fi = inputs.fees.get(definition.id)
        entry = fi.amount if fi is not None else Entry("empty")
        matters = definition.material or (definition.material_on_returns and any_returns)
        if entry.state == "invalid":
            block(f"invalid_fee_{definition.id}", f"{definition.label}: {entry.reason}", f"fee.{definition.id}")
            continue
        if entry.state == "empty":
            if matters:
                missing(f"missing_fee_{definition.id}", definition.label, f"fee.{definition.id}")
            continue
        amount: FeeAmount = FeeAmount("single", 0) if entry.state == "na" else entry.value
        if amount.kind == "tiers":
            err = _validate_bands(amount, definition)
            if err:
                block(f"invalid_tiers_{definition.id}", f"{definition.label}: {err}", f"fee.{definition.id}")
                continue
        refund = 0
        rf = fi.refund_bps if fi is not None else Entry("empty")
        if rf.state == "set":
            refund = rf.value
        elif rf.state == "invalid":
            block(f"invalid_refund_{definition.id}", f"{definition.label} refund: {rf.reason}", f"fee.{definition.id}")
        elif rf.state == "empty" and any_returns and definition.charged_on != "kept":
            refund_assumed = True
        basis = (fi.basis if fi is not None and fi.basis is not None else definition.basis)
        fees.append(PreparedFee(definition, amount, from_bps(refund), basis))
    if refund_assumed:
        assumptions.append(Assumption("refund_default", "Marketplace fees assumed not refunded on returned or RTO orders"))
    if registered and any(f.definition.unit == "percent" and f.basis == "price_incl_gst" for f in fees):
        assumptions.append(
            Assumption("fee_basis", "Percentage fees applied to the selling price including GST (change per fee in Detailed mode)")
        )
    if itc and any_returns:
        assumptions.append(
            Assumption("itc_written_off", "No ITC taken on stock written off through returns or RTO (to be confirmed with your CA)")
        )

    has_blocking = any(i.severity == "blocking" for i in issues)
    scope_note = (
        "Quick Estimate leaves out packaging, advertising, operating costs and return/RTO handling fees. Use Detailed Calculation to include them."
        if quick
        else None
    )

    if has_blocking or price is None:
        return PrepareOutput(None, tuple(issues), tuple(missing_costs), tuple(assumptions), scope_note)

    prepared = Prepared(
        registered=registered,
        itc=itc,
        gst=from_bps(gst_bps),
        purchase_gst=from_bps(purchase_gst_bps),
        services_gst=from_bps(services_gst_bps),
        cost=Fraction(cost),
        packaging=None if quick else packaging,
        fees=tuple(fees),
        n=n,
        rto=rto,
        returned=returned,
        k=k,
        has_monthly_orders=has_monthly_orders,
        rto_rec=rto_rec,
        ret_rec=ret_rec,
        salvage=from_bps(salvage_bps),
        ads=None if quick else ads,
        ad_revenue=None if quick else ad_revenue,
        opex=None if quick else opex,
        opex_answered=False if quick else opex_answered,
    )
    return PrepareOutput(prepared, tuple(issues), tuple(missing_costs), tuple(assumptions), scope_note)


def _validate_bands(f: FeeAmount, definition: FeeFieldDef) -> str | None:
    if not definition.tierable:
        return "price bands are not supported for this fee"
    if len(f.bands) < 1:
        return "add at least one band"
    prev: int | None = None
    for i, b in enumerate(f.bands):
        last = i == len(f.bands) - 1
        if b.up_to is None:
            if not last:
                return "only the last band can have no upper limit"
        else:
            if last:
                return "the last band must have no upper limit"
            if prev is not None and b.up_to <= prev:
                return "bands must be in increasing order"
            if b.up_to <= 0:
                return "band limits must be above zero"
            prev = b.up_to
        if definition.unit == "percent" and b.amount > 10000:
            return "rate cannot be above 100%"
    if definition.unit == "flat" and f.mode == "marginal":
        return "progressive bands only apply to percentage fees"
    return None


# ---------------------------------------------------------------------------
# Exact evaluation at a selling price
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExactLine:
    id: str
    label: str
    group: LineGroup
    amount: Fraction  # monthly total in paise (cost positive, credit negative)


@dataclass(frozen=True, slots=True)
class ExactTotals:
    revenue: Fraction
    output_gst: Fraction
    lines: tuple[ExactLine, ...]
    itc_recovered: Fraction
    total_costs: Fraction
    contribution: Fraction
    ads_line: Fraction
    contribution_before_ads: Fraction


def _excl_price(p: Prepared, price: Fraction) -> Fraction:
    return price / (ONE + p.gst) if p.registered else price


def _per_order_fee(fee: PreparedFee, price: Fraction, excl: Fraction) -> Fraction:
    base = price if fee.basis == "price_incl_gst" else excl
    is_pct = fee.definition.unit == "percent"
    f = fee.amount
    if f.kind == "single":
        return base * from_bps(f.amount) if is_pct else Fraction(f.amount)
    if f.mode == "whole":
        for b in f.bands:
            if b.up_to is None or base <= Fraction(b.up_to):
                return base * from_bps(b.amount) if is_pct else Fraction(b.amount)
        return ZERO
    # marginal (percent only): each band's rate applies to the slice of price inside that band
    total = ZERO
    lower = ZERO
    for b in f.bands:
        upper = base if b.up_to is None else min(base, Fraction(b.up_to))
        if upper > lower:
            total += (upper - lower) * from_bps(b.amount)
        if b.up_to is None or base <= Fraction(b.up_to):
            break
        lower = Fraction(b.up_to)
    return total


def price_breakpoints(p: Prepared) -> list[Fraction]:
    """Selling-price values (paise, rational) where any fee's band changes. Used by the solver."""
    pts: list[Fraction] = []
    for fee in p.fees:
        if fee.amount.kind != "tiers":
            continue
        for b in fee.amount.bands:
            if b.up_to is None:
                continue
            bound = Fraction(b.up_to)
            pts.append(bound if fee.basis == "price_incl_gst" or not p.registered else bound * (ONE + p.gst))
    return pts


def evaluate(p: Prepared, price_int: int) -> ExactTotals:
    price = Fraction(price_int)
    excl = _excl_price(p, price)
    n, k, rto, returned = p.n, p.k, p.rto, p.returned
    lines: list[ExactLine] = []
    itc_recovered = ZERO

    def push(id_: str, label: str, group: LineGroup, amount: Fraction) -> None:
        lines.append(ExactLine(id_, label, group, amount))

    revenue = k * excl
    output_gst = k * (price - excl) if p.registered else ZERO

    # Product cost: net of ITC when claimed; written-off units lose the gross cost.
    net_cost = p.cost / (ONE + p.purchase_gst) if p.itc else p.cost
    push("product", "Product cost", "product", k * net_cost)
    if p.itc:
        itc_recovered += k * (p.cost - net_cost)
    salvage_per_unit = p.salvage * net_cost

    def loss_per_unit(r: RecoveryShares) -> Fraction:
        return r.lost * p.cost + r.damaged * max(ZERO, p.cost - salvage_per_unit)

    stock_loss = rto * loss_per_unit(p.rto_rec) + returned * loss_per_unit(p.ret_rec)
    push("stock_loss", "Stock lost on returns and RTO", "stock_loss", stock_loss)

    if p.packaging is not None:
        net = p.packaging / (ONE + p.services_gst) if p.itc else p.packaging
        push("packaging", "Packaging", "packaging", n * net)
        if p.itc:
            itc_recovered += n * (p.packaging - net)

    gross_fees = ZERO
    refunds = ZERO
    non_kept = rto + returned
    for fee in p.fees:
        a = _per_order_fee(fee, price, excl)
        charged = fee.definition.charged_on
        count = n if charged == "shipped" else k if charged == "kept" else non_kept
        refundable = non_kept if charged == "shipped" else ZERO if charged == "kept" else count
        gross = a * count
        gross_fees += gross
        refunds += (a * refundable) * fee.refund
        push(f"fee_{fee.definition.id}", fee.definition.label, fee.definition.group, gross)
    if refunds != 0:
        push("fee_refunds", "Fees refunded on returns", "fee_refund", -refunds)
    net_fees = gross_fees - refunds
    gst_on_fees = net_fees * p.services_gst
    if p.itc:
        itc_recovered += gst_on_fees
    elif gst_on_fees != 0:
        push("fee_gst", "GST on marketplace charges", "fee_gst", gst_on_fees)

    ads_line = ZERO
    if p.ads is not None:
        net = p.ads / (ONE + p.services_gst) if p.itc else p.ads
        ads_line = net
        push("advertising", "Advertising", "advertising", net)
        if p.itc:
            itc_recovered += p.ads - net

    total_costs = sum((ln.amount for ln in lines), ZERO)
    contribution = revenue - total_costs
    return ExactTotals(
        revenue=revenue,
        output_gst=output_gst,
        lines=tuple(lines),
        itc_recovered=itc_recovered,
        total_costs=total_costs,
        contribution=contribution,
        ads_line=ads_line,
        contribution_before_ads=contribution + ads_line,
    )
