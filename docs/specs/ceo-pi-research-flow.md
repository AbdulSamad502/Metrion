# Metrion — CEO-driven Product Research Flow (CEO → PI → CEO → CFO → CEO) Specification

**Status:** Draft for owner review, 2026-10-14. Build progress: CP1 (this spec), CP2 (PI backend: case, history, pin, top-5 images), CP3 (CEO chain: plan with covered follow-up step `then`, top five, supplier lookup, final case, five-product summary) and CP5 (read-only dashboard) are built and tested; CP4 (the quote offer through the existing §6.36 flow, CFO results attached to the case by the CEO, published supplier price as a labelled fact) and CP6 (print page, spec cross-references) are built. Not done: a single test driving the full chat sequence research → "is #1 worth stocking?" → confirm → CFO figures on the case; real-provider validation (§10); indicative calculations from a published price (Q2, deliberately not built). It completes the "CEO-first" treatment that `ceo-agent-orchestration.md` §6.40 (items 1–3) recorded as future direction for PI ("PI, CI and CFO dashboards are **not** changed … recorded as future direction only"), for **PI only**.
**Prerequisites:** `product-intelligence-agent.md` (PI pipeline, §0 labelling discipline, §6.3 scoring, §6.8 gaps) · `ceo-agent-orchestration.md` (§6.35 PI discovery from chat, §6.36 PI→CFO, §6.37 CFO data requests, §6.40) · `ceo-approval-workflow.md` (stored-plan approval) · `cfo-agent.md` (§6.7, §6.12 batch size) · `deterministic-engine.md` (§5.13.2 `estimate_product_feasibility`; all money) · `auth.md` · `agent-memory.md`.
**Design reference:** `docs/design/Design-Overviews/PI-Dashboard.svg` (layout and information hierarchy only; METRION black/green/white theme per `docs/design/design_status.md` — colours stay configurable).

