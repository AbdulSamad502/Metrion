"""Executes a *validated* plan and builds the evidence packet (cfo-query-planner.md §6.1 steps 4-6, §6.3).

The executor never reads the database or the engine directly: it drives a `PlannerBackend` (the Postgres/engine adapter lives in the
backend package; tests use an in-memory one). It decides *what* to ask for from the plan and the catalog, never *how to compute* it:
set metrics go through the oracle-verified SQL path, engine metrics through Brain 1's own composition, the profit bridge through
`calc_engine.formulas.profit_bridge`. It never defaults: whatever cannot be measured becomes an `UNAVAILABLE` figure with its reason and
(once per reason) a data request.

Anything that was not built is said so, as an `UNAVAILABLE` figure ("not yet computable through the planner") — never silently omitted.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Protocol
from uuid import UUID

from calc_engine.formulas.profit_bridge import profit_bridge
from calc_engine.types import Unavailable
from cfo.planner import catalog as cat
from cfo.planner.evidence import BridgeDriverOut, BridgeOut, CoverageEntry, Drilldown, EvidencePacket, Figure, Stage, percent_text
from cfo.planner.plan import PeriodRef, QueryPlan, plan_hash
from cfo.planner.sql_executor import SQL_DIMENSIONS, SQL_METRICS, Grouping, Scope, SetResult, SetRow
from cfo.planner.validator import (
    CoverageDetail, DataStats, FigureProvenance, ValidationReport, ValidatorLimits, Violation, check_additivity, check_bridge, check_figures_have_refs,
    check_oracle_sample,
)

ENGINE_METRICS: frozenset[str] = frozenset(
    {"NET_REALIZED_REVENUE", "CONTRIBUTION_PROFIT", "CONTRIBUTION_MARGIN_PCT", "MARKETPLACE_FEES", "FEE_RATIO_PCT", "RETURN_RATE_PCT"}
)
SUPPORTED_FILTERS: frozenset[str] = frozenset({"marketplace", "sku"})
AD_METRICS: frozenset[str] = frozenset({"AD_SPEND", "ROAS", "ACOS", "TACOS"})
CASH_METRICS: frozenset[str] = frozenset({"EXPECTED_RECEIPTS", "CASH_SHORTFALL_STATUS"})


@dataclass(frozen=True, slots=True)
class ExecutorConfig:
    """Configuration, never defaults in code."""

    statement_timeout_ms: int
    oracle_sample_size: int
    max_ranking_groups: int


@dataclass(frozen=True, slots=True)
class EngineValue:
    metric_id: str
    available: bool
    value_paise: int | None = None
    value_fraction: Fraction | None = None
    confidence: str = "VERIFIED"
    engine_result_ref: str | None = None
    exclusions: tuple[tuple[str, int], ...] = ()
    missing_inputs: tuple[str, ...] = ()
    reason: str | None = None
    formula_version: str = "v1"
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpenseGroupView:
    category: str
    klass: str
    total_paise: int
    line_count: int
    ref: str | None


@dataclass(frozen=True, slots=True)
class ExpenseView:
    """The ledger's breakdown for a period as Brain 1 computed it (`expense_breakdown`): groups with their cited refs, what was held out, the total."""

    groups: tuple[ExpenseGroupView, ...]
    excluded: tuple[tuple[str, int, int], ...]  # (hold, total_paise, line_count)
    total_paise: int | None  # None = no entry at all (never zero)
    total_ref: str | None
    entries_counted: int


@dataclass(frozen=True, slots=True)
class CashLine:
    key: tuple[tuple[str, str], ...]
    value_paise: int
    count: int
    ref: str | None  # an estimate_ref (the figure is an estimate, never an engine result)
    label: str | None = None


