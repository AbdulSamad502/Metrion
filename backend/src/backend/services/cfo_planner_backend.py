"""The Postgres + Brain 1 adapter behind the CFO query planner (cfo-query-planner.md §6.3).

Set metrics (`GROSS_SALES`, `SETTLEMENT_RECEIPTS`) run through the oracle-verified SQL path (`cfo.planner.sql_executor`); everything else runs
through the *same* composition the P&L routes use (`assemble_canonical_lines_for_period` -> `compute_period_pnl`), so the planner and the
dashboard read identical engine results. This module decides nothing about money: it assembles inputs, calls Brain 1 and carries results.

Coverage figures handed to the validator (V-CMP-1) are *measured* from the same assembly the engine uses, never assumed. Inputs this adapter
cannot measure are simply left out of the stats, which makes the metrics that need them `UNAVAILABLE` ("coverage was not measured").
"""

from __future__ import annotations

import calendar
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from fractions import Fraction
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.api.compute_metric import MetricResult, compute_marketplace_fees, mint_set_based_result
from calc_engine.formulas.expense_pools import parse_expense_pool_adjustment
from calc_engine.formulas.expense_accounting import ExpenseHold, OperatingProfit, OperatingProfitStatus, expense_breakdown, operating_profit
from calc_engine.formulas.ad_spend import AdSpendStatus, ad_ratios, consolidate_ads
from calc_engine.formulas.cash_forecast import Payable, UnsettledLine, cash_shortfall_status, expected_receipts, lower_median
from calc_engine.formulas.settlement_realization import estimate_settlement, observed_lag_days, realization_ratio
from calc_engine.repositories import cash_repo, ad_report_repo, expense_ledger_repo, manual_adjustment_repo, metric_result_repo, read_model_version_repo
from calc_engine.types import Paise, RecognitionState, Unavailable, sum_paise
from cfo.pnl import inputs as pnl_inputs
from cfo.planner import catalog as cat
from cfo.planner.executor import BridgeInputs, CashLine, CashView, EngineValue, ExpenseGroupView, ExpenseView
from cfo.planner.plan import PeriodRef, QueryPlan
from cfo.planner.sql_executor import Grouping, Scope, SetResult, SetRow, execute_set_metric, reference_set_metric
from cfo.planner.validator import DataStats
from cfo.repositories.tenant_context import tenant_scope

from backend.services import cfo_actions, cfo_ads, cfo_costs

_CONFIG_VERSION = "CFO_PLANNER.v1"
_POOL_CATEGORIES_ADS = "advertising"
_CP_FAMILY = frozenset({"CONTRIBUTION_PROFIT", "CONTRIBUTION_MARGIN_PCT"})


def cat_marketplaces() -> tuple[str, ...]:
    return tuple(sorted(cat.MARKETPLACES))


@dataclass(frozen=True, slots=True)
class PlannerComponentCodes:
    fee: frozenset[str]
    forward_logistics: frozenset[str]
    reverse_logistics: frozenset[str]
    non_refunded_fee: frozenset[str]


def _ev(metric_id: str, r: MetricResult) -> EngineValue:
    excl = Counter(str(e.get("rule", "EXCLUDED")) for e in r.exclusions)
    if not r.is_available:
        return EngineValue(metric_id, False, reason=r.unavailable_reason, exclusions=tuple(sorted(excl.items())), formula_version=r.formula_version,
                           missing_inputs=_missing_from(r))
    return EngineValue(metric_id, True, value_paise=r.value_paise, value_fraction=r.value_fraction, confidence=str(r.confidence),
                       engine_result_ref=str(r.id), exclusions=tuple(sorted(excl.items())), formula_version=r.formula_version)


def _missing_from(r: MetricResult) -> tuple[str, ...]:
    reason = (r.unavailable_reason or "").lower()
    return tuple(m for m in ("cogs_per_unit", "rto_outcome", "cancellation_state", "return_status", "rto_status", "refunded_amount") if m in reason)


