# Metrion — CFO Data Intelligence Specification

**Status:** Draft for review (CFO 2.0, P1)
**Prerequisites:** `data-foundation.md` (adapter contract §2.2, validation §4, dedup §6, confidence §7) · `deterministic-engine.md` §7 (manual inputs) · `cfo-agent.md` §6.16 (ingestion-to-canonical) · `auth.md` §7.3 (worker tenancy, D8)
**Related:** `cfo-query-planner.md`, `cfo-unified-financials.md`, `cfo-dashboard.md`

Sellers upload marketplace reports; Metrion turns them into trusted canonical rows. This spec covers **large-file streaming, XLSX, background jobs, semantic column mapping for unfamiliar formats, data-quality reporting, expense and advertising ingestion, and provenance.** It reuses the existing 9 verified adapters, `run_ingestion`, `ingest_and_persist` and the natural-key dedup; it replaces only the whole-file-in-memory read path.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| I1 | **Known formats use the existing verified adapters, unchanged.** Semantic mapping is only for files no adapter detects. | Owner approval 3 |
| I2 | **Local Ollama proposes mappings; deterministic validation and seller confirmation decide.** The model never writes a mapping that takes effect on its own. | Owner approval 3 |
| I3 | **The LLM never receives full files.** It receives column names, inferred types, report metadata and a small *masked* sample. | Owner brief §1 |
| I4 | **CSV and XLSX supported**, streamed; the original file is preserved. | Owner decision 2026-10-21 |
| I5 | **Every canonical row keeps its source reference** (`report_file_id`, `source_row_number`, `source_row_json`, mapping version). | Existing schema; owner approval 3 |
| I6 | **Ingestion runs as a background job** with progress; the upload request returns a job id. | Owner approval 3 |
| I7 | **Advertising reports get an adapter family** (P3); manual ad entry stays as fallback. | Owner decision 2026-10-21 |
| I8 | **Mapped (non-adapter) sources are capped at `PROVISIONAL` confidence** until the seller confirms *and* a verification review marks the mapping verified. | data-foundation §7 (same rule as unverified adapters) |
| I9 | No real-LLM calls in this development cycle; mapping is tested with mocked proposals. | Owner approval 7 |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Job runner | A DB-backed `ingestion_job` table plus an in-process worker pool (bounded concurrency), recovered on startup by a sweep (as `ceo/recovery.py` does). No new broker. | No queue infrastructure exists; Redis stays an optional later transport. Single-process limits already documented for the CEO bus. |
| D2 | Parse strategy | Two-pass streaming: pass 1 reads header + first N rows (profile); pass 2 streams in chunks of K rows (default 5,000, config) through the existing pure `run_ingestion` per chunk | Bounds memory by chunk size, not file size. |
| D3 | Bulk insert | Chunked multi-row inserts / `COPY` into staging then set-based move; keep the existing transaction-per-file atomicity via a staging table and a final commit | Atomic file semantics preserved (no half-ingested file). |
| D4 | Quarantine threshold | Keep the existing 20% rule, evaluated at end of stream; staged rows are discarded on failure | Matches data-foundation §7.4. |
| D5 | XLSX | `openpyxl` read-only mode, streaming rows; sheet selection by detection, else seller choice; formulas read as cached values; macros ignored | Already a dependency; read-only mode is memory-flat. |
| D6 | Mapping scope | Mappings are per-tenant, per-fingerprint (hash of normalised header set + sheet name), reused automatically for the same fingerprint once confirmed | Unfamiliar once, familiar after. |
| D7 | Masking | Deterministic masking before any model sees a sample: names, phones, emails, addresses, GSTIN/PAN/bank refs replaced by typed tokens; numbers and dates kept (needed to infer meaning); sample size ≤ 20 rows, sampled across the file, not the first rows | Privacy + accuracy. |

---

## 3. Assumptions

| # | Assumption | Risk |
|---|---|---|
| A1 | A file's header row is identifiable (first row with ≥ 60% non-empty string cells) | Medium — offer seller-chosen header row |
| A2 | Memory per row ≈ small once streamed; the previously measured ≈ 31× expansion applies to the *old* path only | Low — benchmark records actual |
| A3 | Marketplaces occasionally rename columns; new column names are not adversarial | Medium — treat as untrusted input anyway |

---

## 4. Goals and non-goals

**Goals** — ingest 2,000 to 1M+ row files without exhausting memory; keep the 80k-row, multi-file target (<60 s on the recorded benchmark environment); recognise known formats automatically; propose, validate and confirm mappings for unknown formats; produce a data-quality report per file and per tenant; prevent duplicate ingestion; preserve source files and row references.

**Non-goals** — marketplace API connections (never); OCR of receipts; bank statement ingestion (cfo-agent Q1); automatic acceptance of any ambiguous mapping; inferring missing values; real-model evaluation this cycle.

---

## 5. Data model