@dataclass(frozen=True, slots=True)
class CashView:
    """The seller's cash picture on already-sold orders and entered payables, built from Brain 1's estimate and shortfall functions. Every receipt
    is an ESTIMATE; no bank balance is read. `unavailable_reason` set -> nothing could be projected (said so, with what is needed)."""

    receipts: tuple[CashLine, ...]  # future expected receipts by date
    total_receipts_paise: int | None
    total_ref: str | None
    overdue: CashLine | None  # expected before as_of and still unsettled: reported, never counted as cover
    shortfall: tuple[CashLine, ...]  # one per open payable; `label` is COVERED | AT_RISK | UNKNOWN
    not_projected: tuple[tuple[str, str], ...]  # (marketplace, why)
    excluded_no_amount: int
    excluded_unmatched: int
    unavailable_reason: str | None = None
    missing_inputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BridgeInputs:
    cp: EngineValue
    components: Mapping[str, int | None]  # BRIDGE_COMPONENTS codes -> paise magnitudes (costs positive); None = unavailable
    component_refs: Mapping[str, str | None]


class PlannerBackend(Protocol):
    def data_version(self, tenant_id: UUID) -> int: ...
    def collect_stats(self, tenant_id: UUID, plan: QueryPlan) -> DataStats: ...
    def run_set_metric(self, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, limit: int) -> SetResult: ...
    def reference_row(self, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, keys: tuple[tuple[str, str], ...]) -> SetRow | None: ...
    def mint_set_result(self, tenant_id: UUID, metric_id: str, scope: Scope, row: SetRow, data_version: int, period: PeriodRef) -> str: ...
    def run_engine_metrics(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> Mapping[str, EngineValue]: ...
    def run_bridge_inputs(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> BridgeInputs: ...
    def run_expense_breakdown(self, tenant_id: UUID, period: PeriodRef) -> ExpenseView: ...
    def run_operating_profit(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> EngineValue: ...
    def run_cash_view(self, tenant_id: UUID, period: PeriodRef, scope: Scope) -> CashView: ...
    def run_ad_metrics(self, tenant_id: UUID, period: PeriodRef, scope: Scope, by_marketplace: bool) -> Mapping[str | None, Mapping[str, EngineValue]]: ...
    def raise_data_request(self, tenant_id: UUID, metric_id: str, reason: str, missing_inputs: Sequence[str]) -> str: ...


class PlanFailed(Exception):
    """A post-execution check failed (V-DET-2, V-DET-3, V-ACC-2 numeric mismatch): reported, never retried silently."""

    def __init__(self, violations: Sequence[Violation]) -> None:
        self.violations = tuple(violations)
        super().__init__("; ".join(f"{v.rule_id}: {v.message}" for v in self.violations))


class DataChanged(Exception):
    """E5: the tenant's data_version moved while the plan ran."""


def _scope_for(plan: QueryPlan, period: PeriodRef) -> tuple[Scope, tuple[str, ...]]:
    markets: list[str] | None = None
    skus: list[str] | None = None
    unsupported: list[str] = []
    for f in plan.steps_of("filter"):
        dim, op, val = f.get("dimension"), f.get("op"), f.get("value")
        vals = list(val) if isinstance(val, tuple) else [val]
        if dim == "marketplace":
            markets = (markets or []) + vals if markets is not None else vals
        elif dim == "sku":
            skus = (skus or []) + vals if skus is not None else vals
        elif dim in ("expense_category", "expense_class"):
            continue  # applied to the ledger breakdown itself, never to sales lines
        else:
            unsupported.append(str(dim))
    return Scope(period.start, period.end, tuple(sorted(set(markets))) if markets is not None else None,
                 tuple(sorted(set(skus))) if skus is not None else None), tuple(unsupported)


def _grouping(plan: QueryPlan) -> Grouping:
    dims = plan.group_by_dimensions
    gran = None
    for s in plan.steps_of("group_by"):
        if s.get("period_granularity"):
            gran = s.get("period_granularity")
    if "period" in dims and gran is None:
        gran = "month"  # the validator already requires a legal value when given; "month" is the catalog's coarsest, stated in the spec (§5.2)
    return Grouping(tuple(dims), gran if "period" in dims else None)


def _unavailable(metric_id: str, period_index: int, reason: str, missing: Sequence[str] = (), keys: tuple[tuple[str, str], ...] = (),
                 labels: Sequence[str] = ()) -> Figure:
    return Figure(metric_id=metric_id, status="UNAVAILABLE", period_index=period_index, dimension_keys=keys, unavailable_reason=reason,
                  missing_inputs=tuple(missing), labels=tuple(labels), formula_version=cat.METRICS[metric_id].formula_version)


def _set_figure(metric_id: str, idx: int, row: SetRow, ref: str | None, labels: Sequence[str]) -> Figure:
    fv = cat.METRICS[metric_id].formula_version
    if row.value_paise is None:
        return Figure(metric_id=metric_id, status="UNAVAILABLE", period_index=idx, dimension_keys=row.keys, exclusions=row.excluded,
                      unavailable_reason="no measurable line in this scope", missing_inputs=("sales_lines",) if metric_id == "GROSS_SALES" else ("settlement_lines",),
                      labels=tuple(labels), formula_version=fv)
    status = "PARTIAL" if row.excluded else "VERIFIED"
    return Figure(metric_id=metric_id, status=status, period_index=idx, dimension_keys=row.keys, value_paise=row.value_paise, engine_result_ref=ref,
                  exclusions=row.excluded, labels=tuple(labels), formula_version=fv)


def _engine_figure(metric_id: str, idx: int, v: EngineValue, keys: tuple[tuple[str, str], ...], labels: Sequence[str]) -> Figure:
    fv = v.formula_version
    if not v.available:
        return Figure(metric_id=metric_id, status="UNAVAILABLE", period_index=idx, dimension_keys=keys, unavailable_reason=v.reason or "unavailable",
                      missing_inputs=v.missing_inputs, exclusions=v.exclusions, labels=tuple(sorted({*labels, *v.labels})), formula_version=fv)
    status = "PARTIAL" if v.exclusions and v.confidence == "VERIFIED" else v.confidence
    frac = None if v.value_fraction is None else f"{v.value_fraction.numerator}/{v.value_fraction.denominator}"
    return Figure(metric_id=metric_id, status=status, period_index=idx, dimension_keys=keys, value_paise=v.value_paise, value_fraction=frac,
                  engine_result_ref=v.engine_result_ref, exclusions=v.exclusions, labels=tuple(sorted({*labels, *v.labels})), formula_version=fv)


def _seeded_order(plan_digest: str, keys: Sequence[tuple[tuple[str, str], ...]]) -> list[tuple[tuple[str, str], ...]]:
    """Deterministic sample order seeded by the plan hash (V-DET-3): same plan -> same sample."""
    return sorted(keys, key=lambda k: hashlib.sha256((plan_digest + repr(k)).encode()).hexdigest())


def execute_plan(
    plan: QueryPlan,
    *,
    tenant_id: UUID,
    backend: PlannerBackend,
    report: ValidationReport,
    limits: ValidatorLimits,
    config: ExecutorConfig,
    on_stage: Callable[[str], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> EvidencePacket:
    """Runs the plan. Raises `PlanFailed` on a failed post-execution check and `DataChanged` if the data moved underneath (the caller
    reruns once, E5). Never raises for a merely-unavailable metric: that becomes an UNAVAILABLE figure."""
    import time

    now = clock or time.monotonic
    stages: list[Stage] = []

    def stage(name: str, t0: float) -> None:
        stages.append(Stage(name, int((now() - t0) * 1000)))

    digest = plan_hash(plan)
    dv_before = backend.data_version(tenant_id)
    if on_stage:
        on_stage("QUERYING")
    t0 = now()

    group = _grouping(plan)
    figures: list[Figure] = []
    labels: set[str] = set(report.labels)
    data_requests: dict[str, str] = {}  # reason -> id (de-duplicated, V-CMP-3)
    rows_examined = rows_excluded = 0
    truncated = False
    drilldown: list[Drilldown] = []
    bridge_out: BridgeOut | None = None
    oracle_violations: list[Violation] = []
    additivity_violations: list[Violation] = []

    def request(metric_id: str, reason: str, missing: Sequence[str]) -> None:
        key = f"{metric_id}|{reason}"
        if key not in data_requests:
            data_requests[key] = backend.raise_data_request(tenant_id, metric_id, reason, missing)

    rank_steps = plan.steps_of("rank")

    engine_runs: dict[tuple[object, ...], Mapping[str, EngineValue]] = {}
    excluded_cache: dict[tuple[int, str], tuple[int | None, int, str | None]] = {}
    coverage_entries: dict[tuple[str, int, str], CoverageEntry] = {}
    partial_by_metric = report.partial_metrics()

    def excluded_amount(idx: int, period: PeriodRef, marketplace: str, skus: tuple[str, ...] | None) -> tuple[int | None, int, str | None]:
        """What the excluded marketplace's lines add up to in gross sales (a measured volume, cited), so the seller sees what a partial total leaves out."""
        key = (idx, marketplace)
        if key not in excluded_cache:
            sc = Scope(period.start, period.end, (marketplace,), skus)
            row = backend.run_set_metric(tenant_id, "GROSS_SALES", sc, Grouping(), 1).consolidated
            ref = backend.mint_set_result(tenant_id, "GROSS_SALES", sc, row, dv_before, period) if row.value_paise is not None else None
            excluded_cache[key] = (row.value_paise, row.line_count + sum(c for _, c in row.excluded), ref)
        return excluded_cache[key]

    def coverage_entry(mid: str, idx: int, period: PeriodRef, d: CoverageDetail, skus: tuple[str, ...] | None) -> CoverageEntry:
        share = None if d.share is None else f"{d.share.numerator}/{d.share.denominator}"
        share_pct = None if d.share is None else percent_text(d.share.numerator, d.share.denominator)
        thr = None if d.threshold is None else f"{d.threshold.numerator}/{d.threshold.denominator}"
        thr_pct = None if d.threshold is None else percent_text(d.threshold.numerator, d.threshold.denominator)
        if d.ok or d.marketplace == "ALL":
            return CoverageEntry(mid, idx, d.marketplace, d.ok, d.input_id, share, share_pct, thr, thr_pct, d.reason)
        amount, count, ref = excluded_amount(idx, period, d.marketplace, skus)
        return CoverageEntry(mid, idx, d.marketplace, False, d.input_id, share, share_pct, thr, thr_pct, d.reason, amount, count,
                             "GROSS_SALES_OF_EXCLUDED_MARKETPLACE", ref)

    for idx, period in enumerate(plan.periods):
        base_scope, unsupported_filters = _scope_for(plan, period)

        def run_metric(mid: str, scope: Scope) -> None:
            nonlocal rows_examined, rows_excluded, truncated
            m = cat.METRICS[mid]
            if mid in report.unavailable_metrics:
                reason = report.unavailable_metrics[mid]
                figures.append(_unavailable(mid, idx, reason, m.required_inputs))
                request(mid, reason, m.required_inputs)
                return
            if unsupported_filters:
                reason = f"filtering by {sorted(set(unsupported_filters))} is not supported for this metric yet"
                figures.append(_unavailable(mid, idx, reason))
                return

            if mid in SQL_METRICS:
                bad = [d for d in group.dimensions if d not in SQL_DIMENSIONS[mid]]
                if bad or (mid == "SETTLEMENT_RECEIPTS" and scope.skus is not None):
                    figures.append(_unavailable(mid, idx, f"{mid} cannot be grouped or filtered by {sorted(set(bad) | ({'sku'} if scope.skus else set()))}"))
                    return
                fetch_limit = config.max_ranking_groups if rank_steps else plan.limit
                res = backend.run_set_metric(tenant_id, mid, scope, group, fetch_limit)
                rows_examined += res.consolidated.line_count + sum(c for _, c in res.consolidated.excluded)
                rows_excluded += sum(c for _, c in res.consolidated.excluded)
                rows = list(res.rows)
                if rank_steps:
                    r = rank_steps[0]
                    rows.sort(key=lambda x: (x.value_paise is None, x.value_paise if x.value_paise is not None else 0, x.keys),
                              reverse=False)
                    if r.get("direction") == "desc":
                        measured = sorted([x for x in rows if x.value_paise is not None], key=lambda x: (-x.value_paise, x.keys))  # type: ignore[operator]
                        rows = measured + [x for x in rows if x.value_paise is None]
                    top_n = r.get("top_n")
                    if isinstance(top_n, int) and top_n >= 1:
                        rows = rows[:top_n]
                    if res.truncated:
                        labels.add("RANKING_OVER_TRUNCATED_GROUPS")
                if res.truncated:
                    truncated = True
                dv_now = backend.data_version(tenant_id)
                if dv_now != dv_before:
                    raise DataChanged(f"data_version moved from {dv_before} to {dv_now} during execution")
                for row in rows:
                    ref = backend.mint_set_result(tenant_id, mid, scope, row, dv_before, period) if row.value_paise is not None else None
                    figures.append(_set_figure(mid, idx, row, ref, ()))
                cons_ref = backend.mint_set_result(tenant_id, mid, scope, res.consolidated, dv_before, period) if res.consolidated.value_paise is not None else None
                figures.append(_set_figure(mid, idx, res.consolidated, cons_ref, ("CONSOLIDATED",) if group.dimensions else ()))
                if group.dimensions:
                    drilldown.append(Drilldown(f"{digest[:16]}:{mid}:{idx}", f"{mid} by {', '.join(group.dimensions)}", len(rows)))
                # V-ACC-2: marketplaces add up to the consolidated figure (exactly), when that is the only split and nothing was cut off
                if group.dimensions == ("marketplace",) and not res.truncated:
                    parts = {dict(r.keys)["marketplace"]: r.value_paise for r in res.rows}
                    additivity_violations.extend(check_additivity(mid, parts, res.consolidated.value_paise))
                # V-DET-3: seeded oracle spot-check against the per-line reference
                keys = [r.keys for r in res.rows] or [()]
                for k in _seeded_order(digest, keys)[: config.oracle_sample_size]:
                    fast = res.consolidated if k == () else next(r for r in res.rows if r.keys == k)
                    ref_row = backend.reference_row(tenant_id, mid, scope, group, k)
                    oracle_violations.extend(check_oracle_sample(
                        {f"{mid}{k}": fast.value_paise, f"{mid}{k}#n": fast.line_count},
                        {f"{mid}{k}": None if ref_row is None else ref_row.value_paise, f"{mid}{k}#n": 0 if ref_row is None else ref_row.line_count}))
                return

            if mid in ENGINE_METRICS:
                if group.dimensions and group.dimensions != ("marketplace",):
                    figures.append(_unavailable(mid, idx, f"{mid} is available consolidated or by marketplace on the planner; grouping by {sorted(group.dimensions)} is not built yet"))
                    return
                run_key = (idx, scope.marketplaces, scope.skus)
                if run_key not in engine_runs:
                    engine_runs[run_key] = backend.run_engine_metrics(tenant_id, period, scope)
                v = engine_runs[run_key].get(mid)
                if v is None:
                    figures.append(_unavailable(mid, idx, "the engine did not produce this metric for the scope"))
                    return
                figures.append(_engine_figure(mid, idx, v, (), ()))
                if not v.available and v.missing_inputs:
                    request(mid, v.reason or "unavailable", v.missing_inputs)
                if group.dimensions == ("marketplace",):
                    parts_v: dict[str, int | None] = {}
                    for mk in (scope.marketplaces or cat.MARKETPLACES):
                        sub = backend.run_engine_metrics(tenant_id, period, Scope(period.start, period.end, (mk,), scope.skus)).get(mid)
                        if sub is None:
                            return
                        figures.append(_engine_figure(mid, idx, sub, (("marketplace", mk),), ()))
                        parts_v[mk] = sub.value_paise if sub.available else None
                    if m.additive and v.available:
                        labels.update({"CONSOLIDATED_EXCLUDES_UNAVAILABLE_MARKETPLACES"} if any(x is None for x in parts_v.values()) else set())
                        measured_parts = {k: x for k, x in parts_v.items() if x is not None}
                        additivity_violations.extend(vi for vi in check_additivity(mid, measured_parts, v.value_paise)
                                                     if vi.severity.value == "ERROR" and not any(x is None for x in parts_v.values()))
                return

            if mid == "EXPENSE_BY_CATEGORY":
                extra_dims = set(group.dimensions) - {"expense_category", "expense_class"}
                if extra_dims:
                    figures.append(_unavailable(mid, idx, f"{mid} is shown by category and class; grouping by {sorted(extra_dims)} is not built yet"))
                    return
                view = backend.run_expense_breakdown(tenant_id, period)
                want_class = {str(f.get("value")) for f in plan.steps_of("filter") if f.get("dimension") == "expense_class"}
                want_cat = {str(f.get("value")).casefold() for f in plan.steps_of("filter") if f.get("dimension") == "expense_category"}
                if view.total_paise is None:
                    reason = "no expense entries are recorded for this period"
                    figures.append(_unavailable(mid, idx, reason, ("expense_entries",)))
                    request(mid, reason, ("expense_entries",))
                    return
                rows_examined += view.entries_counted
                for g in view.groups:
                    if (want_class and g.klass not in want_class) or (want_cat and g.category.casefold() not in want_cat):
                        continue
                    lbl = ("UNCLASSIFIED",) if g.klass == "OTHER_UNCLASSIFIED" else ()
                    figures.append(Figure(metric_id=mid, status="VERIFIED", period_index=idx, dimension_keys=(("expense_category", g.category), ("expense_class", g.klass)),
                                          value_paise=g.total_paise, engine_result_ref=g.ref, labels=lbl, formula_version=m.formula_version))
                excl = tuple((f"HELD_{h}", n) for h, _t, n in view.excluded)
                rows_excluded += sum(n for _h, _t, n in view.excluded)
                if not want_class and not want_cat:
                    figures.append(Figure(metric_id=mid, status="PARTIAL" if excl else "VERIFIED", period_index=idx, value_paise=view.total_paise,
                                          engine_result_ref=view.total_ref, exclusions=excl, labels=("CONSOLIDATED",), formula_version=m.formula_version))
                if excl:
                    labels.add("EXPENSES_ON_HOLD")
                return

            if mid in CASH_METRICS:
                if group.dimensions or scope.skus is not None:
                    figures.append(_unavailable(mid, idx, "the cash view is an account-level picture; it is not split or narrowed by " + (", ".join(sorted(group.dimensions)) or "SKU")))
                    return
                cv = backend.run_cash_view(tenant_id, period, scope)
                if cv.unavailable_reason:
                    figures.append(_unavailable(mid, idx, cv.unavailable_reason, cv.missing_inputs, labels=("ESTIMATE_NOT_AVAILABLE",)))
                    request(mid, cv.unavailable_reason, cv.missing_inputs)
                    return
                excl = tuple([*((f"NOT_PROJECTED_{m}", 1) for m, _w in cv.not_projected), *((("NO_EXPECTED_AMOUNT", cv.excluded_no_amount),) if cv.excluded_no_amount else ()),
                              *((("NO_MATCH_KEY", cv.excluded_unmatched),) if cv.excluded_unmatched else ())])
                if cv.not_projected:
                    labels.add("PARTIAL_PROJECTION")
                if mid == "EXPECTED_RECEIPTS":
                    for ln in cv.receipts:
                        figures.append(Figure(metric_id=mid, status="ESTIMATED", period_index=idx, dimension_keys=ln.key, value_paise=ln.value_paise, value_count=ln.count,
                                              estimate_ref=ln.ref, labels=("ESTIMATE",), formula_version=m.formula_version))
                    if cv.overdue is not None:
                        figures.append(Figure(metric_id=mid, status="ESTIMATED", period_index=idx, dimension_keys=cv.overdue.key, value_paise=cv.overdue.value_paise,
                                              value_count=cv.overdue.count, estimate_ref=cv.overdue.ref, labels=("ESTIMATE", "OVERDUE_NOT_COUNTED_AS_COVER"), formula_version=m.formula_version))
                    if cv.total_receipts_paise is not None:
                        figures.append(Figure(metric_id=mid, status="ESTIMATED", period_index=idx, value_paise=cv.total_receipts_paise, estimate_ref=cv.total_ref,
                                              exclusions=excl, labels=("ESTIMATE", "CONSOLIDATED"), formula_version=m.formula_version))
                    return
                if not cv.shortfall:
                    reason = "no open payable has been entered, so there is nothing to compare expected receipts with"
                    figures.append(_unavailable(mid, idx, reason, ("payables",)))
                    request(mid, reason, ("payables",))
                    return
                for ln in cv.shortfall:
                    figures.append(Figure(metric_id=mid, status="ESTIMATED", period_index=idx, dimension_keys=ln.key, value_paise=ln.value_paise, estimate_ref=ln.ref,
                                          labels=("ESTIMATE", f"SHORTFALL_{ln.label}"), exclusions=excl, formula_version=m.formula_version))
                return

            if mid in AD_METRICS:
                if group.dimensions and group.dimensions != ("marketplace",):
                    figures.append(_unavailable(mid, idx, f"{mid} is available consolidated or by marketplace; grouping by {sorted(group.dimensions)} is not built yet"))
                    return
                if scope.skus is not None:
                    figures.append(_unavailable(mid, idx, "advertising cannot be narrowed to a SKU: a report's SKU attribution may be absent"))
                    return
                ad_runs = backend.run_ad_metrics(tenant_id, period, scope, bool(group.dimensions))
                for mkey, vals in ad_runs.items():
                    v = vals.get(mid)
                    if v is None:
                        continue
                    figures.append(_engine_figure(mid, idx, v, () if mkey is None else (("marketplace", mkey),), ()))
                    if not v.available and v.missing_inputs:
                        request(mid, v.reason or "unavailable", v.missing_inputs)
                return

            if mid == "OPERATING_PROFIT":
                if group.dimensions:
                    figures.append(_unavailable(mid, idx, "operating profit is an account-level figure; it cannot be split by " + ", ".join(sorted(group.dimensions)) + " because overhead is not attributed to a marketplace"))
                    return
                if scope.marketplaces is not None or scope.skus is not None:
                    figures.append(_unavailable(mid, idx, "operating profit is account-level: seller overhead cannot be attributed to a marketplace or SKU without an allocation"))
                    return
                ov = backend.run_operating_profit(tenant_id, period, scope)
                figures.append(_engine_figure(mid, idx, ov, (), ()))
                if not ov.available and ov.missing_inputs:
                    request(mid, ov.reason or "unavailable", ov.missing_inputs)
                return

            if mid == "PROFIT_BRIDGE":
                return  # handled once below, across the two periods

            reason = f"{mid} is defined in the catalog but not yet computable through the planner (its data source or path is not built)"
            figures.append(_unavailable(mid, idx, reason, m.required_inputs))
            request(mid, reason, m.required_inputs)


        for mid in plan.metric_ids:
            if mid == "PROFIT_BRIDGE":
                run_metric(mid, base_scope)
                continue
            start = len(figures)
            details = report.coverage.get(mid, ())
            partial = partial_by_metric.get(mid)
            scope_m = base_scope
            if partial is not None:
                good = set(partial[0]) & set(base_scope.marketplaces or partial[0])
                scope_m = Scope(period.start, period.end, tuple(sorted(good)), base_scope.skus)
            if mid == "OPERATING_PROFIT" and partial is not None:
                # overhead is account-wide: subtracting all of it from a Contribution Profit that leaves a marketplace out would be a wrong number
                why = "operating profit needs Contribution Profit for every marketplace; " + "; ".join(f"{d.marketplace}: {d.reason}" for d in partial[1])
                figures.append(_unavailable(mid, idx, why, tuple(sorted({d.input_id for d in partial[1] if d.input_id}))))
                request(mid, why, tuple(sorted({d.input_id for d in partial[1] if d.input_id})))
            else:
                run_metric(mid, scope_m)
            for d in details:
                coverage_entries[(mid, idx, d.marketplace)] = coverage_entry(mid, idx, period, d, base_scope.skus)
            if partial is not None and mid != "OPERATING_PROFIT":
                labels.add("PARTIAL_MARKETPLACE_COVERAGE")
                for i in range(start, len(figures)):
                    f = figures[i]
                    if len(f.dimension_keys) == 1 and f.dimension_keys[0][0] == "marketplace":
                        continue  # a marketplace's own row is complete for that marketplace
                    figures[i] = replace(f, labels=tuple(sorted({*f.labels, "PARTIAL_MARKETPLACE_COVERAGE"})),
                                         status="PARTIAL" if f.status == "VERIFIED" else f.status)
                for d in partial[1]:
                    figures.append(_unavailable(mid, idx, d.reason or "unavailable", (d.input_id,) if d.input_id else (),
                                                keys=(("marketplace", d.marketplace),), labels=("EXCLUDED_BY_COVERAGE",)))
                    request(mid, f"{d.marketplace}: {d.reason}", (d.input_id,) if d.input_id else ())

    # ---- the profit bridge: across exactly two periods, from Brain 1's component figures ----------------------------------
    if "PROFIT_BRIDGE" in plan.metric_ids:
        if len(plan.periods) != 2:
            figures.append(_unavailable("PROFIT_BRIDGE", 0, "a profit bridge needs exactly two periods"))
        else:
            sa, _ = _scope_for(plan, plan.periods[0])
            sb, _ = _scope_for(plan, plan.periods[1])
            a = backend.run_bridge_inputs(tenant_id, plan.periods[0], sa)
            b = backend.run_bridge_inputs(tenant_id, plan.periods[1], sb)
            comp_a = dict(a.components)
            comp_b = dict(b.components)
            comp_a["NET_REALIZED_REVENUE"] = comp_a.get("NET_REALIZED_REVENUE")
            br = profit_bridge(cp_a=a.cp.value_paise if a.cp.available else None, cp_b=b.cp.value_paise if b.cp.available else None,
                               components_a=comp_a, components_b=comp_b)
            if isinstance(br, Unavailable):
                figures.append(_unavailable("PROFIT_BRIDGE", 1, br.reason, br.missing_inputs))
                request("PROFIT_BRIDGE", br.reason, br.missing_inputs)
            else:
                bridge_out = BridgeOut(
                    from_period=0, to_period=1, delta_paise=br.delta_paise,
                    drivers=tuple(BridgeDriverOut(d.component_code, d.effect_paise, b.component_refs.get(d.component_code)) for d in br.drivers),
                    other_paise=br.other_paise, other_ref=b.cp.engine_result_ref, reconciles=br.reconciles)
                oracle_violations.extend(v for v in check_bridge(br.delta_paise, br.other_paise, limits) if v.severity.value == "ERROR")
                labels.update(v.subject for v in check_bridge(br.delta_paise, br.other_paise, limits) if v.severity.value == "WARN" and v.subject)
                figures.append(Figure(metric_id="PROFIT_BRIDGE", status="DERIVED", period_index=1, value_paise=br.delta_paise,
                                      engine_result_ref=b.cp.engine_result_ref, formula_version=cat.METRICS["PROFIT_BRIDGE"].formula_version))
    stage("QUERYING", t0)

    # ---- post-execution checks (§6.2 V-DET-2, V-DET-3, V-ACC-2) -----------------------------------------------------------
    if on_stage:
        on_stage("FINALIZING")
    t1 = now()
    provenance = [FigureProvenance(f.metric_id, f.status, f.engine_result_ref, f.estimate_ref) for f in figures]
    failures = [*check_figures_have_refs(provenance), *oracle_violations, *additivity_violations]
    failures = [v for v in failures if v.severity.value == "ERROR"]
    if failures:
        raise PlanFailed(failures)
    if backend.data_version(tenant_id) != dv_before:
        raise DataChanged("data_version moved before the packet was assembled")
    stage("FINALIZING", t1)

    return EvidencePacket(
        plan_hash=digest, catalog_version=cat.CATALOG_VERSION, data_version=dv_before, as_of_date=max(p.as_of_date for p in plan.periods),
        figures=tuple(figures), bridge=bridge_out, rows_examined=rows_examined, rows_excluded=rows_excluded, truncated=truncated,
        labels=tuple(sorted(labels)), drilldown=tuple(drilldown[:20]), data_requests=tuple(sorted(data_requests.values())), stages=tuple(stages),
        coverage=tuple(coverage_entries[k] for k in sorted(coverage_entries)),
    )
