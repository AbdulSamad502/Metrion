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
| C11 | **Star topology.** Conversational access via CEO; registered direct execution paths require `agent.pi` alone. Brain 1 callable directly. | readiness §1 — Topology, Execution paths |
| C12 | **Entitlement:** free PI is limited (5 shallow runs/month); complete PI is a paid cart item. Values provisional. | readiness §1 — Agent cart |
| C13 | **pgvector, not Qdrant.** All similarity and semantic search in V1 uses pgvector on the existing Postgres. | readiness §1 — RAG |
| C14 | **Google Trends is in V1** under the flat merge, with a mandatory degraded state (§6.5). | readiness §1 — Versioning; 2A.4 |
| C15 | **Proxy ranking, never "units sold."** Marketplaces do not publish unit volumes. | 2A.1 |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Candidate ranking basis | A **composite proxy score** from rank position, rating count, review velocity and price band — labelled an estimate, never a volume | C15. Presenting a proxy as sales data is the fastest way to lose a seller's trust. |
| D2 | Discovery breadth | **Capped per run**, configurable, default 60 candidates → top 5 per marketplace | C3 requires a cap. 60 keeps a run bounded and latency tolerable. |
| D3 | Trends dependency posture | **Best-effort, never blocking.** A run completes without Trends and says so | pytrends is unofficial and breaks without notice (V4). |
| D4 | Feasibility figures | Always from Brain 1 via `margin_curve` / `landed_cost` | PI holds no rates and no formulas (C1 of the engine boundary). |
| D5 | pgvector use | Embed **derived attributes** — theme vectors, category text, product titles as *our* normalised phrasing — never raw marketplace copy | C7/C9. An embedding of scraped review text is a stored derivative of expression. |
| D6 | Shallow vs complete run | Shallow = top-10 per marketplace, no review derivation, no supplier discovery, no Trends. Complete = full pipeline | Gives the free tier something real while leaving the paid tier clearly worth buying. |

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
niche_brief (                             -- 2A.6: structured intake, not free chat
  id uuid pk, tenant_id uuid not null,
  category_text text not null,            -- seller's own words
  budget_paise bigint not null,           -- total procurement budget
  target_price_min_paise bigint, target_price_max_paise bigint,
  marketplaces text[] not null,           -- subset of AMAZON|FLIPKART|MEESHO
  constraints jsonb,                      -- e.g. {fragile:false, max_lead_days:30}
  created_by uuid not null, created_at timestamptz not null
)

pi_research_run (
  id uuid pk, tenant_id uuid not null,
  niche_brief_id uuid not null,
  depth text not null,                    -- SHALLOW | COMPLETE (D6)
  trigger text not null,                  -- DIRECT_UI | CEO_REQUEST
  candidate_cap int not null,             -- D2, configurable
  status text not null,                   -- QUEUED|RUNNING|PARTIAL|COMPLETE|FAILED
  trends_status text not null,            -- OK | UNAVAILABLE | SKIPPED (D3)
  started_at timestamptz, finished_at timestamptz
)

