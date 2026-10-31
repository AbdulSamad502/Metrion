# CMO 3.0 M8 — Listing Performance Intelligence

Status (2026-10-31): implemented and verified by automated tests on a scratch database. **Not browser-verified, not run on real seller data, and not production-ready** (see "Open items").

M8 builds on M6 (listing), M7 (history and comparison) and B8 (seller-confirmed SKU link and go-live date). It adds: importing the seller's own performance report, a deterministic dashboard, a before/after view per saved version, grounded observations, and the seller-facing capture B8 was missing. **Nothing in M8 calls a model or uses an AI credit.**

## 1. What the seller can do

| Seller action | Where | Route (all `agent.cmo`; uploads also `files.upload`) |
|---|---|---|
| Import a CSV/XLSX performance report (preview, then import) | Performance page; chat explains how | `POST /api/v1/cmo/performance/import/preview`, `POST …/import` |
| See impressions, clicks, CTR, orders, conversion, units, sales, trend, previous-period change, coverage | Performance page; chat ("how are my listings performing?") | `GET …/dashboard?marketplace&sku&start&end` |
| Connect a report SKU to a product; review/correct it | Performance page; chat ("connect SKU X to my bottle") | `GET …/sku-candidates`, `POST …/sku-link` (`replace`), `GET …/mappings` |
| Confirm when a saved version went live; correct it | Performance page; chat ("version 2 went live on 3 October") | `POST …/golive` (`replace`) |
| Choose the comparison length (7–90 days) | Performance page; chat ("compare over 14 days") | `POST …/window` |
| See each version before/after | Performance page; chat ("what changed after I updated my title?") | `GET …/versions?sku&marketplace`; also `performance.versionAnalysis` on the M7 compare answer |
| See what is still missing | Performance page; chat ("what performance data is missing?") | `GET …/mappings` (`missing`) |

In chat, a SKU link, go-live date or comparison length is **proposed on a card with a Save button**; typing "yes" saves nothing. Replacing an earlier statement needs an explicit second click (`replace=true`); the earlier statement stays in the history.

## 2. Data model (migration `20261031_0010`, slim-cmo tree; `20261031_0031`, backend tree)

All tables: tenant-owned, `ENABLE`+`FORCE` RLS, application role `SELECT, INSERT` only (append-only).

* `cmo_perf_import` — one row per imported file: marketplace, file name, SHA-256 (**unique per tenant**: the same file cannot be imported twice), period start/end, rows saved/skipped, metrics found, who, when.
* `cmo_perf_line` — one row per (marketplace, report SKU, date), **unique** (a duplicate reporting record is never stored twice and never overwritten). `impressions, clicks, orders, units, sales_paise` are nullable `bigint ≥ 0`: **a metric the report does not carry is NULL, never zero.** Composite FK to the import.
* `cmo_perf_setting` — the seller's comparison length, `CHECK 7..90`, newest row is current.
* `0031` widens `investigation_message_choices_shape` so a CEO answer may carry a `LISTING_PERFORMANCE` card (data only).
* Reused unchanged: `cmo_listing_sku_link`, `cmo_listing_golive` (B8). Their history is the audit trail (who, when, every earlier value).

Both migrations were verified on a fresh scratch database (full chain to slim-cmo `0010` and backend `0031`): up; app-role RLS, check, unique, foreign-key and no-UPDATE/DELETE rejections; downgrade refused while rows exist; down/up round trip with FORCE RLS true on all three tables; `0031` downgrade leaves the constraint `NOT VALID`, upgrade restores it validated.

## 3. Import rules (`slim_cmo/history/report_import.py`, `services/cmo_perf_import.py`)

