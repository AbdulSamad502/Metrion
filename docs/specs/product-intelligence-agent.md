# Metrion — Product Intelligence Agent (PI) Specification

**Status:** Draft for review
**Prerequisites:** `deterministic-engine.md` (all financial math) · `data-foundation.md` (provenance, confidence) · `auth.md` (permissions, execution paths) · `competitor-intelligence-agent.md` (shared fetch posture, §6.5 text handling)
**Pending:** Brain 2 spec (unwritten) · entitlement, metering and billing spec (unwritten)

**PI researches. It never calculates.** Every financial figure — margin, landed cost, feasibility — comes from Brain 1. PI normalises observations into provenance-tagged inputs and renders what the engine returns.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Marketplaces:** Amazon, Flipkart and Meesho, all three at V1. | readiness §1 — Marketplaces |
| C2 | **Discovery sources:** Amazon via **PA-API 5.0**; Flipkart and Meesho via the same on-demand fetch model CI uses. No bulk crawling. | readiness §1 — PI product discovery |
| C3 | **Niche discovery is a paid, on-demand research run.** Structured niche + budget input; user-triggered; bounded, rate-limited, with a capped and configurable candidate volume. Results label estimates, sources, timestamps and unavailable data. | readiness §1 — Niche discovery |
| C4 | **PI discovers suppliers; it never ranks them.** Output is a qualified lead list with contact details. CFO ranks, from seller-supplied quotes only. | readiness §1 — Supplier ownership |
| C5 | **Supplier sources:** Google Places API primary; **IndiaMART user-initiated single lookups only** — no bulk contact harvesting (DPDP exposure). | OP2(b) |
| C6 | **Allowlists are purpose-scoped.** Marketplace research: `amazon.in`, `flipkart.com`, `meesho.com`. Supplier discovery: Google Places, IndiaMART. Trends: approved trend sources. | OP2 |
| C7 | **Facts, not expression.** No review text, listing copy or product description persisted. Derived insight only, with provenance and timestamp. | readiness §1 — Review handling |
| C8 | **No image rehosting.** Permitted hotlinks or thumbnails where technically and legally appropriate; otherwise source links or placeholders. | readiness §1 — Image handling |
| C9 | **Local-only derivation.** Raw fetched text is processed in memory or by a local model, never sent to a hosted provider, never persisted. | `competitor-intelligence-agent.md` C15 |
| C10 | **Scrape-failure fallback:** cached snapshot with a visible age stamp up to **7 days**; beyond that, report unavailable. Never fabricate. | OP3 |
| C11 | **Star topology.** Conversational access via CEO requires `agent.ceo` + `agent.pi`. Registered direct execution paths require `agent.pi`, **plus a shared-service key where the action triggers one** — see §6.8: `pi.discover` additionally requires `research.niche_run`, matching the two-key pattern CFO and CMO use for their own shared-service actions. Brain 1 callable directly. | readiness §1 — Topology, Execution paths; §6.8 |
| C12 | **Entitlement:** free PI is limited (5 shallow runs/month); complete PI is a paid cart item. Values provisional. | readiness §1 — Agent cart |
| C13 | **pgvector, not Qdrant.** All similarity and semantic search in V1 uses pgvector on the existing Postgres. | readiness §1 — RAG |
| C14 | **Google Trends is in V1** under the flat merge, with a mandatory degraded state (§6.5). | readiness §1 — Versioning; 2A.4 |
| C15 | **Proxy ranking, never "units sold."** Marketplaces do not publish unit volumes. | 2A.1 |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Candidate ranking basis | A **composite proxy score** from whatever signals a single run actually observed — rank position, rating, rating count, price-band fit. Review velocity is an *optional refinement* added only when a prior observation of the same candidate exists (§6.3); it is never required and never causes suppression | C15. Presenting a proxy as sales data is the fastest way to lose a seller's trust; requiring a signal no first run can produce would make the score never exist at all. |
| D2 | Discovery breadth | **Capped per run**, configurable. **Complete** run: default 45 candidates → top 15 per marketplace. **Shallow** run: top 5 per marketplace, no enrichment (D6) | C3 requires a cap. Complete must strictly exceed shallow — see D6. |
| D3 | Trends dependency posture | **Best-effort, never blocking.** A run completes without Trends and says so | pytrends is unofficial and breaks without notice (V4). |
| D4 | Feasibility figures | **Two distinct sources, never conflated.** A candidate the seller does not yet own is priced via `estimate_product_feasibility` (`deterministic-engine.md` §5.13.2) — an estimate, `estimate_ref`, range only. A seller's *own* SKU is priced via `margin_curve` (canonical, `engine_result_ref`) — that path belongs to CFO, not PI (`cfo-agent.md` §6.7) | PI holds no rates and no formulas; a discovered candidate has no owned COGS or `metric_result` lineage, so it cannot be dressed as a canonical figure (see §6.7). |
| D5 | pgvector use | Embed **derived attributes only** — theme vectors, category text, structured title attributes (`title_length`, `title_structure`, `keyword_themes`). **Never a paraphrase of the title or any other listing copy** | C7/C9. Per `competitor-intelligence-agent.md` C16, a normalised paraphrase is still a derivative of expression, not a fact. |
| D6 | Shallow vs complete run | **Shallow = top 5 per marketplace**, no review derivation, no supplier discovery, no Trends. **Complete = top 15 per marketplace**, full pipeline (D2). Complete always returns strictly more than shallow | Gives the free tier something real while leaving the paid tier clearly worth buying — the free tier must never out-return the paid one. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | An Amazon Associates account can be obtained and retained | **High** — PA-API access is revoked without qualifying sales (V1) |
| A2 | Flipkart and Meesho listing pages expose price, rating and rating count without authentication | **High** — no discovery source otherwise |
| A3 | Category strings can be normalised across three marketplaces | **High** — fee resolution and comparison both depend on it (Q3) |
| A4 | A local model can derive usable review themes at run volume | Medium — degrades to rating-only insight |
| A5 | Trends data is obtainable at acceptable reliability | Medium — D3 makes this non-blocking |

