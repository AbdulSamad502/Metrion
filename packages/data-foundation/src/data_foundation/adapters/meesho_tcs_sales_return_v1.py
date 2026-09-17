"""meesho.tcs_sales_return.v1 — data-foundation.md §2.3: TAX, real export, 15 columns,
"Negative `total_taxable_sale_value` + `cancel_return`."

Confirmed literal columns: `Sub Order No` (join key), `total_taxable_sale_value` (negative on
this file, per §2.3), and `cancel_return` (the return/cancellation date, §2.3). Of the other
~12 real columns, none are named in the spec.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="meesho.tcs_sales_return.v1",
    marketplace="MEESHO",
    report_category="TAX",
    format_version="v1",
    date_formats={"cancel_return": "%d-%b-%y"},  # Meesho's confirmed date value format (§2.4)
    column_map={
        "Sub Order No": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        "total_taxable_sale_value": ColumnBinding(canonical_field="taxable_amount", component_code=None, is_verified=False),
        "cancel_return": ColumnBinding(
            canonical_field="cancel_return_date",
            component_code=None,
            is_verified=False,
            note="Negative total_taxable_sale_value + this date together represent a return/cancellation (§5.4 C4) — "
            "this adapter does not itself derive return_status from it; that composition is the pipeline's job.",
        ),
    },
)
