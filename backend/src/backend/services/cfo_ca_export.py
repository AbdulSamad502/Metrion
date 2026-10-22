"""The CA export pack (docs/specs/cfo-phase3-scope.md 3e): prepared management material for a chartered accountant — never a return, never a filing.

Every figure is an engine result (or a ledger/levy line summed by the engine's `sum_paise`) and carries its `engine_result_ref` and formula version.
What cannot be computed is listed with the reason — never omitted and never zero. Every sheet starts with the disclaimer. Money appears as integer paise
plus a display string produced by the same integer formatter the CEO uses (no float anywhere). No model is involved.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.formulas.expense_accounting import ExpenseHold, effective_class, expense_breakdown
from calc_engine.repositories import expense_ledger_repo, leak_claim_repo
from calc_engine.repositories.tenant_context import tenant_scope
from calc_engine.types import Paise, RecognitionState, sum_paise
from cfo.planner.plan import PeriodRef
from cfo.reasoning.prompts import GST_DISCLAIMER
from cfo.repositories import agent_data_request_repo

from backend.ceo.figure_format import format_paise
from backend.config import cfo_planner_settings
from backend.services import cfo_actions
from backend.services.cfo_planner_backend import PlannerComponentCodes, PostgresPlannerBackend, cat_marketplaces
from cfo.planner.sql_executor import Scope

DISCLAIMER = ("Prepared management material for review by your chartered accountant. It is NOT a tax return, a GST filing or an audit, and Metrion has filed nothing. "
              "Figures come from the reports you uploaded and the entries you made; items that could not be computed are listed with the reason. "
              "Tax interpretation shown here is indicative unless a rule is marked CA-reviewed.")
SHEETS = ("Cover", "P&L", "Expenses", "GST summary", "TCS-TDS schedule", "Reconciliation", "Exclusions & unavailable", "Open data requests", "Provenance")


@dataclass
class Sheet:
    name: str
    headers: list[str]
    rows: list[list[Any]] = field(default_factory=list)


@dataclass
class CaPack:
    period: PeriodRef
    generated_at: datetime
    data_version: int
    sheets: list[Sheet]


def _money(paise: int | None) -> tuple[int | None, str]:
    return paise, "UNAVAILABLE" if paise is None else format_paise(paise)


def _backend(requested_by: UUID) -> PostgresPlannerBackend:
    s = cfo_planner_settings()
    return PostgresPlannerBackend(
        requested_by=requested_by,
        codes=PlannerComponentCodes(s["fee_codes"], s["forward_logistics_codes"], s["reverse_logistics_codes"], s["non_refunded_fee_codes"]),  # type: ignore[arg-type]
        statement_timeout_ms=int(s["statement_timeout_ms"]), min_coverage=s["min_coverage"], cash_min_samples=int(s["cash_min_samples"]),  # type: ignore[arg-type, call-overload]
    )


def build_pack(tenant_id: UUID, requested_by: UUID, period: PeriodRef) -> CaPack:
    be = _backend(requested_by)
    scope = Scope(period.start, period.end, None, None)
    engine = be.run_engine_metrics(tenant_id, period, scope)
    unavailable: list[list[Any]] = []

    # ---------------------------------------------------------------- P&L
    pnl = Sheet("P&L", ["Line", "Amount (paise)", "Amount (₹)", "Status", "engine_result_ref", "Formula version", "Note"])
    bridge = be.run_bridge_inputs(tenant_id, period, scope)
    refs = {k: engine[k].engine_result_ref for k in engine}

    def line(label: str, value: int | None, status: str, ref: str | None, formula: str, note: str = "") -> None:
        p, rupees = _money(value)
        pnl.rows.append([label, p, rupees, status, ref, formula, note])
        if value is None:
            unavailable.append([label, "UNAVAILABLE", note or "not available"])

    nrr = engine["NET_REALIZED_REVENUE"]
    line("Net Realized Revenue", nrr.value_paise if nrr.available else None, nrr.confidence if nrr.available else "UNAVAILABLE", refs["NET_REALIZED_REVENUE"], nrr.formula_version,
         "" if nrr.available else (nrr.reason or ""))
    labels = {"COGS": "Cost of goods sold", "MARKETPLACE_FEES": "Marketplace fees", "SHIPPING_LOGISTICS": "Shipping and logistics", "ADVERTISING_COSTS": "Advertising costs",
              "RETURN_RTO_LOSSES": "Return and RTO losses", "OTHER_ALLOCATED_COSTS": "Other allocated costs"}
    for code, label in labels.items():
        v = bridge.components.get(code)
        line(label + " (cost, shown positive)", v, "DERIVED" if v is not None else "UNAVAILABLE", None, "component of CONTRIBUTION_PROFIT.v1",
             "a component the engine subtracts in Contribution Profit" if v is not None else "an input is missing; Contribution Profit is unavailable too")
    cp = engine["CONTRIBUTION_PROFIT"]
    line("Contribution Profit (not accounting net profit)", cp.value_paise if cp.available else None, cp.confidence if cp.available else "UNAVAILABLE", refs["CONTRIBUTION_PROFIT"],
         cp.formula_version, "" if cp.available else (cp.reason or ""))
    op = be.run_operating_profit(tenant_id, period, scope)
    line("Management operating profit (before depreciation, interest and tax)", op.value_paise if op.available else None, op.confidence if op.available else "UNAVAILABLE",
         op.engine_result_ref, op.formula_version, ("; ".join(f"{r}: {n}" for r, n in op.exclusions) if op.available else (op.reason or "")) or "")
    for lbl in (op.labels if op.available else ()):
        pnl.rows.append([f"  note: {lbl.replace('_', ' ').lower()}", None, "", "", None, "", ""])

    # ---------------------------------------------------------------- Expenses
    exp = Sheet("Expenses", ["Category", "Class", "Total (paise)", "Total (₹)", "Entries", "Status", "Note"])
    lines = expense_ledger_repo.lines_for_period(tenant_id, period.start, period.end)
    bd = expense_breakdown(lines, period_start=period.start, period_end=period.end)
    for g in bd.groups:
        p, r = _money(g.total_paise)
        exp.rows.append([g.category, g.klass.value, p, r, g.line_count, "UNCLASSIFIED" if g.klass.value == "OTHER_UNCLASSIFIED" else "CONFIRMED CLASS",
                         "excluded from both profit figures until the class is confirmed" if g.klass.value == "OTHER_UNCLASSIFIED" else ""])
    for e in bd.excluded:
        p, r = _money(e.total_paise)
        exp.rows.append([f"(held: {e.hold.value.replace('_', ' ').lower()})", "", p, r, e.line_count, "HELD", "excluded from every total until the seller resolves it"])
        unavailable.append([f"Expenses held ({e.hold.value})", "EXCLUDED", f"{e.line_count} entr{'y' if e.line_count == 1 else 'ies'}, {r}"])
    if not bd.groups and not bd.excluded:
        exp.rows.append(["(no expense entries in this period)", "", None, "UNAVAILABLE", 0, "UNAVAILABLE", "no ledger entry and no declaration for this period"])

    # ---------------------------------------------------------------- GST
    gst = Sheet("GST summary", ["Tax head", "Amount (paise)", "Amount (₹)", "engine_result_ref", "Formula version", "Status"])
    a = be._assembly(tenant_id, period)
    outcome = cfo_actions.render_gst_period_summary(tenant_id, cfo_actions.GstPeriodSummaryRequest(
        lines=a.lines, period_start=period.start, period_end=period.end, as_of_date=period.as_of_date, ingestion_run_ids=a.ingestion_run_ids, adapter_versions=(),
        active_adjustment_ids=a.active_adjustment_ids, requested_by=requested_by))
    for res in outcome.results:
        p, rup = _money(res.value_paise)
        gst.rows.append([res.metric_code, p, rup, str(res.id), res.formula_version, "INDICATIVE"])
    gst.rows.append(["(" + GST_DISCLAIMER + ")", None, "", "", "", ""])

    # ---------------------------------------------------------------- TCS / TDS
    tax = Sheet("TCS-TDS schedule", ["Marketplace", "Order ref", "Line ref", "Component", "Side", "Amount (paise)", "Amount (₹)", "Source row"])
    with tenant_scope(tenant_id) as conn:
        levy = conn.execute(text(
            "SELECT coalesce(s.marketplace, t.marketplace), coalesce(s.order_ref, t.order_ref), coalesce(s.line_ref, t.line_ref), lc.component_code, lc.source_side, lc.amount, "
            "coalesce(s.source_row_number, t.source_row_number) FROM line_component lc "
            "LEFT JOIN sales_line s ON s.id = lc.sales_line_id AND s.tenant_id = lc.tenant_id LEFT JOIN settlement_line t ON t.id = lc.settlement_line_id AND t.tenant_id = lc.tenant_id "
            "WHERE lc.tenant_id = :t AND lc.component_kind = 'LEVY' AND ((s.id IS NOT NULL AND coalesce(s.invoice_date, s.dispatch_date, s.order_date) BETWEEN :a AND :b) "
            "OR (t.id IS NOT NULL AND t.settlement_date BETWEEN :a AND :b)) ORDER BY 1, 2, 3, 4"), {"t": str(tenant_id), "a": period.start, "b": period.end}).all()
    by_code: dict[str, list[int]] = {}
    for mp, order, lref, code, side, amount, row_no in levy:
        p, rup = _money(int(amount))
        tax.rows.append([mp, order, lref, code, side, p, rup, row_no])
        by_code.setdefault(code, []).append(int(amount))
    for code in sorted(by_code):
        p, rup = _money(sum_paise([Paise(v) for v in by_code[code]]).value)
        tax.rows.append([f"TOTAL {code}", "", "", code, "", p, rup, ""])
    if not levy:
        tax.rows.append(["(no TCS or TDS lines in this period)", "", "", "", "", None, "NONE FOUND", ""])
    tax.rows.append(["(TCS and TDS are tax assets that reduce what the marketplace pays out; they are not costs and are not in any profit figure)", "", "", "", "", None, "", ""])

    # ---------------------------------------------------------------- Reconciliation
    rec = Sheet("Reconciliation", ["Discrepancy", "Marketplace", "Category", "Severity", "Amount (paise)", "Amount (₹)", "Claim state (seller-reported)", "Note"])
    with tenant_scope(tenant_id) as conn:
        findings = conn.execute(text("SELECT id, marketplace, leak_category, severity, amount_paise FROM leak_finding WHERE tenant_id = :t ORDER BY marketplace, leak_category, id"),
                                {"t": str(tenant_id)}).all()
    totals: dict[str, list[int]] = {}
    for fid, mp, cat_, sev, amt in findings:
        withheld = mp == "AMAZON"
        state = "WITHHELD" if withheld else leak_claim_repo.current_view(tenant_id, fid).state
        p, rup = (None, "WITHHELD") if withheld else _money(int(amt))
        rec.rows.append([str(fid), mp, cat_, sev, p, rup, state, "Amazon discrepancies are withheld until the match key is verified" if withheld else "discrepancy identified"])
        if not withheld:
            totals.setdefault(mp, []).append(int(amt))
    for mp in sorted(totals):
        p, rup = _money(sum_paise([Paise(v) for v in totals[mp]]).value)
        rec.rows.append([f"TOTAL discrepancies identified — {mp}", mp, "", "", p, rup, "", "a discrepancy identified, not an amount recovered"])
    if not findings:
        rec.rows.append(["(no discrepancies recorded; run a reconciliation to look for them)", "", "", "", None, "NONE FOUND", "", ""])

    # ---------------------------------------------------------------- Exclusions & unavailable
    ex = Sheet("Exclusions & unavailable", ["Item", "Status", "Reason / count"])
    for k, ev in engine.items():
        for reason, n in ev.exclusions:
            ex.rows.append([k, "EXCLUDED", f"{n} × {reason}"])
        if not ev.available:
            ex.rows.append([k, "UNAVAILABLE", ev.reason or "not available"])
    if a.blocked:
        ex.rows.append(["Order lines blocked pending your input", "EXCLUDED", f"{len(a.blocked)} line(s); the missing input is listed under Open data requests"])
    ex.rows.extend(unavailable)
    if not ex.rows:
        ex.rows.append(["(nothing excluded or unavailable)", "", ""])

    # ---------------------------------------------------------------- Open data requests
    req = Sheet("Open data requests", ["Requested field", "Blocking metric", "Reason", "Status", "Created"])
    for dr in agent_data_request_repo.list_for_tenant(tenant_id):
        if dr.get("status") == "OPEN":
            req.rows.append([dr.get("requested_field"), dr.get("blocking_metric"), dr.get("reason"), dr.get("status"), str(dr.get("created_at"))])
    if not req.rows:
        req.rows.append(["(none open)", "", "", "", ""])

    # ---------------------------------------------------------------- Provenance
    prov = Sheet("Provenance", ["Kind", "Reference", "Detail", "Rows / value", "Version"])
    with tenant_scope(tenant_id) as conn:
        for rid, name, mp, adapter, version, status, read, started in conn.execute(text(
                "SELECT r.id, f.original_filename, f.marketplace, r.adapter_id, r.adapter_version, r.status, r.row_count_read, r.started_at FROM ingestion_run r "
                "JOIN report_file f ON f.id = r.report_file_id AND f.tenant_id = r.tenant_id WHERE r.tenant_id = :t ORDER BY r.started_at"), {"t": str(tenant_id)}):
            prov.rows.append(["INGESTION RUN", str(rid), f"{name} · {mp} · {adapter} · {status}", read, version])
    for ln in lines:
        prov.rows.append(["EXPENSE ENTRY", ln.entry_id, f"{ln.category} · {ln.entry_date.isoformat()} · class {effective_class(ln).value}" + (f" · HELD {ln.hold.value}" if ln.hold is not ExpenseHold.NONE else ""),
                          ln.amount_paise, "expense_ledger.v1"])
    for k, ev in sorted(engine.items()):
        prov.rows.append(["ENGINE RESULT", ev.engine_result_ref or "(none: unavailable)", k, ev.value_paise, ev.formula_version])

    cover = Sheet("Cover", ["Item", "Value"])
    cover.rows += [["Period", f"{period.start.isoformat()} to {period.end.isoformat()}"], ["As of", period.as_of_date.isoformat()],
                   ["Generated at", datetime.now(timezone.utc).isoformat(timespec="seconds")], ["Read-model version", be.data_version(tenant_id)],
                   ["What this is", DISCLAIMER], ["Recognition basis", RecognitionState.RECOGNISED.value],
                   ["Sheets", ", ".join(SHEETS)]]
    sheets = [cover, pnl, exp, gst, tax, rec, ex, req, prov]
    assert tuple(s.name for s in sheets) == SHEETS
    return CaPack(period, datetime.now(timezone.utc), be.data_version(tenant_id), sheets)


# ---------------------------------------------------------------------------------------------------- rendering
def to_xlsx(pack: CaPack) -> bytes:
    from openpyxl import Workbook  # type: ignore[import-untyped]
    from openpyxl.styles import Font, Alignment  # type: ignore[import-untyped]

    wb = Workbook()
    wb.remove(wb.active)
    for sh in pack.sheets:
        ws = wb.create_sheet(sh.name[:31])
        ws.append([DISCLAIMER])
        ws["A1"].font = Font(italic=True)
        ws["A1"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.append([])
        ws.append(sh.headers)
        for c in ws[3]:
            c.font = Font(bold=True)
        for row in sh.rows:
            ws.append(row)
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(60, max(12, max((len(str(c.value)) for c in col[2:] if c.value is not None), default=12) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_csv_zip(pack: CaPack) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sh in pack.sheets:
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow([DISCLAIMER])
            w.writerow([])
            w.writerow(sh.headers)
            w.writerows(sh.rows)
            zf.writestr(f"{sh.name.replace('&', 'and').replace(' ', '_')}.csv", out.getvalue())
    return buf.getvalue()
