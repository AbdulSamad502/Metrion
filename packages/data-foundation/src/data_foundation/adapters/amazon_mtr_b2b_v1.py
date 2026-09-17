"""amazon.mtr_b2b.v1 — data-foundation.md §2.3: Amazon SP-API `GST_MTR_B2B`, "Same field set
as B2C, minus the IRN block, plus buyer bill-to identity fields."

Same column-coverage limitation as `amazon_mtr_b2c_v1.py`: only `Amazon Order ID`,
`Shipment Item ID`, and `ASIN` are confirmed literal headers anywhere in the spec. The IRN
block and buyer bill-to fields the spec says B2B adds/removes relative to B2C are never named
individually, so this adapter maps the same minimal set — it is not identical to B2C by
oversight, it is identical because that's the entire confirmed overlap.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="amazon.mtr_b2b.v1",
    marketplace="AMAZON",
    report_category="TAX",
    format_version="v1",
    date_formats={},
    column_map={
        "Amazon Order ID": ColumnBinding(canonical_field="order_ref", component_code=None, is_verified=False),
        "Shipment Item ID": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        "ASIN": ColumnBinding(canonical_field="marketplace_item_id", component_code=None, is_verified=False),
    },
)