---

## 4. Goals and non-goals

**Goals** — accept a structured niche + budget brief; discover candidate products across all three marketplaces within a bounded run; rank candidates on a labelled proxy score; derive review insight without persisting review text; discover qualified supplier leads; attach Trends signal where available; request feasibility figures from Brain 1; return a structured research report to CEO for synthesis.

**Non-goals (V1)** — bulk or continuous crawling · any financial calculation · supplier *ranking* · persisting review text, listing copy or images · sending raw expression to a hosted provider · writing to any marketplace · demand forecasting · Qdrant.

---

## 5. Data model and interfaces

```sql
niche_brief (                             -- 2A.6: structured intake. Authoring is NOT a direct execution path (fix 5).
  id uuid pk, tenant_id uuid not null,
  status text not null,                   -- DRAFT | READY | ARCHIVED — a run may only start from READY
  category_text text,                     -- seller's own words; open-ended, authored via CEO conversation or a plain form, never via a direct-path trigger
  budget_paise bigint,                    -- total procurement budget
  target_price_min_paise bigint, target_price_max_paise bigint,
  marketplaces text[],                    -- subset of AMAZON|FLIPKART|MEESHO
  constraints jsonb,                      -- e.g. {fragile:false, max_lead_days:30}
  created_by uuid not null, created_at timestamptz not null, readied_at timestamptz
)

pi_research_run (
  id uuid pk, tenant_id uuid not null,
  niche_brief_id uuid not null,           -- fk to an ALREADY-READY brief; the direct path never accepts free text (fix 5)
  depth text not null,                    -- SHALLOW | COMPLETE (D6)
  trigger text not null,                  -- DIRECT_UI | CEO_REQUEST
  candidate_cap int not null,             -- D2: 15/marketplace complete, 5/marketplace shallow, configurable
  status text not null,                   -- QUEUED|RUNNING|PARTIAL|COMPLETE|FAILED
  trends_status text not null,            -- OK | UNAVAILABLE | SKIPPED (D3)
  started_at timestamptz, finished_at timestamptz
)

product_candidate (                       -- observed facts only; NO listing copy, NO title paraphrase (C7, D5)
  id uuid pk, tenant_id uuid not null, run_id uuid not null,
  marketplace text not null,
  marketplace_item_id text,               -- ASIN | FSN | Meesho id
  title_length int, title_structure jsonb, keyword_themes jsonb,  -- derived attributes ONLY (D5); never the title text itself
  observed_category text, category_confidence text,
  listed_price_paise bigint, mrp_paise bigint,
  rating numeric(2,1), rating_count int,
  rank_position int,                      -- BSR or equivalent where published
  proxy_score numeric(6,2),               -- D1; an estimate, never a volume; null when proxy_state != COMPUTED
  proxy_state text not null,              -- COMPUTED | UNAVAILABLE — see §6.3; distinguishes "no signals at all" from "computed"
  proxy_basis jsonb not null,             -- which signals produced it
  source_url text not null, fetched_at timestamptz not null,
  capture_status text not null,           -- OK|BLOCKED|NOT_FOUND|PARSE_FAILED
  confidence text not null                -- OBSERVED | DERIVED | UNAVAILABLE — PI-scoped vocabulary; see §5.1 for the Brain 1 boundary rule
)

product_review_insight (                  -- derived only; mirrors CI §6.5 exactly
  id uuid pk, candidate_id uuid not null, tenant_id uuid not null,
  sentiment_split jsonb, rating_distribution jsonb,
  complaint_themes jsonb, positive_themes jsonb, summarised_patterns jsonb,
  reviews_considered int,
  confidence text not null, derivation_method text not null,
  insight_state text not null,            -- COMPLETE|DEGRADED|UNAVAILABLE
  degraded_reason text,
  source_url text not null, fetched_at timestamptz not null, derived_at timestamptz not null
)

supplier_lead (                           -- C4: discovery only, never ranked here
  id uuid pk, tenant_id uuid not null, run_id uuid not null,
  supplier_name text not null,
  source text not null,                   -- GOOGLE_PLACES | INDIAMART_LOOKUP
  contact jsonb,                          -- as published by the source
  locality text, distance_km numeric(6,2),
  category_match text,
  source_url text, fetched_at timestamptz not null
)

trend_signal (
  id uuid pk, run_id uuid not null, tenant_id uuid not null,
  keyword text not null, index_12m jsonb, direction text,
  source text not null, fetched_at timestamptz not null,
  status text not null                    -- OK | UNAVAILABLE (D3)
)

product_embedding (                       -- C13: pgvector, no Qdrant
  id uuid pk, tenant_id uuid not null,
  subject_type text not null,             -- CANDIDATE | THEME | CATEGORY
  subject_id uuid not null,
  embedding vector(768),                  -- nomic-embed-text, dimension fixed
  model_name text not null, model_dim int not null,
  created_at timestamptz not null
)

pi_tenant_config (                        -- retention policy, mirroring competitor-intelligence-agent.md's ci_tenant_config
  tenant_id uuid pk,
  candidate_retention_days int not null default 90,   -- product_candidate, product_review_insight, trend_signal
  supplier_lead_retention_days int not null default 90,
  updated_by uuid, updated_at timestamptz not null
)
```

