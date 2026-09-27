"""amazon.settlement.v2 — data-foundation.md §5.1.2/§5.1.4: the Amazon settlement-side adapter.

**Source tier.** §5.1.2: Amazon's own SP-API documentation
(`developer-docs.amazon.com/sp-api/docs/report-type-values-settlement`) confirms the melted
`amount-type` / `amount-description` / `amount` three-column consolidation this adapter's
docstring is built around — that part traces to Amazon's own docs. The full V2 identity/
join-key column list, however, comes from a third-party compilation (Intentwise's "Amazon
Settlement Report V1 to V2 Mapping Guide", `help.intentwise.com`) — "a credible secondary
compilation of Amazon's real published schema, not a primary Amazon source." Every binding in
this adapter is therefore `is_verified=False`, without exception — no real Amazon settlement
export has been inspected this pass, matching `flipkart.payments.v1`'s own real-sourced-but-
unverified posture (built from research, not a real file).

**This is the third settlement-side adapter in this codebase** (`source_side="SETTLEMENT"`,
following `meesho_payments_v1.py`'s and `flipkart_payments_v1.py`'s precedent of overriding
`BaseAdapter`'s sales-side default).

## Identity/join fields — ordinary bindings (§5.1.4, "no new architecture")

- `"order-id"` -> `order_ref`. §5.1.2 names `order-id` as the anchor identity/join-key field;
  `settlement_line.order_ref` (§5.6) is the same slot every other settlement adapter binds its
  own order-level join key to.
- `"settlement-id"` -> `settlement_id`. §5.1.4: "a direct match, no gap" — `settlement_line`
  (§5.6) already has a dedicated scalar column with this exact name.
- `"shipment-id"`, `"sku"`, `"marketplace-name"`, `"merchant-order-id"` -> plain string
  canonical fields (`shipment_id`, `sku`, `marketplace_name`, `merchant_order_id`). None of
  these has a destination column on `settlement_line`'s current schema (§5.6 has only
  `order_ref`, `line_ref`, `settlement_id`) — captured into `ParsedRow.canonical_fields`/
  `source_row_json`/`source_row_pairs` with nowhere to persist to a real DB column yet, the
  same "captured now, schema question resolved later" posture `meesho.payments.v1`'s own
  `total_sale_amount` binding already established. Not decided here.
- `"order-item-code"` and `"merchant-order-item-id"` -> **two distinct** plain string
  canonical fields (`order_item_code`, `merchant_order_item_id`). §5.1.4 is explicit that
  picking one as "the" line-level join key would be a guess: "both exist per this source and
  may serve different purposes... nothing inspected here disambiguates them." Both are bound,
  both captured verbatim, and **neither is written into `settlement_line.line_ref`** at parse
  time — that persistence-mapping decision is left to a later checkpoint that has a real,
  validated export to check the join against.
- `"posted-date"` / `"posted-date-time"` — **deliberately left unbound.** §5.1.4: "no real
  Amazon settlement date format has been confirmed... binding it without a declared
  `date_formats` entry is left undone rather than guessed." Both columns therefore fall
  through to `unknown_columns` (`V-COL-001`) if present in a real file, never silently dropped.

## The melted amount triple — capture, not classify (§5.1.4)

Amazon's real Settlement V2 report is melted/long-format: one row per `(order-item,
amount-type)` pair, and the classification Metrion needs lives in the *value* of `amount-type`/
`amount-description`, not in a column header. §5.1.4's decision, implemented verbatim here:

- `"amount-type"` -> `settlement_amount_type`, a plain string canonical field, **no
  `enum_maps` entry** — `_parse_row`'s existing `enum_map is None` fallthrough already captures
  the raw value verbatim, with no `V-ENUM-001` finding (that finding is for a *declared-but-
  incomplete* enumeration; none is declared here at all, per §2.2 rule 4).
- `"amount-description"` -> `settlement_amount_description`, the same treatment, for the same
  reason.
- `"amount"` -> `settlement_amount_value`, a **money-scalar canonical field** via one additive
  entry to `adapters/base.py`'s `_MONEY_SCALAR_FIELDS` frozenset (mirroring exactly how
  `gross_settlement_amount`/`total_sale_amount` were added there for `meesho.payments.v1`).
  Amazon's real `amount` values are signed (e.g. `-45.00` for a fee) — `rupees_to_paise`
  converts via `Decimal`, which parses a leading `-` natively, so the signed conversion needs
  no special-casing here.

**Critically: `component_code=None` for all three of these bindings.** No `ComponentValue` is
ever produced from this triple — `_parse_row` never enters the `ComponentValue`-construction
branch for `amount-type`/`amount-description`/`amount`. The classification step this project
actually needs (mapping an observed `(amount-type, amount-description)` pair to a
`component_code`) is deliberately deferred to a later, separately-reviewed checkpoint, once
real Amazon settlement files exist to observe the actual value space from (§5.1.4, "Why not the
value-dispatch alternative").

## `gross_settlement_amount` is never populated by this adapter (§5.1.4)

Amazon's real per-order-item settlement total has no single-column equivalent — it is the sum
of every `amount`-column value across every row sharing that order-item's rows, and summing
across rows is arithmetic that spans more than one row, which `parse()` may never do (§2.2 rule
2: "pure and streaming... no arithmetic"). No column in this adapter's `column_map` is bound to
`gross_settlement_amount`, and no cross-row aggregation happens inside `parse()`. Every
`ParsedRow` this adapter emits has `canonical_fields.get("gross_settlement_amount")` absent —
not zero, an absent/never-set key, per `CLAUDE.md`'s "missing input is UNAVAILABLE, never a
silent default" rule. Producing a real per-order-item settlement total for Amazon is separate,
later aggregation-stage follow-up work, explicitly not this adapter's job.

This is the same designed-for-incompleteness posture `meesho_payments_v1.py` and
`flipkart_payments_v1.py` document for their own unmapped columns and open schema questions —
not a bug, not an oversight, and never to be read as this adapter claiming completeness or a
validated join it does not have.
"""