* Accepted: `.csv` (UTF-8 or Windows-1252; comma, semicolon or tab) and `.xlsx` (first sheet, cell values only; formulas are never evaluated). Up to 10 MB and 50,000 rows.
* Required columns: **Date**, **SKU**, and at least one of **Impressions, Clicks, Orders, Units Sold, Sales** (a short documented list of header synonyms; nothing is guessed from a similar name — *page views are not impressions*). The seller chooses the marketplace; a row naming another marketplace is an error.
* Dates `YYYY-MM-DD` or `DD/MM/YYYY` (day first), `3 Oct 2026`, or Excel dates; impossible or future dates are errors. Counts are whole numbers ≥ 0; sales are rupee amounts with at most two decimals, stored as integer paise (no floats). Blank, `-`, `N/A` = **missing**, not zero.
* CTR / conversion-rate columns are **not stored** (a rate cannot be added across days); rates are recomputed from counts. A report with only rates therefore supplies no metric and is refused.
* Clicks > impressions is an error; orders > clicks is a warning (the rate is shown from the counts as reported).
* Repeated rows with identical numbers count once; repeated with different numbers is an error. A row with no values is skipped, never saved as zero.
* **Preview** saves nothing and shows: problems (first 30 + total), notes, ignored columns, period, new vs already-saved rows, conflicts and a sample (missing shown as "—"). **Import** requires the previewed SHA-256, is refused for invalid files, an exact repeat (409 `ALREADY_IMPORTED`), a changed file (409 `FILE_CHANGED`), rows that already exist with different numbers (409 `CONFLICTING_RECORDS`) and files with nothing new (409 `NOTHING_NEW`). A concurrent repeat is caught by the unique constraint.
* **Manual import only.** Metrion has no live connection to any marketplace; the seller downloads the report and uploads it. Marketplace-specific column layouts beyond the documented headers are not supported (the seller renames headers).

## 4. Metrics (`slim_cmo/history/metrics.py`; integers only)

* Totals for a period are shown **only when** (a) every report row in scope carries the metric and (b) imported reports cover every day of the period. Otherwise `NOT_ASSESSED` with the reason ("Imported reports leave 3 of 7 days uncovered…", "2 of 9 report rows have no clicks…"); a metric no report carries is `UNAVAILABLE`. A day is *covered* when it falls inside the declared period (first to last report date) of an import for that marketplace; a day inside that period with no row for a SKU is the report's statement of no data for it and is not counted as zero.
* CTR = clicks ÷ impressions and conversion rate = orders ÷ clicks, in basis points, half rounded up; undefined when the denominator is zero (NOT_ASSESSED, never 0%).
* Previous period = the equal-length period immediately before. Differences: absolute; relative (basis points) only for counts whose earlier value is above zero; rates differ in percentage points. A difference is calculated only when both periods are fully assessable.
* Sales are a straight sum of the seller's reported values (SQL `SUM` over stored integer paise), shown as reported revenue — not profit, not net of fees or tax.
* The dashboard default period is the seller's comparison length (else 30 days) ending at the last imported date; a custom range is 1–366 days and needs both ends.

## 5. Before/after each version (`services/cmo_perf_view.versions`, reusing `performance.assess`)

For each saved version with a seller-confirmed go-live date *g* and comparison length *N*: **following** = *g … g+N−1*, **previous** = *g−N … g−1* (equal length by construction). The pair is passed through the existing `performance.assess` comparability check per metric (same source/measure, same length, no overlap). Rejected / not assessed:

* no SKU link, no go-live date for the version, or no comparison length → `NOT_ASSESSED`, each item named;
* any day of either period not covered by imports → `NOT_ASSESSED` ("covered: 0 of 7 days before…");
* another version's go-live date inside *g−N … g+N−1* → `INCOMPARABLE` (`OVERLAPPING_PERIODS`).

Comparable output is worded as observation ("Impressions was higher in the 7 days after version 1 went live than in the 7 days before (700 → 1,400).") and always carries `attribution: NOT_ATTRIBUTED` and the note that the change is not shown to be the cause and that the go-live date is the seller's, unverifiable by Metrion. A go-live date is never inferred from creation, approval or copy.

## 6. Observations and suggested actions

`metrics.insights` builds each observation from the measured figures with fixed templates (no model): *impressions up, CTR down*; *clicks up, conversion flat* / *down*; *orders down*; *sales up, units stable*; *impressions down*; *no clear change*; *insufficient data* (one item and nothing else). Each carries: what happened; supporting figures with both periods; "why it may matter" (explicitly labelled possible, not measured); a practical next step; limits (including that two periods are compared, not a cause). "Flat/stable" tolerances are fixed display constants (rates < 0.10 point; counts < 5%), not statistical tests.

Suggested actions map to existing capabilities and **never edit or publish anything**: CTR down → review title clarity and keyword relevance (M3/M2); conversion down → review listing content and buyer questions (M5); impressions down → review keyword evidence (M2); a revision, if wanted, is a normal M6 request that goes through the CEO plan card, approval and audit. The suggested sentences are examples of what to ask; their routing relies on the normal CEO classifier and was not exercised by these tests.

**Decision for the owner:** insights are deterministic text, so no model is involved and no credit is spent. A model-written explanation layer would add cost, a new narration surface and a required eval (CLAUDE.md "LLM evals": no number outside the cited figures, no dropped disclaimer, no narrating a non-result). It has not been added; acceptance row M8-11 is therefore PARTIAL.

