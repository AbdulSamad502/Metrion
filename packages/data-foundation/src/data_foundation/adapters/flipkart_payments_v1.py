"""flipkart.payments.v1 — data-foundation.md §5.1.3: the Flipkart settlement-side adapter.

**No real seller export has ever been inspected for this adapter — unlike `meesho.payments.v1`,
which was built and later verified against a real "Order Payments" tab, this file is built
directly from §5.1.3's secondary-sourced research and nothing else.** §5.1.3 is itself explicit
that its source tier is "lower confidence than [Amazon's]": "No official or primary Flipkart
documentation is publicly available; Flipkart's Reports API is paid and partner-token-only...
The findings below come from third-party reconciliation-tooling sources (the ReconPe glossary,
`gonukkad.com`) — lower-confidence, secondary, and explicitly cited as such." Every binding
below is therefore `is_verified=False`, without exception, and this docstring makes no claim
that any of it is validated. This is the same honest, real-sourced-but-unverified posture this
codebase's very first adapters shipped with, before any real export existed for them either.

**This is the second settlement-side adapter in this codebase** (`source_side="SETTLEMENT"`,
following `meesho_payments_v1.py`'s precedent of overriding `BaseAdapter`'s sales-side default).

## Literal columns bound, and their sourcing

- `"Order ID"` -> `order_ref`. §5.1.3: "`Order ID` is explicitly named by these sources as the
  field used to match settlement rows back to orders" — the one column in this adapter with the
  strongest sourcing (named as a literal join field by two independent secondary sources, per
  §5.1's own row: "corroborated by independent secondary sources"). Still `is_verified=False`:
  corroboration is not primary verification against a real populated export.
- `"Bank Settlement Value"` -> `gross_settlement_amount`. §5.1.3's own quoted dense-header
  evidence that this file is a real payments/bank-reconciliation artifact: "a dense header row
  including `NEFT ID`, `Neft Type`, `Payment Date` and `Bank Settlement Value`... structurally a
  payments/bank-reconciliation file, not a tax invoice." `Bank Settlement Value` is the one
  money-total column named in that quote, and `settlement_line`'s schema (§5.6) has exactly one
  scalar money slot, `gross_settlement_amount` — the same mapping `meesho_payments_v1.py` makes
  for its own settlement-total column (`"Final Settlement Amount"`).
- `"Payment Date"` -> `settlement_date`. Same §5.1.3 quote as above names this as the file's date
  column. Date **value** format declared per `date_formats={"settlement_date": "%d-%m-%Y"}`,
  reusing the exact pattern `data-foundation.md` §2.4 already declares for Flipkart elsewhere
  in this spec (`flipkart.sales_report.v1`'s own citation: "§2.4 gives only the value format
  %d-%m-%Y") — not a new, separately-invented format for this adapter. §2.4's own hazard note
  applies unchanged: `%d-%m-%Y` is ambiguous with `%m-%d-%Y` for day <= 12, and any date that
  fails this declared pattern is a hard `ERROR`, never silently retried under another pattern.

## Fee-line columns

§5.1.3's fee-line paragraph is prose, not a quoted header list: "commission (marketplace fee),
fixed fee, collection fee, shipping fee, return-shipping fee, 'Non-Order Charges' (advertising /
storage), Seller Protection Fund (SPF) credit for warehouse losses, and subvention / rebate
entries... consistent with, and a modest superset of, the Flipkart entries already present in
this spec's `component_code` registry sample (§1.4)." Only one of those eight concepts —
`"Non-Order Charges"` — is itself given in literal quoted form anywhere in §5.1.3. The other
three concepts §5.1.3 explicitly says are *already* in §1.4's registry table (commission, fixed
fee, collection fee, shipping fee) borrow that table's own literal "Flipkart (superseded
sample)" column strings (`"Commission Fee"`, `"Fixed Fee"`, `"Collection Fee"`, `"Shipping
Fee"`) as the best available candidate header text — §1.4 explicitly marks that table's column
as a "superseded sample," so these four bindings carry that caveat explicitly in their notes, on
top of the blanket `is_verified=False` every binding in this file already carries.

- `"Commission Fee"` -> `component_amount` / `COMMISSION` (existing code, reused).
- `"Fixed Fee"` -> `component_amount` / `FIXED_FEE` (existing code, reused).
- `"Collection Fee"` -> `component_amount` / `COLLECTION_FEE` (existing code, reused).
- `"Shipping Fee"` -> `component_amount` / `SHIPPING_CHARGE` (existing code, reused — §1.4's
  registry table already pairs the real Flipkart word "Fee" with the `CHARGE`-kind code
  `SHIPPING_CHARGE`; this adapter does not invent that pairing, it repeats it).
- `"Non-Order Charges"` -> `component_amount` / `NON_ORDER_FEE` (new code, added to
  `component_registry.py` this pass — see that file's own docstring for the kind reasoning).
  This is the one fee-line binding whose header text is itself literally quoted in §5.1.3, not
  borrowed from §1.4's superseded sample table.

## Deliberately left unmapped this pass

- `"Line Item ID"` — data-foundation.md's own instructions for this adapter are explicit that
  "the line-item-level half of the join (`Line Item ID`) remains unverified" per §5.1.3, and
  §5.1.3 itself only says "No source gave a line-item-level key equivalent to Amazon's
  `order-item-code` or Meesho's `sub_order_num`" — it never quotes a literal header string for
  this concept at all, unlike `Order ID`. Binding a column named exactly `"Line Item ID"` would
  therefore not just carry an unverified *mapping* (every binding here does that already) but
  would guess the *header text itself*, which no source in §5.1.3 supplies. Left unmapped for
  that reason — a stronger reason than the ordinary `is_verified=False` caveat every other
  binding in this file carries.
- `"Settlement ID"` — `settlement_line`'s schema (§5.6) has a dedicated `settlement_id` column,
  explicitly noted there as "Flipkart-specific... §5.1's proposed `Order ID + Line Item ID ->
  Settlement ID` key." That note describes an early *proposal*, not a confirmed real column.
  §5.1.3's actual research (the ReconPe/gonukkad sources) never names a "Settlement ID" column
  distinct from "Order ID" anywhere in its findings — the dense-header quote lists `NEFT ID`,
  `Neft Type`, `Payment Date`, `Bank Settlement Value`, and no "Settlement ID". Left unmapped:
  guessing this header string would be inventing a marketplace fact no source in hand supports.
- `"NEFT ID"` / `"Neft Type"` — real, literally-quoted columns (§5.1.3's dense-header evidence
  quote), but there is no `settlement_line` field for a bank-transfer reference number or type;
  they exist in this docstring purely as evidence that the file is a genuine payments/bank-
  reconciliation artifact (§5.1.3's own point in quoting them), not as bindable targets.
- `"return-shipping fee"`, `"SPF credit"` (Seller Protection Fund, warehouse-loss compensation),
  and `"subvention / rebate"` — all three are real fee/credit *concepts* per §5.1.3's prose, and
  each now has its own `component_code` (`RETURN_SHIPPING_FEE`, `SPF_CREDIT`,
  `SUBVENTION_REBATE` respectively — see `component_registry.py`'s docstring this pass), but
  none of the three is given a literal header string anywhere in §5.1.3 — only `"Non-Order
  Charges"` is quoted verbatim among the newly-added concepts. Recording the registry gap now
  (so a future real-export pass has a code ready) without guessing a header to bind it to is the
  same "concept confirmed, header not, leave unmapped" treatment `meesho_payments_v1.py` gives
  `"Meesho Commission Percentage"`.

This is the same designed-for-incompleteness posture `meesho_payments_v1.py` and
`flipkart_sales_report_v1.py` document for their own unmapped columns — not a bug, not an
oversight, and never to be read as this adapter claiming completeness it does not have.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="flipkart.payments.v1",
    marketplace="FLIPKART",
    report_category="SETTLEMENT",
    format_version="v1",
    source_side="SETTLEMENT",
    date_formats={"settlement_date": "%d-%m-%Y"},  # Flipkart's declared date value format,
    # data-foundation.md §2.4 (same pattern flipkart.sales_report.v1 cites for the same
    # marketplace — not separately invented for this adapter).
    column_map={
        "Order ID": ColumnBinding(
            canonical_field="order_ref",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.3: 'Order ID is explicitly named by these sources as the field "
            "used to match settlement rows back to orders' — independent secondary corroboration "
            "(ReconPe, gonukkad.com), not primary verification against a real populated export.",
        ),
        "Bank Settlement Value": ColumnBinding(
            canonical_field="gross_settlement_amount",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.3's dense-header evidence quote names this as the settlement "
            "total column on a real (secondary-sourced) Flipkart payments file; settlement_line's only "
            "scalar money field (§5.6) is gross_settlement_amount.",
        ),
        "Payment Date": ColumnBinding(
            canonical_field="settlement_date",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.3's dense-header evidence quote; date value format declared "
            "per §2.4's existing Flipkart row (%d-%m-%Y), not separately invented.",
        ),
        "Commission Fee": ColumnBinding(
            canonical_field="component_amount",
            component_code="COMMISSION",
            is_verified=False,
            note="data-foundation.md §5.1.3 describes 'commission (marketplace fee)' as a real settlement "
            "fee-line concept; literal header text borrowed from §1.4's registry table's Flipkart "
            "'(superseded sample)' column, since §5.1.3 itself does not quote a literal header for this "
            "concept. Reuses the existing COMMISSION code — not a new one.",
        ),
        "Fixed Fee": ColumnBinding(
            canonical_field="component_amount",
            component_code="FIXED_FEE",
            is_verified=False,
            note="Same sourcing/caveat as 'Commission Fee' above — §5.1.3 names 'fixed fee' as a real "
            "concept, header text borrowed from §1.4's superseded-sample table. Reuses the existing "
            "FIXED_FEE code (also used by meesho.payments.v1 for the equivalent real Meesho concept).",
        ),
        "Collection Fee": ColumnBinding(
            canonical_field="component_amount",
            component_code="COLLECTION_FEE",
            is_verified=False,
            note="Same sourcing/caveat as 'Commission Fee' above — §5.1.3 names 'collection fee' as a real "
            "concept, header text borrowed from §1.4's superseded-sample table. Reuses the existing "
            "COLLECTION_FEE code.",
        ),
        "Shipping Fee": ColumnBinding(
            canonical_field="component_amount",
            component_code="SHIPPING_CHARGE",
            is_verified=False,
            note="Same sourcing/caveat as 'Commission Fee' above — §5.1.3 names 'shipping fee' as a real "
            "concept, header text borrowed from §1.4's superseded-sample table, which already pairs this "
            "exact real Flipkart word ('Shipping Fee') with the CHARGE-kind code SHIPPING_CHARGE.",
        ),
        "Non-Order Charges": ColumnBinding(
            canonical_field="component_amount",
            component_code="NON_ORDER_FEE",
            is_verified=False,
            note="data-foundation.md §5.1.3, literally quoted: \"'Non-Order Charges' (advertising / "
            "storage)\" — the one fee-line concept in §5.1.3 given verbatim header text, not borrowed "
            "from §1.4's superseded sample table. NON_ORDER_FEE added to component_registry.py this pass "
            "(no prior code fit this real concept).",
        ),
    },
)
