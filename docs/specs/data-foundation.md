# Metrion — Data Foundation Specification

**Status:** Draft for review
**Scope:** Canonical financial data model, marketplace adapter contracts, raw-file preservation, validation layer, fee line-item model, settlement reconciliation, report-period model, error and uncertainty handling.

---

## 0. Standing constraints

These govern every section below. They are not negotiable within this document.

1. **Superseded by the marketplace mapping document.** The original synthetic CSVs (`amazon_mtr_sep_2025.csv`, `flipkart_mtr_sep_2025.csv`, `meesho_mtr_sep_2025.csv`) misrepresented structure, not merely values, and are no longer the basis for any adapter. `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf` supplies real column lists from primary marketplace documentation and inspected seller exports. Header text is confirmed; **column order and index positions are not** — validate against a current export before freezing field indices.
2. **No invented fields.** Where a marketplace's real export structure is unknown, this spec marks it `NOT SPECIFIED` rather than guessing a shape. **Amazon settlement is no longer such a case** — it is specified (§0.6, §2.3); what remains unverified is its match keys and real-export validation.
3. **Every uncertain mapping is explicitly flagged** as an unverified assumption and carries that flag through to runtime (§8).
4. **No universal parser.** Each `(marketplace, report_category, format_version)` gets its own adapter (§2).
5. **Amazon requires two report families**: Settlement V2 and Tax (GST_MTR_B2C / GST_MTR_B2B). Both are now specified. They are separate pipelines with different keys and cadences, joined downstream — never merged at ingest.
6. **Amazon settlement is specified** (Settlement V2 flat file). What remains open is the open-ended value space of `amount-type`/`amount-description`, which Amazon does not publish and the normalizer learns from real uploads by design.

---

## 1. Canonical financial data model

### 1.1 Design rules

| Rule | Reason |
|---|---|
| **Money is `BIGINT` paise.** Never float, never `NUMERIC` for transport. | Reference data contains values like `1612.8`; float accumulation drifts, and a drifting margin number is a lost account. |
| **Signed from the seller's perspective.** Revenue positive, deductions negative. | Single most common source of margin sign bugs. Declared once, enforced everywhere. |
| **Grain is the order line item.** | The only grain shared by all three sources: Amazon `Shipment Item ID`, Flipkart `Line Item ID`, Meesho `Sub-Order Number`. |
| **Money components are rows, not columns.** | The three marketplaces decompose fees and discounts entirely differently. Fixed columns cannot represent all three without loss. |
| **Every derived row retains a pointer to its raw source row.** | Any number shown to a seller must be traceable to the original file, byte for byte. |

### 1.2 Entities

```
tenant
└── marketplace_account          (tenant × marketplace × seller identity)
    └── report_file              (immutable raw upload, content-addressed)
        └── ingestion_run        (one parse attempt, versioned by adapter)
            ├── sales_document   (invoice / credit note)
            │   └── sales_line   (canonical grain)
            │       └── line_component   (all money: fees, discounts, taxes, levies)
            ├── settlement_document
            │   └── settlement_line
            │       └── line_component
            └── validation_finding
```

Reconciliation is a separate layer built on top:

```
reconciliation_run
├── reconciliation_match         (sales_line ↔ settlement_line)
└── reconciliation_exception     (variance, orphan, unsettled, duplicate)
```

### 1.3 Core tables (illustrative DDL — specification, not migration)

