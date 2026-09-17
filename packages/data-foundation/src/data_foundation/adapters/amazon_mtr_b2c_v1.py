"""amazon.mtr_b2c.v1 — data-foundation.md §2.3: Amazon SP-API `GST_MTR_B2C`, "Specified from
Amazon documentation."

**Column coverage is minimal, honestly.** The only literal Amazon column names confirmed
anywhere in data-foundation.md are `Amazon Order ID` (order_ref), `Shipment Item ID`
(line_ref), and `ASIN` (marketplace_item_id) — from §1.3's shared natural-key comment. The
§1.4 component_code registry's Amazon column names (`Marketplace Fee Amount`, `Platform Fee`,
`Item Discount`, etc.) are explicitly labelled **"(superseded sample)"** in that table's own
header — i.e. sourced from the deleted synthetic reference file data-foundation.md §0 says
"misrepresented structure, not merely values." Using them here would be exactly the kind of
invented-marketplace-fact this build avoids. Every other column in a real MTR B2C file
(dates, item price, tax amounts, HSN, etc.) is therefore structurally unknown to this adapter
and will correctly raise `V-COL-001` until data-foundation.md §9's validation procedure
supplies the real column list from a real export.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="amazon.mtr_b2c.v1",
    marketplace="AMAZON",
    report_category="TAX",
    format_version="v1",
    date_formats={},  # no date column's literal header is confirmed for this adapter (§2.4
                       # gives only the Amazon *value* format %m/%d/%Y, never a column name)
    column_map={
        "Amazon Order ID": ColumnBinding(canonical_field="order_ref", component_code=None, is_verified=False),
        "Shipment Item ID": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        "ASIN": ColumnBinding(canonical_field="marketplace_item_id", component_code=None, is_verified=False),
    },
)
