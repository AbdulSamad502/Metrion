"""ADAPTER_REGISTRY — one entry per `(marketplace, report_category, format_version)` (§2.1).

`meesho.payments.v1` is the first settlement-side adapter (§5.6/§5.4), later verified against a
real "Order Payments" tab export. `flipkart.payments.v1` is the second settlement-side adapter
(§5.1.3) — built entirely from secondary-sourced research (ReconPe, gonukkad.com), with every
binding `is_verified=False` and no real Flipkart settlement export inspected this pass; see its
own module docstring for the full sourcing/gap breakdown. `amazon.settlement.v2` is the third
settlement-side adapter (§5.1.2/§5.1.4) — built, real-sourced-but-unverified (Amazon's own
SP-API docs confirm the melted amount-type/amount-description/amount consolidation; the full
V2 identity/join-key column list traces to a third-party compilation, not a primary Amazon
source), with the melted amount triple deliberately captured, never classified into a
`component_code`, and `gross_settlement_amount` deliberately never populated by this adapter
(a separate, later cross-row aggregation stage's job) — see its own module docstring for the
full breakdown."""

from __future__ import annotations

from data_foundation.adapters.amazon_mtr_b2b_v1 import adapter as amazon_mtr_b2b_v1
from data_foundation.adapters.amazon_mtr_b2c_v1 import adapter as amazon_mtr_b2c_v1
from data_foundation.adapters.amazon_settlement_v2 import adapter as amazon_settlement_v2
from data_foundation.adapters.flipkart_payments_v1 import adapter as flipkart_payments_v1
from data_foundation.adapters.flipkart_sales_report_v1 import adapter as flipkart_sales_report_v1
from data_foundation.adapters.meesho_orders_v1 import adapter as meesho_orders_v1
from data_foundation.adapters.meesho_payments_v1 import adapter as meesho_payments_v1
from data_foundation.adapters.meesho_tcs_sales_return_v1 import adapter as meesho_tcs_sales_return_v1
from data_foundation.adapters.meesho_tcs_sales_v1 import adapter as meesho_tcs_sales_v1
from data_foundation.types import MarketplaceAdapter

ADAPTER_REGISTRY: dict[str, MarketplaceAdapter] = {
    a.adapter_id: a
    for a in (
        amazon_mtr_b2c_v1,
        amazon_mtr_b2b_v1,
        amazon_settlement_v2,
        flipkart_sales_report_v1,
        flipkart_payments_v1,
        meesho_orders_v1,
        meesho_payments_v1,
        meesho_tcs_sales_v1,
        meesho_tcs_sales_return_v1,
    )
}