```sql
-- Immutable raw upload.
report_file (
  id                uuid pk,
  tenant_id         uuid not null,
  marketplace       text not null,          -- AMAZON | FLIPKART | MEESHO
  report_category   text not null,          -- SETTLEMENT | TAX | ORDER_STATUS | ADVERTISING
  content_sha256    char(64) not null,      -- dedupe + integrity
  original_filename text not null,
  byte_size         bigint not null,
  storage_uri       text not null,          -- object store; never mutated
  uploaded_by       uuid not null,
  uploaded_at       timestamptz not null,
  unique (tenant_id, content_sha256)
)

-- One parse attempt. New adapter version => new run; old runs retained.
ingestion_run (
  id                uuid pk,
  tenant_id         uuid not null,          -- CONFIRMED amendment (Category C, data-foundation
                                             -- package): denormalised from report_file.tenant_id
                                             -- at write time. auth.md §7.3's RLS policy needs
                                             -- tenant_id directly on every tenant-owned table;
                                             -- without it here, isolation would depend on a
                                             -- join-based policy against report_file instead of
                                             -- the standard direct-column pattern every other
                                             -- tenant table in this repo already uses.
  report_file_id    uuid not null,
  adapter_id        text not null,          -- e.g. "meesho.tcs_sales.v1"
  adapter_version   text not null,
  status            text not null,          -- PENDING|PARSING|VALIDATED|FAILED|SUPERSEDED
  row_count_read    int,
  row_count_accepted int,
  row_count_rejected int,
  started_at        timestamptz,
  finished_at       timestamptz
)

sales_line (
  id                   uuid pk,
  tenant_id            uuid not null,
  ingestion_run_id     uuid not null,
  marketplace          text not null,
  -- natural keys (nullable: not every source supplies every key)
  order_ref            text,               -- Amazon Order ID / FK Order ID / Meesho Order Number
  line_ref             text,               -- Shipment Item ID / Line Item ID / Sub-Order Number
  invoice_ref          text,
  -- product
  sku                  text,
  marketplace_item_id  text,               -- ASIN / FSN / (Meesho: none observed)
  item_title           text,
  hsn_sac              text,
  quantity             int,               -- CONFIRMED amendment (Category C, data-foundation
                                           -- package): relaxed from `not null`. No adapter in
                                           -- §2.3's registry has a spec-confirmed literal
                                           -- header for this column (unlike order_ref/line_ref/
                                           -- marketplace_item_id, which this file's own comment
                                           -- above names per marketplace) — a NOT NULL
                                           -- constraint would force every real row to either
                                           -- invent a guessed header or fail to insert. Null
                                           -- here means "not yet mapped," not "zero units";
                                           -- calc-engine's billable_quantity() already treats a
                                           -- missing quantity-dependent input as Unavailable,
                                           -- never a silent zero.
  -- money (paise, signed)
  gross_item_amount    bigint,
  taxable_amount       bigint,
  total_invoice_amount bigint,
  currency             char(3) not null default 'INR',
  -- dates (normalised to date; source format declared by adapter, never inferred)
  order_date           date,
  dispatch_date        date,
  invoice_date         date,
  -- classification
  document_type        text,               -- INVOICE | CREDIT_NOTE
  supply_type          text,               -- INTERSTATE | INTRASTATE
  transaction_type     text,
  payment_method       text,               -- PREPAID | COD
  return_status        text,               -- canonical enum; per-source mapping in adapter
  -- provenance
  source_row_number    int not null,
  source_row_json      jsonb not null,     -- verbatim original row
  confidence           text not null       -- VERIFIED | PROVISIONAL | DERIVED | MANUAL  (§7.1)
)
```

### 1.4 `line_component` — the fee line-item model

This is the table that makes three incompatible fee structures representable.

```sql
line_component (
  id               uuid pk,
  tenant_id        uuid not null,
  sales_line_id    uuid,                   -- one of these two is set
  settlement_line_id uuid,
  component_kind   text not null,          -- see enum below
  component_code   text not null,          -- normalised code, see registry below
  source_side      text not null,          -- INVOICE | SETTLEMENT
  amount           bigint not null,        -- paise, signed (seller perspective)
  tax_amount       bigint,                 -- GST charged *on this fee*, where stated
  rate_pct         numeric(7,4),           -- as stated by source, nullable
  -- provenance
  source_column    text not null,          -- ORIGINAL column name, verbatim
  is_verified      boolean not null,       -- false => unverified mapping (§8)
  note             text
)
```

**`component_kind`**
`DISCOUNT` · `FEE` · `CHARGE` · `TAX` · `LEVY`

**`component_code` registry** — normalised codes with observed source columns.
`is_verified = false` for every row in this table until a real export confirms it.

