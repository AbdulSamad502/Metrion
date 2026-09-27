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

**Meesho fee columns are GST-inclusive by name**: `Fixed Fee (Incl. GST)`, `Warehousing fee (incl GST)`, `Return premium (incl GST)`. These require GST extraction before entering any tax-exclusive calculation. **Exact real header text corrected (§5.1.1):** the real Payments workbook does not use the string `Warehousing fee (incl GST)` verbatim — it has two real, differently-spelled warehousing columns (`Warehousing fee (inc Gst)` and `Warehousing fee (Incl. GST)`), and `Fixed Fee (Incl. GST)` occurs twice as an exact duplicate. This row is retained as the original (slightly imprecise) citation; §5.1.1 has the verified exact strings and column positions.

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
| `meesho.payments.v1` | SETTLEMENT | Real Payments workbook | Five tabs: Order Payments, Ads Cost, Referral Payments, Compensation and Recovery, Disclaimer. **`Order Payments` carries duplicate/near-duplicate column headers — see §5.1.1.** |
| `meesho.tcs_sales.v1` | TAX | Real export, 17 columns | Join key is `sub_order_num` (verified; the adapter previously mapped `Sub Order No`, which does not appear in this file — corrected) |
| `meesho.tcs_sales_return.v1` | TAX | Real export, **18 columns** (was stated as 15) | Join key `sub_order_num` (same correction as tcs_sales.v1); date column is `cancel_return_date` (was stated as `cancel_return`); `total_taxable_sale_value`'s sign is **not confirmed negative** — observed positive on the one real sample inspected (6 rows), the earlier "negative" claim was wrong |

**Amazon V1 settlement reports are removed on 11 November 2026.** `GET_V2_SETTLEMENT_REPORT_DATA_XML` and `GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE` must never be implemented — V2 flat file is the only forward path.

**Settlement and tax are two distinct pipelines**, not two views of one file. Different keys (settlement-level vs invoice-level), different cadences, different purposes. They are joined downstream, never merged at ingest.

**Meesho is four files joined on `sub_order_num`**, not one combined file. `Sub Order No` is the primary key — one row per sub-order, never per order.

**Amazon settlement rows may carry no `order-id` at all.** `ServiceFee`, and some `Adjustment` and `Transfer` rows, are account-level charges. The canonical model must permit a null order/SKU key on these and allocate them separately rather than forcing a product-level join. See §1.4.

**Restricted access:** `GST_MTR_B2B` and `GST_MTR_B2C` require a Restricted Data Token at the API level. Under upload-only this is immaterial, but it rules out any future self-serve API path for tax reports.

**Flipkart's Reports API is a paid, partner-token-only service**, not self-serve. This independently validates the upload-only decision; a manual CSV path is the only viable Flipkart route.

**Resolved.** The earlier assumption that Flipkart and Meesho combine invoice and settlement in one file was an artefact of the synthetic samples. Real exports separate them, and the registry above reflects that. The canonical model absorbed the change without alteration — the row-per-component design was already correct.

