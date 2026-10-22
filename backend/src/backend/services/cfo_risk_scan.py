"""The proactive CFO risk scan (docs/specs/cfo-phase3-scope.md 3f): deterministic rules, no model, fixed wording, Brain-1 figures cited by reference.

Each signal is recorded as a shared finding by the one module allowed to write them (`backend.ceo.findings.record`): text built from a fixed template carries
no digit; the number lives in `figure_refs` (engine results of this tenant) and is rendered at read time. A signal is de-duplicated by (rule, scope, read-model
version), so scanning the same data again adds nothing. Cash `AT_RISK` is computed and returned but NOT persisted: the shared-finding contract has no kind for it
(open item), and mapping it onto another kind would mislabel it.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from fractions import Fraction
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.api.compute_metric import mint_set_based_result
from calc_engine.formulas.risk_rules import MarginDrop, data_age_days, is_stale, margin_drop
from calc_engine.repositories import ad_report_repo, leak_claim_repo, metric_result_repo
from calc_engine.repositories import read_model_version_repo as rmv
from calc_engine.repositories.tenant_context import tenant_scope
from calc_engine.types import Unavailable
from cfo.planner.plan import PeriodRef
from cfo.planner.sql_executor import Scope

from backend.ceo import findings
from backend.config import cfo_planner_settings
from backend.services import cfo_costs
from backend.services.cfo_planner_backend import PlannerComponentCodes, PostgresPlannerBackend, cat_marketplaces

logger = logging.getLogger(__name__)
_CONFIG = "CFO_RISK_SCAN.v1"

# Fixed wording. No digits, no amounts: a number appears only through the cited engine result.
T_MARGIN = "Your contribution margin is lower than in the previous period."
T_STALE = "Your newest uploaded order data is older than expected, so recent results may be missing."
T_NO_DATA = "No order data has been uploaded yet, so no results can be calculated."
T_EXPENSES = "Some expenses are waiting for your confirmation, so operating profit is not final."
T_AD_CONFLICT = "Advertising appears both in an uploaded report and in a cost you entered by hand for the same dates; choose which one is right."
T_COST_CONFLICT = "A cost appears both in your Expense Tracker and in the expense ledger for the same dates; choose which one is right."
T_LEAK_CLOSING = "A discrepancy identified in your settlements is close to its claim deadline."


@dataclass(frozen=True, slots=True)
class Signal:
    rule: str
    kind: str  # LEAK_FOUND | MARGIN_ISSUE | DATA_GAP | (cash: not persisted)
    severity: str  # HIGH | MEDIUM | LOW
    scope: str
    text: str
    figure_refs: tuple[tuple[str, str], ...] = ()  # (engine_result_ref, label)
    persisted: bool = False


@dataclass
class ScanResult:
    as_of: date
    data_version: int
    signals: list[Signal] = field(default_factory=list)
    recorded: int = 0
    already_recorded: int = 0
    not_run: list[tuple[str, str]] = field(default_factory=list)  # (rule, why) — a rule that could not run says so


def _backend(requested_by: UUID) -> PostgresPlannerBackend:
    s = cfo_planner_settings()
    return PostgresPlannerBackend(
        requested_by=requested_by,
        codes=PlannerComponentCodes(s["fee_codes"], s["forward_logistics_codes"], s["reverse_logistics_codes"], s["non_refunded_fee_codes"]),  # type: ignore[arg-type]
        statement_timeout_ms=int(s["statement_timeout_ms"]), min_coverage=s["min_coverage"], cash_min_samples=int(s["cash_min_samples"]),  # type: ignore[arg-type, call-overload]
    )


def _month(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    nxt = (first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1))
    return first, nxt.fromordinal(nxt.toordinal() - 1)


def scan_periods(as_of: date) -> tuple[PeriodRef, PeriodRef]:
    """The last complete calendar month before `as_of`'s month, and the one before it."""
    cur_first, _ = _month(as_of)
    cur_end = cur_first.fromordinal(cur_first.toordinal() - 1)
    cs, ce = _month(cur_end)
    prev_end = cs.fromordinal(cs.toordinal() - 1)
    ps, pe = _month(prev_end)
    return PeriodRef(cs, ce, as_of), PeriodRef(ps, pe, as_of)


