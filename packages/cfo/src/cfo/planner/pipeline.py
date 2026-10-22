"""The planner pipeline (cfo-query-planner.md §6.1): plan -> validate -> cache -> execute -> evidence packet.

The model's only job is to turn the question into a typed selection from the closed catalog (`PlannerProvider.propose` returns JSON text).
Everything after that is deterministic. A plan that fails parsing or validation gets **one** bounded retry that shows the model the error
list; after that the seller gets an honest refusal. Nothing is ever "fixed up" or guessed, and a refusal never contains a number.

The model receives: the question, the catalog summary (ids only), the periods the CEO resolved, and the plan schema. It receives no rows,
no figures and no tenant identifiers; the plan's periods must equal the CEO-resolved ones exactly (the model may not widen a period).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from cfo.planner import catalog as cat
from cfo.planner.cache import cache_key
from cfo.planner.cache_store import EvidenceCache
from cfo.planner.evidence import EvidencePacket, Stage
from cfo.planner.executor import DataChanged, ExecutorConfig, PlanFailed, PlannerBackend, execute_plan
from cfo.planner.plan import PeriodRef, PlanParseError, QueryPlan, parse_plan, plan_hash
from cfo.planner.validator import ValidatorLimits, Violation, validate, validate_static

MAX_RETRIES = 1  # one bounded re-ask with the validator's error list (spec §6.1)


@dataclass(frozen=True, slots=True)
class PlannerRequest:
    question: str
    periods: tuple[PeriodRef, ...]
    errors: tuple[str, ...] = ()  # the previous attempt's violations, on the single retry


class PlannerProvider(Protocol):
    def propose(self, request: PlannerRequest) -> str: ...


class LlmCompleter(Protocol):
    """The existing `cfo.reasoning.provider.LlmProvider` shape (keyword-only, text in, text out; no numeric parameter anywhere)."""

    def complete(self, *, model: str, prompt: str) -> str: ...


def catalog_summary() -> dict[str, Any]:
    """Ids and shapes only: nothing seller-specific, no figures."""
    return {
        "intents": sorted(cat.PLAN_INTENTS),
        "metrics": {k: {"kind": m.kind.value, "unit": m.unit.value, "dimensions": sorted(m.allowed_dimensions)} for k, m in sorted(cat.METRICS.items())},
        "dimensions": sorted(cat.DIMENSIONS),
        "joins": sorted(cat.JOINS),
        "step_ops": list(cat.STEP_OPS),
        "filter_ops": sorted(cat.FILTER_OPS),
        "compare_kinds": sorted(cat.COMPARE_KINDS),
        "rank_directions": sorted(cat.RANK_DIRECTIONS),
        "granularities": sorted(cat.PERIOD_GRANULARITIES),
        "marketplaces": sorted(cat.MARKETPLACES),
    }


_SCHEMA_EXAMPLE = (
    '{"plan_version":"1","intent":"METRIC_BY_DIMENSION","periods":[{"start":"2026-09-01","end":"2026-09-30","as_of_date":"2026-10-01"}],'
    '"steps":[{"op":"group_by","params":{"dimensions":["marketplace"]}},{"op":"metric","params":{"metric":"GROSS_SALES"}}],"limit":20}'
)


def build_prompt(request: PlannerRequest) -> str:
    periods = [{"start": p.start.isoformat(), "end": p.end.isoformat(), "as_of_date": p.as_of_date.isoformat()} for p in request.periods]
    parts = [
        "You select a query plan from a closed catalog. Reply with ONE JSON object and nothing else.",
        "Rules: use only ids that appear in the catalog; never invent a metric, dimension, join, operator or aggregation; "
        "never write SQL, code or formulas; never include a number you computed; use exactly the periods given, unchanged; "
        "never include a tenant or account identifier. A question the catalog cannot answer must still be returned as the closest legal plan.",
        "Plan schema example: " + _SCHEMA_EXAMPLE,
        "Catalog: " + json.dumps(catalog_summary(), sort_keys=True),
        "Periods to use (exactly): " + json.dumps(periods),
        "Question: " + request.question,
    ]
    if request.errors:
        parts.append("Your previous plan was rejected for these reasons; fix them and reply with a corrected plan: " + "; ".join(request.errors))
    return "\n".join(parts)


class LlmPlannerProvider:
    def __init__(self, llm: LlmCompleter, model: str) -> None:
        self._llm, self._model = llm, model

    def propose(self, request: PlannerRequest) -> str:
        return self._llm.complete(model=self._model, prompt=build_prompt(request))


class MockPlannerProvider:
    """Fixed responses for tests (including adversarial JSON). Records every request it received."""

    def __init__(self, responses: Sequence[str | Exception]) -> None:
        self._responses = list(responses)
        self.requests: list[PlannerRequest] = []

    def propose(self, request: PlannerRequest) -> str:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("MockPlannerProvider ran out of responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


# ------------------------------------------------------------------------------------------------ results
@dataclass(frozen=True, slots=True)
class PlannerAnswer:
    packet: EvidencePacket
    attempts: int


@dataclass(frozen=True, slots=True)
class PlannerRefusal:
    """An honest refusal: a stable code, a seller-safe message and the rule ids behind it. Never carries a figure."""

    code: str  # PLAN_MALFORMED | PLAN_INVALID | PLAN_CHECK_FAILED | DATA_CHANGED | PLANNER_ERROR
    message: str
    rule_ids: tuple[str, ...] = ()
    details: tuple[str, ...] = field(default=())


def _periods_match(plan: QueryPlan, resolved: Sequence[PeriodRef]) -> list[str]:
    got = [(p.start, p.end, p.as_of_date) for p in plan.periods]
    want = [(p.start, p.end, p.as_of_date) for p in resolved]
    return [] if got == want else ["V-PIPE-1: the plan's periods must equal the periods the CEO resolved, exactly (the planner may not widen, narrow or invent a period)"]


def _violation_text(vs: Sequence[Violation]) -> list[str]:
    return [f"{v.rule_id}: {v.message}" for v in vs]


def run_financial_query(
    question: str,
    resolved_periods: Sequence[PeriodRef],
    *,
    tenant_id: UUID,
    provider: PlannerProvider,
    backend: PlannerBackend,
    cache: EvidenceCache | None,
    limits: ValidatorLimits,
    config: ExecutorConfig,
    on_stage: Callable[[str], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> PlannerAnswer | PlannerRefusal:
    now = clock or time.monotonic
    periods = tuple(resolved_periods)
    errors: tuple[str, ...] = ()
    last: PlannerRefusal | None = None
    plan: QueryPlan | None = None
    report = None
    plan_ms = validate_ms = 0

    for attempt in range(MAX_RETRIES + 1):
        if on_stage:
            on_stage("PLANNING")
        t0 = now()
        try:
            raw = provider.propose(PlannerRequest(question=question, periods=periods, errors=errors))
        except Exception as exc:  # model down, refusal, timeout...: an honest failure, no fallback guess
            return PlannerRefusal("PLANNER_ERROR", "I could not work out how to answer that right now.", details=(type(exc).__name__,))
        plan_ms += int((now() - t0) * 1000)

        t1 = now()
        if on_stage:
            on_stage("VALIDATING")
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            last = PlannerRefusal("PLAN_MALFORMED", "I could not turn that question into a valid query.", rule_ids=("V-SCH-2",), details=("the reply was not valid JSON",))
            errors = ("V-SCH-2: the reply was not valid JSON",)
            continue
        try:
            plan = parse_plan(obj)
        except PlanParseError as exc:
            last = PlannerRefusal("PLAN_MALFORMED", "I could not turn that question into a valid query.",
                                  rule_ids=tuple(sorted({v.rule_id for v in exc.violations})), details=tuple(f"{v.rule_id}: {v.message}" for v in exc.violations))
            errors = last.details
            continue
        mismatch = _periods_match(plan, periods)
        if mismatch:
            last = PlannerRefusal("PLAN_INVALID", "I could not keep to the period you asked about.", rule_ids=("V-PIPE-1",), details=tuple(mismatch))
            errors = tuple(mismatch)
            plan = None
            continue
        static = validate_static(plan, limits)
        static_errors = [v for v in static if v.severity.value == "ERROR"]
        if static_errors:
            last = PlannerRefusal("PLAN_INVALID", "That question needs something I cannot compute yet.",
                                  rule_ids=tuple(sorted({v.rule_id for v in static_errors})), details=tuple(_violation_text(static_errors)))
            errors = last.details
            plan = None
            continue
        stats = backend.collect_stats(tenant_id, plan)
        report = validate(plan, stats, limits)
        validate_ms += int((now() - t1) * 1000)
        if not report.ok:
            last = PlannerRefusal("PLAN_INVALID", "That question needs something I cannot compute yet.",
                                  rule_ids=tuple(sorted({v.rule_id for v in report.errors})), details=tuple(_violation_text(report.errors)))
            errors = last.details
            plan = None
            report = None
            continue
        break
    else:
        return last or PlannerRefusal("PLAN_INVALID", "That question needs something I cannot compute yet.")

    assert plan is not None and report is not None
    stages_head = [Stage("PLANNING", plan_ms), Stage("VALIDATING", validate_ms)]
    formula_versions: Mapping[str, str] = {m: cat.METRICS[m].formula_version for m in plan.metric_ids}

    for rerun in range(2):  # E5: data changed during execution -> rerun once
        dv = backend.data_version(tenant_id)
        key = cache_key(plan, tenant_id=tenant_id, data_version=dv, formula_versions=formula_versions)
        if cache is not None:
            hit = cache.get(tenant_id, key, plan_hash=plan_hash(plan), catalog_version=cat.CATALOG_VERSION, data_version=dv)
            if hit is not None:
                if on_stage:
                    on_stage("CACHED")
                return PlannerAnswer(hit.with_stages([Stage("CACHED", 0)], cached=True), attempts=attempt + 1)
        try:
            packet = execute_plan(plan, tenant_id=tenant_id, backend=backend, report=report, limits=limits, config=config, on_stage=on_stage, clock=clock)
        except DataChanged:
            if rerun == 0:
                continue
            return PlannerRefusal("DATA_CHANGED", "Your data changed while I was working; please ask again in a moment.")
        except PlanFailed as exc:
            return PlannerRefusal("PLAN_CHECK_FAILED", "I could not verify that answer, so I am not giving it.",
                                  rule_ids=tuple(sorted({v.rule_id for v in exc.violations})), details=tuple(_violation_text(exc.violations)))
        packet = packet.with_stages([*stages_head, *packet.stages])
        if cache is not None:
            cache.put(tenant_id, key, packet)
        return PlannerAnswer(packet, attempts=attempt + 1)
    return PlannerRefusal("DATA_CHANGED", "Your data changed while I was working; please ask again in a moment.")
