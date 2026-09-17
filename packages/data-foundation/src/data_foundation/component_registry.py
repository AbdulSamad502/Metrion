"""component_code -> component_kind — data-foundation.md §1.4's registry table, verbatim.
Shared by every adapter so `component_kind` is never guessed per-adapter."""

from __future__ import annotations

COMPONENT_KIND_BY_CODE: dict[str, str] = {
    "COMMISSION": "FEE",
    "MARKETPLACE_FEE_GENERIC": "FEE",
    "PLATFORM_FEE": "FEE",
    "FIXED_FEE": "FEE",
    "COLLECTION_FEE": "FEE",
    "PACKAGING_FEE": "FEE",
    "LOGISTICS_FEE": "FEE",
    "COD_FEE": "FEE",
    "SHIPPING_CHARGE": "CHARGE",
    "GIFT_WRAP_CHARGE": "CHARGE",
    "SELLER_DISCOUNT": "DISCOUNT",
    "PLATFORM_DISCOUNT": "DISCOUNT",
    "CASHBACK_DISCOUNT": "DISCOUNT",
    "SHIPPING_DISCOUNT": "DISCOUNT",
    "CGST": "TAX",
    "SGST": "TAX",
    "IGST": "TAX",
    "UTGST": "TAX",
    "CESS": "TAX",
    "TCS": "LEVY",
    "TDS": "LEVY",
}
