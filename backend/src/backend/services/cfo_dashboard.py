"""CFO 2.0 dashboard read model (docs/specs/cfo-dashboard-implementation.md §3–4).

Every figure the dashboard shows is produced by the SAME planner pipeline the CEO uses — a fixed, server-built plan (no model, no seller-supplied plan) run through
the validator, the executor and the evidence cache — so a dashboard figure and the CEO's narrated figure for the same tenant, period and filter come from one
evidence packet (AC-DI5). This module only reshapes evidence into `FigureData` objects: the value is the server's display string, the completeness and register are
derived from the packet's own status and labels, and nothing is computed here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from fractions import Fraction
from typing import Any
from uuid import UUID

from cfo.planner.evidence import EvidencePacket, Figure
from cfo.planner.pipeline import PlannerAnswer, PlannerRefusal, PlannerRequest
from cfo.planner.plan import PeriodRef

from backend.ceo.figure_format import format_paise, format_percent_number, format_units
from backend.services.cfo_query import answer_financial_query

TAB, CR, CRLF = chr(9), chr(13), chr(13) + chr(10)
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")

# Labels the engine and planner attach → one fixed plain sentence each. An unknown label is never shown raw.
_NOTES = {
    "PARTIAL_MARKETPLACE_COVERAGE": "Some marketplaces are left out of this total because their data is incomplete; see the coverage below.",
    "ADVERTISING_FROM_REPORT": "Advertising spend comes from your uploaded advertising report.",
    "COSTS_FROM_LEDGER": "Some costs come from your expense ledger.",
    "PARTIAL_AD_COVERAGE": "Advertising data does not cover every marketplace.",
    "LEGACY_ZERO_AD_SPEND": "This profit treats missing advertising entries as no advertising spend.",
}
_PCT_NUMBER_METRICS = {"FEE_RATIO_PCT", "RETURN_RATE_PCT", "CONTRIBUTION_MARGIN_PCT"}  # stored on the percent-number scale
_RATIO_METRICS = {"ROAS", "ACOS", "TACOS"}  # stored as plain ratios


class FixedPlan:
    """A planner provider that returns one server-built plan. The dashboard never asks a model for a plan."""

    def __init__(self, steps: list[dict[str, Any]], periods: Sequence[PeriodRef], intent: str = "METRIC_BY_DIMENSION") -> None:
        self._json = json.dumps({
            "plan_version": "1", "intent": intent, "limit": 50, "steps": steps,
            "periods": [{"start": p.start.isoformat(), "end": p.end.isoformat(), "as_of_date": p.as_of_date.isoformat()} for p in periods]})

    def propose(self, request: PlannerRequest) -> str:  # noqa: ARG002
        return self._json


@dataclass(frozen=True, slots=True)
class Scope:
    start: date
    end: date
    as_of: date
    marketplace: str = "ALL"


def _metric(m: str) -> dict[str, Any]:
    return {"op": "metric", "params": {"metric": m}}


def _scope_steps(scope: Scope) -> list[dict[str, Any]]:
    if scope.marketplace == "ALL":
        return []
    return [{"op": "filter", "params": {"dimension": "marketplace", "op": "eq", "value": scope.marketplace}}]


def run(tenant_id: UUID, requested_by: UUID, scope: Scope, steps: list[dict[str, Any]], *, intent: str = "METRIC_BY_DIMENSION",
        extra_periods: Sequence[PeriodRef] = ()) -> PlannerAnswer | PlannerRefusal:
    periods = [PeriodRef(scope.start, scope.end, scope.as_of), *extra_periods]
    return answer_financial_query(tenant_id, requested_by=requested_by, question="dashboard", periods=periods, provider=FixedPlan(_scope_steps(scope) + steps, periods, intent))


# ------------------------------------------------------------------------------------------------ figure shaping
def _ratio_x(value: Fraction) -> str:
    hundredths = int(value * 100 + Fraction(1, 2)) if value >= 0 else -int(-value * 100 + Fraction(1, 2))
    whole, frac = divmod(abs(hundredths), 100)
    return f"{'-' if hundredths < 0 else ''}{whole}.{frac:02d}x"


def display_for(f: Figure) -> str | None:
    if f.status == "UNAVAILABLE":
        return None
    if f.value_paise is not None:
        return format_paise(f.value_paise)
    if f.value_fraction is not None:
        num, den = (int(x) for x in f.value_fraction.split("/"))
        if f.metric_id in _PCT_NUMBER_METRICS:
            return format_percent_number(num, den)
        if f.metric_id == "ROAS":
            return _ratio_x(Fraction(num, den))
        if f.metric_id in _RATIO_METRICS:  # ACOS, TACOS: a plain ratio shown as a percentage
            return format_percent_number(num * 100, den)
        return format_percent_number(num, den)
    if f.value_count is not None:
        return format_units(f.value_count)
    return None


def completeness_of(f: Figure) -> str:
    if f.status == "UNAVAILABLE":
        return "UNAVAILABLE"
    if f.estimate_ref:
        return "ESTIMATED"
    if f.status == "PARTIAL" or any(lbl.startswith("PARTIAL_") for lbl in f.labels):
        return "PARTIAL"
    if f.status in ("PROVISIONAL", "ESTIMATED"):
        return "PROVISIONAL" if f.status == "PROVISIONAL" else "ESTIMATED"
    return "COMPLETE"


def register_of(f: Figure) -> str:
    if f.status == "UNAVAILABLE":
        return "UNAVAILABLE"
    if f.estimate_ref or f.status == "ESTIMATED":
        return "ESTIMATE"
    return {"VERIFIED": "VERIFIED", "MANUAL": "MANUAL"}.get(f.status, "DERIVED")


def _notes(f: Figure) -> list[str]:
    out = [_NOTES[lbl] for lbl in f.labels if lbl in _NOTES]
    out += ["Advertising is recorded in more than one place for the same dates; choose which one is right." for lbl in f.labels if lbl.startswith("ADVERTISING_SOURCE_CONFLICT_")]
    out += ["A cost is recorded in more than one place for the same dates; choose which one is right." for lbl in f.labels if lbl.startswith("COST_SOURCE_CONFLICT_")]
    return list(dict.fromkeys(out))


def figure_data(f: Figure, label: str, packet: EvidencePacket, *, period_text: str, generated_at: str) -> dict[str, Any]:
    ref = f.engine_result_ref or f.estimate_ref
    ad = next((lbl.removeprefix("AD_STATUS_") for lbl in f.labels if lbl.startswith("AD_STATUS_")), None)
    unavailable = f.status == "UNAVAILABLE"
    return {
        "label": label, "valueDisplay": display_for(f), "completeness": completeness_of(f), "register": register_of(f),
        "source": [] if unavailable else [{"kind": "ENGINE", "label": "Calculated by Metrion from the files you uploaded", "refId": ref}],
        "lastUpdated": generated_at, "asOfDate": packet.as_of_date.isoformat(), "periodCoverage": period_text,
        "engineResultRef": f.engine_result_ref, "estimateRef": f.estimate_ref, "formulaVersion": f.formula_version,
        "exclusions": [{"reason": r, "count": n, "amountDisplay": None} for r, n in f.exclusions],
        "missingInputs": [{"field": m, "why": f.unavailable_reason or "a required input is missing", "dataRequestId": None} for m in f.missing_inputs] if unavailable else [],
        "statusNotes": _notes(f), "adSpendStatus": ad, "unavailableReason": f.unavailable_reason if unavailable else None,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _period_text(s: Scope) -> str:
    return f"{s.start.isoformat()} to {s.end.isoformat()}"


def _by(packet: EvidencePacket, **dims: str) -> dict[str, Figure]:
    out: dict[str, Figure] = {}
    for f in packet.figures:
        keys = dict(f.dimension_keys)
        if all(keys.get(k) == v for k, v in dims.items()):
            out.setdefault(f.metric_id, f)
    return out


def _cell(f: Figure | None) -> dict[str, Any]:
    if f is None:
        return {"display": None, "status": "UNAVAILABLE"}
    return {"display": display_for(f), "status": completeness_of(f)}


def refused(r: PlannerRefusal) -> dict[str, Any]:
    return {"status": "REFUSED", "code": r.code, "message": r.message}


def coverage_view(packet: EvidencePacket) -> list[dict[str, Any]]:
    return [{"metricId": c.metric_id, "marketplace": c.marketplace, "included": c.included, "sharePct": c.share_pct, "thresholdPct": c.threshold_pct, "reason": c.reason,
             "excludedLineCount": c.excluded_line_count, "excludedBasis": c.excluded_basis,
             "excludedAmountDisplay": None if c.excluded_amount_paise is None else format_paise(c.excluded_amount_paise)} for c in packet.coverage]


# ------------------------------------------------------------------------------------------------ views
OVERVIEW_KPIS = (
    ("CONTRIBUTION_PROFIT", "Contribution Profit"),
    ("NET_REALIZED_REVENUE", "Net Realized Revenue"),
    ("OPERATING_PROFIT", "Operating Profit"),
    ("SETTLEMENT_RECEIPTS", "Settlements received"),
    ("LEAK_AGGREGATE", "Discrepancies identified"),
)
GST_UNCONFIRMED = {
    "label": "GST / tax assets", "valueDisplay": None, "completeness": "UNAVAILABLE", "register": "UNAVAILABLE", "source": [], "lastUpdated": None, "asOfDate": None,
    "periodCoverage": None, "engineResultRef": None, "estimateRef": None, "formulaVersion": None, "exclusions": [],
    "missingInputs": [{"field": "gst_treatment", "why": "GST treatment is not confirmed yet, so no GST or tax-asset figure is shown", "dataRequestId": None}],
    "statusNotes": [], "adSpendStatus": None, "unavailableReason": "GST treatment is not confirmed yet, so no GST or tax-asset figure is shown",
}


def overview(tenant_id: UUID, requested_by: UUID, scope: Scope) -> dict[str, Any]:
    res = run(tenant_id, requested_by, scope, [_metric(m) for m, _ in OVERVIEW_KPIS])
    if not isinstance(res, PlannerAnswer):
        return refused(res)
    p = res.packet
    figs = _by(p)
    kpis = []
    for metric, label in OVERVIEW_KPIS:
        f = figs.get(metric)
        kpis.append(figure_data(f, label, p, period_text=_period_text(scope), generated_at=_now()) if f is not None
                    else {**GST_UNCONFIRMED, "label": label, "missingInputs": [], "unavailableReason": "This figure could not be produced for the chosen filters", "statusNotes": []})
    kpis.append(GST_UNCONFIRMED)
    op = figs.get("OPERATING_PROFIT")
    return {
        "status": "ANSWERED", "dataVersion": p.data_version, "cached": p.cached, "generatedAt": _now(), "planHash": p.plan_hash, "kpis": kpis,
        "operatingProfitState": None if op is None else ("UNAVAILABLE" if op.status == "UNAVAILABLE" else ("PROVISIONAL" if op.status == "PROVISIONAL" else "FINAL")),
        "urgentActions": [{"text": t} for t in p.data_requests], "coverage": coverage_view(p), "labels": list(p.labels),
    }


def marketplaces_table(tenant_id: UUID, requested_by: UUID, scope: Scope, *, sort: str, direction: str) -> dict[str, Any]:
    metrics = ("GROSS_SALES", "NET_REALIZED_REVENUE", "CONTRIBUTION_PROFIT", "CONTRIBUTION_MARGIN_PCT")
    res = run(tenant_id, requested_by, scope, [{"op": "group_by", "params": {"dimensions": ["marketplace"]}}] + [_metric(m) for m in metrics])
    if not isinstance(res, PlannerAnswer):
        return refused(res)
    p = res.packet
    rows = []
    for mp in MARKETPLACES:
        if scope.marketplace not in ("ALL", mp):
            continue
        by = _by(p, marketplace=mp)
        if not by:
            continue
        rows.append({"key": mp, "marketplace": mp, "grossSales": _cell(by.get("GROSS_SALES")), "nrr": _cell(by.get("NET_REALIZED_REVENUE")),
                     "contributionProfit": _cell(by.get("CONTRIBUTION_PROFIT")), "margin": _cell(by.get("CONTRIBUTION_MARGIN_PCT")),
                     "_sort": _sort_values(by)})
    rows = _sorted(rows, sort, direction)
    return {"status": "ANSWERED", "items": [{k: v for k, v in r.items() if k != "_sort"} for r in rows], "dataVersion": p.data_version, "coverage": coverage_view(p), "generatedAt": _now()}


def skus_table(tenant_id: UUID, requested_by: UUID, scope: Scope, *, sort: str, direction: str, page: int, page_size: int) -> dict[str, Any]:
    metrics = ("GROSS_SALES", "NET_REALIZED_REVENUE", "CONTRIBUTION_PROFIT")
    res = run(tenant_id, requested_by, scope, [{"op": "group_by", "params": {"dimensions": ["sku"]}}] + [_metric(m) for m in metrics])
    if not isinstance(res, PlannerAnswer):
        return refused(res)
    p = res.packet
    skus = sorted({k for f in p.figures if (k := dict(f.dimension_keys).get("sku"))})
    rows = []
    for sku in skus:
        by = _by(p, sku=sku)
        rows.append({"key": sku, "sku": sku, "grossSales": _cell(by.get("GROSS_SALES")), "nrr": _cell(by.get("NET_REALIZED_REVENUE")),
                     "contributionProfit": _cell(by.get("CONTRIBUTION_PROFIT")),
                     "_sort": _sort_values(by)})
    rows = _sorted(rows, sort, direction)
    total = len(rows)
    start = (page - 1) * page_size
    return {"status": "ANSWERED", "items": [{k: v for k, v in r.items() if k != "_sort"} for r in rows[start:start + page_size]], "page": page, "pageSize": page_size,
            "total": total, "pageCount": max(1, -(-total // page_size)), "dataVersion": p.data_version, "generatedAt": _now(), "truncated": p.truncated}


def _sort_values(by: dict[str, Figure]) -> dict[str, int | None]:
    def v(m: str) -> int | None:
        f = by.get(m)
        return None if f is None else f.value_paise

    return {"grossSales": v("GROSS_SALES"), "nrr": v("NET_REALIZED_REVENUE"), "contributionProfit": v("CONTRIBUTION_PROFIT")}


def _sorted(rows: list[dict[str, Any]], sort: str, direction: str) -> list[dict[str, Any]]:
    """Order rows by a stored figure (an ordering of values the engine already produced; unavailable rows always last). Not arithmetic."""
    key = sort if sort in ("grossSales", "nrr", "contributionProfit") else None
    if key is None:
        return sorted(rows, key=lambda r: str(r["key"]))
    have = [r for r in rows if r["_sort"][key] is not None]
    lack = [r for r in rows if r["_sort"][key] is None]
    return sorted(have, key=lambda r: r["_sort"][key], reverse=direction == "desc") + lack


def trend(tenant_id: UUID, requested_by: UUID, scope: Scope) -> dict[str, Any]:
    res = run(tenant_id, requested_by, scope, [{"op": "group_by", "params": {"dimensions": ["period"], "period_granularity": "month"}}, _metric("CONTRIBUTION_PROFIT")])
    if not isinstance(res, PlannerAnswer):
        return refused(res)
    p = res.packet
    pts = []
    for f in p.figures:
        label = dict(f.dimension_keys).get("period", "")
        pts.append({"label": label, "plot": f.value_paise if f.status != "UNAVAILABLE" else None, "display": display_for(f), "status": completeness_of(f)})
    pts.sort(key=lambda x: str(x["label"]))
    return {"status": "ANSWERED", "points": pts, "dataVersion": p.data_version, "generatedAt": _now()}


def bridge(tenant_id: UUID, requested_by: UUID, scope: Scope, compare: PeriodRef) -> dict[str, Any]:
    steps = [_metric("PROFIT_BRIDGE"), {"op": "compare", "params": {"kind": "period_over_period", "metric": "PROFIT_BRIDGE"}}]
    res = run(tenant_id, requested_by, scope, steps, intent="PROFIT_BRIDGE", extra_periods=[compare])
    if not isinstance(res, PlannerAnswer):
        return refused(res)
    p = res.packet
    b = p.bridge
    if b is None:
        return {"status": "ANSWERED", "bridge": None, "reasons": [f.unavailable_reason for f in p.figures if f.unavailable_reason], "dataRequests": list(p.data_requests),
                "dataVersion": p.data_version, "generatedAt": _now()}
    return {"status": "ANSWERED", "dataVersion": p.data_version, "generatedAt": _now(), "reconciles": b.reconciles,
            "bridge": {"deltaDisplay": format_paise(b.delta_paise), "otherDisplay": format_paise(b.other_paise), "otherRef": b.other_ref,
                       "drivers": [{"metricId": d.metric_id, "deltaDisplay": format_paise(d.delta_paise), "ref": d.ref} for d in b.drivers]}}


def cash(tenant_id: UUID, requested_by: UUID, scope: Scope) -> dict[str, Any]:
    res = run(tenant_id, requested_by, scope, [_metric("EXPECTED_RECEIPTS"), _metric("CASH_SHORTFALL_STATUS")], intent="CASH_VIEW")
    if not isinstance(res, PlannerAnswer):
        return refused(res)
    p = res.packet
    figs = [figure_data(f, "Expected receipts" if f.metric_id == "EXPECTED_RECEIPTS" else "Payable status", p, period_text=_period_text(scope), generated_at=_now()) for f in p.figures]
    return {"status": "ANSWERED", "figures": figs, "dataRequests": list(p.data_requests), "dataVersion": p.data_version, "coverage": coverage_view(p), "generatedAt": _now(),
            "note": "An estimate from your own settlement history: expected settlements and your payables only. It is not your bank balance."}


def leak_findings(tenant_id: UUID, *, status: str, page: int, page_size: int) -> dict[str, Any]:
    from sqlalchemy import text

    from calc_engine.repositories import leak_claim_repo
    from calc_engine.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(
            "SELECT id, marketplace, leak_category, severity, amount_paise, affected_line_count, sku, age_days, claim_window_days, window_status, status, confidence, engine_result_ref "
            "FROM leak_finding WHERE tenant_id = :t ORDER BY CASE window_status WHEN 'CLOSING_SOON' THEN 0 WHEN 'OPEN' THEN 1 WHEN 'UNKNOWN' THEN 2 ELSE 3 END, amount_paise DESC, id"),
            {"t": str(tenant_id)}).all()
    items = []
    for r in rows:
        view = leak_claim_repo.current_view(tenant_id, r[0])
        mp = str(r[1])
        items.append({"id": str(r[0]), "marketplace": mp, "category": r[2], "severity": r[3], "amount": {"display": format_paise(int(r[4])), "status": "PROVISIONAL" if str(r[11]) != "VERIFIED" else "COMPLETE"},
                      "affectedLines": r[5], "sku": r[6], "ageDays": r[7], "claimWindowDays": r[8], "windowStatus": r[9], "claimState": view.state, "engineResultRef": str(r[12]),
                      "withheld": mp.upper() == "AMAZON", "withheldReason": "Amazon findings are withheld until the join keys are validated on a real export." if mp.upper() == "AMAZON" else None})
    if status != "ALL":
        items = [i for i in items if i["claimState"] == status]
    total = len(items)
    start = (page - 1) * page_size
    return {"status": "ANSWERED", "items": items[start:start + page_size], "page": page, "pageSize": page_size, "total": total, "pageCount": max(1, -(-total // page_size)),
            "generatedAt": _now(), "note": "Seller-reported status only: Metrion never files a claim and does not promise an amount will be returned."}


def alerts(tenant_id: UUID, limit: int) -> dict[str, Any]:
    from backend.ceo import findings

    got = findings.list_visible(tenant_id, ["CFO"], limit=limit)
    return {"status": "ANSWERED", "items": [i for i in got.items if i["agent"] == "CFO"], "generatedAt": _now()}


def payables(tenant_id: UUID) -> dict[str, Any]:
    from calc_engine.repositories import cash_repo

    rows = cash_repo.list_payables(tenant_id)
    return {"status": "ANSWERED", "items": [{"id": r.payable_id, "amount": {"display": format_paise(r.amount_paise), "status": "COMPLETE"}, "dueDate": r.due_date.isoformat() if r.due_date else None,
                                           "supplierRef": r.supplier_ref, "poRef": r.po_ref} for r in rows], "generatedAt": _now()}


def _csv_cell(v: object) -> str:
    """One CSV cell. A value that starts with = + - @ tab or CR could run as a formula when opened in a spreadsheet, so it is prefixed with an apostrophe; an
    unavailable figure is the word "Unavailable", never blank or zero."""
    t = "Unavailable" if v is None else str(v)
    if t[:1] in ("=", "+", "-", "@", TAB, CR):
        t = "'" + t
    return '"' + t.replace('"', '""') + '"'


def csv_text(header: list[str], rows: list[list[object]]) -> str:
    everything: list[list[object]] = [list(header), *rows]
    return CRLF.join(",".join(_csv_cell(c) for c in r) for r in everything) + CRLF

