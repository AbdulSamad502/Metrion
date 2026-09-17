"""meesho.tcs_sales.v1 — data-foundation.md §2.3: TAX, real export, 17 columns, "Per-line
`gst_rate`."

Confirmed literal columns: `Sub Order No` (join key, §2.3), `gst_rate` (§2.3, named
directly — kept as the source's own decimal string on the row, since no rate-to-component
pairing is confirmed this pass, see `adapters/base.py`), and `total_taxable_sale_value` — not
named for *this* file directly, but data-foundation.md §5.4/§2.3 describes
`meesho.tcs_sales_return.v1` as carrying "Negative `total_taxable_sale_value`", which only
makes sense as the negation of the same field in this, its non-return sibling file. Included
on that basis, not invented. Of the other ~14 real columns, none are named in the spec.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="meesho.tcs_sales.v1",
    marketplace="MEESHO",
    report_category="TAX",
    format_version="v1",
    date_formats={},
    column_map={
        "Sub Order No": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        "gst_rate": ColumnBinding(canonical_field="gst_rate", component_code=None, is_verified=False),
        "total_taxable_sale_value": ColumnBinding(canonical_field="taxable_amount", component_code=None, is_verified=False),
    },
)
