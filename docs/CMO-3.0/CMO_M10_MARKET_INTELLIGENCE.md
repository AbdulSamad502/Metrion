# CMO 3.0 - M10: Smart Market Opportunities and marketplace news

Status: IMPLEMENTED (backend, database-free, chat, frontend). Unit tests PASSED (see Run results); no integration test exists for M10. Not BROWSER VERIFIED.

## 1. What it is
A free, read-only layer over what the seller has **already researched**. It reads the seller's saved market-trend reports (the paid, approved `cmo.market_trends` flow that already exists) and their own product details, and shows (a) marketplace news and (b) opportunities that relate to their products. It performs **no new web search**, calls **no model**, spends **no credit**, and never changes a marketplace listing or setting. With no saved report it says so and shows nothing: no news, source, date, demand, search volume, sales growth, ranking or competitor performance is ever invented.

## 2. Inputs and rules (`slim_cmo.market.intel`, pure, no floats, no clock)
* **News** = the `MARKET_NEWS` findings of the saved reports. Each shows headline, summary, news kind, the marketplaces it names (found in its theme, summary or source titles/addresses; none named = "marketplace not stated", never guessed), every cited source with title, link and publication date, the newest publication date, and whether a source is an official marketplace source (else "third-party: unconfirmed").
* **Freshness** is recomputed against today: FRESH (14 days or fewer), RECENT (60 or fewer), STALE, or DATE_UNKNOWN (undated or future-dated; never called fresh). A report older than 30 days makes the whole answer STALE_REPORTS with a warning.
* **Duplicates**: the same story found in two reports (same normalised theme or any shared source address) is shown once from the newest report with "seen in N reports".
* **Seller impact** is a fixed sentence per news kind (POLICY, FEE, SELLER_PROGRAM, SEASONAL) or "not known from the report". It is advice to read the source, not a claim about the seller's account.
* **Relevance to the seller's products**: shared words between the finding and the product (name and a few confirmed facts), and shared marketplaces with the product's saved listings. HIGH = both (or two shared words when the finding names no marketplace); MEDIUM = one; LOW = neither (not shown as an opportunity); NOT_ASSESSED = the seller has no saved product. The words and marketplaces are listed as the reason.
* **Opportunities** come from the `ADJACENT`, `NEW_PRODUCTS_BUZZ`, `NICHE` and (only when no policy risk was identified) `REPORTED_TACTICS` findings that relate to a product. Each separates: *what the saved sources reported* (verified as reported, not as true; with sources, independent-source count, freshest date, report date), *a possible explanation (not measured)*, the **evidence strength** (STRONG / MODERATE / WEAK / NOT_ASSESSED from the corroboration stored in the report, downgraded to WEAK when the freshest source is old or undated), **demand = UNAVAILABLE** (always), and next steps.
* **Ranking** ("which should I focus on"): relevance, then evidence strength, then freshness, then newest, then title; no score and no forecast, and the reason is shown.
* **Next steps** are fixed templates: YOU (read the source), PI (research the topic), CMO (check the listing / buyer questions / improve next), CFO (check margin / fee impact), each with a suggested question that is sent to the CEO only when the seller presses its button.

## 3. Backend
`services/cmo_market.py`, `repositories/cmo_market_repo.py` (reads `cmo_trend_report`, tenant-scoped under RLS), routes `GET /api/v1/cmo/market-intelligence`, `/news`, `/opportunities` (filters `sku`, `marketplace`; permission `agent.cmo`; read-only; zero units). No new table. Unknown product -> 404; unknown marketplace -> 422.

## 4. CEO chat (`ceo/cmo_market_chat.py`, card kind `MARKET_INTELLIGENCE`, migration `20261101_0033`)
"Find opportunities for my products", "Show latest marketplace news", "What has changed on Amazon?" (asks which marketplace when none is named), "Which opportunities should I focus on?", "How does this news affect my products?" and "What should I do about this update?" (the last two use the item the previous card focused on, else the most relevant stored item). The phrases are deliberately narrow: the existing market-research requests ("latest news in ecommerce", "Amazon news") still start the research plan. With no saved report the card says so.