| `component_code` | kind | Amazon (superseded sample) | Flipkart (superseded sample) | Meesho (superseded sample) |
|---|---|---|---|---|
| `COMMISSION` | FEE | *(not separated)* | `Commission Fee` | `Commission Fee` |
| `MARKETPLACE_FEE_GENERIC` | FEE | `Marketplace Fee Amount` | — | — |
| `PLATFORM_FEE` | FEE | `Platform Fee` | — | `Platform Charges / Fees` |
| `FIXED_FEE` | FEE | — | `Fixed Fee` | `Fixed Fee` |
| `COLLECTION_FEE` | FEE | — | `Collection Fee` | `Collection Fee` |
| `PACKAGING_FEE` | FEE | `Packing Fee` | `Packaging Fee` | `Packaging Fee` |
| `LOGISTICS_FEE` | FEE | — | — | `Logistics Fee` |
| `COD_FEE` | FEE | `COD Fee` | — | — |
| `SHIPPING_CHARGE` | CHARGE | `Shipping Charge` | `Shipping Fee` | `Shipping Fee` |
| `GIFT_WRAP_CHARGE` | CHARGE | `Gift Wrap Charge` | — | — |
| `SELLER_DISCOUNT` | DISCOUNT | `Item Discount` | `Seller Discount` | `Seller Discount` |
| `PLATFORM_DISCOUNT` | DISCOUNT | `Item Promotional Discount` | `Flipkart Discount` | `Discount` |
| `CASHBACK_DISCOUNT` | DISCOUNT | — | `Cashback Discount` | `Cashback Discount` |
| `SHIPPING_DISCOUNT` | DISCOUNT | `Shipping Discount` | `Shipping Discount` | — |
| `CGST` / `SGST` / `IGST` / `UTGST` / `CESS` | TAX | `* Amount` | `* Amount` | `* Amount` |
| `TCS` | LEVY | `TCS Amount` | `TCS Amount` | `TCS Amount` |
| `TDS` | LEVY | `TDS Amount` | `TDS Amount` | `TDS Amount` |

**Revised against `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`.** Amazon V2 does not expose named fee columns at all. Every charge arrives as an `amount-type` / `amount-description` / `amount` triple, and **Amazon publishes no closed enumeration of those values.** The `component_code` registry is therefore seeded from observed pairs and extended as new ones appear in real seller data.

Seed pairs confirmed from a real settlement report:

| `amount-type` | `amount-description` | Metrion treatment |
|---|---|---|
| `ItemPrice` | `Principal` | Item revenue |
| `ItemPrice` | `Shipping` | Customer-paid shipping income |
| `ItemFees` | `Commission` | `COMMISSION` (negative) |
| `ItemFees` | `FBAPerUnitFulfillmentFee` | Fulfilment fee (negative) |
| `ItemWithheldTax` | `MarketplaceFacilitatorTax-Principal` | Collected and remitted by Amazon. **Nets to zero — never seller revenue** |
| `Promotion` | varies | Seller-funded discount |
| `ServiceFee` | varies | **Account-level**, no order id — allocate, never join to a product |
| `Adjustment` | varies | Other income or credit. **Not a COGS reduction** |
| `Transfer` | varies | Movement between Amazon accounts. **Neither revenue nor expense** |

**Flipkart resolves discount bearer directly.** The real Sales Report splits `Total Discount` into **`Seller Share`** and **`Bank Offer Share`** — the bearer attribution `deterministic-engine.md` §5.3 requires, available as source data rather than inference.

**Flipkart labels TCS as `TDS Rate` / `TDS Amount`.** Confirmed from real rows at 0.1%. A naming trap: the column says TDS, the money is TCS.

**Flipkart retains dead pre-GST columns** — `Type of tax`, `CST Rate/Amount`, `VAT Rate/Amount`, `Luxury Cess Rate/Amount` — which read zero on all GST-era orders. Parse and ignore; never treat as tax data.

**Meesho fee columns are GST-inclusive by name**: `Fixed Fee (Incl. GST)`, `Warehousing fee (incl GST)`, `Return premium (incl GST)`. These require GST extraction before entering any tax-exclusive calculation.

---

## 2. Marketplace adapter contracts

### 2.1 Principle

One adapter per `(marketplace, report_category, format_version)`. Adapters share an interface, never an implementation. No heuristics that "figure out" which marketplace a file came from beyond an explicit, declared detection step.

### 2.2 Interface