product_candidate (                       -- observed facts only; NO listing copy (C7)
  id uuid pk, tenant_id uuid not null, run_id uuid not null,
  marketplace text not null,
  marketplace_item_id text,               -- ASIN | FSN | Meesho id
  normalised_title text,                  -- OUR phrasing, not copied (D5)
  observed_category text, category_confidence text,
  listed_price_paise bigint, mrp_paise bigint,
  rating numeric(2,1), rating_count int,
  rank_position int,                      -- BSR or equivalent where published
  proxy_score numeric(6,2),               -- D1; an estimate, never a volume
  proxy_basis jsonb not null,             -- which signals produced it
  source_url text not null, fetched_at timestamptz not null,
  capture_status text not null,           -- OK|BLOCKED|NOT_FOUND|PARSE_FAILED
  confidence text not null                -- OBSERVED | DERIVED | UNAVAILABLE
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
```

**Similarity needs, served by pgvector (C13):** near-duplicate candidate detection across marketplaces · grouping complaint themes into clusters · matching a seller's niche text to observed categories · finding comparable products for a feasibility comparison. All operate on **derived attributes** (D5), never on raw marketplace expression. `model_name` and `model_dim` are stored so a model change is a detectable, scriptable re-index rather than silent corruption.

**Interfaces PI calls** — all Brain 1 unless noted:

| Interface | Purpose |
|---|---|
| `landed_cost(manual_adjustment_ref, sku, quantity)` | Procurement cost where a seller quote exists |
| `margin_curve(sku, candidate_prices[], period, as_of_date)` | Feasibility at candidate price points |
| `resolve_fee_reference(marketplace, category, fee_type, as_of_date)` | Fees for feasibility; PI holds no rates |
| `estimate_competitor_margin_range(...)` | Only where a candidate doubles as a competitor observation |

---

## 6. Core rules

### 6.1 Intake
A run begins from a `niche_brief` (2A.6) — a structured form, never free text alone. Missing budget or category blocks the run and raises a data request rather than assuming a default.

### 6.2 Discovery
1. **Amazon:** PA-API 5.0 search within the brief's category and price band.
2. **Flipkart / Meesho:** on-demand fetch against the C6 allowlist, bounded by `candidate_cap`.
3. **Never a crawl.** A run touches only what the brief and cap permit, then stops.
4. Every candidate yields a row, including on failure — `capture_status` records why, so a thin result is explained rather than silent.

### 6.3 Ranking (C15, D1)
`proxy_score` is composed from rank position, rating count, review velocity and price-band fit. `proxy_basis` records which signals were available. **Every surface renders it as an estimated interest proxy, never as units sold or revenue.** Where signals are missing the score is suppressed rather than computed from a thinner basis.

### 6.4 Review insight (C7, C9)
Identical discipline to `competitor-intelligence-agent.md` §6.5 — raw text is transient, local-only, and never persisted to PostgreSQL, object storage, files, logs, traces, APM, Redis, vector stores, generated reports **or a hosted model provider**. Only the derived fields on `product_review_insight` survive. Where local derivation is unavailable, `insight_state = DEGRADED` from rating distribution alone, with `degraded_reason` recorded.

### 6.5 Google Trends (C14, D3, 2A.4)
In V1, **best-effort and never blocking**. Requests are **batched and cached by keyword** to survive rate limits. On failure, `trends_status = UNAVAILABLE`, the run completes, and the report states that trend signal was unavailable — it is never silently omitted and never substituted with an invented figure.

### 6.6 Supplier discovery (C4, C5)
Google Places by category and radius; IndiaMART by explicit single lookup only. Output is a **qualified lead list** — name, contact as published, locality, distance, category match. PI attaches **no score and no ranking**. Contact data is retained only for the run's retention window and is never bulk-harvested into a standing directory.

### 6.7 Feasibility
PI assembles observations and calls Brain 1 (§5). It performs no arithmetic. Returned figures carry their `engine_result_ref` and are rendered with assumptions intact.

### 6.8 Registered direct execution paths

| Trigger id | Action | CEO call | Permission | Entitlement | Rate limit | Audit |
|---|---|---|---|---|---|---|
| `pi.discover` | Run discovery from a brief | No | `agent.pi` | `research.niche_run` credit; depth per C12 | Per tenant | Yes |
| `pi.supplier_lookup` | Single supplier lookup | No | `agent.pi` | PI entitlement | Per tenant, strict | Yes |
| `pi.report` | Re-render a completed run | No | `agent.pi` | None | Per tenant | Yes |

Anything open-ended is conversational and requires `agent.ceo` plus `agent.pi`.

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

**Model output boundary.** Where derivation uses a local model, the model performs **classification only** — sentiment class, theme tags, category match. Deterministic code aggregates those labels into proportions, counts and `proxy_score`. **The model never emits a proportion, a weight, a score or a count.** Raw rows and raw text never enter a hosted provider (C9, OP5).

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
| E6 | Zero candidates | Empty result with reasons; never fabricated |
| E7 | Category unresolvable | Feasibility suppressed for that candidate; fee resolution cannot proceed (Q3) |
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
| AC1 | PI contains no financial formula; every figure carries an `engine_result_ref`. |
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
| T13 | `pi.discover` by a partner with `agent.pi`, no `agent.ceo` | Succeeds on the direct path (§6.8) |
| T14 | Conversational PI request without `agent.ceo` | `403` |
| T15 | No run credit | Denied by entitlement, not permission (AC13) |
| T16 | Inspect PI for a fee rate table | None present (AC1) |
| T17 | Embedding model swapped | Mismatch detected; re-index required (E14) |
| T18 | Zero candidates found | Empty result with reasons (E6) |

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