## 7. CEO chat (`ceo/cmo_performance_chat.py`)

Closed set of intents recognised by code before the M7 history handler (free; no model; footprint-tested): overview/trends, lowest CTR/conversion across the seller's own listings, "which listing should I improve first" (lowest CTR, with the action and a no-guarantee line), version before/after, what is missing, import help, connect SKU, go-live date, comparison length. One short clarifying question when the product, marketplace, version or date is open (and the next short answer completes it). It never assumes a version is live, refuses a future date or a date before the version existed, accepts only SKUs found in the seller's own reports, and reads only the caller's tenant. M7 phrases ("show my listing history", "compare version 1 and version 2") are unchanged.

## 8. Frontend

* `/dashboard/cmo/performance` (linked from the CMO page): filters (marketplace, product, date range), seven metric cards with source/period/coverage, a per-metric trend (gaps for missing days, table alternative), "what stands out", report import with preview, "what I still need from you" (SKU links, per-version go-live dates, comparison length, history), and the before/after view.
* CEO chat card `LISTING_PERFORMANCE` (overview, ranking, versions, missing, clarify, confirm link/go-live/window with Save).
* Status is shown with words and marks (▲ ▼ ✓ ✗ ○), never colour alone; no animation; numbers formatted from whole integers.

## 9. Acceptance coverage

| # | Criterion | Status | Evidence |
|---|---|---|---|
| M8-01 | Import and preview supported reports | PASS (automated) | `test_cmo_m8_performance.py` import tests; `ImportPanel` tests; xlsx test |
| M8-02 | Invalid and duplicate imports handled safely | PASS | invalid file, bad type, empty, repeat file, repeated rows, conflicting rows, changed file, partial overlap |
| M8-03 | Performance mapped to products and marketplace SKUs | PASS | link-required filter test; candidates from the seller's own rows; tenant isolation |
| M8-04 | Confirm and update SKU mappings | PASS | page, chat card and API; replace guard + history |
| M8-05 | Confirm go-live dates | PASS | page, chat card and API; future / before-creation refused; never assumed |
| M8-06 | Window configuration controlled | PASS | seller setting 7–90 (UI, chat, API, DB CHECK); operator config remains a fallback; no default |
| M8-07 | Dashboard metrics correct | PASS | pure unit tests (rounding, rates, money format) + integration totals |
| M8-08 | Periods and coverage validated | PASS | uncovered day → NOT_ASSESSED; overlap → INCOMPARABLE; equal length |
| M8-09 | Versions connected to observations | PASS (UI: performance page and chat) | `versions` view + `performance.versionAnalysis` on the M7 compare answer; the M7 compare card still shows the older sales-order block and does not render `versionAnalysis` |
| M8-10 | Missing data stays unassessed/unavailable | PASS | every metric/period test |
| M8-11 | AI insights grounded in stored metrics | **PARTIAL** | grounded and tested, but deterministic text; no model-written explanation (owner decision, §6) |
| M8-12 | Recommendations connect to CMO workflows | **PARTIAL** | actions name M2/M3/M5/M6 and a sentence to ask; no one-click hand-off; routing of those sentences not exercised |
| M8-13 | CEO chat supports the workflow | PASS for the closed intent set | `test_ceo_cmo_m8_performance_chat.py` (10); regex intents, not a real classifier; seller phrasings outside the set go to the rest of the CEO |
| M8-14 | Frontend and backend integrated end to end | **PARTIAL** | API ↔ UI contract and components tested separately with fakes; **no browser run** |
| M8-15 | Tenant isolation, RLS, billing, audit intact | PASS | RLS/append-only checks, cross-tenant tests, zero-unit footprint assertions, regression files |
| M8-16 | Focused tests pass | PASS | see `CMO_RELEASE_BLOCKERS.md` for the exact run |

## 10. Open items and limits

* Not browser-verified; no real seller data; no real marketplace report layouts (B1/B7 unchanged).
* Marketplace-specific export formats (Amazon Business Reports, Flipkart traffic, Meesho) are not parsed natively; headers must match the documented names.
* A day inside an import's declared period with no row for a SKU is treated as "report has no data", not as zero and not as missing coverage; sellers whose reports omit zero-activity days will see totals for the covered period.
* One imported record is never changed by a later file (conflicts are refused); correcting a wrong import needs an operator action.
* Insights have no seasonality, price or advertising context; they compare two periods only.
