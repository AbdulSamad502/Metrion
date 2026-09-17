"""meesho.orders.v1 — data-foundation.md §2.3: ORDER_STATUS, real Supplier Panel export,
"Carries `Reason for Credit Entry`."

Confirmed literal columns: `Sub Order No` (§2.3: "the primary key — one row per sub-order"),
`Meesho Order Number` (order_ref, §1.3 comment), `Reason for Credit Entry` (§2.3, named
directly), and `Return Status` (implied by §4.2's `V-ENUM-001` example: "Meesho `Return
Status` contains `Delivered`"). Every other column in a real Orders export is unnamed in the
spec and structurally unknown to this adapter.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="meesho.orders.v1",
    marketplace="MEESHO",
    report_category="ORDER_STATUS",
    format_version="v1",
    date_formats={},  # §2.4 gives only the value format %d-%b-%y, never a column header
    column_map={
        "Meesho Order Number": ColumnBinding(canonical_field="order_ref", component_code=None, is_verified=False),
        "Sub Order No": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        "Reason for Credit Entry": ColumnBinding(canonical_field="reason_for_credit_entry", component_code=None, is_verified=False),
        "Return Status": ColumnBinding(canonical_field="return_status", component_code=None, is_verified=False),
    },
    # §2.2 rule 4: an Amazon-configured adapter uses "Not Returned"/"Returned"; Meesho's own
    # Return Status values (e.g. "Delivered") are a DIFFERENT enum entirely (§4.2 V-ENUM-001) —
    # this package does not invent Meesho's full value set. An EMPTY mapping (not an absent
    # one) for "return_status" means every observed value is unmapped by construction, so
    # every value correctly raises V-ENUM-001 + PROVISIONAL until the real value set is
    # confirmed against an export — never silently passed through as if understood.
    enum_maps={"return_status": {}},
)
