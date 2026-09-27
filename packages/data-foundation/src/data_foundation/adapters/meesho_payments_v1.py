"""meesho.payments.v1 — data-foundation.md §2.3: SETTLEMENT, real Payments workbook,
"Five tabs: Order Payments, Ads Cost, Referral Payments, Compensation and Recovery,
Disclaimer."

**Tab scope: "Order Payments" only.** The Payments workbook is multi-tab (§2.3), but
`RawFile`/`FileSample` (`data_foundation/types.py`) model a single flat table, and no spec
text anywhere describes a multi-tab ingestion contract. This adapter therefore covers only
the "Order Payments" tab — the one carrying the settlement total and the join key. Ads Cost,
Referral Payments, Compensation and Recovery, and Disclaimer are structurally out of scope
this pass; inventing a multi-tab contract to reach them would not be grounded in the spec.

**This is the first settlement-side adapter in this codebase** (`source_side="SETTLEMENT"`,
overriding `BaseAdapter`'s sales-side default) — `base.py`'s own inline comment on
`source_side` has been corrected accordingly.

Verified by direct inspection of a real "Order Payments" tab export (43 columns). Two columns
are literally named `"Fixed Fee (Incl. GST)"` — index 17 (the one that is part of the real,
arithmetically-verified 18-term settlement formula that sums to `"Final Settlement Amount"`
on the one real row checked) and index 25 (verified NOT part of that formula). There is also
`"Warehousing fee (inc Gst)"` (index 18, exact casing — part of the formula) and a
separately-worded `"Warehousing fee (Incl. GST)"` (index 26, NOT part of the formula) — two
different exact strings, not a true duplicate, but the same class of ambiguity as the Fixed
Fee pair.

Confirmed literal columns mapped this pass:

- `"Sub Order No"` -> `line_ref` (join key): §5.1/§2.3, "`Sub Order No` is the primary key —
  one row per sub-order, never per order", the same header `meesho_orders_v1.py` already uses
  for the same concept.
- `("Fixed Fee (Incl. GST)", 0)` -> `component_amount` / `component_code="FIXED_FEE"`: the
  occurrence-indexed tuple key (`adapters/base.py`) targets ONLY the first occurrence of this
  header — the formula-included one. `FIXED_FEE` is the exact registered code for Meesho's
  `Fixed Fee` column (§1.4 component_code registry). GST-inclusive by name (§1.4: "Meesho fee
  columns are GST-inclusive by name... require GST extraction before entering any
  tax-exclusive calculation") — that extraction is not performed here (§2.2 rule 2, `parse()`
  is shape-only).

**Two exceptions — mapped to scalars, not components:**

- `"Final Settlement Amount"` -> `gross_settlement_amount` (§5.6's own scalar money field on
  `settlement_line`, not a `line_component` row). This required one additive change to
  `base.py`: its `_MONEY_SCALAR_FIELDS` frozenset now also lists `"gross_settlement_amount"`,
  so it gets the same declared rupees->paise conversion `gross_item_amount`/`taxable_amount`/
  `total_invoice_amount` already get. No existing sales-side adapter ever produces a
  canonical_field named `gross_settlement_amount`, so this changes nothing else.
- `"Total Sale Amount (Incl. Shipping & GST)"` -> `total_sale_amount` (index 15, letter `B` in
  the 18-term formula, verified real). Added per this session's architect-pass finding on
  `data-foundation.md` §5.4: Meesho publishes no real invoice-side fee-declaration document
  (verified against the source PDF's §7A.1 Orders-report column list — no fee columns exist
  there at all), so the §5.4 invoice-vs-settlement component subtraction cannot be computed
  for fee components on real data. The buildable alternative is a rate-card comparison
  (`resolve_fee_reference`, `deterministic-engine.md` §5.14) applied to this order's own base
  amount — `total_sale_amount` is that base. Capturing it now is a small, mechanical,
  low-stakes step; `settlement_line`'s current migration (§5.6) has no column for it yet, so it
  lands in `ParsedRow.canonical_fields`/`source_row_pairs` with nowhere to persist to a real DB
  row until that schema question is separately resolved — not decided here. Second entry in
  `_MONEY_SCALAR_FIELDS`, same additive/no-other-adapter-affected reasoning as
  `gross_settlement_amount` above.

**Deliberately left unmapped this pass** — every one of these is now a verified real column
(not a guess), each excluded for a specific, resolved reason, not the earlier placeholder
"no confirmed code" reasoning (which assumed, wrongly, that the file has only a single
"Warehousing fee (incl GST)" column — it actually has two, differently worded, neither
matching that old guessed spelling):

- The SECOND occurrence of `"Fixed Fee (Incl. GST)"` (index 25) — deliberately not bound to
  `("Fixed Fee (Incl. GST)", 1)` or anything else. It is a real, verified column, but its
  business meaning relative to the formula-included first occurrence is unresolved; guessing
  a second component_code for it is exactly what this project's rules prohibit. It correctly
  falls through to `unknown_columns` (`V-COL-001`) via `adapters/base.py`'s occurrence-aware
  lookup.
- `"Warehousing fee (inc Gst)"` (index 18, single occurrence, exact real casing) — left
  unmapped. No `component_code` has been approved for it; the §1.4 registry's `LOGISTICS_FEE`
  row lists a *different, superseded sample* Meesho header ("Logistics Fee"), and mapping this
  real header to `LOGISTICS_FEE` would be an unconfirmed guess. Still an open decision, not
  resolved by finding the real header.
- `"Warehousing fee (Incl. GST)"` (index 26, the second, differently-worded warehousing
  column) — also left unmapped, same reasoning as the duplicate Fixed Fee: a real column, not
  in the 18-term formula, its business meaning relative to the other warehousing column
  unresolved. Not guessed.
- `"Meesho Commission Percentage"` — a rate, not an amount. Neither `settlement_line` nor
  `ComponentValue` has a bare rate-only slot for it (`ComponentValue.rate_pct` is paired to an
  `amount`, and this column has none stated).

This is the same designed-for-incompleteness behavior `flipkart_sales_report_v1.py`'s
docstring documents for its ~37 unmapped columns — not a bug, not an oversight.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="meesho.payments.v1",
    marketplace="MEESHO",
    report_category="SETTLEMENT",
    format_version="v1",
    source_side="SETTLEMENT",
    date_formats={},  # §2.4 gives only the value format %d-%b-%y, never a column header
    column_map={
        "Sub Order No": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
        ("Fixed Fee (Incl. GST)", 0): ColumnBinding(
            canonical_field="component_amount",
            component_code="FIXED_FEE",
            is_verified=False,
            note="First of two columns literally named 'Fixed Fee (Incl. GST)' on the real export "
            "(index 17) — this occurrence is the one arithmetically part of the settlement formula. "
            "GST-inclusive by name (data-foundation.md §1.4) — requires GST extraction before entering "
            "any tax-exclusive calculation; extraction itself is not performed here (§2.2 rule 2, parse() is "
            "shape-only).",
        ),
        "Final Settlement Amount": ColumnBinding(
            canonical_field="gross_settlement_amount", component_code=None, is_verified=False
        ),
        "Total Sale Amount (Incl. Shipping & GST)": ColumnBinding(
            canonical_field="total_sale_amount",
            component_code=None,
            is_verified=False,
            note="Letter B in the 18-term Final Settlement Amount formula — the fee-base amount a "
            "future rate-card-based variance model would apply a fee_reference rate to (architect-pass "
            "finding, data-foundation.md §5.4). Not yet persisted anywhere — settlement_line's current "
            "migration (§5.6) has no column for it.",
        ),
    },
)
