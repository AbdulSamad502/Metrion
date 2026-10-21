"""Typed query plan and its strict parser (cfo-query-planner.md §5.2).

`parse_plan` turns an untrusted JSON object (model output) into a `QueryPlan` or raises
`PlanParseError` carrying stable violation ids. It rejects, rather than ignores, anything unexpected:
unknown fields, a `tenant_id` anywhere in the payload (V-SCH-3), floats anywhere (V-UNIT-1), and
malformed steps. It never "fixes" a plan — the planner may be asked once more with the error list.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

PLAN_VERSION = "1"

_TOP_KEYS = {"plan_version", "intent", "periods", "steps", "limit"}
_PERIOD_KEYS = {"start", "end", "as_of_date", "label"}
_STEP_KEYS = {"op", "params"}
_PARAM_KEYS: dict[str, set[str]] = {
    "filter": {"dimension", "op", "value"},
    "normalize": {"kind"},
    "join": {"join_id"},
    "group_by": {"dimensions", "period_granularity"},
    "aggregate": {"metric"},
    "metric": {"metric"},
    "compare": {"kind", "metric"},
    "rank": {"metric", "direction", "top_n"},
}
_FORBIDDEN_ANYWHERE = {"tenant_id", "tenantid", "tenant", "org_id", "organization_id"}


@dataclass(frozen=True, slots=True)
class PlanViolation:
    rule_id: str
    message: str


class PlanParseError(Exception):
    def __init__(self, violations: Sequence[PlanViolation]) -> None:
        self.violations = tuple(violations)
        super().__init__("; ".join(f"{v.rule_id}: {v.message}" for v in self.violations))


@dataclass(frozen=True, slots=True)
class PeriodRef:
    start: date
    end: date
    as_of_date: date
    label: str | None = None


@dataclass(frozen=True, slots=True)
class Step:
    op: str
    params: tuple[tuple[str, Any], ...]  # sorted (key, value) pairs; lists become tuples — hashable and canonical

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.params:
            if k == key:
                return v
        return default


@dataclass(frozen=True, slots=True)
class QueryPlan:
    plan_version: str
    intent: str
    periods: tuple[PeriodRef, ...]
    steps: tuple[Step, ...]
    limit: int

    # --- accessors: steps are the single source of truth -------------------------------------------
    def steps_of(self, op: str) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.op == op)

    @property
    def metric_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for s in self.steps:
            if s.op in ("aggregate", "metric") and s.get("metric") not in seen:
                seen.append(s.get("metric"))
        return tuple(seen)

    @property
    def group_by_dimensions(self) -> tuple[str, ...]:
        dims: list[str] = []
        for s in self.steps_of("group_by"):
            for d in s.get("dimensions", ()):
                if d not in dims:
                    dims.append(d)
        return tuple(dims)

    @property
    def join_ids(self) -> tuple[str, ...]:
        return tuple(s.get("join_id") for s in self.steps_of("join"))


def _freeze(v: Any) -> Any:
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    return v


def _scan(obj: Any, path: str, out: list[PlanViolation]) -> None:
    """Recursive scan for forbidden keys (V-SCH-3) and floats (V-UNIT-1)."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower().replace("-", "_") in _FORBIDDEN_ANYWHERE:
                out.append(PlanViolation("V-SCH-3", f"client-supplied tenant context is never accepted (found {k!r} at {path})"))
            _scan(v, f"{path}.{k}", out)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _scan(v, f"{path}[{i}]", out)
    elif isinstance(obj, float):
        out.append(PlanViolation("V-UNIT-1", f"floats are not allowed in a plan (at {path})"))


def _parse_date(raw: Any, path: str, out: list[PlanViolation]) -> date | None:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    out.append(PlanViolation("V-SCH-4", f"{path} must be an ISO date (YYYY-MM-DD)"))
    return None