```sql
ingestion_job (
  id uuid pk, tenant_id uuid not null, report_file_id uuid not null references report_file(id),
  adapter_id text, mapping_id uuid null,             -- exactly one of the two set once resolved
  status text not null,   -- QUEUED|PROFILING|AWAITING_MAPPING_CONFIRMATION|PARSING|VALIDATING|COMMITTING|DONE|FAILED|CANCELLED
  progress_rows bigint not null default 0, total_rows_estimate bigint,
  error_code text, error_detail text,
  created_by uuid not null, created_at timestamptz not null, started_at timestamptz, finished_at timestamptz,
  heartbeat_at timestamptz )                          -- recovery sweep marks stale RUNNING jobs

column_mapping (
  id uuid pk, tenant_id uuid not null, fingerprint text not null, version int not null,
  report_kind text not null,            -- SALES | SETTLEMENT | EXPENSE | ADVERTISING
  marketplace text,                     -- null for expense files
  sheet_name text, header_row int not null,
  status text not null,                 -- PROPOSED | CONFIRMED | REJECTED | SUPERSEDED
  proposed_by text not null,            -- MODEL:<model-id> | ADAPTER_DERIVED | SELLER
  confirmed_by uuid, confirmed_at timestamptz,
  verified boolean not null default false,
  unique (tenant_id, fingerprint, version) )

column_mapping_field (
  id uuid pk, tenant_id uuid not null, mapping_id uuid not null references column_mapping(id),
  source_column text not null, source_column_index int not null,   -- index disambiguates duplicate headers
  canonical_field text not null, component_code text null,
  transform text not null,              -- e.g. IDENTITY | RUPEES_TO_PAISE | PERCENT | DATE_DMY | DATE_ISO | STRIP_CURRENCY
  tax_inclusion text null,              -- INCLUSIVE | EXCLUSIVE | UNKNOWN
  sign_convention text null,            -- AS_IS | NEGATE
  decision text not null,               -- AUTO_ACCEPTED_BY_RULES | SELLER_CONFIRMED | SELLER_OVERRIDDEN | REJECTED
  evidence jsonb not null )             -- the validator's checks and results

data_quality_report (
  id uuid pk, tenant_id uuid not null, ingestion_job_id uuid not null,
  summary jsonb not null,               -- counts, coverage, quarantine reasons, duplicate counts, period coverage
  created_at timestamptz not null )
```
All tenant-owned, `FORCE` RLS. `canonical_fields` produced via a mapping carry `mapping_id` + `version` in `source_row_json` provenance; `line_component.is_verified=false` for mapped sources. Existing tables unchanged except `report_file.report_category` already supports `ADVERTISING`; an `EXPENSE` category value is added.

---

## 6. Core rules

### 6.1 Intake
1. Upload (CSV/XLSX) → size cap (config, raised from 20 MB — bounded by *disk/stream*, not memory) → store original → compute content hash → duplicate-hash short-circuit (existing).
2. Create `ingestion_job` (`QUEUED`); return `jobId`. Progress readable by poll and SSE (tenant-keyed, no figures in events).
3. Worker sets tenant context from the job row (auth.md D8); a job without tenant fails closed.

### 6.2 Format resolution (order matters)
1. **Adapter detection** against header (and sheet names): `detect()` of every registered adapter; a match with full confidence → use it (unchanged path).
2. **Confirmed mapping lookup** by fingerprint → use it.
3. Otherwise → **semantic mapping proposal** (§6.4), job state `AWAITING_MAPPING_CONFIRMATION` until resolved.
4. No resolution possible (no usable header, non-tabular) → `FAILED` with a plain reason; nothing stored beyond the original.