**Similarity needs, served by pgvector (C13):** near-duplicate candidate detection across marketplaces (via `title_structure`/`keyword_themes`, never a title paraphrase — E12) · grouping complaint themes into clusters · matching a seller's niche text to observed categories · finding comparable products for a feasibility comparison. All operate on **derived attributes** (D5), never on raw marketplace expression. `model_name` and `model_dim` are stored so a model change is a detectable, scriptable re-index rather than silent corruption.

### 5.1 Confidence vocabulary boundary (fix 2)

PI's `confidence` column uses the same scoped vocabulary as `competitor-intelligence-agent.md` §5.1: `OBSERVED | DERIVED | UNAVAILABLE`. **The same boundary rule applies without exception: `OBSERVED` never crosses into Brain 1.** Any PI-observed value — `observed_category`, `listed_price_paise`, anything on `product_candidate` — enters an engine call as `DERIVED`, regardless of how PI recorded it internally. This preserves the monotonic-confidence rule (`data-foundation.md` §7.1, `deterministic-engine.md` §9): a figure built on a PI observation can never present as `VERIFIED` or `PROVISIONAL`.

**Interfaces PI calls** — all Brain 1 unless noted:

| Interface | Purpose | Returns |
|---|---|---|
| `landed_cost(manual_adjustment_ref, sku, quantity)` | Procurement cost where an actual seller quote exists | `metric_result`, `engine_result_ref` |
| `estimate_product_feasibility(...)` | Feasibility for a **discovered candidate the seller does not yet own** (`deterministic-engine.md` §5.13.2) | `product_feasibility_estimate`, **`estimate_ref` — never an `engine_result_ref`** |
| `resolve_fee_reference(marketplace, category, fee_type, as_of_date)` | Fees for feasibility; PI holds no rates | `fee_reference` row or a declared gap |