class PostgresPlannerBackend:
    def __init__(self, *, requested_by: UUID, codes: PlannerComponentCodes, statement_timeout_ms: int, min_coverage: Fraction, cash_min_samples: int | None = None) -> None:
        self._cash_min_samples = cash_min_samples
        self._requested_by = requested_by
        self._codes = codes
        self._timeout = statement_timeout_ms
        self._min_coverage = min_coverage
        self._assemblies: dict[tuple[date, date], cfo_actions.CanonicalAssemblyOutcome] = {}
        self._pnl: dict[tuple[Any, ...], tuple[Mapping[str, EngineValue], Any]] = {}

    # ------------------------------------------------------------------------------------------ versions & stats
    def data_version(self, tenant_id: UUID) -> int:
        return read_model_version_repo.get(tenant_id)

    def _assembly(self, tenant_id: UUID, period: PeriodRef) -> cfo_actions.CanonicalAssemblyOutcome:
        key = (period.start, period.end)
        if key not in self._assemblies:
            self._assemblies[key] = cfo_actions.assemble_canonical_lines_for_period(tenant_id, period_start=period.start, period_end=period.end)
        return self._assemblies[key]

    def collect_stats(self, tenant_id: UUID, plan: QueryPlan) -> DataStats:
        """Measured, never assumed: coverage is computed per marketplace (the weakest period wins) from the same data the engine reads."""
        needed = {i for mid in plan.metric_ids for i in cat.METRICS[mid].required_inputs}
        by_mp: dict[str, dict[str, Fraction]] = {}
        overall: dict[str, Fraction] = {}
        rows_est = 0
        coverage_end: dict[str, date] = {}
        for period in plan.periods:
            per_mp, n = self._period_coverage(tenant_id, period, needed)
            rows_est += n
            for mp, cov in per_mp.items():
                tgt = by_mp.setdefault(mp, {})
                for k, v in cov.items():
                    tgt[k] = v if k not in tgt else min(tgt[k], v)
        for mp_cov in by_mp.values():
            for k, v in mp_cov.items():
                overall[k] = v if k not in overall else min(overall[k], v)
        with tenant_scope(tenant_id) as conn:
            for mk, end in conn.execute(text(
                    "SELECT marketplace, max(coalesce(invoice_date, dispatch_date, order_date)) FROM sales_line WHERE tenant_id = :t GROUP BY marketplace"),
                    {"t": str(tenant_id)}):
                if end is not None:
                    coverage_end[mk] = end
        if not by_mp and "sales_lines" in needed:
            overall["sales_lines"] = Fraction(0)  # nothing at all in scope: reported, never defaulted
        groups = 1
        dims = plan.group_by_dimensions
        if "marketplace" in dims:
            groups *= len(cat.MARKETPLACES)
        if "sku" in dims:
            with tenant_scope(tenant_id) as conn:
                groups *= max(1, int(conn.execute(text("SELECT count(DISTINCT sku) FROM sales_line WHERE tenant_id = :t"), {"t": str(tenant_id)}).scalar_one()))
        if "period" in dims:
            span = max((p.end - p.start).days + 1 for p in plan.periods)
            groups *= span  # worst case: daily buckets
        return DataStats(input_coverage=overall, coverage_by_marketplace=by_mp, estimated_rows=rows_est, estimated_groups=groups, data_coverage_end=coverage_end)

    def _period_coverage(self, tenant_id: UUID, period: PeriodRef, needed: set[str]) -> tuple[dict[str, dict[str, Fraction]], int]:
        """Per marketplace with lines in the period: input -> share of that marketplace's lines carrying it. The denominator is every sales line the
        marketplace has in the period (including ones the engine cannot assemble), so blocked lines lower coverage instead of vanishing from it."""
        out: dict[str, dict[str, Fraction]] = {}
        with tenant_scope(tenant_id) as conn:
            for mp, total, valid in conn.execute(text(
                    "SELECT marketplace, count(*), count(*) FILTER (WHERE quantity IS NOT NULL AND gross_item_amount IS NOT NULL) FROM sales_line "
                    "WHERE tenant_id = :t AND coalesce(invoice_date, dispatch_date, order_date) BETWEEN :s AND :e GROUP BY marketplace"),
                    {"t": str(tenant_id), "s": period.start, "e": period.end}):
                out[mp] = {"sales_lines": Fraction(int(valid), int(total)), "__total": Fraction(int(total))}
            settle: dict[str, Fraction] = {}
            if "settlement_lines" in needed:
                for mp, st, sv in conn.execute(text(
                        "SELECT marketplace, count(*), count(*) FILTER (WHERE gross_settlement_amount IS NOT NULL) FROM settlement_line "
                        "WHERE tenant_id = :t AND settlement_date BETWEEN :s AND :e GROUP BY marketplace"),
                        {"t": str(tenant_id), "s": period.start, "e": period.end}):
                    settle[mp] = Fraction(int(sv), int(st))
        if "settlement_history" in needed:  # cash views learn from every settlement the marketplace has already paid, whatever the plan's period
            with tenant_scope(tenant_id) as conn:
                settle_hist = {mp: (int(n), int(ok)) for mp, n, ok in conn.execute(text(
                    "SELECT marketplace, count(*), count(*) FILTER (WHERE gross_settlement_amount IS NOT NULL AND settlement_date IS NOT NULL) FROM settlement_line "
                    "WHERE tenant_id = :t AND (settlement_date IS NULL OR settlement_date <= :asof) GROUP BY marketplace"), {"t": str(tenant_id), "asof": period.as_of_date})}
            for mp in out:
                n, ok = settle_hist.get(mp, (0, 0))
                out[mp]["settlement_history"] = Fraction(ok, n) if n else Fraction(0)
        total_rows = sum(int(v["__total"]) for v in out.values())
        if "settlement_lines" in needed:
            for mp in set(out) | set(settle):
                out.setdefault(mp, {})["settlement_lines"] = settle.get(mp, Fraction(0))
        engine_owned = {"cancellation_state", "return_status", "rto_status", "rto_outcome", "cogs_per_unit", "fee_components"}
        if needed & engine_owned:
            a = self._assembly(tenant_id, period)
            hist = cfo_actions.resolve_cost_history_for_skus(tenant_id, set(a.sku_by_line.values()))
            for mp, cov in out.items():
                denom = int(cov["__total"]) if "__total" in cov else 0
                mine = [ln for ln in a.lines if ln.marketplace == mp]
                if not denom:
                    for k in needed & engine_owned:
                        cov[k] = Fraction(0)
                    continue
                cov["cancellation_state"] = Fraction(sum(1 for ln in mine if ln.cancellation_state is not None), denom)
                cov["return_status"] = Fraction(sum(1 for ln in mine if ln.return_status is not None), denom)
                cov["rto_status"] = Fraction(sum(1 for ln in mine if ln.rto_status is not None), denom)
                rto_lines = [ln for ln in mine if ln.rto_status == "RTO"]
                cov["rto_outcome"] = Fraction(sum(1 for ln in rto_lines if ln.rto_outcome is not None), len(rto_lines)) if rto_lines else Fraction(1)
                cov["cogs_per_unit"] = Fraction(sum(1 for ln in mine if hist.get(a.sku_by_line.get(str(ln.sales_line_id), "")) ), denom)
                cov["fee_components"] = Fraction(sum(1 for ln in mine if any(c.component_kind == "FEE" for c in ln.components)), denom)
        if "ad_source" in needed:
            sources = cfo_costs.load_sources(tenant_id, list(out), period.start, period.end)
            for mp, cov in out.items():
                item = cfo_ads.evaluate_marketplace(tenant_id, mp, period.start, period.end, net_revenue_paise=None, sources=sources)
                cov['ad_source'] = Fraction(0) if item.reason == cfo_ads.NO_EVIDENCE else Fraction(1)
        for cov in out.values():
            cov.pop("__total", None)
        return out, total_rows

    # ------------------------------------------------------------------------------------------ set metrics (SQL)
    def run_set_metric(self, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, limit: int) -> SetResult:
        return execute_set_metric(tenant_id, metric_id, scope, group, limit=limit, statement_timeout_ms=self._timeout)

    def reference_row(self, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, keys: tuple[tuple[str, str], ...]) -> SetRow | None:
        with tenant_scope(tenant_id) as conn:
            by_key, total = reference_set_metric(conn, tenant_id, metric_id, scope, group)
        return total if keys == () else by_key.get(keys)

    def mint_set_result(self, tenant_id: UUID, metric_id: str, scope: Scope, row: SetRow, data_version: int, period: PeriodRef) -> str:
        now = datetime.now(timezone.utc)
        res = mint_set_based_result(
            metric_id, row.value_paise, unavailable_reason=None if row.value_paise is not None else "no measurable line in this scope",
            exclusions=[{"rule": reason, "count": n} for reason, n in row.excluded], data_version=data_version, computed_at=now,
            as_of_date=period.as_of_date, confidence="PROVISIONAL" if row.excluded else "VERIFIED")
        scope_ref = ",".join(f"{k}={v}" for k, v in row.keys) or "ALL"
        metric_result_repo.save(tenant_id, res, grain="TENANT_PERIOD", target_ref=f"{tenant_id}|{scope_ref}",
                                period=f"{period.start.isoformat()}/{period.end.isoformat()}", config_version=_CONFIG_VERSION)
        return str(res.id)

    # ------------------------------------------------------------------------------------------ engine metrics
    def _lines_for(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> tuple[Any, tuple[Any, ...]]:
        a = self._assembly(tenant_id, period)
        lines = tuple(
            ln for ln in a.lines
            if (scope.marketplaces is None or ln.marketplace in scope.marketplaces)
            and (scope.skus is None or a.sku_by_line.get(str(ln.sales_line_id)) in scope.skus))
        return a, lines

    def run_engine_metrics(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> Mapping[str, EngineValue]:
        key = (period.start, period.end, scope.marketplaces, scope.skus)
        if key in self._pnl:
            return self._pnl[key][0]
        a, lines = self._lines_for(tenant_id, period, scope)
        if not lines:
            why = "no order line in this scope could be assembled for the period" if not a.blocked else f"{len(a.blocked)} line(s) are blocked pending seller input"
            empty = {m: EngineValue(m, False, reason=why, missing_inputs=("sales_lines",)) for m in
                     ("NET_REALIZED_REVENUE", "CONTRIBUTION_PROFIT", "CONTRIBUTION_MARGIN_PCT", "MARKETPLACE_FEES", "FEE_RATIO_PCT", "RETURN_RATE_PCT")}
            self._pnl[key] = (empty, None)
            return empty
        mps_in_scope = scope.marketplaces if scope.marketplaces is not None else cat_marketplaces()
        resolved = cfo_costs.resolve_for(tenant_id, tuple(mps_in_scope), period.start, period.end)  # one source per cost, or a named conflict: nothing counted twice
        ads = [dict(v) for v in resolved.advertising]
        other = [dict(v) for v in resolved.other]
        hand_entered = [i for i in resolved.counted if i.source in ("POOL", "LEDGER")]
        ads_report = [i for i in resolved.counted if i.source == "REPORT"]
        narrowed = scope.marketplaces is not None or scope.skus is not None
        now = datetime.now(timezone.utc)
        hist = cfo_actions.resolve_cost_history_for_skus(tenant_id, a.sku_by_line.values())
        pnl = cfo_actions.compute_period_pnl(tenant_id, cfo_actions.PeriodPnlRequest(
            lines=lines, period_start=period.start, period_end=period.end, as_of_date=period.as_of_date,
            recognition_state=RecognitionState.RECOGNISED, sku_by_line=a.sku_by_line, cost_history_by_sku=hist,
            fee_component_codes=self._codes.fee, forward_logistics_codes=self._codes.forward_logistics, reverse_logistics_codes=self._codes.reverse_logistics,
            non_refunded_fee_codes=self._codes.non_refunded_fee, advertising_adjustment_values=ads, other_adjustment_values=other,
            ingestion_run_ids=a.ingestion_run_ids, adapter_versions=(), active_adjustment_ids=a.active_adjustment_ids,
            requested_by=self._requested_by, computed_at=now))
        fees, _flags = pnl_inputs.resolve_marketplace_fees(lines, fee_component_codes=self._codes.fee)
        fees_result = compute_marketplace_fees(fees, computed_at=now, as_of_date=period.as_of_date)
        metric_result_repo.save(tenant_id, fees_result, grain="TENANT_PERIOD", target_ref=str(tenant_id),
                                period=f"{period.start.isoformat()}/{period.end.isoformat()}", config_version=_CONFIG_VERSION)
        vals: dict[str, EngineValue] = {
            "NET_REALIZED_REVENUE": _ev("NET_REALIZED_REVENUE", pnl.nrr), "MARKETPLACE_FEES": _ev("MARKETPLACE_FEES", fees_result),
            "FEE_RATIO_PCT": _ev("FEE_RATIO_PCT", pnl.fee_ratio_pct), "RETURN_RATE_PCT": _ev("RETURN_RATE_PCT", pnl.return_rate_pct),
            "CONTRIBUTION_PROFIT": _ev("CONTRIBUTION_PROFIT", pnl.contribution_profit), "CONTRIBUTION_MARGIN_PCT": _ev("CONTRIBUTION_MARGIN_PCT", pnl.margin_pct),
        }
        cp_labels = tuple(sorted(
            ({'ADVERTISING_FROM_REPORT'} if ads_report else set()) | ({'COSTS_FROM_LEDGER'} if any(i.source == 'LEDGER' for i in hand_entered) else set())
            | {(f'ADVERTISING_SOURCE_CONFLICT_{c.marketplace}' if c.component == 'ADVERTISING' else f'COST_SOURCE_CONFLICT_{c.component}_{c.marketplace}') for c in resolved.conflicts}))
        if cp_labels:
            for m in _CP_FAMILY:
                vals[m] = replace(vals[m], labels=cp_labels)
        if scope.skus is not None and ads_report:
            for m in _CP_FAMILY:
                vals[m] = EngineValue(m, False, reason='advertising comes from a report that may not attribute spend to a SKU, so a SKU-level profit would be wrong', missing_inputs=('ad_sku_attribution',))
        if narrowed and hand_entered:
            why = "seller-entered advertising/other cost pools are account-level; they cannot be attributed to one marketplace or SKU without an allocation"
            for m in _CP_FAMILY:
                vals[m] = EngineValue(m, False, reason=why, missing_inputs=("cost_pool_allocation",))
        self._pnl[key] = (vals, (a, lines, ads, other, hist))
        return vals

    def run_bridge_inputs(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> BridgeInputs:
        vals = self.run_engine_metrics(tenant_id, period, scope)
        ctx = self._pnl[(period.start, period.end, scope.marketplaces, scope.skus)][1]
        cp = vals["CONTRIBUTION_PROFIT"]
        if ctx is None:
            none: dict[str, int | None] = {c: None for c, _ in __import__("calc_engine.formulas.profit_bridge", fromlist=["BRIDGE_COMPONENTS"]).BRIDGE_COMPONENTS}
            return BridgeInputs(cp, none, {k: None for k in none})
        a, lines, ads, other, hist = ctx

        def m(v: Paise | Unavailable) -> int | None:
            return None if isinstance(v, Unavailable) else v.value

        nrr = vals["NET_REALIZED_REVENUE"]
        cogs = pnl_inputs.resolve_cogs(lines, sku_by_line=a.sku_by_line, cost_history_by_sku=hist, as_of=period.as_of_date)
        fees, _ = pnl_inputs.resolve_marketplace_fees(lines, fee_component_codes=self._codes.fee)
        rto = pnl_inputs.resolve_return_rto_losses(
            lines, sku_by_line=a.sku_by_line, cost_history_by_sku=hist, as_of=period.as_of_date,
            forward_logistics_codes=self._codes.forward_logistics, reverse_logistics_codes=self._codes.reverse_logistics,
            non_refunded_fee_codes=self._codes.non_refunded_fee)
        comps: dict[str, int | None] = {
            "NET_REALIZED_REVENUE": nrr.value_paise if nrr.available else None, "COGS": m(cogs), "MARKETPLACE_FEES": fees.value,
            "SHIPPING_LOGISTICS": pnl_inputs.resolve_shipping_logistics(lines).value,  # the same default the P&L composition uses, so the bridge reconciles
            "ADVERTISING_COSTS": pnl_inputs.resolve_expense_pool_total(ads).value, "RETURN_RTO_LOSSES": m(rto),
            "OTHER_ALLOCATED_COSTS": pnl_inputs.resolve_expense_pool_total(other).value,
        }
        return BridgeInputs(cp, comps, {k: cp.engine_result_ref for k in comps})

    def raise_data_request(self, tenant_id: UUID, metric_id: str, reason: str, missing_inputs: Sequence[str]) -> str:
        return str(cfo_actions.raise_data_request(tenant_id, requested_field=", ".join(missing_inputs) or "unspecified", reason=reason, blocking_metric=metric_id))

    # ------------------------------------------------------------------------------------------ the expense ledger (Phase 3a)
    def _mint(self, tenant_id: UUID, metric_id: str, value: int | None, period: PeriodRef, *, target: str, reason: str | None = None,
              exclusions: Sequence[dict[str, Any]] = (), confidence: str = "VERIFIED") -> str:
        res = mint_set_based_result(metric_id, value, unavailable_reason=reason, exclusions=exclusions, data_version=self.data_version(tenant_id),
                                    computed_at=datetime.now(timezone.utc), as_of_date=period.as_of_date, confidence=confidence)
        metric_result_repo.save(tenant_id, res, grain="TENANT_PERIOD", target_ref=f"{tenant_id}|{target}",
                                period=f"{period.start.isoformat()}/{period.end.isoformat()}", config_version=_CONFIG_VERSION)
        return str(res.id)

    def run_expense_breakdown(self, tenant_id: UUID, period: PeriodRef) -> ExpenseView:
        lines = expense_ledger_repo.lines_for_period(tenant_id, period.start, period.end)
        b = expense_breakdown(lines, period_start=period.start, period_end=period.end)
        in_scope = [ln for ln in lines if period.start <= ln.entry_date <= period.end]
        if not in_scope:
            return ExpenseView((), (), None, None, 0)
        groups = tuple(
            ExpenseGroupView(g.category, g.klass.value, g.total_paise, g.line_count,
                             self._mint(tenant_id, "EXPENSE_BY_CATEGORY", g.total_paise, period, target=f"expense|{g.category}|{g.klass.value}"))
            for g in b.groups)
        total = b.grouped_total_paise
        return ExpenseView(groups, tuple((e.hold.value, e.total_paise, e.line_count) for e in b.excluded), total,
                           self._mint(tenant_id, "EXPENSE_BY_CATEGORY", total, period, target="expense|ALL"), sum(g.line_count for g in b.groups))

    def run_operating_profit(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> EngineValue:
        cp = self.run_engine_metrics(tenant_id, period, scope)["CONTRIBUTION_PROFIT"]
        lines = expense_ledger_repo.lines_for_period(tenant_id, period.start, period.end)
        coverage = expense_ledger_repo.overhead_coverage(tenant_id, period.start, period.end)
        res = operating_profit(cp.value_paise if cp.available else None, lines, coverage, period_start=period.start, period_end=period.end)
        if isinstance(res, Unavailable):
            missing = res.missing_inputs
            return EngineValue("OPERATING_PROFIT", False, reason=res.reason, missing_inputs=tuple(missing), formula_version="OPERATING_PROFIT.v1")
        assert isinstance(res, OperatingProfit)
        counted = sum(1 for ln in lines if period.start <= ln.entry_date <= period.end and ln.hold is ExpenseHold.NONE)
        excl = tuple(e for e in (("UNCLASSIFIED_EXPENSE", res.unclassified.line_count), ("HELD_EXPENSE", res.held.line_count)) if e[1])
        provisional = res.status is OperatingProfitStatus.PROVISIONAL
        ref = self._mint(tenant_id, "OPERATING_PROFIT", res.value_paise, period, target="operating_profit",
                         exclusions=[{"rule": r, "count": n} for r, n in excl], confidence="PROVISIONAL" if provisional else "DERIVED")
        return EngineValue("OPERATING_PROFIT", True, value_paise=res.value_paise, confidence="PROVISIONAL" if provisional else "DERIVED", engine_result_ref=ref,
                           exclusions=excl, formula_version="OPERATING_PROFIT.v1", labels=(f"BASED_ON_{counted}_EXPENSE_ENTRIES",))

    # ------------------------------------------------------------------------------------------ advertising (Phase 3b)
    def run_ad_metrics(self, tenant_id: UUID, period: PeriodRef, scope: Scope, by_marketplace: bool) -> dict[str | None, dict[str, EngineValue]]:
        mps = scope.marketplaces if scope.marketplaces is not None else cat_marketplaces()
        sources = cfo_costs.load_sources(tenant_id, list(mps), period.start, period.end)
        items = []
        for mp in mps:
            nrr = self.run_engine_metrics(tenant_id, period, Scope(period.start, period.end, (mp,), None)).get("NET_REALIZED_REVENUE")
            items.append(cfo_ads.evaluate_marketplace(tenant_id, mp, period.start, period.end,
                                                      net_revenue_paise=nrr.value_paise if nrr is not None and nrr.available else None, sources=sources))
        # a marketplace with no data at all (no sales, no advertising evidence) is simply absent, not an "unknown" that would blur the total
        with tenant_scope(tenant_id) as conn:
            have_sales = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT marketplace FROM sales_line WHERE tenant_id = :t AND coalesce(invoice_date, dispatch_date, order_date) BETWEEN :s AND :e"),
                {"t": str(tenant_id), "s": period.start, "e": period.end})}
        items = [i for i in items if i.reason != cfo_ads.NO_EVIDENCE or i.marketplace in have_sales]
        out: dict[str | None, dict[str, EngineValue]] = {None: self._ad_values(tenant_id, period, items, "ALL")}
        if by_marketplace:
            for i in items:
                out[i.marketplace] = self._ad_values(tenant_id, period, [i], i.marketplace)
        return out

    def _ad_values(self, tenant_id: UUID, period: PeriodRef, items: list[Any], label: str) -> dict[str, EngineValue]:
        agg = consolidate_ads(items)
        labels = (f"AD_STATUS_{agg.status.value}",) + (("PARTIAL_AD_COVERAGE",) if agg.excluded else ())
        excl = tuple((f"EXCLUDED_{m}", 1) for m, _why in agg.excluded)
        why = "; ".join(f"{m}: {w}" for m, w in agg.excluded) or "no advertising information"
        if agg.spend_paise is None:
            miss = ("ad_source",)
            return {m: EngineValue(m, False, reason=why, missing_inputs=miss, labels=labels, exclusions=excl) for m in ("AD_SPEND", "ROAS", "ACOS", "TACOS")}
        ratios = ad_ratios(status=agg.status, spend_paise=agg.spend_paise, attributed_sales_paise=agg.attributed_sales_paise, total_sales_paise=agg.total_sales_paise)
        spend_ref = self._mint(tenant_id, "AD_SPEND", agg.spend_paise, period, target=f"ads|{label}", confidence="PROVISIONAL")
        out = {"AD_SPEND": EngineValue("AD_SPEND", True, value_paise=agg.spend_paise, confidence="PROVISIONAL", engine_result_ref=spend_ref, exclusions=excl,
                                        labels=labels, formula_version="AD_SPEND.v1")}
        for name, frac in (("ROAS", ratios.roas), ("ACOS", ratios.acos), ("TACOS", ratios.tacos)):
            if frac is None:
                out[name] = EngineValue(name, False, reason=ratios.unavailable.get(name.lower(), "not available"), missing_inputs=("ad_attributed_sales",) if name != "TACOS" else ("NET_REALIZED_REVENUE",),
                                        labels=labels, exclusions=excl)
                continue
            res = mint_set_based_result(name, None, value_fraction=frac, data_version=self.data_version(tenant_id), computed_at=datetime.now(timezone.utc),
                                        as_of_date=period.as_of_date, confidence="PROVISIONAL")
            metric_result_repo.save(tenant_id, res, grain="TENANT_PERIOD", target_ref=f"{tenant_id}|ads|{label}",
                                    period=f"{period.start.isoformat()}/{period.end.isoformat()}", config_version=_CONFIG_VERSION)
            out[name] = EngineValue(name, True, value_fraction=frac, confidence="PROVISIONAL", engine_result_ref=str(res.id), labels=labels, exclusions=excl,
                                    formula_version=f"{name}.v1")
        return out

    # ------------------------------------------------------------------------------------------ cash and payables (Phase 3c)
    def run_cash_view(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> CashView:
        """Expected receipts on already-sold lines (an ESTIMATE from what the marketplace has actually paid before) and each open payable's
        shortfall status. Only marketplaces whose order-to-settlement key is validated are projected; the rest are named, never guessed."""
        wanted = scope.marketplaces if scope.marketplaces is not None else cat_marketplaces()
        validated = {j.id.split("_")[0].upper() for j in cat.JOINS.values() if j.validated and j.id.endswith("_orders_to_settlement")}
        not_projected: list[tuple[str, str]] = [(m, "no order-to-settlement key has been validated against a real export for this marketplace") for m in wanted if m not in validated]
        lines: list[UnsettledLine] = []
        lags: dict[str, list[int]] = {}
        ratios: dict[str, Any] = {}
        unmatched = no_amount = 0
        for mp in (m for m in wanted if m in validated):
            pairs = cash_repo.settled_pairs(tenant_id, mp, period.as_of_date)
            ratio = realization_ratio([(p.gross_item_amount_paise, p.settled_amount_paise) for p in pairs], self._cash_min_samples)
            if isinstance(ratio, Unavailable):
                not_projected.append((mp, ratio.reason))
                continue
            lag = observed_lag_days([(p.document_date.toordinal(), p.settlement_date.toordinal()) for p in pairs])
            if len(lag) < (self._cash_min_samples or 1):
                not_projected.append((mp, f"{len(lag)} usable settlement lag(s) observed; at least {self._cash_min_samples} are needed"))
                continue
            ratios[mp], lags[mp] = ratio, lag
            sold, um = cash_repo.unsettled_lines(tenant_id, mp, period.start, period.end)
            unmatched += um
            for ln in sold:
                lines.append(UnsettledLine(ln.sales_line_id, mp, ln.document_date, estimate_settlement(ln.gross_item_amount_paise, ratio)))
        if not lines:
            why = "; ".join(f"{m}: {w}" for m, w in not_projected) or "no sold, unsettled order line in this period"
            return CashView((), None, None, None, (), tuple(not_projected), 0, unmatched, unavailable_reason="nothing could be projected: " + why,
                            missing_inputs=("settled_lines",) if not_projected else ("unsettled_lines",))
        er = expected_receipts(lines, lags, period.as_of_date, self._cash_min_samples)
        if isinstance(er, Unavailable):
            return CashView((), None, None, None, (), tuple(not_projected), 0, unmatched, unavailable_reason=er.reason, missing_inputs=tuple(er.missing_inputs))
        no_amount = er.excluded_no_amount

        def est(value: int, target: str) -> str:
            return self._mint(tenant_id, "EXPECTED_RECEIPTS", value, period, target=f"cash|{target}", confidence="DERIVED")

        receipts = tuple(CashLine((("expected_date", b.expected_date.isoformat()),), b.total_paise, b.line_count, est(b.total_paise, b.expected_date.isoformat())) for b in er.buckets)
        total = sum_paise([Paise(b.total_paise) for b in er.buckets]).value if er.buckets else None
        overdue = CashLine((("expected_date", "OVERDUE"),), er.overdue_total_paise, er.overdue_line_count, est(er.overdue_total_paise, "overdue")) if er.overdue_line_count else None
        payables = cash_repo.list_payables(tenant_id)
        statuses = cash_shortfall_status([Payable(p.payable_id, p.amount_paise, p.due_date) for p in payables], er)
        shortfall: tuple[CashLine, ...] = ()
        if not isinstance(statuses, Unavailable):
            amount = {p.payable_id: p.amount_paise for p in payables}
            shortfall = tuple(CashLine((("payable", s.payable_id),), amount[s.payable_id], 1, est(amount[s.payable_id], f"payable|{s.payable_id}"), s.status.value) for s in statuses)
        return CashView(receipts, total, None if total is None else est(total, "total"), overdue, shortfall, tuple(not_projected), no_amount, unmatched)