**A second, later set of mock CSV files (tenant-supplied, `amazon_mtr_sep_2025.csv` / `flipkart_mtr_sep_2025.csv` / `meesho_mtr_sep_2025.csv` under `Ecom_Analysis/Data/Raw/`) was checked during the §5.1.2/§5.1.3 research pass and explicitly rejected as evidence for any schema or join-key conclusion.** All three reproduce the already-debunked combined-file assumption above — each embeds settlement-shaped columns (`Settlement ID`, `Settlement Date`, `Settlement Amount`, and, on the Meesho mock, fabricated columns such as `Settlement Commission` / `Settlement Logistics` / `Settlement TCS` / `Settlement TDS` / `Settlement Net Amount` with no counterpart in the real, verified Payments workbook of §5.1.1) directly inside a tax-invoice row. The Amazon mock additionally uses named fee columns (`Marketplace Fee Type` / `%` / `Amount`) — the shape §7.2 already marks `SUPERSEDED` relative to the real, confirmed `amount-type` / `amount-description` / `amount` triple. As a further, independent check, the mock files were run through the real, already-built sales-side adapters (`amazon.mtr_b2c.v1`, `flipkart.sales_report.v1`); neither mock file's headers matched the adapters' real documented column names at all (e.g. the real Amazon adapter expects the literal header `Amazon Order ID`, the mock has `Order ID`; the real Flipkart adapter expects `FK Order ID` / `Seller Share` / `Bank Offer Share`, present in none of the mock's columns), and both adapters correctly reported the mismatches as `unknown_columns` rather than silently mis-mapping anything — the "never guess" contract (§2.2 rule 3) held. **This is recorded so a future reader does not wonder whether these files were overlooked: they were inspected and deliberately excluded, not missed.** None of §5.1.2's or §5.1.3's findings are informed by these files' structure.

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

**Status: match keys mixed.** The report families are specified for all three marketplaces. The invoice-to-settlement **join key** is now confirmed real for Meesho; for Flipkart it remains provisional, though the `Order ID` component is now corroborated by independent secondary research (§5.1.3); for Amazon the settlement *field list* is confirmed real and a join-key candidate is now named from secondary research (§5.1.2), but unvalidated. Reconciliation is therefore specifiable everywhere and *runnable* against real data only where the join has been validated — that is Meesho only, per `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`. Neither the Amazon nor the Flipkart research (§5.1.2, §5.1.3) upgrades either marketplace to *runnable* — both remain research-grounded candidates, blocked on a real populated export.

### 5.1 Match keys

| Marketplace | Proposed key | Status |
|---|---|---|
| Meesho | `sub_order_num` — invoice and settlement rows joined on this key | **VERIFIED as a real join key**, confirmed across four independently-inspected real export files for the same seller account: Orders report (PDF §7A.1), Payments workbook (PDF §7A.2), TCS_Sales (PDF §8.1, ~2.28M real rows) and TCS_Sales_Return (PDF §8.2). Per the PDF's closing "Final decision" section: *"Meesho is implemented from real, verified Supplier Panel exports — Orders, Payments, TCS_Sales and TCS_Sales_Return — joined on sub_order_num."* **The 18-term Final Settlement Amount formula's letter-to-column mapping is now RESOLVED** — see §5.1.1, verified against a real seller's Payments workbook export (`meesho_PREVIOUS_PAYMENT_2026-01-01_2026-01-31`, Jan 2026, tenant-supplied) and arithmetically reproduced against a real settled row. **New open item found during that same verification:** the "Order Payments" tab carries duplicate/near-duplicate column headers not previously known — see §5.1.1. |
| Flipkart | `Order ID` join field now corroborated by independent secondary sources (see §5.1.3); `Line Item ID` half of the key and the overall join mechanism remain unverified | **Partially corroborated, still unvalidated.** Reference file is pre-joined; no real populated Flipkart settlement export has been inspected. Only the `Order ID` component of this row's proposed key has independent secondary support — `Line Item ID` is unchanged from "unverified." |
| Amazon | Candidate identity fields real: `order-id`, `merchant-order-id`, `order-item-code`, `merchant-order-item-id`, `sku`. Most likely real join-key pair now named: `order-id` + `order-item-code` (or `merchant-order-item-id`) — see §5.1.2. | **Field list real; join-key candidate named from a credible secondary compilation; still unvalidated against a real populated export.** Amazon's V2 settlement field list is independently verified from Amazon's own SP-API developer docs (PDF §3.1) and includes real order/line identity fields. §5.1.2 adds a secondary-sourced (not Amazon-primary) compilation naming the two most plausible join-key candidates. This moves the join key from *unspecified* to *specified-but-unvalidated* — it is still not validated against a real populated export, and remains a candidate, not a confirmed key. |

### 5.1.1 Meesho Final Settlement Amount — resolved letter mapping, and a new duplicate-header finding

**Source of verification.** A real seller's Meesho export (`meesho_PREVIOUS_PAYMENT_2026-01-01_2026-01-31`, January 2026, tenant-supplied — not the PDF's SS Digital India account, a second independent real account) was inspected directly, sheet by sheet, header row and formula-letter row read verbatim. The `Order Payments` tab's own row 2 (a formula-letter annotation row Meesho includes in the export itself) states each column's role in the settlement formula — this was not inferred, it was read directly from the file. The mapping below was then cross-checked arithmetically against a real settled row: `B+C+G+H+I+L+Q+R+S+T+U+V+W+Y+AA+AD+AF+AX` computed from that row's real values equals that row's real `Final Settlement Amount` cell exactly (`195.00 + 0 + 0 + 0 − 68.74 + 0 − 0.95 + 0 + 0 − 0.19 + 0×8 = 125.12`, matching the file's own stated total).

| Letter | Real column | Letter | Real column |
|---|---|---|---|
| A | Product GST % | S | Recovery |
| B | Total Sale Amount (Incl. Shipping & GST) | T | TDS |
| C | Total Sale Return Amount (Incl. Shipping & GST) | U | Return premium (incl GST) |
| F | Meesho Commission Percentage | V | Return premium (incl GST) of Return |
| G | Meesho Commission (Incl. GST) = −(B+C)×F | W | GST Compensation (PRP Shipping) |
| H | Return Shipping Charge (Incl. GST) | X | TDS Rate % |
| I | Shipping Charge (Incl. GST) | Y | Claims |
| J | Other Support Service Charges (Excl. GST) | AA | Meesho mall platform fee (Incl. GST) |
| K | Waivers (Excl. GST) | AC | Fixed Fee (Incl. GST) — **duplicate header, see below; NOT in the formula** |
| L | Net Other Support Service Charges = J+K | AD | Fixed Fee (Incl. GST) — **duplicate header, see below; IS in the formula** |
| P | GST on Net Other Support Service Charges = L×18/100 | AF | Warehousing fee (inc Gst) — IS in the formula |
| Q | TCS = −1% of (B+C+U+V)/(1+A) | AG | Warehousing fee (Incl. GST) — a second, differently-worded warehousing column; NOT in the formula |
| R | Compensation | AX | Meesho gold platform fee (Incl. GST) |

**New finding: duplicate/near-duplicate column headers.** The `Order Payments` tab carries a column literally named `Fixed Fee (Incl. GST)` **twice** (once at letter `AD`, in the formula; once at letter `AC`, not in the formula) — genuinely identical header text for two columns with different financial meaning. It separately carries two *differently*-worded warehousing columns (`Warehousing fee (inc Gst)`, letter `AF`, in the formula; `Warehousing fee (Incl. GST)`, letter `AG`, not in the formula) — not an exact-text duplicate, but the same class of ambiguity, and neither string exactly matches this document's earlier §1.4 citation of `Warehousing fee (incl GST)`, which does not appear verbatim in the real file at all.

**Status of the non-formula duplicates (`AC`, `AG`).** Their business meaning relative to their formula-included counterparts is **not resolved by this verification** — the real export confirms they exist and are excluded from the settlement total, not what they represent. No `component_code` is assigned to either in this pass (see the adapter architecture note below); this remains an explicit open question, not a guess.

**Adapter architecture consequence.** `packages/data-foundation`'s adapter contract (`ColumnBinding` keyed by header string) could not previously represent two same-named columns at all — a real gap this finding exposed, not something anticipated in the original design. Resolved via occurrence-indexed column binding (`(header, occurrence_index)` keys, backward-compatible with every existing single-occurrence adapter) — implementation in `packages/data-foundation/src/data_foundation/adapters/base.py`, not restated here; this document records the data fact, that package's own code records the parsing mechanism.

### 5.1.2 Amazon settlement join-key research (secondary-sourced, not primary-verified)

**Source tier.** Amazon's own SP-API documentation (`developer-docs.amazon.com/sp-api/docs/report-type-values-settlement`) re-confirms the `amount-type` / `amount-description` / `amount` three-column consolidation already recorded above — this part traces to Amazon's own docs. Amazon's documentation does not, however, give the full V2 column list in one place. For that, a third-party compilation — Intentwise's "Amazon Settlement Report V1 to V2 Mapping Guide" (`help.intentwise.com`) — was consulted. **This is a credible secondary compilation of Amazon's real published schema, not a primary Amazon source, and is cited as such.**

That compilation lists, as identity/join-key fields present in V2: `order-id`, `order-item-code`, `shipment-id`, `sku`, `merchant-order-id`, `merchant-order-item-id`. It also lists passthrough fields identical between V1 and V2: `settlement-id`, `settlement-start-date` / `settlement-end-date`, `deposit-date`, `total-amount`, `currency`, `transaction-type`, `adjustment-id`, `marketplace-name`, `fulfillment-id`, `posted-date` / `posted-date-time`, `quantity-purchased`, `promotion-id`.

**What this resolves.** `order-id` paired with `order-item-code` (or possibly `merchant-order-item-id`) is now named as the *most likely* real join key from `amazon.settlement.v2` back to `sales_line`'s `order_ref` / `line_ref`. This is a reasoned, sourced conclusion — not a guess — and it moves item 2 of §9's blocking list from "join key not specified at all" to "join key specified as a candidate, execution still blocked on real-file validation."

**What this does not resolve, precisely stated.** This is **not** the same as validating the key against a real file. §9 item 2's own distinction between *specification* and *execution* still applies in full: this finding moves the join key from *unspecified* to *specified-but-unvalidated*, not to *validated*. Specifically still open:

- Whether `order-item-code` or `merchant-order-item-id` is the actually-correct match — both exist per this source and may serve different purposes (e.g. one order-scoped, one item-scoped); nothing inspected here disambiguates them.
- The real, undocumented value space of `amount-type` / `amount-description` — Amazon publishes no closed enum (already noted above; unchanged by this finding).
- Whether a real file's `order-id` reliably round-trips against `sales_line.order_ref` given the already-documented behaviour (§1.4, §2.3) that some settlement rows — `ServiceFee`, some `Adjustment` and `Transfer` rows — carry **no** `order-id` at all. That behaviour interacting with this specific candidate join has not been examined against real data.

### 5.1.3 Flipkart settlement schema research (secondary-sourced, lower confidence than 5.1.2)

**Source tier — lower confidence than the Amazon research above.** No official or primary Flipkart documentation is publicly available; Flipkart's Reports API is paid and partner-token-only (§2.3, already noted). The findings below come from third-party reconciliation-tooling sources (the ReconPe glossary, `gonukkad.com`) — lower-confidence, secondary, and explicitly cited as such. None of this traces to a Flipkart-authored document, unlike part of the Amazon finding above.

**Independent corroboration that settlement and tax/invoice are genuinely separate files.** This spec already concluded (§2.3, "Resolved" note) that the earlier combined-file assumption was an artefact of the synthetic samples, and that real Flipkart exports separate invoice and settlement. The sources consulted here describe the settlement report independently as its own artefact: a dense header row including `NEFT ID`, `Neft Type`, `Payment Date` and `Bank Settlement Value`, roughly 76 columns, one row per order-or-order-event (sale / return / commission-adjustment / promotional-adjustment) — structurally a payments/bank-reconciliation file, not a tax invoice. This is **independent secondary corroboration of an already-held conclusion**, not new proof standing alone — it strengthens confidence in an existing finding, it does not establish a new one.

**Join field.** `Order ID` is explicitly named by these sources as the field used to match settlement rows back to orders. No source gave a line-item-level key equivalent to Amazon's `order-item-code` or Meesho's `sub_order_num`. Accordingly, §5.1's Flipkart row above has been updated to reflect that the `Order ID` half of the proposed key is now corroborated by independent secondary sources — the `Line Item ID` half, and the overall join mechanism (how a settlement row that may span multiple line items resolves to one), remain unverified. This is a partial, not a whole-row, confidence upgrade.

**Fee-line columns (secondary-sourced).** The same sources describe settlement fee lines as: commission (marketplace fee), fixed fee, collection fee, shipping fee, return-shipping fee, "Non-Order Charges" (advertising / storage), Seller Protection Fund (SPF) credit for warehouse losses, and subvention / rebate entries. This is consistent with, and a modest superset of, the Flipkart entries already present in this spec's `component_code` registry sample (§1.4) — no contradiction found, only additional candidate line types not yet in the registry.

**What remains open.** All of the above is secondary-sourced and unvalidated against a real populated Flipkart settlement export. No real Flipkart settlement file has been available this session (§9 item 8 remains open, not resolved) — this research narrows the shape of what to expect, it does not confirm it.

### 5.1.4 `amazon.settlement.v2`'s melted amount triple — adapter design decision (capture, not classify)

**The problem, precisely.** Every other adapter in this codebase (§2.2's `column_map` contract, `adapters/base.py`'s `_parse_row`) classifies a `ComponentValue`'s `component_code` from a **column name** — a fee amount lives under a column literally named `Fixed Fee (Incl. GST)`, `Commission`, etc., and the header itself carries the business meaning. Amazon's real Settlement V2 report (§2.3, §5.1.2) does not have this shape. It is melted/long-format: one row per `(order-item, amount-type)` pair, and the classification Metrion needs lives in the **value** of the `amount-type` (and `amount-description`) column on that row, not in a column header — e.g. a row with `amount-type="ItemFees"`, `amount-description="Commission"`, `amount="-45.00"` is a commission charge, but nothing about the header `amount-type` says so; only its per-row value does. Compounding this, §5.1.2 and §0.6 already establish that `amount-type`/`amount-description`'s real value space is **not published anywhere** by Amazon and is not yet observed from any real Metrion-side export — "the normalizer learns from real uploads by design." `adapters/base.py`'s `column_map`/`ColumnBinding` mechanism has no way to key a `component_code` off a cell value at all today, and even if it did, there is currently no real, confirmed value space to key it against.

**Decision: capture as an uninterpreted fact, never a `ComponentValue`.** `amount-type`, `amount-description` and `amount` are each bound as **ordinary, plain `column_map` entries** — no new architecture, no new `ParsedRow` field, no change to `ComponentValue`'s shape:

- `amount-type` -> a plain string `canonical_field` (e.g. `settlement_amount_type`), **no `enum_maps` entry**. `_parse_row`'s existing fallthrough (`enum_map is None` -> `canonical_fields[canonical_field] = raw_value or None`) already does exactly the right thing here: the raw value is captured verbatim, with no attempt at classification and no `V-ENUM-001` finding (that finding is for a *declared-but-incomplete* enumeration — deliberately not applicable here, because no enumeration is declared at all, per §2.2 rule 4's own "does not guess").
- `amount-description` -> the same treatment, a second plain string `canonical_field` (e.g. `settlement_amount_description`), for the same reason.
- `amount` -> a **money-scalar `canonical_field`** (e.g. `settlement_amount_value`), via one additive entry to `adapters/base.py`'s `_MONEY_SCALAR_FIELDS` frozenset — the same, already-precedented pattern used to add `gross_settlement_amount` and `total_sale_amount` for `meesho.payments.v1` (`adapters/base.py`'s own comment on that set). This gets the declared rupees-to-paise conversion, signed (Amazon's real `amount` values are signed, e.g. `-45.00` for a fee), and nothing more — no summing, no derivation.

Critically: **no `component_code`, no `component_kind`, and no `ComponentValue` is ever produced from this triple.** `binding.component_code` stays `None` for all three bindings, so `_parse_row` never enters the `ComponentValue`-construction branch for them. The classification step this project actually needs — mapping an observed `(amount-type, amount-description)` pair to a `component_code` — is deliberately deferred to a later, separately-reviewed checkpoint, once real Amazon settlement files exist to observe the actual value space from. This keeps `parse()` "pure, shape-only" (§2.2 rule 2) exactly as written: it captures a real fact (this row said `ItemFees`/`Commission`/`-45.00`) without pretending to know what that fact means financially.

**Why not the value-dispatch alternative.** The alternative considered was extending `ColumnBinding`/`column_map` to support a `(column_name, expected_value) -> ColumnBinding` binding shape, so a future checkpoint could map specific `amount-type` values straight to `component_code`s without touching `base.py` again. This was rejected for this pass: it is real architecture work today for a capability that has **nothing to bind yet** — no real `amount-type`/`amount-description` value has been observed from an actual Metrion-side Amazon export (§5.1.2's seed pairs are themselves secondary-sourced, from `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf`, not a real seller file this codebase has inspected). Building the dispatch mechanism now would mean designing it against value strings this project cannot yet confirm are correct — the same "invent nothing, defer explicitly" posture already applied to the Meesho duplicate-column pair (§5.1.1, "no `component_code` is assigned to either in this pass"), `hsn_gst_reference`'s schema gap (G1), and `AnomalyConfigurationGap` (E2). Capture-not-classify defers *only* the classification step, on data this project already knows it can capture correctly today; value-dispatch would additionally require guessing the shape of a mapping mechanism ahead of the data that would exercise it. If a real Amazon export later shows `amount-type`/`amount-description` pairs are numerous enough, or vary enough per row, that per-value dispatch inside `column_map` becomes the right mechanism, that is a decision for the checkpoint that has real values to design against — not this one.

**Identity/join fields — ordinary bindings, no new architecture.** Per the task that produced this subsection, the following are plain named columns with fixed meaning in Amazon's real schema (§5.1.2) and bind exactly like every other adapter's `column_map` entries, with no melted-format complication:

- `order-id` -> `order_ref` (mirrors `settlement_line.order_ref`, §5.6 — the same slot Meesho's `Sub Order No` join key occupies conceptually, though Amazon's real key is `order-id`, not `sub_order_num`).
- `shipment-id`, `sku`, `marketplace-name`, `merchant-order-id` -> plain string canonical fields. None of these has a destination column on `settlement_line`'s current schema (§5.6 has `order_ref`, `line_ref`, `settlement_id`, no `sku`/`shipment_ref`/`marketplace_name` columns) — captured into `ParsedRow.canonical_fields`/`source_row_json` with nowhere to persist to a real DB column yet, the same "captured now, schema question resolved later" posture `meesho.payments.v1`'s `total_sale_amount` already established (`adapters/base.py`'s own comment on that field). Not decided here; a real, separate schema follow-up.
- `settlement-id` -> `settlement_id`, which already exists as a named scalar column on `settlement_line` (§5.6) — a direct match, no gap.
- `posted-date` (or `posted-date-time`) is the candidate `settlement_date` source, but no real Amazon settlement date **format** has been confirmed the way §2.4 confirms one for Amazon's tax report (`%m/%d/%Y`) — binding it without a declared `date_formats` entry is left undone rather than guessed; this is an explicit, separate gap, not resolved by this subsection.

**`order-item-code` vs. `merchant-order-item-id` — both bound, neither chosen as "the" line-level join key yet.** §5.1.2 already names this as a genuinely unresolved ambiguity: both fields are real, and "may serve different purposes (e.g. one order-scoped, one item-scoped) — nothing inspected here disambiguates them." Binding only one would be a guess; binding neither would discard a real, confirmed-to-exist column for no reason. The decision here is to bind **both**, as two distinct, ordinary plain-string `canonical_field`s (e.g. `order_item_code` and `merchant_order_item_id`) — capturing both real values verbatim, exactly as they appear, without picking a winner. Neither is written into `settlement_line.line_ref` at parse time. Which of the two (if either, or whether `settlement_line` needs to grow a second nullable join-key column to hold both) actually becomes the value that `reconcile()`'s matching logic (`calc_engine.api.reconcile`, currently Meesho-only per its own module docstring, "this function's matching logic is Meesho-shaped for now, not marketplace-generic") uses for Amazon is a persistence-mapping decision for the checkpoint that builds the real adapter and validates the join against a real populated export (§5.1.2's own "specified-but-unvalidated" status is unchanged by this subsection) — not decided here, and not guessed.

**Consequence for `gross_settlement_amount` (§5.6) — real and structural, not an oversight.** `settlement_line.gross_settlement_amount` is a single scalar per settlement line. For Meesho, `meesho.payments.v1` populates it directly from one column, `"Final Settlement Amount"`, because that file states the per-sub-order total directly. Amazon's real per-order-item settlement total has no equivalent single column — it is the **sum of every `amount`-column value across every row sharing that order-item's `amount-type` rows** (§5.1.2's melted-row structure; a real order-item's settlement total is spread across as many rows as it has distinct `amount-type` charges). Summing across rows is arithmetic that spans more than one row, which `parse()` is not permitted to do (§2.2 rule 2: "pure and streaming... no arithmetic"; each `_parse_row` call sees exactly one row and nothing else). **`gross_settlement_amount` therefore cannot and will not be populated by `amazon.settlement.v2`'s `parse()` step at all** — every `ParsedRow` it emits will have `canonical_fields["gross_settlement_amount"]` absent (not zero — an absent/never-set key, the same "missing input is `UNAVAILABLE`, never a silent default" rule `CLAUDE.md` states for money generally). Producing a comparable per-order-item settlement total for Amazon requires a **separate, later aggregation stage** — grouping captured `settlement_amount_value` facts by the resolved order-item join key (once §5.1.2's join-key ambiguity above is resolved against a real file) and summing them — that stage is explicitly named here as real, necessary, separate follow-up work. It is not this adapter's job, not this checkpoint's job, and its exact location (a post-parse normalization step, or something `reconcile()`/a settlement-ingestion pipeline stage does before persisting `settlement_line` rows) is not decided here.

### 5.1.5 Extending `reconcile()` to Amazon and Flipkart — design decision (this session, join key + amount-gap handling)

`calc_engine.api.reconcile.reconcile()`'s own module docstring today is explicit that its matching is "Meesho-shaped for now, not marketplace-generic," and correctly refuses to invent a fake multi-marketplace join-key abstraction for keys that were never validated. This subsection is the design for extending it — it does **not** change §5.1's status table for Amazon/Flipkart (both remain **specified-but-unvalidated**); it decides how `reconcile()` behaves when pointed at them anyway, honestly.

**1. The join-key field, per marketplace — a lookup, not new architecture.** `reconcile()` gains a small, explicit `(marketplace -> join_key_field)` table. This is the only change `reconcile()` itself needs for point 1 below; none of `calc_engine.formulas.leak`'s pure functions (`resolve_match_candidates`, `classify_variance`, `classify_settlement_lag`, `should_report_unsettled_as_leak`) reference a marketplace-specific field name today — they already operate on pre-extracted scalars or pre-resolved candidate dicts, so they need no change for this. `is_duplicate_settlement` is the one exception; see point 4.

| Marketplace | Join key field `reconcile()` uses | Grain | Why |
|---|---|---|---|
| Meesho | `line_ref` (`sub_order_num`) | Line-item | Unchanged. §5.1's VERIFIED key. |
| Flipkart | `order_ref` (`Order ID`) only | **Order**, not line-item | `flipkart.payments.v1` binds only `order_ref` (§5.1.3) — no line-item candidate is captured by this adapter at all. `settlement_line.settlement_id` (§5.6's comment: "Flipkart-specific... proposed `Order ID + Line Item ID -> Settlement ID` key") remains unbound by the real adapter and unpopulated — it cannot be used for matching until a real export names a line-item column and the adapter is amended to bind it. That is separate, later adapter work, not decided here. |
| Amazon | `order_ref` (`order-id`) only | **Order**, not line-item | `amazon.settlement.v2` captures **two** real line-item candidates (`order_item_code`, `merchant_order_item_id`, §5.1.4) but persists **neither** to `settlement_line.line_ref` — §5.1.4 explicitly defers that choice to "the checkpoint that builds the real adapter and validates the join against a real populated export." `reconcile()` cannot match on a value that was never written to a column it reads via `settlement_repo`. Amazon is therefore order-grain **today**, as a direct consequence of what is actually persisted, not a judgement that `order_ref` is "the right" key — and it does not foreclose a future `settlement_line` schema change to carry one of the two item-level fields once §5.1.4's ambiguity resolves against a real export. |

**Consequence of order-grain matching for Amazon/Flipkart, stated plainly.** A real Amazon or Flipkart order commonly has more than one line item. Multiple `sales_line` rows can legitimately share one `order_ref`. Under `resolve_match_candidates`'s existing, unchanged rules (§5.2, C3), a settlement row whose join key is `order_ref` will resolve to a genuine `Collision` (`AMBIGUOUS_MATCH`) far more often for Amazon/Flipkart than it ever does for Meesho's line-grain key — this is an expected, structural consequence of order-grain matching against a multi-item order, **not a bug and not evidence the key is wrong.** It is a real cost of matching at a coarser grain than the data's true grain, and it will visibly inflate `AMBIGUOUS_MATCH` volume for these two marketplaces relative to Meesho. Nothing in this design papers over that; `deterministic-engine.md` §5.12.2 (confidence) and this fact together are why an Amazon/Flipkart `AMBIGUOUS_MATCH` must never be presented with the same weight as a Meesho one.

**2. Amazon's missing `gross_settlement_amount` — skip, never fabricate, mirroring Decision A's own precedent.** `reconcile.py`'s existing "Decision A" (its own docstring) already establishes the project's posture for a real amount-gap: skip the pair, count it, never default to zero. This design extends that same posture explicitly to Amazon's structural gap (§5.1.4): `amazon.settlement.v2` never populates `gross_settlement_amount` — every Amazon `settlement_line` row has this column absent/`None`. `reconciliation_exception.amount_paise` (§5.9) is `NOT NULL`, so a settlement-row-driven exception (`ORPHAN_SETTLEMENT`, `AMBIGUOUS_MATCH`, `DUPLICATE_SETTLEMENT`) can never honestly be persisted for an Amazon settlement row today — there is no real value to put in that column, and `0` would misrepresent an unknown amount as a known zero-value leak. `reconcile()` must therefore check `gross_settlement_amount is None` **before** attempting to mint any of these three exception types, and where `None`, skip persisting the row entirely and count it in a new, disclosed counter (e.g. `amount_unavailable_count` on `ReconcileResult`, mirroring the existing `dates_missing_count` precedent) — quarantine-and-disclose, never a guessed amount, never a silently dropped row.

Amazon's per-`component_code` variance path (`reconciliation_match`, `VARIANCE_EXCEEDS_TOLERANCE`) is separately, structurally unreachable today for an unrelated reason already established by §5.1.4: Amazon's settlement-side `amount`/`amount-type`/`amount-description` triple is captured with `component_code=None` on every row (capture-not-classify), so **zero `line_component` rows with `source_side='SETTLEMENT'` exist for Amazon** — `_group_settlement_components` will always be empty for an Amazon line, `shared_codes` will always be the empty set, and `classify_variance` is never reached. This mirrors `reconcile.py`'s own Decision A finding on the invoice side (no adapter produces `INVOICE`-side `line_component` rows) — for Amazon the mirror gap is on the settlement side too, so the variance path is doubly closed for this marketplace. This is a real, disclosed limitation of today's data, not new logic: Amazon reconciliation, run today, can honestly produce **only** Path B (`UNSETTLED_WITHIN_LAG`/`UNSETTLED_BEYOND_LAG`) findings — every settlement-row-driven outcome is either amount-blocked (point above) or component-blocked (this paragraph). This must be stated to the seller as a real, current gap (§7.3's disclosure principle), never silently narrowed to "Amazon reconciliation works."

**3. Flipkart is not equally blocked.** `flipkart.payments.v1` **does** bind `gross_settlement_amount` (`"Bank Settlement Value"`) and **does** bind real settlement-side `component_code`s (`COMMISSION`, `FIXED_FEE`, `COLLECTION_FEE`, `SHIPPING_CHARGE`, `NON_ORDER_FEE`; §5.1.3). `ORPHAN_SETTLEMENT`, `AMBIGUOUS_MATCH` and `DUPLICATE_SETTLEMENT` exceptions **can** therefore be honestly persisted for Flipkart today, with a real amount. Flipkart's variance path (`reconciliation_match`) is blocked for the same reason Meesho's currently is — no adapter anywhere in this codebase produces `INVOICE`-side `line_component` rows yet (Decision A; verified across every adapter with a non-`None` `component_code`: `base.py`, `amazon.settlement.v2`, `flipkart.payments.v1`, `meesho.payments.v1` — all four are settlement-side only) — not by any new Flipkart-specific gap. If a future invoice-side adapter starts emitting `component_code`s, Flipkart's variance path becomes exercisable immediately, gated only by shared `component_code`s existing on both sides, exactly as Path A already handles for Meesho.

**4. Duplicate-settlement detection (C4, §5.2) for Amazon — hardening `is_duplicate_settlement`, a real bug this design must close before it ships.** `is_duplicate_settlement` (`calc_engine.formulas.leak`) compares `candidate["gross_settlement_amount"] == processed["gross_settlement_amount"]` as one of C4's three required equalities. For Amazon, this value is `None` on every row (point 2). Two `None`s compare equal in Python — **unmodified, this function would wrongly flag any two same-`order_ref`, same-`settlement_date` Amazon rows as `DUPLICATE_SETTLEMENT`**, a real false-positive risk, not a hypothetical one. The fix belongs in `is_duplicate_settlement` itself (a pure-function hardening, unit-testable in isolation): if `candidate["gross_settlement_amount"] is None`, return `False` unconditionally — an unavailable amount is never treated as "the same amount," matching or otherwise. Net effect, stated plainly per the task's own framing: **Amazon settlement rows can never be flagged `DUPLICATE_SETTLEMENT` until the §5.1.4 aggregation stage closes the amount gap.** This is not a workaround to relax later — it is the only honest answer given `None` amounts cannot be compared for equality. Flipkart is unaffected (its `gross_settlement_amount` is real), and Meesho is unaffected (already real).

**5. What this design does not do.** Running `reconcile()` against Amazon or Flipkart under this design does **not** upgrade either marketplace's join-key status in §5.1's table from *specified-but-unvalidated* to *validated*. Real output — real `reconciliation_match`/`reconciliation_exception` rows, honestly labelled with the confidence and flag mechanism in `deterministic-engine.md` §5.12.2 — is not the same claim as "the join is correct." It is a real, disclosed, provisional signal computed against a candidate key, exactly as `hsn_gst_reference`'s `PROVISIONAL` rows are real curated data, not confirmed observed rates. Validating either key still requires a real populated export (§9 item 2, item 8) — this design does not, and cannot, substitute for that.

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

**Collision handling — CONFIRMED (Phase C, C3).** When a settlement row's join key (§5.1)
resolves to more than one candidate `sales_line`, matching does not proceed to outcome
classification at all. `classify_variance` (`calc_engine.formulas.leak`) already documents its
own precondition — *"Requires both sides to already be known present (settlement exists,
matched to this invoice line) — orphan/duplicate/unsettled cases are classified by the other
functions in this module, which run before this one is ever reached"* — and a collision fails
even earlier than that: it fails at candidate resolution, before any of the seven outcomes
above is a question that can be asked. A collision is therefore **not an eighth
`ReconciliationOutcome` value**. It is its own explicit ambiguous/quarantined match state,
produced by the matching step and never auto-resolved to a "best guess" single match. Reasoning:
the seven outcomes above are exhaustive answers to "given a matched (or explicitly absent) pair,
what happened" — collision is a different, prior question ("is there even one candidate to
classify against") that fails before the outcome question is posed. Folding it into the outcome
enum would misrepresent a matching-step ambiguity as a classification-step result and force
every consumer to special-case a value that `classify_variance`/`classify_settlement_lag` never
produce.

**Duplicate-settlement detection — CONFIRMED (Phase C, C4).** Two settlement rows are
`DUPLICATE_SETTLEMENT` only when all three match exactly: (1) the same join key per §5.1's
marketplace-specific key, (2) the same settlement amount, and (3) the same settlement date. This
is deliberately the most conservative rule available — lowest false-positive risk. A genuine
second, distinct charge on a different date against the same order/line is never wrongly
flagged as a duplicate under this rule.

**Amendment (this session, §5.1.5 point 4) — `None`-amount hardening.** Condition (2), "the same
settlement amount," must never be satisfied by two absent (`None`) amounts comparing equal to
each other — an unavailable amount is not "the same amount" as another unavailable amount.
`is_duplicate_settlement` returns `False` unconditionally whenever the candidate's
`gross_settlement_amount` is `None`. This is currently only reachable for Amazon (§5.1.4's
structural gap); its practical effect is that **Amazon settlement rows can never be flagged
`DUPLICATE_SETTLEMENT`** until that gap closes. Meesho and Flipkart, whose `gross_settlement_amount`
is always real, are unaffected.

### 5.3 Leak categories

`FEE_OVERCHARGE` · `SHORT_SETTLEMENT` · `MISSING_SETTLEMENT` · `UNEXPECTED_DEDUCTION` · `RETURN_NOT_CREDITED` · `TCS_TDS_MISMATCH` · `DUPLICATE_DEDUCTION`

### 5.4 The core signal

**Evidence upgraded to VERIFIED.** The original justification cited the synthetic reference file's co-located columns, which §0 and §2.3 retract. Per `docs/Metrion_PnL_and_MTR_Mapping_FINAL.pdf` §7A — headed "VERIFIED — real seller data inspected... transcribed directly from a real Meesho seller's exports (Orders report, Payments workbook)... for account SS Digital India / GSTIN 07AWOPM5761A1ZG," and stating this "supersedes the earlier STRUCTURALLY INDICATIVE status for Meesho settlement" — Meesho's real Supplier Panel exports carry invoice-side revenue fields (`Fixed Fee (Incl. GST)`, `Warehousing fee (incl GST)`, `Return premium (incl GST)`, `Meesho Commission Percentage`) alongside settlement-side values (`Final Settlement Amount`, and the documented 18-term settlement formula), joinable on `sub_order_num` — a key independently confirmed across four separately-inspected real files for the same seller account: Orders report (PDF §7A.1), Payments workbook (PDF §7A.2), TCS_Sales (PDF §8.1, ~2.28M real rows) and TCS_Sales_Return (PDF §8.2).

**Status: VERIFIED (real export), formula mapping now resolved, one new gap open.** Column-level pairing on `sub_order_num` is validated against real exports, not merely proposed — the both-sides claim is confirmed, not just evidence-backed (§9). The 18-term Final Settlement Amount formula (`= B + C + G + H + I + L + Q + R + S + T + U + V + W + Y + AA + AD + AF + AX`) is now mapped to real named columns — see §5.1.1 for the full table and its arithmetic verification against a real settled row. That same verification found the real Payments workbook does not use the exact string `Warehousing fee (incl GST)` quoted above (retained here as the original citation's wording) — the real headers are `Warehousing fee (inc Gst)` (in the formula) and a second, separate `Warehousing fee (Incl. GST)` column (not in the formula); `Fixed Fee (Incl. GST)` similarly occurs twice with different formula roles. §5.1.1 has the resolved detail; the open gap now is the business meaning of the two non-formula duplicate columns, not the formula mapping itself.

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

### 5.6 `settlement_line` schema — CONFIRMED (Phase C, C1)

Mirrors `sales_line`'s structural pattern (§1.3): money decomposition lives entirely in the
existing `line_component` table, never as new columns on `settlement_line` itself.
`line_component.settlement_line_id` (§1.4) already exists as a bare UUID column waiting for
exactly this table — *"one of these two is set"* (`sales_line_id` / `settlement_line_id`) has
been true since §1.4 was written.

**Adjustment from the originally proposed shape.** The proposal called for a
`settlement_document_id` column paralleling `sales_line`'s relationship to `sales_document`.
Checked against §1.3's actual DDL: `sales_line` carries **no** `sales_document_id` FK column at
all — its only lineage columns are `ingestion_run_id` and the nullable natural key `invoice_ref`
(text). `sales_document` is named in §1.2's entity tree but has no defined DDL anywhere in this
spec. To mirror `sales_line` exactly, rather than inventing a column pattern that doesn't exist
on the table being mirrored, `settlement_line` below **omits** `settlement_document_id` and uses
`ingestion_run_id` for run lineage — the same substitution `sales_line` itself makes.
`settlement_document` remains, like `sales_document`, a named entity-tree node without its own
schema; defining one is future work, not blocking this table.

This is a proposed schema for a future migration (data-foundation-owned, §5.7), not a migration
itself.

```sql
settlement_line (
  id                       uuid pk,
  tenant_id                uuid not null,
  ingestion_run_id         uuid not null,      -- mirrors sales_line's lineage column exactly;
                                                -- sales_line has no sales_document_id FK to
                                                -- parallel (see note above), so none is added here
  marketplace              text not null,
  -- natural keys (nullable: not every source supplies every key; mirrors sales_line's pattern)
  order_ref                text,               -- join-key candidate; real for Meesho
                                                -- (sub_order_num, §5.1/§5.4)
  line_ref                 text,               -- join-key candidate
  settlement_id            text,               -- Flipkart-specific; §5.1's proposed
                                                -- `Order ID + Line Item ID -> Settlement ID` key
  -- money (paise, signed; mirrors sales_line.gross_item_amount exactly — nullable, no NOT NULL
  -- constraint, since not every settlement row carries a computable gross amount, e.g.
  -- ServiceFee / Adjustment / Transfer rows, §2.3)
  gross_settlement_amount  bigint,
  currency                 char(3) not null default 'INR',   -- mirrors sales_line.currency exactly
  settlement_date          date,
  document_type            text,               -- informed by meesho.payments.v1's five real tabs
                                                -- (§2.3): Order Payments | Ads Cost | Referral
                                                -- Payments | Compensation and Recovery | Disclaimer
  -- provenance (mirrors sales_line exactly)
  source_row_number        int not null,
  source_row_json          jsonb not null,
  confidence                text not null      -- VERIFIED | PROVISIONAL | DERIVED | MANUAL (§7.1)
)
```

Every field above is grounded either in `sales_line`'s real §1.3 columns (mirrored 1:1 where a
parallel exists) or in evidence already cited in this file at §5.1/§5.4/§2.3. No field beyond
these two sources is included.

### 5.7 Migration ownership — CONFIRMED (Phase C, C2)

| Table | Owner | Reasoning |
|---|---|---|
| `settlement_document`, `settlement_line` | **data-foundation** | Raw ingested facts, same layer as `sales_document`/`sales_line`/`line_component` — already the unambiguous convention (`packages/calc-engine/migrations/README.md` already states this package "never authors DDL for tables owned by `data-foundation.md` (`sales_line`, `line_component`, `settlement_line`, etc.)"). This spec now states it explicitly here too. |
| `reconciliation_run`, `reconciliation_match`, `reconciliation_exception` | **calc-engine** | These are `reconcile()`'s own computed OUTPUT (`deterministic-engine.md` §5.13.1), not raw ingested data-foundation facts — the same precedent as `metric_result`/`manual_adjustment`, which are calc-engine-owned despite depending on `sales_line`. |

This resolves a real ownership ambiguity found during Phase-C scoping: `calc_engine.formulas.leak`'s
module docstring currently states the opposite — that *"`reconciliation_match`/
`reconciliation_exception` are data-foundation-owned tables (its table-ownership tree lists
them, mirroring `sales_line`/`line_component`)"* — while `packages/cfo`'s own migration work
already assumed calc-engine ownership. **This spec resolves the contradiction in favour of
calc-engine ownership**, per the reasoning above. `leak.py`'s docstring is flagged here as
needing a follow-up correction to match this decision; that correction is Phase-D
implementation work and is not made in this pass (this document does not edit calc-engine
source).

The model these tables represent — outcomes (§5.2), leak categories (§5.3), match keys (§5.1) —
continues to be **defined in this document**, per `deterministic-engine.md` §5.13.1's existing
`reconcile()` row ("Model defined in `data-foundation.md` §5"); only the DDL/migration lives in
calc-engine. This mirrors the split already established for `reconciliation_tolerance_config`
(defined by `data-foundation.md` §5.5, DDL owned and given in `deterministic-engine.md` §5.12.1).

### 5.8 Evaluation order for `reconcile()` — CONFIRMED (Phase C, C5)

Two separate evaluation paths, not one linear pipeline — they run against different row
populations and neither falls through into the other.

**Path A — a settlement row exists** (evaluated per settlement row, against its candidate
`sales_line` match(es)):

1. **Collision check (§5.2, C3).** If the settlement row's join key resolves to more than one
   candidate `sales_line`, stop here — quarantine as an ambiguous match, never proceed to steps
   2–4.
2. **Duplicate check (§5.2, C4).** Before treating a single resolved candidate as "the match,"
   check whether another already-processed settlement row shares the same join key, amount and
   settlement date. If so, this row is `DUPLICATE_SETTLEMENT` — evaluated before match/variance
   because a repeat charge changes what "the match" even means for every later step.
3. **Match/orphan check.** Does a corresponding `sales_line` exist at all for this settlement
   row's join key? If not, `ORPHAN_SETTLEMENT`.
4. **Variance classification.** For a settlement row with exactly one resolved `sales_line`
   match that is neither a collision nor a duplicate: `classify_variance()` (`leak.py`) applies,
   returning `MATCHED_EXACT` / `MATCHED_WITHIN_TOLERANCE` / `VARIANCE_EXCEEDS_TOLERANCE`.

**Path B — no settlement row was found at all, for a given `sales_line`.** This is not step 5
of Path A — it is a distinct case, evaluated over the `sales_line` rows that Path A's step 3
left unmatched, using a different function pair:

1. `classify_settlement_lag()` (`leak.py`) determines `UNSETTLED_WITHIN_LAG` vs
   `UNSETTLED_BEYOND_LAG` from elapsed time against `settlement_lag_days`.
2. `should_report_unsettled_as_leak()` (`leak.py`) gates whether an `UNSETTLED_BEYOND_LAG` line
   is actually surfaced as a reportable exception yet (the grace-period buffer,
   `deterministic-engine.md` §5.12.1) — a line can read `UNSETTLED_BEYOND_LAG` without yet being
   reported.

A future `reconcile()` implementer runs Path A over settlement rows and Path B over the
`sales_line` rows Path A's step 3 left unmatched; the two paths' outputs are combined into one
`reconciliation_exception[]` result, but they are computed independently — Path B is never a
later stage of Path A's pipeline.

### 5.9 `reconciliation_run`/`reconciliation_match`/`reconciliation_exception` schema — CONFIRMED, architect pass

Migration: `packages/calc-engine/migrations/versions/20260925_0004_reconciliation_tables.py`
(calc-engine-owned per §5.7, C2). `reconciliation_run` is the parent; `reconciliation_match`
and `reconciliation_exception` are its children (§1.2's entity tree). Real per-tenant FORCE RLS
on all three (mirrors `settlement_line`'s pattern, §5.6 — not
`reconciliation_tolerance_config`'s nullable-platform-default variant, §5.5). `sales_line_id`/
`settlement_line_id` are bare UUID columns with no FK (this package "never authors DDL for
tables it doesn't own," same convention `line_component.settlement_line_id` used before its own
FK existed).

```sql
reconciliation_run (
  id                        uuid pk,
  tenant_id                 uuid not null,
  marketplace               text not null,
  period_start              date not null,
  period_end                date not null,
  as_of_date                date not null,
  tolerance_config_version  int not null,
  formula_version           text not null,
  status                    text not null,
  settlement_line_count     int,
  sales_line_count          int,
  match_count               int,
  exception_count           int,
  join_key_validated        boolean not null,   -- CONFIRMED addition, §5.1.5 / deterministic-
                                                 -- engine.md §5.12.2: true only for
                                                 -- MEESHO (line_ref, VERIFIED per §5.1); false for
                                                 -- AMAZON/FLIPKART (order_ref-only, still
                                                 -- specified-but-unvalidated per §5.1's own status
                                                 -- table, unchanged by this run producing output).
                                                 -- Run-level, not per-row: a run's marketplace is
                                                 -- fixed for its whole lifetime, so every match/
                                                 -- exception under one run shares this value —
                                                 -- consumers join reconciliation_run rather than
                                                 -- this column being duplicated onto every child row.
  started_at                timestamptz not null,
  finished_at               timestamptz
)

reconciliation_match (
  id                     uuid pk,
  tenant_id              uuid not null,
  reconciliation_run_id  uuid not null references reconciliation_run(id),
  sales_line_id          uuid not null,       -- no FK, data-foundation-owned table
  settlement_line_id     uuid not null,       -- no FK, data-foundation-owned table
  component_code         text,
  outcome                text not null,
  variance_paise         bigint not null,
  confidence             text not null,
  formula_version        text not null,
  computed_at            timestamptz not null
)

reconciliation_exception (
  id                        uuid pk,
  tenant_id                 uuid not null,
  reconciliation_run_id     uuid not null references reconciliation_run(id),
  reconciliation_match_id   uuid references reconciliation_match(id),
  exception_type            text not null,
  sales_line_id             uuid,             -- no FK, data-foundation-owned table
  settlement_line_id        uuid,             -- no FK, data-foundation-owned table
  candidate_sales_line_ids  jsonb,
  marketplace               text not null,
  component_code            text,
  amount_paise              bigint not null,
  confidence                text not null,
  formula_version           text not null,
  computed_at               timestamptz not null,
  check (sales_line_id is not null or settlement_line_id is not null)
)
```

**Outcome-to-table mapping (schema documentation only; `reconcile()` itself is separate,
later work).** Of §5.2's seven `ReconciliationOutcome` values, only three land in
`reconciliation_match.outcome`, and a different, partly-overlapping set lands in
`reconciliation_exception.exception_type`:

`reconciliation_match` — written ONLY when `resolve_match_candidates()`
(`calc_engine.formulas.leak`) returns `SingleMatch` AND `is_duplicate_settlement()` is
`False` — exactly one resolved, non-duplicate pair. `outcome` holds one of `MATCHED_EXACT` /
`MATCHED_WITHIN_TOLERANCE` / `VARIANCE_EXCEEDS_TOLERANCE` (via `classify_variance()`). All
three are written, including the "fine" two, for audit completeness — not only problems.

`reconciliation_exception` — written for the reportable subset, `exception_type` one of:

| `exception_type` | `sales_line_id` | `settlement_line_id` | `reconciliation_match_id` | `amount_paise` | `component_code` |
|---|---|---|---|---|---|
| `VARIANCE_EXCEEDS_TOLERANCE` | set | set | set (same pair's match row) | the variance (= that match row's `variance_paise`) | set |
| `ORPHAN_SETTLEMENT` | null | set | null | that settlement row's `gross_settlement_amount` | null |
| `UNSETTLED_BEYOND_LAG` | set | null | null | that sales_line's invoice-side total | null |
| `DUPLICATE_SETTLEMENT` | null | set | null | that duplicate settlement's `gross_settlement_amount` | null |
| `AMBIGUOUS_MATCH` | null | set | null | that settlement row's `gross_settlement_amount` (same convention as `ORPHAN_SETTLEMENT`) | null |

`AMBIGUOUS_MATCH` additionally populates `candidate_sales_line_ids` (a JSON array of the 2+
candidate `sales_line` UUIDs, as strings) from a `Collision` result — it is not a
`ReconciliationOutcome` value (§5.2, C3), same as `DUPLICATE_SETTLEMENT`'s source
(`is_duplicate_settlement()` returning `True`) is not itself an outcome enum member either;
both are matching-step states that this table's `exception_type` vocabulary is deliberately
wider than `ReconciliationOutcome` to accommodate.

`UNSETTLED_WITHIN_LAG` is never persisted anywhere — no `reconciliation_match` row (there is
no settlement side at all to pair against) and no `reconciliation_exception` row (not
reportable yet, per the grace-period gate in `should_report_unsettled_as_leak()`).

`leak_finding.reconciliation_exception_id`/`amount_paise`/`marketplace`
(`packages/cfo/migrations/versions/20260923_0001_cfo_tables.py`, already live) were designed
against this exact shape — that table's `amount_paise`/`marketplace` are copied from here,
never recomputed. Any consumer that needs to know whether a given `reconciliation_exception`
was produced against a validated join key (Meesho) or an unvalidated candidate (Amazon/Flipkart)
— e.g. the CFO agent deciding how to caveat a `leak_finding` to the seller — joins back to
`reconciliation_run.join_key_validated` (added this session, §5.1.5, mechanism in
`deterministic-engine.md` §5.12.2); this is deliberately
not duplicated onto every `reconciliation_match`/`reconciliation_exception` row, since it never
varies within one run.

Integration tests: `packages/calc-engine/tests/integration/test_reconciliation_tables.py` —
migration application, RLS isolation, the CHECK constraint, both FK constraints, and one
realistic row per `exception_type` (all five).

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
2. **Amazon settlement match keys and grain.** The report family is specified (item 1 resolved). A join-key candidate (`order-id` + `order-item-code`/`merchant-order-item-id`) is now named from a credible secondary compilation of Amazon's real fields (§5.1.2) — this moves the item from *unspecified* to *specified-but-unvalidated*, not to *resolved*. It still blocks reconciliation *execution* on Amazon until validated against a real populated export; the candidate is not a confirmed key.
3. **Leak Shield for Amazon.** Blocked on (2) alone. Findings are withheld until the join is validated — not because settlement data is absent.
4. **Amazon two-file upload flow.** The report identity is specified (`amazon.settlement.v2`); cadence and join keys still require a real export.

### Must be validated — mapping likely to change

5. **All three adapter column maps.** Every binding is `is_verified = false`. Real Amazon MTR uses different column names entirely.
6. **Date format declarations.** Amazon `%m/%d/%Y` and Flipkart `%d-%m-%Y` are mutually ambiguous for day ≤ 12. Confirm from a real export before any production ingest.
7. **Meesho `sss` column.** Unverified — likely Shipping City. Not to be renamed until confirmed.
8. **Whether Flipkart and Meesho really combine invoice and settlement** in one export, or ship them separately. For Flipkart, independent secondary sources (§5.1.3) now corroborate that they are separate, and name `Order ID` as the settlement-to-order join field — still secondary-sourced and unvalidated against a real populated Flipkart export, so this item remains open, not resolved, pending a real file.
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