```python
class MarketplaceAdapter(Protocol):
    adapter_id: str            # "meesho.tcs_sales.v1"
    marketplace: Marketplace
    report_category: ReportCategory
    format_version: str

    # Dates are DECLARED, never inferred. See §2.4.
    date_formats: Mapping[str, str]        # canonical_field -> strptime pattern

    column_map: Mapping[str, ColumnBinding]  # source column -> canonical binding
    enum_maps: Mapping[str, Mapping[str, str]]

    def detect(self, sample: FileSample) -> DetectionResult: ...
    def parse(self, f: RawFile) -> Iterator[ParsedRow]: ...
```

```python
@dataclass(frozen=True)
class ColumnBinding:
    canonical_field: str
    component_code: str | None
    is_verified: bool          # False for every binding in v1 (synthetic source)
    note: str | None           # e.g. "Unverified field — likely Shipping City"
```

**Contract rules**

1. `detect()` returns a confidence score and the set of expected-but-missing columns. It never mutates.
2. `parse()` is pure and streaming. It performs **no** validation, **no** arithmetic, **no** inference. Shape only.
3. Unknown columns are **preserved**, never dropped — they land in `source_row_json` and raise `V-COL-001`.
4. An adapter that encounters an unmapped enum value emits the row with `confidence = PROVISIONAL` and a `V-ENUM-001` finding. It does not guess.
5. Adapters are versioned and immutable once released. A mapping correction is a new version.

### 2.3 Adapter registry (v1)

**Revised against `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`** — the synthetic reference files misrepresented the structure, not merely the values. The registry below replaces the earlier synthetic-basis registry entirely.

| `adapter_id` | Category | Basis | Status |
|---|---|---|---|
| `amazon.settlement.v2` | SETTLEMENT | Amazon SP-API `GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2` | **Specified.** Three generic columns: `amount-type`, `amount-description`, `amount` |
| `amazon.mtr_b2c.v1` | TAX | Amazon SP-API `GST_MTR_B2C` | Specified from Amazon documentation |
| `amazon.mtr_b2b.v1` | TAX | Amazon SP-API `GST_MTR_B2B` | Same field set as B2C, minus the IRN block, plus buyer bill-to identity fields |
| `flipkart.sales_report.v1` | TAX | Real seller export, 47 literal columns | Header text confirmed; column order unconfirmed |
| `meesho.orders.v1` | ORDER_STATUS | Real Supplier Panel export | Carries `Reason for Credit Entry` |
| `meesho.payments.v1` | SETTLEMENT | Real Payments workbook | Five tabs: Order Payments, Ads Cost, Referral Payments, Compensation and Recovery, Disclaimer |
| `meesho.tcs_sales.v1` | TAX | Real export, 17 columns | Per-line `gst_rate` |
| `meesho.tcs_sales_return.v1` | TAX | Real export, 15 columns | Negative `total_taxable_sale_value` + `cancel_return` |

**Amazon V1 settlement reports are removed on 11 November 2026.** `GET_V2_SETTLEMENT_REPORT_DATA_XML` and `GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE` must never be implemented — V2 flat file is the only forward path.

**Settlement and tax are two distinct pipelines**, not two views of one file. Different keys (settlement-level vs invoice-level), different cadences, different purposes. They are joined downstream, never merged at ingest.

**Meesho is four files joined on `sub_order_num`**, not one combined file. `Sub Order No` is the primary key — one row per sub-order, never per order.

**Amazon settlement rows may carry no `order-id` at all.** `ServiceFee`, and some `Adjustment` and `Transfer` rows, are account-level charges. The canonical model must permit a null order/SKU key on these and allocate them separately rather than forcing a product-level join. See §1.4.

**Restricted access:** `GST_MTR_B2B` and `GST_MTR_B2C` require a Restricted Data Token at the API level. Under upload-only this is immaterial, but it rules out any future self-serve API path for tax reports.

**Flipkart's Reports API is a paid, partner-token-only service**, not self-serve. This independently validates the upload-only decision; a manual CSV path is the only viable Flipkart route.

**Resolved.** The earlier assumption that Flipkart and Meesho combine invoice and settlement in one file was an artefact of the synthetic samples. Real exports separate them, and the registry above reflects that. The canonical model absorbed the change without alteration — the row-per-component design was already correct.

### 2.4 Date handling

Declared per adapter. Never auto-detected.