**This spec adds orchestration, a read-only dashboard, history and export. It adds no discovery source, no scoring rule and no money formula.** Every figure still comes from PI's persisted rows or Brain 1 (CFO). The CEO structures and explains; it never computes (hard rule, `CLAUDE.md`).

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | The seller interacts **only with the CEO** to start research. The PI dashboard is a **read-only** results workspace: no niche-brief form, no input fields, no "run discovery" or "supplier lookup" button. | Owner brief 2026-10-14 |
| C2 | The CEO orchestrates every cross-agent request. **PI never calls CFO** (`ceo-agent-orchestration.md` C1 unchanged). PI produces facts; the CEO passes them to CFO as slots and renders CFO's cited results. | Owner brief; orchestration C1 |
| C3 | Stored-plan approval stays. `pi.discover` is approval-required and metered (`ceo-approval-workflow.md`); the chat's answers end in a plan card the seller approves. The CEO collects inputs conversationally (already built, §6.35 `PI_DISCOVER` session) and the plan card is the confirmation. | Owner brief ("preserve existing confirmation requirements"); D-8 |
| C4 | **Top-5 selection is pre-rank, then re-rank.** From the discovered list (≤ `candidate_cap`, default 30) a deterministic **pre-rank** (Stage 1 `proxy_score` plus review-sentiment quality, same point weights as §6.3 Stage 4 with the supplier component left out and named `NOT_YET_EVALUATED`) picks the top 5. Supplier lookup runs for those 5 only. Stage 4 (`shortlist_scoring.score_shortlist`, unchanged) then produces the **final order** of the 5. The 30 are internal discovery candidates; only the 5 are seller-facing. | Owner answer 2026-10-14 |
| C13 | **Research depth (2026-10-14).** The CEO no longer asks Quick/Complete: PI records the value but both run the same research (`product-intelligence-agent.md` D2), so asking promised a difference that does not exist. Chat runs use `SHALLOW`; the choice returns only when depth changes behaviour. | Owner 2026-10-14 |
| C14 | **Top five carry commentary where possible (2026-10-14).** The pre-rank (C4) puts products WITH viewer/web commentary first, then by score; a product without commentary fills a place only when fewer than five have it, and the case names the gap. | Owner 2026-10-14 |
| C5 | **Supplier cost → CFO is both-labelled and never silently converted.** (a) A unit price a supplier lead **explicitly publishes** may be shown as a **preliminary, indicative** figure with its source URL and capture date. It is **not** a `supplier.quote` and is never saved as one. (b) The CEO **offers** (skippable) to ask the seller for an actual quote per shortlisted product. (c) **Only a seller-confirmed quote**, saved through the existing §6.36 confirm-card path (`enter_expense`, `financials.adjust`), feeds authoritative CFO results (`cfo.landed_cost`, `cfo.batch_size`, `engine_result_ref`). (d) Indicative calculations, if supported, are shown in a separate block labelled "Indicative — from a published price, not a quote" and carry an `estimate_ref`, never an `engine_result_ref`. (e) Missing price, shipping, fees or any required input → that calculation is `UNAVAILABLE` with the reason named. | Owner answer 2026-10-14 |
| C6 | **History:** the latest **10 unpinned** completed reports plus every pinned report are listed. When an 11th unpinned report completes, the **oldest unpinned** is **archived** (`archived_at` set; hidden from history, not shown, purged later by the existing `candidate_retention_days` window). Pinned reports are never archived or purged by cleanup. The unpinned limit is a configurable value (default 10, `pi_tenant_config.history_unpinned_limit`). | Owner answer 2026-10-14 |
| C7 | **PDF = print-optimised report page** with a Print / Save as PDF button (browser print). No server PDF library in this slice. | Owner answer 2026-10-14 |
| C8 | **Honest labelling is unchanged (`product-intelligence-agent.md` §0).** Results are "opportunity candidates", never "trending products". The seller's brief says "customer reviews"; V1 has **no verified buyer reviews** (§0b, no marketplace access). The dashboard and chat show **"Viewer / web commentary"** (YouTube commentary and web editorial, sentiment and themes) and state once, plainly, that verified marketplace reviews are not available. | Spec §0b; owner brief reconciled |
| C9 | **Google Ads demand data stays `UNAVAILABLE`** (PI C2: developer-token brand verification pending). The brief lists it as a supported source; the report names it as an unavailable source with its reason. Tavily and YouTube are the live sources. | PI C2 |
| C11 | **Images (2026-10-14).** The ~30 discovered candidates persist with **no image**; a YouTube thumbnail is **never** used as a product image (PI C8's 2026-10-01 thumbnail fallback is reversed). Only the five selected products get an image, resolved after selection by searching by the product's own name and accepted only if: its text names every identity token (≥ 2), it is not hosted on a video site, and it loads as JPEG/PNG/WEBP with shorter side ≥ 300 px and no banner aspect (largest wins). None found → no image and a plain placeholder, never a guess. Hotlinked with visible source attribution. Implemented in `discovery/top5_images.py`. | Owner 2026-10-14 |
| C12 | **Dashboard layout** follows `PI-Dashboard.svg` section for section: header with `+ New Discovery` (a link into the CEO chat, not a form), "Top Products from your Old Investigations" strip, the current investigation (rank carousel, Product Information tiles, commentary insights, supplier lead, recommendation), and collapsible "Old Investigation" blocks with `View Details` and `Full Audit Report`. The SVG's "Verified supplier", "Net margin 44.2%", "Handoff PO to CFO" and live-revenue outcome text are **not** reproduced as claims: leads are labelled by source and "not verified", cost/margin/units show `Unavailable` until a seller-confirmed quote exists, and the CFO button becomes "Ask the CEO to check costs". | Owner 2026-10-14 |
| C15 | **Evidence on the dashboard and printout (2026-10-14).** Per product: independent source count with one link per domain, YouTube engagement (videos, views, comments) or why it is missing, the demand signal's status (Google Ads unavailable, with its reason), and the per-signal score breakdown. Stated as attention, not verified demand. | Owner 2026-10-14 |
| C16 | **Quantities (2026-10-14).** "Most units your budget allows" is a budget-and-minimum-order ceiling, never a recommendation or forecast; the CEO says so beside the figure. Net margin needs a selling price and fees and stays `Unavailable` until supplied. | Owner 2026-10-14 |
| C10 | Tenant isolation, RLS (`FORCE`), `agent.ceo` + `agent.pi` (+ `research.niche_run` for the run, + CFO keys/entitlement for CFO legs), entitlement meters and `agent_run` audit rows are unchanged. No endpoint takes a client-supplied `tenant_id`. | `CLAUDE.md`; `auth.md` |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | **One research "case" = one `pi_research_run`.** The case aggregates the run's top 5, their review insights, supplier leads, the CEO-requested CFO results and the PI recommendation. The dashboard report id is the existing `run_id`. | No new aggregate table for the PI-owned facts. CFO results are stored by CFO (`engine_result_ref`/`estimate_ref`); the case references them. A new `pi_research_case_link` table (§5) links a run to the investigation, the CFO result refs and the recommendation snapshot. | Keeps provenance; avoids copying figures. |
| D2 | **Post-approval pipeline stages.** After `pi.discover` completes the CEO runs, within the same approved plan, `pi.shortlist_top5` (a pure, no-fetch PI read that applies C4's pre-rank), then `pi.supplier_lookup` for those 5, then `pi.report`. Supplier lookup is a **second metered, external action**; the plan card must list it up front so the seller's single Approve covers it. | Extend the stored plan to a fixed, ordered leg list `[pi.discover, pi.supplier_lookup(top5), pi.report]`; the top-5 ids are resolved by code between legs. | `ceo-approval-workflow.md` freezes slots at plan time; the supplier leg's ids are unknown until discovery finishes — **this needs a plan-model decision (Q1).** |
| D3 | **PI recommendation is deterministic text assembled from PI fields.** Per product: ranking reasons come from `final_score_explanation`; pros and cons from `positive_themes`/`complaint_themes`; supplier option from the leads; units/profit from CFO results. No LLM writes a number. A single narration pass may phrase the summary only under `narration_safety.py` and the eval requirements in `CLAUDE.md` (no number outside cited figures, required disclaimer kept, non-results not narrated as results). | Build the deterministic recommendation first; narration optional and eval-gated. | Hard rule. |
| D4 | **CEO result summary shape** is a typed card, not free prose: up to 5 rows + overall pick, each field either a cited value or a named gap. | `kind: "PI_RESEARCH_SUMMARY"` message payload rendered by the frontend; text fallback produced by code. | Prevents the model restating figures. |
| D5 | **Indicative calculations (C5d)** need a new `cogs_basis` value in Brain 1 (`PUBLISHED_INDICATIVE`) so an estimate built on a published price cannot be mistaken for `STATED`. | **Do not reuse `STATED` for a published price.** Either add the value to `estimate_product_feasibility` (a `deterministic-engine.md` change, architect-reviewed) or ship C5 without indicative calculations (published price shown as a plain labelled fact only). | `STATED` means a seller-supplied quote; reusing it would silently upgrade an estimate (PI §0c). **Q2.** |
| D6 | Published supplier price extraction. Today `contact.moq` is always `null` for Places and Tavily leads, so no unit price exists. Extraction (deterministic regex over the supplier result's own snippet, as `web_price_signal` does, with the price, the quoted unit, the URL and `fetched_at`) is the only way C5a produces data. | Implement as an extension to `pi_supplier_lookup.py`, `confidence=DERIVED`, never fed to Brain 1 except through D5's labelled path. Absence is the common case and is rendered as "no published price found". | Honest, small, testable. **Q3** if the owner wants it deferred. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | The local Ollama model and Tavily/YouTube keys are configured; a missing integration makes `pi.discover` plan-building fail with `INTEGRATION_UNAVAILABLE` (already built) and the CEO says so. | Low — existing behaviour. |
| A2 | A normal run still yields ≥ 5 candidates with usable signal. Fewer than 5 → the report lists fewer and says so; it never pads. | Medium. |
| A3 | Sellers answer "marketplace, budget, category, price range" in chat. Other PI parameters (`exclude_brands`, `max_lead_days`, fragile) are **optional** and asked only if the seller volunteers them or the request implies them; they are never invented. | Low. |
| A4 | CFO leg inputs (quantity, window, budget) for the five products come from the seller's brief budget and stored quotes; no default is substituted for a missing input. | Medium — drives many `UNAVAILABLE` cells. |

---

## 4. Goals and non-goals

**Goals.** (1) A seller types "Find me trending products under ₹20,000 on Amazon"; the CEO recognises the PI need, asks only the missing inputs in chat, reuses what was already said or remembered (offered as a choice, never filled in silently), and runs the research after one plan approval. (2) Research runs end to end: ≈30 candidates → pre-rank → top 5 → viewer/web commentary → suppliers → CEO→CFO financials → PI recommendation. (3) The CEO chat shows a **summary only** with a working **View Detailed Research** link to the saved report. (4) The PI dashboard is the read-only detail workspace, with history, pin/unpin and Print/PDF, all from real saved data.

**Non-goals.** Any PI→CFO direct call · new discovery sources · any marketplace fetch · changing scoring weights · supplier ranking by PI (C4 of the PI spec: CFO ranks, from quotes only) · server-generated PDF · writing to any marketplace · showing all 30 candidates to the seller · research started from the dashboard.

---

## 5. Data model and interfaces

### 5.1 Schema (PI package migration, `product-intelligence`, RLS `FORCE`, tenant-scoped like every PI table)

```sql
ALTER TABLE pi_research_run
  ADD COLUMN pinned_at      timestamptz,   -- NULL = not pinned
  ADD COLUMN archived_at    timestamptz,   -- NULL = visible; set by auto-replacement only; never set while pinned_at IS NOT NULL
  ADD COLUMN completed_at   timestamptz;   -- set when the case (not just the discovery) is complete; orders history

-- CHECK (NOT (pinned_at IS NOT NULL AND archived_at IS NOT NULL))

ALTER TABLE pi_tenant_config
  ADD COLUMN history_unpinned_limit int NOT NULL DEFAULT 10 CHECK (history_unpinned_limit BETWEEN 5 AND 10);

pi_research_case (                       -- 1:1 with a run once the pipeline finished; the seller-facing "report"
  run_id uuid primary key references pi_research_run(id),
  tenant_id uuid not null,
  investigation_id uuid,                 -- the CEO investigation that asked (nullable: provenance only, not an FK across packages)
  top5_candidate_ids uuid[] not null,    -- final order (Stage 4)
  prerank_explanation jsonb not null,    -- C4 pre-rank inputs per candidate, deterministic
  recommendation jsonb not null,         -- D3: per-product recommendation + overall pick; every figure a ref
  cfo_refs jsonb not null default '[]',  -- [{candidate_id, kind: "ENGINE"|"ESTIMATE", ref, leg_key, status}] written by the CEO, never by PI
  gaps jsonb not null default '[]',      -- named missing evidence (integration down, no supplier, no price, ...)
  created_at timestamptz not null default now()
)
```

RLS: `FORCE ROW LEVEL SECURITY`, `tenant_id = current_setting('app.tenant_id')::uuid` pattern identical to the other PI tables. The CEO writes `cfo_refs` through a PI repository function (`pi_research_case_repo.attach_cfo_results`), so PI code never imports CFO and the CEO never writes SQL (`backend/ceo` contains no SQL — architecture test stays green).

### 5.2 Backend interfaces

| Interface | Kind | Notes |
|---|---|---|
| `pi.shortlist_top5` | New CEO registry action, effect `READ`/compute-persist, **no external call, no meter** | Applies C4's pre-rank to the run's candidates, persists `pi_research_case.top5_candidate_ids`/`prerank_explanation`. Deterministic; unit-tested. |
| `pi.supplier_lookup` | Existing registry action | Called by the CEO with the 5 ids resolved by code. Already metered and permission-checked. |
| `pi.report` | Existing; extended | Returns the case: top 5 in final order, per-candidate review insight, supplier leads (+ published price when present), PI recommendation, `cfo_refs`, `gaps`, and the `unavailable[]` list (adds `demand_signal` and `verified_buyer_reviews`). |
| `GET /api/v1/pi/research` | New, read, `agent.pi` | History list: pinned first, then latest unpinned (≤ limit), excluding archived. Returns id, title (brief category), marketplaces, budget, date, status, pinned flag, top-product names. |
| `GET /api/v1/pi/research/{run_id}` | New, read, `agent.pi` | The full case (same shape as `pi.report` plus history metadata). 404 for another tenant's id. |
| `POST /api/v1/pi/research/{run_id}/pin` · `/unpin` | New, write, `agent.pi` | Idempotent. Unpin may trigger replacement (C6). No other body. |
| Print page | Not an API: the frontend route `/reports/pi/{run_id}/print` (outside `/dashboard`, so the printout carries no sidebar or header) calling the read above; "Print / Save as PDF" is the browser's print. | C7. |
| History replacement | Repository function `pi_research_run_repo.archive_over_limit(tenant, limit)` | Called when a case completes and on unpin. Archives oldest unpinned beyond the limit; **never touches `pinned_at IS NOT NULL`**; single SQL statement, tenant-scoped. |

The old direct routes `POST /pi/discover`, `POST /pi/supplier-lookup` and `/pi/niche-briefs*` stay **server-side** (the CEO registry invokes the handlers; tests and `test_frontend_api_paths_exist` pin them). The **frontend stops calling them**.

### 5.3 CEO conversation contract (delta over §6.35)

1. **Recognition.** `intent_router` rule `QT_PRODUCT_IDEAS` / `pi.discover` already routes; extend the rule set with natural phrasings ("trending products under ₹20k on Amazon", "what should I sell", "find products for <niche>") and add a **slot extractor** that reads *stated* values from the same message (budget "under ₹20,000" → `budget`; marketplace names → `marketplaces`; "mens watches" → `category`; "₹500 to 1,500" → `price_range`) with the existing deterministic parsers (`_amount`, `_marketplaces`, `_price_range`). Extracted values are pre-filled into the input session as answered; **each is echoed in the next question or the plan summary so the seller can correct it**. Nothing extracted by a model; nothing invented.
2. **Questions.** Only fields still missing, in the existing order (category → budget → marketplaces → price range → depth). A previously confirmed value (PI memory) is **offered as one option**, never silently applied (existing behaviour, kept).
3. **Plan.** After the last answer the existing summary + plan card is produced (C3). The card now also lists the supplier-lookup leg and the read legs (D2).
4. **After approval.** `pi.discover` → `pi.shortlist_top5` → `pi.supplier_lookup` → `pi.report`; each leg is one `agent_run` child of the CEO turn (orchestration R5).
5. **CFO step.** For each of the 5, the CEO checks for a stored seller quote (`ceo_reads.stored_quotes`). With a quote and a stated budget, it runs `cfo.landed_cost` and `cfo.batch_size` (existing legs, `NEW_PRODUCT_DECISION` slots). Without one it records the gap `supplier_quote_missing` and **offers** (skippable) to collect a quote per product through the existing §6.36/§6.37 guided session and confirm card. Published prices (C5a) are displayed as indicative facts; D5 decides whether any indicative calculation runs.
6. **Summary message** (D4): top-5 names in final order · one-line description and main pro/con · PI's per-product recommendation · best-evidenced supplier option (the lead with the most evidence fields; no ranking claim — "best evidenced", defined as: most of {phone, website, locality, MOQ, published price} present, ties by lead order) · CFO suggested quantity and profit estimate where an `engine_result_ref` exists, else the named gap · overall pick (highest `final_score`, ties named) · **View Detailed Research** → `/dashboard/pi?run=<run_id>`. The 30 candidates are not listed.

### 5.4 Dashboard (frontend, read-only)

Route `/dashboard/pi` becomes: **history rail** (pinned section, then recent; pin toggle on each; search not required) + **workspace** for the selected report (`?run=` deep link, default latest) following `PI-Dashboard.svg`: header (niche, budget, target price, "Top 5 shortlist"), rank-tabbed product cards (image with source attribution per PI C8, name, category, marketplaces, Selling price / Cost price / Net margin / Units-to-buy tiles with ref and basis chips), viewer/web commentary insights (positive, defects to address), supplier details (name, locality, source, phone, MOQ, published price + date, link), CEO/PI recommendation block, "Full audit report" → print page. Unavailable cells show the named reason, never a blank or a zero. No forms, no run buttons; an empty state says "Ask the CEO to research products" with a link to the CEO Hub. The sidebar/logo are untouched (`project_ui_redesign` constraint). Dark and light themes via existing tokens.

---

## 6. Core rules

1. **No number is produced outside Brain 1 or copied from a PI row.** The recommendation, summary and dashboard render figures from `cfo_refs`/PI columns only.
2. **Authoritative vs indicative never mix** (C5d): separate blocks, separate chips (`Quote-based · engine` vs `Indicative · estimate`), separate refs.
3. **A missing input is `UNAVAILABLE`, named** (budget, quote, shipping, fee reference, category).
4. **Top 5 is exactly the seller-facing set.** Candidates beyond 5 are not returned by `pi.report`'s case view or the dashboard; they stay in the table for retention/audit only.
5. **History cleanup is tenant-scoped, archive-only, pin-safe** (C6). An unpinned report is archived only when it falls outside the newest N unpinned *of that tenant*.
6. **Pinning** requires `agent.pi`; reading history and reports requires `agent.pi`; the chat path requires `agent.ceo` + `agent.pi`.

---

## 7. AI requirements

| Brain | Role |
|---|---|
| Brain 1 | All figures (CFO legs, `estimate_product_feasibility`). |
| Brain 2 | None added. |
| Brain 3 | Intent recognition (existing classifier + deterministic rules), commentary classification and product-name extraction (existing, local Ollama). **Optional** narration of the recommendation, behind `narration_safety.py`. |

**Evals (required by `CLAUDE.md` for any new Brain-3 narration surface):** if narration of the recommendation or summary is added, the suite must assert: no numeral absent from the cited figures; no "trending"/"bestseller"/unqualified "review"; the estimate/indicative disclaimer is present; a `NO_SUPPLIER`/`UNAVAILABLE` product is never described as ready to buy or profitable. The deterministic summary (D4) needs no narration eval but is unit-tested for the same properties.

---

## 8. Authorization and security

- Chain unchanged (`auth.md` §7.1). New read/pin routes: `require_auth(permission=AGENT_PI)`; tenant from the session only.
- Cross-tenant: another tenant's `run_id` returns 404 on read, pin, unpin and print; the archive function filters by `tenant_id`; RLS is the final boundary. Tests prove each.
- Pinning cannot be abused to bypass entitlement: pinning stores a flag on an existing row only.
- Prompt-injection: Tavily/YouTube text remains untrusted evidence; supplier snippets rendered on the dashboard are escaped text; links open with `rel="noopener noreferrer"`. The CEO never follows instructions found in supplier or product text.
- The print page contains only that tenant's saved data and no tokens.
- `pi.supplier_lookup` stays a metered external action; it is never run without the approved plan.

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Fewer than 5 candidates survive | Report shows what exists; gap "only N opportunity candidates found". |
| E2 | Tavily/YouTube/Ollama down | Plan not buildable (`INTEGRATION_UNAVAILABLE`) before any spend; mid-run degradation → run `PARTIAL`, gaps named. |
| E3 | Supplier lookup finds nothing for a product | Product stays in the top 5; supplier block "no supplier lead found"; Stage 4 gives the supplier component 0 with that reason. |
| E4 | Seller skips the quote | CFO cells `UNAVAILABLE: supplier quote not provided`; PI recommendation says what is missing and does not call it ready to buy. |
| E5 | Seller answers the quote for 2 of 5 | CFO results for those 2; the other 3 named gaps. |
| E6 | Same run viewed from two investigations | One case, two links; no duplication. |
| E7 | Pin 11th report while 10 pinned | Allowed (pinned are unlimited); recent-unpinned list is simply empty. A product limit on pinned reports is Q4. |
| E8 | Unpin when over the unpinned limit | Immediately re-run replacement; the oldest unpinned (possibly the just-unpinned one) is archived per ordering by `completed_at`. |
| E9 | Seller re-asks identical question | New plan, new run (research is metered); not deduplicated silently. |
| E10 | Report opened for an archived run | 404 "no longer in history". |
| E11 | Run FAILED | Not in history (history lists COMPLETE/PARTIAL only); CEO message states the failure. |
| E12 | Browser blocks print | Page remains readable; "Print / Save as PDF" is a plain button. |

---

## 10. Production-validation blockers

Real Tavily/YouTube keys and a running Ollama are needed for a live end-to-end run; tests use the package's mock providers (CI precedent) and are labelled simulated. Published supplier-price extraction (D6) has not been validated against real supplier pages and must be labelled as such until sampled. Print layout needs a manual check in Chrome/Edge. None of these blocks the code; they block calling the feature *production-validated*.

---

## 11. Acceptance criteria

1. **AC1** "Find me trending products under ₹20,000 on Amazon" is routed to PI; budget and marketplace are taken from the message and echoed; only missing inputs are asked; no value is invented.
2. **AC2** Nothing runs before the plan is approved; the plan lists every external leg; a denied/expired plan runs nothing.
3. **AC3** Top 5 is selected by the C4 pre-rank, suppliers are looked up for exactly those 5, and the final order equals Stage 4's `final_score` order. The same inputs give the same order.
4. **AC4** Each seller-facing product has: image with attribution (or none), viewer/web commentary pros/cons or a named gap, supplier leads or a named gap, and a PI recommendation built from PI fields.
5. **AC5** CFO results appear only via the CEO; an architecture test proves `product_intelligence` imports nothing from CFO and `backend/ceo` imports no SQL.
6. **AC6** Quote-based CFO figures carry an `engine_result_ref`; indicative figures (if D5 adopted) carry an `estimate_ref` and a separate label; a published price is never stored as `supplier.quote`.
7. **AC7** The chat summary shows exactly the 5 products, never the 30, and every number resolves to a ref; **View Detailed Research** opens `/dashboard/pi?run=<id>` to the same saved report.
8. **AC8** The PI dashboard has no form, input or run button; all content comes from the report/history endpoints.
9. **AC9** History shows ≤ N unpinned + all pinned; the (N+1)th completion archives the oldest unpinned; pinned reports survive any number of completions; unpin re-applies the limit.
10. **AC10** Pin/unpin/read/print are tenant-isolated (404 across tenants, proven with two tenants).
11. **AC11** Print / Export PDF page includes the 5 products, findings, suppliers, financial estimates (with labels) and recommendations, and prints legibly in black-on-white.
12. **AC12** Missing integration, supplier price, quote or fee reference is named, never zero or invented.
13. **AC13** Existing CEO, PI, CFO suites stay green.

---

## 12. Test scenarios

| # | Scenario | Level |
|---|---|---|
| T1 | Slot extractor: "under ₹20,000 on Amazon" → budget 2,000,000 paise, `AMAZON`; "5k" refused and asked; range, lakh, negative cases | unit |
| T2 | Pre-rank: deterministic ordering, tie-break by candidate id, supplier component `NOT_YET_EVALUATED`, fewer than 5 | unit |
| T3 | Archive function: 12 unpinned + 3 pinned → 2 oldest unpinned archived, pinned untouched; two tenants isolated; idempotent | integration (Postgres) |
| T4 | Pin/unpin routes: idempotent, 404 cross-tenant, permission denied without `agent.pi` | integration |
| T5 | `pi.report` case shape: top 5 only, `unavailable[]` names demand + verified reviews | integration |
| T6 | Full chat flow with mock providers: ask → clarifying turns → plan → approve → legs → summary card with 5 products and `viewReport` link | e2e (backend) |
| T7 | CFO step: with a stored quote → `landed_cost`/`batch_size` refs attached; without → named gap + skippable quote offer; skipping saves nothing | e2e |
| T8 | Architecture: PI package has no CFO import; CEO has no SQL; frontend no longer references `/pi/discover`, `/pi/niche-briefs` (path-existence test updated) | unit |
| T9 | Narration/summary safety: no numeral outside refs, no "trending", no "ready to buy" with missing quote | unit/eval |
| T10 | Frontend: dashboard renders history, pin toggle, empty state, unavailable cells; no input elements (a11y test); print page | vitest |
| T11 | Prompt-injection text in a supplier snippet is rendered escaped and never changes CEO behaviour | unit |

---

## 13. Explicit open questions

| # | Question | Recommendation | Blocks |
|---|---|---|---|
| Q1 | **Plan model:** `ceo-approval-workflow.md` freezes slots at plan time. The supplier-lookup leg's candidate ids exist only after discovery. Options: (a) a plan "stage 2" that resolves ids by code and is listed in the card as part of the one Approve (ids resolved from the run's own pre-rank, no new user input); (b) a second Approve for the lookup. | (a), with the card stating "I will then look up suppliers for the top 5 and read the saved results". | CP3 |
| Q2 | **D5:** add `cogs_basis=PUBLISHED_INDICATIVE` to `estimate_product_feasibility` (Brain 1 change), or ship published price as a labelled fact with no indicative calculation. | Ship the labelled fact first; add the engine value only if owner wants indicative margins. | CP4 |
| Q3 | **D6:** build published-price extraction now (rarely finds anything) or defer. | Build; it is small and absence is handled. | CP4 |
| Q4 | Cap on the number of pinned reports per tenant. | Unbounded in V1, flagged for entitlement spec. | — |
| Q5 | Should the CEO auto-offer the quote questions for all 5 in sequence, or ask once "want to enter supplier quotes?" and then per product? | Ask once, then per product, each skippable. | CP4 |

### Resolved — do not re-flag
Q1 plan model = (a), one Approve covering the supplier lookup · Q2 = published price shown as a labelled fact first, engine value only on request · Q3 = build published-price extraction · Q5 = ask once, then per product, each skippable (all owner "go with recommendations", 2026-10-14) · Top-5 method (C4) · supplier cost policy (C5) · archive-not-delete (C6) · print PDF (C7) · Google Ads stays unavailable (C9) — all by the owner on 2026-10-14.

---

## 14. Gap analysis → checkpoints (build order)

| CP | Content | Gap closed |
|---|---|---|
| CP1 | This spec; update `product-intelligence-agent.md` §6.8/§6.9 and `ceo-agent-orchestration.md` §6.40 pointers to it | Spec-first rule |
| CP2 | PI backend: migration (`pinned_at`, `archived_at`, `completed_at`, `history_unpinned_limit`, `pi_research_case`), repos, pre-rank (`pi.shortlist_top5`), case assembly in `pi_report`, history/pin routes, archive function + tests (T2–T5, T8) | Dashboard has nothing to read; no top-5; no history |
| CP3 | CEO: slot extractor + rules, extended plan (Q1), leg chain, `PI_RESEARCH_SUMMARY` card, deterministic recommendation, View-Detailed-Research link (T1, T6, T9) | PI not driven end-to-end from chat; summary shows only quoted names |
| CP4 | CEO→CFO step: quote offer/skip, `landed_cost`/`batch_size` legs, `cfo_refs` attach, published-price extraction and labels (T7, T11) | No CEO→CFO financials for PI products |
| CP5 | Frontend: read-only dashboard from the SVG, history rail, pin, deep link, empty state; remove forms and run buttons; update tests (T10) | Dashboard is a form/test harness |
| CP6 | Print page; full regression (backend unit/integration, frontend vitest/tsc); live-provider smoke where keys exist, labelled | PDF; verification |

## 15. Current gaps found in the code (2026-10-14 inspection)

1. `ceo/plans.py` registers `pi.discover` as a session action with no slot extraction from the first message (the session asks all six questions regardless of what was already said).
2. After `pi.discover` the orchestrator runs only `pi.report` (`_with_pi_report`); there is no top-5 selection, **no automatic supplier lookup**, no CFO step, and §6.35 deliberately relays "no scores or estimates" — the chat shows at most ten quoted idea names.
3. `pi_supplier_lookup` is metered and reachable only via its own route or the dashboard harness; the CEO registry has the action but no chain invokes it.
4. `contact.moq` is always `null`; no published supplier price exists anywhere.
5. `frontend/app/dashboard/pi/page.tsx` (999 lines) is a niche-brief form + discover button + supplier-lookup button harness, and ends in a "not yet available" final-recommendation placeholder.
6. No history, pin, archive or case concept; `GET /pi/report/{run_id}` returns up to the full candidate list.
7. `ceoModel.ts` already builds a deep link `/dashboard/pi?run=<id>#discover`, so the link target contract exists; the page behind it is the harness.
8. `product-intelligence-agent.md` §6.8 still lists CEO dispatch and the CFO hand-off as "not implemented" — to be corrected at CP1 closeout.
