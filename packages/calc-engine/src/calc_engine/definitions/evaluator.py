"""Pure recursive evaluator for formula_definition trees — deterministic-engine.md §4.1 (F1-F6).

No I/O inside evaluate() (F6): all data (lines, config values, other metrics' definitions,
the call-function registry) is pre-fetched into an EvalContext by the caller
(api.compute_metric) before evaluation starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Sequence

from calc_engine.definitions.schema import (
    CallNode,
    ComponentSumNode,
    ConfigRefNode,
    DivideRatioNode,
    MetricRefNode,
    Node,
    OpNode,
)
from calc_engine.formulas.component_sum import BearerResolver, sum_components
from calc_engine.types import ZERO, Bearer, CanonicalLine, Paise, Unavailable

EvalResult = Paise | Unavailable | Fraction | str
CallFunction = Callable[["EvalContext"], EvalResult]


@dataclass
class EvalContext:
    """Everything a formula_definition tree needs, pre-fetched — evaluate() does no I/O."""

    lines: Sequence[CanonicalLine]
    bearer_resolver: BearerResolver
    call_registry: dict[str, CallFunction] = field(default_factory=dict)
    config: dict[str, object] = field(default_factory=dict)
    metric_definitions: dict[str, Node] = field(default_factory=dict)
    _memo: dict[str, EvalResult] = field(default_factory=dict)


def evaluate(node: Node, context: EvalContext) -> EvalResult:
    if isinstance(node, ComponentSumNode):
        bearer = Bearer(node.bearer) if node.bearer is not None else None
        return sum_components(
            context.lines,
            component_codes=frozenset(node.component_codes) if node.component_codes is not None else None,
            component_kind=node.component_kind,
            side=node.side,
            bearer=bearer,
            bearer_resolver=context.bearer_resolver if bearer is not None else None,
            exclude_rto_lines=node.exclude_rto_lines,
            exclude_codes=frozenset(node.exclude_codes) if node.exclude_codes is not None else None,
        )

    if isinstance(node, MetricRefNode):
        if node.metric_code in context._memo:
            return context._memo[node.metric_code]
        if node.metric_code not in context.metric_definitions:
            raise KeyError(f"evaluate: no formula_definition registered for metric_code {node.metric_code!r}")
        result = evaluate(context.metric_definitions[node.metric_code], context)
        context._memo[node.metric_code] = result
        return result

    if isinstance(node, CallNode):
        if node.function not in context.call_registry:
            raise KeyError(f"evaluate: no function {node.function!r} in the call registry")
        return context.call_registry[node.function](context)

    if isinstance(node, OpNode):
        return _evaluate_op(node, context)

    if isinstance(node, DivideRatioNode):
        numerator = evaluate(node.numerator, context)
        denominator = evaluate(node.denominator, context)
        if isinstance(numerator, Unavailable):
            return numerator
        if isinstance(denominator, Unavailable):
            return denominator
        if not isinstance(numerator, Paise) or not isinstance(denominator, Paise):
            raise TypeError("divide_ratio requires both terms to evaluate to Paise")
        if denominator.value == 0:
            return node.on_zero_denominator
        return Fraction(numerator.value, denominator.value)

    if isinstance(node, ConfigRefNode):
        if node.config_key not in context.config:
            raise KeyError(f"evaluate: config key {node.config_key!r} not resolved in context.config")
        config_value = context.config[node.config_key]
        if not isinstance(config_value, (Paise, Unavailable, Fraction, str)):
            raise TypeError(f"config_ref {node.config_key!r} resolved to unsupported type {type(config_value)!r}")
        return config_value

    raise TypeError(f"evaluate: unknown node type {type(node)!r}")


def _evaluate_op(node: OpNode, context: EvalContext) -> EvalResult:
    """ADD sums every term. SUB treats the first term as the base and subtracts the rest —
    this matches every §5 formula's shape (e.g. NRR = GOV - SFD - ...), where the first term
    is the starting value, not one more thing to subtract."""
    if not node.terms:
        return ZERO

    if node.op == "ADD":
        total = ZERO
        for term in node.terms:
            value = evaluate(term.term, context)
            if isinstance(value, Unavailable):
                if term.required:
                    return value
                continue
            if not isinstance(value, Paise):
                raise TypeError(f"op ADD term evaluated to non-Paise value {value!r}")
            total = total + value
        return total

    if node.op == "SUB":
        first_term = node.terms[0]
        first_value = evaluate(first_term.term, context)
        if isinstance(first_value, Unavailable):
            if first_term.required:
                return first_value
            first_value = ZERO
        if not isinstance(first_value, Paise):
            raise TypeError(f"op SUB base term evaluated to non-Paise value {first_value!r}")

        total = first_value
        for term in node.terms[1:]:
            value = evaluate(term.term, context)
            if isinstance(value, Unavailable):
                if term.required:
                    return value
                continue
            if not isinstance(value, Paise):
                raise TypeError(f"op SUB term evaluated to non-Paise value {value!r}")
            total = total - value
        return total

    raise ValueError(f"unknown op {node.op!r}")
