"""The trust gate (spec §6.2.1, AC20; P6 decisions 3, 4, 5, 7).

Identity: (provider, model, schema_version) - nothing else, no digest. All-or-nothing: the gate is not per
attribute. A triple is TRUSTED iff its LATEST evaluation run (by `run_at`, ties by id) passed. No run, or a
latest run that failed, means NOT trusted.

* `decide_gate`   - at analysis time: which run (if any) a new analysis may cite as its `eval_gate_ref`.
* `stamp_attributes` - observed values become `IMAGE_OBSERVED` + `EVAL_PASSED` ONLY under a passing gate;
  otherwise `UNVERIFIED_HINT`. UNKNOWN entries are never trusted. The vision parser can emit nothing else.
* `effective_attributes` - at READ time: stored rows are immutable, so a later FAILING evaluation revokes trust
  by downgrading `EVAL_PASSED` to `UNVERIFIED_HINT` in what consumers see. A stored hint is never upgraded.

The database constraint (P1) remains the backstop: it refuses `EVAL_PASSED` without a passing, matching run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from slim_cmo.types import AttributeBasis, TrustState
from slim_cmo.vision.parse import ParsedAnalysis


@dataclass(frozen=True, slots=True)
class EvalRunRef:
    id: UUID
    provider: str
    model: str
    schema_version: str
    passed: bool
    run_at: datetime  # timezone-aware


@dataclass(frozen=True, slots=True)
class GateDecision:
    passed: bool
    gate_ref: UUID | None  # the passing run a new analysis cites; None when the gate is closed
    reason: str


def latest_run(runs: Iterable[EvalRunRef], provider: str, model: str, schema_version: str) -> EvalRunRef | None:
    """The latest run for EXACTLY this triple: a different provider, model or schema version never counts."""
    matching = [r for r in runs if (r.provider, r.model, r.schema_version) == (provider, model, schema_version)]
    return max(matching, key=lambda r: (r.run_at, str(r.id))) if matching else None


def decide_gate(latest: EvalRunRef | None) -> GateDecision:
    if latest is None:
        return GateDecision(False, None, "no evaluation has been recorded for this provider, model and schema version")
    if not latest.passed:
        return GateDecision(False, None, "the latest evaluation for this provider, model and schema version did not pass")
    return GateDecision(True, latest.id, "the latest evaluation passed")


def stamp_attributes(parsed: ParsedAnalysis, decision: GateDecision) -> list[dict[str, Any]]:
    """The attribute list persisted in `product_image_analysis.attributes`."""
    out: list[dict[str, Any]] = []
    for a in parsed.attributes:
        if a.value is None:
            out.append({"name": a.name, "value": None, "basis": AttributeBasis.UNKNOWN.value, "trust_state": TrustState.UNVERIFIED_HINT.value})
        else:
            trust = TrustState.EVAL_PASSED if decision.passed else TrustState.UNVERIFIED_HINT
            out.append({"name": a.name, "value": a.value, "basis": AttributeBasis.IMAGE_OBSERVED.value, "trust_state": trust.value})
    return out


def effective_attributes(attributes: Sequence[Mapping[str, Any]], latest_passed: bool) -> list[dict[str, Any]]:
    """What a consumer may rely on. A copy: the stored row is never modified. Without a currently passing latest
    evaluation every `EVAL_PASSED` is treated as `UNVERIFIED_HINT`; nothing is ever promoted."""
    out: list[dict[str, Any]] = []
    for a in attributes:
        item = dict(a)
        if not latest_passed and item.get("trust_state") == TrustState.EVAL_PASSED.value:
            item["trust_state"] = TrustState.UNVERIFIED_HINT.value
        out.append(item)
    return out