**PI does not call `margin_curve` and does not call `estimate_competitor_margin_range` (fix 3, fix 7).** `margin_curve` is reserved for a seller's own SKU and belongs to CFO (`cfo-agent.md` §6.7) — a discovered candidate has no owned COGS or `metric_result` lineage to price canonically. `estimate_competitor_margin_range` and its `competitor_estimate` table are **CI-exclusive** (`deterministic-engine.md` §5.13.1); PI reaching that surface from a discovered candidate would bypass CI's own entitlement gate and blur "seller-supplied competitor" (CI's job) with "PI-discovered candidate" (a different thing). Where a discovered candidate is genuinely worth comparing to competitors, that is a CEO-brokered handoff to CI (Q8), never a direct PI call.

---

## 6. Core rules

### 6.1 Intake — authoring is not a direct path (fix 5)

Two separate steps, deliberately not one:

1. **Authoring a `niche_brief`.** The seller describes what they want, in their own words, with CEO's conversational help if needed. This is open-ended by nature — `category_text` is free text, `constraints` is open `jsonb` — and per `auth.md` §5.2's guardrail ("no direct path may accept free-form input... anything open-ended requires `agent.ceo`"), it is **never** a direct execution path. It is either a **plain CRUD form** — a standard authenticated tenant-write, gated only by ordinary membership (no `agent.*` key, since no agent is invoked) — or a **conversational exchange** (`agent.ceo` + `agent.pi`) where CEO helps compose the brief. Either path writes the same `DRAFT` row.
2. **`DRAFT` → `READY`.** Any member who could author the brief may mark it `READY`, and only once budget, category and at least one marketplace are present — missing either blocks the transition and raises a data request rather than assuming a default. **A `READY` brief may be edited back to `DRAFT`** at any time before a run starts against it (correcting a mistake is always allowed); it may not be edited while a `pi_research_run` referencing it is `QUEUED` or `RUNNING`.
3. **`ARCHIVED`.** Set by the same member (or the owner) once the brief is no longer wanted for future runs. Archiving is a soft state, not a delete — prior runs and their `niche_brief_id` references remain valid and readable.
4. **Triggering a run from a `READY` brief.** The direct path `pi.discover` (§6.8) takes only `niche_brief_id` — a UUID referencing an already-authored, already-bounded, `READY` brief. No free text ever reaches a direct-path call. A brief in `DRAFT` or `ARCHIVED` cannot be passed to `pi.discover`.

### 6.2 Discovery
1. **Amazon:** PA-API 5.0 search within the brief's category and price band.
2. **Flipkart / Meesho:** on-demand fetch against the C6 allowlist, bounded by `candidate_cap`.
3. **Never a crawl.** A run touches only what the brief and cap permit, then stops.
4. Every candidate yields a row, including on failure — `capture_status` records why, so a thin result is explained rather than silent.

### 6.3 Ranking (C15, D1)

`proxy_score` is composed from **whatever signals a single run actually observed**: rank position, rating, rating count, price-band fit. `proxy_basis` records exactly which of these were available. **Review velocity is an optional refinement, added only when a prior `product_candidate` observation of the same `marketplace_item_id` exists from an earlier run against the same `niche_brief_id`** — it is never a required input, so a first run is never penalised for lacking history it cannot have.

`proxy_state = UNAVAILABLE` only when **none** of the base signals could be captured at all (e.g. total fetch failure); in that case `proxy_score` is null and the candidate is still reported, per E6/E5, with the gap named. `proxy_state = COMPUTED` whenever at least one base signal exists — the score is never withheld merely because velocity, a multi-run enrichment, is absent. Every surface renders it as an estimated interest proxy, never as units sold or revenue.

**Retention makes this comparison possible, and it stays on-demand (C15's "no bulk/continuous crawling" is unaffected).** Velocity compares two *already-triggered* runs — it never causes a fetch, never schedules one, and reads only what `pi_tenant_config.candidate_retention_days` (default 90 days) still has on disk. Exactly as `competitor-intelligence-agent.md` C19 states for its own retained snapshots: a bounded retention window that a later on-demand run may reference is not monitoring, because nothing happens between runs and no run is ever triggered by the passage of time.

### 6.4 Review insight (C7, C9)
Identical discipline to `competitor-intelligence-agent.md` §6.5 — raw text is transient, local-only, and never persisted to PostgreSQL, object storage, files, logs, traces, APM, Redis, vector stores, generated reports **or a hosted model provider**. Only the derived fields on `product_review_insight` survive. Where local derivation is unavailable, `insight_state = DEGRADED` from rating distribution alone, with `degraded_reason` recorded.

### 6.5 Google Trends (C14, D3, 2A.4)
In V1, **best-effort and never blocking**. Requests are **batched and cached by keyword** to survive rate limits. On failure, `trends_status = UNAVAILABLE`, the run completes, and the report states that trend signal was unavailable — it is never silently omitted and never substituted with an invented figure.

### 6.6 Supplier discovery (C4, C5)
Google Places by category and radius; IndiaMART by explicit single lookup only. Output is a **qualified lead list** — name, contact as published, locality, distance, category match. PI attaches **no score and no ranking**. Contact data is retained per `pi_tenant_config.supplier_lead_retention_days` (default 90 days — the final DPDP-appropriate value is still open, Q6) and is never bulk-harvested into a standing directory.

### 6.7 Feasibility (fix 3, fix 7)

PI assembles observations and calls **`estimate_product_feasibility`** (`deterministic-engine.md` §5.13.2) for a discovered candidate the seller does not yet own. It performs no arithmetic. The returned figure carries an **`estimate_ref`**, is always a range, and is rendered with its assumptions and any fee-reference gaps intact — never an `engine_result_ref`, and never `margin_curve`, which is CFO's canonical-SKU surface.

**PI never derives, estimates, or supplies a cost figure itself — it has no costing capability at all** (front matter: "PI researches. It never calculates"). There are exactly two cases:

1. **The seller has an actual `supplier.quote` for the candidate.** PI passes that quote's stated cost as `stated_cogs_paise`. The engine's `cogs_basis = STATED` on the result.
2. **No quote exists.** PI passes nothing for `stated_cogs_paise` — it never guesses, averages, or infers a cost from observed prices. The engine returns `cogs_basis = UNKNOWN` and a range describing price-and-fee spread only, explicitly **not** a margin estimate. PI renders that distinction verbatim; it is never presented to the seller as if a cost basis existed.

### 6.8 Registered direct execution paths

| Trigger id | Action | CEO call | Permission | Entitlement | Rate limit | Audit |
|---|---|---|---|---|---|---|
| `pi.discover(niche_brief_id)` | Run discovery from an already-`READY` brief (§6.1). **No free-form field accepted** | No | `agent.pi` **and** `research.niche_run` — two independent keys, identical two-meter pattern to `cfo-agent.md` §6.8 `cfo.gst_lookup` and `slim-cmo-agent.md` §8 `cmo.gst_answer` | `agent.pi`: PI entitlement, depth per C12. `research.niche_run`: its own OP9-style cap, metered independently — `403` if either key is missing | Per tenant | Yes |
| `pi.supplier_lookup` | Single supplier lookup | No | `agent.pi` | PI entitlement | Per tenant, strict | Yes |
| `pi.report` | Re-render a completed run | No | `agent.pi` | None | Per tenant | Yes |

**Authoring a `niche_brief` is never itself a direct-path trigger** (§6.1, fix 5) — it is either a plain form or a conversational exchange, and only the resulting `niche_brief_id` ever reaches `pi.discover`. Anything else open-ended is conversational and requires `agent.ceo` plus `agent.pi`.

**Why `research.niche_run` is a separate key, even though only PI consumes it.** The mechanism matches CFO's `service.gst_lookup` and CMO's `service.gst_lookup` — two independent keys, two independent meters — but the rationale is different, not a literal precedent: GST Lookup is genuinely shared across two agents. `research.niche_run` is consumed only here. Its purpose is **spend control**: niche discovery is the paid research run readiness §1 singles out ("Paid, on-demand research run"), and a tenant's OWNER may want a permission boundary between "may use PI at all" and "may spend the tenant's paid-research budget" — e.g. granting a partner `agent.pi` for reading past reports without granting them the ability to trigger a new billable run. The two-key *shape* is reused because it already solves exactly this separation; the *reason* for using it here is an access-control gate on spend, not multi-agent sharing.

### 6.9 Output to CEO
A run returns a **structured report object**, not prose: brief echo · ranked candidates with `proxy_basis` · review insight per candidate · supplier leads · trend signals with status · feasibility figures with `engine_result_ref` · and an explicit **`unavailable[]`** list naming everything that could not be obtained and why.

**CEO synthesises; PI does not.** PI never addresses the seller directly, never merges another agent's output, and never editorialises. CEO composes the narrative, decides what to surface first, and routes to CFO or CMO where the seller's follow-up calls for it (star topology, C11).

---

## 7. AI requirements

| Brain | Role in PI |
|---|---|
| **Brain 1** | Every financial figure — feasibility, landed cost, margin at price. No LLM. |
| **Brain 2** | Statistical signals only (trend direction, outlier pricing). Spec unwritten — see Q5. |
| **Brain 3** | Interpreting the brief, selecting sources, classifying review themes, and composing the structured report. |

**Model output boundary.** Where derivation uses a local model, the model performs **classification only** — sentiment class, theme tags, category match. Deterministic code aggregates those labels into proportions, counts and `proxy_score`. **The model never emits a proportion, a weight, a score or a count.**

**Brain 3 emits no number of its own, anywhere (fix 8).** Every number in PI's structured report (§6.9) — `proxy_score`, price fields, feasibility figures, rating counts — is copied verbatim from a `product_candidate` row, a `trend_signal`, or an engine result (`engine_result_ref` / `estimate_ref`). Brain 3 composes the surrounding narrative and selects what to surface; it never restates, rounds, adjusts, or originates a figure. This is the same rule as `cfo-agent.md` AC2, applied here for the first time in this spec.

Raw rows and raw text never enter a hosted provider (C9, OP5).

---

## 8. Authorization and security

1. Every request enters the `auth.md` §7.1 six-step chain; PI adds no bypass.
2. Permission (`agent.pi`) and entitlement (cart, run credit) are independent gates; both must pass.
3. Conversational access additionally requires `agent.ceo`; direct paths (§6.8) do not.
4. Allowlists are enforced **server-side**, per purpose (C6). A source outside its scoped list is refused.
5. Tenant-scoped throughout; RLS is the final boundary. Background runs set tenant context from the job payload or fail closed.
6. Outbound fetches are rate-limited and identify honestly; `robots.txt` posture follows the CI open question (CI Q10), not a separate rule.
7. Supplier contact data is personal data under DPDP where the supplier is a proprietor — retained per run, never accumulated (C5).

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | PA-API access revoked | Amazon discovery reports unavailable; run completes for the other two, `unavailable[]` names it |
| E2 | Fetch blocked on Flipkart/Meesho | `BLOCKED`; cached served if ≤7 days, else unavailable (C10) |
| E3 | Trends unavailable | `trends_status = UNAVAILABLE`; run completes; stated in the report (D3) |
| E4 | Local model unavailable | Review insight `DEGRADED` from ratings; **never** sent to a hosted provider (C9) |
| E5 | Fewer candidates than the cap | Reported honestly; never padded |
| E6 | Zero candidates, or a candidate with no signal at all | Empty result / `proxy_state = UNAVAILABLE`, reasons named; never fabricated (§6.3) |
| E7 | Category unresolvable | Feasibility suppressed for that candidate; fee resolution cannot proceed (Q3) |
| E7b | First run on a niche — no prior observation exists | `proxy_score` computed from base signals alone; review velocity simply absent from `proxy_basis`, never causing suppression (§6.3, D1) |
| E7c | Seller authors free-text niche details | Handled by a plain form or CEO conversation; never reaches `pi.discover` directly — only the resulting `niche_brief_id` does (§6.1) |
| E7d | Seller asks PI for a competitor-margin-style estimate on a discovered candidate | Refused; PI has no access to `estimate_competitor_margin_range`. Whether and how CEO can hand the candidate to CI as an observation is **pending Q8** — no mechanism exists yet in either spec |
| E8 | No supplier leads in radius | Reported as none found; radius shown |
| E9 | Seller asks PI to rank suppliers | Refused; routed via CEO to CFO once quotes exist (C4) |
| E10 | Seller asks for units sold | Explained as unavailable; proxy offered with its basis (C15) |
| E11 | Shallow run hits a complete-run feature | Gated; the upgrade path is named, nothing silently degraded |
| E12 | Duplicate candidate across marketplaces | Detected by pgvector similarity, grouped, both sources retained |
| E13 | Run exceeds latency budget | `PARTIAL`; completed candidates retained |
| E14 | Embedding model changed | Detected via `model_name`/`model_dim`; re-index required before similarity is trusted |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | **Amazon Associates account and PA-API approval** (A1) | All Amazon discovery |
| V2 | Flipkart/Meesho page structure and anti-bot behaviour (A2) | Discovery on two of three marketplaces |
| V3 | Category taxonomy mapping (A3, Q3) | Feasibility and cross-marketplace comparison |
| V4 | Trends source reliability (A5) | §6.5 quality, not run completion |
| V5 | Local derivation quality at run volume (A4) | §6.4 |
| V6 | Google Places quota and cost | §6.6 |
| V7 | Legal review of fetching and contact retention | Launch |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | PI contains no financial formula. |
| AC1b | Every **canonical** financial figure PI renders (e.g. `landed_cost`) carries an `engine_result_ref`. |
| AC1c | Every **feasibility estimate** for a discovered candidate carries an `estimate_ref` (`product_feasibility_estimate.id`) and never an `engine_result_ref`; PI never calls `margin_curve` for a candidate the seller does not own. |
| AC1d | PI never calls `estimate_competitor_margin_range`; `competitor_estimate` is CI-exclusive. |
| AC2 | `proxy_score` is never labelled as units sold, sales or revenue. |
| AC3 | No review text, listing copy or rehosted image is persisted anywhere, including vector storage. |
| AC4 | No raw expression is transmitted to a hosted model provider. |
| AC5 | No embedding is generated from raw marketplace copy. |
| AC6 | Every run is explicitly triggered; no scheduled discovery exists. |
| AC7 | Every run respects `candidate_cap` and its purpose-scoped allowlist. |
| AC8 | PI emits no supplier score or ranking. |
| AC9 | A Trends failure never fails a run, and is always disclosed. |
| AC10 | Every report carries an `unavailable[]` list. |
| AC11 | Qdrant is not used; all similarity runs on pgvector with `model_name`/`model_dim` recorded. |
| AC12 | PI output is structured; CEO composes all seller-facing narrative. |
| AC13 | Permission and entitlement are evaluated independently. |
| AC14 | Background runs without tenant context fail closed. |
| AC15 | No PI-`OBSERVED` value crosses into a Brain 1 call as anything other than `DERIVED` (§5.1). |
| AC16 | `pi.discover` accepts only `niche_brief_id`; no free-text or open `jsonb` field reaches a direct-path call (§6.1, §6.8). |
| AC17 | `pi.discover` is denied with `403` if either `agent.pi` or `research.niche_run` is missing (§6.8). |
| AC18 | No `product_candidate` row stores a title paraphrase; only `title_length`, `title_structure` and `keyword_themes` are persisted (D5). |
| AC19 | A complete run always returns strictly more candidates per marketplace than a shallow run (D2, D6). |
| AC20 | No number in PI's structured report is emitted by an LLM; every number traces to a stored observation or an engine result (§7). |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Complete run, valid brief | Candidates across three marketplaces, ranked, capped |
| T2 | PA-API returns 403 | Amazon unavailable; other two complete (E1) |
| T3 | Trends times out | Run completes, `UNAVAILABLE` disclosed (AC9) |
| T4 | Local model down | Review insight `DEGRADED`; no outbound provider call (AC4) |
| T5 | Grep all stores for a known review phrase | Zero hits (AC3) |
| T6 | Inspect embeddings for raw copy | None; derived attributes only (AC5) |
| T7 | Seller asks "how many units sell?" | Proxy with basis, explicitly not a volume (AC2) |
| T8 | Seller asks PI to rank suppliers | Refused; CFO path named (E9, AC8) |
| T9 | Shallow run requests review insight | Gated; upgrade named (E11) |
| T10 | Same product on two marketplaces | Grouped by similarity; both sources kept (E12) |
| T11 | Request outside the marketplace allowlist | Refused server-side (AC7) |
| T12 | Supplier lookup outside the supplier allowlist | Refused (C6) |
| T13 | `pi.discover` by a partner with `agent.pi` **and** `research.niche_run`, no `agent.ceo` | Succeeds on the direct path — `agent.ceo` is never required off the conversational route (§6.8, C11) |
| T14 | Conversational PI request without `agent.ceo` | `403` |
| T15 | No run credit | Denied by entitlement, not permission (AC13) |
| T16 | Inspect PI for a fee rate table | None present (AC1) |
| T17 | Embedding model swapped | Mismatch detected; re-index required (E14) |
| T18 | Zero candidates found | Empty result with reasons (E6) |
| T19 | First-ever run on a brand-new niche | `proxy_score` computed from base signals; velocity absent, no suppression (E7b, D1) |
| T20 | `pi.discover` called with a `category_text` field instead of `niche_brief_id` | Rejected — direct paths accept only the enumerated `niche_brief_id` (AC16) |
| T21 | `pi.discover` with `agent.pi` but no `research.niche_run` | `403` (AC17) |
| T22 | Inspect any `product_candidate` row for title text | Only `title_length`/`title_structure`/`keyword_themes` present, no paraphrase (AC18) |
| T23 | Compare complete vs shallow candidate counts for the same brief | Complete strictly exceeds shallow (AC19) |
| T24 | PI attempts `estimate_competitor_margin_range` | Not callable; interface absent from PI's surface (AC1d) |
| T25 | Discovered-candidate feasibility rendered | Carries `estimate_ref`, range only, never `engine_result_ref` (AC1c) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | **Trends source** — pytrends (free, fragile) or a paid provider? C14 puts Trends in V1; D3 makes it non-blocking, but sustained failure makes the feature decorative. | 🔴 §6.5 |
| Q2 | **PA-API dependency.** Associates access requires qualifying affiliate sales. If revoked, does Amazon discovery move to on-demand fetch like the other two? | 🔴 §6.2 |
| Q3 | **Category taxonomy mapping** — the same gap as CI Q8. Three marketplace taxonomies plus the fee reference store's. | 🔴 Feasibility |
| Q4 | **`proxy_score` weights** — configuration, and what basis? Nothing locked. | §6.3 |
| Q5 | **Brain 2 spec does not exist** (readiness §7 item 8). | §7 |
| Q6 | **Supplier contact retention window** under DPDP. | §6.6, V7 |
| Q7 | **Shallow/complete boundary** (D6) and free-tier caps are provisional. | Entitlement spec |
| Q8 | **Does a candidate observation feed CI's competitor set**, and if so, how under star topology? | Orchestration |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Supplier ranking | **PI discovers only** (C4). CFO ranks from seller quotes. |
| R2 | Units sold | **Not obtainable.** Proxy score with declared basis (C15, D1). |
| R3 | Qdrant | **Not used.** pgvector, dimension pinned (C13). |
| R4 | Review text | **Transient, local-only, never persisted** (C7, C9). |
| R5 | Trends in V1 | **Yes**, best-effort with a mandatory degraded state (C14, D3). |
| R6 | Feasibility provenance contract | **Resolved via `deterministic-engine.md` §5.13.2.** Discovered candidates get a dedicated `estimate_product_feasibility` interface returning `estimate_ref`, structurally separate from CFO's `margin_curve` (`engine_result_ref`) and from CI's `competitor_estimate`. PI never calls either of the other two (D4, §6.7, AC1c/AC1d). **`stated_cogs_paise` is optional and seller-quote-sourced only** — PI supplies nothing when no quote exists, and the engine returns `cogs_basis = UNKNOWN` rather than a disguised margin figure (§6.7). |
| R13 | Retention policy for observed data | **Resolved.** `pi_tenant_config` (§5), default 90 days, mirroring `competitor-intelligence-agent.md` C19. Velocity comparison reads only within this window and never triggers a fetch — bounded retention referenced by a later on-demand run is not monitoring (§6.3). |
| R14 | `agent.pi` vs `research.niche_run` in C11 | **Resolved.** C11 now states the two-key requirement explicitly rather than the single-key claim it previously made in isolation from §6.8. |
| R7 | `research.niche_run` permission treatment | **Resolved — matches `cfo-agent.md`/`slim-cmo-agent.md` exactly.** Two independent keys (`agent.pi` + `research.niche_run`), two independent meters, `403` if either is missing (§6.8, AC17). |
| R8 | Free-form input on a direct path | **Resolved.** Authoring a `niche_brief` is a plain form or a CEO conversation, never a direct-path trigger. `pi.discover` accepts only `niche_brief_id` (§6.1, §6.8, AC16). |
| R9 | Title embedding vs expression | **Resolved.** No paraphrase is stored or embedded. Only `title_length`, `title_structure`, `keyword_themes` — matching `competitor-intelligence-agent.md` C16's rule exactly (D5, AC18). |
| R10 | Shallow/complete candidate-count inversion | **Resolved.** Complete = top 15/marketplace; shallow = top 5/marketplace. Complete strictly exceeds shallow (D2, D6, AC19). |
| R11 | `proxy_score` suppression on first run | **Resolved.** Review velocity is an optional enrichment, never a required signal; `proxy_state` distinguishes "no signals at all" from "computed" (§6.3, D1). |
| R12 | Brain 3 number-emission boundary | **Resolved.** Same rule as `cfo-agent.md` AC2 — no LLM-originated number anywhere in PI's output (§7, AC20). |
