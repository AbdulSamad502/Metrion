"""The four approved criteria (spec §6.18, 2026-10-10) computed from scored results. Each is a stats `block` with hold-out counts and a verdict.

Routing .............. route AND key correct and every required slot taken from the message (all cases except those that must clarify)
Missing-input ........ recall: it clarified when it had to; and over-clarify: it asked when the case was complete (must stay <= 10%)
Conflict handling .... composer cases of category CONFLICT scored clean
Grounded answers ..... every other composer case scored clean on the FIRST draft (gate + the case's own rules)

The HARD safety gate is not measured here: it is measured through the whole orchestrator (`tests/integration/test_ceo_safety_gate.py`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from backend.ceo_eval import stats

_EXECUTING = ("BUSINESS_STATE", "ACTION", "PLAYBOOK", "ADVISORY", "SYNTHESIZE")


def _clarify_only(case: Any) -> bool:
    return "CLARIFY" in case.routes and not any(r in _EXECUTING for r in case.routes)


def _expects_execution(case: Any) -> bool:
    return any(r in ("BUSINESS_STATE", "ACTION", "PLAYBOOK", "SYNTHESIZE") for r in case.routes) and "CLARIFY" not in case.routes


def classifier_criteria(results: Sequence[Any], cases: Mapping[str, Any]) -> dict[str, Any]:
    fam = lambda r: getattr(cases[r.case_id], "family", "")  # noqa: E731
    routing = [(r.case_id, bool(r.route_ok and r.key_ok is not False and r.slots_ok is not False), fam(r)) for r in results if not _clarify_only(cases[r.case_id])]
    recall = [(r.case_id, r.predicted_route == "CLARIFY", fam(r)) for r in results if _clarify_only(cases[r.case_id])]
    over = [(r.case_id, bool(r.over_clarified), fam(r)) for r in results if _expects_execution(cases[r.case_id])]
    miss = stats.block(recall)
    over_block = stats.block(over, kind="upper")
    both = "PASS" if miss["verdict"] == "PASS" and over_block["verdict"] == "PASS" else (
        "INSUFFICIENT_N" if "INSUFFICIENT_N" in (miss["verdict"], over_block["verdict"]) else "FAIL")
    return {"routing": stats.block(routing), "missing_input_recall": miss, "over_clarify": over_block, "missing_input_verdict": both}


def composer_criteria(results: Sequence[Any], cases: Mapping[str, Any]) -> dict[str, Any]:
    fam = lambda r: getattr(cases[r.case_id], "family", "")  # noqa: E731
    conflict = [(r.case_id, bool(r.ok), fam(r)) for r in results if cases[r.case_id].category == "CONFLICT"]
    grounded = [(r.case_id, bool(r.ok), fam(r)) for r in results if cases[r.case_id].category != "CONFLICT"]
    return {"conflict_handling": stats.block(conflict), "grounded_answers": stats.block(grounded)}
