"""Proves the formula_definition evaluator agrees with calling the formulas directly —
deterministic-engine.md §4.1 (F1-F6), approved plan §E.1.
"""

from __future__ import annotations

from calc_engine.definitions.evaluator import EvalContext, evaluate
from calc_engine.definitions.schema import parse_node
from calc_engine.definitions.seed_definitions import GROSS_ORDER_VALUE_V1, SELLER_FUNDED_DISCOUNTS_V1
from calc_engine.formulas.discount_attribution import seller_funded_discounts
from calc_engine.formulas.gross_order_value import gross_order_value
from calc_engine.types import Paise

from tests.conftest import make_bearer_resolver
from tests.fixtures.canonical_builder import CanonicalDataBuilder


def test_gross_order_value_v1_tree_matches_direct_call():
    lines = [
        CanonicalDataBuilder().gross(100_000).build(),
        CanonicalDataBuilder().gross(50_000).build(),
    ]
    resolver = make_bearer_resolver({})
    context = EvalContext(
        lines=lines,
        bearer_resolver=resolver,
        call_registry={"gross_order_value": lambda ctx: gross_order_value(ctx.lines)},
    )

    node = parse_node(GROSS_ORDER_VALUE_V1)
    evaluated = evaluate(node, context)
    direct = gross_order_value(lines)

    assert evaluated == direct == Paise(150_000)


def test_seller_funded_discounts_v1_tree_matches_direct_call():
    lines = [
        CanonicalDataBuilder().gross(100_000).discount("SELLER_DISCOUNT", 20_000).build(),
        CanonicalDataBuilder().gross(50_000).discount("PLATFORM_DISCOUNT", 5_000).build(),  # falls to UNKNOWN -> seller-borne
    ]
    resolver = make_bearer_resolver({})  # no mappings -> everything not explicitly SELLER falls to UNKNOWN
    context = EvalContext(lines=lines, bearer_resolver=resolver)

    node = parse_node(SELLER_FUNDED_DISCOUNTS_V1)
    evaluated = evaluate(node, context)
    direct = seller_funded_discounts(lines, resolver)

    assert evaluated == direct == Paise(25_000)  # 20000 + 5000 (via the UNKNOWN wildcard term)