| Marketplace | Observed format | Pattern | Hazard |
|---|---|---|---|
| Amazon | `8/26/2025` | `%m/%d/%Y` | **Ambiguous with `%d/%m/%Y` for day ≤ 12.** Silent corruption if inferred. |
| Flipkart | `26-08-2025` | `%d-%m-%Y` | Same ambiguity class. |
| Meesho | `15-Sep-25` | `%d-%b-%y` | Two-digit year; century assumed 2000s. |

Any date that fails its declared pattern is a hard `ERROR`. It is never retried under a different pattern.

---

## 3. Raw-file preservation

### 3.1 Rules

1. **The uploaded bytes are immutable.** Stored once, content-addressed by SHA-256, never rewritten.
2. **Re-parsing is always possible from raw.** When an adapter improves, the fix is a re-run — never a re-upload request to the seller.
3. **Ingestion is idempotent.** Same file + same adapter version = same result. Re-uploading a duplicate (matching `content_sha256`) is detected and reported, not re-ingested.
4. **Parse runs are versioned and additive.** A new run supersedes the previous (`status = SUPERSEDED`); prior results are retained for audit, not deleted.
5. **Every canonical row carries `source_row_json`** — the verbatim original row. This is what makes "why is this number what it is?" answerable down to the source column.
6. **Raw files are retained while the account is active**, because they are the only thing that permits re-derivation. Deletion policy on account closure is deferred to the data-protection spec.

### 3.2 Why this matters here specifically

**Because no adapter mapping has yet been validated against a real export, the first one may break them.** Raw preservation is what turns that from an incident into a re-run.

---

## 4. Validation layer

Sits strictly between parsing and calculation. Nothing reaches the margin engine without passing it.

### 4.1 Severities

| Severity | Effect |
|---|---|
| `ERROR` | Row is quarantined. Excluded from all financial aggregates. Surfaced to the seller. |
| `WARNING` | Row is ingested and included, flagged, and counted in the data-quality report. |
| `INFO` | Recorded for diagnostics only. |

**Policy:** a period containing unresolved `ERROR` rows produces figures marked incomplete, and the CFO agent must disclose the exclusion rather than silently reporting a lower number. This implements the planning-doc rule *"handle incomplete/missing data before giving any recommendation."*

### 4.2 Rule set

Every rule below is derived from a defect actually present in the reference files.

| ID | Rule | Severity | Observed in reference data |
|---|---|---|---|
| `V-TAX-001` | `supply_type = INTERSTATE` ⇒ IGST used, CGST/SGST zero (and inverse) | ERROR | **6 of 40 Amazon rows** marked `Interstate` while charging CGST+SGST. Legally impossible. |
| `V-TAX-002` | `CGST% = SGST%`; tax components sum to `Total Tax Amount` | ERROR | — |
| `V-TAX-003` | Effective GST rate within plausible slab set | WARNING | Amazon row 1: 9% total on HSN 8517. |
| `V-FEE-001` | Where `rate_pct` and `amount` are both present, they reconcile within tolerance | ERROR | Amazon row 1: `Marketplace Fee % = 10`, `Amount = ₹50` on a ₹37,206 item. |
| `V-FEE-002` | Detect candidate duplicate fee lines (equal amount, overlapping semantics) | WARNING | Amazon row 1: `Platform Fee` = `Marketplace Fee Amount` = ₹50. Double-count risk. |
| `V-SUM-001` | Money components sum to the stated document total | ERROR | Amazon `Shipping Charge` ₹50 excluded from `Total Invoice Value`. |
| `V-DATE-001` | All dates parse under the declared format and fall within the report period | ERROR | — |
| `V-DATE-002` | `order_date ≤ dispatch_date ≤ invoice_date` | WARNING | — |
| `V-ID-001` | Required identifiers present for the source's declared grain | ERROR | — |
| `V-ENUM-001` | Enum value present in the adapter's mapping | WARNING | Meesho `Return Status` contains `Delivered`; Amazon uses `Not Returned` / `Returned`. Same column name, different semantics. |
| `V-COL-001` | Unknown / unexpected column encountered | WARNING | Meesho column 28 is literally named `sss`. |
| `V-CUR-001` | Currency is INR | ERROR | V1 is INR-only. |
| `V-QTY-001` | `quantity > 0`, or document is a credit note | ERROR | — |
| `V-SETL-001` | Settlement row references a resolvable sales line | WARNING | — |
| `V-PER-001` | Report period declared and internally consistent | ERROR | Amazon file named `sep_2025` covers 16 Aug – 15 Sep, `GST Filing Month = 8`. |

