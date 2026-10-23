# CFO 2.0 acceptance matrix (2026-10-23)

Status words: **Passed** (an automated test or a recorded benchmark proves it) · **Partial** (part proved, the rest named) · **Not built** · **Deferred** (decided, in writing) · **Manual** (needs a person: a browser, a real file, a CA).
Each row names where the proof lives. The authority for every criterion is its own spec; this page only states where each one stands. Nothing here claims a real-LLM result: no real model was called this cycle (mocked LLM only).

## Data intelligence (`cfo-data-intelligence.md`)

| Criterion | Status | Proof / note |
|---|---|---|
| AC-D1 bounded memory (large files) | Passed (as re-worded) | `docs/evaluation/cfo-2-ac-d1-large-file-benchmark.md`; 4-file 80,000-row run re-done after the merge (`cfo-2-ingest-benchmark.md`) |
| AC-D2 known formats identical to old path | Passed | golden comparison tests in `packages/data-foundation` |
| AC-D3 – D5 proposals, mapping rules, failed job leaves nothing | Passed | data-foundation + `test_cfo_*` integration suites |
| AC-D6 / D6b / D6c duplicates and overlap | Passed | integration tests; held-row **resolution choices** `SUPERSEDE_WITH_THIS` / `KEEP_BOTH_WITH_REFERENCE` are **Not built** (see below) |
| AC-D7 – D10 provenance, PII, tenant, zip-bomb | Passed | unit + integration |
| AC-D11 expense duplicates held | Passed | built in Phase 3a |
| AC-D12 benchmark report before any performance claim | Passed | the two reports above |
| Real-file check (Meesho zip, mock MTR) | Passed for the formats found; **Manual** for your own files | CP-E fixes: wrong-dimension xlsx, TCS sales vs return, `d-Mon-yy` dates, with regression tests |

## Query planner (`cfo-query-planner.md`)

| Criterion | Status | Proof / note |
|---|---|---|
| AC-P1, P2, P4, P6 – P11 | Passed | `test_planner_*`, `test_cfo_query_route.py`, oracle suite |
| AC-P3 fast path equals engine | Partial | holds for the two SQL metrics; the other metrics run through Brain 1's own code (exact by construction, not a fast path) — §16.2 |
| AC-P5 legitimate one-to-many | Partial | validator level only; no executed plan uses a join |
| AC-P12 stage events stream, no figures | **Passed (2026-10-23)** | planner stages PLANNING / VALIDATING / CACHED / QUERYING / FINALIZING reach the chat turn as `CFO_*` events (names only) through `services/ceo_progress.py`; frontend labels "Asking the CFO: …"; `test_ceo_progress_stages.py`, `ceoModel.test.ts` |
| Measured real-LLM planner/classifier quality | Deferred | decided in §12; no real model called |
| Redis cache live test | Deferred | process-local cache is correct; no live-Redis test run |

## Expense ledger (`cfo-expense-ledger.md`)

| Criterion | Status | Proof / note |
|---|---|---|
| AC-L1 – L11 | Passed | `test_cfo_expense_ledger.py`, `test_planner_ledger_metrics.py` (real DB) |
| One expense source: CFO ledger authoritative, Tracker compatible | **Passed (2026-10-23)** | decided 2026-10-23 (§14.4). The CEO expense chat now reads and writes the ledger; the explicit Tracker → ledger bridge (preview + sync, idempotent, no double count, no silent migration, carries payment status) is kept; `test_expense_bridge.py` (5), `test_ceo_expense_tracker_chat.py` (26). A chat-added expense has no confirmed class, so it moves Operating Profit only after the seller confirms one (suggest-only) |
| Payment states UNPAID / PARTIALLY_PAID / PAID (§14.5) | **Passed** | append-only `expense_payment_event`; "not stated" when no statement; a partial payment must be above zero and below the whole; never moves a profit figure; calc-engine unit + integration, route and chat tests |
| Auditable void reason (§14.5) | **Passed** | required (3 to 300 chars), stored on the void row with who / when / which entry; the database refuses a new void row without a reason; routes and chat require it |

