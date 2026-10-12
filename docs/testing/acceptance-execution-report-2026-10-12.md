# Practical acceptance: execution report (2026-10-12)

What this is: the scenarios of `pre-push-practical-test.md` that could be executed **by the assistant** in this environment, with the status each one really had. Branch `feat/ceo-foundation`, HEAD `2b954c9`, tree uncommitted. **You still have to run the manual checklist yourself with real Clerk sign-in before pushing.**

## How it was run (read this before trusting any row)
- **Real:** the repository's FastAPI app (all routers, orchestrator, registry, repositories, RLS), the real Postgres **scratch** database (host port 5544, container `metrion-verify-pg`; positively verified by matching `pg_postmaster_start_time()` to that container, never the development container on 5432), the real local Ollama models (`qwen3.5:4b` classifier, `qwen3:8b` composer), a real production build of the frontend, and the in-app browser driving it.
- **Simulated:** **Clerk only.** The acceptance backend (`scratchpad/acceptance_backend.py`, not part of the repository) answers authentication from an `X-Acceptance-User` header (tenant A or B, one OWNER each). In the browser the page used the user's existing Clerk session cookie for localhost, but the backend ignored the token. So **real sign-in, token validation, expiry and onboarding were not tested.**
- **No outward calls:** Tavily/YouTube/Google Places keys blank; every proxy pointed at a dead local port (anything not localhost fails at once). This also means the **public GST pages could not be fetched** (a deliberate "specialist dependency unavailable" test, not a test of a successful lookup).
- `CEO_LEG_ABANDON_SECONDS` unset. `CEO_MAX_CANDIDATE_PRICES=5` was set **in the acceptance process only** for B4b (the user's `.env` does not set it; see B4b).
- The development frontend (3000) and backend (8000) were never used; they returned 200 / 401 before and after.

## Scenario results (API over real HTTP + DB inspection unless marked UI)
| ID | Scenario | Status | Evidence / note |
|---|---|---|---|
| A1 | signed-out requests rejected | PASS (simulated auth) | `/session` and `/ceo/investigations` 401 `Not authenticated` |
| A2 | session resolves tenant A, OWNER, ACTIVE | PASS (simulated auth) | |
| A3 | cross-tenant / forged ids are 404 | PASS | B reads A's conversation, findings, posts a turn: all 404, A has 0 turns, B's list excludes it |
| A4 | client tenant/role claims ignored | PASS | `investigation.tenant_id` = A despite `tenant_id=B` in the body |
| A5 | errors carry no internals | PASS | 422/422/422, no `Traceback`, driver names, DB port |
| B1 | "Where am I losing money?" | PASS | BUSINESS_STATE/QT_LEAKS, DELIVERED, no leg, `model=rules` |
| B2 | "Find trending products ..." (approval-gated) | PASS | ADVISORY/DENIED, no leg, approval text. UI: Task status "Needs an approved plan" |
| B2b | "What product ideas did you find?" | PASS | QT_PRODUCT_IDEAS read, no discovery |
| B3 | "What are my competitors charging?" | PASS | QT_COMPETITORS_PRICES read, no discovery |
| B4 | "Show me the latest product research report" | PASS | CLARIFY, "no report to show", none invented |
| B4b | "Acme dropped to Rs 499 ..." | **PASS with a config requirement** | With the user's current `.env` the turn refuses honestly (`CONFIG_MISSING: max candidate prices`, FAILED, nothing run) because `CEO_MAX_CANDIDATE_PRICES` is not set. With it set (the example file suggests 5) it asks "(2 of 11) Which competitor changed their price?" |
| B5 | compound GST + leaks | PASS | one `cfo.gst_lookup` leg; answer lists "Handled: ... / Not handled: ... not started, send it as its own message"; no rate claimed |
| B6 | compound with an unrecognised clause | PASS | "Not handled: upload my sales file ... could not match" |
| B7 | hashtags from chat | PASS | ADVISORY/DENIED, no leg |
| B7b | "Run research now ..." | PASS | no `ci.research_now` run exists |
| B8 | single GST lookup, web blocked | PASS **with a limitation** | leg COMPLETE, turn SUCCEEDED, answer "No GST rate could be found ... ask your accountant". Spec 8.4.1 makes an unreachable page and an empty page the same `NO_RELIABLE_SOURCE_FOUND`; so "sources unreachable" is not distinguished from "no match" (see defect list D7) |
| B9 | model-dependent question (real qwen) | PASS (real local model) | 66 s, CLARIFY via `qwen3.5:4b`, no leg |
| C1 | same id + same text | PASS | `replayed` false then true, same turn and answer, 1 turn row |
| C2 | same id, different text | PASS | 409 `CLIENT_REQUEST_ID_REUSED`, nothing written |
| C3 | simultaneous duplicates | PASS | (200 run, 409 in progress), 1 turn row |
| C5 | **real process kill** mid-turn, restart, retry with same id | PASS (real process death, real Ollama) | RUNNING anchor seen, hard kill, restart; retry `replayed:true`, FAILED, "That request was interrupted and did not finish", anchor FAILED `INTERRUPTED`, 1 turn |
| C6 | new id after interruption | PASS | runs as a new submission |
| C7 | id scoped to tenant/investigation | PASS | B own conversation runs; B on A's conversation 404 |
| C4, C8-C10 | retry while running (HTTP), UI id reuse, late result, repeatable vs uncertain | see notes | C4 covered by C3 and by automated tests; C8 observed in the browser (Network body carried `clientRequestId`; a resend after backend recovery reused the failed attempt's id); late result and repeatable/uncertain classes are **automated only** (`test_ceo_leg_deadline`): the hard deadline is unset by design |
| D1 | business name remembered | PASS | acknowledged by code; answered without a model; 1 memory row |
| D2 | new conversation + hard backend restart | PASS | same answer both times |
| D4 | supersession | PASS | newer name answered |
| D5 | where-I-sell / niche | PASS | |
| D6 | other tenant | PASS | "You have not told me ..." |
| E-PI1 | PI draft missing fields cannot be READY | PASS | 4xx names budget/marketplaces; DB still DRAFT |
| E-PI2 | complete then READY | PASS | DB READY, 5,000,000 paise |
| E-PI3 | discovery with providers unavailable | PASS | 200 PARTIAL, `candidateIds: []`, reason names the unreachable providers; nothing fabricated |
| E-CI1 | CI URL allowlist | PASS | evil.example.com 400 (allowlist); amazon.in stored, never fetched |
| E-CI2 | compare unknown product | PASS | actionable 404 |
| E-CI3 | CI summary per tenant | PASS | A tracks 1, B 0 |
| E-CFO1 | Seller Goal | **FAIL then FIXED -> PASS** | the API accepted `"abc"` as `target_margin_pct` (200) while only the form refused it, and that text is quoted into the strategic-briefing prompt. Fixed server-side (ASCII-digit percentage grammar, 422 naming the field); 5 bad values 422 on the real backend; 22 new integration cases; UI re-verified: reads saved goal, refuses "abc" with no request, saves 18.5, reads it back |
| E-CFO2 | reconcile / preview / health on an empty tenant | PASS with a note | all 200 with structured bodies. Note D6: `preview` returns `headlineTotalPaise: 0` with an engine ref for a tenant with no data (a zero, not UNAVAILABLE): decision for the financial campaign |
| E-CFO3 | invalid CFO inputs | PASS | 422 naming missing/invalid fields |
| E-CFO4 | GST lookup, web blocked | PASS with the B8 limitation | 200, `result: null`, `noMatch` with attempted URLs; no rate invented |
| E-CMO1 | market trends preview / history | **BLOCKED** | 503 `CMO_NOT_CONFIGURED`: trends need the Tavily/YouTube providers, which were deliberately blanked |
| E-CMO2 | title generation with minimal input | PASS (honest failure) | 200 with `runStatus: FAILED`, `unitsBilled: 0`, `CONFIG_MISSING` |
| E-CMO3 | actual title generation | **BLOCKED** | needs platform configuration `format_constraint_max_age_days`, `internal_retry_bound` and VERIFIED marketplace format constraints (none seeded, no seed utility in the repo) |
| G6 | no run left RUNNING | PASS | 0 for the acceptance tenants |

## UI scenarios (real production build on :3100 -> real backend :8001 -> scratch DB)
| ID | Scenario | Status | Evidence / note |
|---|---|---|---|
| U1 | send a rule question | PASS | answer shown, Task status Completed, POST body carried `clientRequestId`, turn row stored |
| U2 | approval-gated request | PASS | "Needs an approved plan", nothing run |
| U3 | compound request | PASS | UI showed Running ("Writing the answer..."), then the answer with the Handled / Not handled block |
| U4 | **refresh while a turn is running** | **FAIL then FIXED -> PASS** | before: after reload the Hub showed IDLE/Ready while the turn was RUNNING server-side (question stored, no answer). After: "Answering your last question...", Task status Running, a notice that it has not been reported as done, re-read every 3 s until the answer arrives (re-verified in the browser) |
| U5 | send while another turn is running | **FAIL then FIXED (component tests only)** | the refusal (409) was explained but also flipped Task status to FAILED. Now a notice and the running task keeps its own status. Browser re-check of the fix not repeated |
| U6 | backend outage and recovery | PASS | outage showed "Not sent" + failure notices; after restart a resend reused the attempt's id and the answer arrived, no duplicate question. Three overlapping messages were seen; the first (a "could not be loaded" banner) is now shown only when no earlier list exists (tested; browser re-check not repeated) |
| U7 | Overview, empty tenant, real API | PASS | "Nothing needs your attention" only with every feed OK; "No saved profit results yet"; Market watch shows the 1 tracked competitor |
| U8 | overflow, all 8 signed-in pages | PASS | 360 px: Overview, PI, Competitors, CFO, CMO, Action Center, Agents, Settings, Hub: no horizontal overflow; 768 px: Overview, PI, Competitors, CFO, CMO, Hub: none |
| U9 | Seller Goal form | PASS | see E-CFO1 |
| U10 | Task status label | **FAIL then FIXED (unit)** | showed "Qt leaks" for the saved-results question; now "Where money is leaking" (10 keys labelled) |
| U11 | history row status | **FAIL then FIXED (unit)** | showed "plan validated"; in-flight statuses now read "In progress" |
| U12 | PI / CI / CMO interactions in the browser | NOT RUN | covered at API level above and by the component tests; not driven by hand here |

## BLOCKED or NOT RUN (honest list)
Real Clerk sign-in/sign-up/onboarding and expired or rejected tokens (BLOCKED: needs your Clerk credentials and users); stopping Ollama mid-test (NOT RUN: it is your running service); successful GST lookup, PI discovery with providers, CMO trends and generation, vision extraction (BLOCKED: external providers deliberately blocked, platform configuration unseeded, vision model `qwen2.5vl-manual` not installed); CFO populated-data flows and any import (not run: the separate financial campaign and no synthetic fixtures exist); manual keyboard walkthrough and screen-reader testing (not performed; no assistive-technology tool was used); 390 px and 1440 px sweeps of the real pages (the harness sweep earlier covered them, the real-backend sweep covered 360 and 768).

## Totals
**API scenarios: 42 executed** (41 in the first driver run + E-CMO3 added after triage): **39 PASS** (several with a stated note or config requirement), **1 FAIL then FIXED** (E-CFO1), **2 BLOCKED** (E-CMO1, E-CMO3). The first run had 37 PASS and 4 FAIL; triage: B4b = configuration (passes with the setting), E-CMO2 = my expectation was too narrow (the honest failed run is correct), E-CMO1 = blocked by my own choice to blank providers, E-CFO1 = a genuine defect, fixed.
**UI scenarios: 12 defined**: **7 PASS** (U1, U2, U3, U6, U7, U8, U9), **4 FAIL then FIXED** (U4 re-verified in the browser; U5, U10, U11 verified by component tests only), **1 NOT RUN** (U12). **No scenario ended FAIL.** Real Clerk, live providers, populated CFO data, keyboard and screen-reader checks are BLOCKED or NOT PERFORMED as listed above.
