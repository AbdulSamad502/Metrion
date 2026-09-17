"""ADAPTER_REGISTRY — one entry per `(marketplace, report_category, format_version)` (§2.1).
Settlement-side adapters (`amazon.settlement.v2`, `meesho.payments.v1`) are deliberately
absent — out of scope for this sales-side-only pass."""

from __future__ import annotations

from data_foundation.adapters.amazon_mtr_b2b_v1 import adapter as amazon_mtr_b2b_v1
from data_foundation.adapters.amazon_mtr_b2c_v1 import adapter as amazon_mtr_b2c_v1
from data_foundation.adapters.flipkart_sales_report_v1 import adapter as flipkart_sales_report_v1
from data_foundation.adapters.meesho_orders_v1 import adapter as meesho_orders_v1
from data_foundation.adapters.meesho_tcs_sales_return_v1 import adapter as meesho_tcs_sales_return_v1
from data_foundation.adapters.meesho_tcs_sales_v1 import adapter as meesho_tcs_sales_v1
from data_foundation.types import MarketplaceAdapter

ADAPTER_REGISTRY: dict[str, MarketplaceAdapter] = {
    a.adapter_id: a
    for a in (
        amazon_mtr_b2c_v1,
        amazon_mtr_b2b_v1,
        flipkart_sales_report_v1,
        meesho_orders_v1,
        meesho_tcs_sales_v1,
        meesho_tcs_sales_return_v1,
    )
}
