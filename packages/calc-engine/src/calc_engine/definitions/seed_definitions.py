"""formula_version=template.v1 trees — deterministic-engine.md §1.2.1.

`SELLER_FUNDED_DISCOUNTS.v1` is decomposed into the primitive node types to demonstrate F1
("no metric's structure is expressed in imperative code") concretely. `GROSS_ORDER_VALUE.v1`,
`NET_REALIZED_REVENUE.v1`, and `CONTRIBUTION_PROFIT.v1` wrap their existing pure functions via
a `call` node instead — each of those functions' own logic (per-line exclusion/disclosure for
NRR, Unavailable-propagation for Contribution Profit) is genuinely procedural, which is exactly
what F1's own `call` node type exists for ("invoke a named function from a closed, reviewed
registry, for genuinely procedural logic"). Decomposing them further into primitives would not
make them more "data-driven" in any way that changes what F2-F6 require — it would just
duplicate logic that already lives in one reviewed, tested place.
"""

from __future__ import annotations

from typing import Any

GROSS_ORDER_VALUE_V1: dict[str, Any] = {
    "type": "call",
    "function": "gross_order_value",
}

SELLER_FUNDED_DISCOUNTS_V1: dict[str, Any] = {
    "type": "op",
    "op": "ADD",
    "terms": [
        {
            "required": True,
            "term": {
                "type": "component_sum",
                "component_codes": ["SELLER_DISCOUNT"],
                "component_kind": "DISCOUNT",
                "side": "INVOICE",
            },
        },
        {
            "required": True,
            "term": {
                "type": "component_sum",
                "component_codes": ["SHIPPING_DISCOUNT"],
                "component_kind": "DISCOUNT",
                "side": "INVOICE",
                "bearer": "SELLER",
            },
        },
        {
            "required": True,
            "term": {
                "type": "component_sum",
                "component_codes": ["PLATFORM_DISCOUNT"],
                "component_kind": "DISCOUNT",
                "side": "INVOICE",
                "bearer": "SELLER",
            },
        },
        {
            "required": True,
            "term": {
                "type": "component_sum",
                "component_codes": ["CASHBACK_DISCOUNT"],
                "component_kind": "DISCOUNT",
                "side": "INVOICE",
                "bearer": "SELLER",
            },
        },
        {
            "required": True,
            "term": {
                "type": "component_sum",
                "component_codes": None,
                "component_kind": "DISCOUNT",
                "side": "INVOICE",
                "bearer": "UNKNOWN",
                "exclude_codes": ["SELLER_DISCOUNT"],
            },
        },
    ],
}

NET_REALIZED_REVENUE_V1: dict[str, Any] = {
    "type": "call",
    "function": "net_realized_revenue",
}

CONTRIBUTION_PROFIT_V1: dict[str, Any] = {
    "type": "call",
    "function": "contribution_profit",
}

SEED_DEFINITIONS: dict[str, dict[str, Any]] = {
    "GROSS_ORDER_VALUE.v1": GROSS_ORDER_VALUE_V1,
    "SELLER_FUNDED_DISCOUNTS.v1": SELLER_FUNDED_DISCOUNTS_V1,
    "NET_REALIZED_REVENUE.v1": NET_REALIZED_REVENUE_V1,
    "CONTRIBUTION_PROFIT.v1": CONTRIBUTION_PROFIT_V1,
}
