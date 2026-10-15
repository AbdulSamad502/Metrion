# Metrion — Phase 1 Readiness Review

**Reviewed:** `docs/planning/metrion-master-plan.pdf` (20 pp.) · the gap/conflict analysis · all decisions taken in session · `docs/specs/data-foundation.md`
**Purpose:** determine whether specification writing (Phase 2) can proceed.

Classification: **[B]** Blocking · **[P]** Important but can be provisional · **[D]** Non-blocking / deferred

---

## 1. Resolved decisions

### Product shape
| Decision | Resolution |
|---|---|
| Seller data source | Upload-only. No marketplace APIs for seller data. |
| Marketplaces | Amazon + Flipkart + Meesho at V1. |
| Write-back | None. Recommend-only; every output is a proposal. |
| Interface | CEO is the sole **conversational** interface. Dashboards and buttons are the deterministic fast path. |
| Dashboards | Four tier-aware panels: Profit & P&L, Products, Competitors, Leaks & Alerts. "Specs" folds into Products. |
| Orders / Customers / Inventory | Out. Replaced by SKU and order profitability. |
| **Team model** | **Teams are V1** (supersedes the p.5 reading that placed them under V2 COO). One tenant = one business workspace, one OWNER plus multiple PARTNERs with an explicit permission grid. Identity via Clerk Organizations. See `auth.md`. |
| Versioning | Flat merge — one V1, no V1.5 tier. |
| Agent canvas | n8n-style nodes controlling **availability only**. No user-drawn edges; CEO always owns routing. |

### Agents and monetisation
| Decision | Resolution |
|---|---|
| Calculation ownership | One shared deterministic Brain 1 service. No agent owns the math; CFO owns interpretation. |
| Agent cart | Retained. Free: CEO (capped), Slim CMO (capped), PI limited, CI limited. Cart: CFO, complete PI, complete CI. |
| Free-tier caps | CEO 30/mo · CMO 10/mo · PI 5 runs/mo shallow · CI 3 URLs + 5 runs/mo. **Config values, provisional.** |
| Pricing | Deferred to pre-launch. Four seams built now: metered events, account→plan chain, entitlement chokepoint, GST fields. |
| Entitlement chokepoint | Live from day one, not a stub — the cart requires it. |
| Partner program / spin wheel | Built last, gated on the credit model. |

### Intelligence and data
| Decision | Resolution |
|---|---|
| Competitor data | Seller-supplied URLs, stored. On-demand scraping only, user- or WhatsApp-triggered. No live monitoring. |
| PI product discovery | Amazon PA-API; Flipkart and Meesho via the same on-demand scrape model. |
| Supplier discovery | Discovery, not ranking. Google Places primary; IndiaMART user-initiated only. Ranking comes from a seller-filled quote comparison. |
| Batch size | Retained — sales velocity from reports + seller-entered lead time and MOQ. |
| Statistical detection | Available immediately. |
| Forecasting | Gated at 6 complete months. Below that: "Market Outlook" from web search + trends, with structured disclosure of the metrics used. |
| RAG | Policy knowledge base **and seller document upload** on pgvector. No Qdrant in V1. |
| Scraping posture | Facts not expression; user-triggered; short-lived cache; link back to source. |

### Engineering
| Decision | Resolution |
|---|---|
| Dev LLM | Local Ollama. qwen3:4b inner loop, qwen3:8b correctness checks, thinking mode off for tool calls, `num_ctx` 8192. |
| Provider abstraction | Required from the first commit. |
| Money representation | Signed `BIGINT` paise, seller perspective. |
| Ingestion | Immutable raw files, versioned re-runnable parse runs, per-source adapters. |
| Calculator website | Deferred; built pre-deployment as a marketing asset. |

### Agent architecture — confirmed final (Phase 1 close)

