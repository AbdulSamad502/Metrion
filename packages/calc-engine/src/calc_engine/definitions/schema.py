"""Closed set of formula_definition JSON node types — deterministic-engine.md §4.1 (F1-F6).

A metric's structure (terms, sign, filters) lives as one of these six node types, composed
into a tree. No metric's structure is expressed in imperative Python (F1); only these node
types, and the closed set of `call` functions and `config_ref` keys they may reference, are
reviewed/extended in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Union


@dataclass(frozen=True)
class ComponentSumNode:
    component_codes: tuple[str, ...] | None
    component_kind: str | None = None
    side: str = "INVOICE"
    bearer: str | None = None  # "SELLER" | "MARKETPLACE" | "UNKNOWN" | None
    exclude_rto_lines: bool = False
    exclude_codes: tuple[str, ...] | None = None


@dataclass(frozen=True)
class MetricRefNode:
    metric_code: str


@dataclass(frozen=True)
class CallNode:
    function: str


@dataclass(frozen=True)
class OpTerm:
    term: "Node"
    required: bool = True


@dataclass(frozen=True)
class OpNode:
    op: Literal["ADD", "SUB"]
    terms: tuple[OpTerm, ...]


@dataclass(frozen=True)
class DivideRatioNode:
    numerator: "Node"
    denominator: "Node"
    on_zero_denominator: str = "UNDEFINED"


@dataclass(frozen=True)
class ConfigRefNode:
    config_key: str


Node = Union[ComponentSumNode, MetricRefNode, CallNode, OpNode, DivideRatioNode, ConfigRefNode]


def parse_node(data: dict[str, Any]) -> Node:
    """Parses a plain dict (as stored in `formula_definition.definition_json`) into a typed Node."""
    node_type = data["type"]

    if node_type == "component_sum":
        codes = data.get("component_codes")
        exclude_codes = data.get("exclude_codes")
        return ComponentSumNode(
            component_codes=tuple(codes) if codes is not None else None,
            component_kind=data.get("component_kind"),
            side=data.get("side", "INVOICE"),
            bearer=data.get("bearer"),
            exclude_rto_lines=data.get("exclude_rto_lines", False),
            exclude_codes=tuple(exclude_codes) if exclude_codes is not None else None,
        )
    if node_type == "metric_ref":
        return MetricRefNode(metric_code=data["metric_code"])
    if node_type == "call":
        return CallNode(function=data["function"])
    if node_type == "op":
        terms = tuple(
            OpTerm(term=parse_node(t["term"]), required=t.get("required", True)) for t in data["terms"]
        )
        return OpNode(op=data["op"], terms=terms)
    if node_type == "divide_ratio":
        return DivideRatioNode(
            numerator=parse_node(data["numerator"]),
            denominator=parse_node(data["denominator"]),
            on_zero_denominator=data.get("on_zero_denominator", "UNDEFINED"),
        )
    if node_type == "config_ref":
        return ConfigRefNode(config_key=data["config_key"])

    raise ValueError(f"parse_node: unknown formula_definition node type {node_type!r}")
