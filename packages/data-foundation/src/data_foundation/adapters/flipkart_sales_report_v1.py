"""flipkart.sales_report.v1 — data-foundation.md §2.3: real seller export, 47 literal columns,
"Header text confirmed; column order unconfirmed."

**Column coverage reflects exactly what's confirmed, not all 47 columns.** The spec quotes
only a subset of the real header text by name: `FK Order ID`/`Line Item ID`/`FSN` (§1.3's
natural-key comment), `Seller Share`/`Bank Offer Share` (the real Sales Report's discount-
bearer split, §1.4 prose — NOT the same-section's registry *table*, whose Flipkart column is
labelled "(superseded sample)" and is therefore not used here), `TDS Rate`/`TDS Amount` (§1.4
prose: "the column says TDS, the money is TCS" — mapped to `TCS`, deliberately not `TDS`, per
that exact correction), and the four dead pre-GST columns that "read zero on all GST-era
orders... Parse and ignore; never treat as tax data" (§1.4 prose). The other ~37 real columns
are unnamed anywhere in the spec and are therefore structurally unknown here, correctly
raising `V-COL-001` until a real export is inspected (§9).
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

_IGNORE = ColumnBinding(
    canonical_field="_ignored_legacy_tax_column",
    component_code=None,
    is_verified=True,  # the *fact* that these are dead/zero on GST-era orders is spec-stated, not guessed
    note="Dead pre-GST column (§1.4): reads zero on all GST-era orders — parsed and discarded, never tax data.",
)

adapter = BaseAdapter(
    adapter_id="flipkart.sales_report.v1",
    marketplace="FLIPKART",
    report_category="TAX",
    format_version="v1",
    date_formats={},  # §2.4 gives only the value format %d-%m-%Y, never a column header
    column_map={
        "FK Order ID": ColumnBinding(canonical_field="order_ref", component_code=None, is_verified=False),
        "Line Item ID": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        "FSN": ColumnBinding(canonical_field="marketplace_item_id", component_code=None, is_verified=False),
        "Seller Share": ColumnBinding(
            canonical_field="component_amount",
            component_code="SELLER_DISCOUNT",
            is_verified=False,
            note="Real Sales Report's seller-borne half of Total Discount (§1.4) — bearer is source data, not inferred.",
        ),
        "Bank Offer Share": ColumnBinding(
            canonical_field="component_amount",
            component_code="PLATFORM_DISCOUNT",
            is_verified=False,
            note="Real Sales Report's non-seller half of Total Discount (§1.4). Mapped to PLATFORM_DISCOUNT "
            "as the closest existing code for a not-seller-funded discount — this specific code choice is "
            "this package's own judgment call, not spec-stated, and should be revisited against a real export.",
        ),
        "TDS Rate": _IGNORE,  # rate has no confirmed pairing target this pass (see base.py note)
        "TDS Amount": ColumnBinding(
            canonical_field="component_amount",
            component_code="TCS",
            is_verified=False,
            note="Column is literally named TDS; the money is TCS at 0.1%, confirmed from real rows (§1.4). "
            "Never mapped to component_code=TDS — that would repeat the exact naming trap the spec warns about.",
        ),
        "Type of tax": _IGNORE,
        "CST Rate": _IGNORE,
        "CST Amount": _IGNORE,
        "VAT Rate": _IGNORE,
        "VAT Amount": _IGNORE,
        "Luxury Cess Rate": _IGNORE,
        "Luxury Cess Amount": _IGNORE,
    },
)