| Decision | Resolution |
|---|---|
| **Topology** | **Star, confirmed.** CEO owns all agent-to-agent routing. No direct agent-to-agent reasoning edges in V1. Future cross-agent delegation must be CEO-brokered. |
| **Execution paths** | Two, with different permission requirements. **Conversational route:** open-ended request to CEO, which routes; requires `agent.ceo` plus the target agent's key. **Direct execution path:** a pre-enumerated, non-conversational action the member selects explicitly (a dashboard button); requires the target agent's key alone. Direct paths are registered individually, accept no free-form input, and there is no generic "invoke agent" endpoint. CEO remains the sole conversational interface and sole router. See `auth.md` §5.2. |
| **Brain 1 access** | All agents may call Brain 1 directly for deterministic calculation. Brain 1 is a shared service, not any agent's property. |
| **Rationale** | Preserves the agent cart and entitlement boundaries, keeps traceability, prevents uncontrolled cost fan-out. A free agent (CMO) cannot leak paid output (CFO). |
| **True Margin ownership** | Brain 1 is the single source of truth for all margin and profit calculation. CI supplies competitor-observed inputs only — selling price, visible discounts, source metadata. **Superseded detail (B9/C18):** CI supplies **no fees and no rates**; Brain 1 resolves those from its own versioned fee reference store (`deterministic-engine.md` §5.14). CI must not hold or compute a separate margin formula. CFO interprets outputs. |
| **Leak Shield ownership** | Powers sit with the **CFO agent** as interpreter: margin calculation, anomaly detection, and reconciliation of transactions, orders, settlements, returns, and logistics (where the seller supplies logistics data). Split across brains per §1.x below. **Amended:** *ranking* (ordering by amount, age or claim window) is arithmetic and computed deterministically in Brain 1; Brain 3 retains *prioritisation as judgement* — which finding matters most and why. See `deterministic-engine.md` §5.12 and `cfo-agent.md` D10. |
| **Niche discovery** | Paid, on-demand research run. Structured niche + budget input; user-triggered, bounded, rate-limited; capped and configurable candidate volume. No continuous crawling or bulk scraping. Results label estimates, sources, timestamps, and unavailable data. Complete PI remains a cart item. |
| **Supplier ownership** | **PI discovers** — qualified supplier leads and contact details. **CFO ranks** — only after the seller provides quotes or structured supplier data (price, MOQ, lead time, shipping, payment terms, reliability notes). CI has no supplier responsibility in V1. |
| **Review handling** | No storage or reproduction of full review text. Derived insight only: sentiment split, complaint themes, positive themes, rating distribution, summarised patterns. Source listing links retained. Provenance and timestamp on every derived insight. |
| **Image handling** | No rehosting of marketplace images. Permitted hotlinks or thumbnails where technically and legally appropriate; otherwise source links or placeholders. |

### Operational policies — confirmed final (Phase 1 close)

| # | Policy | Resolution |
|---|---|---|
| OP1 | **Seller data entry** | Manual entry **or** marketplace MTR/report upload. Where an agent needs data it does not have, it may **request it from the seller** — a structured agent-initiated data request, not a silent default. |
| OP2 | **Trusted sources — three purpose-scoped allowlists** | **(a) Marketplace research:** official India domains only — `amazon.in`, `flipkart.com`, `meesho.com`. Seller-supplied URLs outside the list are refused with a clear message. **(b) Supplier discovery:** Google Places API, IndiaMART. **(c) GST lookup / Market Outlook:** government and tax-authority sources, plus approved trend sources. No global allowlist; each surface is scoped separately. |
| OP3 | **Scrape-failure fallback** | Serve the cached snapshot with a visible age stamp up to **7 days**. Beyond that, report unavailable rather than mislead. Never fabricate. |
| OP4 | **Database failure** | **RPO 15 minutes** via WAL archiving; **RTO 4 hours**. Raw uploaded files replicated separately — they are the only irreplaceable asset, since every derived figure is re-computable. |
| OP5 | **Large uploads / context discipline** | Raw rows are **never** sent to an LLM. Files are parsed, cleaned, validated and stored; questions are answered by computation over stored data or by a pre-aggregated summary view. The LLM structures the final answer only. |
| OP6 | **Anomaly detection** | Runs only where the seller has uploaded data. Statistical at V1 per Q30 — no trained models. |
| OP7 | **CMO catalog scope** | CMO answers marketplace-catalog questions (descriptions, catalog fields). **~~Product GST questions, calling the shared GST Applicability Lookup~~ — SUPERSEDED 2026-10-03:** CMO has no GST path. CEO handles product GST questions by permission: **Route A** — `cfo.gst_lookup` for members with `agent.cfo` (existing OP13 resolution); **Route B** — CEO's own call to the shared GST Applicability Lookup service for members with `service.gst_lookup` but no `agent.cfo`, tier 3 / provisional only, shipped only if the safety conditions G1–G7 are demonstrated by test (no permission bypass, independent metering, never convertible to a calculation input without CFO acceptance). Results are sourced, dated, uncertain, never claimed verified. See `slim-cmo-agent.md` C4/§6.9, `ceo-agent-orchestration.md` C11/§6.9. |
| OP8 | **Product image input** | The seller may upload a photo of their own product for better CMO output. Seller-supplied images only; no marketplace images. Resolves §2.27. **Amended 2026-10-03:** the asset store now has an owning spec — `slim-cmo-agent.md` §5 `seller_image_asset` (object-store URI, SHA-256, immutable; never bytes in Postgres). Retention policy and limits remain open (2.31). |
| OP9 | **Shared-service principle** | **Bounded services are shared; agent reasoning is CEO-brokered.** Brain 1 and GST Applicability Lookup are callable by any agent. Anything requiring another agent's *reasoning* routes through CEO. Shared services carry their own entitlement caps. |
| OP10 | **LLM computation access** | **Fixed tool catalog** with typed, pre-built, tested tools. No LLM-generated SQL or Python execution in V1. Matches planning doc p.11. |
| OP11 | **Vision pipeline** | External vision model extracts a **defined structured schema** from the seller's product image; the local text model consumes only that structure. Vision sits behind a `VisionProvider` abstraction slot, swappable like the LLM provider. **Amended 2026-10-03:** vision may emit only `IMAGE_OBSERVED`/`UNKNOWN` attributes and never a price, weight or dimension. **Trust gate (decided):** image-derived facts are `UNVERIFIED_HINT` — never used as claims — until a provider passes a recorded evaluation (CI Q18 measured the local llava 7B reporting absent fields and dropping digits). Pass-bar values are a human decision (`slim-cmo-agent.md` §6.2.1, Q4). |
| OP12 | **Seller document RAG** | In V1, on pgvector. No Qdrant. |
| OP13 | **GST rate source — layered, in precedence order** | **(1) Observed** from the seller's own uploaded reports (`CGST %`, `SGST %`, `IGST %` are present per line) — authoritative for anything they have sold. **(2) Curated HSN→rate knowledge base** maintained by Metrion in the policy KB — for products not yet sold. **(3) GST Applicability Lookup** (web, provisional) — fallback for unknown or new products. Sellers are never asked to upload rate schedules. |
| OP14 | **GST Portal is not a Metrion data source** | Metrion never logs in to the GST Portal and never asks for GST credentials. If a tax figure is needed and is missing from uploaded reports, the agent **asks the seller for it** (OP1). Consistent with T3 (no GSTIN or credentials at signup) and T4 (file-first). The GSTR2A TCS cross-check described in the mapping PDF is explicitly **not adopted**. |

