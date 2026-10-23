"""meesho.tcs_sales.v1 — data-foundation.md §2.3: TAX, real export, 17 columns, "Per-line
`gst_rate`."

Confirmed literal columns, verified by direct inspection of a real `tcs_sales.xlsx` export
(17 columns: `identifier, sup_name, gstin, sub_order_num, order_date, hsn_code, quantity,
gst_rate, total_taxable_sale_value, tax_amount, total_invoice_value, taxable_shipping,
end_customer_state_new, enrollment_no, financial_year, month_number, supplier_id`):

- `sub_order_num` (join key) — the real header is lowercase snake_case, matching every other
  column on this file. This file never has a column literally named `"Sub Order No"`; an
  earlier pass of this adapter guessed that header (inferred from the return file's naming,
  not verified against a real export) and was wrong. Corrected here.
- `gst_rate` (named directly in the spec) — kept as the source's own decimal string on the
  row, since no rate-to-component pairing is confirmed this pass, see `adapters/base.py`.
- `total_taxable_sale_value` — verified present and correctly mapped; unchanged.

Of the other ~14 real columns, none are named in the spec.
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
    excluded_columns=frozenset({"cancel_return_date"}),  # the return report is this report plus a return date: a file with that column is the return report
    column_map={
        "sub_order_num": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        "gst_rate": ColumnBinding(canonical_field="gst_rate", component_code=None, is_verified=False),
        "total_taxable_sale_value": ColumnBinding(canonical_field="taxable_amount", component_code=None, is_verified=False),
    },
)
