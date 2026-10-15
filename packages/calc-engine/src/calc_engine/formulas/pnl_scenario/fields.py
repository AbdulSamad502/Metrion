"""Data-driven fee FIELD definitions per marketplace. This file holds field definitions only, never a rate: the seller types every value.
Do not add default rates here (docs/specs/calculator.md N4)."""

from __future__ import annotations

from dataclasses import dataclass

from calc_engine.formulas.pnl_scenario.types import AmazonFulfilment, ChargedOn, LineGroup, MarketplaceId, PriceBasis


@dataclass(frozen=True, slots=True)
class FeeFieldDef:
    id: str
    label: str
    unit: str  # "percent" | "flat"
    group: LineGroup
    charged_on: ChargedOn
    basis: PriceBasis = "price_incl_gst"
    quick: bool = False
    material: bool = False
    material_on_returns: bool = False
    tierable: bool = False
    amazon_fulfilment: tuple[AmazonFulfilment, ...] | None = None


_AMAZON = (
    FeeFieldDef("referral", "Referral fee", "percent", "commission", "shipped", quick=True, material=True, tierable=True),
    FeeFieldDef("closing", "Closing fee", "flat", "other_fee", "shipped", quick=True, material=True, tierable=True),
    FeeFieldDef("shipping", "Shipping / weight-handling fee", "flat", "shipping", "shipped", quick=True, material=True,
                amazon_fulfilment=("easy_ship", "seller_flex", "self_ship")),
    FeeFieldDef("fba_fulfilment", "FBA fulfilment fee", "flat", "fulfilment", "shipped", quick=True, material=True, amazon_fulfilment=("fba",)),
    FeeFieldDef("reverse", "Return / RTO handling fee", "flat", "shipping", "rto_return", material_on_returns=True),
    FeeFieldDef("other", "Other per-order fee", "flat", "other_fee", "shipped"),
)
_FLIPKART = (
    FeeFieldDef("commission", "Commission", "percent", "commission", "shipped", quick=True, material=True, tierable=True),
    FeeFieldDef("fixed_fee", "Fixed fee", "flat", "other_fee", "shipped", quick=True, material=True, tierable=True),
    FeeFieldDef("collection_fee", "Collection / payment fee", "percent", "other_fee", "shipped"),
    FeeFieldDef("shipping", "Shipping fee", "flat", "shipping", "shipped", quick=True, material=True),
    FeeFieldDef("reverse", "Reverse shipping fee", "flat", "shipping", "rto_return", material_on_returns=True),
    FeeFieldDef("other", "Other per-order fee", "flat", "other_fee", "shipped"),
)
_MEESHO = (
    FeeFieldDef("commission", "Commission", "percent", "commission", "shipped", quick=True, material=True, tierable=True),
    FeeFieldDef("shipping", "Shipping charge", "flat", "shipping", "shipped", quick=True, material=True),
    FeeFieldDef("reverse", "Return / RTO shipping charge", "flat", "shipping", "rto_return", material_on_returns=True),
    FeeFieldDef("other", "Other platform fee", "flat", "other_fee", "shipped", quick=True),
)

MARKETPLACE_FIELDS: dict[str, tuple[FeeFieldDef, ...]] = {"amazon": _AMAZON, "flipkart": _FLIPKART, "meesho": _MEESHO}


def active_fields(marketplace: MarketplaceId, amazon_fulfilment: AmazonFulfilment) -> list[FeeFieldDef]:
    return [
        f
        for f in MARKETPLACE_FIELDS[marketplace]
        if f.amazon_fulfilment is None or (marketplace == "amazon" and amazon_fulfilment in f.amazon_fulfilment)
    ]
