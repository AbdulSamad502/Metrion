"""Conflict detection and rendering (spec §6.32, AC46).

A conflict is two stored values for one quantity that disagree. It is detected by CODE from persisted rows, never by the model; both sides are Figures with refs
(so each is verified like any other figure); and the system, not the model, renders the block that states both values, both sources and both dates and says
that neither was chosen or averaged. The composer must write the conflict's marker; it may not say which value is right.

Two classes (V1), each defined narrowly so ordinary recomputation is never mistaken for a disagreement:
  C1 METRIC .......... two stored engine results for the same metric, period, grain, target and basis, computed from the SAME inputs (data version, config,
                       formula, adjustment set) that nonetheless hold different values. A newer result computed from newer inputs is an update, not a conflict.
  C2 MANUAL INPUT .... two ACTIVE seller inputs for the same target and field with different values (the supersede flow keeps one active; two is a disagreement).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction
from typing import Any

from backend.ceo.contract import Conflict, Figure, RefKind

_SOURCE: Mapping[RefKind, str] = {
    RefKind.ENGINE_RESULT: "Metrion's calculation",
    RefKind.ESTIMATE: "an estimate",
    RefKind.SELLER_PROVIDED: "entered by you",
    RefKind.AGENT_REPORT_FIELD: "a saved specialist report",
}


def source_label(figure: Figure) -> str:
    return _SOURCE.get(figure.ref.kind, "a stored record")


def side_text(f: Figure) -> str:
    when = f", as of {f.as_of.date().isoformat()}" if f.as_of is not None else ""
    return f"{f.label}: {f.formatted_value} ({source_label(f)}, {f.register.value.lower()}{when})"


def render(c: Conflict) -> str:
    """The block the seller reads. Written by code from two verified figures; the model never writes it."""
    return f"{c.what} has two different stored values: {side_text(c.a)}, and {side_text(c.b)}. They differ; neither has been chosen, averaged or combined."


def _value_key(row: Mapping[str, Any]) -> tuple[str, str]:
    den = row.get("value_fraction_denominator")
    if den:
        return ("fraction", str(Fraction(int(row["value_fraction_numerator"]), int(den))))
    return ("paise", str(row.get("value_paise")))


def metric_conflicts(
    rows: Sequence[Mapping[str, Any]], *, figure_for: Callable[[Mapping[str, Any]], Figure], what_for: Callable[[Mapping[str, Any]], str],
) -> list[Conflict]:
    """C1: group available results by everything that makes two results comparable AND everything they were computed from; a group holding two different
    values is a conflict between its two most recent distinct values."""
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        if not r.get("is_available"):
            continue
        key = tuple(str(r.get(k)) for k in (
            "metric_code", "period", "grain", "target_ref", "recognition_state", "calculation_basis", "canonical_data_version", "config_version", "formula_version",
        )) + (json.dumps(r.get("manual_adjustment_set"), sort_keys=True, default=str),)
        groups[key].append(r)
    out: list[Conflict] = []
    for members in groups.values():
        distinct: dict[tuple[str, str], Mapping[str, Any]] = {}
        for r in sorted(members, key=lambda m: m["computed_at"], reverse=True):
            distinct.setdefault(_value_key(r), r)
        if len(distinct) >= 2:
            a, b = list(distinct.values())[:2]
            out.append(Conflict("C1_METRIC", what_for(a), figure_for(a), figure_for(b)))
    return out


def manual_input_conflicts(
    rows: Sequence[Mapping[str, Any]], *, comparable: Callable[[Mapping[str, Any]], str | None], figure_for: Callable[[Mapping[str, Any]], Figure], what: str,
) -> list[Conflict]:
    """C2: `rows` are the ACTIVE inputs of ONE target and field. `comparable` maps a row to the value being compared (None = not comparable, left out). Two
    different comparable values are a conflict between the two most recent."""
    distinct: dict[str, Mapping[str, Any]] = {}
    for r in sorted(rows, key=lambda m: m["created_at"], reverse=True):
        v = comparable(r)
        if v is not None:
            distinct.setdefault(v, r)
    if len(distinct) < 2:
        return []
    a, b = list(distinct.values())[:2]
    return [Conflict("C2_MANUAL_INPUT", what, figure_for(a), figure_for(b))]
