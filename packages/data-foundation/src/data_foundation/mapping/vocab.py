"""The closed vocabulary a mapping proposal may draw from (cfo-data-intelligence.md §6.4, M-VOC).

Canonical field names mirror the real `sales_line` / `settlement_line` columns plus the expense and
advertising shapes the spec adds. Component codes come straight from the existing registry. The
synonym register is derived from the verified adapters' own headers, so a header an adapter already
knows can be recognised exactly — and a *plausible* synonym ("Item Price", "Sale Amount") is never
auto-trusted: it has to pass validation and be confirmed by the seller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from data_foundation.component_registry import COMPONENT_KIND_BY_CODE

REPORT_KINDS: tuple[str, ...] = ("SALES", "SETTLEMENT", "EXPENSE", "ADVERTISING")

# transform ids a proposal may name
TRANSFORMS: frozenset[str] = frozenset(
    {"IDENTITY", "PAISE_IDENTITY", "RUPEES_TO_PAISE", "DATE_ISO", "DATE_DMY", "DATE_MDY", "PERCENT", "FRACTION_TO_PERCENT"}
)
MONEY_TRANSFORMS: frozenset[str] = frozenset({"PAISE_IDENTITY", "RUPEES_TO_PAISE"})
DATE_TRANSFORMS: frozenset[str] = frozenset({"DATE_ISO", "DATE_DMY", "DATE_MDY"})
PERCENT_TRANSFORMS: frozenset[str] = frozenset({"PERCENT", "FRACTION_TO_PERCENT"})

TAX_INCLUSION_VALUES: frozenset[str] = frozenset({"INCLUSIVE", "EXCLUSIVE", "UNKNOWN"})
SIGN_CONVENTIONS: frozenset[str] = frozenset({"AS_IS", "NEGATE"})

COMPONENT_FIELD = "component_amount"  # a money column that feeds line_component; needs a component_code


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    value_type: str  # text | int | money | date | percent | enum
    kinds: frozenset[str]  # report kinds that accept this field
    is_key: bool = False  # identity-bearing (used for grain detection)


def _f(name: str, vt: str, kinds: tuple[str, ...], key: bool = False) -> FieldSpec:
    return FieldSpec(name, vt, frozenset(kinds), key)


_S, _T, _E, _A = "SALES", "SETTLEMENT", "EXPENSE", "ADVERTISING"

CANONICAL_FIELDS: dict[str, FieldSpec] = {
    f.name: f
    for f in (
        # sales_line
        _f("order_ref", "text", (_S, _T), True), _f("line_ref", "text", (_S, _T), True), _f("invoice_ref", "text", (_S,), True),
        _f("sku", "text", (_S, _A)), _f("marketplace_item_id", "text", (_S,)), _f("item_title", "text", (_S,)),
        _f("hsn_sac", "text", (_S,)), _f("quantity", "int", (_S,)),
        _f("gross_item_amount", "money", (_S,)), _f("taxable_amount", "money", (_S,)), _f("total_invoice_amount", "money", (_S,)),
        _f("order_date", "date", (_S,)), _f("dispatch_date", "date", (_S,)), _f("invoice_date", "date", (_S,)),
        _f("document_type", "enum", (_S, _T)), _f("supply_type", "enum", (_S,)), _f("transaction_type", "enum", (_S,)),
        _f("payment_method", "enum", (_S,)), _f("return_status", "enum", (_S,)), _f("gst_rate", "percent", (_S,)),
        _f("currency", "enum", (_S, _T, _A)),
        # settlement_line
        _f("settlement_id", "text", (_T,)), _f("gross_settlement_amount", "money", (_T,)), _f("settlement_date", "date", (_T,)),
        # expense (registered through manual_adjustment `expense.<category>`; not a new store)
        _f("expense_date", "date", (_E,)), _f("expense_category", "text", (_E,)), _f("expense_amount", "money", (_E,)),
        _f("expense_description", "text", (_E,)), _f("expense_vendor", "text", (_E,)), _f("expense_payment_ref", "text", (_E,)),
        # advertising
        _f("report_date", "date", (_A,)), _f("campaign_ref", "text", (_A,)), _f("spend", "money", (_A,)),
        _f("attributed_sales", "money", (_A,)), _f("impressions", "int", (_A,)), _f("clicks", "int", (_A,)),
        # component feed: money column with a component_code (fee, tax, discount, levy, charge)
        _f(COMPONENT_FIELD, "money", (_S, _T)),
    )
}

COMPONENT_CODES: frozenset[str] = frozenset(COMPONENT_KIND_BY_CODE)

# Required fields per report kind: every group must be satisfied by at least one of its members.
REQUIRED_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "SALES": (("order_ref",), ("quantity",), ("gross_item_amount",), ("invoice_date", "dispatch_date", "order_date")),
    "SETTLEMENT": (("order_ref", "line_ref"), ("gross_settlement_amount",), ("settlement_date",)),
    "EXPENSE": (("expense_date",), ("expense_category",), ("expense_amount",)),
    "ADVERTISING": (("report_date",), ("spend",)),
}

# Fields on which a mixed-sign column is legitimate (refunds/reversals settle negative).
MIXED_SIGN_OK: frozenset[str] = frozenset({"gross_settlement_amount", "gross_item_amount", "total_invoice_amount", "taxable_amount"})


def normalise_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


@lru_cache(maxsize=1)
def synonym_register() -> dict[str, tuple[str, str | None]]:
    """normalised header -> (canonical_field, component_code) taken from every registered adapter's own
    column map. Exact recognition only; anything else is an unrecognised name."""
    from data_foundation.adapters.registry import ADAPTER_REGISTRY  # local: avoids an import cycle at module load

    reg: dict[str, tuple[str, str | None]] = {}
    for adapter in ADAPTER_REGISTRY.values():
        for key, binding in adapter.column_map.items():
            header = key if isinstance(key, str) else key[0]
            if binding.canonical_field.startswith("_"):
                continue
            canonical = COMPONENT_FIELD if binding.component_code else binding.canonical_field
            if canonical in CANONICAL_FIELDS or canonical == COMPONENT_FIELD:
                reg.setdefault(normalise_header(header), (canonical, binding.component_code))
    return reg


def is_exact_register_match(source_column: str, canonical_field: str, component_code: str | None) -> bool:
    hit = synonym_register().get(normalise_header(source_column))
    return hit is not None and hit == (canonical_field, component_code)