### 4.3 Output

Each run produces a **Data Quality Report**: counts by severity, per-rule breakdown, quarantined row list with source row numbers, and the resulting confidence level for the period.

### 4.4 `validation_finding` — CONFIRMED (Category C, data-foundation package)

§1.2's entity tree names a `validation_finding` table but no schema was ever defined for it —
a real gap, since §4.3's Data Quality Report cannot be assembled from prose alone. This is the
one row-per-finding table that §4.2's rule table and §4.3's report are both describing:

```sql
validation_finding (
  id                 uuid pk,
  tenant_id          uuid not null,
  ingestion_run_id   uuid not null,
  sales_line_id      uuid,              -- null for a run-level finding (e.g. V-PER-001, which
                                         -- checks the whole report period, not one row)
  rule_id            text not null,     -- e.g. 'V-TAX-001', from §4.2's table
  severity           text not null,     -- ERROR | WARNING | INFO (§4.1)
  message            text not null,
  source_row_number  int,
  created_at         timestamptz not null default now()
)
```

An `ERROR`-severity finding does not delete or omit its `sales_line` row — §3's raw-file
preservation and full-traceability rules apply to quarantined rows exactly as to accepted
ones. Exclusion from financial aggregates (§4.1's stated ERROR effect) is enforced downstream,
at calculation time, by joining `validation_finding` on `sales_line_id` — this is precisely
what `deterministic-engine.md`'s `CanonicalLine.quarantine_rule_ids` field already exists to
carry.

---

## 5. Settlement reconciliation model

**Status: match keys unverified.** The report families are specified for all three marketplaces. What is not yet verified is the **join key** between invoice and settlement rows — known provisionally for Flipkart and Meesho, **UNKNOWN for Amazon** (§5.1). Reconciliation is therefore specifiable everywhere and *runnable* only where the join has been validated against a real export.

### 5.1 Match keys (all unverified)

| Marketplace | Proposed key | Status |
|---|---|---|
| Meesho | `Sub-Order Number` → settlement columns on same row | Unverified — reference file is pre-joined |
| Flipkart | `Order ID` + `Line Item ID` → `Settlement ID` | Unverified — reference file is pre-joined |
| Amazon | **UNKNOWN** | **Cannot be specified without a real settlement report.** |

### 5.2 Outcomes

| Outcome | Meaning |
|---|---|
| `MATCHED_EXACT` | Invoice and settlement agree within zero tolerance |
| `MATCHED_WITHIN_TOLERANCE` | Agree within configured tolerance |
| `VARIANCE_EXCEEDS_TOLERANCE` | **Leak candidate** |
| `UNSETTLED_WITHIN_LAG` | Invoiced, not yet settled, inside expected settlement lag |
| `UNSETTLED_BEYOND_LAG` | **Leak candidate** — overdue |
| `ORPHAN_SETTLEMENT` | Settlement with no matching invoice |
| `DUPLICATE_SETTLEMENT` | Same line settled more than once |

### 5.3 Leak categories

`FEE_OVERCHARGE` · `SHORT_SETTLEMENT` · `MISSING_SETTLEMENT` · `UNEXPECTED_DEDUCTION` · `RETURN_NOT_CREDITED` · `TCS_TDS_MISMATCH` · `DUPLICATE_DEDUCTION`

### 5.4 The core signal

**Evidence corrected.** The original justification cited the synthetic reference file's co-located columns, which §0 and §2.3 retract. The conclusion survives on better evidence: per `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`, Meesho's real Supplier Panel exports carry invoice-side revenue fields (`Fixed Fee (Incl. GST)`, `Warehousing fee (incl GST)`, `Return premium (incl GST)`, `Meesho Commission Percentage`) alongside settlement-side values (`Final Settlement Amount`, and the documented 18-term settlement formula), joinable on `sub_order_num` across the Orders, Payments and TCS files.

**Status: provisional.** Column-level pairing has not been validated against a live export, so the both-sides claim is evidence-backed but unverified (§9).

**That delta is Leak Shield's primary signal**, and the `source_side` column on `line_component` exists specifically to express it:

```
leak_amount = Σ component[SETTLEMENT] − Σ component[INVOICE]   (per component_code, per line)
```

Meesho is therefore the best proof-of-concept target: it is the only source that currently supplies both sides.

### 5.5 Configuration (all values unverified, must not be hardcoded)

| Parameter | Note |
|---|---|
| Variance tolerance | Per marketplace, per component. Expressed in paise **and** basis points. |
| Settlement lag | Per marketplace. Determines `WITHIN_LAG` vs `BEYOND_LAG`. **Requires real data.** |
| Grace period | Buffer before an overdue settlement is reported as a leak. |

Per the planning doc: fee percentages are never hardcoded. All tolerances and lags are configuration, sourced and revised from observed data.

---

## 6. Report-period model

```sql
report_period (
  id               uuid pk,
  tenant_id        uuid not null,          -- CONFIRMED amendment (Category C, data-foundation
                                            -- package) — same reasoning as ingestion_run above:
                                            -- denormalised from report_file.tenant_id, required
                                            -- for auth.md §7.3's direct-column RLS policy.
  report_file_id   uuid not null,
  period_start     date not null,
  period_end       date not null,
  source           text not null,   -- DECLARED_IN_FILE | DERIVED_FROM_ROWS
  declared_filing_month int,
  declared_filing_year  int
)
```

**Rules**

1. **Periods may straddle calendar months.** The Amazon reference file runs 16 Aug – 15 Sep. Filename and calendar month are both unreliable.
2. **Period boundaries come from the file's period fields**, never the filename. Where absent, derive from row dates and set `source = DERIVED_FROM_ROWS`.
3. **P&L allocation uses document date, not report period.** A line dated 28 Aug belongs to August regardless of which report delivered it.
4. **Overlapping uploads are expected.** Deduplicate on natural key + content hash; never double-count.
5. **Gap detection is a product feature.** The seller is told which periods are missing, per marketplace — this directly supports the forecasting data-sufficiency gate.

---

## 7. Error and uncertainty handling

### 7.1 Confidence propagates

Every canonical row and every derived figure carries one of:

| Level | Meaning | Rank |
|---|---|---|
| `VERIFIED` | Mapping confirmed against a real marketplace export | 1 (strongest) |
| `PROVISIONAL` | Mapping derived from superseded sample data, or containing an unverified field | 2 |
| `DERIVED` | Computed under a stated assumption | 3 |
| `MANUAL` | Incorporates a seller-supplied value (`deterministic-engine.md` §7.2) | 4 (weakest) |

**In v1, every row is `PROVISIONAL` at best**, because no mapping has been confirmed against a real export.

Confidence is **monotonic under aggregation**: any total containing a `PROVISIONAL` input is itself `PROVISIONAL`. A figure can never present as more certain than its weakest input.

### 7.2 Unverified field registry

Runtime-visible, not merely a comment.

| Marketplace | Source column | Assumption | Status |
|---|---|---|---|
| Meesho | `sss` | **Moot.** The synthetic file it came from is superseded; no real Meesho export contains this column. Retained here only as a record. | SUPERSEDED |
| Amazon | `Marketplace Fee Type` / `%` / `Amount` | **Superseded.** No such columns exist in Settlement V2; charges arrive as `amount-type`/`amount-description`/`amount`. | SUPERSEDED |
| Amazon | `Platform Fee` vs `Marketplace Fee Amount` | Relationship unknown; may be duplicate representations of one charge | UNVERIFIED |
| Flipkart | Settlement columns co-located with invoice columns | Assumed pre-joined; real exports may separate | UNVERIFIED |
| Meesho | Settlement columns co-located with invoice columns | Same | UNVERIFIED |
| Meesho | `Discount` vs `Seller Discount` vs `Cashback Discount` | Three discount fields; relationship and precedence unknown | UNVERIFIED |
| All | Return-status enum semantics | Amazon uses return state, Meesho appears to use delivery state | UNVERIFIED |

### 7.3 Disclosure

Uncertainty surfaces to the seller rather than being hidden — consistent with the product's *degraded but disclosed* principle:

> *"Based on 38 of 40 rows. 2 rows excluded: interstate supply charged with CGST/SGST (V-TAX-001). Figures are provisional pending data correction."*

### 7.4 Failure modes

| Failure | Behaviour |
|---|---|
| Adapter cannot detect format | Reject at upload with the expected-column diff. No partial ingest. |
| Row fails `ERROR` validation | Quarantine row; continue run; report. |
| >20% of rows quarantined | Fail the whole run; the file is presumed mismatched. Threshold configurable. |
| Adapter version updated | New `ingestion_run` over preserved raw; prior run marked `SUPERSEDED`. |
| Duplicate file uploaded | Detected by `content_sha256`; reported, not re-ingested. |

---

## 8. Open items deferred to later specs

- ~~Exact P&L formula and COGS input path~~ — resolved in `deterministic-engine.md` §1.1–1.2
- ~~GST depth~~ — resolved: management-grade (`deterministic-engine.md` §1.3)
- ~~Tenant isolation mechanism~~ — resolved in `auth.md` §1.4, §7.3
- ~~Expense and cash-flow input paths~~ — resolved in `cfo-agent.md` §6.10 via `manual_adjustment`
- Retention and deletion policy on account closure — **still open** (`auth.md` Q9)

---

## 9. Real Report Validation Required Before Production

**Nothing in this list may be treated as production-ready until validated against a genuine marketplace export.**

### Blocking — feature cannot ship

1. ~~Amazon settlement report structure~~ — **RESOLVED.** Settlement V2 flat file, field list specified from Amazon SP-API documentation. What remains open is the *value space* of `amount-type`/`amount-description`, which Amazon does not publish and which the normalizer learns from real uploads by design. Not a blocker.
2. **Amazon settlement match keys and grain.** The report family is specified (item 1 resolved); the invoice-to-settlement join key is not. Blocks reconciliation *execution* on Amazon, not its specification.
3. **Leak Shield for Amazon.** Blocked on (2) alone. Findings are withheld until the join is validated — not because settlement data is absent.
4. **Amazon two-file upload flow.** The report identity is specified (`amazon.settlement.v2`); cadence and join keys still require a real export.

### Must be validated — mapping likely to change

5. **All three adapter column maps.** Every binding is `is_verified = false`. Real Amazon MTR uses different column names entirely.
6. **Date format declarations.** Amazon `%m/%d/%Y` and Flipkart `%d-%m-%Y` are mutually ambiguous for day ≤ 12. Confirm from a real export before any production ingest.
7. **Meesho `sss` column.** Unverified — likely Shipping City. Not to be renamed until confirmed.
8. **Whether Flipkart and Meesho really combine invoice and settlement** in one export, or ship them separately.
9. **Amazon fee decomposition.** Whether a real report separates commission / closing / fixed fees, or aggregates as the synthetic file does.
10. **`Platform Fee` vs `Marketplace Fee Amount` on Amazon.** Possible duplicate representation — a double-count risk that goes straight into margin.
11. **Meesho's three discount fields** — relationship, precedence, and whether they overlap.
12. **Return-status enum semantics per marketplace.** Amazon appears to encode return state; Meesho appears to encode delivery state.
13. **Settlement lag per marketplace.** Determines when an unsettled line becomes a reportable leak. No basis for a value currently exists.
14. **Variance tolerances per marketplace and component.** Same.
15. **Real file scale.** Reference files are 40 rows. Production sizing, streaming thresholds, and memory behaviour are unvalidated. Planning notes suggest 10,000+ rows per marketplace per period.
16. **Credit-note and return-flow representation.** Reference files contain no credit-note rows; `Document Type` is uniformly `Invoice`.
17. **B2B invoices.** Amazon reference data is entirely `Sale (B2C)`; B2B GST treatment is unexercised.
18. **Multi-state sellers.** All reference rows ship from Telangana. Multi-`Ship From State` behaviour is untested.

### Validation procedure

For each marketplace, on receipt of a real export:

1. Diff real columns against the adapter's `column_map`; record additions, removals, renames.
2. Run the full §4 rule set; a real export should produce materially fewer findings than the synthetic one.
3. Verify arithmetic identities (`V-SUM-001`, `V-FEE-001`) hold on real data.
4. Confirm every entry in the §7.2 unverified registry; promote to `VERIFIED` or correct.
5. Release a new adapter version; re-run ingestion from preserved raw files.
6. Only then may affected figures be promoted from `PROVISIONAL` to `VERIFIED`.