| OP15 | **CMO V1 workflow** *(2026-10-03)* | CEO accepts image, product details, target price and 1–3 marketplaces → CMO analyses the image and produces **5 marketplace-specific SEO title options per marketplace** → the seller **approves one** (persisted approval record) → CMO generates description, bullets and keywords grounded in that title. Hashtags only where marketplace support is established; in V1 none is, so they are a separate optional artefact. Catalog Q&A labels every attribute `SELLER_PROVIDED | IMAGE_OBSERVED | ESTIMATED | SOURCE_DERIVED | UNKNOWN`. Independent and CI-informed generation are both supported; CI input is optional and never blocking. Recommend-only throughout. Full detail: `slim-cmo-agent.md`. |
| OP16 | **CMO billing semantics** *(2026-10-03)* | One artefact delivered = one row = one unit. A five-title set for one marketplace is **one** unit; three marketplaces are **three**. The post-approval **listing copy pack (description + bullets + keywords) is one artefact = one unit per marketplace** (full three-marketplace workflow = 6 units). Only delivered artefacts consume a unit; failed artefacts consume none; internal retries consume none; a seller-initiated regeneration is a new artefact and a new unit; approval is free; duplicates are idempotent. Multi-marketplace requests are entitlement-checked up-front for their full count (all-or-nothing). Cap values remain provisional config — none seeded or invented (3.5). |
| OP17 | **Market-trend research** *(2026-10-03, expanded round 3)* | CMO answers "what's trending" in **seven sections**: your niche · marketplace and e-commerce news (policy, fees, seller programs, seasonal) · reported tactics (attributed, unverified, policy-risk-flagged, never recommended if rule-breaking) · new products and buzz · adjacent opportunities (separate from PI ranking) · CMO's labelled interpretation · evidence and limitations. Dated, cited web signals only; **source counts, independence, recency and corroboration are computed deterministically** (same-source repeats count once); attention/agreement is never presented as demand, sales or profitability. Architecture: a **shared Market Signal Retrieval service** (OP9 pattern; Tavily + YouTube, lifted from PI's `sources/` behind the R9 gate) retrieves; CMO interprets; PI is neither called nor duplicated. Own permission key (`research.market_trends`) and meter. All budgets, windows and thresholds are configuration with no defaults (missing ⇒ `CONFIG_MISSING`). Provider capabilities are verified in a probe before build, not assumed. Google Trends / keyword-volume remain unavailable. See `slim-cmo-agent.md` §6.8. |
| OP18 | **Catalog-seeded niche and research egress** *(2026-10-03, round 3)* | CMO may suggest niche terms from the seller's own ingested catalog (distinct item titles only, deterministic derivation, no LLM), shown for seller confirmation **before any external research**. Only confirmed, identifier-screened niche terms may be sent to research providers; raw reports, customer data, financial figures, images and prices never are. Every outbound query is shown first and persisted for audit. See `slim-cmo-agent.md` C15/§6.8.3. |
| OP19 | **Marketplace-specific listing copy and constraint integrity** *(2026-10-03, round 3)* | Each approved title produces its own marketplace-specific pack (description + bullets + keywords) from claim-eligible facts and that marketplace's VERIFIED, non-stale format constraints, enforced deterministically; missing/stale/unverified constraints block production generation for that marketplace; `TEST_FIXTURE` rows are test-only. No publishing or write-back. See `slim-cmo-agent.md` §6.4, C13. |
| OP20 | **CEO as operating layer** *(2026-10-07, CP1)* | CEO is the seller's single conversational interface **and** a business operating layer, not a router: Business State, investigation management, cross-agent synthesis, decision support, executive answers; deterministic services plus two LLM seams (classify, compose), **no sub-agents**. It answers business questions no specialist owns from four labelled knowledge layers; **no quantitative claim ever comes from model knowledge**. Full detail: `ceo-agent-orchestration.md` §6.10, §6.16. |
| OP21 | **Bounded fan-out via deterministic playbooks** *(CP1-D1)* | One classification into a closed enum; one fixed plan (state read, one registered action, or one playbook's parallel independent legs); one composition. The LLM never chooses tools. The action registry is the only specialist access; **no write-class action is CEO-callable in V1**. `ceo-agent-orchestration.md` §6.11–§6.12, C3/C4/C21. |
| OP22 | **CEO data access and gating** *(CP1-D2/D3/D7/D8)* | Business State = fixed read catalog over persisted verified results, **no fresh computation**; CFO-class results need `agent.cfo` **and** CFO entitlement, with the gated preview on entitlement denial; investigations tenant-wide (`agent.ceo` + `investigation.view`), RLS-bounded; findings by reference; the summary holds no figures. §6.13–§6.15. |
| OP23 | **Proactive CEO and evaluation** *(CP1-D4/D5/D6)* | Proactive detection: post-ingest event-driven (V1-later), scheduled Redis worker V1.1; system runs consume no seller units. The classifier/composer eval harness is built before the conversational CEO is relied on; **no pass-bar values are set — a human decision.** §6.17–§6.18. |
| OP24 | **Goals and KPIs** *(2026-10-07, CP1 round 2)* | A structured goal registry owned by the CEO; **goal progress and deviation are a Brain 1 function** (`deterministic-engine.md` §5.16) — the CEO interprets and never subtracts. A goal is active only after explicit member confirmation. The CFO's `seller.goal` stays context only. `ceo-agent-orchestration.md` §6.20. |
| OP25 | **CEO Hub surface and agent attachment** *(CP1-U1/U2/U3, G4)* | The Agent canvas (readiness §1: availability only, no user-drawn edges) is realised as the CEO Hub: the seller attaches/detaches specialists per investigation; the CEO orchestrates **only attached** agents and answers from domain knowledge (labelled, no numbers) or says "add the agent" otherwise; attachment never grants access. Chat input at the bottom; agent responses on the right; health as bands and verified figures only — **no composite score, no projected uplift**. §6.22, §6.27. |
| OP26 | **CEO latency** *(CP1-L)* | Reduced by UI-initiated routes that skip the classifier, template-only pure reads, prefetch/cache, progressive delivery and sentence-gated streaming — **never** by skipping a permission, entitlement, provenance or composition gate. Every turn is stage-traced; no numeric target is set until a baseline is measured. §6.26. |
| OP27 | **Decision support, briefing, situations and follow-ups** *(CP1 round 2)* | Verified-option decision briefs with a labelled, conditional recommendation (§6.23); an on-demand executive briefing in V1 and proactive/scheduled briefings later (§6.24); deterministic detectors, situation lifecycle and a lexicographic Priority Engine (§6.21); follow-ups that re-read persisted state and a notification-sink interface (§6.25). |

**Leak Shield across the three brains** — CFO is the interpreting agent, not the calculator:

| Brain | Responsibility |
|---|---|
| Brain 1 (deterministic) | Reconciliation arithmetic, margin computation, variance detection against tolerance |
| Brain 2 (statistical) | Anomaly detection, outlier scoring, trend deviation |
| Brain 3 / CFO agent | Interpretation, explanation, recommended action, prioritisation **as judgement**. Deterministic ranking belongs to Brain 1 (amended above). |

---

## 2. Still-unresolved ambiguities

| # | Item | Class |
|---|---|---|
| 2.1 | ~~P&L formula and COGS input path~~ | **RESOLVED** — see `deterministic-engine.md` §1.1, §1.2 (template.v1) |
| 2.2 | ~~GST depth~~ | **RESOLVED** — management-grade; `deterministic-engine.md` §1.3, §8 |
| 2.3 | **Fee-schedule source** — **reclassified.** Historical margin uses fees actually charged in the reports, so this does *not* block the engine. Required only for forward-looking figures: pricing recommendations, feasibility checker, public calculator | **[P]** |
| 2.4 | ~~Tenant isolation mechanism~~ | **RESOLVED** — `auth.md` §1.4, §7.3: row-level `tenant_id` + Postgres RLS with `FORCE`, `SET LOCAL` context |
| 2.5 | ~~Repo layout~~ | **RESOLVED** — monorepo: `packages/calc-engine` (deterministic engine, Brain 1), `backend/` (FastAPI), `frontend/` (Next.js App Router). Enforced by the pre-commit hook at `.claude/hooks/pre-commit` (`core.hooksPath` must be set locally — see `docs/planning/mechanical-setup-log.md`). |
| 2.6 | ~~Agent topology~~ | **RESOLVED** — star confirmed; CEO brokers all agent-to-agent routing (§1 Agent architecture) |
| 2.7 | ~~Fast-path vs AI-path router mechanism~~ | **RESOLVED** — structural, not a runtime classifier (`ceo-agent-orchestration.md` C2/R2). *(Row was stale; reconciled 2026-10-07.)* |
| 2.8 | Expense and cash-flow input path — manual entry, statement upload, or settlement-derived only | **[P]** — **SUPERSEDED 2026-10-15 by EXP-01…EXP-08 (owner, `docs/decisions/phase1-decisions.md`), as applied to the expense input path** |
| 2.9 | "User can give the data" for forecasting — additional report upload, or manual numeric entry | **[P]** |
| 2.10 | Web search provider (Tavily / Brave / Serper) | **[P]** — *note 2026-10-03:* Tavily + YouTube are de facto wired in PI and become the Market Signal Retrieval service's sources (OP17). Formal closure of this item is the seller's/your call, not asserted here |
| 2.11 | Google Trends source — pytrends vs paid; now load-bearing for Market Outlook | **[P]** — *note 2026-10-03:* dropped from PI (PI C14), **not adopted in CMO V1**; CMO trend reports carry `demand_evidence = UNOBSERVED`. The "Market Outlook" named in §1 is the forecasting-gate fallback and is **not** a PI feature; it is unbuilt and untouched by OP17 |
| 2.12 | Alert channel for sellers who decline WhatsApp opt-in | **[P]** |
| 2.13 | Embedding model permanence — swapping it is a re-index migration, not config | **[P]** |
| 2.14 | ~~Competitor snapshot staleness~~ | **RESOLVED** — OP3: 7-day ceiling with age stamp |
| 2.15 | ~~Scrape-failure UX~~ | **RESOLVED** — OP3 |
| 2.16 | WhatsApp completion behaviour — send summary back, or silently update dashboard | **[P]** |
| 2.17 | ~~Session strategy~~ | **RESOLVED** — `auth.md` D1, D7: Clerk-issued JWT via JWKS, no Redis sessions; cookies hold UI state only |
| 2.18 | Developer split between the two of you | **[P]** |
| 2.19 | Deployment target — AWS / Railway / Render / Cloudflare, never chosen | **[P]** |
| 2.20 | Scale targets — sellers in first 3 months, orders/month per seller | **[P]** |
| 2.21 | Data retention and DPDP posture | **[P]** |
| 2.22 | Is the feasibility checker part of the deferred calculator site, or separate? | **[P]** |
| 2.23 | Language — English-only vs Hindi/Hinglish | **[D]** |
| 2.24 | Latency targets (p95) | **[D]** |
| 2.25 | Funding-readiness output definition | **[D]** |
| 2.26 | ~~CMO "other simple marketplace task"~~ | **RESOLVED 2026-10-03** — removed from V1; scope is the exhaustive list in `slim-cmo-agent.md` C3/§3 |
| 2.27 | ~~CMO vision input~~ | **RESOLVED** — OP8: seller-uploaded product photos only |
| 2.28 | **`VisionProvider` choice, eval bar and cost metering** — hosted vs local; a vision eval must pass before trust (CI Q18 evidence) | **[P]** — blocks image-informed CMO output |
| 2.29 | **Marketplace category taxonomy source** for authoritative category/vertical/required-attribute answers; V1 returns labelled estimates only | **[P]** |
| 2.30 | ~~GST access for CMO-only sellers~~ | **RESOLVED 2026-10-03** — Route B (CEO shared-lookup call) conditional on G1–G7 |
| 2.31 | **Seller-image retention/deletion and upload limits** (extends 2.21) | **[P]** |
| 2.32 | ~~Post-approval copy unit count~~ | **RESOLVED 2026-10-03** — one pack = 1 unit. Free-tier cap values remain 3.5 |
| 2.33 | ~~Shared-service extraction~~ | **APPROVED 2026-10-03 with a gate** — a written plan and PI regression tests must exist and pass before any PI code is touched |
| 2.34 | **Trend configuration values** (budgets, windows, corroboration thresholds, term caps) — none decided or seeded | **[P]** — blocks any trend report |
| 2.35 | **Provider capability probe** (Tavily/YouTube: news/recency mode, publication dates, channel id, quotas, India bias, terms of use) | **[P]** — build step P7-0; may change §6.8 |
| 2.36 | **Tactic policy-risk pattern set** — owner and initial content | **[P]** — safe fallback `UNASSESSED` applies meanwhile |
| 2.37 | **Verified marketplace format constraints and the max-age policy** (who verifies, from which official pages, how often) | **[B]** before any production generation |
| 2.38 | **Legal/ToS review of using search providers for seller trend research** (analogous to 3.1) | **[B]** before launch of `cmo.market_trends` |
| 2.39 | **Catalog-title read:** permission key (`files.view`?) and `item_title` availability per marketplace (Meesho observed identifiers: none) | **[P]** |

### 2A. Preserved for later specification (Phase 1 close)

Explicitly deferred, not forgotten. Each is specified before the feature that depends on it.

| # | Item | Depends on / blocks | Class |
|---|---|---|---|
| 2A.1 | **Proxy ranking model** replacing "total units sold" — marketplaces do not publish unit volumes | PI niche discovery | **[P]** |
| 2A.2 | **Estimated competitor margin range**, never a competitor margin figure — competitor COGS, fee tier and ad spend are unobservable | CI | **[P]** |
| 2A.3 | **Budget-constrained quantity estimate** for new products with no sales history | CFO batch size | **[P]** |
| 2A.4 | **Batched and cached Google Trends** with defined degraded state | PI, Market Outlook | **[P]** |
| 2A.5 | **Per-agent memory and shared memory model** — contents, boundaries, interaction with investigations and rolling summary, retention | Orchestration, memory spec | **[P]** | **Partially resolved 2026-10-07 (CEO CP1-D2):** conversation memory = Investigation + rolling summary; business memory = structured deterministic rows (`ceo_decision`/`ceo_open_issue`/`ceo_followup`), V1-later; per-agent memory remains each agent's own. Retention remains open (2.21).
| 2A.6 | **Structured niche + budget intake schema** | PI niche discovery | **[P]** |
| 2A.7 | **WhatsApp entitlement, investigation and cap behaviour** — do CEO caps apply on WhatsApp; does an inbound question open an Investigation; behaviour at cap mid-thread | WhatsApp channel | **[P]** |
| 2A.8 | ~~Marketplace catalog forms in V1 CMO~~ | **RESOLVED** — OP7: in V1 as catalog Q&A, not bulk catalog generation | — |
| 2A.9 | ~~Trusted-domain allowlist scope~~ | **RESOLVED** — OP2: three purpose-scoped allowlists | — |
| 2A.10 | ~~GST Lookup as shared service~~ | **RESOLVED** — OP7, OP9: shared service with its own cap | — |
| 2A.11 | ~~LLM computation access pattern~~ | **RESOLVED** — OP10: fixed tool catalog | — |
| 2A.12 | ~~Vision model requirement~~ | **RESOLVED** — OP11: external extraction to structured schema, behind a provider slot | — |
| 2A.13 | **Agent-initiated data request flow** (OP1) — how an agent declares missing data, how the seller is prompted, how the response is validated and stored as a manual input | Orchestration, manual inputs | **[P]** — **SUPERSEDED 2026-10-15 by EXP-01…EXP-08 (owner, `docs/decisions/phase1-decisions.md`), as applied to the expense input path** *Only the expense-input part; OP1 (the general agent-initiated data-request flow) stays locked.* |

### 2B. Carried-forward architectural constraints (from the planning document)

Restated at Phase 1 close so none is lost. Each is implemented in the spec named.

| # | Constraint | Specified in |
|---|---|---|
| 2B.1 | Scraping fails sometimes — serve prior snapshot or degrade gracefully; never fabricate | Competitor research pipeline |
| 2B.2 | Database failure plan — strong backup system | Infrastructure / operations |
| 2B.3 | Optimised LLM calls: simple calc → Python/SQL · aggregation → SQL · anomaly → statistical/ML · explanation → LLM | Orchestration + deterministic engine |
| 2B.4 | Marketplace fees change gradually — never hardcode rates; use current knowledge | Deterministic engine §4.1 (F4) |
| 2B.5 | Scrape only through trusted sources | Competitor research pipeline |
| 2B.6 | Handle incomplete or missing data before issuing any recommendation | Deterministic engine §4, §9 |
| 2B.7 | Latency reduction: parallel retrieval, hybrid fast/AI path, Redis caching | Orchestration + API contracts |
| 2B.8 | Large uploads: never feed 10k+ rows to an LLM. Extract structure first; Python/SQL summarises; LLM only structures the final answer | Ingestion + orchestration |
| 2B.9 | Three-brain strategy | Across all specs; roles fixed above |
| 2B.10 | RAG placement per planning doc — marketplace policies, seller documents, policy knowledge base | Knowledge base spec |
| 2B.11 | Agent connect / remove architecture | Entitlement spec |
| 2B.12 | Token limit architecture | Entitlement + metering spec |

---

## 3. Business decisions requiring explicit approval

| # | Item | Class |
|---|---|---|
| 3.1 | **Legal review of the scraping posture before launch** — IT Act §43/§66 exposure is India-specific | **[B]** before launch |
| 3.2 | **Amazon Associates account** — PA-API access depends on it and on maintaining qualifying sales | **[B]** before PI ships |
| 3.3 | Final pricing, tiers, and credit values | **[P]** — deferred by agreement |
| 3.4 | CFO gate behaviour — recommended: headline number + one revealed example + rest locked | **[P]** |
| 3.5 | Free-tier caps as real limits | **[P]** |
| 3.6 | Partner commission terms — recommended 20% for 12 months, not lifetime | **[P]** |
| 3.7 | Spin wheel frequency — recommended once per account | **[P]** |
| 3.8 | Payment provider and GSTIN for own invoicing (18% GST, B2B input credit) | **[P]** |
| 3.9 | Ollama: development-only, or production too | **[P]** |
| 3.10 | Sign-off on the marketing-promise removal list | **[P]** |
| 3.11 | Data retention and deletion policy | **[P]** |

---

## 4. Technical assumptions that can safely remain provisional

All of these are already designed to change without architectural rework.

- Every adapter column map (`is_verified = false` throughout)
- Declared date formats per marketplace
- Meesho `sss` — retained under its original name, unverified
- Combined vs separated invoice/settlement files
- Amazon fee decomposition; `Platform Fee` vs `Marketplace Fee Amount` relationship
- Return-status enum semantics per source
- Settlement lag and variance tolerances (configuration, never constants)
- Free-tier caps (per-plan configuration)
- LLM model selection (absorbed by the provider abstraction)
- Qdrant migration path if document RAG outgrows pgvector
- Streaming and memory thresholds pending real file sizes

**Why safe:** raw-file preservation plus versioned, re-runnable parse runs mean a wrong assumption is corrected by a re-run, not by re-onboarding sellers.

---

## 5. Conflicts between the original plan and current architecture

| Planning doc | Current architecture | Status |
|---|---|---|
| p.1 CEO is the *sole customer-facing interface* | CEO is sole **conversational** interface; fast path bypasses agents | Resolved |
| CEO as single-shot router (spec C3/C4, pre-CP1) | CEO is an operating layer with bounded fan-out via deterministic playbooks; still one classification and one composition per turn | **Resolved 2026-10-07** (OP20–OP23) |
| p.2 CI owns "True Margin engine" | Shared Brain 1 owns all math; CI computes nothing | Resolved |
| p.2 CI acts "by help of CMO" | Star topology forbids agent-to-agent calls | **RESOLVED** — CEO routes to CMO; CI never calls CMO (`competitor-intelligence-agent.md` §6.6) |
| p.3 WhatsApp invoke/revoke in V1.0 | 1/day opt-in prompt + alerts; limited two-way | Superseded |
| p.5 ML forecasting is V2.0 | Gated forecasting in V1 | Superseded, recorded |
| p.7 Qdrant in the V1 stack | pgvector | Superseded |
| p.9 "API fails → use 10–15 min old records" | Moot for seller data under upload-only | Superseded |
| p.9 "don't hardcode fees, use updated knowledge" | No fee source has been chosen | **Open — 2.3** |
| p.11 "10000+ cols & 15+ rows" | Read as inverted (~10k rows × ~15 cols) | Unconfirmed **[D]** |
| p.14 rolling summary vs p.15 fresh investigation | Investigations top-level, summarisation within | Resolved |
| p.16 "2 agents free" | Three free agents plus CEO | Superseded |
| **p.17 "CFO consume more token"** | CFO is mostly deterministic Python/SQL, so consumes the *fewest* LLM tokens | **RESOLVED** — technical half settled (`cfo-agent.md` §7.3.1); commercial half deliberately deferred to the entitlement, metering and billing spec (§7.3.3). No agent spec asserts a meter. |
| p.17 CMO paused by default | CMO is free | Superseded |
| OP7 "CMO calls the shared GST Lookup" | CEO routes CMO-context GST questions to CFO; CMO has no GST path | **Superseded 2026-10-03** (OP7 amended). Open consequence: 2.30 |
| PI "Market Outlook" assumed to exist as the trend source | No such PI feature; PI C14 reassigned trends to CMO; Market Outlook is the unbuilt forecasting fallback | **Resolved 2026-10-03** — shared retrieval service (OP17) |
| p.18 two free tools at launch | Both deferred to pre-deployment | Changed |
| Mockups: "Ecom OS" branding, "Connected" integrations, live/today copy, ₹4,999 Pro | Non-binding per `design_status.md`; contradicted by upload-only and the cart | Superseded |

**The one genuine contradiction remaining** is p.17's token ranking. It mattered little when it was a billing curiosity; it matters now because CFO is the paid agent. If CFO is the cheapest agent to run, the monetisation rationale needs to rest on **value delivered**, not compute consumed. That is a positioning decision, not a technical one.

---

## 6. Missing information that would block implementation

| # | Item | Blocks | Class |
|---|---|---|---|
| 6.1 | P&L formula and COGS source | The calculation spec, and therefore the core product | **[B]** |
| 6.2 | GST depth decision | Calculation spec; carries legal/accuracy consequence | **[B]** |
| 6.3 | Fee-schedule source | True Margin accuracy; the entire value proposition | **[B]** |
| 6.4 | **A real Amazon export to verify settlement match keys** (the report family is specified) | Amazon reconciliation and Leak Shield execution — a shipped V1 feature | **[B]** before launch |
| 6.5 | One real export per marketplace | Production ingestion (not spec writing) | **[B]** before production |
| 6.6 | Expense / cash-flow input path | Those two features only | **[P]** — **SUPERSEDED 2026-10-15 by EXP-01…EXP-08 (owner, `docs/decisions/phase1-decisions.md`), as applied to the expense input path** |
| 6.7 | Scale targets | Infrastructure sizing | **[P]** |
| 6.8 | Repo layout | First commit | **[P]** |

---

## 7. Recommended specification-writing order

Ordered by what unblocks the most downstream work.

| # | Specification | Prerequisites |
|---|---|---|
| 1 | **Calculation & P&L engine (Brain 1)** | 6.1, 6.2, 6.3 — **currently blocked** |
| 2 | Tenant, identity & account model | 2.4 |
| 3 | Entitlement, metering & billing seams | — (values provisional) |
| 4 | Agent orchestration & routing | 2.6, 2.7 |
| 5 | Investigations & memory | — |
| 6 | Competitor research pipeline | 2.14, 2.15 |
| 7 | Policy knowledge base | 2.13 |
| 8 | Statistical detection & forecasting gate | depends on 1 |
| 9 | WhatsApp channel | 2.12, 2.16 |
| 10 | API & dashboard contracts | depends on 1–5 |
| 11 | Growth mechanics (partner, spin wheel) | pricing model |

Specs 2 and 3 can be written immediately and in parallel with resolving spec 1's blockers.

---

## Verdict

# READY FOR PHASE 2

All three Phase 1 blockers are cleared.

| Blocker | Status |
|---|---|
| P&L formula + COGS path | **Resolved.** Structure confirmed; recorded as `formula_version = template.v1`, to be upgraded after CFO is built. COGS via weighted-average cost master (D3). |
| GST depth | **Resolved.** Management-grade decision support, plus GST Applicability Lookup as a structurally isolated research feature. |
| Fee-schedule source | **Resolved by reclassification.** Historical True Margin uses the fees actually charged in the reports (`line_component`); leak detection compares invoice side to settlement side. No external schedule is involved. A fee schedule is required only for *forward-looking* figures — pricing recommendations, feasibility checker, public calculator — so it blocks a later spec, not this one. |

Agent architecture, ownership boundaries, and research posture are confirmed final (§1).

### Outstanding, but never blocked specification work

| # | Item | Effect |
|---|---|---|
| 1 | ~~Real Amazon settlement report~~ **— amended.** The report family is **specified** (`amazon.settlement.v2`, `data-foundation.md` §0.6, §2.3). What remains is **settlement match-key verification against a real export**. Amazon reports `RECOGNISED` and withholds leak findings until that closes — pending validation, not categorically unsupported. |
| 2 | **Cancellation encoding** (C1) | R4 fully specified, inactive until real data shows the representation. |
| 3 | **RTO encoding** (C2) | R6 fully specified, inactive for the same reason. |
| 4 | **Real exports, all three marketplaces** | Every adapter mapping remains `is_verified = false`. |

### The one genuine contradiction still open

Planning doc p.17 ranks CFO as the heaviest token consumer. CFO is now also the Leak Shield interpreter — and Leak Shield is Brain 1 arithmetic plus Brain 2 statistics, with the LLM only explaining results. **CFO is therefore the most deterministic agent in the system and should consume the fewest LLM tokens, not the most.**

**Resolution (amended):** the *technical* half is settled — CFO is the most deterministic agent and its model cost is flat with respect to seller data volume (`cfo-agent.md` §7.3.1). The *commercial* half is deliberately **not** settled by any agent spec: `cfo-agent.md` §7.3.3 records it as input I1/I2 for the entitlement and billing specification, which owns the meter. No agent spec asserts a metering basis.

### Phase 2 order

Per §7. Specs 2 (tenant/identity) and 3 (entitlement/metering) have no open dependencies and may begin immediately.