def run_scan(tenant_id: UUID, requested_by: UUID, as_of: date) -> ScanResult:
    if tenant_id is None:
        raise ValueError("a risk scan needs a tenant (fail closed)")
    s = cfo_planner_settings()
    be = _backend(requested_by)
    dv = rmv.get(tenant_id)
    out = ScanResult(as_of, dv)
    cur, prev = scan_periods(as_of)

    def key(rule: str, scope: str) -> str:
        return hashlib.sha256(f"cfo-risk|{rule}|{scope}|{dv}".encode()).hexdigest()

    def persist(sig: Signal, anchor: str) -> None:
        refs = [{"kind": "ENGINE_RESULT", "id": r, "label": lbl[:60]} for r, lbl in sig.figure_refs]
        if sig.kind not in ("LEAK_FOUND", "MARGIN_ISSUE", "DATA_GAP"):
            out.signals.append(sig)
            return
        try:
            got = findings.record(tenant_id, agent="CFO", kind=sig.kind, text=sig.text, source_ref={"kind": "metric_result", "id": anchor}, subject=f"{sig.rule}:{sig.scope}"[:120],
                                  figure_refs=refs, dedupe_key=key(sig.rule, sig.scope), created_by=requested_by)
        except findings.FindingError as exc:  # e.g. a cited result that does not resolve: the signal is reported as not recorded, the scan goes on
            out.not_run.append((sig.rule, f"could not be recorded: {exc}"))
            return
        out.signals.append(Signal(sig.rule, sig.kind, sig.severity, sig.scope, sig.text, sig.figure_refs, persisted=got is not None))
        out.recorded += 1 if got is not None else 0
        out.already_recorded += 0 if got is not None else 1

    # an anchor record for rules with no figure of their own: the age of the newest order document, as an engine result
    with tenant_scope(tenant_id) as conn:
        newest = conn.execute(text("SELECT max(coalesce(invoice_date, dispatch_date, order_date)) FROM sales_line WHERE tenant_id = :t"), {"t": str(tenant_id)}).scalar_one()
    age = data_age_days(newest, as_of)
    anchor_res = mint_set_based_result("DATA_AGE_DAYS", None, value_fraction=None if age is None else Fraction(age), unavailable_reason="no order data has been uploaded",
                                       data_version=dv, computed_at=datetime.now(timezone.utc), as_of_date=as_of, confidence="DERIVED")
    metric_result_repo.save(tenant_id, anchor_res, grain="TENANT_PERIOD", target_ref=str(tenant_id), period=as_of.isoformat(), config_version=_CONFIG)
    anchor = str(anchor_res.id)

    # R: stale or missing data
    stale = is_stale(age, int(s["stale_days"]))  # type: ignore[call-overload]
    if isinstance(stale, Unavailable):
        out.not_run.append(("STALE_DATA", stale.reason))
    elif stale:
        sig = Signal("STALE_DATA", "DATA_GAP", "MEDIUM" if age is not None else "HIGH", "ALL", T_STALE if age is not None else T_NO_DATA,
                     ((anchor, "Age of newest order data (days)"),) if age is not None else ())
        persist(sig, anchor)

    # R: margin drop between the last two complete months
    cur_m = be.run_engine_metrics(tenant_id, cur, Scope(cur.start, cur.end, None, None)).get("CONTRIBUTION_MARGIN_PCT")
    prev_m = be.run_engine_metrics(tenant_id, prev, Scope(prev.start, prev.end, None, None)).get("CONTRIBUTION_MARGIN_PCT")
    drop = margin_drop(prev_m.value_fraction if prev_m is not None and prev_m.available else None, cur_m.value_fraction if cur_m is not None and cur_m.available else None,
                       s["margin_drop_points"], s["margin_drop_high_points"])  # type: ignore[arg-type]
    if isinstance(drop, Unavailable):
        out.not_run.append(("MARGIN_DROP", drop.reason))
    elif isinstance(drop, MarginDrop):
        assert cur_m is not None and prev_m is not None and cur_m.engine_result_ref and prev_m.engine_result_ref
        persist(Signal("MARGIN_DROP", "MARGIN_ISSUE", drop.severity, f"{cur.start.isoformat()}", T_MARGIN,
                       ((cur_m.engine_result_ref, "Contribution margin, latest month"), (prev_m.engine_result_ref, "Contribution margin, month before"))), cur_m.engine_result_ref)

    # R: expenses waiting for confirmation (unclassified or held)
    op = be.run_operating_profit(tenant_id, cur, Scope(cur.start, cur.end, None, None))
    if op.available and op.exclusions and op.engine_result_ref:
        persist(Signal("EXPENSES_UNCONFIRMED", "DATA_GAP", "MEDIUM", cur.start.isoformat(), T_EXPENSES, ((op.engine_result_ref, "Operating profit (provisional)"),)), op.engine_result_ref)

    # R: advertising source conflict
    for c in cfo_costs.resolve_for(tenant_id, cat_marketplaces(), cur.start, cur.end).conflicts:
        if c.component == "ADVERTISING":
            persist(Signal("AD_SOURCE_CONFLICT", "DATA_GAP", "MEDIUM", c.marketplace, T_AD_CONFLICT), anchor)
        else:
            persist(Signal("COST_SOURCE_CONFLICT", "DATA_GAP", "MEDIUM", f"{c.component}:{c.marketplace}", T_COST_CONFLICT), anchor)

    # R: a discrepancy's claim window is closing (never for Amazon: withheld)
    with tenant_scope(tenant_id) as conn:
        closing = conn.execute(text("SELECT id, marketplace, engine_result_ref FROM leak_finding WHERE tenant_id = :t AND window_status = 'CLOSING_SOON' AND marketplace <> 'AMAZON'"),
                               {"t": str(tenant_id)}).all()
    for fid, mp, ref in closing:
        if leak_claim_repo.current_view(tenant_id, fid).state in ("SELLER_REPORTED_RAISED", "SELLER_REPORTED_RESOLVED", "DISMISSED"):
            continue
        persist(Signal("LEAK_WINDOW_CLOSING", "LEAK_FOUND", "HIGH", str(fid), T_LEAK_CLOSING, ((str(ref), "Discrepancy identified"),)), str(ref))

    # R: cash at risk — computed and returned, not persisted (no shared-finding kind exists for it)
    window = PeriodRef(prev.start, as_of, as_of)  # sold since the start of the month before last, up to today
    cv = be.run_cash_view(tenant_id, window, Scope(window.start, window.end, None, None))
    at_risk = [ln for ln in cv.shortfall if ln.label == "AT_RISK"]
    if at_risk:
        out.signals.append(Signal("CASH_AT_RISK", "CASH_RISK", "HIGH", "ALL", "Expected receipts may not cover a payable by its due date.", tuple((ln.ref, "Payable at risk") for ln in at_risk if ln.ref), persisted=False))
    return out


# ------------------------------------------------------------------------------------------------ after-change hook
def enabled() -> bool:
    return os.environ.get("CFO_RISK_SCAN_ON_CHANGE", "").strip().lower() in ("1", "true", "yes", "on")


def scan_in_background(tenant_id: UUID, requested_by: UUID | None = None, *, as_of: date | None = None) -> bool:
    """Called after an ingest or a ledger / payable / advertising change. Off unless `CFO_RISK_SCAN_ON_CHANGE` is set (the scan assembles two months of
    order lines; its cost on large books has not been measured). Runs on a daemon thread; a failure is logged and never reaches the write that triggered it."""
    if not enabled():
        return False

    def work() -> None:
        try:
            run_scan(tenant_id, requested_by or UUID(int=0), as_of or date.today())
        except Exception:  # noqa: BLE001
            logger.exception("risk scan failed for a tenant; the change that triggered it is unaffected")

    threading.Thread(target=work, name="cfo-risk-scan", daemon=True).start()
    return True