## 5. Frontend
`/dashboard/cmo/market` (`MarketDashboard`): product and marketplace filters, opportunity and news lists with source links and dates, freshness and relevance words, evidence strength, demand UNAVAILABLE, next steps, loading / empty / stale / error states, and "Ask the CEO about this" (a fixed-sentence hand-off, `?ask=market&kind=...`). In the chat, `MarketIntelligenceCard` shows the same items; a suggested question is sent only by its button.

## 6. Limits
* It is only as good as the seller's saved reports; it does not discover anything new. A seller with no saved report sees the NO_REPORT state and the instruction to ask for a market-trends report (a separate paid step they approve).
* Relevance is word and marketplace overlap, not understanding; a finding that describes a product in other words may be rated LOW and hidden.
* Official-source classification depends on the operator-configured official domains (open question Q5). With none configured nothing is called official.
* Marketplace news carries no seller-account facts: "impact" is generic advice.

## 7. Safety
Read-only; tenant-scoped; no model; no outbound request; no write; no billing; nothing published. Never claims demand.

## 8. Status (vocabulary: IMPLEMENTED, AUTOMATED TESTED, INTEGRATION TESTED, BROWSER VERIFIED, PARTIAL, NOT TESTED)
| Capability | Status |
|---|---|
| Opportunities and news from saved reports, sources, dates, freshness, duplicates, relevance, recommendations | IMPLEMENTED. Tests written (`slim-cmo tests/unit/market/test_intel.py`); RUN: 11 passed |
| Read-only routes | IMPLEMENTED. Route-surface test updated; integration tests RUN (20 passed, see run results) |
| CEO chat (six requests, clarification, card) and migration `20261101_0033` | IMPLEMENTED. Routing and answers tests written (`backend/tests/unit/test_cmo_m10_and_pagination.py`); RUN (unit and integration, passed). Migration `20261101_0033` applied to the scratch database only (`metrion_eval`) |
| Frontend page and chat card | IMPLEMENTED. Component tests written (`components/cmo/market/market.test.tsx`); RUN, passed (see run results). Type-check and lint clean. **NOT BROWSER VERIFIED** |
| Official-source recognition | PARTIAL: needs configured official domains (Q5) |
| Live end-to-end with a real saved report | NOT TESTED |

Static checks actually performed on this work: Python byte-compilation of every changed module, the slim-cmo no-float lint, a one-off smoke call of the pure rules and the phrase classifier (six phrases recognised; "latest news in ecommerce", "Amazon news" and other requests not captured), TypeScript type-check and ESLint of the changed frontend. These are not test results.

## Run results (2026-11-01, scratch database metrion_eval)
* Migrations `20261101_0012` (slim-cmo) and `20261101_0033` (backend) APPLIED (upgrade only; heads now 0012 and 0033). Downgrade-with-data refusal for 0012 was NOT exercised.
* slim-cmo `tests/unit/market` 11 passed; `test_p2_purity.py`, `test_lint_no_float.py` passed.
* Backend unit: `test_cmo_m10_and_pagination.py`, `test_cmo_perf_view_products.py`, `test_cmo_p5_unit.py`, `test_ceo_architecture.py`, `test_request_contract_snapshot.py`, `test_frontend_api_paths_exist.py`: passed after fixing two test-data mistakes and the architecture allowlist (the six files were not re-run together in one final run; the two that failed were re-run and passed, 318 passed).
* Backend integration: `test_cmo_perf_correction.py` + `test_cmo_m9_images.py` + `test_ceo_cmo_m9_images_chat.py`: 39 passed. M8 files `test_cmo_m8_performance.py`, `test_cmo_b8_performance.py`, `test_ceo_cmo_m8_performance_chat.py`: 43 passed (after the daily query moved to the effective view).
* Frontend: market, corrections, pagination, performance and images tests, hub guard and test-support: all passed after fixing a duplicate "Marketplace" label; `ceoHubRestore` timed out once under load and passed alone. The full frontend suite was NOT re-run after these changes.
* NOT run: the full slim-cmo, backend and frontend suites, CFO suites, the full 18-file M5/M6/M7 batch after the M6 typed-title fix (the batch ran once: 260 passed, 1 failed on that now-fixed defect; the six affected M6 files then passed, 57), browser verification. M10 integration tests exist and ran (`backend/tests/integration/test_cmo_m10_market.py`, 20 passed).