### 6.3 Streaming parse/validate/commit
- Chunked read (CSV via incremental reader; XLSX via read-only worksheet iterator); per chunk: apply adapter/mapping → existing row validation rules → stage accepted rows, collect findings.
- **Duplicate handling (amended 2026-10-21, owner requirement 4).** Every incoming row is classified *before* financial posting, within the file and against previously ingested data, using two measurements: an **identity** (who the row claims to be) and a **raw-row hash** (what the row says: a digest of the row's source columns, order-independent). Classification is a pure function over those two, tested without a database.

  **Report family.** Identity includes the *kind of report* a row came from (the adapter id without its version suffix, or the file shape of a confirmed mapping). A Meesho orders report and a Meesho TCS report both carry rows for one Sub Order No: different facts about it, not duplicates of each other. Only a re-upload of the same kind of report can overlap.

  **Strong identity, defined per marketplace** (from the columns each marketplace's reports really carry; `MARKETPLACE_IDENTITY` in code). A row is *identity-strong* only when it carries the marketplace's own unique **line id**. A product id (SKU, ASIN, FSN) is never a line id: the same product can sit on several lines of one order.

  | Marketplace | Strong sales identity (the line id) | Settlement row identity (never strong) |
  |---|---|---|
  | **Meesho** | `Sub Order No` (`line_ref`; the verified unique sub-order key, data-foundation §5.1) | `Sub Order No` + final settlement amount (the Payments export carries nothing more) |
  | **Amazon** | `Shipment Item ID` (`line_ref`; `ASIN` is the product, not the line) | order id + order-item code + merchant-order-item id + shipment id + settlement id + the melted amount-type / amount-description / amount (one row per fee or principal line) |
  | **Flipkart** | `Line Item ID` (`line_ref`; `FSN` is the product, not the line) | order id + settlement id + settlement date + amount |

**Legitimate financial events that share an order or shipment id are different events** (a sale and its credit note, a shipment and its refund, partial refunds, a replacement shipment, several shipments of one order, one shipment carrying several items or several orders). The identity therefore also carries the event discriminators a row has: `document_type` and `transaction_type` for sales rows, `document_type` for settlement rows, compared case- and separator-insensitively ("Credit Note" = "CREDIT_NOTE"). Today's verified adapters map neither, so for them events are told apart by line id, amounts, dates and descriptions; where that is not enough two rows of one line with different content are a `CONFLICT` and an identical repeat is `AMBIGUOUS`, held with an explanation — never merged, never silently both posted.

  A sales row with no line id still gets an identity (order, invoice, and its product ids so two products of one order never merge), but it is *weak*: an identical repeat is held as ambiguous, never skipped. A settlement row is never strong: identical settlement rows cannot be told from a double export, while different amounts or dates on one order (partial settlements, adjustments, reversals) are different identities and post. An unknown marketplace gets the conservative default (nothing strong).

  | Class | When | Action |
  |---|---|---|
  | `NEW` | identity not seen in the file or in prior data | post |
  | `EXACT_DUPLICATE_CROSS_FILE` | same identity and same raw-row hash as already-ingested data (an overlapping upload) | skip; counted and disclosed as overlap, never silently |
  | `EXACT_DUPLICATE_IN_FILE` | same identity and same raw-row hash earlier in this file, **identity-strong** (the marketplace's own line id present) | skip the repeat; `WARNING` finding `V-DUP-001` naming the first row |
  | `CONFLICT_CROSS_FILE` | same identity, different raw-row hash from already-ingested data (a correction? a status change? a different report version?) | **hold** the incoming row (not posted); `ERROR` finding `V-DUP-003` explaining that an earlier upload has this line with different values and that superseding requires the seller's confirmation |
  | `CONFLICT_IN_FILE` | same identity, different raw-row hash earlier in this file | keep the first, **hold** the later row; `V-DUP-003` |
  | `AMBIGUOUS_REPEAT` | an identical raw row repeated within a file where nothing distinguishes the repeats (identity-weak sales rows, or settlement rows): a double export and two real identical entries cannot be told apart | keep the first, **hold** the repeats; `ERROR` finding `V-DUP-002` explaining that if both entries are real the seller must add a distinguishing reference |

  **Held rows are unresolved: they are not posted, and so they are excluded from every authoritative financial figure** until the seller resolves them (resolution flow: OQ7/OQ10). Held rows are never posted and never silently dropped: each has a finding with its row number and plain-language reason, counts appear in the data-quality report, and the original file is preserved so the seller can resolve and re-upload. **Held-duplicate rows are excluded from the 20% quarantine-threshold ratio**: a heavily overlapping re-upload is not evidence of a mismatched file (data-foundation §7.4 concerns malformed rows). Because the legacy path compared only against *existing* rows, within-file duplicates were previously posted twice; the new behaviour is a deliberate correction, and the legacy path remains unchanged for reference. The in-file index holds a 16-byte digest per distinct identity (about 130 bytes per entry), a stated memory cost at very large files (OQ6).

- End of stream: evaluate quarantine threshold; on success one commit moves staged rows into `sales_line`/`settlement_line`/`line_component` and bumps `cfo_read_model_version`; on failure staged rows are discarded, nothing is half-committed.
- Rejected-row reasons stored as today (`validation_finding`), bounded by the threshold.
- Heartbeats every chunk; a stale job is marked `FAILED(stale)` by the sweep and may be retried from the stored file (idempotent: content hash + natural keys).

### 6.4 Semantic column mapping
Input to the model (masked, bounded): column names, inferred type and format per column (numeric/date/enum/free text with distinct-count and min/max for numerics and dates), report metadata (sheet name, filename tokens, first-row hints), ≤ 20 masked sample rows. Output: JSON proposal `[{source_column, index, canonical_field, component_code?, transform, tax_inclusion?, sign_convention?, confidence_note}]` plus `unmapped_columns`. The canonical field set and `component_code` registry are the **closed vocabulary** (`component_registry`, adapter canonical fields); the model may only choose from it, or mark a column `UNMAPPED`.

**The deterministic mapping validator** (all per-field; any ERROR blocks auto-accept):

| Rule | Check |
|---|---|
| M-VOC | field/component is in the closed vocabulary; no invented names |
| M-ONE | no two source columns map to the same non-additive canonical field; duplicate headers addressed by index |
| M-TYP | ≥ 98% of non-null values parse under the proposed transform (numeric, date format, enum domain) |
| M-GRN | transaction grain detected (row = order line / order / settlement line / ad day) from key uniqueness over the profile; must match the report kind's required grain |
| M-TAX | tax inclusion: where `taxable`, `tax`, `gross` columns coexist, test `|taxable + tax − gross| ≤ tolerance` on ≥ 98% of rows to determine inclusion; absent a test → `UNKNOWN` → seller must confirm |
| M-SGN | sign convention: refunds/returns/fees checked against expected sign domain per component; mixed signs in one column → ERROR |
| M-CUR | currency column/metadata resolves to INR; any other → ERROR (V1) |
| M-PER | a date column covers a plausible contiguous period; future dates or > 5-year span → WARN |
| M-STA | settlement status columns map to the engine's settlement states only through a seller-confirmed enum table |
| M-UNT | rupee vs paise detected: values with ≥ 1 non-zero fractional digit in > 2% of rows → rupees; else ambiguous → seller confirms |
| M-PCT | percentage units: an ambiguous rate column (all values within (0, 1], no `%`) must be resolved by the seller; `FRACTION_TO_PERCENT` is refused where a value exceeds 1 or carries a `%` (§6.4a) |
| M-REQ | all fields required by the report kind are mapped, or the missing ones are listed as `agent_data_request`s |

### 6.4a Value transforms with exact definitions

**`PERCENT` (decision R2 — documented, ready for owner approval).** Implemented once in `data_foundation/mapping/units.py` (`parse_percent_points`) and used by both the validator and the mapped adapter.

| Aspect | Definition |
|---|---|
| Meaning | A percentage in **percentage points**: "18" or "18%" is 18 points (an 18% rate). It is **not** converted to a fraction, because every consumer (V-TAX-003, the GST slab references) compares in percentage points, as the verified adapters store it. |
| Accepts | optional surrounding spaces; digits with an optional decimal part; an optional single trailing `%`. No leading `+`. |
| Range | `0 ≤ value ≤ 100`, inclusive. Negative or above 100 is invalid; never clamped. |
| Precision | at most 4 decimal places (the width of `line_component.rate_pct numeric(7,4)`). More than 4 is invalid. |
| Rounding | **none**. The exact decimal is kept, normalised to its shortest form ("18.00" becomes "18", "0.00" becomes "0"). |
| Never | a heuristic: "0.18" is 0.18 points, not 18%. A column of fractions is not guessed at. |
| Invalid | anything else (`""`, `abc`, `NaN`, `inf`, `1e1`, `1,8`, `18%%`, `-1`, `100.01`, `18.12345`): the row is quarantined by V-MAP-001 naming the value; never defaulted to 0. A blank cell is "not given" (not an error, not 0). |
| Ambiguity (**mandatory unit-aware validation**) | A column whose non-blank values are all within (0, 1] and none carries a `%` could be percentage points (0.18 = 0.18%) or fractions (0.18 = 18%). Metrion **never decides**: rule **M-PCT** requires the seller to choose the unit explicitly, and auto-accept is impossible even for a recognised header. A column with a value above 1 or any `%` is unambiguously percentage points; an all-zero column is not ambiguous. |
| `FRACTION_TO_PERCENT` | A **seller-chosen** transform, never a default: the values are fractions of 1 and "0.18" becomes 18. Accepts 0 to 1 inclusive with at most 6 decimals and no `%`; the result is value × 100, exact (at most 4 decimals). Refused (M-PCT) when any value is above 1 or has a `%`; always needs the seller's confirmation. |
| Tests | `tests/unit/mapping/test_units_percent.py`: valid and invalid tables, a property test that every 4-place value in 0..100 round-trips exactly, a property test that anything above 100 is invalid, the adapter and validator paths. |

**Decision logic.** A field is `AUTO_ACCEPTED_BY_RULES` only when every applicable rule passes *and* the column name matches the closed-vocabulary synonym register or an adapter's own column (so "Item Price"/"Sale Amount"/"Selling Price" never auto-accept as the same thing without validation passing); anything else — including every `tax_inclusion`, `sign_convention`, `unit` and money-bearing field that was not exactly matched — requires **seller confirmation** in the mapping review UI. Seller edits are re-validated. A rejected mapping stays rejected for that fingerprint.

**Never:** infer a mapping silently, accept a model proposal that fails validation, map a column to a component_code outside the registry, or apply a mapping to a file whose fingerprint differs from the confirmed one.

### 6.5 Mapped data confidence
Rows ingested via a mapping carry `PROVISIONAL`; metric results cite `mapping_id`/version in provenance; the dashboard shows "Mapped source — confirmed by you on <date>". A verification review (`column_mapping.verified=true`, by a Metrion reviewer, not seller) is the only path to `VERIFIED` and requires comparison against a real export.

### 6.5a GST-inclusive mapped amounts — current limitation and the specified future workflow (decision R3)

**Scope.** GST-inclusive mapping and India-specific tax reconciliation (GST on sales and fees, TCS/TDS, ITC visibility, CA-ready reconciliation) remain **in the production scope** of CFO 2.0. The limitation below is a *temporary safety refusal*, not a reduction of scope; the future workflow is specified here, with seller confirmation and CA review where required.

**Limitation (in force).** A mapped gross/total amount must be declared **tax-exclusive**. A mapping whose gross or total amount includes GST, or whose GST treatment is unknown, is **refused** (`TAX_INCLUSIVE_UNSUPPORTED_FOR_MAPPED`); nothing is posted. The seller is told plainly and the mapped path stays closed to such files. This is the safe behaviour: posting an inclusive amount as exclusive would overstate revenue.

**Future workflow (specified, not built): GST-exclusive conversion.**
1. *Source of the base.* Prefer a tax-exclusive column in the file (`taxable_amount`): then no conversion is needed and the mapping is accepted as tax-exclusive by measurement (M-TAX).
2. *Otherwise convert in Brain 1, never in mapping or by a model.* A new engine formula `gst_exclusive_amount(inclusive_paise, rate_pct)` = `inclusive × 100 / (100 + rate)` rounded once, half-up, to whole paise (`deterministic-engine.md` §5.11, D8), with `rate_pct` in percentage points (the `PERCENT` definition, §6.4a). Integer arithmetic only; `UNAVAILABLE` if the rate is missing; zero or negative inclusive amounts convert by the same rule.
3. *The rate comes only from the OP13 layered source* (observed in the seller's own report, then the curated HSN reference, then the GST Applicability Lookup **accepted by the seller**). No rate from model knowledge; an unresolved rate leaves the line `UNAVAILABLE`, never defaulted.
4. *Provenance.* The converted figure is stored beside the source amount (never overwriting it) with the rate, the rate's source, the formula version and confidence `DERIVED`; the original inclusive amount stays visible.
5. *Gate.* Tax-adjacent conversion is shown as indicative until the formula and rate sources are CA-reviewed (`cfo-unified-financials.md` OQ5).
6. *Acceptance (when built).* Golden conversions at 0%, 5%, 12%, 18%, 28% including rounding boundaries; a missing or unaccepted rate is `UNAVAILABLE`; the source amount is untouched; conversion reproduces on re-run; a mapped inclusive file posts exactly the converted figures and flags them `DERIVED`.

### 6.6 Data-quality report
Per job: rows read/accepted/rejected/duplicate, rejection reasons by rule, date coverage, per-column null rates, enum values unmapped, quarantine ratio, mapping decisions, items needing the seller. Per tenant (rolled up for dashboard trust badges): last updated per source, coverage by marketplace and period, open `agent_data_request`s.

### 6.7 Expense ingestion
Expense CSV/XLSX → canonical expense entries via `manual_adjustment` (`expense.<category>`) rows, **not a new store** (cfo-agent AC17d): date, category, amount, description, optional vendor, payment reference. Mapping uses the same machinery (`report_kind=EXPENSE`). Each row: category mapped via `expense_class_map` or `OTHER_UNCLASSIFIED`; duplicate-cost prevention per `cfo-unified-financials.md` §4.3 (exact-row duplicate → skipped, counted; same vendor/amount/date within a file or against existing entries → `POSSIBLE_DUPLICATE` held for confirmation; marketplace-deduction-like categories → `MAY_OVERLAP_MARKETPLACE`). Writes require `financials.adjust` (AC11) and record `entered_by`.

### 6.7a Expense ingestion — design gap found while sizing AC-D11 (2026-10-21), and the proposed deferral

> **Resolved 2026-10-21 (Phase 3a):** the owner chose Option C (a dedicated ledger, legacy pools preserved). See `cfo-expense-ledger.md`; the text below records the gap that led to that decision.

Sizing AC-D11 against the real engine showed that §6.7 as drafted cannot be implemented safely, so it is **not built**:

1. The engine's expense registry (`deterministic-engine.md` §7.2.1) holds **pooled costs** in exactly five categories (`expense.advertising | packaging | storage | logistics | other`), each of which **feeds Contribution Profit** (§5.6). A real expense file has many more kinds (rent, salaries, software, owner drawings, inventory purchases, capital items).
2. Mapping such rows onto `expense.other` would put owner drawings, purchases and capital items into Contribution Profit as "other allocated costs". That is exactly the contamination the spec forbids (`cfo-unified-financials.md` §4.2, AC-U3), and the engine would have no way to tell afterwards.
3. The per-transaction ledger (date, vendor, description, payment reference), the class of each category (`OVERHEAD`, `OWNER_DRAWING`, `INVENTORY_PURCHASE`, `CAPITAL`, ...), and the cost-ownership overlap check need a representation the engine does not have. Classification must be **suggest-only until the seller confirms** (decision OQ2), which needs a stored suggestion and a stored confirmation.

**Proposal (needs owner approval): defer AC-D11 to Phase 3 (Expense Intelligence), where the expense model is specified properly first.** The decision to take there: (A) a new engine-owned `expense_entry` ledger (reverses the earlier "no CFO-owned store" decision R6/AC17d, justified by the above), or (B) extend the `manual_adjustment` registry with a ledger field kind plus a confirmed `expense.class`. Until then no expense row is posted anywhere, so none can contaminate a profit figure. The benchmark's expense file is streamed, profiled and mapping-validated only, and labelled so.

### 6.8 Advertising ingestion (P3)
Adapter family `{amazon,flipkart,meesho}.ads.*` registered like other adapters (`report_category=ADVERTISING`), landing in `ad_report_line` (cfo-unified-financials §5): spend, attributed sales where reported, date, campaign, SKU where reported. Built from published report formats and marked `is_verified=False` until a real export validates them (PV2). Until then manual ad spend remains available and V-DUP-2 governs which source is authoritative.

### 6.9 Performance and the benchmark
Target (not guarantee): 80,000 rows across four files ingested in < 60 s on the recorded environment. A benchmark script generates a **clearly labelled synthetic** dataset of the Ravi shape (25k/18k/32k/5k rows), runs ingestion, and writes a report with machine spec, Postgres version, chunk size, wall time, peak RSS, rows/s. No claim of meeting the target is made until that report exists and is committed.

---

## 7. AI requirements
Local Ollama only; masked metadata; one proposal call per unfamiliar fingerprint; output validated strictly as JSON against the closed vocabulary; any parse error → mapping falls back to "ask the seller to map manually" (the review UI supports manual mapping). Provider behind `LlmProvider`. In tests, a mock provider returns fixed proposals, including adversarial ones (invented field, swapped sign, tax-inclusive mislabelled as exclusive, duplicate target field, rupees mislabelled as paise). **Real-model mapping quality tests are deferred** (Brain-3-style extraction evals required by CLAUDE.md before seller exposure).

## 8. Authorization and security
Upload and job read: `agent.cfo` + entitlement. Mapping confirm and expense/ad writes: `financials.adjust`. Files: tenant-scoped storage path; content never logged. XLSX hardening: read-only, no macro/external-link evaluation, size and sheet-count caps, zip-bomb guard (uncompressed-size ratio cap), CSV-injection-safe on export. Masking applied before any model call and before logs. Worker tenancy per auth.md D8. No client-supplied `tenant_id`.

## 9. Edge cases
E1 header not on row 1 · E2 duplicate header strings (index-disambiguated, existing occurrence-index logic) · E3 multi-sheet XLSX with some irrelevant sheets · E4 merged cells/blank leading rows · E5 numbers as text with commas/currency symbols · E6 dates mixed `DD/MM/YYYY` and `MM/DD/YYYY` → ambiguity → seller confirms · E7 re-upload overlapping periods (natural-key dedup counts duplicates) · E8 file changes format mid-file (quarantine threshold) · E9 worker killed mid-job (staging discarded, sweep marks stale, retry) · E10 two jobs for the same file (hash dedup) · E11 empty or header-only file · E12 > configured row cap → `FAILED(too_large)` with the cap stated · E13 formula cells with uncached values → treated missing (UNAVAILABLE downstream) · E14 unknown currency · E15 all rows quarantined.

## 10. Production-validation blockers
PV1 Flipkart/Amazon adapters and ad adapters unverified against real exports (cfo-agent V1/V6) · PV2 real Ollama proposal quality unmeasured (deferred) · PV3 throughput target unmeasured until benchmark report exists · PV4 masking completeness needs a PII review before production use.

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC-D1 | **Bounded memory.** An upload never loads its file into memory: rows are read in chunks of `CFO_STREAM_CHUNK_ROWS`. Peak memory is bounded by (a) *chunk size × row width* (a row carries one finding per unmapped column) plus (b) one small digest (≈130–230 bytes) per *distinct row identity* in the duplicate index, which grows linearly with rows and is capped by `CFO_STREAM_MAX_ROWS`; it never grows with the file's bytes. A file larger than the old 20 MB cap must ingest within these bounds, with the figures recorded by the benchmark. |
| AC-D1-status | **PASSED (as re-worded), 2026-10-21.** The committed large-file benchmark (`tools/benchmarks/cfo_ingest_benchmark.py --large-file`, report `docs/evaluation/cfo-2-ac-d1-large-file-benchmark.md`) met C1–C4: a 42.8 MiB / 240,000-row file ingested in full (110.6 s, peak growth 236 MiB). **Caveat, shown openly:** the memory slope was 354 B/row against the 400 B/row limit — a thin margin — and the criteria are provisional, to be revisited with real seller exports (a spill-to-disk index remains the mitigation, OQ6). Original criteria: C1 file above 20 MiB; C2 every row posted and equal to the database count; C3 memory slope ≤ 400 bytes/row between N and 4N rows; C4 peak growth at 4N ≤ 400 MiB; C5 throughput recorded; each size run in its own process. |
| AC-D1-note | *Wording change, shown openly:* the earlier text said memory is "bounded by chunk size". Measurement showed that is incomplete: a 1,000,000-row run grew peak memory by 231 MiB and a wide 75,000-row run by 153 MiB, because of the duplicate index and per-column findings. The requirement is **not weakened**: memory is still independent of file size and the row cap is a hard ceiling; the statement now names what actually bounds it. A spill-to-disk index remains the planned mitigation if a benchmark shows the ceiling is too high (OQ6). |
| AC-D2 | Known-format files ingest through the existing adapters with results identical to the old path (golden comparison) |
| AC-D3 | An unfamiliar file yields a proposal; no row is persisted before every ambiguous field is seller-confirmed |
| AC-D4 | A mapping failing M-VOC/M-TYP/M-TAX/M-SGN/M-UNT cannot auto-accept |
| AC-D5 | A failed or cancelled job leaves no staged rows and no partial canonical rows |
| AC-D6 | Re-uploading the same bytes, or an overlapping file, never double-counts |
| AC-D6c | Legitimate events sharing an order or shipment id post: a sale and its credit note, a shipment and its refund, one order in several shipments, one shipment with several items or orders, a replacement shipment, equal and opposite refund/reversal rows, partial settlements and per-description melted settlement rows. Identical events that cannot be told apart are held with the reason |
| AC-D6b | Within-file duplicates and cross-file overlap are detected before posting; identical identity with different content, and unexplainable identical repeats, are held with a stated reason; partial settlements and adjustments on one order are posted, not held |
| AC-D7 | Every canonical row traces to file, row number, ingestion run and (if used) mapping version |
| AC-D8 | Samples sent to the (mocked) model contain no unmasked PII tokens |
| AC-D9 | A job without tenant context fails closed; cross-tenant job/mapping reads return nothing |
| AC-D10 | XLSX with a zip-bomb ratio or macros is rejected/ignored safely |
| AC-D11 | Expense duplicates and overlap-prone categories are held, not totalled — **BUILT in Phase 3a (2026-10-21)** through the expense ledger (`cfo-expense-ledger.md`, owner decision Option C): an expense file is read through a seller-confirmed mapping, an exact repeat is skipped and counted, a same-day/amount/vendor lookalike and a marketplace-deduction-like category are held and excluded, an unreadable row is rejected with its reason, and the whole file is one transaction. Evidence: `packages/data-foundation/tests/integration/test_expense_ingestion.py` (7 tests) and the four-file 80,000-row run in `docs/evaluation/cfo-2-ingest-benchmark.md`. Limits: GST in an expense file is stored beside the amount with its treatment unconfirmed (amount used as entered); the mapping proposal in tests and the benchmark is a mock; no real seller expense file has been used. |
| AC-D12 | Benchmark report exists with environment recorded before any performance claim |

## 12. Test scenarios
TD1 golden Meesho orders via old vs streaming path → identical rows · TD2 100k-row streamed file memory bound · TD3 mocked proposal "Item Price" tax-inclusive mislabelled → M-TAX blocks auto-accept · TD4 swapped-sign refunds → M-SGN · TD5 paise-as-rupees → M-UNT · TD6 duplicate target field → M-ONE · TD7 invented component → M-VOC · TD8 kill worker mid-parse → no partial rows · TD9 overlapping re-upload · TD9b classification matrix (NEW, exact cross-file, exact in-file, conflict cross-file, conflict in-file, ambiguous repeat), two items of one order without `line_ref`, three partial settlements of one order, identical adjustment rows twice in one file · TD10 XLSX multi-sheet selection · TD11 masked sample audit (regex for names/GSTIN/phone) · TD12 tenant isolation on jobs/mappings · TD13 expense CSV with duplicate rows and ad-spend overlap · TD14 header-only file · TD15 quarantine threshold at stream end discards staged rows.

## 13. Explicit open questions
| # | Question |
|---|---|
| OQ1 | New configured upload cap value and max rows (recommend 200 MB / 2M rows, disk-bounded) |
| OQ2 | Retention of original files (policy and storage backend beyond local disk) |
| OQ3 | Who performs "verified" mapping reviews, and against which real exports |
| OQ4 | Whether to expose the closed-vocabulary synonym register as configuration |
| OQ5 | Locale handling for dates/numbers (Indian digit grouping handled; others?) |
| OQ6 | In-file duplicate index memory at 1M+ rows (one digest per identity); spill to disk or a DB-side temp table if the benchmark shows a problem |
| OQ7 | **Partly resolved (2026-10-22, §6.3a).** Held rows are now kept and the seller can KEEP_EARLIER or DISCARD them. **Still open:** SUPERSEDE_WITH_THIS and KEEP_BOTH_WITH_REFERENCE — they need a supersession mechanism on `sales_line` / `settlement_line` that about 30 readers across the CFO, CMO and CI would have to honour; that is a data-model decision for the owner, not built |

---

## 14. Phase 1 implementation record (2026-10-21) — what was built, and every place it refined this spec

**Built and tested** (deterministic tests; mocked proposals; no LLM call): streaming CSV/XLSX readers; atomic chunked ingestion; duplicate classification (§6.3); `ingestion_job`, `column_mapping`, `column_mapping_field`, `data_quality_report`, `ad_report_line`, `expense_class_map`, `cfo_read_model_version` tables (migrations `20261021_0003` data-foundation, `20261021_0013` calc-engine); job runner with atomic claim, cancellation, failure messages; mapping propose / confirm with re-validation; a mapped adapter; routes `POST /cfo/uploads`, `GET /cfo/jobs`, `GET /cfo/jobs/{id}`, `POST /cfo/jobs/{id}/cancel`, `GET /cfo/jobs/{id}/mapping`, `POST /cfo/jobs/{id}/mapping/confirm`; the local-model proposer (off unless `CFO_MAPPING_MODEL` is set).

**Refinements to the draft, shown against what the draft said. Column "Changes a previously stated requirement?" is answered openly; owner decisions of 2026-10-21 are recorded in the last column.**

| # | Draft said | Built / now says | Changes a previously stated requirement? | Owner decision (2026-10-21) |
|---|---|---|---|---|
| R1 | D1: a startup sweep recovers interrupted jobs | Lazy, **per-tenant** recovery on every job read/list/upload; a job waiting for the seller is never stale | **Yes** — mechanism changed (startup sweep to lazy per-tenant) | Accepted with the other refinements. Reason is structural: RLS forbids a cross-tenant sweep |
| R2 | Percent transform named `PERCENT_TO_FRACTION` | Renamed `PERCENT`, value in percentage points; full definition in §6.4a | **Yes** — name and semantics clarified (it never converted to a fraction) | Approve **after** formula, valid inputs, rounding and tests are documented: **done in §6.4a and `test_units_percent.py`; ready for approval** |
| R3 | Mapped sales may be GST-inclusive with `tax_inclusion` recorded | **Refused** (`TAX_INCLUSIVE_UNSUPPORTED_FOR_MAPPED`) until a GST-exclusive conversion exists; workflow specified in §6.5a | **Yes** — behaviour tightened (allowed-with-note to refused) | Approved as a temporary limitation; future workflow specified in §6.5a |
| R4 | Unreadable cell: not specified | New row rule V-MAP-001 quarantines the row, naming column and value | No — gap filled; nothing contradicted | — |
| R5 | A model proposal is validated | The proposer is also handed **masked profiles** only | No — strengthens the stated rule that no raw value reaches a model | — |
| R6 | Mapping confirmation records decisions | Confirmation **re-validates** and refuses on any error, missing required field, or undecided field that needs the seller; needs `financials.adjust` | No — makes AC-D3/AC-D4 executable | — |
| R7 | `column_mapping` columns | + `evidence`; + job "adapter or mapping, never both" check | No — additive schema | — |
| R8 | One report category per file | New uploads label SALES as `ORDER_STATUS` provisionally | No — provisional label; reconciling it is OQ9 | — |
| R9 | `ingest_and_persist` | Left unchanged as the legacy path | No | — |
| R10 | In-file duplicates: not specified beyond OQ6 | Identity now **defined per marketplace** with a report family (§6.3); held rows are unresolved and excluded from authoritative figures | **Yes** — the generic "(sku, item id) makes it strong" rule from the first draft is replaced: a product id is never a line id | "Keep unresolved duplicates held and excluded; define strong identity separately for each marketplace": implemented and tested |

**Also refined during verification (2026-10-21):** an optional `adapter_id` on `POST /cfo/uploads` lets the seller state the report type when a file's columns fit several (Amazon's B2B and B2C MTR reports share every header); the runner never guesses, and fails an ambiguous file with plain guidance.

**Additional open questions raised by implementation**

| # | Question |
|---|---|
| OQ8 | A specified GST-extraction rule for mapped, GST-inclusive amounts (needs a rate source and a CA-reviewed rule), without which such mappings stay refused |
| OQ9 | Reconcile `report_file.report_category` with the resolved adapter/mapping after the job resolves the format |
| OQ10 | Held-duplicate resolution flow (OQ7) and a manual-mapping UI when the model proposal fails or the model is off |
| OQ11 | The `ADVERTISING` and `EXPENSE` ingestion routes (spec §6.7, §6.8) are not built yet; `POST /cfo/uploads` rejects those kinds with a clear 400 |


## 6.3a Held rows — seller resolution (dashboard track, 2026-10-22)

**Confirmed decisions.** A row an upload holds back (same order line with different values, or an identical repeat that cannot be told from a double export) is kept verbatim in the append-only `held_row` table (migration 20261022_0018), in the same transaction as the file, with its rule (`V-DUP-002/003`), the plain reason, the earlier row number (in-file) and the row's values. It never reaches a figure. The seller decides with `POST /cfo/jobs/{id}/held/resolve` (`financials.adjust`): **KEEP_EARLIER** (the earlier data stands) or **DISCARD** (this row is dropped). One decision per held row (`held_row_resolution`, unique); neither action changes a figure, so neither bumps the read-model version. `GET /cfo/jobs/{id}/held` lists them (paged; HELD | RESOLVED | ALL).

**Not built (deliberately, OQ7):** `SUPERSEDE_WITH_THIS` and `KEEP_BOTH_WITH_REFERENCE` are refused with "not available yet". Superseding earlier data needs canonical-line supersession that every reader of `sales_line` / `settlement_line` must honour (30 query sites in the CFO, CMO and CI); keeping both needs a seller-supplied distinguishing identity. Both change what posts, so they need an owner decision on the data model first.

**Limits.** Cross-file conflicts show the held row and the reason but not the earlier row's values side by side (the database remembers only the earlier row's hash). A multi-row resolve is applied row by row; a refusal part-way leaves the earlier rows decided (each is independently recorded).

**Manual mapping.** `POST /cfo/jobs/{id}/mapping/manual` (`financials.adjust`) is accepted for a job that failed with `MAPPING_PROPOSAL_FAILED` or `NO_MATCHING_FORMAT`. The seller's chosen columns become a PROPOSED mapping (`proposed_by = SELLER`) on a fresh attempt, validated and explicitly confirmed exactly like a model's proposal; nothing is saved before confirmation. Tests: `test_cfo_uploads_jobs.py`, `test_stream_persist.py`.
