"""The evidence packet the CEO receives (cfo-query-planner.md §5.3).

A packet carries *figures* (each citing the engine result it came from), disclosures (exclusions, missing inputs,
labels), the plan/catalog/data identity and the stages timeline — never a raw row. `content_json()` is the
deterministic part (V-DET-1: same plan hash + data version -> byte-identical); the stage timings are wall-clock and
live outside it. No money arithmetic happens here: values arrive from Brain 1 and are only carried.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

PACKET_VERSION = "1"
FIGURE_STATUSES: frozenset[str] = frozenset({"VERIFIED", "DERIVED", "MANUAL", "ESTIMATED", "PARTIAL", "PROVISIONAL", "UNAVAILABLE"})
MAX_DRILLDOWN = 20


@dataclass(frozen=True, slots=True)
class Figure:
    metric_id: str
    status: str
    period_index: int = 0
    dimension_keys: tuple[tuple[str, str], ...] = ()
    value_paise: int | None = None
    value_count: int | None = None
    value_fraction: str | None = None  # exact "numerator/denominator", never a float
    engine_result_ref: str | None = None
    estimate_ref: str | None = None
    formula_version: str = "v1"
    exclusions: tuple[tuple[str, int], ...] = ()  # (reason, count)
    missing_inputs: tuple[str, ...] = ()
    unavailable_reason: str | None = None
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in FIGURE_STATUSES:
            raise ValueError(f"unknown figure status {self.status!r}")
        if self.status == "UNAVAILABLE" and (self.value_paise is not None or self.value_count is not None or self.value_fraction is not None):
            raise ValueError("an UNAVAILABLE figure carries no value (a missing input is never zero)")
        if self.status != "UNAVAILABLE" and self.value_paise is None and self.value_count is None and self.value_fraction is None:
            raise ValueError("an available figure needs a value")
        if self.engine_result_ref and self.estimate_ref:
            raise ValueError("a figure cites an engine_result_ref or an estimate_ref, never both")


@dataclass(frozen=True, slots=True)
class BridgeDriverOut:
    metric_id: str
    delta_paise: int
    ref: str | None


@dataclass(frozen=True, slots=True)
class BridgeOut:
    from_period: int
    to_period: int
    delta_paise: int
    drivers: tuple[BridgeDriverOut, ...]
    other_paise: int
    other_ref: str | None
    reconciles: bool


@dataclass(frozen=True, slots=True)
class Drilldown:
    handle: str
    label: str
    row_count: int


def percent_text(numerator: int, denominator: int) -> str:
    """A share as a percentage with one decimal, **truncated, never rounded up**: 94.99% must not read as 95.0%. Integers only."""
    if denominator <= 0:
        return "0.0"
    tenths = (numerator * 1000) // denominator
    return f"{tenths // 10}.{tenths % 10}"


@dataclass(frozen=True, slots=True)
class CoverageEntry:
    """How well one marketplace's data covers one metric, and what that did to the answer (V-CMP-1 per marketplace). Included marketplaces carry their
    weakest input's share; excluded ones carry the reason and — so the seller sees what is missing from a total — the gross sales of the lines left
    out (`excluded_basis` says what that amount measures; it is never a guess at the metric's own value)."""

    metric_id: str
    period_index: int
    marketplace: str
    included: bool
    input_id: str | None = None
    share: str | None = None  # exact "numerator/denominator"
    share_pct: str | None = None  # truncated to one decimal
    threshold: str | None = None
    threshold_pct: str | None = None
    reason: str | None = None
    excluded_amount_paise: int | None = None
    excluded_line_count: int | None = None
    excluded_basis: str | None = None  # e.g. GROSS_SALES_OF_EXCLUDED_MARKETPLACE
    excluded_ref: str | None = None  # engine_result_ref of that amount


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    ms: int


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    plan_hash: str
    catalog_version: str
    data_version: int
    as_of_date: date
    figures: tuple[Figure, ...]
    bridge: BridgeOut | None = None
    rows_examined: int = 0
    rows_excluded: int = 0
    truncated: bool = False
    labels: tuple[str, ...] = ()
    drilldown: tuple[Drilldown, ...] = ()
    data_requests: tuple[str, ...] = ()
    stages: tuple[Stage, ...] = field(default=())
    cached: bool = False
    coverage: tuple[CoverageEntry, ...] = ()

    def content(self) -> dict[str, Any]:
        """Everything deterministic about the answer (no timings, no cache flag)."""
        return {
            "packet_version": PACKET_VERSION,
            "plan_hash": self.plan_hash,
            "catalog_version": self.catalog_version,
            "data_version": self.data_version,
            "as_of_date": self.as_of_date.isoformat(),
            "figures": [_figure_dict(f) for f in self.figures],
            "bridge": None if self.bridge is None else {
                "from_period": self.bridge.from_period, "to_period": self.bridge.to_period, "delta_paise": self.bridge.delta_paise,
                "drivers": [{"metric_id": d.metric_id, "delta_paise": d.delta_paise, "ref": d.ref} for d in self.bridge.drivers],
                "other_paise": self.bridge.other_paise, "other_ref": self.bridge.other_ref, "reconciles": self.bridge.reconciles,
            },
            "rows_examined": self.rows_examined,
            "rows_excluded": self.rows_excluded,
            "truncated": self.truncated,
            "labels": sorted(self.labels),
            "drilldown": [{"handle": d.handle, "label": d.label, "row_count": d.row_count} for d in self.drilldown],
            "data_requests": sorted(self.data_requests),
            "coverage": [_coverage_dict(c) for c in self.coverage],
        }

    def content_json(self) -> str:
        return json.dumps(self.content(), sort_keys=True, separators=(",", ":"))

    def to_json(self) -> str:
        body = self.content()
        body["stages"] = [{"name": s.name, "ms": s.ms} for s in self.stages]
        return json.dumps(body, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def from_json(raw: str) -> "EvidencePacket":
        d = json.loads(raw)
        if d.get("packet_version") != PACKET_VERSION:
            raise ValueError("unsupported evidence packet version")
        b = d.get("bridge")
        return EvidencePacket(
            plan_hash=d["plan_hash"], catalog_version=d["catalog_version"], data_version=int(d["data_version"]),
            as_of_date=date.fromisoformat(d["as_of_date"]),
            figures=tuple(_figure_from_dict(f) for f in d["figures"]),
            bridge=None if b is None else BridgeOut(
                b["from_period"], b["to_period"], b["delta_paise"],
                tuple(BridgeDriverOut(x["metric_id"], x["delta_paise"], x["ref"]) for x in b["drivers"]),
                b["other_paise"], b["other_ref"], b["reconciles"]),
            rows_examined=d["rows_examined"], rows_excluded=d["rows_excluded"], truncated=d["truncated"],
            labels=tuple(d["labels"]), drilldown=tuple(Drilldown(x["handle"], x["label"], x["row_count"]) for x in d["drilldown"]),
            data_requests=tuple(d["data_requests"]), stages=tuple(Stage(s["name"], s["ms"]) for s in d.get("stages", [])),
            coverage=tuple(CoverageEntry(**c) for c in d.get("coverage", [])),
        )

    def with_stages(self, stages: Sequence[Stage], cached: bool = False) -> "EvidencePacket":
        return replace(self, stages=tuple(stages), cached=cached)


def _coverage_dict(c: CoverageEntry) -> dict[str, Any]:
    return {f: getattr(c, f) for f in c.__dataclass_fields__}


def _figure_dict(f: Figure) -> dict[str, Any]:
    return {
        "metric_id": f.metric_id, "status": f.status, "period_index": f.period_index,
        "dimension_keys": [list(k) for k in f.dimension_keys], "value_paise": f.value_paise, "value_count": f.value_count,
        "value_fraction": f.value_fraction, "engine_result_ref": f.engine_result_ref, "estimate_ref": f.estimate_ref,
        "formula_version": f.formula_version, "exclusions": [list(e) for e in f.exclusions], "missing_inputs": list(f.missing_inputs),
        "unavailable_reason": f.unavailable_reason, "labels": sorted(f.labels),
    }


def _figure_from_dict(d: Mapping[str, Any]) -> Figure:
    return Figure(
        metric_id=d["metric_id"], status=d["status"], period_index=d["period_index"],
        dimension_keys=tuple((k[0], k[1]) for k in d["dimension_keys"]), value_paise=d["value_paise"], value_count=d["value_count"],
        value_fraction=d["value_fraction"], engine_result_ref=d["engine_result_ref"], estimate_ref=d["estimate_ref"],
        formula_version=d["formula_version"], exclusions=tuple((e[0], e[1]) for e in d["exclusions"]),
        missing_inputs=tuple(d["missing_inputs"]), unavailable_reason=d["unavailable_reason"], labels=tuple(d["labels"]),
    )


def assert_no_raw_rows(packet: EvidencePacket, forbidden_markers: Sequence[str]) -> list[str]:
    """AC-P10 helper: names any forbidden marker (a column name, a source id) found in the serialised packet."""
    body = packet.to_json()
    return [m for m in forbidden_markers if m in body]