## Expense Tracker through the CEO (`ceo-expense-tracker-chat.md`)

| Criterion | Status | Proof / note |
|---|---|---|
| AC-X1 – X12 (add, show, change, remove, mark paid, mention → ask, period reads, approval card is the only save path, tenant and permission checks) | Passed | `test_ceo_expense_chat.py` (81), `test_ceo_expense_tracker_chat.py` (22), guard tests for approval gate, effects, architecture, periods |
| Wording quality of the guided questions with a real model | Deferred | the conversation is rule-driven (no model decides a field); no real-LLM run |

## Phase 3 scope (`cfo-phase3-scope.md`)

| Criterion | Status | Proof / note |
|---|---|---|
| AC-B1 – B7, C1 – C6, D2 – D5, E1 – E6, F1 – F5 | Passed | recorded in the spec (C2 for Meesho only) |
| GST treatment | Deferred | stays unconfirmed; GST is indicative, not filing-grade |
| CA review | Deferred | skipped by owner decision |

## Dashboard and UI (`cfo-dashboard*.md`)

| Criterion | Status | Proof / note |
|---|---|---|
| AC-UI1 / AC-DI1 no client money math | Passed | `noClientMath.test.ts` covers v2 |
| AC-UI2 – UI5, DI2 – DI5 trust metadata, UNAVAILABLE never 0, wording, same truth as CEO | Passed | component tests and same-truth backend test |
| AC-UI6 / DI6 server-side filters, exports, URL state | Passed | |
| AC-UI7 / DI7 existing sections reachable | Passed | |
| AC-UI10 owner block hidden without `financials.adjust` | Passed | |
| AC-UI8 / AC-DI9 layout at 375 / 768 / 1280 px | **Manual** | not checked in a browser this cycle |
| AC-DI8 manual mapping and held-row resolution flows | Partial | upload, progress, mapping review/confirm built; manual mapping and the two held-row resolutions are not |
| SKU concentration and margin-stability panels | Not built | named in the spec as later |
| Deep links carrying context refs | Not built | |
| Export audit log | Not built | |

## Unified financials (`cfo-unified-financials.md`)

| Criterion | Status | Proof / note |
|---|---|---|
| AC-U1 – U10 | Passed | unit + integration; U7 CA pack carries provenance and lists open items (CA review itself Deferred) |

## Left for you (manual verification) — see `cfo-2-manual-verification.md`

1. Run the mock MTR set and your real Meesho zip through Upload and read the numbers against the source files.
2. Click through each CFO tab and the CEO expense conversation (add, show monthly / date-wise, change, remove, mark paid, and mention an expense in passing).
3. Check the layout at phone, tablet and desktop widths.
4. Try the bridge: add an expense in the Tracker (or in chat), call `GET /cfo/ledger/tracker-bridge`, then `POST` it, and confirm Operating Profit moves once and a second POST changes nothing.

## Unfinished features (built-order backlog, none blocks manual verification)

1. Held-row resolution choices `SUPERSEDE_WITH_THIS` and `KEEP_BOTH_WITH_REFERENCE`; manual mapping flow.
2. SKU concentration and margin-stability panels; deep links carrying context; export audit log.
3. A payment-status editor and a removal button on the CFO Expenses tab (the tab shows payment state read-only; changes are made through the CEO or the routes).
4. Responsive check at 375 / 768 / 1280 px in a browser; real-LLM evaluations (planner, classifier, narration); live-Redis test.
5. CA review and GST treatment confirmation (deferred by decision).

## Known failures outside CFO (PI / Tavily), tracked separately

See the "Known failures" section of the final report for this run. Any PI or Tavily test that fails is listed there with its error and is not counted against the CFO criteria above.