def parse_plan(obj: Any) -> QueryPlan:
    """Strictly parse model output. Raises `PlanParseError` listing every problem found."""
    errs: list[PlanViolation] = []
    if not isinstance(obj, Mapping):
        raise PlanParseError([PlanViolation("V-SCH-2", "plan must be a JSON object")])
    _scan(obj, "plan", errs)

    unknown = set(obj.keys()) - _TOP_KEYS
    if unknown:
        errs.append(PlanViolation("V-SCH-2", f"unknown plan fields: {sorted(map(str, unknown))}"))
    if obj.get("plan_version") != PLAN_VERSION:
        errs.append(PlanViolation("V-SCH-2", f"plan_version must be {PLAN_VERSION!r}"))
    intent = obj.get("intent")
    if not isinstance(intent, str) or not intent:
        errs.append(PlanViolation("V-SCH-2", "intent must be a non-empty string"))

    periods: list[PeriodRef] = []
    raw_periods = obj.get("periods")
    if not isinstance(raw_periods, Sequence) or isinstance(raw_periods, (str, bytes)) or not raw_periods:
        errs.append(PlanViolation("V-SCH-4", "periods must be a non-empty list"))
    else:
        for i, p in enumerate(raw_periods):
            if not isinstance(p, Mapping):
                errs.append(PlanViolation("V-SCH-2", f"periods[{i}] must be an object"))
                continue
            extra = set(p.keys()) - _PERIOD_KEYS
            if extra:
                errs.append(PlanViolation("V-SCH-2", f"periods[{i}] has unknown fields {sorted(map(str, extra))}"))
            s = _parse_date(p.get("start"), f"periods[{i}].start", errs)
            e = _parse_date(p.get("end"), f"periods[{i}].end", errs)
            a = _parse_date(p.get("as_of_date"), f"periods[{i}].as_of_date", errs)  # explicit, never "now" (V-SCH-4)
            if s is not None and e is not None and a is not None:
                label = p.get("label")
                periods.append(PeriodRef(s, e, a, label if isinstance(label, str) else None))

    steps: list[Step] = []
    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes)) or not raw_steps:
        errs.append(PlanViolation("V-SCH-2", "steps must be a non-empty list"))
    else:
        for i, st in enumerate(raw_steps):
            if not isinstance(st, Mapping):
                errs.append(PlanViolation("V-SCH-2", f"steps[{i}] must be an object"))
                continue
            extra = set(st.keys()) - _STEP_KEYS
            if extra:
                errs.append(PlanViolation("V-SCH-2", f"steps[{i}] has unknown fields {sorted(map(str, extra))}"))
            op = st.get("op")
            params = st.get("params", {})
            if not isinstance(op, str) or op not in _PARAM_KEYS:
                errs.append(PlanViolation("V-SCH-1", f"steps[{i}].op {op!r} is not a permitted operation"))
                continue
            if not isinstance(params, Mapping):
                errs.append(PlanViolation("V-SCH-2", f"steps[{i}].params must be an object"))
                continue
            bad = set(params.keys()) - _PARAM_KEYS[op]
            if bad:
                errs.append(PlanViolation("V-SCH-2", f"steps[{i}] ({op}) has unknown params {sorted(map(str, bad))}"))
            steps.append(Step(op=op, params=tuple(sorted((str(k), _freeze(v)) for k, v in params.items() if k in _PARAM_KEYS[op]))))

    limit = obj.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, int):
        errs.append(PlanViolation("V-RES-2", "limit must be an integer"))
        limit = 0

    if errs:
        raise PlanParseError(errs)
    assert isinstance(intent, str)
    return QueryPlan(plan_version=PLAN_VERSION, intent=intent, periods=tuple(periods), steps=tuple(steps), limit=limit)


def canonical_plan_json(plan: QueryPlan) -> str:
    """Stable serialisation: the same plan always yields the same bytes (hash input, V-DET-1)."""
    payload = {
        "plan_version": plan.plan_version,
        "intent": plan.intent,
        "periods": [[p.start.isoformat(), p.end.isoformat(), p.as_of_date.isoformat()] for p in plan.periods],
        "steps": [[s.op, [[k, list(v) if isinstance(v, tuple) else v] for k, v in s.params]] for s in plan.steps],
        "limit": plan.limit,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def plan_hash(plan: QueryPlan) -> str:
    return hashlib.sha256(canonical_plan_json(plan).encode()).hexdigest()