from __future__ import annotations

from data_foundation.adapters.base import BaseAdapter
from data_foundation.types import ColumnBinding

adapter = BaseAdapter(
    adapter_id="amazon.settlement.v2",
    marketplace="AMAZON",
    report_category="SETTLEMENT",
    format_version="v2",
    source_side="SETTLEMENT",
    date_formats={},  # §5.1.4: posted-date/posted-date-time deliberately left unbound this pass —
    # no confirmed real Amazon settlement date format exists to declare here.
    column_map={
        "order-id": ColumnBinding(
            canonical_field="order_ref",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.2/§5.1.4: order-id is the anchor identity/join-key field per "
            "Intentwise's secondary compilation of Amazon's real V2 schema — specified-but-unvalidated, "
            "not confirmed against a real populated export.",
        ),
        "settlement-id": ColumnBinding(
            canonical_field="settlement_id",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: 'a direct match, no gap' — settlement_line (§5.6) already "
            "has a dedicated settlement_id scalar column.",
        ),
        "shipment-id": ColumnBinding(
            canonical_field="shipment_id",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: no settlement_line column exists for this yet — captured "
            "into canonical_fields/source_row_json only, same posture as meesho.payments.v1's "
            "total_sale_amount before its own schema question was resolved.",
        ),
        "sku": ColumnBinding(
            canonical_field="sku",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: no settlement_line column exists for this yet — captured, "
            "not persisted, until a separate schema follow-up resolves it.",
        ),
        "marketplace-name": ColumnBinding(
            canonical_field="marketplace_name",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: no settlement_line column exists for this yet — captured, "
            "not persisted, until a separate schema follow-up resolves it.",
        ),
        "merchant-order-id": ColumnBinding(
            canonical_field="merchant_order_id",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: no settlement_line column exists for this yet — captured, "
            "not persisted, until a separate schema follow-up resolves it.",
        ),
        "order-item-code": ColumnBinding(
            canonical_field="order_item_code",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: bound alongside merchant-order-item-id, deliberately NOT "
            "written to settlement_line.line_ref at parse time — §5.1.2 names both as real candidates "
            "for the line-level join key with 'nothing inspected here' to disambiguate them; picking "
            "one would be a guess.",
        ),
        "merchant-order-item-id": ColumnBinding(
            canonical_field="merchant_order_item_id",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: bound alongside order-item-code, same 'neither is line_ref "
            "yet' reasoning — see that binding's note.",
        ),
        "amount-type": ColumnBinding(
            canonical_field="settlement_amount_type",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4's melted-triple capture-not-classify decision: raw value "
            "captured verbatim via _parse_row's enum_map-is-None fallthrough, no enum_maps entry "
            "declared, no component_code, no ComponentValue ever produced from this field.",
        ),
        "amount-description": ColumnBinding(
            canonical_field="settlement_amount_description",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: same melted-triple capture-not-classify treatment as "
            "amount-type — raw value captured verbatim, no classification attempted.",
        ),
        "amount": ColumnBinding(
            canonical_field="settlement_amount_value",
            component_code=None,
            is_verified=False,
            note="data-foundation.md §5.1.4: the melted triple's money value, bound as a money-scalar "
            "canonical_field (via base.py's _MONEY_SCALAR_FIELDS, additive entry this pass) — signed "
            "rupees->paise conversion, e.g. '-45.00' for a fee. component_code=None: no ComponentValue "
            "is ever produced from this field; classification is deferred to a later checkpoint.",
        ),
    },
)
