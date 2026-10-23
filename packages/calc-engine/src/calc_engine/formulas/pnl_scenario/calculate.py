"""`calculate_scenario` — the single entry point for a hypothetical P&L over seller-typed inputs (docs/specs/calculator.md §14).

Rounding: each displayed line is rounded to the paisa with `round_half_up_paise` (half away from zero for negatives, deterministic-engine.md
§5.11/§G) and a view's profit is revenue minus its ROUNDED lines, so the figures on screen always add up. Margins and ratios are computed
from the exact totals. The reference calculator rounds the same way (verified identical for negative half-paise values by the parity tests),
so there is no rounding difference to carry.
"""

from __future__ import annotations

from fractions import Fraction

from calc_engine.formulas.pnl_scenario.model import (
    ONE,
    ZERO,
    ExactTotals,
    Prepared,
    evaluate,
    prepare,
)
from calc_engine.formulas.pnl_scenario.types import (
    Breakdown,
    LineShare,
    Segment,
    LineGroup,
    Line,
    Metrics,
    OrderCounts,
    ScenarioInputs,
    ScenarioResult,
    View,
)
from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Paise

_FEE_GROUPS: frozenset[LineGroup] = frozenset({"commission", "shipping", "fulfilment", "other_fee", "fee_gst", "fee_refund"})


def _to_bps(ratio: Fraction) -> int:
    return round_half_up_paise(ratio * 10000).value


def make_view(totals: ExactTotals, divisor: Fraction, opex: Fraction | None) -> View:
    """Round every line to the paisa, then derive profit from the rounded lines so the screen always adds up."""

    def rd(x: Fraction) -> Paise:
        return round_half_up_paise(x / divisor)

    revenue = rd(totals.revenue)
    lines = tuple(Line(ln.id, ln.label, ln.group, rd(ln.amount)) for ln in totals.lines)
    contribution = Paise(revenue.value - sum(ln.amount.value for ln in lines))
    if opex is None:
        return View(revenue, lines, contribution)
    ox = rd(opex)
    return View(revenue, lines, contribution, ox, Paise(contribution.value - ox.value))


def _compute_metrics(p: Prepared, t: ExactTotals, price: int) -> Metrics:
    def ratio_bps(num: Fraction, den: Fraction) -> int | None:
        return _to_bps(num / den) if den > 0 else None

    fee_costs = sum((ln.amount for ln in t.lines if ln.group in _FEE_GROUPS), ZERO)
    sales_incl_gst = p.k * price
    f = ONE / (ONE + p.services_gst) if p.itc else ONE
    cm_before_ads_on_sales = t.contribution_before_ads / sales_incl_gst if sales_incl_gst > 0 else ZERO
    per_kept_before_ads = t.contribution_before_ads / p.k

    ads = p.ads
    ad_revenue = p.ad_revenue
    ads_known = ads is not None and ads > 0
    ad_rev_known = ad_revenue is not None and ad_revenue > 0

    return Metrics(
        contribution_margin_bps=ratio_bps(t.contribution, t.revenue),
        operating_margin_bps=ratio_bps(t.contribution - p.opex, t.revenue) if p.opex is not None and p.opex_answered else None,
        effective_fee_bps=ratio_bps(fee_costs, t.revenue),
        acos_bps=ratio_bps(ads, ad_revenue) if ads is not None and ad_revenue is not None and ads_known and ad_rev_known else None,
        tacos_bps=ratio_bps(ads, sales_incl_gst) if ads is not None and ads_known else None,
        roas_bps=ratio_bps(ad_revenue, ads) if ads is not None and ad_revenue is not None and ads_known and ad_rev_known else None,
        break_even_roas_bps=_to_bps(f / cm_before_ads_on_sales) if p.ads is not None and cm_before_ads_on_sales > 0 else None,
        max_cac=round_half_up_paise(per_kept_before_ads / f) if p.ads is not None and per_kept_before_ads > 0 else None,
        gst_recovered_per_kept=round_half_up_paise(t.itc_recovered / p.k) if p.itc else None,
        gst_recovered_monthly=round_half_up_paise(t.itc_recovered) if p.itc and p.has_monthly_orders else None,
    )


TOP_COST_COUNT = 3


def _breakdown(totals: ExactTotals, per_kept: View) -> Breakdown | None:
    """Shares of revenue per line, the chart slices and the biggest costs, all from the EXACT totals (the divisor cancels, so it is the same per order kept
    as monthly). Amounts shown beside them are the rounded per-order-kept ledger amounts."""
    revenue = totals.revenue
    if revenue <= 0:
        return None
    shown = {ln.id: ln.amount for ln in per_kept.lines}
    shares = [LineShare(ln.id, ln.label, ln.group, shown[ln.id], _to_bps(ln.amount / revenue)) for ln in totals.lines]
    profit_share = _to_bps(totals.contribution / revenue)

    costs = [(ln, sh) for ln, sh in zip(totals.lines, shares) if ln.amount > 0]
    top = tuple(sh for _, sh in sorted(costs, key=lambda pair: -pair[0].amount)[:TOP_COST_COUNT])  # stable: ties keep ledger order

    reason: str | None = None
    if any(ln.amount < 0 for ln in totals.lines):
        reason = "A fee refund is a credit, which cannot be drawn as a slice. See the ledger for the exact lines."
    elif totals.contribution < 0:
        reason = "Costs are higher than revenue, so there is no profit slice to draw. See the ledger."
    segments: tuple[Segment, ...] | None = None
    if reason is None:
        out: list[Segment] = []
        cum = ZERO
        for ln, sh in costs:
            start = _to_bps(cum / revenue)
            cum += ln.amount
            out.append(Segment(ln.id, ln.label, ln.group, sh.amount, sh.share_bps, start, _to_bps(cum / revenue)))
        out.append(Segment("profit", "Left as profit", "profit", per_kept.contribution, profit_share, _to_bps(cum / revenue), 10000))
        segments = tuple(out)
    return Breakdown(tuple(shares), profit_share, segments, reason, top)


def calculate_scenario(inputs: ScenarioInputs) -> ScenarioResult:
    prep = prepare(inputs)
    p = prep.prepared
    if p is None or inputs.selling_price.state != "set":
        return ScenarioResult(
            status="incomplete",
            issues=prep.issues,
            missing_costs=prep.missing_costs,
            assumptions=prep.assumptions,
            scope_note=prep.scope_note,
            is_example=inputs.is_example,
            orders=None,
            no_kept_orders=False,
            per_kept=None,
            per_placed=None,
            monthly=None,
            metrics=None,
        )

    price = inputs.selling_price.value
    totals = evaluate(p, price)
    no_kept = p.k <= 0
    opex = p.opex if p.opex_answered else None

    per_kept = None if no_kept else make_view(totals, p.k, opex)
    return ScenarioResult(
        status="provisional" if prep.missing_costs else "estimate",
        issues=prep.issues,
        missing_costs=prep.missing_costs,
        assumptions=prep.assumptions,
        scope_note=prep.scope_note,
        is_example=inputs.is_example,
        orders=OrderCounts(placed=p.n, kept=p.k, rto=p.rto, returned=p.returned),
        no_kept_orders=no_kept,
        per_kept=per_kept,
        per_placed=make_view(totals, p.n, opex),
        monthly=make_view(totals, ONE, opex) if p.has_monthly_orders else None,
        metrics=None if no_kept else _compute_metrics(p, totals, price),
        breakdown=None if per_kept is None else _breakdown(totals, per_kept),
    )
