"""Deterministic plan validator (cfo-query-planner.md §6.2).

Every rule is a pure function of `(plan, catalog, facts, limits)` with a stable rule id. An `ERROR`
blocks execution; a `WARN` attaches a label that must travel with the result. Facts about the data
(join cardinality, control totals, coverage ...) are supplied by the executor — this module never
touches a database, a clock or an LLM, and never does arithmetic on money: summing and ratios live in
`calc_engine` (`formulas.identities`), which the post-execution checks call.

Fail closed: a fact the validator needs but was not given is a violation, never an assumption.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from fractions import Fraction

from calc_engine.formulas.identities import check_additive, unexplained_share

from cfo.planner import catalog as cat
from cfo.planner.plan import QueryPlan, Step

_STEP_ORDER = {"filter": 0, "normalize": 0, "join": 1, "group_by": 2, "aggregate": 3, "metric": 3, "compare": 4, "rank": 5}


class Severity(str, Enum):
    ERROR = "ERROR"
    WARN = "WARN"


@dataclass(frozen=True, slots=True)
class Violation:
    rule_id: str
    severity: Severity
    message: str
    subject: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatorLimits:
    """Configuration, never constants in code (CLAUDE.md): the caller supplies every value. There are
    deliberately no defaults — a missing threshold is a configuration gap, not something to guess."""

    max_rows_scanned: int
    max_groups: int
    max_limit: int
    min_coverage: Mapping[str, Fraction]  # required input id -> minimum share of lines carrying it
    low_explainability_share: Fraction  # |OTHER| / |delta| above this -> LOW_EXPLAINABILITY label


@dataclass(frozen=True, slots=True)
class JoinFacts:
    unique_side_rows: int
    unique_side_distinct_keys: int
    control_total_before: int
    control_total_after: int
    many_side_preaggregated: bool
    settlement_lines_matching_multiple_orders: int = 0
    orders_matching_multiple_settlement_lines: int = 0  # legitimate for ONE_TO_MANY; disclosed only
    unmatched_left_rows: int = 0
    unmatched_right_rows: int = 0
    declared_many_to_one_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DataStats:
    joins: Mapping[str, JoinFacts] = field(default_factory=dict)
    input_coverage: Mapping[str, Fraction] = field(default_factory=dict)  # input id -> share of lines carrying it
    natural_key_rows: Mapping[str, tuple[int, int]] = field(default_factory=dict)  # source -> (rows, distinct natural keys)
    cost_owners: Mapping[tuple[str, str], frozenset[str]] = field(default_factory=dict)  # (component, scope) -> active owners
    unconfirmed_overlap_expenses: int = 0
    estimated_rows: int = 0
    estimated_groups: int = 0
    data_coverage_end: Mapping[str, date] = field(default_factory=dict)  # marketplace -> last date with data


@dataclass(frozen=True, slots=True)
class ValidationReport:
    violations: tuple[Violation, ...]
    unavailable_metrics: Mapping[str, str]  # metric id -> reason (V-CMP-1); the executor returns UNAVAILABLE + a data request

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.WARN)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def labels(self) -> frozenset[str]:
        return frozenset(v.subject for v in self.warnings if v.subject)

    def rule_ids(self) -> frozenset[str]:
        return frozenset(v.rule_id for v in self.violations)


def _e(rule: str, msg: str, subject: str | None = None) -> Violation:
    return Violation(rule, Severity.ERROR, msg, subject)


def _w(rule: str, msg: str, label: str) -> Violation:
    return Violation(rule, Severity.WARN, msg, label)


def _is_str_or_strs(v: object) -> bool:
    return isinstance(v, str) or (isinstance(v, tuple) and bool(v) and all(isinstance(x, str) for x in v))


# --------------------------------------------------------------------------------------- static rules
def _check_steps(plan: QueryPlan) -> list[Violation]:
    out: list[Violation] = []
    if plan.intent not in cat.PLAN_INTENTS:
        out.append(_e("V-SCH-1", f"unknown intent {plan.intent!r}", plan.intent))

    last = -1
    for s in plan.steps:
        order = _STEP_ORDER[s.op]
        if order < last:
            out.append(_e("V-SCH-6", f"step {s.op!r} is out of order (filter/normalize -> join -> group_by -> aggregate/metric -> compare -> rank)", s.op))
        last = max(last, order)
        out.extend(_check_one_step(s))

    if not plan.metric_ids:
        out.append(_e("V-SCH-5", "a plan must compute at least one registered metric"))
    return out


def _check_one_step(s: Step) -> list[Violation]:
    out: list[Violation] = []
    if s.op == "filter":
        dim, op, val = s.get("dimension"), s.get("op"), s.get("value")
        if dim not in cat.DIMENSIONS:
            out.append(_e("V-SCH-1", f"filter dimension {dim!r} is not in the catalog", str(dim)))
        if op not in cat.FILTER_OPS:
            out.append(_e("V-SCH-1", f"filter operator {op!r} is not permitted", str(op)))
        if not _is_str_or_strs(val):
            out.append(_e("V-SCH-2", "filter value must be a string or a list of strings"))
        elif dim == "marketplace":
            vals = (val,) if isinstance(val, str) else val
            for v in vals:
                if v.upper() not in cat.MARKETPLACES:
                    out.append(_e("V-SCH-1", f"unknown marketplace {v!r}", v))
    elif s.op == "normalize":
        if s.get("kind") not in cat.NORMALIZE_KINDS:
            out.append(_e("V-SCH-1", f"normalize kind {s.get('kind')!r} is not permitted", str(s.get("kind"))))
    elif s.op == "join":
        if s.get("join_id") not in cat.JOINS:
            out.append(_e("V-JOIN-1", f"join {s.get('join_id')!r} is not in the catalog (ad-hoc key pairs are never allowed)", str(s.get("join_id"))))
    elif s.op == "group_by":
        dims = s.get("dimensions", ())
        if not isinstance(dims, tuple) or not dims:
            out.append(_e("V-SCH-2", "group_by needs a non-empty dimensions list"))
        else:
            for d in dims:
                if d not in cat.DIMENSIONS:
                    out.append(_e("V-SCH-1", f"group_by dimension {d!r} is not in the catalog", str(d)))
        gran = s.get("period_granularity")
        if gran is not None and gran not in cat.PERIOD_GRANULARITIES:
            out.append(_e("V-SCH-1", f"period_granularity {gran!r} is not permitted", str(gran)))
        if gran is not None and (not isinstance(dims, tuple) or "period" not in dims):
            out.append(_e("V-SCH-2", "period_granularity requires 'period' in dimensions"))
    elif s.op in ("aggregate", "metric"):
        mid = s.get("metric")
        m = cat.METRICS.get(mid) if isinstance(mid, str) else None
        if m is None:
            out.append(_e("V-SCH-1", f"metric {mid!r} is not in the catalog", str(mid)))
        else:
            is_set = m.kind in (cat.MetricKind.SET_SUM, cat.MetricKind.SET_COUNT, cat.MetricKind.SET_DISTINCT_COUNT, cat.MetricKind.SET_WEIGHTED_AVG)
            if s.op == "aggregate" and not is_set:
                out.append(_e("V-SCH-6", f"{mid} is an engine metric; use a 'metric' step, not 'aggregate'", str(mid)))
            if s.op == "metric" and is_set:
                out.append(_e("V-SCH-6", f"{mid} is a set aggregation; use an 'aggregate' step, not 'metric'", str(mid)))
    elif s.op == "compare":
        if s.get("kind") not in cat.COMPARE_KINDS:
            out.append(_e("V-SCH-1", f"compare kind {s.get('kind')!r} is not permitted", str(s.get("kind"))))
        mid = s.get("metric")
        if mid is not None and mid not in cat.METRICS:
            out.append(_e("V-SCH-1", f"compare metric {mid!r} is not in the catalog", str(mid)))
    elif s.op == "rank":
        mid = s.get("metric")
        if mid not in cat.METRICS:
            out.append(_e("V-SCH-1", f"rank metric {mid!r} is not in the catalog", str(mid)))
        if s.get("direction") not in cat.RANK_DIRECTIONS:
            out.append(_e("V-SCH-1", f"rank direction {s.get('direction')!r} is not permitted", str(s.get("direction"))))
        top_n = s.get("top_n")
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n <= 0:
            out.append(_e("V-RES-2", "rank top_n must be a positive integer"))
    return out


def _requested_grain(plan: QueryPlan) -> cat.Grain:
    dims = plan.group_by_dimensions
    if "sku" in dims:
        return cat.Grain.SKU
    if "marketplace" in dims:
        return cat.Grain.MARKETPLACE
    return cat.Grain.ACCOUNT


def _check_grain(plan: QueryPlan) -> list[Violation]:
    out: list[Violation] = []
    requested = _requested_grain(plan)
    dims = set(plan.group_by_dimensions)
    for mid in plan.metric_ids:
        m = cat.METRICS.get(mid)
        if m is None:
            continue  # already V-SCH-1
        disallowed = dims - m.allowed_dimensions
        if disallowed:
            out.append(_e("V-GRN-2", f"{mid} cannot be grouped by {sorted(disallowed)}", mid))
        if requested < m.grain:
            if m.allocatable:
                out.append(_w("V-GRN-4", f"{mid} is defined at {m.grain.name} grain; the finer view is an allocation (engine §5.10) and is DERIVED", "DERIVED_ALLOCATION"))
            else:
                out.append(_e("V-GRN-1", f"{mid} is not defined at {requested.name} grain (finest supported: {m.grain.name})", mid))
    return out


def _check_periods(plan: QueryPlan) -> list[Violation]:
    out: list[Violation] = []
    for i, p in enumerate(plan.periods):
        if p.end < p.start:
            out.append(_e("V-SCH-4", f"periods[{i}] ends before it starts"))
        if p.as_of_date < p.start:
            out.append(_e("V-SCH-4", f"periods[{i}].as_of_date precedes the period start"))

    compares = plan.steps_of("compare")
    for c in compares:
        if c.get("kind") == "period_over_period":
            if len(plan.periods) < 2:
                out.append(_e("V-PER-2", "a period comparison needs two periods"))
                continue
            a, b = plan.periods[0], plan.periods[1]
            if not (a.end < b.start or b.end < a.start):
                out.append(_e("V-PER-5", "compared periods overlap"))
            elif (a.end - a.start) != (b.end - b.start):
                out.append(_w("V-PER-2", "compared periods have different lengths", "UNEQUAL_PERIODS"))

    bases = {cat.METRICS[m].basis for m in plan.metric_ids if m in cat.METRICS}
    if len(bases) > 1:
        out.append(_w("V-PER-1", "metrics on different date bases are shown together; each must be labelled", "MIXED_BASIS"))
    return out


def _check_pnl_exclusions(plan: QueryPlan) -> list[Violation]:
    """V-ACC-4: owner drawings, inventory purchases, capital items and tax assets never feed a P&L metric."""
    out: list[Violation] = []
    has_pnl = any(cat.METRICS[m].is_pnl_metric for m in plan.metric_ids if m in cat.METRICS)
    if not has_pnl:
        return out
    for f in plan.steps_of("filter"):
        if f.get("dimension") == "expense_class":
            val = f.get("value")
            vals = (val,) if isinstance(val, str) else (val or ())
            bad = sorted(v for v in vals if isinstance(v, str) and v.upper() in cat.NON_PNL_EXPENSE_CLASSES)
            if bad:
                out.append(_e("V-ACC-4", f"{bad} can never feed a profit figure (cash/owner/tax items, not P&L)", bad[0]))
    return out


def _check_joins_static(plan: QueryPlan) -> list[Violation]:
    out: list[Violation] = []
    for jid in plan.join_ids:
        j = cat.JOINS.get(jid)
        if j is None:
            continue
        if not j.validated:
            if jid.startswith("amazon_"):
                out.append(_e("V-JOIN-7", "Amazon settlement match keys are not yet validated against a real export — pending match-key verification", jid))
            else:
                out.append(_w("V-JOIN-7", f"{jid}: join key not yet validated against a real export; results are PROVISIONAL", "PROVISIONAL_JOIN"))
    return out


def validate_static(plan: QueryPlan, limits: ValidatorLimits) -> list[Violation]:
    out = _check_steps(plan)
    if plan.limit < 1 or plan.limit > limits.max_limit:
        out.append(_e("V-RES-2", f"limit must be between 1 and {limits.max_limit}"))
    out.extend(_check_periods(plan))
    out.extend(_check_grain(plan))
    out.extend(_check_pnl_exclusions(plan))
    out.extend(_check_joins_static(plan))
    return out


# ---------------------------------------------------------------------------------- data-fact rules
def _check_join_facts(plan: QueryPlan, stats: DataStats) -> list[Violation]:
    out: list[Violation] = []
    for jid in plan.join_ids:
        j = cat.JOINS.get(jid)
        if j is None:
            continue
        f = stats.joins.get(jid)
        if f is None:
            out.append(_e("V-JOIN-2", f"no join facts were measured for {jid}; refusing to execute (fail closed)", jid))
            continue
        if f.unique_side_rows != f.unique_side_distinct_keys:
            out.append(_e("V-JOIN-2", f"{jid}: the '{j.uniqueness_side}' side is not unique on its key ({f.unique_side_rows} rows, {f.unique_side_distinct_keys} distinct keys)", jid))
        if f.control_total_before != f.control_total_after:
            out.append(_e("V-JOIN-3", f"{jid}: control total changed across the join — fan-out detected; execution blocked", jid))
        if j.cardinality == "ONE_TO_MANY" and not f.many_side_preaggregated:
            out.append(_e("V-JOIN-4", f"{jid}: the many side must be aggregated to the join key before joining", jid))
        if f.settlement_lines_matching_multiple_orders > 0 and f.declared_many_to_one_reason is None:
            out.append(_e("V-JOIN-5", f"{jid}: {f.settlement_lines_matching_multiple_orders} settlement line(s) match more than one order with no declared reason", jid))
        if f.unmatched_left_rows or f.unmatched_right_rows:
            out.append(_w("V-JOIN-6", f"{jid}: {f.unmatched_left_rows} unmatched on the left, {f.unmatched_right_rows} on the right (reported, not dropped silently)", "UNMATCHED_ROWS"))
    return out


def _check_duplicates(stats: DataStats) -> list[Violation]:
    out: list[Violation] = []
    for source, (rows, distinct) in sorted(stats.natural_key_rows.items()):
        if rows != distinct:
            out.append(_e("V-DUP-1", f"{source}: {rows} rows but {distinct} distinct natural keys — duplicates would inflate every aggregate", source))
    for (component, scope), owners in sorted(stats.cost_owners.items()):
        if len(owners) > 1:
            out.append(_e("V-DUP-2", f"{component} ({scope}) has more than one active source {sorted(owners)}; the seller must choose which is authoritative", component))
    if stats.unconfirmed_overlap_expenses > 0:
        out.append(_w("V-DUP-3", f"{stats.unconfirmed_overlap_expenses} expense entries may overlap a marketplace deduction and are excluded until confirmed", "EXCLUDED_OVERLAP_EXPENSES"))
    return out


def _check_partial_period(plan: QueryPlan, stats: DataStats) -> list[Violation]:
    out: list[Violation] = []
    if not stats.data_coverage_end:
        return out
    wanted: set[str] = set(stats.data_coverage_end)
    for f in plan.steps_of("filter"):
        if f.get("dimension") == "marketplace":
            val = f.get("value")
            wanted = {v.upper() for v in ((val,) if isinstance(val, str) else (val or ()))}
    for p in plan.periods:
        for mkt in sorted(wanted):
            end = stats.data_coverage_end.get(mkt)
            if end is not None and end < p.end:
                out.append(_w("V-PER-3", f"{mkt}: data ends {end.isoformat()}, before the period end {p.end.isoformat()}", "PARTIAL_PERIOD"))
    return out


def _unavailable_by_completeness(plan: QueryPlan, stats: DataStats, limits: ValidatorLimits) -> dict[str, str]:
    """V-CMP-1: a metric whose required inputs are under-covered, unmeasured or unconfigured is UNAVAILABLE
    (never defaulted) — and the caller raises a data request (V-CMP-3)."""
    out: dict[str, str] = {}
    for mid in plan.metric_ids:
        m = cat.METRICS.get(mid)
        if m is None:
            continue
        for inp in m.required_inputs:
            threshold = limits.min_coverage.get(inp)
            if threshold is None:
                out[mid] = f"CONFIG_MISSING: no minimum coverage is configured for input '{inp}'"
                break
            coverage = stats.input_coverage.get(inp)
            if coverage is None:
                out[mid] = f"input '{inp}' coverage was not measured"
                break
            if coverage < threshold:
                out[mid] = f"input '{inp}' is available for {coverage.numerator}/{coverage.denominator} of lines, below the required {threshold.numerator}/{threshold.denominator}"
                break
    return out


def validate(plan: QueryPlan, stats: DataStats | None, limits: ValidatorLimits) -> ValidationReport:
    """Static rules always; data-fact rules only when the static rules passed and facts were supplied
    (the executor measures facts only for a plan that is otherwise legal)."""
    violations = validate_static(plan, limits)
    unavailable: dict[str, str] = {}
    if not any(v.severity is Severity.ERROR for v in violations):
        if stats is None:
            violations.append(_e("V-RES-3", "data facts were not supplied; refusing to execute (fail closed)"))
        else:
            violations.extend(_check_join_facts(plan, stats))
            violations.extend(_check_duplicates(stats))
            violations.extend(_check_partial_period(plan, stats))
            if stats.estimated_rows > limits.max_rows_scanned:
                violations.append(_e("V-RES-1", f"estimated rows scanned {stats.estimated_rows} exceeds the cap {limits.max_rows_scanned}"))
            if stats.estimated_groups > limits.max_groups:
                violations.append(_e("V-RES-1", f"estimated groups {stats.estimated_groups} exceeds the cap {limits.max_groups}; narrow the scope"))
            unavailable = _unavailable_by_completeness(plan, stats, limits)
    return ValidationReport(violations=tuple(violations), unavailable_metrics=unavailable)


# ------------------------------------------------------------------------ post-execution checks
@dataclass(frozen=True, slots=True)
class FigureProvenance:
    metric_id: str
    status: str  # VERIFIED | DERIVED | MANUAL | ESTIMATED | UNAVAILABLE | PARTIAL
    engine_result_ref: str | None = None
    estimate_ref: str | None = None


def check_figures_have_refs(figures: Sequence[FigureProvenance]) -> list[Violation]:
    """V-DET-2 / AC-P10: every figure cites its source result; an estimate cites an estimate_ref, never an engine ref."""
    out: list[Violation] = []
    for f in figures:
        if f.status == "UNAVAILABLE":
            continue
        if f.status == "ESTIMATED":
            if not f.estimate_ref or f.engine_result_ref:
                out.append(_e("V-DET-2", f"{f.metric_id}: an estimate must cite an estimate_ref and never an engine_result_ref", f.metric_id))
        elif not f.engine_result_ref:
            out.append(_e("V-DET-2", f"{f.metric_id}: figure has no engine_result_ref", f.metric_id))
    return out


def check_additivity(metric_id: str, per_marketplace: Mapping[str, int | None], consolidated: int | None) -> list[Violation]:
    """V-ACC-2: Σ per-marketplace == consolidated for additive metrics, exactly. The sum is Brain 1's
    (`calc_engine.formulas.identities`); this only turns its verdict into a violation."""
    m = cat.METRICS.get(metric_id)
    if m is None or not m.additive:
        return []
    r = check_additive(per_marketplace, consolidated)
    if r.ok:
        return []
    if r.unavailable_parts:
        return [_e("V-ACC-2", f"{metric_id}: unavailable for {list(r.unavailable_parts)}; a consolidated figure would silently exclude them", metric_id)]
    return [_e("V-ACC-2", f"{metric_id}: marketplaces do not add up to the consolidated figure", metric_id)]


def check_bridge(delta: int, other: int, limits: ValidatorLimits) -> list[Violation]:
    """V-ACC-3: drivers plus OTHER equal the delta (guaranteed by the engine); a nonzero OTHER is
    reported, and a large unexplained share is labelled LOW_EXPLAINABILITY."""
    out: list[Violation] = []
    if other != 0:
        out.append(_e("V-ACC-3", "the bridge does not fully reconcile: a component feeding Contribution Profit is missing from it", "OTHER"))
    share = unexplained_share(delta, other)
    if share is not None and share > limits.low_explainability_share:
        out.append(_w("V-ACC-3", "the named drivers explain too little of the movement", "LOW_EXPLAINABILITY"))
    return out


def check_oracle_sample(fast: Mapping[str, int | None], reference: Mapping[str, int | None]) -> list[Violation]:
    """V-DET-3: the set-based fast path must equal the per-line reference engine on the sampled keys."""
    out: list[Violation] = []
    for key in sorted(set(fast) | set(reference)):
        if fast.get(key, "<absent>") != reference.get(key, "<absent>"):
            out.append(_e("V-DET-3", f"fast path and reference engine disagree for {key}: this is a defect, not a rounding difference", key))
    return out
