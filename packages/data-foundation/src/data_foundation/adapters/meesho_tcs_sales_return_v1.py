"""meesho.tcs_sales_return.v1 — data-foundation.md §2.3: TAX, real export, "Negative
`total_taxable_sale_value` + `cancel_return`."

Verified by direct inspection of a real `tcs_sales_return.xlsx` export: the real header row
has **18 columns** (not the 15 an earlier, unverified pass of this docstring claimed):
`identifier, sup_name, gstin, sub_order_num, order_date, hsn_code, quantity, gst_rate,
total_taxable_sale_value, tax_amount, total_invoice_value, taxable_shipping,
end_customer_state_new, enrollment_no, cancel_return_date, financial_year, month_number,
supplier_id`.

Confirmed literal columns, corrected against that real header row:

- `sub_order_num` (join key) — the real header is lowercase snake_case, same as
  `meesho_tcs_sales_v1.py`'s fix; this file never has a column literally named
  `"Sub Order No"`.
- `total_taxable_sale_value` — present on this file. **Sign not confirmed negative as a
  universal rule.** An earlier pass of this docstring asserted it is always negative here,
  citing §2.3. The one real return row directly inspected (a 6-row sample) shows it
  **positive** (`+238.14`). That single-sample observation does not establish the sign is
  always positive either — it only corrects the earlier "always negative" claim, which was
  wrong on the one sample checked. `test_meesho_return_negative_taxable_amount` in
  `test_base.py` is unaffected by this correction: it is a unit test of `rupees_to_paise`'s
  handling of a negative numeric string, not an assertion that real Meesho return data is
  always negative, and is left as-is.
- `cancel_return_date` (the return/cancellation date column) — the real header is
  `cancel_return_date`, not the `cancel_return` an earlier, unverified pass guessed. Fixed
  both the `column_map` key and the `date_formats` key below.

Of the other ~14 real columns, none are named in the spec.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="meesho.tcs_sales_return.v1",
    marketplace="MEESHO",
    report_category="TAX",
    format_version="v1",
    date_formats={"cancel_return_date": "%d-%b-%y"},  # Meesho's confirmed date value format (§2.4)
    column_map={
        "sub_order_num": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        "total_taxable_sale_value": ColumnBinding(canonical_field="taxable_amount", component_code=None, is_verified=False),
        "cancel_return_date": ColumnBinding(
            canonical_field="cancel_return_date",
            component_code=None,
            is_verified=False,
            note="total_taxable_sale_value + this date together may represent a return/cancellation (§5.4 C4) — "
            "this adapter does not itself derive return_status from it; that composition is the pipeline's job.",
        ),
    },
)
