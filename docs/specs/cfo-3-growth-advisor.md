# CFO 3.0: financial intelligence and business growth advisor (audit, root causes, specification, roadmap)

**Status:** specification and audit, 2026-10-23. Phase 0 fixes marked **DONE** below are built and tested; everything else is **not built**. Nothing in section 5 is a real system output: it is the simulated, expected behaviour that Phase 1 to 4 must reach.
**Prerequisites:** `cfo-agent.md`, `cfo-unified-financials.md`, `cfo-expense-ledger.md`, `cfo-query-planner.md`, `ceo-agent-orchestration.md`, `ceo-expense-tracker-chat.md`, `deterministic-engine.md`.
**Hard rules carried in (unchanged):** the LLM explains numbers and never computes them; money is signed integer paise; a missing input is "not yet calculable", never zero; every figure cites a result reference; one authoritative ledger; the seller talks only to the CEO; the CFO recommends and never acts on a marketplace; writes only after an approved plan card; tenant isolation is the boundary.

## 1. What exists today (verified in this build unless marked)

| Area | State | Evidence |
|---|---|---|
| Marketplace file ingestion (CSV/XLSX), mapping, held rows, duplicate protection, provenance | **Built, tested** (known formats recognised; unknown formats need the seller's one-time column mapping) | `test_cfo_uploads_jobs`, `test_cfo_user_sample_files`; real Meesho workbooks and the 3 mock reports ingested end to end |
| Attachment in CEO chat | **Read only by design**: totals are summed by code and the answer says "nothing was imported". There is **no approved import action in chat** | `services/ceo_attachment_analysis.py`; no `cfo.import_*` registry key |
| Gross sales, fees, SKU and marketplace tables, cost breakdown, overview | **Built, tested** | dashboard routes `/cfo/overview`, `/profitability/*` |
| Net revenue, contribution profit, operating profit | **Built, deterministic; unavailable until inputs exist** (cost per unit, return/cancel/RTO status, refund amounts, ad spend) | engine formulas; `cfo_actions.assemble_canonical_lines_for_period` |
| Expenses through the CEO (add, show, change, remove, paid/unpaid/partly paid, void reason, mention question) | **Built, tested, on the CFO ledger** | `test_ceo_expense_tracker_chat.py` (28) |
| Tracker to ledger bridge | **Built, tested** | `test_expense_bridge.py` |
| Cash: expected settlements, payables | **Dashboard only**; no CEO saved-state question for cash | `/cfo/cash/*`, no `QT_CASH` |
| Leak Shield, claim drafts, CA workbook | **Built**; Amazon/Flipkart findings provisional | `leak-findings`, `ca-export` |
| Landed cost, batch size, pricing, funding-readiness evidence, anomalies, strategic briefing | **Built as separate actions**; funding readiness is a reduced slice (no margin stability, no concentration) | `cfo_actions`, `/cfo/funding-readiness` |
| Open financial questions (planner) | **Built; needs a planner model switched on** | `/cfo/query`, `CFO_PLANNER_MODEL` |
| Forecasting, working-capital and funding-gap calculator, loan scenarios, inventory reinvestment, ad budget planner, growth scenarios, expansion advisor, goals roadmap, proactive briefings, scenario storage | **Missing** | none of these exist |

Not verified in this audit: behaviour of every older CFO action with a real model, the full 7,500-test backend suite (not re-run after the latest changes), mobile layout.

## 2. Root causes of the failed conversation (from the transcript and the code)

1. **Attachments never became records.** The CEO's attachment reader is intentionally read-only and the chat has no import action. Every later financial question therefore read an empty ledger. Both statements were true; the seller was never told the one thing that matters ("add these to your financial records, here is how"). *Open (Phase 0b).*
2. **Dashboard not updated** is the same fact: nothing was written, so there was nothing to refresh. A preview must never look like ledger data; the fix is the import workflow, not a refresh hook.
3. **"Which period?" loops.** `orchestrator._resume_plain_question` treated any reply of 8 words or fewer, without a question mark, as the answer to the CEO's open question. "Add ₹5,000 as office rent for yesterday" (7 words) was swallowed as the "period". *DONE: a message that a plain rule reads as a request, or that is not a period when a period was asked, is a new request.*
4. **Period parser gaps.** "1 September to 31 October 2025" failed ("ends before it starts": the year applied only to the end); "August and September 2025", whole years and "this year" were unrecognised. *DONE.* Calendar quarters (Q1 to Q4) are deliberately **still unresolved**: an Indian financial-year quarter differs, so it is a decision (D2).
5. **"Add ... as office rent" not recognised** as an expense (the rule needed the word "expense"). *DONE for amount plus a cost word.*
6. **Raw engine text as the answer** ("available for 0/1 of lines, below the required 19/20"). *DONE for the saved-results template*: one plain explanation of what cannot be calculated and what is needed, with the technical detail left on the CFO page. The LLM-narrated path still receives the raw gaps (Phase 1).
7. **Cash question answered with listing content; growth question answered with a discount confirmation.** There is no cash question type among the closed saved-state questions, so the classifier fell back to a wrong one; and a half-finished competitor-price input session was still open, so a later unrelated message was parsed as its answer ("I am still not using the discount, offers, price until you confirm them"). *Open (Phase 0c): add `QT_CASH` and growth/health question routing; an unrelated message must close an open input session, as the period question now does.*
8. **Multi-intent messages** are handled one request per message by design (the CEO says what it did and did not handle). Acceptable, but the wording to the seller should offer to continue with the next part. *Phase 1.*

## 3. CFO 3.0 product specification (condensed)

Five questions every answer is organised around: where is my money going; where am I making and losing money; how much cash do I have and need; what growth can I afford; what next and why. Every substantive answer carries: direct answer, evidence with sources, interpretation, risks and limitations, one recommended next step, and a dashboard link when something was persisted.

Three labelled layers, never mixed: **facts** (recorded data), **forecasts** (deterministic projections from stated assumptions, each with its assumptions listed), **recommendations** (interpretation and trade-offs).

| # | Feature | Engine owner | Key rules |
|---|---|---|---|
| F1 | Financial health intelligence | calc-engine metrics + CFO bands | no composite score without a validated method; top three problems with measurable impact only |
| F2 | Cash forecast 7/30/60/90 days | new `cash_forecast` formula | separate contractual obligations, observed patterns, speculative assumptions; opening cash is seller-stated, never inferred |
| F3 | Working capital and funding gap | new formula | a requirement calculation, not a borrowing recommendation |
| F4 | Loan and funding scenarios | new `loan_schedule` formula (EMI, total cost, coverage) | hypothetical only; no eligibility or suitability claim |
| F5 | Inventory reinvestment | combines SKU margin, velocity, returns, MOQ, lead time, landed cost, reserve | maximum affordable is not the safest quantity; history is not guaranteed demand |
| F6 | Advertising budget planner | CFO constraints, CMO strategy | break-even ACOS, contribution after ads, caps from cash |
| F7 | Growth scenario simulator | scenario engine (conservative, base, aggressive) | every scenario lists assumptions; stored apart from actual transactions |
| F8 | Expansion advisor | CFO unit economics + PI/CI/CMO evidence | no invented demand or competitor data |
| F9 | Early warnings | planner + thresholds | each alert: evidence, severity rationale, impact, action |
| F10 | Goals and roadmap | goal store + milestones | measurable milestones, monitoring metrics |
| F11 | Proactive briefings | scheduler | only data-backed alerts or labelled forecasts |
| F12 | Conversational workspace | CEO context | follow-ups ("why", "what if", "save this scenario") reuse the active scenario without leaking into unrelated requests |

**Data contracts to add (all additive, all tenant-scoped, FORCE RLS, append-only where history matters):** `cash_opening_balance` (seller-stated, dated), `financial_scenario` + `scenario_assumption` + `scenario_result` (separate from the ledger), `loan_scenario`, `financial_goal` milestones, `import_plan` (the approved chat import). No second ledger.

## 4. Architecture

`Attachment (read only) -> import plan (CEO card: file, detected type, row count, date reading, what will be added) -> seller Approve -> existing upload pipeline (mapping if needed) -> sales_line/ledger -> read-model version bump -> calculation -> dashboard + CEO answer`. The import reuses `/cfo/uploads` and the mapping/confirm machinery; the CEO never writes canonical rows itself. Known formats import with one approval; unknown formats (the three mock reports) hand the seller to the one-time column mapping, then import. Cache invalidation is by the existing `cfo_read_model_version`.
Scenario results are computed by calc-engine formulas and stored with their assumptions; the CEO narrates stored results only. Cross-agent work (F6, F8) uses the existing CEO delegation: PI/CI/CMO supply evidence, CFO supplies constraints and unit economics, the CEO writes the synthesis.

## 5. Saad's journey: expected behaviour (SIMULATED, not system output)

Amounts other than those from the mock reports are hypothetical inputs.

| Scene | Saad asks | Route | Needs | Dashboard effect | Gap today |
|---|---|---|---|---|---|
| 1 | "What can you do?" | CEO greeting | none | none | works (rule-based) |
| 2 | Attach 3 reports, "add to my dashboard" | CEO attachment read -> import plan card -> Approve -> upload pipeline | file bytes, mapping for unknown formats | uploads job, rows, gross sales by marketplace appear | **no chat import action** (Phase 0b) |
| 3 | September performance | BUSINESS_BRIEFING / `cfo.query` | imported lines | overview figures | works once imported; wording improved |
| 4 | "Why can't you calculate profit?" | QT_DATA_GAPS | costs, returns, refunds | none | now one plain list; guided collection is Phase 1 |
| 5, 6 | Best products; which marketplace | `cfo.query` over SKU and marketplace | cost per unit, returns | By SKU / By marketplace | needs planner model + costs; never ranks by gross alone |
| 7 | Rent expense, partly paid, monthly expenses | expense actions (approval card) | none | Expenses tab | **built** (28 tests) |
| 8 | Money held by marketplaces | Leak Shield | settlement + order reports | Leak findings | built; "no findings" is not "no problem" |
| 9, 10 | Next 30 days; settlement delayed 15 days | F2 | opening cash, payables, settlements | Cash & Tax | **F2 missing**; expected receipts and payables exist on the dashboard only |
| 11, 12, 13 | Loan readiness; funding gap; loan comparison | funding-readiness evidence; F3; F4 | history, cash, assumptions | scenarios | readiness evidence built; F3/F4 missing |
| 14, 15 | Puma budget; reorder priorities | landed cost + batch size; F5 | supplier quote (approved), margins | none | quote flow built; F5 missing |
| 16, 17, 18 | Ad budget; match competitor; new product | F6, CI+CFO, F8 | evidence from CMO/CI/PI | none | F6, F8 missing; CI/PI/CMO exist separately |
| 19, 20, 22 | Scenarios; 90-day plan; what-if | F7, F10, F12 | assumptions | scenarios, goals | missing |
| 21 | Monitoring | F9, F11 | thresholds | alerts | risk scan exists (off by default); briefings missing |

## 6. Roadmap

| Phase | Content | Gate |
|---|---|---|
| **0 Repair** | 0a routing and clarification contamination **DONE**; period parser **DONE**; plain missing-data wording (template path) **DONE**; 0b approved chat import (`import_plan`); 0c `QT_CASH` + growth/health routing + closing stale input sessions; 0d LLM-path wording | the real transcript replays without a wrong or looping answer; an attached file becomes ledger rows only after Approve |
| **1 Foundation** | health briefing with top three problems, SKU/marketplace comparisons on imported data, guided cost collection, risk list | calculation oracle tests; every figure cited |
| **2 Growth finance** | F2, F3, F4, F5, F6 as calc-engine formulas with oracle tests | arithmetic tests to the paisa; assumptions always listed |
| **3 Advisor** | F7, F8, F10, F11, F12, 90-day plan | scenarios reproducible; specialist evidence cited |
| **4 Hardening** | full journey tests, permissions, performance, mobile | the 22 scenes pass as written |

## 7. Decision register (needs the owner)

- **D1** Chat import: may a known-format attachment import with a single approval, or must the seller always open the Data & imports page?
- **D2** Quarters: Indian financial-year or calendar quarters (until decided, unresolved).
- **D3** Opening cash: seller-stated balance only, or also derived from settlements? (Recommended: stated only.)
- **D4** Where scenarios live (a new `financial_scenario` store, recommended) and whether the CEO may save one without a card.
- **D5** Lending boundary wording for India: what the product may say about funding readiness.
- **D6** Whether the advisor may name a "safe" purchase quantity or only show constraints.
- **D7** Planner model availability: open financial questions need `CFO_PLANNER_MODEL`; without it the CEO can only answer rule-routed questions.

## 8. Readiness

Reuse: ingestion and mapping, the ledger and its approval cards, the planner and evidence layer, the dashboard services, the CEO delegation. Build: chat import plan, cash question, formulas F2 to F7, scenario store, goal milestones. Blocked on decisions: D1, D2, D3, D5. Recommended first: Phase 0b and 0c (they fix the failure the seller saw), then F2 and F3. Approvals needed before coding Phase 2: D3, D4, D5.
