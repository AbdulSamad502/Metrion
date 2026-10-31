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

**Decision:** insights stay deterministic text, so no model is involved and no credit is spent. A model-written explanation layer would add cost, a new narration surface and a required eval (CLAUDE.md "LLM evals"); it is a future enhancement, not a current blocker.

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
| M8-11 | AI insights grounded in stored metrics | PASS | every insight is assembled from measured figures with both periods named; possible explanations are labelled as possible; missing or incomplete data yields one "not enough data" item and no trend; no model is used (decision: deterministic text is the default; model-written explanations are a future enhancement, not a blocker) |
| M8-12 | Recommendations connect to CMO workflows | PASS (draft hand-off) | each insight with a known product and marketplace links to the CEO hub with the question ready (§6a); each of the four sentences is tested to reach its existing free workflow; the seller presses send |
| M8-13 | CEO chat supports the workflow | PASS for the closed intent set | `test_ceo_cmo_m8_performance_chat.py` (10); regex intents, not a real classifier; seller phrasings outside the set go to the rest of the CEO |
| M8-14 | Frontend and backend integrated end to end | **PARTIAL** | API, chat and components tested separately (fakes on the UI side); flows reviewed (§6b); **browser verification NOT DONE** |
| M8-15 | Tenant isolation, RLS, billing, audit intact | PASS | RLS/append-only checks, cross-tenant tests, zero-unit footprint assertions, regression files |
| M8-16 | Focused tests pass | PASS | see `CMO_RELEASE_BLOCKERS.md` for the exact run |

## 10. Open items and limits

* Not browser-verified; no real seller data; no real marketplace report layouts (B1/B7 unchanged).
* Marketplace-specific export formats (Amazon Business Reports, Flipkart traffic, Meesho) are not parsed natively; headers must match the documented names.
* A day inside an import's declared period with no row for a SKU is treated as "report has no data", not as zero and not as missing coverage; sellers whose reports omit zero-activity days will see totals for the covered period.
* One imported record is never changed by a later file (conflicts are refused); correcting a wrong import needs an operator action.
* Insights have no seasonality, price or advertising context; they compare two periods only.

## 6a. One-click hand-off (closure pass)
An insight whose product and marketplace are known carries `action.draft`. The performance page and the version panel show a link to `/dashboard/ceo-hub?ask=cmo&kind=<TITLE|KEYWORDS|CONTENT|REVISE>&about=<product>&mp=<MARKETPLACE>`. The hub turns a known kind and marketplace back into a fixed sentence in the chat bar (arbitrary text cannot be injected); **the seller presses send; nothing runs on arrival.** The sentences are answered by existing free code, so no new routing, billing or approval path exists:

| Insight action | Sentence | Reaches |
|---|---|---|
| Low CTR (title, keyword relevance), keyword evidence | "What should I improve next in my {product} listing on {marketplace}?" | M7 recommendations from the saved audit, confirmed facts and M2 keyword evidence |
| Low conversion / content | "What questions will buyers ask about my {product}?" | M5 buyer-question and readiness card |
| Revision | "Show my latest {product} listing on {marketplace}" | the saved version with its own audit; an M6 rewrite is then a normal plan card with approval and billing |

Tested in `test_ceo_cmo_m8_performance_chat.py` (each sentence reaches the stated card; footprint of generations, units and model calls unchanged). Limit: title analysis (M3) and keyword research runs are paid/planned flows and are deliberately not started from a link; the advice view is the hand-off. Without a known product (all-products dashboard) no link is offered.

## 6b. End-to-end review (closure pass)
Reviewed: import → preview → import → dashboard; SKU link; go-live date; before/after; chat cards and Save; error handling. Findings: typing "yes" (or "confirm") after a SKU, go-live or window proposal saves nothing (tested for go-live and window; SKU tested earlier); replacing an earlier SKU link or go-live date returns 409 until `replace` is sent, and the page and card ask first (tested at API, page and card level); a repeated identical date is a repeat, not a change; all errors carry a plain `detail` the UI shows. **Browser verification: NOT DONE.** It needs a signed-in session on a database holding seller records; this pass used synthetic data only and, per the standing rule, creates no records in the shared development tenant. M8-14 stays PARTIAL until a controlled walkthrough is run.

## 6c. Correcting a wrong import: deferred (design)
Not built; kept out of this pass because it needs a new table and changes every read. Safe design for a follow-up: an append-only `cmo_perf_correction` (tenant, line id, replacement metrics or "void", reason, who, when, confirmed flag) with FORCE RLS and INSERT/SELECT only; the original `cmo_perf_line` is never updated or deleted; `daily()` reads the newest correction per line (LEFT JOIN LATERAL) so totals use the corrected view while the original stays as evidence; a correction is proposed on a card and needs an explicit Save; `ALREADY_IMPORTED`/conflict rules are unchanged. Until then a wrong import is corrected by an operator and the seller can only re-import a corrected file under a different date range or SKU.

## 6d. Missing daily rows: decision
Unchanged and conservative: a missing row is never zero. A day is covered only inside an import's declared period; a day inside it with no row for a SKU counts as "the report has no data", not zero activity; incomplete coverage keeps the metric NOT_ASSESSED. Zero-treatment is introduced only if a marketplace's own documentation confirms that an absent row means zero activity (none has been confirmed; no marketplace semantics are inferred).

## 6e. Frontend timeout cause (closure pass)
The failing tests (`ceoDecide` price-impact, `ceoAttach` first upload, `ceoInput`, `ceoSendFailure`) are each the FIRST test of a file that renders the whole CEO Hub tree in jsdom; alone that first render costs 1-2 s. With all 12 cores running 60+ files in parallel it passed the 5 s limit. The same group run on the previous commit (`8ab58ea`) also failed (`ceoDecide` at 5 s), so this is not an M8 regression and not a test-isolation bug. A first attempt (`userEvent` `delay: null`) did not remove the failures and was reverted. Fix: `maxWorkers: "50%"` in `vitest.config.mts`; no timeout was raised. Result: `components/ceo` + `components/cmo` + `lib` = 62 files, 570 tests, all passed in 106 s.

## 11. Closure-pass verification
Backend (scratch DB, port 5545): test_cmo_m8_performance.py, test_cmo_b8_performance.py, test_ceo_cmo_m8_performance_chat.py (13, including the hand-off and typing-yes tests), test_ceo_cmo_m7_history_chat.py, test_cmo_m7_history.py, test_cmo_p5_unit.py, test_ceo_architecture.py, test_request_contract_snapshot.py = 432 passed in 2m45s. slim-cmo history + purity + no-float = 314 passed. Frontend: components/ceo + components/cmo + lib = 62 files, 570 tests passed in 106 s (before the vitest worker change the same group failed 4 first-render tests at 5 s, and failed ceoDecide on 8ab58ea too); tsc --noEmit clean; eslint clean on changed files. Schema: no migration in this pass. Not run: the full backend, frontend and slim-cmo suites and the earlier six-file regression set (no code they cover changed); browser verification NOT DONE; no real data.
