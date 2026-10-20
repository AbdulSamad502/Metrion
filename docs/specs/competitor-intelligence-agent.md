# Metrion — Competitor Intelligence Agent (CI) Specification

**Status:** Draft for review — **revised 2026-09-21 for CI V2 (Checkpoint 0).** The V2 revision is **additive**: it adds discovery, identity resolution, relevance scoring, customer-voice snippet retention, the two-layer alert model, the price-band formula and the generalized handoff contract (C21–C30, D8–D13, A6–A9, §5.4–§5.6, §6.10–§6.20). It changes **one** prior decision — the competitor-discovery non-goal, reversed on the record by **C21** — and leaves the evidence-upload pipeline (C2, C4, C16, the §5.1 confidence vocabulary, and the `competitor_snapshot`/`competitor_evidence`/insight data model) exactly as written.
**V3 revision — 2026-10-18 (CI Upgrade, Checkpoint 0).** Owner-approved upgrade of CI into a **CEO-only, evidence-based research and monitoring system**. **Additive again, with deliberate reversals, each recorded and none silent:** (1) the seller-facing evidence-upload dashboard surface and the seller-product-profile form are retired in favour of CEO Hub conversation (C32, C36, C31 amended); (2) Tavily is approved as the discovery provider, with the C22 provider record still to be completed (C34); (3) the §6.13.2 gate that auto-rejects every `NOT_A_MATCH` — which, as built, rejects every cross-brand competitor — is split into identity and relationship (C43, flagged Q20); (4) the dashboard's input forms are removed (C32). V3 adds C32–C47, D14–D18, A11–A14, §5.7, §6.21–§6.29, AC38–AC58, T74–T107, Q19–Q24 and V16–V18. **C1–C31 stand except where a V3 row names the row it amends.** The arithmetic boundary, the confidence vocabulary, the snapshot/evidence data model, C23 (discovery is not intelligence), C26 (Layer 1 only) and the Brain 1 boundary are unchanged.

**Prerequisites:** `deterministic-engine.md` (all margin math) · `data-foundation.md` (provenance, confidence) · `auth.md` (permissions) · `whatsapp-integration.md` (WhatsApp identity, invoke/revoke, and investigation-creation mechanics — CI decides none of this itself; §6.9 records only what that spec resolves)

**The arithmetic boundary (B8).** CI may compute **deltas over its own observed facts** — a price change between two snapshots it captured. CI may **never** compute anything financial: no margin, fee, profit, tax or cost figure. All of those originate in Brain 1. CI normalises observations into a provenance-tagged input object, passes it to Brain 1, and reads the result back unchanged. CI holds no financial formula.

**Boundary restated for V2 (unchanged in substance, two clarifications).** (a) Where a seller's own current price is in hand, **CI supplies `competitor_prices[]` as `DERIVED` inputs to the existing engine functions `compute_price_positioning` and `compute_repricing_scenario` (`deterministic-engine.md` §5.15)** and renders their `metric_result` output unchanged, citing the returned `engine_result_ref`. This spec **does not restate or reimplement** that arithmetic; §5.15 is the authority for it, including its `UNAVAILABLE` rules and its explicit non-margin-awareness. (b) The **price-band / outlier computation (§6.16.3)** is arithmetic over money values and therefore, under the project's hard rule, **does not belong in CI — RESOLVED and LOCKED (2026-09-21, D10/R17).** The quartile/IQR/fence/outlier arithmetic lives in `deterministic-engine.md` **§5.15.1 `compute_price_band`**. CI supplies the tenant's tracked competitor prices as `DERIVED` inputs — the identical pattern it already uses for `compute_price_positioning`/`compute_repricing_scenario` — and renders the returned `metric_result` rows unchanged, citing the returned `engine_result_ref`. **CI never computes a quartile, an IQR, a fence or an outlier flag.**

---

## 1. Confirmed decisions

| # | Decision |
|---|---|
| C1 | **Marketplaces:** Amazon, Flipkart and Meesho, all three at V1 (readiness §1, Product shape — Marketplaces). |
| C2 | **[AMENDED V3 — the seller submits through the CEO Hub chat, not a dashboard form: C32, C36.] Acquisition — REVISED (locked pivot): seller-submitted evidence, not fetching.** The seller uploads a screenshot of a competitor listing via Metrion's own web dashboard. A vision model extracts structured fields from it, with a **manual-entry fallback** for anything unclear or missing. Multiple screenshots may be submitted per research session and are **merged** (§5.3, §6.1). Metrion's backend **never fetches** a competitor URL, on demand or otherwise. No continuous crawling, no bulk discovery, no live monitoring, no scraping in any form. **See §1a** — WhatsApp evidence intake is a documented **future** channel, once a BSP is contracted; only dashboard upload ships in this pass. |
| C3 | **The upload-only rule applies to seller financial data; competitor data acquisition is now also seller-submitted, but through a distinct pipeline** (readiness §1, Product shape — Seller data source; `auth.md` T3–T5). Seller financials remain upload-only, parsed by marketplace-report adapters. **Competitor data is submitted by the seller as evidence** — a screenshot the seller captured, extracted by a vision model with manual-entry fallback — **never fetched by Metrion from a competitor URL, under any circumstance.** The two paths still never mix: financial uploads flow through report adapters into the canonical model; competitor evidence flows through vision extraction into `competitor_snapshot`. |
| C4 | **Trusted domains (OP2a) — repurposed as a labeling/format check, not a fetch gate.** Since Metrion never fetches a `competitor_url`, the allowlist can no longer gate network access — there is no network access to gate. It is retained as a **data-quality validation at intake**: a submitted `competitor_url`'s host must still match one of `amazon.in`, `flipkart.com`, `meesho.com`, or their official short-link domains `amzn.in`/`fkrt.co` (D7, resolved 2026-09-21), so `marketplace` can be derived from it reliably and the enum stays meaningful. URLs outside the allowlist are still refused at intake with a clear message — the refusal is now about labeling correctness, not about preventing a fetch, because no fetch is ever attempted either way. |
| C5 | **Facts, not expression.** No raw review text stored or reproduced beyond the bounded, transient processing scope (C14). No marketplace images rehosted — the one exception is the seller's own submitted evidence image (a reviews-tab or listing screenshot), governed by the same `competitor_evidence` retention policy as everything else in §6.8, not by this rule (§6.5). |
| C6 | **REVISED (resolves Q11): review output is derived insight only, sourced from a seller-submitted reviews-tab screenshot — the same `competitor_evidence` evidence mechanism as listing evidence (C2, §5.3), never a live fetch.** Output: sentiment split, complaint themes, positive themes, rating distribution, summarised patterns. `competitor_review_insight.source_url` references the competitor listing this evidence is about, not a URL Metrion visited. Provenance and a capture timestamp (of the seller's upload, not a fetch) on every insight. See §6.5. |
| C7 | **No live review monitoring.** Review insight is produced only when the seller submits reviews-tab evidence for extraction (`EVIDENCE_UPLOAD`, §6.1/§6.4/§6.5) — there is no scheduled or on-demand fetch of any kind. |
| C8 | **Scrape-failure fallback (OP3):** serve the cached snapshot with a visible age stamp up to **7 days**; beyond that report unavailable. Never fabricate. |
| C9 | **Margin ownership:** Brain 1 is the single source of truth. CI supplies **observed price, visible discounts, and source metadata only** — never fees or rates, which Brain 1 resolves from its own reference store (C18). CI holds no financial formula. CFO interprets. |
| C10 | **Estimated margin range, never competitor margin** (2A.2). Competitor COGS, fee tier and ad spend are unobservable. |
| C11 | **Star topology.** CI is reachable only through CEO. No agent-to-agent edges. CI may call Brain 1 directly as a shared service. |
| C12 | **No supplier responsibility.** PI discovers suppliers; CFO ranks them from seller quotes. |
| C13 | **Entitlement:** CI free is limited (3 saved URLs, 5 runs/month); complete CI is a paid cart item (25 URLs, 100 runs/month). Values are provisional config. |
| C14 | **REVISED for the evidence model — still holds, refined for what "transient" now scopes.** The reviews-tab **screenshot itself** (`competitor_evidence.image_ref`) is stored and retained under the standard evidence-image policy (§6.8) — same as any other evidence upload, not treated specially or purged early. What remains **transient and local-only** is the **review text the derivation process reads off that screenshot** — individual review bodies, quotes, anything more granular than the derived aggregate: held in memory solely to derive insight; **never persisted** to any surface in the canonical list (§6.5) and **never sent to a hosted model provider**. No review-text corpus. No full reviews or long quotations in user-facing output. |
| C15 | **Local-only derivation (B4).** Review and listing derivation runs in-process or through local models (e.g. local Ollama) operating on the seller-submitted screenshot. Raw review text extracted from that screenshot never crosses the process boundary to a third-party provider. Where local processing is unavailable, CI returns a **degraded result from structured metadata** rather than sending the screenshot's extracted text out. |
| C16 | **Competitor listing copy is expression, not fact (M5) — narrowed by a genuine re-decision, not just a scope note.** Full titles, descriptions, bullets or listing text **scraped or copied from a live page** remain forbidden to persist — though there is no more scraping under this model, so that prohibition is now moot in its original form (nothing is ever copied from a live page). **New carve-out:** text and images the seller **affirmatively submits as their own evidence** — captured in a screenshot they chose to take and upload — may be persisted as structured fields (title, description, bullet text) via vision extraction or manual entry, on the same terms as price, rating and availability. This is the seller's own submitted record of what they observed, not Metrion copying expression off a page it visited. §6.6 is updated accordingly. |
| C17 | **Brain 1 owns all financial arithmetic (B1).** CI normalises evidence-derived observations into a structured, provenance-tagged input object and passes it to Brain 1. Where Brain 1 needs a new interface to accept observed competitor inputs, **Brain 1 is extended** — never CI. Output is always an *estimated margin range*, never a competitor margin. **See §1a — this feature is deferred pending a `deterministic-engine.md` extension spec.** |
| C18 | **Fee references are backend-managed configuration (B9).** Versioned, effective-dated, source-attributed reference data consumed by Brain 1. CI never holds rates. |
| C19 | **Retention (B6):** competitor snapshots are **not** retained indefinitely. Configurable policy, initially **90 days** (§6.8). Retention must never imply continuous monitoring — CI is on-demand only. |
| C20 | **[AMENDED V3 — the dashboard is no longer a seller input surface; evidence enters via the CEO Hub as a fixed CEO tool dispatch: C32, C36, §6.4.]** **Direct CI execution (B7).** A dashboard **evidence-upload** CI run (trigger `EVIDENCE_UPLOAD`, §6.4, §5) is a **direct CI execution path**, not a CEO conversational route, and does not consume a CEO call. It enforces the full check set in §6.4. **See §1a — only this direct path ships in the next implementation pass.** |

### V2 additions (C21–C31) — Checkpoint-0 review, 2026-09-21

C21–C30 come from the externally-reviewed **CI V2 Master Specification** (five review rounds) accepted at this Checkpoint-0 spec review. They are **additive**: none of them alters C2, C4, C5, C14, C15, C16 or the evidence-upload pipeline, the confidence vocabulary, or the `competitor_snapshot`/`competitor_evidence`/insight data model, all of which stand exactly as written above. **C31 is later (2026-09-21, same review cycle): it records the resolution of D8/Q12 after the decisions were made by the user, and is additive on the same terms.**

| # | Decision |
|---|---|
| C21 | **Competitor discovery — DECISION REVERSAL (locked).** The V1 non-goal *"competitor discovery (CI never finds competitors, the seller supplies them)"* is **superseded**. CI now generates research queries from the seller's own product and surfaces **candidate** competitors for seller review. This is a real reversal of a locked non-goal, recorded here in the same way C2 recorded the scraping→evidence pivot and D7 recorded the short-link resolution — **not** a silent edit. **Reason:** the Checkpoint-0 review (2026-09-21) accepted the V2 Master Specification's finding that manual-URL-only entry makes CI a screenshot-processing utility rather than a competitive-intelligence product. **Two hard limits ride with the reversal, and neither is negotiable:** (a) discovery finds *candidates only* and never populates competitive intelligence (C23); (b) **manual URL entry remains a permanent, always-available path**, independent of discovery, and is never removed or deprecated. §4's non-goal list is amended accordingly. |
| C22 | **[PARTLY RESOLVED V3 — Tavily approved by the owner 2026-10-18; the §6.10.1 provider record is still to be completed: C34.]** **Search acquisition is contract-first, and no provider is named in this spec.** Discovery uses a **licensed search provider**, never scraping, never a marketplace fetch (C2 is untouched: search results are *leads*, never live marketplace facts). **No named provider may be selected or integrated by an implementation agent on its own initiative.** Implementation builds, in order: domain models → a `SearchProvider` interface → a `MockSearchProvider` returning fixture data → the discovery pipeline against that interface. Only after a **provider record** (§6.10.1 — allowed use, data retention, redistribution/display rights, attribution, region, query limits, cost) is completed for at least two candidates and **explicitly approved by a human** may a real adapter be written behind the interface. Selecting a provider is a legal/commercial decision, not an engineering one. **See §1a item 6 — deferred.** |
| C23 | **Discovery is not intelligence (the load-bearing V2 rule).** Search discovery finds candidates; it does **not** populate live competitor intelligence. **Every field used in comparison (§6.19), customer-voice mining (§6.18.2) or alerting (§6.17) must trace to an evidence-bearing source — a seller screenshot or a licensed data provider — never to a search snippet alone.** A candidate that has passed discovery, identity resolution and relevance scoring is still an *unevidenced candidate*: it is shown as **"Approved — awaiting evidence"**, a distinct and visible state, and is **never silently compared, mined or alerted on as if evidence existed.** The acquisition matrix in §6.10.2 is the field-by-field statement of this rule. |
| C24 | **Product/entity identity resolution is a distinct, required pipeline stage.** A candidate is not assumed to be the competitor's actual product. Identity resolution extracts brand, model/variant, pack size and bundle status and compares them against the seller's own product record, emitting an explicit `EXACT_MATCH` / `LIKELY_VARIANT` / `UNCERTAIN` / `NOT_A_MATCH` field — never a silent assumption of exactness. Gating per §6.13.2. The entity model separates **Brand · Seller · Product · Listing · Competitor** (§6.13.3). |
| C25 | **Relevance scoring uses the locked eight-axis algorithm in §6.14 — implemented exactly, not reinvented.** Eight axes scored 0/1/2, summed to a max of 16, banded `HIGH`/`MEDIUM`/`LOW`. Every `UNKNOWN` or `CONFLICTED` axis scores **0** and is never guessed upward, including the seller-side-unknown case. A band is **never rendered without its per-axis breakdown**. **Relevance, identity-match confidence, evidence confidence and freshness are four separate attributes and are never collapsed into one number or badge** (§6.14.5). A score computed before evidence exists is labelled **"Discovery relevance (provisional)"** (§6.14.0). This is a first-pass rule set, tunable post-launch with real seller feedback, but implementation builds *this* scheme. |
| C26 | **Two-layer alert model.** **Layer 1 (CI, observational only):** *"Competitor X dropped price 8% (₹999 → ₹919)."* CI computes and states nothing about margin, contribution or break-even. **Layer 2 (CEO-composed fusion):** the CEO orchestrator receives the CI alert, requests margin/contribution impact from CFO, and delivers the combined alert. **CI produces Layer 1 only**, and only for evidenced candidates (C23). The fused alert is never something CI computes internally — this is the structural enforcement of C9/C17/AC1. **Layer 2 is DEFERRED — see §1a item 8:** no CFO agent implementation exists in this codebase (CEO Hub reports CFO as `NOT_CONNECTED`). |
| C27 | **Customer-voice mining retains evidence-snippet references under one rule, not two.** Themes are reported with stated frequency (*"this theme appeared in N of M sampled reviews"*, never "some people complained"). A theme's supporting **evidence-snippet reference** — the cited one-to-two-sentence extract, its theme, the source competitor/listing reference, and the extraction date — is retained for a **configurable default of 90 days from extraction**, tenant-aware, extendable per competitor by a seller or Metrion admin for a named reason, and **never exceeding any retention ceiling imposed by a source or licensed provider's terms**. On expiry the **aggregate theme remains visible** but is marked **"source evidence expired"** — not deleted, not silently kept traceable forever. This mechanism never retains the raw screenshot image (that follows §6.8's own policy) nor full review text beyond the cited snippet. **This narrows C14, it does not contradict it:** C14 forbids a review-text *corpus* and any granular body beyond the derived aggregate; C27 permits exactly one bounded, auditable exception — the specific snippet a theme cites — under an explicit expiry. Where C14 and C27 appear to disagree, **C27 governs the cited snippet only** and C14 governs everything else. |
| C28 | **Generalized `Evidence` / `CIHandoff` contract, routed `CI → CEO` only.** Every finding type (price, availability, listing content, review theme, differentiation, market position) traces through one common `Evidence` record carrying a `source_type` discriminator — `SELLER_SCREENSHOT | LICENSED_PROVIDER | REVIEW_SNIPPET` — of which the C27 snippet reference is one subtype. Schema in §5.6. **Routing is `CI → CEO`, never `CI → CFO` or `CI → CMO` directly** — this is C11 restated, not a new rule, and must not regress. A `CIHandoff` payload is **never shown to the seller as-is**: it is always composed into a Competitive Brief (§6.20.2) or a CEO-orchestrated cross-agent alert first. |
| C29 | **Market trend signals are DEFERRED, explicitly.** Any trend claim must state geography, time window, comparison baseline, search term(s), source and data freshness — a bare *"demand is rising"* is meaningless and is never emitted. The common `pytrends` route scrapes Google Trends' public frontend: **the same acquisition-risk shape as marketplace scraping, aimed at a different target**, and therefore forbidden under C2's reasoning. Trend research waits for a licensed/approved acquisition method. **This deferral does not block discovery (C21–C22), which has its own separately-resolved licensed search path.** See §1a item 7. |
| C30 | **`SellerProduct` is a read-only baseline contract with explicit `KNOWN`/`UNKNOWN` per field.** Every seller-side value the relevance and comparison logic reads comes from this one structure (§5.5), sourced from Metrion's existing seller data. **Any field Metrion does not capture for a given seller is `UNKNOWN` — never inferred from other fields, never backfilled with an implementer's guess, never silently defaulted.** CI never writes to it. A seller-side `UNKNOWN` propagates as an `UNKNOWN` comparison scoring 0 (§6.14, C25) rather than producing an invented baseline. **See D8 (RESOLVED) and C31 — the fields with no `sales_line` source are populated by a seller-maintained product profile, which is a second legitimate *source*, not a relaxation of this rule.** |
| C31 | **[AMENDED V3 — the *form* is superseded by CEO conversation (C32, §6.21.4); the `SellerProduct` contract, sources and precedence below are unchanged.]** **NEW — RESOLVED D8/Q12 (LOCKED, 2026-09-21). A minimal, one-time-but-editable manual seller-product form is built, and its values are stored as explicit `SellerProduct` field overrides.** Metrion ships a **seller-product-profile form — new UI and new API surface, not merely a backend view** — capturing **category, attributes (key/value pairs), keywords, current listing price (signed BIGINT paise), and fulfillment type** for the seller's own product. **This does not weaken C30's discipline in any way:** every field remains exactly `KNOWN` (the seller entered it) or `UNKNOWN` (nobody entered it) — nothing is inferred, defaulted, backfilled or derived from another field, and an unfilled form field stays `UNKNOWN` and scores 0. What C31 adds is a **second legitimate source** for populating a field, alongside the `sales_line`-derived one — `field_source` is `SELLER_ENTERED` or `CANONICAL_DERIVED` (§5.5; note this is a *source* marker, distinct from §5.1's `DERIVED` confidence value and never conflated with it). **Precedence when both exist and disagree: the seller-entered value wins**, explicitly mirroring the established competitor-side precedent — §5.3 rule 4, implemented in `packages/competitor-intelligence/.../evidence/merge.py::apply_manual_overrides`, where a `SELLER_ENTERED` value always supersedes a `VISION_EXTRACTED` one. Same pattern, seller side. Every field records which source produced it, and the override is editable at any time, never write-once. CI still **never writes** to `SellerProduct`; the profile form is a seller-facing surface, not a CI surface. Model in §5.5; scope of what the form does *not* cover in V12. |

### V3 additions (C32–C47) — CI Upgrade, Checkpoint 0, 2026-10-18

Decided by the owner in the CI Upgrade brief and its four corrections (2026-10-18). **C32–C47 amend only the rows they name.** The Brain 1 boundary (C9, C17, AC1), C23, C26 and the §5.1 confidence vocabulary are untouched.

| # | Decision |
|---|---|
| C32 | **CEO is the only seller-facing conversational surface; CI has no chatbot, and the CI dashboard is a read-only visual workspace.** The seller asks, uploads and confirms **only through the CEO Hub** (dashboard and, later, WhatsApp share one CEO–CI backend workflow). The CI dashboard **shows** findings, evidence and history that CEO–CI investigations produced; it contains **no manual form and no data-entry input** (no URL form, no evidence upload, no manual-entry form, no seller-product-profile form, no threshold form). **Amends C20/R3:** a seller screenshot no longer enters through a dashboard "direct execution" button; it enters through the CEO Hub (C36), and CI's validation→extraction→store pipeline is invoked by a **fixed CEO tool dispatch**, never by an LLM choosing code (C11 unchanged). **Amends C31:** the seller-product-profile *form* is superseded by CEO conversation (§6.21.4); the `SellerProduct` contract, `KNOWN`/`UNKNOWN` discipline, `SELLER_ENTERED` precedence and its table are unchanged. **Amends the manual-entry fallback (C2):** a seller-stated value (`SELLER_ENTERED`) is still how a gap is filled, but it is collected conversationally by the CEO (C38), never by a dashboard form. |
| C33 | **Dashboard shortcuts are CEO Hub entry points, not CI controls.** The CI dashboard keeps exactly two top-level shortcuts — **Research Competitors** and **See / Monitor Competitors** — plus contextual **Ask CEO** buttons on individual findings, competitors and candidates. Each opens the CEO Hub carrying a **structured, server-validated context reference** (the selected SKU's `product_id`, the intent, and for Ask CEO the `finding_id`), pre-composing a visible message the seller sends (D14). A shortcut **never** calls a CI run endpoint, never runs anything itself, never collects input, and never carries a client-supplied `tenant_id`. §6.21.2. |
| C34 | **Tavily is approved as CI's discovery provider (resolves C22's human-approval gate for provider selection; owner decision 2026-10-18).** Discovery acquires **leads via the Tavily search API only — no scraping of any marketplace or search frontend** (C2 untouched). The adapter is written behind the existing `SearchProvider` interface, reuses the existing backend Tavily configuration, enforces the C4/D7 marketplace-host allowlist on every returned URL, and sits under the §6.11 query-privacy boundary and §6.12 budgets unchanged. **What the approval does not do:** it does not waive the §6.10.1 provider record, which must still be completed for Tavily in CP1 (allowed use, retention, display/redistribution, attribution, region, limits, cost); and **Tavily's terms and cost at CI volume remain pre-launch validation V11/V16**, not assumed. The two-provider comparison C22 required is waived by the owner for V3; the interface keeps a second provider swappable. §6.28. |
| C35 | **A Tavily result is a lead, never a verified observation — restated as an enforceable rule.** No price, stock status, rating, review count or other value read from a Tavily title/snippet is ever written to `competitor_snapshot`/`competitor_snapshot_field`, used as a `competitor_prices[]` input to Brain 1, used for a delta, price band, comparison, review theme, Layer 1 alert or `CIHandoff` `validated_fact`, or given an `Evidence` record of `source_type = SELLER_SCREENSHOT`. Such a value may be **displayed** only on a discovery candidate, labelled **"reported by search — unverified"**. **During monitoring, Tavily may refresh discovery leads (new candidates; whether a candidate still surfaces) and nothing else** (C40). §6.28.3. |
| C36 | **Image evidence enters through the CEO Hub chat attachment; WhatsApp is a placeholder only.** The seller attaches a competitor listing screenshot or a reviews-tab screenshot in the CEO Hub chat. A new trigger `CEO_HUB_UPLOAD` (§6.4) is recorded on the run. **Quality validation → duplicate detection → vision extraction → product matching → confirmation where required (C37) → evidence storage** is one fixed pipeline (§6.22). WhatsApp is declared as `EvidenceIntakeChannel = WHATSAPP`, a **placeholder**: the channel value and interface exist so both channels share one workflow, but it accepts nothing and returns a named `CHANNEL_NOT_AVAILABLE` until `whatsapp-integration.md`'s BSP exists (§1a item 3 stands). **No WhatsApp media-ingestion behaviour is specified or built here.** |
| C37 | **Seller confirmation is risk-based — by evidence confidence and by consequence, never blanket and never absent where it matters.** A field is **consequential** if its value, once stored, would (a) feed Brain 1 (`competitor_prices[]` → price band, positioning, scenarios), (b) create or suppress a price/stock delta or alert, or (c) assert product identity as `EXACT_MATCH`. A **consequential** vision-extracted field is **confirmed by the seller before it becomes a verified observation** (conservative while Q18 stands: measured vision price accuracy 13/31 and the extractor emits no ambiguity flag). A **non-consequential** field extracted at `HIGH` confidence is stored as extracted, shown in the CEO's summary and correctable at any time without a prompt. A **non-consequential** field at `MEDIUM`/`LOW`/missing is stored with its confidence or left `UNKNOWN` and is **not** asked about unless the seller asks. A field the seller declines to confirm stays `UNKNOWN` and **never** enters a consequential path. Full matrix: §6.23. |
| C38 | **Missing or uncertain information travels CI → CEO → seller → CEO → CI; CI never addresses the seller.** CI returns a structured **`InfoRequest`** (field, reason, evidence reference, allowed answer forms) to the CEO; the CEO phrases the question in chat; the seller's answer returns through a fixed CEO tool (`ci.confirm_field`) and is stored `SELLER_CONFIRMED`/`SELLER_ENTERED` with provenance. CI invents nothing to fill a gap (C23, §6.18). §6.23.3. |
| C39 | **Competitor management is CEO-conversational and fully audited: approve, reject, add, remove.** The seller says it in chat; the CEO executes a **fixed** CI action. **Approve** = the C21/§6.15 accept (candidate → tracked competitor). **Reject** = decision stored with reason; a rejected candidate is not re-surfaced by later discovery unless the seller asks. **Add** = a marketplace URL the seller states in chat (C4/D7 allowlist and entitlement cap apply) or a named candidate. **Remove** = **soft removal** (`REMOVED`): excluded from comparison, monitoring and alerts; history and evidence retained under §6.8; restorable by re-adding. Bulk requests ("track these three") are echoed for the seller's confirmation before the write. Every action writes an audit event (C47); every row is tenant-scoped with RLS `FORCE`. §6.24. |
| C40 | **"Monitoring" means *re-evaluation of stored evidence*, never watching.** A monitor request re-evaluates, from data already held: per-competitor **freshness**, **verified snapshot-to-snapshot deltas**, **review findings** and open alerts, and returns a **Monitoring Report stamped with its as-of time and each competitor's evidence date**. CI makes **no competitor fetch, no scheduled scrape and no continuous-monitoring claim** — the CEO says "as of <evidence date>", never "live", "tracking in real time" or "continuously monitored". Where evidence is stale or absent the CEO **asks the seller for a fresh screenshot** (CEO Hub; WhatsApp placeholder). A scheduled *internal* job that only re-reads stored data to compute freshness and reminders is permitted and is not monitoring of competitors (D16). Tavily may refresh **discovery leads only** (C35). §6.25. |
| C41 | **Freshness is source-specific.** D6/D9 are unchanged for seller-screenshot price/availability (24h `is_stale`, 7-day hard ceiling) and §6.16.2's other per-field thresholds. **Adds:** a seller-confirmed or seller-entered field **inherits the age of the evidence it confirms, not the confirmation time**; a Tavily lead signal has **no freshness tier — it is always unverified** and never "fresh"; a review finding's freshness follows §6.16.2's 30 days. A stale or unconfirmed fact **never fires a confirmed alert** (AC27 unchanged). §6.25.3. |
| C42 | **Alerts gain configurability, deduplication, quiet hours and freshness reminders — Layer 1 only (C26 unchanged).** Thresholds stay configurable per tenant and per competitor (D2, R9). **Deduplication** (§6.26.1): one alert per `(competitor, finding type, direction, evidence pair)`; a repeat fires only on a new valid snapshot whose delta against the **last alerted value** again meets the threshold. **Quiet hours** (§6.26.2): a tenant window with a timezone in which alerts are **held, not dropped**, and delivered when it ends; no default window. **Freshness reminders** (`staleness_reminder_days`) are delivered through the CEO. Channels this pass: CEO Hub and dashboard; WhatsApp placeholder. |
| C43 | **Product identity and competitive relationship are separate, and the §6.13.2 gate is split accordingly (REVERSES part of a locked rule — D17, Q20).** *Identity* (`identity_match`, C24, **values unchanged**) answers *"is this the same sellable product as mine?"*. *Relationship* (`relationship_class`, new, §6.27.1) answers *"how does this product compete with mine?"* — `SAME_PRODUCT · VARIANT · DIRECT_COMPETITOR · FUNCTIONAL_ALTERNATIVE · UNRELATED · UNKNOWN`. **Defect this fixes (verified 2026-10-18 against `identity_resolution.py`):** `resolve_identity` returns `NOT_A_MATCH` for any different brand and §6.13.2 gates `NOT_A_MATCH` to `REJECTED`, so **every other-brand competitor is auto-rejected before relevance scoring** — the opposite of what discovery exists to find. **Fix:** `EXACT_MATCH` and `LIKELY_VARIANT` gate exactly as before; `NOT_A_MATCH` **proceeds to relevance scoring** and is rejected only if the relationship resolves to `UNRELATED`; `UNCERTAIN` stays blocked for seller review (now asked conversationally, C38). Unknown is never guessed upward (C25). Relevance, identity, relationship, evidence confidence and freshness are **five separate attributes**, never collapsed (extends C25's four). |
| C44 | **Comparison extends to delivery, fulfillment, offers and effective price — with `UNKNOWN` kept visible.** §6.19 adds: delivery charge, fulfillment type, ratings and review counts, and **visible offers/coupons/temporary deals** as observed fields from seller evidence. **Effective price** continues to mean `listed − visible discount` (existing `effective_price`), an observed-fact subtraction under B8, **never** a margin-aware figure; an offer that needs a buyer-side condition (bank offer, first order) is recorded as an **offer with its condition**, not silently subtracted. Every unobserved value renders `UNKNOWN` with a reason, never blank or zero. §6.27.3. |
| C45 | **Every important CI recommendation carries traceable evidence, and review analysis keeps its sample size.** A finding resolves to its `Evidence` records and states *N of M sampled*, evidence date, confidence and seller-confirmation state (§6.20, C27, extended by §6.29.2). Review analysis uses **only legitimately available evidence** — a seller-submitted reviews-tab screenshot (C6) — and never states a population statistic from a screenshot's sample. |
| C46 | **Stable `finding_id` and the Ask-CEO contract.** Every CI finding the dashboard shows has a stable tenant-scoped `finding_id` (§5.7). **Ask CEO** passes that id; the CEO **re-reads the finding and its evidence server-side from the id** (never trusting client-supplied finding content) and continues the investigation. Findings created during CEO conversations appear on the dashboard with no seller action. A `finding_id` outside the tenant resolves `404`. §6.29.1. |
| C47 | **CI events are structured, append-only and auditable (resolves Q9 and Q16 for CI's scope).** Event types, at minimum: `EVIDENCE_RECEIVED`, `EVIDENCE_REJECTED_QUALITY`, `EVIDENCE_DUPLICATE`, `FIELD_CONFIRMATION_REQUESTED`, `FIELD_CONFIRMED`, `FIELD_CONFIRMATION_DECLINED`, `COMPETITOR_APPROVED`, `COMPETITOR_REJECTED`, `COMPETITOR_ADDED`, `COMPETITOR_REMOVED`, `DISCOVERY_RUN_STARTED`, `DISCOVERY_RUN_COMPLETED`, `DISCOVERY_RUN_FAILED`, `QUERY_DISPATCHED`, `PRIVACY_FILTER_DROP`, `FINDING_CREATED`, `ALERT_RAISED`, `ALERT_SUPPRESSED_DEDUP`, `ALERT_HELD_QUIET_HOURS`, `MONITOR_RUN`, `CEO_INVESTIGATION_LINKED`. Each records `tenant_id`, actor (`member_id` or `SYSTEM`), timestamp, the CEO investigation/`agent_run` link where one exists, and object ids — **never raw review text or snippets** (§7 rules 8, 14). The dashboard's Evidence and Changes history is read from these events. §5.7, §6.29.3. |

---

## 1a. Deferred for this implementation pass

This section is a scope/status annotation, not a re-decision. It defers no confirmed decision, design decision, assumption or open question below — it records which already-decided pieces of this spec are not being built in the next pass, and why.

1. **WhatsApp-confirmed trigger and CEO-routed conversational invocation are DEFERRED, pending CEO agent implementation.** Neither the CEO orchestrator nor the CFO agent has any implementation code yet (only DB migrations for `agent_run`/`investigation` exist, in `backend/migrations/versions/20260917_0002_orchestration_tables.py`); building CI's conversational/WhatsApp path now would mean coding against a mocked/guessed CEO routing contract, which risks rework once CEO's real classifier/routing shape is actually designed. Only CI's own **direct execution path** (C20 — the fast path that bypasses CEO/the LLM entirely) will be implemented in the next pass. *Update 2026-10-07 (CEO CP1):* the CEO design is now specified (`ceo-agent-orchestration.md` §6.10–§6.15) — conversational CI access is the registry entries `ci.research_now`, `ci.discover_competitors`, `ci.request_price_scenario` plus Business State reads of CI's persisted data; `CEO_REQUEST` is an existing trigger enum value awaiting that surface. **WhatsApp-confirmed invocation remains deferred (no BSP — `whatsapp-integration.md`).**
2. **The estimated-margin-range feature (C17 / §5.2 "Interface to Brain 1" / §6.7 "Estimated margin range") is DEFERRED, pending a Brain-1 extension spec.** This feature depends on an `estimate_ref` type/family, a `CompetitorObservationSet` input struct, and a Brain-1 function to accept competitor observations and return an estimated margin range — none of which exist anywhere in `packages/calc-engine` (verified by grep: zero matches for `estimate_ref`, `competitor_estimate`, `CompetitorObservationSet`, `margin_curve`). This spec already states correctly that "Brain 1 is extended — never CI" when it needs this interface (C17); that extension is an architecture-level decision affecting the deterministic engine and must go through its own spec update to `deterministic-engine.md` before CI implements anything that calls it. **This deferral is unaffected by the acquisition-model pivot (C2–C4, C16) recorded elsewhere in this spec: the pivot changes how CI acquires observations, not whether the estimated-margin-range feature is in scope. It remains deferred for the same reason as before — the Brain-1 interface still does not exist.**
3. **WhatsApp evidence intake is DEFERRED, pending a contracted BSP.** C2 documents "seller-submitted evidence" as the acquisition model, built in this pass as dashboard screenshot upload only. Submitting evidence via WhatsApp (e.g. forwarding a screenshot to the tenant's bound WhatsApp number) is a plausible future intake channel once `whatsapp-integration.md`'s BSP integration exists, but no BSP is contracted yet and no WhatsApp media-ingestion contract is specified anywhere. Building it now would mean coding against a channel that does not exist. Only the dashboard upload path (`EVIDENCE_UPLOAD`, §6.1, §6.4) ships in the next pass.
4. **The real vision-extraction model is DEFERRED, pending model choice and quality validation.** This spec specifies the *interface* a vision-extraction step must satisfy (§5.3, §6.1) — structured fields in, confidence and source per field out, manual-entry fallback on failure — but does not select a concrete model or provider. This connects directly to the existing 🔴-flagged **Q7** (local derivation model choice and quality): whatever is chosen must satisfy the same local-processing constraints already established for review/listing derivation (C14, C15) if it is to avoid sending a seller's screenshot to a hosted provider, and its extraction quality on real competitor listing screenshots is unproven. Until a model is chosen and validated, `extraction_status` on `competitor_evidence` (§5) may legitimately sit at `PENDING`/`EXTRACTION_FAILED` more often than the product experience wants, with manual entry as the working fallback.
5. **The estimated-margin-range feature (C17) remains deferred as stated in item 2 above, and is explicitly unaffected by this acquisition-model pivot.** Listed again here only so a reader scanning "what changed with the pivot" does not mistake its deferred status for something newly introduced by C2–C4/C16 — it was already deferred before the pivot and stays deferred after it, for the original Brain-1-interface reason, not a pivot-related one.
6. **NEW (V2). Real search-provider selection and any provider-specific adapter are DEFERRED, pending a legal/commercial provider-record decision.** Per C22, the provider record in §6.10.1 must be completed for at least two candidate providers and **approved by a human outside the implementation agent's authority** before a named provider is chosen or wired in. What ships without that approval: the `SearchProvider` interface, a `MockSearchProvider` returning fixture data, and the **entire discovery pipeline built and tested end-to-end against the mock**. Those are *not* blocked on the provider decision and must not be held up waiting for it. What is blocked: any provider-specific request/response handling, any integration test against a live provider, and any production discovery run. An implementation agent reading "implementation-ready" as permission to pick a provider (e.g. by name, by reputation, or by "clean ToS") is **out of scope by decision**, not by omission.
7. **NEW (V2). Market trend signals / trend research are DEFERRED, pending a licensed or approved acquisition method (C29).** The `pytrends` route is scraping with a different target and is refused on C2's own reasoning. No trend claim is emitted at all until this is resolved — a partially-sourced trend claim is worse than none, per the same OP3 logic that governs stale evidence (D6). **This deferral is scoped tightly and does not block discovery (C21/C22), price bands (§6.16.3) or anything else in §6.10–§6.19.**
8. **NEW (V2). Layer 2 fused, financially-aware alerts (C26) are DEFERRED, pending a real CFO agent.** Layer 2 requires the CEO orchestrator to request a margin/contribution figure from CFO and compose it with CI's observation. **Verified against the codebase at this review: no CFO agent implementation exists** — CEO Hub reports CFO as `NOT_CONNECTED`, and only the `agent_run`/`investigation` migrations exist (same gap already recorded in item 1 above). Building Layer 2 now would mean coding against a guessed CFO response contract and, worse, would create pressure to approximate a margin figure inside CI — the exact failure C26 exists to prevent. **Layer 1 (CI, observational only) is real, unblocked and ships in this pass.** When a CFO agent exists, Layer 2 is composed by CEO; nothing in CI changes to enable it beyond emitting the `CIHandoff` payload it already emits (C28). *Update 2026-10-07: the stated blocker is stale — a real CFO agent now exists (11 `dispatch_cfo_*` functions, direct routes, Brain 1/2 wiring). Layer 2 is no longer blocked on CFO; it is specified as the CEO playbook `COMPETITOR_PRICE_IMPACT` (`ceo-agent-orchestration.md` §6.12: CI `ci.request_price_scenario` + CFO `cfo.pricing` as parallel legs, composed by CEO) and is built with the conversational CEO. CI still computes no margin (C26/AC1 unchanged).*

9. **NEW (V3).** **WhatsApp is a declared placeholder for CI evidence intake and alert delivery** (C36, C42): the `WHATSAPP` channel value exists in the shared interface and returns `CHANNEL_NOT_AVAILABLE`. Items 1 and 3 above are *narrowed, not removed*: **CEO Hub screenshot upload is now in scope** (C36) and the CEO conversational route is in scope (the CEO exists), so their "only the dashboard direct path ships" statements are **superseded for the dashboard-upload surface** — retired as a seller surface (C32) and replaced by the CEO Hub attachment path.
10. **NEW (V3).** **Item 6 is partly resolved:** Tavily is approved, its adapter is built (CP1) and its §6.10.1 provider record is completed (§6.10.1a, 2026-10-18). **Still deferred:** the human decisions the record surfaced — redisplay rights, Tavily's retention/training use of query text, and the per-tenant cost ceiling (V16). The two-provider comparison is waived by the owner.
11. **NEW (V3). Item 8 (Layer 2) stands.** The CEO may request a CFO scenario *when available*; where none exists the CEO says so and offers nothing financial (C26, AC29, E37).
12. **NEW (V3). Explicitly deferred by the owner:** competitor sales predictions, speculative competitor margins, automatic repricing, unsupported market-share estimates, continuous scraping, and any additional agent. None may be built under this revision.

None of these deferrals changes C1–C47, D1–D18, A1–A14 or Q1–Q24 as decisions of record; each only states which of them are not yet in scope for the next build pass.

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Price-change detection basis | **Snapshot-to-snapshot delta**, not continuous monitoring | Without live monitoring, change can only be observed between two on-demand runs. Any other framing over-promises. |
| D2 | Default threshold | **±5% on effective selling price**, tenant-configurable | Small enough to catch real repricing, large enough to ignore rounding and minor promo noise. |
| D3 | Secondary threshold | **Availability transition** (in stock ⇄ out of stock) fires regardless of price | A competitor going out of stock is often more actionable than a price move. |
| D4 | Snapshot retention | **Configurable, initially 90 days** (C19, §6.8). Not indefinite. | Deltas need history, but retention is bounded pending DPDP review. Revisit after legal. |
| D5 | Fee references | Held in a **versioned backend-managed reference store** consumed by Brain 1 (C18, `deterministic-engine.md` §5.14). CI passes only marketplace and category, never rates. | Satisfies F4 and 2B.4 — coefficients are configuration, never constants, and never live in an agent. |
| D6 | Stale-evidence policy | **OP3 governs, reframed for evidence:** a snapshot built from evidence is served with a visible age stamp (age of the evidence, not a fetch timestamp) **up to 7 days**. **Beyond 7 days the result is reported unavailable** and the seller is prompted to submit fresh evidence — not displayed with a stamp. Stale data never fires an alert. | OP3 is a locked policy: *report unavailable rather than mislead.* The mechanism changes (no cache to re-fetch; the fix is the seller submitting a new screenshot) but the policy intent is unchanged. |
| D7 | Trusted-domain allowlist's role post-pivot (C4) | **RESOLVED (2026-09-21).** Keep the allowlist as a lightweight intake-time labeling/format check (host must match `amazon.in`/`flipkart.com`/`meesho.com` **or their official short-link domains `amzn.in`/`fkrt.co`**), not a fetch gate — rather than making `competitor_url` fully freeform. The short-link addition itself was also a real-usage finding, not a re-derivation: a real seller's first test submission was Amazon's own mobile-app "Share" link (`amzn.in/...`), rejected under the original three-domain list — confirming these short links are how sellers actually copy competitor URLs in practice, not an edge case. Meesho has no comparably widespread official short-link domain, so none was added for it; revisit if that changes. | Cheap to keep, costs nothing since there is no fetch to gate, and keeps the `marketplace` enum derivable and meaningful instead of asking the seller to self-declare it. |
| D8 | Where `SellerProduct` (C30, §5.5) comes from | **RESOLVED AND LOCKED (2026-09-21) — two sources, not one.** (1) The `sales_line`-derived fields stay a **derived, read-only view** over existing canonical seller data (`packages/data-foundation`), exactly as originally recommended: `product_id`, `title`, `last_updated`. (2) The fields `sales_line` cannot supply — `category`, `attributes`, `keywords`, `price` (current listing price), `fulfillment_type` — are supplied by the seller through a **minimal, editable manual seller-product-profile form** and stored as explicit **`SellerProduct` field overrides** (C31, §5.5). Where both a view-derived and a seller-entered value exist and disagree, **the seller-entered value supersedes**, mirroring §5.3 rule 4 / `evidence/merge.py::apply_manual_overrides` on the competitor side. CI reads both; CI writes neither. | The original view-only recommendation was correct about ownership (CI must not become a second home for seller product data) but was **only partly satisfiable** against the verified schema: `sales_line` has no `category`, `attributes`, `keywords`, `fulfillment_type`, `rating` or `review_count` column and no list-price column (`gross_item_amount` is a transacted amount, not a listing price), and no product/catalog table exists anywhere in the repo. Rather than accept five of eight relevance axes scoring 0 forever, or infer values (which C30 forbids outright), the seller supplies them once. **This is a new UI/API surface, not a backend view** — scoped deliberately small. The `KNOWN`/`UNKNOWN` discipline is untouched: an unfilled field is `UNKNOWN`, never a default. `rating` and `review_count` for the seller's *own* product remain out of the form's scope and stay `UNKNOWN` — see V12. |
| D9 | How V2's per-field freshness thresholds (§6.16.2 — price/availability 24h, rating/review-count/listing-content 7d, review themes 30d) relate to D6/§6.8's locked OP3 7-day ceiling | **RESOLVED AND LOCKED (2026-09-21), exactly as recommended: two layers, both apply; neither replaces the other.** The per-field thresholds (24h price/availability, 7d rating/review-count/listing-content, 30d review themes) set **only** `is_stale = true` on a **fact** — the fact is not hidden or deleted, and any finding built on it says so explicitly. D6's 7-day ceiling remains the separate, stricter **OP3 unavailability ceiling** on the *current answer* for a URL: past 7 days the snapshot is reported unavailable, not merely flagged, and never fires an alert. **Nothing about existing 7-day behaviour changes.** | The V2 source document calls §9.1 "the single source of truth for every other section's reference to the freshness threshold," which read literally would have loosened D6 from *unavailable* to *flagged* — a weakening of a locked never-mislead policy. Layering preserves both intents and is now the locked reading: where the two appear to conflict, **D6/OP3's 7-day ceiling governs availability and §6.16.2 governs only the `is_stale` flag.** The seller-facing wording ("stale" at 24h vs "unavailable" at 7 days) is a copy/UX task, not a spec ambiguity. Note the current implementation hardcodes only the 7-day ceiling (`STALE_SNAPSHOT_CEILING`), so the 24h flagging layer is genuinely new work. |
| D10 | Where the price-band / outlier computation lives | **RESOLVED AND LOCKED (2026-09-21): the deterministic engine, not CI.** The amendment to `deterministic-engine.md` was approved and is made: the arithmetic is **`compute_price_band`, `deterministic-engine.md` §5.15.1**, beside `compute_price_positioning`/`compute_repricing_scenario` (§5.15). **CI's entire role is to supply the tenant's tracked competitor prices as `DERIVED` inputs and render the returned `metric_result` rows, citing the returned `engine_result_ref`** — the identical interface pattern CI already uses for the §5.15 pair. **CI never computes the quartiles, the IQR, the fences or the outlier flags.** | The formula is not margin-aware, but every operand is a signed-`BIGINT` paise money value and the project's hard rule puts all such math in the engine. §6.16.3 below retains the **product rules** — when a band may be shown, the 3-competitor minimum, how outliers are displayed — and states the arithmetic's home; `deterministic-engine.md` §5.15.1 is the authority for the arithmetic itself. Neither spec restates the other. |
| D11 | Discovery opt-out default | **Discovery enabled by default, with a tenant-level opt-out a seller can set at any time** (`ci_tenant_config.discovery_enabled`, §5.4). With discovery off, manual URL entry is the whole product surface and nothing degrades except candidate suggestions. | §6.11 requires discovery be opt-out capable. Defaulting it on matches C21's reason for the reversal; defaulting it off would ship the reversal and then hide it. The opt-out is the seller's control over what leaves Metrion in a query, so it must be honoured before any query is sent, not filtered afterwards. |
| D12 | Entitlement treatment of a discovery run | **One discovery run consumes one CI run unit** against C13's runs/month allowance, the same unit an `EVIDENCE_UPLOAD` run consumes. Candidate volume is bounded separately by §6.12's budgets. | Avoids inventing a second meter before the entitlement spec exists (Q2, Q3 already flag that gap). Provisional, and explicitly subordinate to `billing-and-pricing.md` when that spec finalizes tiers. |
| D13 | Whether discovery may run without a seller-approved product baseline | **No.** A discovery run requires a `SellerProduct` (§5.5) with at least `title` **or** `category` `KNOWN`. With both `UNKNOWN` the run is refused with a named reason, not attempted on thin input. | Query generation from an all-`UNKNOWN` baseline would either produce useless queries or tempt an implementation into inferring a baseline — the precise failure C30 and §6.18 forbid. Refusing is the honest outcome. |
| D14 | How a dashboard shortcut reaches the CEO (C33) | **A pre-composed, visible message the seller sends — not an auto-submitted turn.** The shortcut opens the CEO Hub with the draft text and a structured context reference (`{intent, product_id, finding_id?}`) attached; the seller presses send. | An auto-submitted click would meter a CEO turn and a CI run from an accidental click and put words in the seller's mouth. One extra click keeps the seller in control; the context is still passed structurally so the CEO never parses prose to find the SKU or finding. |
| D15 | Which fields are "consequential" for confirmation (C37) | **Price and effective price, availability transition, and an `EXACT_MATCH` identity assertion** — the three things that reach Brain 1, an alert or a "same product" claim. Rating, review count, delivery text, offer text and listing copy are non-consequential. **While Q18 stands, a vision-extracted consequential field is always confirmed.** | Seller attention is the scarce resource; confirming every field makes a confirmation marathon (the §6.13.2 rationale) and trains click-through. Measured vision price accuracy (13/31, Q18) makes *not* confirming price indefensible. The list is configuration-shaped so Q18's resolution can relax it without a data-model change. |
| D16 | Whether a scheduled job may exist under "no continuous monitoring" (C40) | **Yes, for stored-data re-evaluation only:** freshness recomputation and evidence-freshness reminders over rows CI already holds. **No** scheduled job ever contacts Tavily for prices, fetches a URL, or words anything as current. | Reminders need a trigger; a job that only reads CI's own tables watches no competitor. The honesty rule lives in wording and in C35 and is enforced by test (AC47). |
| D17 | Splitting identity from relationship (C43) | **Keep the four `identity_match` values and their basis unchanged; add `relationship_class`; gate rejection on `UNRELATED`, not on `NOT_A_MATCH`.** Derivation is deterministic from identity plus the category/product/use-case axes (§6.27.1); no new LLM judgement. | Changes no persisted value and no existing relevance axis, so existing rows and tests keep their meaning. The alternative — a fifth identity value — would change a locked enum and every consumer. **This overrides a locked rule (§6.13.2; the code in `identity_resolution.py` `_GATING_TABLE` and its tests) and needs explicit owner confirmation (Q20).** |
| D18 | Dashboard price chart with sparse data (C45, §6.29) | **Plot only real verified snapshots, each dated; draw no line between points further apart than one freshness window; show a plain empty state below two points.** | A smooth 30-day line over three snapshots is an invented trend — the failure C29 and PI §0 both forbid. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | **REVISED for the evidence model (judgment call, flagged for review).** A seller's screenshot legibly shows price, MRP, rating, rating count and availability at the moment of capture, well enough for a vision model to extract them | **High** — vision extraction has nothing to extract if the screenshot omits, crops or obscures a field; mitigated, not eliminated, by the manual-entry fallback (C2, §6.1) |
| A2 | **REVISED for the evidence model.** A competitor URL kept as a reference remains stable enough that a human can still open it weeks later to "go check the listing" | Medium — URL rot means the reference link may not resolve when a seller or CFO wants to verify it directly; it no longer breaks the snapshot series, since the series is built from submitted evidence, not re-fetches |
| A3 | Screenshots of Meesho listings expose a comparable field set to Amazon and Flipkart screenshots | Medium — Meesho's listing layout may yield a thinner extraction even from a clear screenshot |
| A4 | Fee references in the Brain 1 store (`deterministic-engine.md` §5.14) are close enough for a *range*, not a point estimate | Medium — range widens and the gap is named; never presented as precise |
| A5 | One URL maps to one sellable variant | Medium — multi-variant pages need a variant key |
| A6 | **NEW (V2).** A licensed search provider exists whose terms permit storing returned results and redisplaying them to sellers inside a commercial SaaS product, at a cost that works at §6.12's query volume | **High** — if no candidate provider clears the §6.10.1 record, discovery (C21) has no acquisition path at all and CI falls back permanently to manual URL entry. This is precisely why C22 forbids assuming a provider by name |
| A7 | **NEW (V2).** Search snippets carry enough signal (title, visible price, marketplace, seller name) to run identity resolution and provisional relevance scoring *before* any evidence exists | Medium — if snippets are thinner than assumed, most axes score `UNKNOWN`/0 and the Recommended set degrades toward "five arbitrary leads". Mitigated, not eliminated, by C23: nothing is presented as intelligence either way |
| A8 | **NEW (V2).** Sellers will actually upload evidence for candidates they approve, converting "Approved — awaiting evidence" into evidence-backed competitors | **High** — the whole V2 value chain (comparison, mining, alerts) is gated on evidence per C23. If conversion is low, discovery produces a list the product can say almost nothing about. Product-side mitigation (prompting, digest reminders via `staleness_reminder_days`) is outside this spec's control |
| A9 | **NEW (V2).** The eight relevance axes and their 0/1/2 thresholds (§6.14) are approximately right for Indian marketplace categories on first launch | Medium — explicitly a first-pass rule set (C25); wrong thresholds produce a poorly-ordered Recommended set, not a wrong *fact*, and are tuned from real seller feedback without any data-model change |
| A10 | **NEW (C31).** Enough sellers will fill the minimal seller-product-profile form (§5.5.1) — five fields, one time, editable — for relevance scoring to be materially better than the all-`UNKNOWN` baseline | Medium — if completion is low, CI degrades **gracefully and honestly** to exactly the pre-C31 behaviour (those axes score 0, nothing is invented). A wrong *score ordering*, never a wrong *fact*. Mitigation is product-side prompting, outside this spec. Tracked at V12 |
| A11 | **NEW (V3).** Sellers will attach screenshots in chat and answer short confirmation questions (price, stock) when the CEO asks. | **High** — if not, consequential fields stay unconfirmed and CI correctly produces no verified price, band or alert (C37): honest degradation, never a fabricated figure. Mitigation is CEO wording and one-tap answers, outside this spec. |
| A12 | **NEW (V3).** Tavily returns enough title/snippet/URL signal on Amazon, Flipkart and Meesho listings for identity resolution and provisional relevance to be useful (extends A7). | Medium — with thin snippets most axes score `UNKNOWN`/0 and the Recommended set weakens; nothing is presented as fact either way (C35). |
| A13 | **NEW (V3).** Deterministic image checks (dimensions, size, blur measure), optionally with the local vision model, can meet the §6.22.1 quality gate. | Medium — if not, more poor images reach extraction; C37's confirmation of consequential fields is the backstop. |
| A14 | **NEW (V3).** The CEO Hub's existing attachment mechanism (`CEO_ATTACHMENT_*` limits, attachment reader — `ceo-agent-orchestration.md` §6.34) can carry a competitor screenshot to CI's intake without weakening the CEO's request hardening. | Medium — **corrected at CP1:** the CP0 text said the CEO Hub had no attachment path; backend attachment support exists (images/PDF, env-limited, refused when unset). CP3 must audit what it already does before adding anything (§7 rules 16–18). |

---

## 4. Goals and non-goals

**Goals** — store seller-supplied, reference-only competitor URLs; let the seller submit evidence (dashboard screenshot upload) for those competitors; extract structured snapshots from that evidence via a vision model, with manual-entry fallback; detect threshold-breaching price and availability changes between snapshots; produce derived review insight; supply observed inputs to Brain 1 for an estimated margin band; surface findings through CEO and, where enabled, WhatsApp.

**Goals — V2 additions (C21–C30).** Generate research queries from the seller's own product and surface **candidate** competitors for seller review (C21), within a locked query-privacy boundary (§6.11) and query/cost budget (§6.12) · resolve each candidate's product identity explicitly (C24) · score candidate relevance on the locked eight-axis algorithm and always show the breakdown (C25) · keep every candidate visible across three labelled tiers, filtering nothing silently (§6.15) · mine customer voice into themes with stated frequency and bounded, auditable snippet retention (C27) · emit Layer 1 observational alerts (C26) · emit a structured Competitive Brief and `CIHandoff` payloads to CEO (C28) · **supply `competitor_prices[]` as `DERIVED` inputs to `deterministic-engine.md` §5.15 and render its results unchanged.**

**Goals — V3 additions (C32–C47).** One seller-facing conversation, with the CEO · screenshot evidence by CEO Hub attachment with quality, duplicate and identity checks · risk-based seller confirmation · cross-brand competitors found and classified without guessing · conversational approve/reject/add/remove with full history · honest monitoring as re-evaluation of stored evidence · configurable, deduplicated, quiet-hours-aware Layer 1 alerts · a read-only CI dashboard that mirrors actual CEO–CI findings, evidence and history, with professional empty states.

**Non-goals — V3 additions.** Any manual form, input or upload on the CI dashboard (C32) · a CI chatbot or any seller-facing CI voice (C32, C38) · treating a Tavily value as an observation (C35) · any claim of continuous, live or real-time monitoring (C40) · competitor sales prediction, speculative competitor margins, automatic repricing, unsupported market-share estimates, continuous scraping, additional agents (§1a item 12) · rehosting or discovering competitor product images — the dashboard shows insights and findings only (C5, owner decision 2026-10-18) · building WhatsApp media ingestion (C36).

**Non-goals — SUPERSEDED entry.** The V1 non-goal *"competitor discovery (CI never finds competitors, the seller supplies them)"* is **superseded by C21 (2026-09-21, Checkpoint-0 review)** and is struck from the list below. It is recorded here rather than deleted, so the reversal is traceable — the same treatment C2 gave the scraping→evidence pivot and D7 gave the short-link resolution. **What survives the reversal:** manual URL entry remains a permanent, always-available path (C21); discovery still never produces competitive-intelligence *facts* (C23); and nothing about discovery involves fetching a marketplace URL — C2 is untouched.

**Non-goals (V1, as amended)** — **fetching any competitor URL, ever, for any reason** (the pivot's central non-goal) · continuous or scheduled monitoring · ~~competitor discovery~~ **(superseded by C21 — see above)** · persisting scraped or copied review text, listing copy or images (seller-submitted evidence is the one carved-out exception, C16) · performing any financial calculation · holding fee rates · indefinite snapshot or raw-evidence-image retention · sending raw expression to a hosted model provider · deciding WhatsApp behaviour · WhatsApp evidence intake in this pass (§1a) · supplier data · automated repricing or any marketplace write.

**Non-goals — V2 additions.** Scraping a search engine's frontend, or any other page, to obtain discovery leads (C22 — licensed provider or nothing) · treating a search snippet as a competitive-intelligence fact (C23) · comparing, mining or alerting on a candidate that has no evidence source (C23) · computing any financial, margin or break-even implication inside a CI alert (C26 — Layer 2 is CEO's, and is deferred) · market/demand trend claims of any kind (C29) · inventing a seller-side baseline to complete a comparison (C30, §6.18) · presenting absence of evidence as evidence of absence (§6.18) · cross-seller aggregate benchmarking (a data-availability gate, revisitable once enough tracked competitors exist across enough sellers) · prescribing discovery's internal persistence/API shape beyond the distinguishable states §5.4 requires.

---

## 5. Data model and interfaces

```sql
competitor_url (
  id uuid pk, tenant_id uuid not null,
  marketplace text not null,            -- AMAZON | FLIPKART | MEESHO — derived from host (C4), labeling only
  url text not null,                    -- REFERENCE-ONLY (C2/C3): never fetched. A pointer for a human to go check the listing.
  label text,                           -- seller's own name for this competitor
  linked_sku text,                      -- optional: seller SKU this competes with
  tags text[] not null default '{}',    -- NEW: free-form tenant labels, e.g. 'DIRECT_RIVAL', 'ASPIRATIONAL'
  price_threshold_pct_override numeric(5,2),        -- NEW (closes Q5): per-URL override of ci_tenant_config.price_threshold_pct; null = inherit tenant default
  alert_on_availability_change_override boolean,    -- NEW (closes Q5): per-URL override; null = inherit tenant default
  status text not null,                 -- ACTIVE | UNREACHABLE | ARCHIVED  -- UNREACHABLE now means "seller reports this listing no longer exists", not a fetch failure
  added_by uuid not null, created_at timestamptz not null,
  unique (tenant_id, url)
)

-- NEW: an evidence submission — one row per screenshot the seller uploads.
-- See §5.3 for the shape of a research session and merge semantics.
competitor_evidence (
  id uuid pk, tenant_id uuid not null,
  competitor_url_id uuid not null,
  research_session_id uuid not null,    -- groups the screenshots submitted together as one merge unit (§5.3)
  image_ref text not null,              -- pointer into object storage; NOT a guarantee of indefinite raw-byte retention (§6.8)
  uploaded_by uuid not null,
  uploaded_at timestamptz not null,
  extraction_status text not null,      -- PENDING | EXTRACTED | EXTRACTION_FAILED
  extraction_model text,                -- which vision model/version ran; null while §1a item 4 is unresolved
  image_retained_until timestamptz      -- raw image bytes purged after this; the evidence row and its extracted fields survive (§6.8)
)

competitor_snapshot (
  id uuid pk, tenant_id uuid not null,
  competitor_url_id uuid not null,
  ci_capture_run_id uuid not null,
  research_session_id uuid not null,    -- NEW: which evidence submission(s) this snapshot was merged from
  captured_at timestamptz not null,     -- NEW MEANING: the merge/derivation time, not a fetch time
  capture_status text not null,         -- COMPLETE | PARTIAL | PENDING_MANUAL_ENTRY (replaces OK|BLOCKED|NOT_FOUND|PARSE_FAILED — no fetch outcome exists any more, §5.3)
  -- Per C16's carve-out: seller-submitted title/description/bullets MAY now be captured as structured fields.
  -- Per-field confidence and source live in competitor_snapshot_field (§5.3), not as one snapshot-level value.
  title text, description text, bullets jsonb,   -- NEW under C16's carve-out: seller's own submitted evidence, never scraped
  seller_name text,                     -- business identity, a fact, not expression
  observed_category text,               -- BL5: as shown in the seller's evidence; see Q8 on taxonomy mapping
  category_confidence text,             -- §5.1 vocabulary: VISION_EXTRACTED | SELLER_ENTERED | DERIVED | UNAVAILABLE
  listed_price_paise bigint, mrp_paise bigint,
  visible_discount_paise bigint,
  rating numeric(2,1), rating_count int,
  availability text,                    -- IN_STOCK | OUT_OF_STOCK | UNKNOWN
  variant_key text,                     -- A5
  source_url text not null,             -- the competitor_url this evidence is for; reference-only, never re-visited by Metrion
  confidence text not null              -- §5.1 vocabulary, snapshot-level rollup: VISION_EXTRACTED | SELLER_ENTERED | DERIVED | UNAVAILABLE
)

-- NEW: per-field provenance and merge-conflict tracking (§5.3). One row per extracted/entered
-- field per snapshot. `competitor_snapshot`'s scalar columns above hold the current merged
-- value for convenience; this table is the authority for what produced it and whether it is
-- trustworthy on its own.
competitor_snapshot_field (
  id uuid pk, tenant_id uuid not null,
  snapshot_id uuid not null,
  field_name text not null,             -- e.g. listed_price_paise, mrp_paise, rating, title, availability, ...
  value jsonb,                          -- null when conflicted/unresolved — see conflict rule below
  source text not null,                 -- VISION_EXTRACTED | SELLER_ENTERED
  confidence text not null,             -- §5.1 vocabulary
  evidence_id uuid,                     -- the competitor_evidence this value came from; null when conflicted across evidence
  conflict boolean not null default false,  -- true when N screenshots disagree on this field (§5.3 rule 3)
  conflict_values jsonb,                -- the disagreeing candidate values, shown to the seller for manual resolution
  set_at timestamptz not null,
  unique (snapshot_id, field_name)
)

competitor_review_insight (               -- C5/C6/C14: derived only, no verbatim text
  id uuid pk, snapshot_id uuid not null, tenant_id uuid not null,
  sentiment_split jsonb,                -- {positive, neutral, negative} proportions
  rating_distribution jsonb,            -- {1..5: count}
  complaint_themes jsonb,               -- [{theme, weight}] — themes, never quotes
  positive_themes jsonb,
  summarised_patterns jsonb,            -- C6: required derived output
  reviews_considered int,               -- review count
  -- B5: confidence, provenance, degraded state
  confidence text not null,             -- see §5.1 vocabulary
  derivation_method text not null,      -- LOCAL_MODEL | LOCAL_HEURISTIC | STRUCTURED_ONLY
  insight_state text not null,          -- COMPLETE | DEGRADED | UNAVAILABLE
  degraded_reason text,                 -- required when insight_state <> COMPLETE
  source_url text not null,             -- RENAMED MEANING (resolves Q11): the competitor_url this evidence is about; reference-only, never fetched by Metrion (consistent with competitor_snapshot.source_url, §5)
  fetched_at timestamptz not null,      -- RENAMED MEANING (resolves Q11): when the seller captured/uploaded the reviews-tab screenshot(s) this insight was derived from, not a fetch time (consistent with competitor_snapshot.captured_at, §5)
  derived_at timestamptz not null       -- when derivation ran
)

competitor_listing_insight (              -- C16/M5: derived attributes only, no copied text
  id uuid pk, snapshot_id uuid not null, tenant_id uuid not null,
  keyword_themes jsonb,                 -- themes, never the title itself
  title_length int, title_structure jsonb,
  feature_categories jsonb,
  benefit_term_patterns jsonb,
  differentiation_opportunities jsonb,
  bullet_count int, image_count int,
  confidence text not null,
  derivation_method text not null,
  insight_state text not null,
  source_url text not null,
  fetched_at timestamptz not null, derived_at timestamptz not null
)

ci_tenant_config (                        -- thresholds, retention and (NEW) staleness/digest defaults
  tenant_id uuid pk,
  price_threshold_pct numeric(5,2) not null default 5.00,   -- D2; per-URL override at competitor_url.price_threshold_pct_override
  alert_on_availability_change boolean not null default true, -- D3; per-URL override at competitor_url.alert_on_availability_change_override
  snapshot_retention_days int not null default 90,          -- C19
  raw_evidence_image_retention_days int not null default 90,  -- NEW: separate, shorter-or-equal retention for raw screenshot bytes (§6.8); metadata/extracted fields outlive the image
  staleness_reminder_days int not null default 14,          -- NEW: remind the seller to submit fresh evidence for a URL after this many days since its last evidence
  digest_default_frequency text not null default 'WEEKLY',  -- NEW: NONE | DAILY | WEEKLY — default applied when a member has no explicit ci_digest_subscription row
  updated_by uuid, updated_at timestamptz not null
)
-- No WhatsApp state here. Enablement lives on auth.md `whatsapp_binding.enabled`
-- (owner-controlled, W10); cadence and scheduling belong to whatsapp-integration.md (§6.9).

-- NEW: in-app digest/reminder subscription (§5.3). WhatsApp delivery is a documented future
-- channel (§1a item 3) — `channel` has exactly one legal value in this pass.
ci_digest_subscription (
  id uuid pk, tenant_id uuid not null,
  member_id uuid not null,
  frequency text not null,              -- NONE | DAILY | WEEKLY
  channel text not null default 'IN_APP',   -- IN_APP only in this pass; WHATSAPP deferred (§1a)
  enabled boolean not null default true,
  last_sent_at timestamptz,
  created_at timestamptz not null,
  unique (tenant_id, member_id)
)

competitor_price_event (
  id uuid pk, tenant_id uuid not null,
  competitor_url_id uuid not null,
  from_snapshot_id uuid not null, to_snapshot_id uuid not null,
  delta_paise bigint not null, delta_pct numeric(6,2) not null,
  direction text not null,              -- INCREASE | DECREASE
  availability_change text,             -- null | IN_TO_OUT | OUT_TO_IN
  threshold_breached boolean not null,
  ci_capture_run_id uuid not null,      -- MN14: provenance
  created_at timestamptz not null,
  observed_span interval not null,      -- gap between the two snapshots
  alert_eligible boolean not null       -- false when either snapshot is stale (D6)
)

-- Retention note (MN7): snapshot purge (§6.8) must not orphan derived rows.
-- `competitor_review_insight.snapshot_id`, `competitor_listing_insight.snapshot_id`
-- and `competitor_price_event.from_snapshot_id/to_snapshot_id` are nullable-on-purge:
-- the snapshot row is removed, the derived insight and its own provenance survive.

ci_capture_run (                          -- distinct from PI's paid niche research run
  id uuid pk, tenant_id uuid not null,
  trigger text not null,                -- EVIDENCE_UPLOAD | DIRECT_UI | CEO_REQUEST | WHATSAPP_CONFIRM
                                         -- EVIDENCE_UPLOAD is NEW and is the only wired value in this pass (§6.1, §6.4):
                                         -- it fires when the seller submits a screenshot from the dashboard, and effectively
                                         -- supersedes DIRECT_UI's former role as "the dashboard trigger" (DIRECT_UI previously
                                         -- meant a fetch-triggering button, which no longer exists). DIRECT_UI is kept in the
                                         -- enum for a possible future non-evidence direct action (e.g. "recompute this
                                         -- research session's merge without new evidence") but is not wired to any execution
                                         -- path in this pass. CEO_REQUEST and WHATSAPP_CONFIRM remain deferred per §1a, unchanged.
  requested_by uuid not null,
  url_ids uuid[] not null,
  research_session_id uuid,             -- NEW: set when trigger = EVIDENCE_UPLOAD; the merge unit this run processed
  status text not null,                 -- QUEUED | RUNNING | PARTIAL | COMPLETE | FAILED
  started_at timestamptz, finished_at timestamptz
)
```

### 5.1 Confidence vocabulary for evidence-derived data (M12) — REVISED for the evidence model

`data-foundation.md` §7.1 defines confidence in terms of *adapter mapping* provenance, which does not describe a field extracted from a seller's screenshot or typed in by hand. CI therefore uses an explicitly scoped vocabulary, declared here rather than borrowed. **`OBSERVED` is retired** — it meant "read directly from the listing page at `fetched_at`", which no longer describes anything CI does, since CI never reads a listing page. It is replaced by two tiers reflecting who/what actually produced the value:

| Level | Meaning for CI |
|---|---|
| `VISION_EXTRACTED` | Extracted by the vision model from a seller-submitted screenshot, not (yet) corrected or confirmed by the seller |
| `SELLER_ENTERED` | Typed in directly by the seller — either manual entry where extraction found nothing, or a manual correction of a `VISION_EXTRACTED` value |
| `DERIVED` | Computed or inferred from `VISION_EXTRACTED`/`SELLER_ENTERED` values (themes, patterns, deltas) — meaning unchanged from before |
| `UNAVAILABLE` | Could not be captured or resolved; reason recorded — meaning unchanged from before, and also the required outcome for a multi-screenshot field conflict (§5.3 rule 3) pending seller resolution |

When a CI value is passed into Brain 1 it **always enters as `DERIVED`**, regardless of whether CI recorded it internally as `VISION_EXTRACTED` or `SELLER_ENTERED`. Neither tier ever crosses the boundary as itself. This gives a defined ordering against `data-foundation.md` §7.1 — a CI-sourced figure can never present as `VERIFIED` or `PROVISIONAL` — and the monotonic rule then applies to everything downstream, exactly as it did under the retired `OBSERVED` label.

### 5.2 Interface to Brain 1 (C17 / B1)

**Deferred — see §1a.** This interface, and everything below in this subsection, is not being implemented in the next pass: it requires a Brain-1 extension (`estimate_ref`, `CompetitorObservationSet`, and the accepting function) that does not yet exist in `packages/calc-engine` and must be specified in `deterministic-engine.md` first. The description below remains the design intent, not a build target.

CI normalises observations into a provenance-tagged input object. **Brain 1 performs every calculation.** The interface itself is specified in `deterministic-engine.md` §5.13; CI only constructs the input and renders the output.

```
CompetitorObservationSet {
  marketplace, category,
  observed_price_paise, visible_discount_paise, mrp_paise,
  variant_key,
  source_url, fetched_at,
  confidence            -- always DERIVED at this boundary (§5.1)
}
```

CI passes **no rates and no fee amounts** — Brain 1 resolves those from the fee reference store (C18). Brain 1 returns an estimated range carrying an **`estimate_ref`** plus its basis, assumptions and engine metadata (engine §9.1). CI renders it unchanged, cites the `estimate_ref` — never an `engine_result_ref` — and always labels it **"estimated margin range"** (C10, C17).

### 5.3 Evidence submission, `research_session_id` and merge semantics (NEW — C2)

**A research session is the merge unit.** One `research_session_id` groups every `competitor_evidence` (screenshot) row the seller submits together for one `competitor_url` in one sitting. It exists so multiple screenshots — e.g. a full listing page that needed two scrolled captures — can be merged into a single `competitor_snapshot` rather than producing several partial, conflicting snapshots.

1. **Extraction runs per screenshot.** Each `competitor_evidence` row is extracted independently by the vision model, producing candidate field values with `source = VISION_EXTRACTED`.
2. **Merge runs per research session.** For each `field_name`, if every screenshot that reports a value agrees (or only one screenshot reports it), that value is written to `competitor_snapshot_field` and rolled up into `competitor_snapshot`'s scalar column.
3. **Disagreement is never silently resolved — hard rule.** If two or more screenshots in the same research session report *different* values for the same field, the merge **never picks one**. `competitor_snapshot_field.conflict = true`, `value = null`, `confidence = UNAVAILABLE`, and `conflict_values` records every candidate so the seller can resolve it manually (which produces a `SELLER_ENTERED` correction, superseding the conflict). The snapshot-level column for that field is also `null`/`UNAVAILABLE` until resolved. This is the same architectural rule that governs every other "don't guess, surface it" case in this codebase (data-foundation confidence, discount-bearer `UNKNOWN` handling, fee-reference gaps) — it is not a suggestion.
4. **Manual entry** (`source = SELLER_ENTERED`) is available for any field, at any time: where extraction found nothing (`competitor_evidence.extraction_status = EXTRACTION_FAILED` or the field was simply absent from every screenshot), where the seller wants to correct a `VISION_EXTRACTED` value, or where the seller wants to resolve a conflict from rule 3. A `SELLER_ENTERED` value always supersedes a `VISION_EXTRACTED` one for the same field on the same snapshot.
5. **`capture_status` reflects the merge outcome, not a fetch outcome** (replaces `OK | BLOCKED | NOT_FOUND | PARSE_FAILED`, §5):

| `capture_status` | Meaning |
|---|---|
| `COMPLETE` | Every field required for change detection and alerts (price, availability) is resolved, with no open conflict |
| `PARTIAL` | Some required fields are resolved; at least one is `UNAVAILABLE` (extraction miss or unresolved conflict) but the snapshot is still usable for the fields it does have |
| `PENDING_MANUAL_ENTRY` | Extraction failed or found nothing usable for a required field, and the seller has not yet supplied it manually — the snapshot exists (§6.1 rule 4 still holds: an evidence submission always yields a row) but cannot support change detection until the seller acts |

A snapshot may transition `PENDING_MANUAL_ENTRY → PARTIAL → COMPLETE` as the seller enters missing fields; it never transitions backward silently — a later contradicting entry creates a new superseding value, following the same non-destructive spirit as `manual_adjustment` in `deterministic-engine.md` §7.1, even though CI's provenance model is its own (§5.1).

### 5.4 Discovery data model (NEW — C21–C25)

Everything in this subsection is **additive**. No table, column or enum defined in §5 above is altered, renamed or dropped by V2.

**States that must stay distinguishable.** The V2 source document deliberately stops short of prescribing discovery's internal persistence shape — that is an implementation decision, since discovery's state lives entirely inside CI and crosses no boundary another team's code depends on. What it *does* fix, and what this spec adopts as binding, is the **complete list of states a valid implementation must keep distinct**. The SQL below is one conforming shape, offered so the spec is concrete; an implementation may choose different tables, **but may not collapse any two of these into one field**:

| State / entity | Must stay distinguishable from |
|---|---|
| Discovery run, with its state-machine status (§6.12.2) | — |
| Raw candidate (unanalyzed) | Analyzed candidate |
| Analyzed candidate (identity-resolved + relevance-scored) | Raw candidate; Recommended candidate |
| Recommended candidate | Analyzed candidate (it is a subset of it) |
| Identity match result (`EXACT_MATCH`/`LIKELY_VARIANT`/`UNCERTAIN`/`NOT_A_MATCH`) | The relevance score — a separate axis (C25) |
| Relevance breakdown (per-axis scores + band) | Discovery-provisional vs confirmed labelling (§6.14.0) |
| Seller approval/rejection decision | The identity match result — approval is a **seller action**, not a system-computed value |
| Evidence status (`AWAITING_EVIDENCE` / `EVIDENCE_BACKED`) | Relevance **and** identity match — this is a third, independent axis (C23, C25) |
| Search result / cache entry | Raw candidate — one cache entry may produce zero or many raw candidates |

Collapsing any two of these silently violates a rule locked elsewhere in this spec: collapsing evidence status into relevance violates C23/C25; collapsing the seller decision into the identity match result makes a human approval indistinguishable from a machine judgement.

```sql
-- NEW: one discovery run. State machine in §6.12.2.
ci_discovery_run (
  id uuid pk, tenant_id uuid not null,
  seller_product_ref text not null,     -- the SellerProduct.product_id this run is for (§5.5); a reference, not a FK — SellerProduct is a merged contract over a canonical view plus seller-entered overrides, not a single table (D8, C31, §5.5.1)
  requested_by uuid not null,
  status text not null,                 -- QUEUED | SEARCHING | DISCOVERING | WAITING_FOR_REVIEW | RESEARCHING | COMPLETE | FAILED | PARTIAL | STALE
  partial_reason text,                  -- REQUIRED when status = PARTIAL: which budget or provider error stopped it (§6.12.1)
  failed_reason text,                   -- REQUIRED when status = FAILED
  stale_marked_at timestamptz,          -- set when a COMPLETE run transitions to STALE (§6.12.2 locked rule)
  provider_name text,                   -- which SearchProvider implementation ran; 'MOCK' until C22's approval lands
  queries_used int not null default 0,
  raw_candidate_count int not null default 0,
  analyzed_candidate_count int not null default 0,
  ci_capture_run_id uuid,               -- links to the run that consumed the entitlement unit (D12)
  started_at timestamptz, finished_at timestamptz,
  created_at timestamptz not null
)

-- NEW: one externally-sent query. Tenant-isolated (§6.11). The stored text is the
-- POST-REDACTION text actually sent — never the pre-redaction draft (§6.11 rule 4).
ci_search_query (
  id uuid pk, tenant_id uuid not null,
  discovery_run_id uuid not null,
  query_text text not null,             -- exactly what left Metrion, after the §6.11 allow/deny filter
  query_kind text not null,             -- PRODUCT_TERM | CATEGORY_TERM | FEATURE_TERM | INTENT_PHRASE | SUBSTITUTE_TERM | KEYWORD_TERM
  is_followup boolean not null default false,  -- secondary/follow-up search for a specific candidate (§6.12.1 cap)
  parent_candidate_id uuid,             -- set when is_followup
  sent_at timestamptz not null,
  provider_name text not null,
  result_count int,
  error_code text                       -- provider error; contributes to PARTIAL (§6.12.1)
)

-- NEW: raw provider results, cached 24h (§6.12.1). Tenant-isolated: the cache is NEVER
-- shared across tenants, even for an identical query string — cross-tenant cache reuse
-- would leak one tenant's research interest to another.
ci_search_result (
  id uuid pk, tenant_id uuid not null,
  search_query_id uuid not null,
  result_rank int not null,
  result_url text not null,
  result_title text,                    -- LEAD ONLY (C23) — never rendered as a competitor fact
  result_snippet text,                  -- LEAD ONLY (C23)
  fetched_at timestamptz not null,
  cache_expires_at timestamptz not null,   -- fetched_at + 24h by default (§6.12.1)
  provider_response_ref text            -- provider's own result/response id, for Evidence.source_reference when a licensed provider is in use (C28)
)

-- NEW: a discovered candidate. `tier`, `identity_match`, `seller_decision` and
-- `evidence_status` are FOUR independent fields and are never merged (see table above).
ci_candidate (
  id uuid pk, tenant_id uuid not null,
  discovery_run_id uuid not null,
  search_result_id uuid,                -- null when the candidate was added manually by the seller
  origin text not null,                 -- DISCOVERED | MANUAL_URL | PROMOTED_BY_SELLER
  candidate_url text not null,          -- validated against the C4/D7 allowlist on the same terms as competitor_url
  marketplace text,                     -- derived from host (C4)
  tier text not null,                   -- RAW | ANALYZED | RECOMMENDED  (§6.15 visibility tiers; RECOMMENDED is a subset of ANALYZED's population, kept as its own value deliberately)
  identity_match text,                  -- EXACT_MATCH | LIKELY_VARIANT | UNCERTAIN | NOT_A_MATCH | null while tier = RAW (C24)
  identity_match_basis jsonb,           -- which attributes drove the judgement (brand, model, pack size, bundle status) — required whenever identity_match is set
  seller_decision text not null default 'NONE',   -- NONE | APPROVED | REJECTED  — a HUMAN action, never system-written (§6.13.2)
  seller_decided_by uuid, seller_decided_at timestamptz,
  evidence_status text not null default 'AWAITING_EVIDENCE',  -- AWAITING_EVIDENCE | EVIDENCE_BACKED (C23)
  competitor_url_id uuid,               -- set once the candidate is promoted into a tracked competitor_url (§6.15 rule 6)
  created_at timestamptz not null,
  unique (tenant_id, discovery_run_id, candidate_url)
)

-- NEW: the relevance breakdown. One row per candidate per scoring pass. Never collapsed
-- into a single number on ci_candidate — C25 forbids it, and §6.14.3 requires the
-- per-axis numbers be renderable with the band, always.
ci_candidate_relevance (
  id uuid pk, tenant_id uuid not null,
  candidate_id uuid not null,
  scored_at timestamptz not null,
  is_provisional boolean not null,      -- true while the candidate has no evidence source (§6.14.0)
  band text not null,                   -- HIGH | MEDIUM | LOW
  total_score int not null,             -- 0..16
  axis_scores jsonb not null,           -- {category:2, product:2, price_proximity:2, features:1, keywords:2, use_case:2, fulfillment:'UNKNOWN', review_tier:1}
  axis_states jsonb not null,           -- per axis: KNOWN | UNKNOWN | CONFLICTED  (§6.14.2) — an UNKNOWN axis and a genuinely-0 axis are different things and are stored differently
  axis_rationale jsonb,                 -- per axis, the plain-language reason rendered in the "why this competitor" panel (§6.14.4); for LLM-judged axes, the attributes cited
  recalculated_from uuid                -- prior ci_candidate_relevance row this supersedes, when evidence contradicted a discovery assumption (§6.14.0)
)

-- NEW: bounded, auditable retention of the snippet a review theme cites (C27).
-- This is the ONE carve-out from C14's no-granular-review-text rule, and it is explicitly bounded.
ci_evidence_snippet (
  id uuid pk, tenant_id uuid not null,
  review_insight_id uuid not null,      -- the competitor_review_insight whose theme this supports
  theme_key text not null,              -- the theme in that insight's complaint_themes/positive_themes this snippet evidences
  snippet_text text not null,           -- typically one to two sentences — the cited extract ONLY, never a full review (C27)
  competitor_url_id uuid not null,      -- source competitor/listing reference
  extracted_at timestamptz not null,
  retain_until timestamptz not null,    -- extracted_at + ci_tenant_config.evidence_snippet_retention_days; never beyond a source/provider retention ceiling (C27)
  retention_extended_by uuid,           -- seller or Metrion admin who extended it
  retention_extension_reason text,      -- REQUIRED when retention_extended_by is set (C27: "a specific competitor, e.g. an ongoing dispute")
  expired boolean not null default false   -- set on purge; the parent theme then renders "source evidence expired" rather than disappearing (C27)
)
```

**Additions to `ci_tenant_config` (§5)** — new columns only; no existing column changes:

```sql
-- appended to ci_tenant_config
  discovery_enabled boolean not null default true,              -- D11; the §6.11 opt-out. Honoured BEFORE any query is sent.
  max_discovery_queries_per_run int not null default 20,        -- §6.12.1
  max_raw_candidates int not null default 50,                   -- §6.12.1
  max_analyzed_candidates int not null default 20,              -- §6.12.1
  max_recommended_candidates int not null default 5,            -- §6.12.1
  max_followup_searches_per_candidate int not null default 3,   -- §6.12.1
  discovery_run_timeout_seconds int not null default 120,       -- §6.12.1
  search_cache_ttl_hours int not null default 24,               -- §6.12.1
  evidence_snippet_retention_days int not null default 90,      -- C27
  freshness_price_hours int not null default 24,                -- §6.16.2
  freshness_availability_hours int not null default 24,         -- §6.16.2
  freshness_rating_days int not null default 7,                 -- §6.16.2
  freshness_review_count_days int not null default 7,           -- §6.16.2
  freshness_listing_content_days int not null default 7,        -- §6.16.2
  freshness_review_theme_days int not null default 30,          -- §6.16.2
  min_competitors_for_price_band int not null default 3         -- §6.16.3
```

Every value above is **configuration, not a constant**. None may be hardcoded. All are tunable without a migration.

**RLS.** Every table in this subsection carries `tenant_id` and is RLS-scoped with `FORCE`, on the identical pattern as the existing CI tables (`auth.md` §7.3). `ci_search_result` in particular is tenant-scoped **even though its content is public search output** — see §6.11 rule 5.

### 5.5 `SellerProduct` — read-only baseline contract (NEW — C30; sources resolved by C31/D8)

```
SellerProduct {
  product_id: string
  title:            string | UNKNOWN
  category:         string | UNKNOWN
  price:            paise  | UNKNOWN          -- signed BIGINT paise, never a float
  attributes:       [ { key, value } ] | UNKNOWN
  keywords:         [ string ] | UNKNOWN
  fulfillment_type: enum   | UNKNOWN          -- same enum space as competitor fulfillment_type
  review_count:     number | UNKNOWN
  rating:           number | UNKNOWN
  last_updated:     timestamp

  -- per-field provenance, REQUIRED on every populated field (C31)
  field_source:     { <field_name>: CANONICAL_DERIVED | SELLER_ENTERED }
}
```

**Every field is explicitly `KNOWN` or `UNKNOWN`. Never silently defaulted, never inferred from another field, never backfilled with an implementer's guess.** A seller-side `UNKNOWN` propagates as an `UNKNOWN` comparison scoring 0 (§6.14.2) — the system never invents a baseline in order to produce a comparison. **C31 does not change this.** It adds a second legitimate *source*, not a relaxation: a field is `KNOWN` because the canonical data supplies it **or** because the seller typed it, and `UNKNOWN` otherwise.

#### 5.5.1 The two sources, and precedence — LOCKED (D8/C31, 2026-09-21)

**Source 1 — canonical-derived (read-only view).** A derived, read-only view over existing canonical seller data, primarily `sales_line` (`packages/data-foundation`) — not a new stored table. CI reads it and never writes it; the view inherits `sales_line`'s RLS.

**Source 2 — the manual seller-product profile (`SELLER_ENTERED`).** A **minimal, one-time-but-always-editable seller-product-profile form — new UI and new API surface, not a backend view** — capturing **category · attributes (key/value pairs) · keywords · current listing price · fulfillment type**. Values are persisted as explicit **`SellerProduct` field overrides**, tenant-scoped and RLS-`FORCE`d like every other tenant table (§7). **CI never writes this surface either** — the seller owns it; CI only reads the merged contract.

**Precedence — mirroring the existing competitor-side precedent, not a new rule.** Where both sources have a value for the same field and they disagree, **the `SELLER_ENTERED` value supersedes the `CANONICAL_DERIVED` one**, and `field_source` records which won. This is deliberately the **same "manual entry supersedes" pattern already implemented for competitor-side data** at §5.3 rule 4 — `packages/competitor-intelligence/src/competitor_intelligence/evidence/merge.py::apply_manual_overrides`, where a `SELLER_ENTERED` value always supersedes a `VISION_EXTRACTED` one. Seller side, same shape.

**Not a conflict case.** Unlike §5.3's multi-screenshot merge (AC8b), a disagreement here does **not** produce `UNAVAILABLE`/`conflict = true`: there is a designated winner by rule, because one of the two sources is the seller stating a present fact about their own product and the other is an inference-free read of historical transactions. Where **neither** source has a value, the field is `UNKNOWN` — never a merge artefact, never a default.

#### 5.5.2 Field-by-field sourcing (verified against the current schema, 2026-09-21)

Against `packages/data-foundation/migrations/versions/20260917_0001_sales_side_tables.py`:

| `SellerProduct` field | Canonical source | Seller-profile form (C31) | Resulting status |
|---|---|---|---|
| `product_id` | `sales_line.sku` (or `marketplace_item_id`) | — | Available |
| `title` | `sales_line.item_title` | — | Available |
| `category` | none | **Yes** | `KNOWN` once the seller fills it; `UNKNOWN` until then. Still subject to Q8 (taxonomy mapping) for *fee* resolution — a seller-typed category string is a CI baseline, not a fee-store taxonomy key |
| `price` | none (`gross_item_amount` is a *transacted* amount, not a listing price — using it would be an inference C30 forbids) | **Yes** — signed `BIGINT` paise, entered as the seller's current listing price | `KNOWN` once filled; `UNKNOWN` until then |
| `attributes` | none | **Yes** — key/value pairs | `KNOWN` once filled; `UNKNOWN` until then |
| `keywords` | none | **Yes** | `KNOWN` once filled; `UNKNOWN` until then |
| `fulfillment_type` | none | **Yes** — same enum space as competitor `fulfillment_type` | `KNOWN` once filled; `UNKNOWN` until then |
| `review_count` | none | **No — out of the form's scope by decision** | `UNKNOWN`. A seller's own review count is a marketplace-observed number that changes continuously; hand-typing it would produce a stale figure presented as current. See V12 |
| `rating` | none | **No — out of the form's scope by decision** | `UNKNOWN`, same reasoning as `review_count`. See V12 |
| `last_updated` | `sales_line` ingestion timestamps, or the profile's own edit timestamp, whichever is later | implicit | Available |

**Consequence, stated plainly.** With the profile filled, `price_proximity`, `features`, `keywords` and `fulfillment` become scorable and `HIGH` is reachable. With it **empty** — a seller who never fills the form — behaviour is exactly as before C31: those axes score 0, honestly, and nothing is invented. `review_tier` stays `UNKNOWN`/0 either way, capping a candidate's reachable total at 14/16. **Form-completion rate is therefore a product risk, not a correctness risk** (see A10, V12). **D13 is unchanged:** a discovery run is still refused when both `title` and `category` are `UNKNOWN`.

### 5.6 Generalized `Evidence` and `CIHandoff` schema (NEW — C28)

The earlier, narrower handoff typed evidence references as review-snippet ids specifically — a type that only exists for review-mining themes. A price or availability finding traces back to a screenshot extraction record, not a review snippet, so that typing broke the Evidence→Finding→Action chain (§6.20.1) for most finding types. Generalized:

```
Evidence {
  evidence_id:      string
  source_type:      enum        -- SELLER_SCREENSHOT | LICENSED_PROVIDER | REVIEW_SNIPPET
  source_reference: string      -- competitor_evidence.id | provider response ref | ci_evidence_snippet.id
  captured_at:      timestamp
  field:            string      -- e.g. "price", "availability", "review_theme:battery_life"
  extracted_value:  string      -- the extracted value this record supports
  confidence:       enum        -- HIGH | MEDIUM | LOW, assigned per §6.16.1
}

CIHandoff {
  finding_id:   string
  finding_type: enum            -- PRICE_CHANGE | LISTING_GAP | REVIEW_THEME | AVAILABILITY_CHANGE |
                                --  DIFFERENTIATION_OPPORTUNITY | MARKET_POSITION
  validated_fact: [ {
      fact:       string,       -- e.g. "Competitor price = ₹899"
      confidence: enum,         -- HIGH | MEDIUM | LOW, per §6.16.1
      freshness: { captured_at: timestamp, is_stale: boolean }   -- is_stale per the §6.16.2 per-field threshold
  } ]
  evidence_refs:   [ evidence_id ]      -- a REVIEW_SNIPPET-typed record is valid only inside its C27 retention window
  competitor_refs: [ competitor_id ]
  implication:     string
  suggested_action: { target_agent: enum (CFO | CMO), suggested_question: string }
  created_at:      timestamp
  created_by:      "CI"                 -- fixed
}
```

**Relationship to the existing `handoff.py` shape.** `packages/competitor-intelligence/src/competitor_intelligence/handoff.py` currently exposes `CiHandoffSnapshot` — a flat "latest known facts for one competitor" payload (price, availability, `is_stale`, `capture_status`, `confidence`, `source_url`). That is a **different and still-valid object**: it is a *fact* view, whereas `CIHandoff` above is a *finding* view with an implication and a suggested action. V2 adds the finding view; it does **not** delete or rename the fact view, and existing consumers of `CiHandoffSnapshot` are unaffected. Where the two overlap, `Evidence.source_type = SELLER_SCREENSHOT` with `source_reference = competitor_evidence.id` is the bridge.

**Confidence vocabularies — read this carefully, they are two different scales.** §5.1's `VISION_EXTRACTED | SELLER_ENTERED | DERIVED | UNAVAILABLE` describes **who produced a value** and is CI's internal provenance vocabulary; it is unchanged. `Evidence.confidence`'s `HIGH | MEDIUM | LOW` describes **how much to trust an extraction** and is assigned per §6.16.1. They are not interchangeable and neither is derived from the other by a lookup table. A field that cannot be extracted at all has **no** `HIGH/MEDIUM/LOW` value — it is `UNAVAILABLE` in §5.1 terms and `UNKNOWN` in §6.18 terms, which is a **distinct state from `LOW`**: `LOW` means *a value exists, trust it cautiously*; `UNKNOWN` means *no value exists*. Anything crossing into Brain 1 still enters as `DERIVED`, per §5.1, unchanged.

---

### 5.7 V3 data model additions (NEW — C32–C47)

Contract-level; column types and migrations are finalised in the checkpoint that builds each table. **Every table below is tenant-owned: `tenant_id uuid not null`, RLS `FORCE`, no endpoint accepting a client `tenant_id`, background work without tenant context failing closed (§7 rules 9–10, 13).** No existing column changes meaning; additions only.

```sql
-- C46/C47: a stable, tenant-scoped id for anything the dashboard shows as a finding
ci_finding (
  id uuid pk, tenant_id uuid not null,
  product_id text not null,                 -- seller SKU the finding is about
  competitor_url_id uuid,                   -- null for market-level findings
  finding_type text not null,               -- PRICE_CHANGE | AVAILABILITY_CHANGE | REVIEW_THEME | LISTING_GAP | DIFFERENTIATION | MARKET_POSITION | FRESHNESS | DISCOVERY_CANDIDATE
  evidence_refs uuid[] not null,            -- §5.6 Evidence ids; a finding with no evidence_refs is invalid (AC53)
  sample_size int, sample_total int,        -- "N of M sampled" (C45); null where not applicable
  confidence text not null,                 -- §5.6 vocabulary
  freshness text not null,                  -- FRESH | STALE | UNAVAILABLE (§6.16.2)
  seller_confirmation text not null,        -- NOT_REQUIRED | PENDING | CONFIRMED | DECLINED
  engine_result_ref uuid,                   -- Brain 1 citation where a figure is shown
  payload jsonb not null,                   -- derived, display-safe facts only; never raw review text (§7 rules 8, 14)
  created_at timestamptz not null, superseded_by uuid
)

-- C47: append-only audit/history; the Evidence and Changes history reads from here
ci_event (
  id uuid pk, tenant_id uuid not null,
  event_type text not null,                 -- C47 list
  actor text not null,                      -- member uuid as text, or 'SYSTEM'
  agent_run_id uuid, investigation_id uuid, -- the CEO–CI link where one exists
  object_type text, object_id uuid,
  detail jsonb not null default '{}',       -- ids and enums only
  occurred_at timestamptz not null
)  -- no UPDATE or DELETE grant to the application role (AC56)

-- C37/C38: the CI -> CEO -> seller question, and its answer
ci_info_request (
  id uuid pk, tenant_id uuid not null,
  competitor_url_id uuid, evidence_id uuid, snapshot_field_id uuid,
  field_name text not null,
  reason text not null,                     -- LOW_CONFIDENCE | CONSEQUENTIAL_FIELD | MISSING | CONFLICT | IDENTITY_UNCERTAIN | WHICH_COMPETITOR
  consequential boolean not null,
  proposed_value jsonb,                     -- what vision read, if anything
  status text not null,                     -- OPEN | ANSWERED | DECLINED | EXPIRED
  answered_value jsonb, answered_by uuid, answered_at timestamptz,
  created_at timestamptz not null, expires_at timestamptz not null
)

-- C36: duplicate detection and channel provenance, appended to competitor_evidence
-- ALTER competitor_evidence ADD:
--   content_sha256 text, perceptual_hash text,                -- per-tenant duplicate detection (§6.22.2); null on legacy rows
--   intake_channel text not null default 'DASHBOARD_UPLOAD',  -- DASHBOARD_UPLOAD (legacy rows) | CEO_HUB_ATTACHMENT | WHATSAPP (placeholder, never written)
--   quality_status text not null default 'UNCHECKED',         -- ACCEPTED | REJECTED_LOW_QUALITY | REJECTED_NOT_A_LISTING | UNCHECKED
--   duplicate_of uuid                                         -- the earlier evidence this duplicates, if any

-- C43: appended to ci_candidate (carried to the tracked competitor)
-- ALTER ci_candidate ADD: relationship_class text not null default 'UNKNOWN',
--                         relationship_basis jsonb not null default '{}'   -- which identity/axis values drove it (like identity_match_basis)

-- C39: soft removal on the tracked competitor
-- ALTER competitor_url ADD: removed_at timestamptz, removed_by uuid, removal_reason text   -- status gains REMOVED

-- C42: appended to ci_tenant_config
-- quiet_hours_start time, quiet_hours_end time, quiet_hours_tz text,   -- all null = no quiet hours
-- alert_dedup_window_hours int not null default 24,
-- review_finding_min_sample int not null default 10                      -- provisional (Q22)

ci_alert_state (                            -- dedup memory (§6.26.1)
  tenant_id uuid not null, competitor_url_id uuid not null,
  finding_type text not null, direction text not null,
  last_alerted_value_paise bigint, last_alerted_snapshot_id uuid,
  last_alerted_at timestamptz not null,
  primary key (tenant_id, competitor_url_id, finding_type, direction)
)
ci_held_alert (                             -- quiet-hours queue (§6.26.2): held, never dropped
  id uuid pk, tenant_id uuid not null, finding_id uuid not null,
  hold_until timestamptz not null, delivered_at timestamptz
)
```

`finding_id` is `ci_finding.id`. The existing `CIHandoff`/`Evidence` shapes (§5.6) are reused unchanged; `ci_finding` is the persisted, dashboard-addressable form of a `validated_fact` set.

---

## 6. Core rules

### 6.1 URL intake and evidence submission — REVISED for the evidence model

**URL intake (reference-only, C2–C4):**
1. Seller submits a competitor URL; CI validates its host against the OP2(a) allowlist server-side, **now a labeling/format check, not a fetch gate (C4, D7)**. Non-allowlisted hosts are refused, naming the reason.
2. Marketplace is derived from the host, never asked.
3. Saved-URL count is checked against entitlement before insert.
4. A URL is stored **and is never fetched, at intake or at any later point.** It exists so a human can be pointed back to "go check this listing."

**Evidence submission (new — C2, §5.3):**
5. The seller opens a `competitor_url` and uploads one or more screenshots as a single **research session** (`research_session_id`, §5.3). Each screenshot is stored as `competitor_evidence` (§5).
6. Each screenshot is queued for vision extraction independently. When every screenshot in the session has reached a terminal `extraction_status` (`EXTRACTED` or `EXTRACTION_FAILED`), the merge in §5.3 runs and produces exactly one `competitor_snapshot` for that research session.
7. Any field extraction misses or that conflicts across screenshots (§5.3 rule 3) is exposed to the seller for manual entry/resolution before the snapshot is treated as `COMPLETE`.
8. Run/evidence-submission volume is checked against entitlement (runs/month, §1 C13) before the session is accepted, on the same terms saved-URL count is checked at intake.

**V3 amendment (C32, C36).** Rules 5–8 above describe *what* happens to a submission; **V3 changes *how a seller submits it*.** The seller no longer opens a competitor row on a dashboard and uploads there. The seller attaches the screenshot(s) in the **CEO Hub chat**; the CEO runs the fixed intake pipeline of §6.22, and a CEO-asked confirmation (§6.23) replaces the dashboard "manual entry/resolution" of rule 7. Rule 1's URL intake is likewise conversational (§6.24: the seller states the URL in chat). Entitlement checks (rules 3 and 8) are unchanged.

### 6.2 Capture run — REVISED for the evidence model

1. Triggered only by an evidence submission (`EVIDENCE_UPLOAD`, §5), a CEO request, or a WhatsApp confirmation. **Never on a schedule** (C2). `DIRECT_UI` is defined in the trigger enum (§5) but not wired to any path in this pass.
2. All checks in §6.4 pass before queuing.
3. Runs execute as background jobs with tenant context set from the job payload, or fail closed.
4. Each research session yields exactly one `competitor_snapshot` — `capture_status` (`COMPLETE | PARTIAL | PENDING_MANUAL_ENTRY`, §5.3) records the merge outcome so the series has no silent gaps, even when extraction fails on every screenshot.
5. Bounded; a run never expands beyond the evidence it was given. Rate limiting on this path governs upload/extraction volume, not outbound requests — there are none.

### 6.3 Change detection — REVISED for the evidence model
1. On each new snapshot, compare against the most recent prior `COMPLETE` (or `PARTIAL`, for fields it does have) snapshot for the same `competitor_url_id` and `variant_key`.
2. Compute `delta_pct` on effective selling price (listed price less visible discount). **This is a delta over CI's own recorded facts, permitted by the arithmetic boundary stated in the front matter — it is not a financial calculation.**
3. `threshold_breached` when `|delta_pct| >= ` the resolved threshold — the per-URL override at `competitor_url.price_threshold_pct_override` if set, else `ci_tenant_config.price_threshold_pct` (D2, closes Q5) — **or** availability transitions, subject to the resolved per-URL/tenant availability-alert setting (D3).
4. `alert_eligible = false` if either snapshot is `PENDING_MANUAL_ENTRY` for the compared field, or if either exceeds the OP3 freshness ceiling (§6.8).
5. **No prior snapshot means no event.** A first observation is a baseline, never a change.

### 6.4 Execution paths and enforcement (C20 / B7) — trigger updated for the evidence model

CI has two entry paths. Both enforce the same checks; they differ only in whether a CEO call is consumed.

| Path | Trigger | CEO call consumed |
|---|---|---|
| **Direct CI execution** | `EVIDENCE_UPLOAD` — dashboard screenshot submission (§5, §6.1) | **No** |
| **CEO conversational route** | `CEO_REQUEST` | Yes |
| **WhatsApp-confirmed** | `WHATSAPP_CONFIRM` | **Not decided here** — credit and cap treatment belongs to `whatsapp-integration.md` (§6.9) |
| **CEO Hub upload (V3)** | `CEO_HUB_UPLOAD` — screenshot attached in the CEO Hub chat (C36, §6.22). Replaces the dashboard `EVIDENCE_UPLOAD` button as the seller's route; `EVIDENCE_UPLOAD` is retained only as the stored trigger value on legacy rows. | Per **Q19** (recommendation: the turn is a CEO turn as any other, and the intake is metered as one CI run unit) |

Every CI execution, on every path, enters the **full `auth.md` §7.1 six-step chain** — authentication, membership, active status, role, permission (`agent.ci`), and resource tenant ownership. CI restates nothing; it defers to that chain in full.

On top of the chain, every execution additionally enforces:

| # | Check |
|---|---|
| 1 | CI entitlement / credit availability (`auth.md` §7.2 — a separate gate from permission) |
| 2 | Rate limiting |
| 3 | Audit logging (MN9 — event set not yet specified; see Q9) |

**`agent.ceo` is required only on the conversational route.** A direct CI execution needs `agent.ci` alone, because it never reaches CEO and there is no routing decision to make. This matches the amended `auth.md` §5.2 and R2, which now define direct execution paths explicitly. The CI capture action is a **registered direct execution path**: one named action, one required key (`agent.ci`), no free-form input.

### 6.5 Review insight acquisition and text handling — screenshot-based, transient, local-only (C5–C7, C14, C15, resolves Q11)

**RESOLVED (was flagged as Q11, §12).** Review/customer-feedback insight acquisition is **screenshot-based, on the identical evidence model as everything else in this pivot** — not a new mechanism, and not a live fetch of any kind.

**Acquisition:**

1. The seller submits a screenshot of the competitor's reviews tab/page through the **same `competitor_evidence` upload mechanism** already specified for price/listing evidence (§5, §5.3, §6.1). It is stored as one more `competitor_evidence` row, tagged to the same `competitor_url_id` and grouped into a `research_session_id` (§5.3) exactly like a listing screenshot — there is no separate upload path, trigger, or table for review evidence.
2. A vision/derivation model extracts what is **visible in that screenshot** — sentiment cues, recurring complaint and positive themes, and the rating distribution as shown on the page (e.g. the star-count breakdown bar, where the screenshot captures it) — using the same `VISION_EXTRACTED` confidence tier defined for listing extraction (§5.1). It derives nothing beyond what is legible in the image.
3. **The same manual-entry fallback pattern as the rest of the pivot applies.** Where extraction cannot resolve a field — the rating-distribution bar is cropped, sentiment is ambiguous from what's visible, or extraction fails outright — the seller may supply it directly (`SELLER_ENTERED`), on the same terms as §5.3 rule 4.
4. Multiple reviews-tab screenshots submitted in one research session merge under the **identical §5.3 rules**, including the conflict rule (rule 3): if two screenshots disagree on, say, the visible rating distribution, that field is `UNAVAILABLE`/`conflict = true` pending manual resolution — never silently picked.
5. **This is not a new acquisition mechanism.** It is C2's evidence-upload model applied to a reviews-tab screenshot instead of a listing-page screenshot; every rule already specified in §5.3 and §6.1 governs it without modification. `ci_capture_run.trigger = EVIDENCE_UPLOAD` covers this submission on the same terms as a listing-evidence submission.

**Never persisted, and never transmitted — the canonical surface list (M3):**

| Surface | Rule |
|---|---|
| PostgreSQL | No raw-text column exists on any table |
| Object storage / files | Never written to disk |
| Application logs | Excluded from every log statement |
| Exception traces | Scrubbed before a trace leaves the process |
| Debug output | Never included, including in development builds |
| Observability / APM | Excluded from spans, breadcrumbs and payload capture |
| Redis cache | Never cached |
| Vector store | **No review-text embeddings.** No corpus |
| Generated reports | No full reviews, no long quotations |
| **Hosted model providers** | **Never transmitted** (C15). Local processing only |

**Persisted output** is limited to `competitor_review_insight` (§5): sentiment split, positive themes, complaint categories, rating distribution, summarised patterns, review count, `source_url` (the competitor listing this evidence is about — reference-only, never a URL Metrion visited), `fetched_at` (when the seller captured/uploaded the reviews-tab screenshot(s) this insight was derived from — not a fetch time), `derived_at`, confidence, derivation method and insight state.

**Degraded path.** Where local processing is unavailable, or the submitted screenshot cannot be usefully processed (illegible, wrong page, cropped past recovery), CI returns `insight_state = DEGRADED` (or `UNAVAILABLE`) built from structured metadata already captured — rating, rating count, distribution, availability — with `degraded_reason` recorded. It never persists raw review expression extracted from the screenshot, and never sends the screenshot or its extracted text to a hosted provider, as a workaround.

**Images.** The reviews-tab screenshot itself is retained under the standard `competitor_evidence` image retention policy (§6.8) — the same policy as any other evidence image, not a special or earlier purge — because it is the seller's own submitted evidence, on the same terms as C16's carve-out for listing screenshots. What is never rehosted is anything **beyond** what the seller captured: Metrion does not fetch, hotlink or reproduce marketplace review-page images the seller did not themselves submit. Per the locked wording (M6), where a thumbnail of the seller's own submitted evidence is shown back to them it is permitted; otherwise source links or placeholders.

**Enforcement is structural.** Raw text extracted from the screenshot lives in one bounded processing scope that emits only derived structure. Because derivation is local (C15), that boundary is also the process boundary — nothing downstream, and no external service, can observe the text. The screenshot's stored image bytes (§6.8) sit outside this concern entirely — they are ordinary evidence storage, not raw expression in flight.

**Model output boundary (MN8).** Where `derivation_method = LOCAL_MODEL`, the model performs **classification only** — it labels each review visible in the screenshot with a sentiment class and theme tags. **Deterministic code then aggregates** those labels into `sentiment_split` proportions, theme weights and the rating distribution. The model never emits a proportion, a weight or a count. This keeps the locked rule intact — models classify, code computes — and makes the numbers reproducible from the same labels.

### 6.6 Listing copy handling (C16 / M5) — REVISED for the evidence-carve-out

Competitor listing copy remains **expression**, not fact, when it would have to be scraped or copied off a live page — but under this model nothing is ever scraped or copied off a live page, so that concern no longer arises in its original form.

**Still never persisted:** any title, description or bullet text obtained by Metrion visiting or copying a competitor page — there is no such path any more, so this is now a structural impossibility rather than a rule CI must actively enforce.

**Now permitted, under C16's carve-out (§1, §5):** title, description and bullet text **the seller submitted themselves**, as vision-extracted or manually-entered structured fields on `competitor_snapshot` (`title`, `description`, `bullets`, §5). This is the seller's own evidence, not Metrion's derivation of someone else's expression.

**Persisted derived attributes, unchanged** (`competitor_listing_insight`, §5): keyword themes · title structure and length · feature categories · benefit-term patterns · differentiation opportunities · bullet count · image count — plus source URL, confidence and provenance, computed **from the seller-submitted title/description/bullets now stored under the C16 carve-out**, rather than from raw text fetched and held only transiently.

Derivation is local-only, on the same terms as §6.5. Where the seller wants *generated* copy, CEO routes to CMO. **CI never calls CMO** (C11).

**Ownership boundary with CMO (MN12).** CI derives what a *competitor's* listing does — themes present, structure used, gaps observed. CMO produces what the *seller's* listing should say. `differentiation_opportunities` is an observation about the competitive field, not drafted copy; the moment output becomes text for the seller to publish, it is CMO's and routes through CEO.

### 6.7 Estimated margin range (C17 / B1)

**Deferred — see §1a.** This whole subsection describes design intent, not a build target for the next pass: it depends on the Brain-1 interface in §5.2, which does not yet exist and requires its own `deterministic-engine.md` extension spec before CI can call it.

1. CI assembles a `CompetitorObservationSet` (§5.2) from observed facts only.
2. CI calls Brain 1. **CI performs no part of the calculation** and holds no rates — Brain 1 resolves fee references itself (C18).
3. Brain 1 returns a range with its basis, assumptions and engine metadata.
4. CI renders it unchanged, always labelled **"estimated margin range"**, with the snapshot timestamp and the stated assumptions.
5. CI never emits a single-point competitor margin (C10). Where fee data is unavailable, the range widens and the assumption is stated explicitly rather than the figure being suppressed.
6. **Reproducibility is surfaced, not hidden (MN10).** Per `deterministic-engine.md` §5.13, an estimate is reproducible only for a fixed observation set, not across re-captures. Every rendering states the observation it was computed from (`source_url`, `fetched_at`) so a changed figure is explained by a new capture rather than appearing unstable.
7. **The estimate is never written to `metric_result`** (engine §5.13 rule 5). It carries its own provenance contract — an **`estimate_ref`** (`competitor_estimate.id`, engine §9.1) — which is what a consumer cites when displaying it. An estimate never carries an `engine_result_ref`. Re-rendering an old snapshot recomputes at the current `fee_reference_version`, stamped on the output.

### 6.8 Freshness and retention (C19 / B2 / B6) — REVISED for the evidence model

**Freshness (OP3, locked — reframed).** "Stale" no longer means "our cached scrape is stale"; it means **"this evidence is old, ask the seller to refresh it."** The mechanism changes; the never-mislead policy does not:

| Evidence/snapshot age | Behaviour |
|---|---|
| ≤ 7 days since the newest evidence in the snapshot's research session | Served, with a visible age stamp |
| > 7 days | **Reported unavailable.** Not displayed with a stamp, never used in an alert. The seller is prompted (`staleness_reminder_days`, §5, default 14) to submit fresh evidence for that URL |

**Retention (C19):** two separate policies, since a snapshot's *data* and a screenshot's *bytes* have different retention needs:

- `competitor_snapshot`, `competitor_snapshot_field` and their derived insights: configurable per tenant via `ci_tenant_config.snapshot_retention_days`, **default 90 days**, unchanged from before.
- **Raw screenshot image bytes (`competitor_evidence.image_ref`) — NEW, judgment call:** retained only up to `ci_tenant_config.raw_evidence_image_retention_days` (default 90, ≤ `snapshot_retention_days`), after which the image bytes are purged and `competitor_evidence.image_retained_until` marks when this happened. The `competitor_evidence` row itself — pointer, `uploaded_at`, `competitor_url_id`, `tenant_id`, `extraction_status` — survives past that point as provenance for the fields it produced, same as a purged `competitor_snapshot` leaves its derived insights behind (below). Rationale: a screenshot can incidentally capture more than the listing (browser chrome, other open tabs, unrelated content); minimizing how long raw images are kept limits that exposure while the actual product data (already extracted into `competitor_snapshot_field`) persists on the normal snapshot policy.

- **OP3's 7-day ceiling governs the *current answer* for a URL, not the historical series.** A trend chart may render snapshots older than 7 days, each with its own capture date; what it may not do is present a >7-day-old snapshot as the current state, or alert on one.
- Keep the latest successful snapshots required for comparison and trend display.
- Extraction-failure/`PENDING_MANUAL_ENTRY` status metadata is retained only for the limited period needed to explain a gap.
- Minimal provenance is preserved for snapshots referenced by an existing report or investigation, subject to the policy.
- **Retention must never be presented as monitoring.** CI is on-demand; a 90-day history is a record of evidence the seller submitted, not a watch.

Revisit after DPDP and legal review (`auth.md` Q9). **The legal-risk review that motivated this whole pivot (V6, below) does not eliminate this DPDP note** — retaining seller-uploaded images and extracted competitor data still has its own, separate privacy/retention profile.

### 6.9 WhatsApp

`whatsapp-integration.md` now exists and owns every WhatsApp decision. **CI still decides no WhatsApp behaviour of its own** — this section only restates what that spec resolves, plus what remains genuinely open there.

| Fact | Source |
|---|---|
| One WhatsApp Business destination per tenant | `auth.md` W1 |
| Explicit verification and opt-in required | `auth.md` W4, W5 |
| Inbound messages resolve to the verified tenant, and to exactly one member (`bound_by`, always the OWNER in V1) | `auth.md` W6; `whatsapp-integration.md` C8/§6.7 |
| Partner permissions cannot be bypassed through WhatsApp | `auth.md` W11; `whatsapp-integration.md` §6.7 (holds trivially — no partner identity is ever resolved through the channel) |
| A `CONFIRM` reply to a `PRICE_CHANGE` alert re-enters CI's own full authorization chain (`auth.md` §7.1) — WhatsApp confirmation supplies intent, not authorization | `whatsapp-integration.md` §6.4, §8.2 |
| A `WHATSAPP_CONFIRM`-triggered run with no `ACTIVE` investigation for the tenant implicitly opens one before the run's result is processed | `whatsapp-integration.md` C7/§6.5; `ceo-agent-orchestration.md` §6.7 |

**Still deliberately not decided here** (M8/M9/M10 reverted, narrowed to what `whatsapp-integration.md` itself leaves open): credit and cap treatment for WhatsApp-triggered runs · behaviour at cap mid-thread · alert channel when a seller declines WhatsApp · what happens when a WhatsApp-confirmed run completes. All belong to `whatsapp-integration.md` and readiness 2.12, 2.16, 2A.7 — see its own §13 Q3 for the billing-cap piece.

A `WHATSAPP_CONFIRM` trigger is recognised by §6.2 and enforced by §6.4; everything in the "still not decided" list above is pending in `whatsapp-integration.md` itself, not a CI gap.

**V3 amendment (C36).** WhatsApp remains a **placeholder** for CI: the shared `EvidenceIntakeChannel` interface (§6.22.4) carries a `WHATSAPP` value that accepts nothing and returns `CHANNEL_NOT_AVAILABLE`. Everything above stays the record of what `whatsapp-integration.md` resolves; CI adds no WhatsApp behaviour.

### 6.10 Discovery pipeline and the discovery/intelligence boundary (NEW — C21–C23)

Given a `SellerProduct` baseline (§5.5), CI generates research queries and surfaces candidate competitors, **replacing manual-URL-only entry as the default path while keeping manual URL entry as a permanent, always-available fallback** (C21). Query generation covers six kinds: product terms, category terms, feature terms, customer-intent phrases, alternative/substitute terms, and market/keyword terms (`ci_search_query.query_kind`, §5.4).

#### 6.10.1 Provider record — required before any named provider (C22)

Before a provider is selected, a record is produced **for each candidate provider**, answering:

| Field | Question it answers |
|---|---|
| Provider name | — |
| Allowed use | Does the ToS explicitly permit **storing and redisplaying** results inside a commercial SaaS product, to end customers? |
| Data retention | How long may Metrion retain returned data — indefinitely, or time-boxed? |
| Redistribution / display rights | May extracted fields (price, title) be shown to sellers as part of a paid product? |
| Attribution | Does display require crediting the source? |
| Region | Any geographic restriction (matters for India-focused sellers)? |
| Query limits | Rate limits and volume caps at the plan tier under consideration |
| Cost | Cost at the query volume in §6.12.1 |

**Process:** fill the record for **at least two** candidates (a first-party search API and a third-party wrapper). Confirm "allowed use" and "redistribution" against the provider's **current terms directly** — not from memory, not from reputation. Only then select, and lock the choice. Re-verify if terms change materially.

**Build order, binding on implementation (C22):**

1. Domain models (§5.4 entities, §5.6 `Evidence`/`CIHandoff`)
2. The `SearchProvider` interface
3. `MockSearchProvider` — a stub returning fixture data
4. The whole discovery pipeline (§6.10–§6.15) against the interface, using the mock
5. Complete the provider record (above) for ≥2 real candidates
6. **Human approval of a provider — outside an implementation agent's authority**
7. Implement the real adapter behind the existing interface
8. Integration tests against the real adapter

**Steps 1–4 do not depend on 5–8 and must not be blocked waiting on them.** Switching providers later is a configuration change, never a rewrite. If a candidate provider's terms require retaining query text beyond what Metrion is comfortable with, that **counts against selecting them** (§6.11).

#### 6.10.1a Provider record — Tavily (completed 2026-10-18, CP1; owner-approved provider, C34)

Filled from Tavily's **current published terms (last updated 4 May 2026, `tavily.com/terms`) and credits documentation (`docs.tavily.com`)**, read on 2026-10-18 — not from memory. **This is an engineering reading of public text, not legal advice.** Per §6.10.1, any field the terms do not clearly answer is recorded `UNKNOWN` and treated as **not permitted** until a human resolves it.

| Field | Finding | Status |
|---|---|---|
| Provider name | Tavily (search API) | — |
| Allowed use | Integrating the service into a customer application that serves third-party end users is permitted (terms §§2, 3.2, 3.5). Use is described as for **internal business purposes**. The terms **do not explicitly address redisplaying search outputs to end customers** inside a paid product | **`UNKNOWN` — human/legal decision (V16)** |
| Data retention (Metrion's side) | **Not stated** — no limit on how long a customer may keep returned results | `UNKNOWN`; Metrion's own bound is `search_cache_ttl_hours` (24 h) for reuse and the §6.8 snapshot retention for anything else; lead rows are never promoted to evidence (C35) |
| Data retention (Tavily's side) | **Concern.** Tavily may store and use *customer input* (the query text) and outputs, **including for model training** (terms §§6.5, 9.2); no retention period is given. Under §6.11 ("terms require retaining query text beyond what Metrion is comfortable with count against selecting the provider") this is an **owner decision**, mitigated but not removed by the §6.11 privacy filter, which already keeps SKU ids, costs and tenant identifiers out of every query | **Owner/legal decision (V16)** |
| Redistribution / display rights | Not explicitly stated (see Allowed use). Until resolved, the product shows only a lead's title, snippet and URL, labelled unverified (C35, §6.28.3), and never redistributes provider data outside the seller's own tenant | `UNKNOWN` — conservative display only |
| Attribution | Not stated | `UNKNOWN`; none implemented |
| Region | No India restriction. Access is barred for users in embargoed or sanctioned countries/regions and for sanctioned persons (terms §17.1) | No restriction for the target market |
| Competing / derivative use | Customers may not build a competing product, reverse-engineer, create derivative works of the service, or train competing models on outputs (terms §§3.2, 6.6). Reasonable API use is allowed. CI uses the documented API only and does not train models on outputs | Compatible as designed |
| Query limits | Rate limits per plan **not stated** in the credits documentation read. CI applies its own caps: `max_discovery_queries_per_run` (20), per-tenant `CI_TAVILY_DAILY_QUERY_CAP` (default 100 / rolling 24 h), 24 h per-tenant result cache | Provider limits `UNKNOWN`; CI caps in force |
| Cost | **1 credit per basic search**; free tier **1,000 credits/month, no card**; pay-as-you-go **$0.008 per credit** once the plan limit is reached. A full discovery run is at most 20 queries = **20 credits (~$0.16)**; the free tier is therefore about **50 full runs a month, and it is shared with PI** (same key) | Known; the per-tenant monthly ceiling is a commercial decision (V16) |

**Consequence for build and launch.** The adapter ships (C34) and is safe to run in development because it returns only unverified leads. **Launch of discovery to real sellers is gated on V16:** a human decision on (a) redisplay of Tavily outputs to paying sellers, (b) Tavily retaining and training on Metrion's search text, and (c) the per-tenant monthly cost ceiling. The two-provider comparison C22 required is waived by the owner; the `SearchProvider` interface keeps a second provider swappable if (a) or (b) fails.

#### 6.10.2 Acquisition matrix — what discovery can and cannot produce (C23)

| Data field | Discovery search / snippet | Seller screenshot | Licensed provider (if added) |
|---|---|---|---|
| Product title | **Lead only** — confirm via evidence | Authoritative | Authoritative |
| Price | **Lead only — never shown as fact** | Authoritative | Authoritative |
| Availability | Lead only, often absent | Authoritative | Authoritative |
| Rating | Lead only, often absent | Authoritative | Authoritative |
| Review count | Rarely present in snippet | Authoritative | Authoritative |
| Review text / themes | **Not available from search** | Authoritative (§6.18.2) | Authoritative |
| Description / bullets | Rarely present in snippet | Authoritative | Authoritative |
| Listing-change history | **Not available from search** | Over time, via repeated uploads | Authoritative |

#### 6.10.3 Consequence for the pipeline — hard rule

1. A candidate that has passed discovery, identity resolution and relevance scoring is still an **unevidenced candidate** until the seller uploads evidence for it, or a licensed provider is integrated.
2. Comparison (§6.19), customer-voice mining (§6.18.2) and alerts (§6.17) operate **only** on candidates with `evidence_status = EVIDENCE_BACKED`.
3. A candidate with discovery data alone is shown as **"Approved — awaiting evidence"** — a distinct, visible state (`ci_candidate.evidence_status = AWAITING_EVIDENCE`) — and is **never silently compared, mined or alerted on as if evidence existed.**
4. `ci_search_result.result_title` and `.result_snippet` are stored as leads. They may seed identity resolution and provisional relevance scoring. They may **never** be rendered to a seller as a competitor fact, written into a `competitor_snapshot` field, or used as an `Evidence` record backing a `CIHandoff` finding.

### 6.11 Query privacy boundary — locked policy (NEW)

**Permitted in an externally-sent query:**

- Generic product name / product type
- Generic category
- Non-sensitive product attributes (colour, size class, generic material)
- Generic customer-intent terms (e.g. "budget", "wireless", "for gaming")
- Public-facing keywords **already used in the seller's own public listing**

**Never sent externally, under any circumstance:**

- Internal SKU codes or internal product IDs
- Supplier / sourcing information
- Margin, COGS, or any cost data
- Private sales volume or ad-spend data
- Proprietary positioning language not already public in the seller's listing
- Any other confidential business information

**Additional rules:**

1. **Automated discovery is opt-out capable.** A seller may disable it entirely and use manual URL entry only, at any time (`ci_tenant_config.discovery_enabled`, D11). The flag is checked **before any query is composed or sent**, never as a post-hoc filter on results.
2. The filter is **allow-list-shaped, server-side, and applied to the composed query text**, not to the inputs alone — a query assembled from permitted parts can still leak if a free-text field is concatenated in unchecked.
3. **A query that cannot be composed within the permitted list is not sent.** It is dropped with a recorded reason. CI never sends a "best effort" query containing a borderline term.
4. `ci_search_query.query_text` stores **the post-redaction text actually sent** — never a pre-redaction draft. Storing the draft would put the forbidden content into Metrion's own database, defeating the boundary.
5. **Query and discovered-candidate records are tenant-isolated in storage.** No cross-tenant visibility, consistent with existing RLS. This explicitly includes the 24h search cache (§6.12.1): **the cache is never shared across tenants even for an identical query string**, because doing so would reveal one tenant's research interest to another and would let a cross-tenant read escape the RLS boundary.
6. **Provider-side query retention is governed by the provider record** (§6.10.1). A provider whose terms require retaining query text beyond Metrion's comfort counts against selection.

### 6.12 Query/cost budget and the research job state machine (NEW)

#### 6.12.1 Locked budget defaults — configuration, never hardcoded

| Parameter | Default | Config column (§5.4) |
|---|---|---|
| Max discovery queries per run | 20 | `max_discovery_queries_per_run` |
| Max initial (raw) candidates returned from search | 50 | `max_raw_candidates` |
| Max candidates carried into identity resolution + relevance scoring ("analyzed") | 20 | `max_analyzed_candidates` |
| Max candidates in the "Recommended" set | 5 | `max_recommended_candidates` |
| Max secondary/follow-up searches per candidate | 3 | `max_followup_searches_per_candidate` |
| Discovery run timeout | 2 minutes | `discovery_run_timeout_seconds` |
| Search-result cache duration | 24 hours | `search_cache_ttl_hours` |

**If a run hits any limit before completing discovery, it ends `PARTIAL` with an explicit note of which limit was hit** (`ci_discovery_run.partial_reason`) — **never a silently truncated result presented as complete.** This is the same "don't guess, surface it" rule that governs §5.3's merge conflicts.

#### 6.12.2 Research job state machine

A discovery run takes real time and must never appear frozen to the seller.

```
QUEUED → SEARCHING → DISCOVERING → WAITING_FOR_REVIEW → RESEARCHING → COMPLETE
                                                            ↘ FAILED
                                                            ↘ PARTIAL
                                                            ↘ STALE
```

| State | Meaning |
|---|---|
| `QUEUED` | Accepted, entitlement and §6.4 checks passed, not yet started |
| `SEARCHING` | Queries composed (post-§6.11 filter) and sent to the `SearchProvider` |
| `DISCOVERING` | Raw results resolved into candidates; identity resolution and relevance scoring run on the analyzed subset |
| `WAITING_FOR_REVIEW` | Candidates presented; awaiting seller accept/reject/promote decisions (§6.15). **The pipeline waits here only for `UNCERTAIN` candidates** — `EXACT_MATCH` and `LIKELY_VARIANT` proceed without blocking (§6.13.2) |
| `RESEARCHING` | Approved candidates being set up for tracking / awaiting evidence |
| `COMPLETE` | Run finished within budget with no unexplained gap |
| `PARTIAL` | Hit a budget limit or a provider error partway through; `partial_reason` required (§6.12.1) |
| `FAILED` | Could not produce a usable result at all; `failed_reason` required |
| `STALE` | See the locked rule below |

**Locked run-level `STALE` rule.** §6.16.2 defines freshness *per field*, but a run holds many fields with different thresholds, so "the run's evidence aged past the threshold" would otherwise be ambiguous — one stale price field cannot by itself decide the status of a whole run.

> A `COMPLETE` run transitions to `STALE` when **any fact currently used by that run's active findings** — the specific facts feeding its Competitive Brief (§6.20.2) or an open alert (§6.17) — has crossed **its own field-specific freshness threshold** (§6.16.2). A single stale field **does not invalidate the run's other, still-fresh findings**: each finding independently carries its own `is_stale` flag (§5.6). The run as a whole is marked `STALE` purely as a signal that re-running discovery/evidence collection is due. **A run with zero active findings referencing stale facts remains `COMPLETE`.**

### 6.13 Product/entity identity resolution (NEW — C24)

#### 6.13.1 Required pipeline stage

```
Candidate found → Product identity resolution → Match confidence → Gating rule (6.13.2) → Relevance scoring
```

Relevance scoring **presumes** a candidate is the competitor's actual product. It is not, by default: a result titled *"Wireless Mouse Pro — ₹999"* could be a different variant, a different brand with similar wording, a bundle, a different pack size, a sponsored/irrelevant result, or a discontinued listing.

Identity resolution extracts **brand, model/variant, pack size and bundle status** from the candidate and compares them against the seller's product record (§5.5). **Match confidence is reported as its own explicit field** — `EXACT_MATCH` | `LIKELY_VARIANT` | `UNCERTAIN` | `NOT_A_MATCH` — **never silently assumed to be exact.** `ci_candidate.identity_match_basis` records which attributes drove the judgement and is required whenever `identity_match` is set.

#### 6.13.2 Gating rule — tuned for friction — REVISED V3 by C43 / §6.27.2: `NOT_A_MATCH` is no longer auto-rejected

Requiring seller confirmation for *anything* below `EXACT_MATCH` would turn every run with ambiguous candidates into a confirmation marathon, defeating the automatic-CI experience discovery exists to deliver.

| Match confidence | Behaviour |
|---|---|
| `EXACT_MATCH` | Automatically eligible — proceeds to relevance scoring without a stop |
| `LIKELY_VARIANT` | Automatically eligible and proceeds, but is **visibly marked everywhere it appears** (e.g. *"may be a 2-pack, not the single unit you sell"*). The seller may approve or reject at any time; **the pipeline does not block waiting for that decision** |
| `UNCERTAIN` | **Blocked** — seller approval required before proceeding (`WAITING_FOR_REVIEW`) |
| `NOT_A_MATCH` | Rejected automatically; not shown in the recommended flow (still visible in the raw tier, §6.15) |

**The ambiguity travels with the data, not just with a UI badge on the candidate card.** Any comparison field (§6.19) derived from a `LIKELY_VARIANT` candidate carries the same visible caveat as the candidate itself, including inside a `CIHandoff` payload.

#### 6.13.3 Entity model

Five entities, conflated in casual usage, distinct in the data model, and each mattering for historical tracking:

- **Brand** — e.g. "XYZ"
- **Seller** — e.g. "ABC Traders", the account operating under a brand
- **Product** — e.g. "Wireless Mouse Pro", the underlying item
- **Listing** — the specific marketplace listing for that product; one product may have several, across marketplaces or variants
- **Competitor** — a **resolved, seller-approved relationship** between the seller's product and another party's product/listing

Note the last: *Competitor* is not a thing discovery finds. It is a relationship a seller approves. `ci_candidate.seller_decision` is that approval and is never system-written (§5.4).

### 6.14 Relevance scoring — locked algorithm (NEW — C25)

#### 6.14.0 Discovery relevance is provisional until evidence exists

Scoring runs on discovery-stage data — candidate title, snippet, extracted attributes — which §6.10.2 states is **leads only**. Scoring a candidate before evidence exists is valid and useful (it drives the Recommended set), but the result must never be presented with the confidence of a post-evidence finding.

> **Every relevance score computed before a candidate has an evidence source is labelled `Discovery relevance (provisional)`, never a bare band** (`ci_candidate_relevance.is_provisional = true`).

Once evidence arrives, the candidate becomes evidence-backed and comparison/mining may proceed. **The score itself is not necessarily recalculated at that point — only its label changes**, from provisional to confirmed — *unless* the new evidence contradicts a discovery-stage assumption, in which case it is recalculated under §6.14.3 and the prior row is retained via `recalculated_from`.

Rendering, before and after:

```
"Discovery relevance (provisional): HIGH (12/16) — Evidence status: Approved, awaiting evidence"
"Relevance: HIGH (12/16) — Evidence status: Evidence-backed"
```

#### 6.14.1 Per-axis calculation method — eight axes

| Axis | Method |
|---|---|
| Product similarity | Deterministic text/attribute similarity (category, model attributes), **plus** LLM judgement where structured attributes are insufficient. **The LLM output must cite which attributes drove the judgement** |
| Category similarity | Deterministic — category taxonomy match |
| Customer/use-case similarity | LLM-derived from product description and customer-intent query terms; **must state its reasoning** |
| Price proximity | Deterministic — numeric % difference from the **seller's own price** (see §6.14.6 on naming) |
| Feature overlap | Deterministic where structured attributes exist; LLM-assisted extraction from listing text otherwise |
| Keyword overlap | Deterministic — set intersection of extracted keyword sets |
| Fulfillment type | Deterministic where the source exposes it explicitly; otherwise `UNKNOWN` — **never inferred** |
| Review-volume tier | Deterministic — bucketed from extracted review count when available; otherwise `UNKNOWN` |

The LLM's role on the three LLM-touched axes is **judgement with cited reasoning, over facts CI already holds**. It never originates a marketplace fact, and it never produces the band or the total — **deterministic code sums the axes and assigns the band**, on the same "models classify, code computes" rule already locked at §6.5's model-output boundary.

#### 6.14.2 Missing-data rule — hard requirement, including seller-side unknowns

1. **Any axis without a directly observed value is `UNKNOWN` — never inferred, never silently defaulted.**
2. **If sources disagree on a value it is `CONFLICTED`, with both values shown** — never silently resolved to one. (Same rule as §5.3 rule 3, applied to a different stage.)
3. **Seller value `UNKNOWN` + competitor value known → the comparison itself is `UNKNOWN`, scoring 0.** The system **never invents or assumes a seller baseline** in order to produce a comparison.
4. A finding must never present *"Fulfillment: Seller-fulfilled"* when that was a model guess rather than an extracted fact — **for either side**.

`ci_candidate_relevance.axis_states` records `KNOWN`/`UNKNOWN`/`CONFLICTED` per axis separately from `axis_scores`, because *"scored 0 because it genuinely doesn't match"* and *"scored 0 because we don't know"* are different facts and must render differently.

#### 6.14.3 Relevance bands — locked

**Step 1 — score each of the eight axes 0, 1 or 2:**

| Score | Condition |
|---|---|
| **2** (strong) | Category: exact match · Product: same product line/model family · Price proximity: within **15%** of seller's price · Feature/keyword overlap: **≥60%** shared · Fulfillment / review-tier: matches seller's tier (only when the seller's own value is `KNOWN`, per §6.14.2 rule 3) |
| **1** (partial) | Category: parent-category match only · Product: same product type, different line · Price proximity: within **40%** · Feature/keyword overlap: **25–59%** shared · Fulfillment / review-tier: adjacent tier |
| **0** (weak / none) | Anything below the `1` threshold, **and every `UNKNOWN` or `CONFLICTED` axis** — never guessed into a higher score, including the seller-side-unknown case |

**Step 2 — sum the eight axis scores (max 16) and band:**

| Band | Condition |
|---|---|
| `HIGH` | total **≥ 11**, **AND** category similarity and product similarity **both scored ≥ 1** — a candidate cannot reach `HIGH` on price/keyword overlap alone if it isn't even the same kind of product |
| `MEDIUM` | total **6–10** |
| `LOW` | total **≤ 5** |

**Step 3 — always render the band with its full axis breakdown.** Example:

```
HIGH (13/16): category=2, product=2, price proximity=2, features=1,
keywords=2, use-case=2, fulfillment=UNKNOWN(0), review-tier=1
```

**Never show a band without the per-axis numbers that produced it.** This is a first-pass rule set, tunable post-launch from real seller feedback (A9) — but implementation builds **this exact scheme**, not an invented one.

#### 6.14.4 "Why this competitor?" — first-class UI requirement

The axis-level explanation is a **first-class, always-visible product feature**, not backend metadata a seller must dig for. Every recommended competitor card shows a plain-language **"Why Metrion selected this competitor"** panel:

```
Why Metrion selected this competitor
✓ Same product category
✓ 82% feature overlap
✓ Same customer use case
✓ ₹100 price difference
✓ 14,200 reviews
  Fulfillment type: not available from current evidence
```

This is what makes CI read as an analyst's reasoning rather than a search-result dump, and it is the natural surface for showing `UNKNOWN` axes **honestly rather than omitting them**. An implementation that hides `UNKNOWN` axes from this panel violates §6.18.

#### 6.14.5 Relevance, identity confidence, evidence confidence and freshness are four separate attributes

They are **never collapsed into a single number or badge.** A competitor can simultaneously be:

- Relevance: `HIGH`
- Identity match: `LIKELY_VARIANT`
- Evidence confidence: `LOW`
- Freshness: `STALE`

That combined state — *"highly relevant competitor, but it may be the 2-pack, the evidence is 18 days old, and extraction confidence was low"* — is itself a **useful, trustworthy signal**, and is more informative than any single collapsed score. Every finding and UI surface displays these as distinct, labelled attributes.

#### 6.14.6 Naming: price proximity vs price band

The scoring axis compares a competitor's price to the **seller's own price** — a proximity check. The **price band** (§6.16.3) is a percentile distribution computed across all tracked competitors. These are different concepts. The axis is named **price proximity** throughout; **"price band" is reserved exclusively for §6.16.3.**

### 6.15 Human-in-the-loop discovery review and visibility tiers (NEW)

```
50 raw candidates          (max_raw_candidates)
      ↓
20 candidates analyzed     (max_analyzed_candidates) — identity-resolved + relevance-scored
      ↓
5 candidates recommended   (max_recommended_candidates)
```

1. **Recommended** — the top scored candidates, each with a full "why this competitor" panel (§6.14.4), relevance labelled `Discovery relevance (provisional)` until evidence exists (§6.14.0).
2. **Other analyzed** — the remaining scored candidates, with the **same axis breakdown**, just not in the top set.
3. **Unanalyzed search results** — the remaining raw candidates that never entered scoring. Shown as **raw search leads only** (title / URL / snippet), **explicitly labelled as not yet analyzed**, with an option for the seller to **promote** one into analysis manually.

**"Don't silently filter" is thereby concretely true — nothing is hidden** — while an unanalyzed lead is never presented with the confidence of a scored candidate.

4. Seller actions on any candidate: **Accept · Reject · Add manually · Promote to analysis** (for unanalyzed results). A promotion sets `origin = PROMOTED_BY_SELLER` and moves the candidate to `tier = ANALYZED`, consuming budget on the same terms as any other analyzed candidate.
5. **Manual URL entry remains a permanent, always-available path, independent of discovery** (C21) — it works with `discovery_enabled = false`, with a failed run, and with no provider approved at all.
6. Accepting a candidate promotes it into a tracked `competitor_url` (§5), subject to the same C4/D7 allowlist check and the same entitlement saved-URL cap as manual intake (§6.1). Until evidence is uploaded for it, it sits at `evidence_status = AWAITING_EVIDENCE` (§6.10.3).

### 6.16 Evidence honesty layer (NEW)

Every extracted fact carries a **timestamp and a confidence tag** (*"extracted 3 days ago, high confidence"* vs *"extracted 18 days ago, manually corrected"*). **Manual correction is a first-class action** and is weighted **higher** than original extraction in downstream comparisons; correction frequency per field is tracked as a data-quality signal.

#### 6.16.1 Evidence-confidence assignment — locked rule

Evaluated **per extracted field, at extraction time**. This is what `Evidence.confidence` (§5.6) is computed from.

| Assigned confidence | Condition |
|---|---|
| `HIGH` | Field extracted cleanly by vision extraction with **no ambiguity flag** from the model, **or** the field was manually corrected/entered by the seller |
| `MEDIUM` | Field extracted **with** an ambiguity flag (partially obscured text, OCR certainty below the model's own high-confidence cutoff), but a value was still produced |
| `LOW` | Field extracted from a partial/cropped screenshot, **or** conflicting values found across multiple extraction attempts on the same evidence, **or** the model's certainty falls below the `MEDIUM` threshold |

**A field that cannot be extracted at all is not assigned a confidence.** It is `UNKNOWN` — a **distinct state from `LOW`**. `LOW` means *a value exists, trust it cautiously*; `UNKNOWN` means *no value exists* (§5.6, §6.18).

**A stale fact must never silently drive a live decision or alert.** Past its threshold, findings using it say so explicitly, and freshness is never folded into relevance (§6.14.5).

#### 6.16.2 Freshness thresholds — locked per-field defaults

| Field / fact type | Threshold (`is_stale` beyond this age) | Config column |
|---|---|---|
| Price | **24 hours** | `freshness_price_hours` |
| Availability | **24 hours** | `freshness_availability_hours` |
| Rating | 7 days | `freshness_rating_days` |
| Review count | 7 days | `freshness_review_count_days` |
| Listing content (title, description, bullets) | 7 days | `freshness_listing_content_days` |
| Review themes (customer-voice mining) | 30 days | `freshness_review_theme_days` |

**A fact past its threshold is not deleted or hidden — it is marked `is_stale: true`, and any finding built on it states this explicitly.** This table is the single source of truth for every reference to "the freshness threshold" in §6.10–§6.20, including the run-level `STALE` state (§6.12.2) and `CIHandoff.validated_fact[].freshness.is_stale` (§5.6).

**Relationship to D6/§6.8's 7-day OP3 ceiling — RESOLVED AND LOCKED (D9, 2026-09-21).** These are **two layers, and both apply**: the table above sets **only** an `is_stale` flag on a *fact* — it never hides, deletes or makes anything unavailable. **D6's 7-day ceiling is the hard rule and is unchanged**: past 7 days the current answer for a URL is reported **unavailable**, not merely flagged, and no alert fires. Where the two appear to conflict, **D6/OP3 governs availability and this table governs only the flag.** The V2 source document's "single source of truth for the freshness threshold" framing is explicitly **not** adopted to the extent it would soften D6. The current implementation (`STALE_SNAPSHOT_CEILING`, `packages/competitor-intelligence/.../delta/compute.py`) implements the 7-day ceiling correctly and **needs no change**; the 24h flagging layer is additive new work.

#### 6.16.3 Price band and outliers — CI's role only; the arithmetic lives in the engine (D10, LOCKED)

**Where this runs — SETTLED (2026-09-21, D10/R17).** Every operand is a signed-`BIGINT` paise money value, so under the project's hard rule the arithmetic belongs in the deterministic engine, and `deterministic-engine.md` has been amended accordingly: the quartile/IQR/fence/outlier computation is **`compute_price_band`, `deterministic-engine.md` §5.15.1**, which is the authority for it.

**CI's role, exhaustively:**

1. **Select and supply the inputs** — the current prices of the tenant's tracked `EXACT_MATCH`-or-`LIKELY_VARIANT` competitors for that seller's product, each as `{ value_paise, confidence, source_ref }` and each entering **`DERIVED`** per §5.1/§5.2. This is the identical interface pattern CI already uses for `compute_price_positioning` and `compute_repricing_scenario` (§5.15).
2. **Pass the configured minimum** — `ci_tenant_config.min_competitors_for_price_band` (default 3, engine floor 3).
3. **Render what comes back, unchanged**, citing the returned `engine_result_ref`: the band boundaries, the typical-range headline, and the per-price outlier flags.
4. **Nothing else.** CI computes **no** percentile, quartile, IQR, fence or outlier flag, and holds no copy of the formula. Trigger and recomputation timing stay CI's: the band is refreshed on each new evidence upload for that product.

**Product rules CI owns (these are not arithmetic):** the minimum-competitor gate's seller-facing behaviour, how outliers are displayed, and the wording of the headline.

A **price band** is computed per product category as a fixed set of percentile buckets across all currently tracked `EXACT_MATCH`-or-`LIKELY_VARIANT` competitors for that seller's product, recomputed on each new evidence upload. **A minimum of 3 tracked competitors is required before a band is shown** (`min_competitors_for_price_band`); below that, CI reports raw comparison only (*"competitor is ₹100 below you"*) **without claiming a "band."**

Locked calculation — **implemented in `deterministic-engine.md` §5.15.1, never in CI.** Restated here only so the product rules below are readable; §5.15.1 is the authority and, if the two ever diverge in wording, §5.15.1 governs. The method matters, because a vague "1.5× IQR" produces different numbers across implementations:

1. **Percentile method:** linear interpolation between closest ranks — the method used by NumPy's default `percentile` and by standard SQL `PERCENTILE_CONT`, chosen specifically for cross-language/cross-database consistency.
2. **Quartiles:** `Q1` = 25th percentile, `Q3` = 75th percentile of tracked competitor prices, using that method.
3. **IQR:** `IQR = Q3 − Q1`
4. **Fences:** `lower_fence = Q1 − 1.5 × IQR`, `upper_fence = Q3 + 1.5 × IQR`
5. **Outlier rule:** a price is an outlier if `price < lower_fence OR price > upper_fence`.
6. **Outlier handling, explicit:** outliers **do** participate in the Q1/Q3 calculation (fences are computed from the **full** tracked set, not a pre-filtered one) · outliers **are** displayed in the distribution/UI, **visibly flagged as outliers** · outliers are **excluded only** from the seller-facing *"typical competitor range"* headline (e.g. *"most competitors: ₹850–₹1,050"*), so one extreme listing doesn't distort the band at a glance.

**Integer paise throughout; no floats, including in the percentile interpolation, which rounds per `deterministic-engine.md` §5.11** — enforced there, in §5.15.1, not here. **No implementation of this formula is ever authorized inside CI** (AC28): a percentile, IQR, fence or outlier computation found in `packages/competitor-intelligence` is a defect regardless of how it is spelled.

### 6.17 Alerts — the two-layer model (NEW — C26)

The tempting example — *"Competitor X dropped price 8%, which puts them below your break-even at current ad spend"* — has CI computing a break-even outcome, directly contradicting AC1, C9 and C17. Fixed structurally:

| Layer | Owner | Content |
|---|---|---|
| **Layer 1 — CI alert (observational only)** | **CI** | *"Competitor X dropped price 8% (₹999 → ₹919)."* CI computes and states **nothing** about margin, contribution or break-even |
| **Layer 2 — cross-agent business alert** | **CEO orchestrator** | CEO receives the CI alert, requests margin/contribution impact from CFO, and delivers the combined alert: *"Competitor X dropped price 8% → CFO: matching would reduce contribution margin to Y% → recommendation: [CFO output]"* |

1. **CI produces Layer 1 only**, and only for candidates with an evidence source (§6.10.3).
2. The fused alert is a **CEO composition of CI's and CFO's separate outputs — never something CI computes internally.** CI's contribution to Layer 2 is exactly the `CIHandoff` payload it already emits (§5.6); nothing else in CI changes to enable it.
3. **Layer 2 is DEFERRED — §1a item 8.** No CFO agent implementation exists (CEO Hub reports CFO `NOT_CONNECTED`). Building it now would mean coding against a guessed CFO contract and would create pressure to approximate a margin inside CI — the exact failure this rule exists to prevent.
4. Per-competitor configurable thresholds (price change %, new listing, rating shift, availability change) remain exactly as specified in D2/D3/§6.3 — V2 adds no new threshold mechanism.
5. Weekly digest and future WhatsApp delivery reuse the already-specified infrastructure (`ci_digest_subscription`, §5; §1a item 3 for WhatsApp).
6. A stale fact never fires an alert — D6 and §6.16.2 both apply.

### 6.18 General evidentiary discipline (NEW — generalized)

§5.3 rule 3, §6.5's degraded path, §6.14.2 and §6.19.2 each resolve a specific instance of one underlying requirement. Stated once, generally, so it governs claims not explicitly covered:

1. **No inferred value is presented as an observed fact.** Missing data is `UNKNOWN`, not guessed.
2. **No absence-of-evidence claim is presented as evidence-of-absence.** *"Not observed"* is not *"does not exist."*
3. **Every generated claim resolves to its supporting evidence on demand**, within that evidence's retention window (C27, §6.8). **If CI cannot show its work for a claim, the claim is not generated.**
4. **Confidence and freshness are attached to data, not left implicit**, and are never collapsed into relevance (§6.14.5).
5. **An LLM may interpret evidence; it may never invent a missing marketplace fact.** *Bad:* "Amazon competitor is probably in stock." *Good:* "Availability: `UNKNOWN` — not present in available evidence." **This is an explicit implementation test case (T44), not a prompt-phrasing convention.**

#### 6.18.1 Where this sits relative to existing rules

This generalizes discipline CI already enforces; it does not replace any of it. §5.3 rule 3 (merge conflicts), §5.1's `UNAVAILABLE` tier, §6.5's `DEGRADED` path and D6's never-mislead ceiling all remain the specific, binding forms of rules 1–3 for their own surfaces.

#### 6.18.2 Customer-voice mining and snippet retention (C27)

From uploaded review evidence, CI extracts: **recurring complaint themes with stated frequency** (*"this theme appeared in N of M sampled reviews"* — **never** *"some people complained"*), **unmet needs / feature requests**, and **explicitly praised attributes**. Only from evidenced candidates (§6.10.3).

**Persistence chain:**

```
Screenshot → extracted review text (transient, local-only, C14/C15)
           → theme with frequency  (persisted: competitor_review_insight, §5)
           → evidence-snippet reference (persisted: ci_evidence_snippet, §5.4)
                  ↓ retained 90 days by default
           auditable within the retention window
```

**Retained within the window:** the minimum needed to audit a theme — the specific extracted snippet (typically one to two sentences), the theme it supports, the source competitor/listing reference, and the extraction date. This is third-party customer-review text and carries the same retention discipline as any other retained third-party content.

**Never retained by this mechanism:** the raw screenshot image (governed by its own, separate, possibly shorter policy at §6.8), and **full review text beyond the snippet a theme actually cites.**

**Consequence of expiry:** the **theme remains visible** (e.g. *"battery life mentioned in 27/80 reviews sampled on [date]"*) but is marked **"source evidence expired"** — not deleted outright, and not silently kept fully traceable forever.

**Enforcement.** Every theme must resolve, on demand and within its retention window, to its supporting snippet references. **This is a verification step between generation and what reaches the user, not a prompting convention.**

**Reconciling with C14.** C14 forbids a review-text corpus and any granular review body beyond the derived aggregate. C27/`ci_evidence_snippet` is the single bounded exception: one cited snippet per theme, with an explicit expiry, tenant-scoped, never embedded (AC5b stands — **no snippet is ever vectorized**), never sent to a hosted provider (C15 stands), and never rendered as a long quotation (AC5c stands). Outside that exception, C14 is unchanged.

### 6.19 Competitor-vs-seller comparison (NEW)

Structured comparison across price, rating, review volume, availability, features/attributes, title, description, bullets, keywords and customer-feedback content — **computed only for candidates with at least one evidence source** (§6.10.3).

#### 6.19.1 The four-bucket framing

1. **Listing gaps** — things competitors have in their listing that the seller doesn't
2. **Product strengths** — where the seller objectively wins on comparable attributes
3. **Product weaknesses** — where the seller objectively loses
4. **Differentiation opportunities** — gaps in competitors' listings/reviews the seller could **credibly** claim

Any bucket entry derived from a `LIKELY_VARIANT` candidate carries that candidate's caveat (§6.13.2). Any bucket entry requiring a seller-side value that is `UNKNOWN` (§5.5) is reported `UNKNOWN`, not omitted and not inferred.

#### 6.19.2 Differentiation claim rule — corrected

The tempting framing — *"competitors are getting complaints about X, your product doesn't have that problem, and your listing doesn't say so"* — contains an unsupported leap: **absence of a complaint in the seller's own evidence does not prove absence of the problem.**

> **State only what the evidence supports:** *"Available seller evidence does not indicate this problem; your listing doesn't currently address it."* Only escalate to a stronger claim (*"your product does not have this problem"*) when there is **affirmative** seller evidence — a positive review, a test result, an explicit product spec — supporting it, **not merely an absence of contrary evidence.**

This is §6.18 rule 2 applied to the one place it is most tempting to break. It applies to **every** differentiation claim CI generates, including anything handed to CMO via CEO.

**Ownership boundary is unchanged (§6.6, MN12):** `differentiation_opportunities` is an observation about the competitive field, never drafted copy. The moment output becomes text for the seller to publish, it is CMO's and routes through CEO.

### 6.20 Evidence → Finding → Action (NEW — C28)

#### 6.20.1 The chain

```
SOURCE → EVIDENCE → VALIDATED FACT → FINDING → IMPLICATION → SUGGESTED ACTION
```

Worked example:

```
Screenshot
   ↓
Price = ₹899 (extracted)
   ↓
Validated seller evidence (timestamp + confidence attached)
   ↓
Finding: "Competitor is ₹200 below your price"
   ↓
Implication: "Your current price position is above this competitor"
   ↓
Suggested action: "Ask CFO to model contribution margin at ₹899"
```

**Every finding CI surfaces must be constructible by walking this chain, and every step must be inspectable** — a seller, or Metrion's own debugging, can trace any suggested action back through implication, finding, validated fact and evidence to the original source, subject to the retention window (C27, §6.8). **This is what makes hallucination structurally harder: each step references the one before it.** CI never ends on a bare observation.

Note the example's final step: CI says *"ask CFO to model contribution margin at ₹899."* **It does not model it.** Where a seller's own current price is in hand, the concrete arithmetic available today is `compute_price_positioning` / `compute_repricing_scenario` (`deterministic-engine.md` §5.15), which CI calls with `competitor_prices[]` as `DERIVED` and whose `metric_result` it renders unchanged, citing the returned `engine_result_ref`. **CI restates none of that arithmetic.**

#### 6.20.2 Output shape — the Competitive Brief

The chain's natural output is a structured brief, not a flat list of observations:

| Section | Content |
|---|---|
| **Market** | N relevant, **evidenced** competitors approved (§6.10.3 distinguishes these from awaiting-evidence candidates) |
| **Price** | Seller's price vs competitor range, with band status — band values from `deterministic-engine.md` §5.15.1 `compute_price_band`, rendered with their `engine_result_ref` (§6.16.3) |
| **Listing** | Specific gaps observed across tracked competitors |
| **Customer voice** | Themes with stated sample frequency (§6.18.2) |
| **Changes** | Recent detected changes (§6.17, Layer 1) |
| **Position** | Seller's price/feature position relative to the tracked set |
| **Opportunity** | Differentiation findings, phrased per §6.19.2 |
| **Next action** | Explicit suggested handoff(s) to CFO and/or CMO (§5.6) |

Every figure in a brief carries its `engine_result_ref` where it came from Brain 1, its source link and capture timestamp otherwise (AC6), and its own `is_stale` flag (§6.16.2).

#### 6.20.3 Routing — explicit, not point-to-point

**A `CIHandoff` payload always flows `CI → CEO`. Never `CI → CFO`. Never `CI → CMO`.** This is C11 restated, not a new rule, and must not regress.

The CEO orchestrator is responsible for:

- **CEO → CFO** — forwarding payloads where `target_agent = CFO`, receiving CFO's calculated result, and composing it with the original CI finding (the Layer 1 / Layer 2 mechanism, §6.17). **Layer 2 is now specified as the CEO playbook `COMPETITOR_PRICE_IMPACT` (2026-10-07; `ceo-agent-orchestration.md` §6.12) — no longer blocked on CFO, built with the conversational CEO.**
- **CEO → CMO** — forwarding payloads where `target_agent = CMO` for listing-action follow-through.

**A `CIHandoff` payload is never passed through to the seller as-is.** It is always composed into a Competitive Brief (§6.20.2) or a CEO-orchestrated cross-agent alert (§6.17) first.

### 6.21 The CEO-only surface (NEW — C32, C33, C46)

#### 6.21.1 The rule

The seller talks to **the CEO and nobody else**. CI has no chat endpoint, no seller-facing prose of its own, and no question it can ask the seller directly (C32, C38). CI returns **structured results** — findings, `InfoRequest`s, monitoring reports, candidate lists — and the CEO composes them into language. The CI dashboard displays what those investigations produced; it collects nothing.

#### 6.21.2 Shortcut and Ask-CEO context contract

The dashboard's two shortcuts and every contextual **Ask CEO** button open the CEO Hub with a draft message (D14) and a context reference:

```
CeoEntryContext {
  intent:  RESEARCH_COMPETITORS | MONITOR_COMPETITORS | ASK_ABOUT_FINDING | ASK_ABOUT_COMPETITOR | ASK_ABOUT_CANDIDATE
  product_id:        text           -- the SKU selected in the dashboard's SKU selector (required for the two shortcuts)
  finding_id?:       uuid           -- ASK_ABOUT_FINDING (C46)
  competitor_url_id?: uuid          -- ASK_ABOUT_COMPETITOR
  candidate_id?:     uuid           -- ASK_ABOUT_CANDIDATE
}
```

1. **Ids only, never content.** The CEO resolves every id **server-side, tenant-scoped**, and reads the finding/competitor/candidate and its evidence itself. A client-supplied title, price or finding body is ignored (C46).
2. The context pre-fills the CEO's *investigation scope*; it does not run anything. The run begins only when the seller sends the message and the CEO routes it (D14).
3. Where the seller has several SKUs and none is selected, the CEO asks which one — never defaults (A/C25 discipline).
4. An id outside the tenant, or one that no longer exists, yields a plain "I can't find that" from the CEO and no data (`404` at the API, AC54).

#### 6.21.3 Scenario → fixed CEO action map

Every row is a **fixed, hand-registered CEO action** (the existing `ceo/registry.py` pattern); an LLM never chooses which code runs (C11, `agent-orchestration-patterns`). Approval and metering follow `ceo-approval-workflow.md` and the entitlement spec — **CI adds no approval mechanism of its own.**

| Seller says / does | CEO action | CI function | New? |
|---|---|---|---|
| "Find competitors for my 1L steel bottle on Amazon" / "research more competitors" | `ci.discover_competitors` | discovery run (§6.10–§6.15), Tavily (§6.28); excludes rejected candidates (C39) | Exists; classifier route is new |
| "Which should I track?" → approves / rejects / adds / removes | `ci.competitor_approve` · `ci.competitor_reject` · `ci.competitor_add` · `ci.competitor_remove` | §6.24 | New (extends existing accept/reject/promote) |
| Attaches a screenshot | `ci.evidence_intake` | §6.22 pipeline | New |
| Answers a CEO confirmation question | `ci.confirm_field` | §6.23 | New |
| "Track / monitor my competitors" | `ci.monitor_competitors` | §6.25 re-evaluation | New |
| "What do customers complain about at my competitors?" | `ci.review_findings` | read of §6.18 review insight, with sample size (C45) | New read action |
| "Should I reduce my price?" | `ci.request_price_scenario` → CFO when available | existing; CEO composes with CFO output (C26) | Exists |
| Clicks Ask CEO | per `CeoEntryContext` | read by id (C46) | New |

#### 6.21.4 Seller product profile by conversation (amends C31)

When CI needs a seller-side field it does not have (e.g. discovery refused under D13, or a relevance axis scoring `UNKNOWN` because the seller's price is unknown), it returns an `InfoRequest` (reason `MISSING`). The CEO asks; the seller states the value; the CEO stores it through the **existing `ci.seller_product_set` action** as `SELLER_ENTERED` and **echoes the stored values back**. Nothing is inferred, defaulted or backfilled (C30). Editing later works the same way, and dependent relevance scores are recomputed with `recalculated_from` (AC22c, unchanged).

---

### 6.22 Image evidence intake (NEW — C36)

```
CEO Hub attachment → quality gate → duplicate check → vision extraction → competitor/product matching
   → confirmation where required (§6.23) → store evidence + snapshot → finding(s) → CEO explains
```

#### 6.22.1 Quality gate

Server-side, before any model runs. Checks: supported image type **by content (magic bytes), not extension or client MIME**; size within `ci_max_evidence_bytes`; minimum pixel dimensions; a blur/legibility measure; and a "looks like a marketplace listing or reviews page" check. Outcomes: `ACCEPTED`, `REJECTED_LOW_QUALITY`, `REJECTED_NOT_A_LISTING` — the last two return a **named reason** to the CEO ("too blurry to read the price"), store **no snapshot**, and write `EVIDENCE_REJECTED_QUALITY`. The thresholds are configuration (A13). A rejected image is retained only as long as needed to explain the rejection (§6.8).

#### 6.22.2 Duplicate detection (per tenant)

`content_sha256` equality → **exact duplicate**: no new evidence row beyond a link, no new snapshot, the CEO tells the seller it already has this and shows the existing result (`EVIDENCE_DUPLICATE`). A close `perceptual_hash` → **possible duplicate**: stored with `duplicate_of`, and **no snapshot is created unless the seller says it is a fresh capture** (asked via `InfoRequest`, low consequence). Duplicate keys are tenant-scoped; nothing crosses tenants.

#### 6.22.3 Extraction and matching

Vision extraction follows §5.3/§6.1 unchanged (structured fields, confidence and source per field), extended with the C44 fields (delivery charge, fulfillment, offers with conditions). **Text visible inside a screenshot is data, never instruction** — extractor output is parsed into typed fields only and never executed or followed (§7 rule 16). To attach the evidence to a competitor: (a) the seller names it; else (b) extracted title/URL is matched to a tracked competitor through identity resolution; else (c) CI returns an `InfoRequest` (`WHICH_COMPETITOR`) — **a screenshot of an untracked competitor is never auto-added** (E45); the CEO asks whether to add it (§6.24). Multiple images in one message form one research session (§5.3).

#### 6.22.4 Channels

```
EvidenceIntakeChannel = CEO_HUB_ATTACHMENT | WHATSAPP | DASHBOARD_UPLOAD (legacy rows only)
```

`CEO_HUB_ATTACHMENT` is live. `WHATSAPP` returns `CHANNEL_NOT_AVAILABLE` until a BSP and a media-ingestion contract exist. `DASHBOARD_UPLOAD` is never produced by V3 code. All channels call **the same pipeline**.

#### 6.22.5 What the CEO tells the seller

The CEO composes from CI's structured result: the extracted price, specifications, offers and delivery as the seller confirmed or CI read them (each with its confidence), what is `UNKNOWN`, and the **comparison against the seller's product** (§6.19, Brain 1 figures cited by `engine_result_ref`). The finding(s) and evidence appear on the dashboard automatically (C46).

---

### 6.23 Seller confirmation policy (NEW — C37, C38)

#### 6.23.1 The matrix

Confirmation is decided per field by **confidence × consequence** (D15), not applied to everything.

| Field class | Confidence | Behaviour |
|---|---|---|
| **Consequential** (price, effective price, availability transition, `EXACT_MATCH` assertion) | any, from vision | **Seller confirms before the value becomes a verified observation** (while Q18 stands). Until confirmed: stored `PENDING`, **excluded** from Brain 1 inputs, deltas, price band, comparison and alerts |
| Consequential | seller-stated (`SELLER_ENTERED`) | Verified on entry; the CEO echoes it back once |
| Non-consequential (rating, review count, delivery text, offer text, listing copy) | `HIGH` | Stored as extracted; shown in the CEO's summary; **correctable, never prompted** |
| Non-consequential | `MEDIUM` / `LOW` | Stored with its confidence, labelled; **not asked** unless the seller asks or the field becomes consequential |
| Any | missing | `UNKNOWN` with a reason; asked **only** if consequential **and** needed for something the seller requested (e.g. a price comparison) |
| Any | conflicting across screenshots (§5.3 rule 3) | `InfoRequest` (`CONFLICT`) — the seller picks or states the value |

#### 6.23.2 Declines, corrections, expiry

- A **declined** confirmation leaves the field `UNKNOWN` and `FIELD_CONFIRMATION_DECLINED` is recorded; it **never** enters a consequential path.
- A seller's stated value **wins over** the extracted one (`SELLER_ENTERED`, §5.3 rule 4 — same precedent), with the original extraction retained in the audit trail.
- An unanswered `InfoRequest` **expires** at `expires_at` (default 7 days, the D6 ceiling) → `EXPIRED`, field `UNKNOWN`, snapshot not usable for consequential paths, and an evidence-freshness reminder (C42) is the only follow-up.

#### 6.23.3 The InfoRequest loop

```
CI emits InfoRequest{field, reason, evidence_id, proposed_value?, allowed_answers}  → CEO phrases the question
→ seller answers in chat → CEO tool ci.confirm_field{info_request_id, answer} → CI stores SELLER_CONFIRMED / SELLER_ENTERED
```

An answer is bound to one `ci_info_request.id`, is **idempotent** on replay, and is accepted only from a member holding `agent.ci` within the tenant (§7 rule 20). CI never contacts the seller; **if the CEO is unavailable the request simply stays `OPEN`** (it is never routed around the CEO).

---

### 6.24 Competitor management and the watchlist (NEW — C39)

| State | Meaning | Reached by |
|---|---|---|
| `CANDIDATE` | Found by discovery; unevidenced (C23) | discovery run |
| `APPROVED` (tracked) | Seller said track it; `AWAITING_EVIDENCE` until evidence exists (C23, §6.15 rule 6) | `ci.competitor_approve` / `ci.competitor_add` |
| `REJECTED` | Seller said no; reason stored; not re-surfaced by later discovery unless the seller asks (Q21) | `ci.competitor_reject` |
| `REMOVED` | Soft removal of a tracked competitor | `ci.competitor_remove` |

1. **Add** accepts a marketplace URL the seller states in chat; host allowlist (C4/D7), entitlement cap (C13) and tenant scope apply exactly as in §6.1. Over cap → refused with the named reason.
2. **Remove** excludes the competitor from comparison, monitoring and alerts, closes its open alerts and `InfoRequest`s (E41), and **retains evidence and history** under §6.8. **Re-adding restores it.** Nothing is hard-deleted by this action.
3. **Bulk** ("track these three"): the CEO echoes the named competitors and writes only after the seller confirms.
4. **History per competitor and per seller SKU:** evidence, snapshots, decisions and events are queryable by `(product_id, competitor_url_id)`.
5. Every action writes a `ci_event` (C47) with the actor and the CEO investigation link; every read is tenant-scoped (AC57).

---

### 6.25 Monitoring semantics and source-specific freshness (NEW — C40, C41)

#### 6.25.1 What a monitor run does

`ci.monitor_competitors(product_id)` reads, for each tracked competitor of that SKU: its latest usable snapshot and evidence date → **freshness state**; the verified snapshot-to-snapshot **deltas** and open Layer 1 alerts (§6.3, §6.17); the current **review findings** (§6.18) with sample sizes; and any open `InfoRequest`s. It performs **no outbound request to any competitor, marketplace or search provider.** It writes `MONITOR_RUN`.

#### 6.25.2 The Monitoring Report and its wording

The report carries `as_of` (when the run executed) and, per competitor, `evidence_date`, `freshness` (`FRESH | STALE | UNAVAILABLE`), the verified delta if any, and a **requested action** — for stale or missing evidence, *"send a fresh screenshot of <competitor>"*. Wording rules, enforced by test (AC46, AC47):

- **Required:** "As of <evidence date>…", "based on the screenshot you sent on…".
- **Forbidden:** "live", "real-time", "continuously", "always up to date", "I'm watching/tracking" in the present continuous, or any statement of a current price/stock for a competitor whose evidence is past D6's ceiling.
- Where nothing is fresh, the CEO says so plainly and asks for evidence; it does not soften the gap.

"Research more competitors" is a separate action (`ci.discover_competitors`) and is the **only** place Tavily is used; it refreshes *leads* and never touches a tracked competitor's snapshot (C35).

#### 6.25.3 Freshness by source

| Source | `is_stale` | Hard ceiling | Notes |
|---|---|---|---|
| Seller screenshot — price, availability | 24 h (§6.16.2) | 7 days (D6/D9): beyond it the current answer is `UNAVAILABLE` and fires no alert | unchanged |
| Seller screenshot — rating, review count, listing content | 7 days | — | unchanged |
| Review themes (reviews-tab screenshot) | 30 days | — | unchanged; snippet retention per C27 |
| Seller-confirmed / seller-entered field | **inherits the evidence's capture date** (C41) | as above | a confirmation does not make old evidence fresh |
| Tavily lead signal | **none — always unverified** | n/a | never counted as fresh evidence, never alerts |

---

### 6.26 Alert hardening (NEW — C42)

1. **Deduplication.** The dedup key is `(tenant, competitor_url, finding_type, direction)`, remembered in `ci_alert_state` with the last alerted value. A repeat of the same condition produces `ALERT_SUPPRESSED_DEDUP` and no new alert. A **new** alert fires only on a **new valid snapshot** (fresh, with its consequential fields confirmed) whose delta against the **last alerted value** again meets the threshold, or on a direction change. The window is `alert_dedup_window_hours`.
2. **Quiet hours.** `quiet_hours_start/end/tz` (all null = none). An alert raised inside the window is written to `ci_held_alert` with `ALERT_HELD_QUIET_HOURS` and **delivered when the window ends — held, never dropped.** **Re-validated at delivery:** if the underlying evidence has since gone stale (D6) the alert is **not** delivered as a confirmed alert (the seller instead gets the freshness request). No priority override in V3 (Q23).
3. **Thresholds.** Price % (D2), availability (D3), per-competitor overrides (R9) — unchanged and configurable through CEO conversation (`ci.threshold_set`, new, writes `ci_tenant_config` / the override columns, echoed back).
4. **Review findings.** A review finding is "significant" only if it meets `review_finding_min_sample` and states N of M (C45); thresholds provisional (Q22).
5. **Freshness reminders.** Driven by `staleness_reminder_days`, delivered through the CEO, written as `FRESHNESS` findings; never worded as an observation about the competitor.
6. **Never claim currency.** An alert is stamped with its evidence date. C26 (Layer 1 only, no margin/contribution/break-even) and AC29 are unchanged.

---

### 6.27 Matching, relationship and comparison (NEW — C43, C44)

#### 6.27.1 Relationship class — derived, never guessed

`relationship_class` is computed **deterministically** from `identity_match` plus the already-scored §6.14 axes; no new LLM judgement is introduced.

| `relationship_class` | Derivation |
|---|---|
| `SAME_PRODUCT` | `identity_match = EXACT_MATCH` |
| `VARIANT` | `identity_match = LIKELY_VARIANT` |
| `DIRECT_COMPETITOR` | not the same product, **category axis ≥ 1** and **product axis = 2** (same function, comparable offer) — typically another brand |
| `FUNCTIONAL_ALTERNATIVE` | not the same product, **product axis = 1** and **use-case axis ≥ 1**, or category axis ≥ 1 with product axis = 1 |
| `UNRELATED` | **category axis = 0 *and* product axis = 0, both `KNOWN`** |
| `UNKNOWN` | any required axis `UNKNOWN`/`CONFLICTED`, or `identity_match = UNCERTAIN` not yet approved. **Never promoted to a named class to make a list look fuller.** |

`relationship_basis` records the values used. The exact thresholds are inherited from §6.14, not redefined here.

**CP2 refinement (2026-10-18, built).** At discovery a search lead has no structured category and no use-case judgement, so those axes are `UNKNOWN` and, read literally, every lead would stay `UNKNOWN`. Therefore, **when category is `UNKNOWN`, the product axis alone may name `DIRECT_COMPETITOR` (axis 2) or `FUNCTIONAL_ALTERNATIVE` (axis 1), marked provisional** (`relationship_basis.is_provisional`); `UNRELATED` stays reserved for the evidence-backed case (category and product both `KNOWN` zero). The product axis at discovery is a **deterministic title-token overlap** between the lead and the seller product, brand excluded (`>= 0.5` same line, `>= 0.15` same type/different line); **low overlap is `UNKNOWN`, never "different"** (synonyms such as bottle/flask defeat a token test). **Only candidates whose relationship is `SAME_PRODUCT`, `VARIANT`, `DIRECT_COMPETITOR` or `FUNCTIONAL_ALTERNATIVE` may fill the Recommended tier**; `UNKNOWN` and `UNRELATED` candidates are scored and stay visible in the other tiers. Known limitation, tracked at V18: token overlap misses true competitors that share few words with the seller title.

#### 6.27.2 Revised gate (replaces the §6.13.2 table)

| `identity_match` | Behaviour |
|---|---|
| `EXACT_MATCH` | Proceeds to relevance scoring — **unchanged** |
| `LIKELY_VARIANT` | Proceeds with the visible caveat — **unchanged** |
| `UNCERTAIN` | Blocked for seller review — **unchanged**; the question is now asked by the CEO (`InfoRequest`, `IDENTITY_UNCERTAIN`) |
| `NOT_A_MATCH` | **Proceeds to relevance scoring** (previously `REJECTED`); then rejected from the recommended flow **only if** `relationship_class = UNRELATED`. A rejected-by-relationship candidate stays visible in the raw tier (§6.15), as before |

The ambiguity-travels-with-the-data rule (§6.13.2) is unchanged. **Tests and code asserting `NOT_A_MATCH → REJECTED` must be revised in CP2 and the revision named in the CP2 report — it is not a silent change.** An `EXACT_MATCH` candidate may be the seller's own listing or a reseller of the same product; it is shown with that caveat and never auto-tracked (E42).

#### 6.27.3 Comparison fields (extends §6.19)

Compared where observed: selling price, MRP and visible discount, **effective price** (`listed − visible discount`, B8 observed-fact arithmetic only), delivery charge, fulfillment, rating, review count, visible offers/coupons/temporary deals, and the specification attributes the seller and competitor both expose. **Offers carry their condition** (`{kind, amount_paise?, percent?, condition_text, valid_until?}`); a conditional offer is **not** subtracted from effective price. Temporary deals carry an `observed_on` date and age like any other field. Each field renders `KNOWN` with its source and confidence, or `UNKNOWN` with a reason — never blank, never zero (C44). Where the seller's own value is `UNKNOWN`, the comparison is `UNKNOWN` (C30). Price positioning, band and scenarios remain Brain 1 (§5.15/§5.15.1); CI renders them unchanged citing `engine_result_ref`.

---

### 6.28 Tavily discovery provider (NEW — C34, C35)

#### 6.28.1 Adapter contract

A `TavilySearchProvider` implements the existing `SearchProvider` protocol and returns `SearchResult` rows with `source = "TAVILY"` and `provider_response_ref`. It: reuses the existing backend Tavily key/config (never the client); sends only the §6.11-filtered query text; **drops any result whose host fails the C4/D7 allowlist** (recorded, not silently); **de-duplicates** by canonical listing (host + marketplace product id such as ASIN/FSN, else normalised URL) across queries in a run; honours §6.12 budgets plus provider-level rate and daily-cost caps (configuration); and caches per tenant only (§6.11 rule 5, §7 rule 11).

**Errors are typed and honest:** a provider outage, timeout, rate limit or quota exhaustion yields a `FAILED` (or `PARTIAL`, with the completed queries named) discovery run and a CEO message saying discovery could not complete — never an empty "no competitors exist" and never a stale cache presented as fresh. Manual add (§6.24) is unaffected (C21).

#### 6.28.2 Provider record (still required — C22, V16)

Completed for Tavily in CP1 from Tavily's own current terms, **not from this spec or from memory**: allowed use for a commercial SaaS; whether results may be stored, for how long, and redisplayed to sellers; attribution; region; query limits; cost per query and the per-tenant monthly cost ceiling. Any field the terms do not clearly answer is recorded `UNKNOWN` and treated as **not permitted** until a human resolves it.

#### 6.28.3 The lead-signal rule, operationalised

Snippet-derived text (a price, "in stock", a star rating) may be parsed only into **display-only candidate fields** (`reported_*`, labelled "reported by search — unverified"). The observation path — `competitor_snapshot*`, the Brain 1 input builder, delta, band, comparison, review mining, alerts, `CIHandoff` — **must not import or read those fields**; this is enforced by a static test (T81), not by convention. The seller upgrades a lead to evidence only by submitting a screenshot (C23, C36).

---

### 6.29 CI dashboard and the findings contract (NEW — C32, C45, C46, C47)

#### 6.29.1 What the dashboard is

A **read-only visual workspace** over data CEO–CI investigations already produced. It is a **refactor** of the existing CI workspace: reuse the working components and backend connections (`/ci/summary`, `/competitor-urls`, `/market-overview`, `/comparison`, `/discovery-runs`, snapshots, events), delete every form and input, keep the original Metrion logo and the exact black/green theme (tokens configurable per `design_status.md`), and **hide technical identifiers by default** (ids, `engine_result_ref`, `evidence_id` appear only inside an expandable "details" view). It never shows a marketplace or competitor product image (C5) — insights and findings only.

Layout (the combination of the two approved mockups; **the numbers in those mockups are illustrative — every real figure comes from stored evidence or Brain 1**):

| Region | Content | Source |
|---|---|---|
| Header | Title, SKU selector, **Research Competitors** and **See / Monitor Competitors** shortcuts (C33) | read-only; shortcuts per §6.21.2 |
| KPI row | Competitors tracked (with *verified* count) · Important changes (price/stock/review) · Your price vs market median · Customer insights count | CI reads; price/median **Brain 1** cited |
| Market snapshot | Price band Q1/median/Q3 and typical range with "your price" position; price-history chart (D18) | **Brain 1** `compute_price_band`/positioning, cited |
| Tabs | **Overview · Competitors · Changes · Evidence** | — |
| Competitors | name, marketplace, price, **relationship class** (not just identity), relevance band (expand for the 8-axis breakdown, C25), last evidence date, status (Verified/Unverified), View, Ask CEO | `ci_candidate`/`competitor_url`/snapshots |
| Changes | verified price/stock changes, freshness items, open alerts (held alerts shown as held) | `competitor_price_event`, `ci_finding`, `ci_alert_state` |
| Evidence | evidence history per competitor (channel, date, confidence, confirmation state), pending confirmations | `competitor_evidence`, `ci_info_request`, `ci_event` |
| Insights & recommendations | findings with evidence date and Ask CEO | `ci_finding` |
| Review insights / listing gaps | themes with N of M and evidence date | §6.18 |
| Discovery candidates | candidate, relationship, provisional relevance, **"Approved — awaiting evidence"** state | `ci_candidate` |
| Recent activity | the C47 event stream, readable | `ci_event` |
| CEO's next step | the latest CEO–CI investigation's deterministic summary, with an Ask CEO action | CEO investigation record; no text generated by CI |

#### 6.29.2 "Verified", and traceability

A competitor/price is **Verified** only if it comes from seller-screenshot evidence, its consequential fields are confirmed (C37), and it is within the D6 ceiling. Otherwise it is **Unverified** with the reason. Every finding row resolves to its `Evidence` records and shows its evidence date, confidence, sample size where applicable and confirmation state (C45); a finding with no evidence is not displayable (AC53).

#### 6.29.3 History

The Evidence and Changes history, and Recent activity, are rendered from `ci_event` and persisted findings — **not from client state or a re-computation** — so what the seller sees is what happened. Findings created during a CEO conversation appear on the next dashboard read with no seller action (AC55).

#### 6.29.4 Empty and degraded states (every panel defines one)

| Panel | Empty / degraded state |
|---|---|
| Whole workspace, new seller | A calm explanation of what CI does, the two shortcuts, and "Ask the CEO to find your competitors" — **no fabricated or sample data** |
| Competitors | "No competitors tracked for this product yet" + Research Competitors |
| KPIs | A KPI with no data shows "—" with a one-line reason, never `0` |
| Price band | Below `min_competitors_for_price_band`: "Needs at least N verified competitor prices" (AC28) |
| Price chart | Below two verified points: plain text, no line (D18) |
| Changes / Insights | "No verified changes yet" / "No insights yet — send a competitor screenshot to the CEO" |
| Stale evidence | Shown, flagged stale with its date (never hidden, never presented as current) |
| Provider/discovery failure | The honest failure and when it happened (§6.28.1) |
| Loading / API error | Skeleton then a retryable error; never a partially-rendered misleading panel |

---

## 7. Authorization and security rules

1. Every CI request enters the `auth.md` §7.1 six-step chain. CI adds no path around it.
2. **Permission and entitlement are separate gates** (`auth.md` §7.2): `agent.ci` says the member may use CI; the cart says the tenant has limited or complete CI. Both must pass.
3. On the **conversational route**, `agent.ci` without `agent.ceo` is unreachable — CEO is the door (C11, `auth.md` R2). On the **direct execution path**, `agent.ci` alone suffices (§6.4, C20).
4. All queries are tenant-scoped; RLS is the final boundary. Background runs set tenant context from the job payload or fail closed.
5. **Allowlist enforcement is server-side, and is now a labeling/format check, not a fetch gate (C4, D7).** A client-supplied URL's host is validated on the server; the UI is not a control. No fetch is being permitted or refused, because none is ever attempted.
6. **RESOLVED BY OBSOLESCENCE — no outbound fetches exist.** This rule previously required outbound fetches to be rate-limited and identify honestly, with `robots.txt` handling left to Q10/legal review (V6). Under the evidence model, CI makes **no outbound request to any competitor URL at all**, so there is nothing to rate-limit, no user-agent to identify honestly, and no `robots.txt` posture to take. **Q10 and V6 are marked resolved/moot in §9 and §12** — see those sections for why this is a resolution, not a silent deletion.
7. Snapshots store facts; review text scraped from a live page, listing copy scraped from a live page, and rehosted images are never persisted — narrowed by C16's carve-out (§1, §6.6): the seller's own submitted title/description/bullets, extracted from their own evidence, are the one exception, and are persisted as such.
8. **Raw review text extracted from a seller-submitted reviews-tab screenshot (§6.5, resolves Q11) and any listing text obtained other than through the seller's own submitted evidence is excluded from every observability surface** and from every hosted provider — logs, exception traces, debug output, APM spans, payload capture, and any external model call — by keeping it inside a bounded, local processing scope that emits only derived structure (§6.5, §6.6).
9. A seller may only ever see their own tenant's competitor URLs and snapshots.
10. **NEW (V2). Every discovery table is tenant-owned and RLS-scoped with `FORCE`** — `ci_discovery_run`, `ci_search_query`, `ci_search_result`, `ci_candidate`, `ci_candidate_relevance`, `ci_evidence_snippet` (§5.4), on the identical pattern as the existing CI tables (`auth.md` §7.3). Discovery runs execute as background jobs and **set tenant context from the job payload or fail closed**, exactly as capture runs do (§6.2 rule 3).
11. **NEW (V2). The search-result cache is never shared across tenants**, even for a byte-identical query string (§6.11 rule 5). A shared cache would both leak one tenant's research interest to another and create a read path around RLS. `ci_search_result` is keyed by `tenant_id` first.
12. **NEW (V2). The query privacy filter (§6.11) is server-side and applied to the composed query text**, immediately before dispatch. The UI is not a control. `ci_tenant_config.discovery_enabled = false` is checked **before any query is composed**, not as a post-hoc filter on results — an opt-out that still sent the query would be no opt-out at all.
13. **NEW (V2). No endpoint accepts a client-supplied `tenant_id` on any discovery surface**, and a candidate URL supplied by a client is validated against the C4/D7 allowlist server-side on the same terms as manual intake (§6.1 rule 1).
14. **NEW (V2). `ci_evidence_snippet` rows are third-party review text under a bounded retention (C27)** and are excluded from every observability surface on the same terms as §7 rule 8 — logs, traces, debug output, APM spans, payload capture, and any hosted model provider. **They are never embedded into a vector store** (AC5b is unchanged by C27's carve-out).
15. **NEW (C31). The seller-product-profile surface (§5.5.1) is a tenant-owned table like any other**: `tenant_id` on every row, RLS `FORCE`, no endpoint accepting a client-supplied `tenant_id`, and background jobs without tenant context failing closed (§7 rules 9–10, 13 restated for this surface). Write access follows the same permission grid as other seller-owned configuration (`auth.md` §7.3); **CI itself holds no write path to it** (AC22b, T72, T73).
16. **NEW (V3). CEO Hub attachment hardening (C36, A14).** Image type is established by content (magic bytes), size-capped server-side, stored under a **server-generated, tenant-scoped path** (never a client-supplied name or path), and the bytes are never logged. **Text inside a screenshot is data, never instruction:** vision output is parsed into typed fields only and cannot cause an action, a tool call or a change of tenant/scope. The attachment path adds no way around the CEO's existing request hardening.
17. **NEW (V3). Tavily outbound (C34).** Only the §6.11-filtered query text leaves Metrion — never a seller id, SKU id, cost or any tenant-identifying value. The API key is server-side only. Responses are data (their text cannot instruct CI). Per-tenant caches, per-tenant cost caps, and the allowlist applied to every returned URL. A provider outage fails closed to "discovery unavailable" (§6.28.1).
18. **NEW (V3). Context ids are validated, never trusted (C33, C46).** Every id in a `CeoEntryContext` is resolved server-side within the tenant; a client never supplies finding content, a price, or a `tenant_id`; a foreign or unknown id is `404`.
19. **NEW (V3). `ci_event` is append-only (C47).** The application role holds no `UPDATE` or `DELETE` on it; `detail` carries ids and enums only — never raw review text, snippets or image content (rules 8, 14).
20. **NEW (V3). Confirmation answers (C38).** An answer is accepted only from a tenant member holding `agent.ci`, is bound to one `ci_info_request.id`, is idempotent on replay, and cannot target a request in another tenant. Competitor approve/reject/add/remove carry the same permission and tenant scoping as every CI action (`auth.md` §7.1).

---

## 8. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | URL outside allowlist | Refused at intake, reason named — now a labeling check (C4, D7) |
| E2 | **REVISED.** No screenshot ever submitted for a `competitor_url` (was: listing removed/404) | No `competitor_snapshot` exists yet; nothing to compare or alert on; URL stays `ACTIVE`, awaiting evidence |
| E3 | **REVISED.** Vision extraction finds no usable fields in any screenshot of a research session (was: fetch blocked) | `capture_status = PENDING_MANUAL_ENTRY` (§5.3); seller prompted for manual entry; no alert until resolved |
| E4 | Snapshot's evidence older than 7 days | **Reported unavailable** per OP3, reframed for evidence age — not displayed with a stamp; no alert; seller prompted to submit fresh evidence (§6.8) |
| E5 | First-ever snapshot | Baseline only; no `competitor_price_event` |
| E6 | Multi-variant page (as shown across the seller's screenshots) | Keyed by `variant_key`; deltas compared within a variant only (A5) |
| E7 | Price unchanged, availability flips | Event fires on D3 with `delta_pct = 0` |
| E8 | Competitor raises price above seller's | Still an event; direction recorded; interpretation left to CFO/CEO |
| E9 | Entitlement exhausted mid-run | **Pending** — cap behaviour belongs to the entitlement and WhatsApp specs (readiness 2A.7). Not decided here (M10) |
| E10 | Seller deletes a URL | URL `ARCHIVED`; snapshots retained only within the retention policy (§6.8) |
| E11 | Same URL added twice | Rejected by unique constraint |
| E12 | **REVISED.** Two or more screenshots in one research session disagree on a field's value (was: marketplace changes page structure) | Field is `UNAVAILABLE`, `conflict = true`, all candidate values recorded in `conflict_values` (§5.3 rule 3); no fabricated or auto-picked value; seller resolves manually |
| E12b | **NEW.** A screenshot is illegible, cropped, or otherwise unusable for a field the seller expected extracted | That field is left `UNAVAILABLE` from that screenshot's extraction; other screenshots in the session, or manual entry, may still supply it (§5.3) |
| E13 | Review count zero | `insight_state = UNAVAILABLE` with `degraded_reason`; never zero-filled |
| E14 | Seller asks for competitor's exact margin | Refused as unknowable; estimated band returned with its basis (C10) |
| E15 | Partner lacks `agent.ci` | `403` — parity between the direct and CEO paths (§6.4). WhatsApp is not a third comparable path here: it never resolves to a Partner identity at all in V1 (always `bound_by`, the OWNER — `whatsapp-integration.md` C8/§6.7), so this denial cannot occur over WhatsApp; it isn't that WhatsApp grants Partners something the other paths deny |
| E16 | Local processing unavailable | `insight_state = DEGRADED` from structured metadata; `degraded_reason` recorded. Raw text is **never** sent to a hosted provider as a fallback (C15, §6.5) |
| E17 | Exception raised mid-derivation while raw text is in memory | Trace is scrubbed; no review body reaches logs or APM (§6.5) |
| E18 | Snapshot passes the retention horizon | Purged per policy; derived insights and referenced provenance retained per §6.8 |
| E19 | Fee reference missing for a category | Brain 1 widens the range and states the assumption; the figure is not suppressed (§6.7.5) |
| E20 | Seller asks CI for a fee rate | CI holds none. Resolved by Brain 1 from the reference store (C18) |
| E21 | **NEW (V2).** Discovery run hits `max_discovery_queries_per_run`, `max_raw_candidates`, or the 2-minute timeout before finishing | Run ends `PARTIAL` with `partial_reason` naming the exact limit hit; results shown are explicitly labelled incomplete — **never a silently truncated list presented as complete** (§6.12.1) |
| E22 | **NEW (V2).** Search provider returns an error, rate-limits, or times out mid-run | Same as E21: `PARTIAL` with `partial_reason`; `ci_search_query.error_code` recorded. If **no** query succeeded, `FAILED` with `failed_reason`. Never a fabricated or cached-from-another-tenant result |
| E23 | **NEW (V2).** Discovery returns zero candidates | `COMPLETE` with zero candidates and a plain message. **Not `FAILED`** — "no candidates found" is a valid, honest answer. Manual URL entry offered (§6.15 rule 5) |
| E24 | **NEW (V2).** Candidate resolves to `UNCERTAIN` identity match | Blocked at `WAITING_FOR_REVIEW` pending seller approval; not scored into the Recommended set until approved (§6.13.2). `EXACT_MATCH`/`LIKELY_VARIANT` candidates in the same run proceed without waiting |
| E25 | **NEW (V2).** Candidate is `LIKELY_VARIANT` and the seller never decides | Proceeds, permanently marked with its caveat; **the caveat travels into every comparison field and every `CIHandoff` derived from it**, not just the candidate card (§6.13.2) |
| E26 | **NEW (V2).** Seller's own `price`, `category` or `fulfillment_type` is `UNKNOWN` — i.e. the seller has not filled the §5.5.1 product profile (D8/C31) | The affected axis is `UNKNOWN` and scores **0**; no seller baseline is invented (§6.14.2 rule 3). With **both** `title` and `category` `UNKNOWN`, the run is refused with a named reason (D13). The seller is prompted to complete the profile — prompting is never a substitute for a value |
| E26b | **NEW (C31).** A canonical-derived `SellerProduct` field and a seller-entered override disagree | The **seller-entered value wins** and `field_source` records `SELLER_ENTERED` (§5.5.1). This is **not** an AC8b-style conflict and never yields `UNAVAILABLE` — there is a designated winner by rule, the same precedent as §5.3 rule 4 on the competitor side |
| E26c | **NEW (C31).** Seller edits the product profile after a relevance score was computed | The score is **recomputed**, not patched, and the superseded row is retained via `ci_candidate_relevance.recalculated_from` (§5.4, §6.14.0) — the same mechanism already used when evidence contradicts a discovery assumption |
| E27 | **NEW (V2).** Seller approves a candidate and never uploads evidence | Candidate sits at `evidence_status = AWAITING_EVIDENCE`, shown as **"Approved — awaiting evidence."** It appears in no comparison, no mining output and no alert (C23, §6.10.3) |
| E28 | **NEW (V2).** Fewer than 3 tracked competitors when a price band is requested | No band is shown or claimed. Raw comparison only (*"competitor is ₹100 below you"*) (§6.16.3) |
| E29 | **NEW (V2).** One competitor's price is an extreme outlier | It **participates** in the Q1/Q3 fences, **is displayed** flagged as an outlier, and is **excluded only** from the "typical competitor range" headline (§6.16.3) |
| E30 | **NEW (V2).** An evidence snippet passes its C27 retention window | Snippet purged (`expired = true`); **the aggregate theme remains visible**, marked **"source evidence expired"** — not deleted, not silently still traceable (§6.18.2) |
| E31 | **NEW (V2).** A COMPLETE run's competitor price crosses the 24h freshness threshold while an alert built on it is open | The **fact** is flagged `is_stale`; the **finding** carries its own `is_stale`; the **run** transitions to `STALE` (§6.12.2). Other still-fresh findings in that run remain valid. A stale fact fires no new alert (§6.17 rule 6) |
| E32 | **NEW (V2).** Seller disables discovery mid-run | In-flight queries are not re-sent; no further query is composed. The run ends `PARTIAL` with `partial_reason = 'DISCOVERY_DISABLED'`. Manual URL entry unaffected (§6.15 rule 5) |
| E33 | **NEW (V2).** Query generation produces a term that would carry a forbidden field (SKU, COGS, ad spend) | That query is **not sent**; the drop and its reason are recorded. The pre-redaction draft is **never persisted** (§6.11 rules 3–4) |
| E34 | **NEW (V2).** Seller asks CI "should I drop my price to match?" | CI emits a Layer 1 observation plus a `CIHandoff` suggesting CFO. **CI states nothing about margin or break-even** (C26). Where the seller's current price is in hand, the price-only arithmetic is `deterministic-engine.md` §5.15, rendered unchanged |
| E35 | **NEW (V2).** Seller asks for a market/demand trend | Refused as not available, with the reason named (C29). **No partially-sourced trend claim is ever emitted** |
| E36 | **NEW (V2).** A model output asserts availability, fulfillment type or any other marketplace fact not present in evidence | Rejected before it reaches the user; the field renders `UNKNOWN` with its reason (§6.18 rule 5). This is an enforced test case (T44), not a prompt convention |
| E37 | **NEW (V3).** Seller asks "should I reduce my price?" and no CFO result is available | The CEO states that no financial scenario is available yet; CI offers the observed competitor delta only; **no margin, break-even or recommendation is produced** (C26, AC29, §1a item 11) |
| E38 | **NEW (V3).** Seller attaches several screenshots in one message | One research session (§5.3); each is quality-checked and duplicate-checked independently; a rejected image does not block the others |
| E39 | **NEW (V3).** Seller answers a confirmation with a value different from the extraction | The seller's value wins (`SELLER_ENTERED`); the original extraction stays in the audit trail (§6.23.2) |
| E40 | **NEW (V3).** An `InfoRequest` is never answered | `EXPIRED`; field `UNKNOWN`; consequential paths stay closed; a freshness reminder, not an assumption (§6.23.2) |
| E41 | **NEW (V3).** Seller removes a competitor that has open alerts or pending `InfoRequest`s | Alerts closed, requests `EXPIRED`, evidence and history retained; re-adding restores (§6.24) |
| E42 | **NEW (V3).** A discovery candidate is `EXACT_MATCH` to the seller's own product | It may be the seller's own listing or a reseller; shown with that caveat and **never auto-tracked** (§6.27.2) |
| E43 | **NEW (V3).** The same competitor product appears on two marketplaces | Two tracked competitors (A5: one URL, one sellable variant); never merged silently |
| E44 | **NEW (V3).** Seller asks to monitor with no tracked competitors | The CEO says none are tracked and offers competitor research; nothing is reported as monitored (§6.25) |
| E45 | **NEW (V3).** Seller attaches a screenshot of a competitor that is not tracked | CI asks via `InfoRequest` (`WHICH_COMPETITOR`); **never auto-adds** (§6.22.3) |
| E46 | **NEW (V3).** Quiet hours cross midnight, or the tenant timezone changes | The window is evaluated in `quiet_hours_tz` as a wrap-around interval; held alerts keep their original `hold_until` unless the seller changes the window (§6.26.2) |
| E47 | **NEW (V3).** Tavily returns the same listing under several URLs, or a URL that redirects off the allowlist | De-duplicated by canonical listing; an off-allowlist final host is dropped and recorded (§6.28.1) |

---

## 9. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | **REVISED.** Screenshot field legibility and layout coverage per marketplace — will a typical seller screenshot actually contain price, MRP, rating, rating count and availability legibly enough to extract (A1, A3) | Every extraction path |
| V2 | **RESOLVED BY OBSOLESCENCE.** Was "anti-bot behaviour under realistic volume" — no fetching occurs, so no anti-bot posture is needed. See Q6 in §12. | — |
| V3 | Populating the Brain 1 fee reference store per marketplace and category (A4, `deterministic-engine.md` §5.14) | The estimated range's usefulness |
| V4 | Items `whatsapp-integration.md` itself still leaves open (credit/cap treatment, mid-thread cap behaviour, decline-alert channel, post-completion messaging) | The residual items in §6.9, not the whole WhatsApp path |
| V6 | **RESOLVED BY OBSOLESCENCE.** Was "legal review of on-demand fetching before launch" — this pivot **is** the outcome of that legal-risk review (automated marketplace scraping was assessed as not viable without legal review the team cannot currently afford). There is no fetching left to review. **Residual, separate item:** DPDP/privacy review of retaining seller-uploaded screenshots and extracted competitor data still applies (§6.8) — tracked there and at `auth.md` Q9, not here. | Launch, not build |
| V7 | Variant-key derivation per marketplace, from the seller's screenshots (A5) | Delta correctness on multi-variant listings |
| V8 | Local derivation quality on target hardware (Q7) — sentiment/theme extraction from reviews-tab screenshots (§6.5, acquisition resolved via Q11; model-quality question itself remains open) and vision-model field extraction generally (§1a item 4) at volume on constrained hardware | §6.5, §6.6, §5.3 |
| V9 | Category capture and taxonomy mapping (BL5, Q8) | The estimated margin range cannot resolve fees without it |
| V10 | **NEW.** Real seller screenshots have not yet validated that vision extraction can reliably distinguish price/MRP/discount fields, rating vs. rating count, and availability state across the three marketplaces' actual mobile/desktop listing layouts | Extraction quality, `capture_status` distribution in practice |
| V11 | **NEW (V2).** No search provider has cleared the §6.10.1 provider record. Whether *any* candidate's terms permit storing and redisplaying results inside a paid SaaS product, in India, at §6.12.1's query volume and an acceptable cost, is unestablished (A6, C22) | **Production discovery entirely.** Does **not** block building the pipeline against `MockSearchProvider` (§1a item 6) |
| V12 | **REVISED (C31/D8 resolved).** The *sourcing* question is closed — the seller-product profile (§5.5.1) supplies `category`, `price`, `attributes`, `keywords` and `fulfillment_type`. **What remains to validate in production:** (a) real form-completion rates (A10) — an empty profile degrades relevance to the honest-but-thin pre-C31 behaviour; (b) whether sellers enter a *current, accurate* listing price and keep it current, since nothing in Metrion can verify it against the marketplace; (c) `rating` and `review_count` for the seller's own product remain `UNKNOWN` by decision, so `review_tier` always scores 0, capping a candidate at 14/16 | Relevance-scoring usefulness, not correctness. No axis ever reports a wrong *fact* — an unfilled or unmaintained field scores 0 |
| V13 | **NEW (V2).** Layer 2 fused alerts cannot be validated at all until a CFO agent exists (C26, §1a item 8) | Layer 2 only. Layer 1 is independently buildable and testable |
| V14 | **NEW (V2).** Identity-resolution accuracy on real Indian marketplace search snippets — whether brand/model/pack-size/bundle can actually be distinguished from a title and a short snippet (A7) — is unproven. A weak resolver pushes candidates into `UNCERTAIN`, converting the "automatic CI" experience into the confirmation marathon §6.13.2 exists to avoid | The gating rule's friction profile, and the usefulness of the Recommended set |
| V15 | **NEW.** **DPDP/privacy review of the C27 evidence-snippet carve-out, before launch.** C27 itself is a **locked design decision** and is not in question here — what is unvalidated is its legal standing. It is the first time any granular third-party review text is persisted anywhere in Metrion (one cited one-to-two-sentence extract per theme, 90 days, extendable for a named reason), and it has a different privacy profile from the derived aggregates C14 was written to protect. The same DPDP review already pending at §6.8 and `auth.md` Q9 must cover it **explicitly, not by implication**. **If review refuses the carve-out, §6.18.2's "every theme resolves to its snippet on demand" requirement becomes unsatisfiable and must be re-specified on the record — never quietly dropped** | Launch, not build. `ci_evidence_snippet` and §6.18.2's traceability guarantee. Does **not** block building C27 as specified |
| V16 | **NEW (V3).** Tavily's terms and cost at CI volume (C34, §6.28.2). **The provider record is complete (§6.10.1a); three items need a human decision:** (a) the terms do not address redisplaying outputs to end customers of a paid product; (b) Tavily may retain and train on Metrion's query text; (c) the per-tenant monthly cost ceiling (free tier 1,000 credits/month is shared with PI) | Production launch of discovery |
| V17 | **NEW (V3).** Real-seller validation of the CEO Hub screenshot-and-confirm flow (A11, A13): do sellers attach, and answer, and does the confirmation cadence feel proportionate? Includes real quality-gate behaviour on phone screenshots | Production launch of evidence intake |
| V18 | **NEW (V3).** Accuracy of `relationship_class` on real Indian-marketplace leads across at least two categories (D17, A12) — a wrong class is a wrong *ordering/label*, never a wrong fact, but it must be measured | Production launch of cross-brand discovery |

---

## 10. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | CI contains **no financial formula of any kind** — margin, fee, profit, tax or cost. Every such figure traces to a Brain 1 call. Price deltas over CI's own observed facts are permitted and are not financial calculations. |
| AC2 | No competitor margin is ever emitted as a point value — only a labelled range. |
| AC3 | No scheduled or background crawling exists, and none is possible — **Metrion never fetches a competitor URL, ever.** Every snapshot traces to an explicit evidence submission (`EVIDENCE_UPLOAD`). |
| AC4 | Non-allowlisted hosts are refused server-side (now a labeling/format check, C4/D7 — not a fetch gate, since nothing is fetched). |
| AC5 | No scraped review text, no scraped listing copy and no rehosted image is persisted anywhere — including logs, traces, APM, Redis and vector stores. **Narrowed by C16's carve-out:** the seller's own submitted title/description/bullets, extracted from their own evidence, are the one permitted exception and are persisted as structured fields. |
| AC5d | No raw review or listing text is ever transmitted to a hosted model provider (C15). |
| AC5b | No vector embedding is ever generated from review text; no review-text corpus exists. *Cross-reference (2026-10-12):* the shared RAG index (`rag-knowledge.md`) may index only CI's **derived** `COMPETITOR_CHANGE` findings (the shared-findings ledger's own text, which the ledger already forbids from carrying free numbers) - never review text, listing copy, scraped pages or C27 snippets; `rag-knowledge.md` AC15 tests this with a known-phrase grep of the index. AC5b is unchanged. |
| AC5c | User-facing output contains no full review and no long quotation. |
| AC6 | Every displayed figure carries a source link and capture timestamp. |
| AC7 | Snapshots whose evidence is older than 7 days are reported unavailable and never fire an alert (OP3, §6.8). |
| AC7b | Snapshots are purged per the configured retention policy; raw evidence images are purged per their own, shorter-or-equal policy; neither is retained indefinitely (C19, §6.8). |
| AC8 | Evidence that fails extraction still produces a snapshot row with a status (`PENDING_MANUAL_ENTRY`, §5.3), never a gap and never a fabricated value. |
| AC8b | **NEW.** When two or more screenshots in one research session disagree on a field, that field is `UNAVAILABLE` and flagged (`conflict = true`) — never silently resolved by picking one (§5.3 rule 3). |
| AC9 | Permission and entitlement are evaluated independently and both must pass. |
| AC10 | CI never calls another agent directly. |
| AC10b | CI holds no fee rate table; all fee references resolve inside Brain 1 (C18). |
| AC10d | Every displayed estimated range cites an `estimate_ref` and never an `engine_result_ref` (engine §9.1). |
| AC10c | No WhatsApp cap, investigation or mid-thread behaviour is decided in this spec (§6.9). |
| AC11 | A first snapshot generates no change event. |
| AC12 | Background runs without tenant context fail closed. |
| AC13 | **NEW (V2).** No named search provider is referenced, imported, configured or depended on anywhere in the codebase. Discovery runs entirely through a `SearchProvider` interface with `MockSearchProvider` as the only shipped implementation (C22, §1a item 6). |
| AC14 | **NEW (V2).** No comparison, mining output or alert exists for any candidate whose `evidence_status = AWAITING_EVIDENCE`. Every comparison/mining/alert field traces to an `Evidence` record with `source_type` `SELLER_SCREENSHOT` or `LICENSED_PROVIDER` — **never to a search snippet** (C23, §6.10.3). |
| AC15 | **NEW (V2).** A candidate with discovery data only is displayed as **"Approved — awaiting evidence"**, a visibly distinct state, never as a tracked competitor with facts (C23). |
| AC16 | **NEW (V2).** No externally-sent query ever contains an internal SKU/product ID, supplier or sourcing data, margin/COGS/cost data, private sales-volume or ad-spend data, or non-public positioning language. Verified against the **stored post-redaction** `ci_search_query.query_text`, and no pre-redaction draft is persisted anywhere (§6.11). |
| AC17 | **NEW (V2).** With `discovery_enabled = false`, **zero** queries are composed or sent, and manual URL entry remains fully functional (D11, §6.11 rule 1). |
| AC18 | **NEW (V2).** The 24h search cache is never read across tenants, even for an identical query string (§6.11 rule 5, §7 rule 11). |
| AC19 | **NEW (V2).** A run that hits any §6.12.1 budget or a provider error ends `PARTIAL` with a `partial_reason` naming the limit — never a silently truncated list presented as complete. |
| AC20 | **NEW (V2).** Every candidate carries an explicit `identity_match` value with a recorded basis; no candidate is treated as `EXACT_MATCH` by default. `UNCERTAIN` blocks; `LIKELY_VARIANT` proceeds carrying its caveat into every derived field (C24, §6.13.2). |
| AC21 | **NEW (V2).** No relevance band is ever rendered without its full per-axis breakdown, and every `UNKNOWN`/`CONFLICTED` axis scores exactly 0 (C25, §6.14.3). |
| AC22 | **NEW (V2).** No seller-side baseline is ever invented. A `SellerProduct` field with **neither** a canonical source **nor** a seller-entered value is `UNKNOWN`, and the resulting comparison is `UNKNOWN` scoring 0 (C30, C31, §6.14.2 rule 3). An unfilled profile field is `UNKNOWN`, never a default. |
| AC22b | **NEW (C31).** Every populated `SellerProduct` field carries a `field_source` of `CANONICAL_DERIVED` or `SELLER_ENTERED`; where both exist and disagree, the `SELLER_ENTERED` value is the one used and is recorded as such (§5.5.1). CI writes to neither source. |
| AC22c | **NEW (C31).** The seller-product profile is editable at any time, not write-once, and an edit triggers recomputation of dependent relevance scores rather than a silent patch (E26c). |
| AC23 | **NEW (V2).** Relevance, identity-match confidence, evidence confidence and freshness are stored and displayed as four separate attributes; no surface collapses any two into one score or badge (C25, §6.14.5). |
| AC24 | **NEW (V2).** A relevance score computed before evidence exists is labelled **"Discovery relevance (provisional)"** wherever it appears (§6.14.0). |
| AC25 | **NEW (V2).** All three candidate tiers are reachable in the UI — Recommended, Other analyzed, and Unanalyzed search results — with unanalyzed leads explicitly labelled as not yet analyzed. **Nothing is silently filtered out** (§6.15). |
| AC26 | **NEW (V2).** Every `Evidence.confidence` value is produced by the §6.16.1 rule, and a non-extractable field is `UNKNOWN`, never `LOW`. |
| AC27 | **NEW (V2).** Every fact past its §6.16.2 per-field threshold is marked `is_stale: true` and is never hidden; every finding built on one states so explicitly; no stale fact fires an alert. **The per-field thresholds set the flag and nothing else**; D6's separate 7-day OP3 unavailability ceiling applies unchanged and governs availability wherever the two meet (AC7, D9 LOCKED). |
| AC28 | **NEW (V2).** No price band is shown below `min_competitors_for_price_band` tracked competitors; outliers participate in the fences, are displayed flagged, and are excluded only from the "typical competitor range" headline (§6.16.3). |
| AC28b | **NEW (D10, LOCKED).** **CI contains no percentile, quartile, IQR, fence or outlier arithmetic of any kind.** Every band figure CI displays came from `deterministic-engine.md` §5.15.1 `compute_price_band` and is rendered citing the returned `engine_result_ref`; CI's only inputs to it are the tracked competitor prices as `DERIVED` and the configured minimum. Same boundary as AC35. |
| AC29 | **NEW (V2).** No CI alert contains a margin, contribution, break-even, fee or cost figure or implication. CI emits Layer 1 only (C26, and AC1 restated for alerts). |
| AC30 | **NEW (V2).** Every review theme resolves on demand to its supporting snippet reference within the retention window; past expiry the theme remains visible marked **"source evidence expired"** and the snippet is gone (C27, §6.18.2). |
| AC31 | **NEW (V2).** No snippet retained under C27 is ever embedded, logged, traced, or sent to a hosted model provider — AC5b, AC5c and AC5d are unchanged by the carve-out (§7 rule 14). |
| AC32 | **NEW (V2).** No differentiation claim asserts evidence-of-absence. Stronger claims appear only with affirmative supporting evidence (§6.19.2). |
| AC33 | **NEW (V2).** No LLM output containing an invented marketplace fact reaches a user; such fields render `UNKNOWN` with a reason (§6.18 rule 5). Enforced by test, not by prompt phrasing. |
| AC34 | **NEW (V2).** Every `CIHandoff` payload routes `CI → CEO` only, is never delivered to a seller as-is, and every `validated_fact` resolves to an `Evidence` record via `evidence_refs` (C28, §6.20.3). |
| AC35 | **NEW (V2).** CI contains no price-positioning or repricing arithmetic of its own. Where a seller price is in hand it calls `deterministic-engine.md` §5.15 with `competitor_prices[]` as `DERIVED` and renders the result citing the returned `engine_result_ref`. |
| AC36 | **NEW (V2).** No market/demand trend claim is emitted by any surface (C29). |
| AC37 | **NEW (V2).** Every discovery table carries `tenant_id`, is RLS-scoped with `FORCE`, and discovery background jobs without tenant context fail closed (§7 rule 10, AC12 restated for discovery). |
| AC38 | **NEW (V3).** The CI dashboard contains **no form, input, upload control or manual-entry field**, and CI exposes no seller-facing chat endpoint (C32). |
| AC39 | **NEW (V3).** The Research/Monitor shortcuts and every Ask CEO button open the CEO Hub with a structured context reference; none calls a CI run endpoint, collects input, or carries a client-supplied `tenant_id` or finding content (C33, §6.21.2). |
| AC40 | **NEW (V3).** Discovery runs through a `TavilySearchProvider` behind `SearchProvider`; non-allowlisted hosts are dropped and recorded; provider failure yields an honest `FAILED`/`PARTIAL` run, never a silent empty result; no marketplace or search frontend is scraped (C34, §6.28). |
| AC41 | **NEW (V3).** No value read from a Tavily result is written to a snapshot or snapshot field, used as a Brain 1 input, delta, band, comparison, review theme, alert or `validated_fact`; it is displayed only on a candidate and only labelled unverified. Enforced by a static test (C35, §6.28.3). |
| AC42 | **NEW (V3).** A CEO Hub attachment passes the §6.22 pipeline: low-quality and non-listing images are rejected with a named reason and store no snapshot; an exact duplicate creates no new snapshot; the `WHATSAPP` channel returns `CHANNEL_NOT_AVAILABLE` (C36). |
| AC43 | **NEW (V3).** A consequential vision-extracted field is never a verified observation, a Brain 1 input, a delta or an alert source until the seller confirms it; non-consequential `HIGH` fields are not prompted; a declined confirmation leaves the field `UNKNOWN` and it never reaches a consequential path (C37, §6.23). |
| AC44 | **NEW (V3).** CI never addresses the seller: every question is an `InfoRequest` composed by the CEO, and every answer returns through `ci.confirm_field`, stored with provenance, idempotent on replay (C38). |
| AC45 | **NEW (V3).** Approve, reject, add and remove run as fixed CEO actions; removal is soft and retains evidence and history; a rejected candidate is not re-surfaced unless asked; bulk requests are echoed before writing; each action writes a `ci_event` (C39, §6.24). |
| AC46 | **NEW (V3).** A monitoring report carries its as-of time and each competitor's evidence date, performs no outbound request, and requests fresh evidence where stale (C40, §6.25). |
| AC47 | **NEW (V3).** No CI- or CEO-composed text about competitor currency uses live/real-time/continuous wording, and no scheduled job contacts a competitor, marketplace or Tavily for prices — enforced by an eval and a test, not by prompt phrasing (C40, D16). |
| AC48 | **NEW (V3).** Freshness is evaluated per source; a confirmed field inherits its evidence's age; a Tavily signal is never fresh (C41, §6.25.3). |
| AC49 | **NEW (V3).** A repeated identical condition raises one alert; a new alert needs a new valid snapshot whose delta against the **last alerted value** meets the threshold (C42, §6.26.1). |
| AC50 | **NEW (V3).** Alerts raised in quiet hours are held, not dropped, delivered at window end, and re-validated against freshness at delivery (C42, §6.26.2). |
| AC51 | **NEW (V3).** An other-brand `NOT_A_MATCH` candidate reaches relevance scoring and receives a `relationship_class`; only `UNRELATED` is rejected from the recommended flow; `UNCERTAIN` stays blocked for review; `relationship_class` is never promoted from `UNKNOWN` to fill a list (C43, §6.27). |
| AC52 | **NEW (V3).** Comparison shows delivery, fulfillment, ratings, reviews and offers with every unobserved value `UNKNOWN` plus reason; a conditional offer is recorded with its condition and not subtracted from effective price (C44, §6.27.3). |
| AC53 | **NEW (V3).** Every displayed finding resolves to `Evidence` records and shows evidence date, confidence, sample size (N of M) where applicable and confirmation state; a finding without evidence is invalid and not displayed (C45, §6.29.2). |
| AC54 | **NEW (V3).** Ask CEO passes a `finding_id`; the CEO re-reads the finding and evidence server-side; a foreign or unknown id is `404` and yields no data (C46, §7 rule 18). |
| AC55 | **NEW (V3).** Findings created in CEO conversations appear on the dashboard with no seller action, and the dashboard renders persisted findings and events, never client state (C46, §6.29.3). |
| AC56 | **NEW (V3).** Every event type in C47 is written; `ci_event` is append-only (no `UPDATE`/`DELETE` grant); `detail` never contains raw review text, snippets or image content (C47, §7 rule 19). |
| AC57 | **NEW (V3).** Every V3 table carries `tenant_id` with RLS `FORCE`; V3 background jobs without tenant context fail closed; no V3 endpoint accepts a client-supplied `tenant_id` (§5.7, §7). |
| AC58 | **NEW (V3).** The dashboard shows no marketplace or competitor image, hides technical identifiers by default, and every panel defines an empty/degraded state with no fabricated data and no `0` standing in for missing (C5, §6.29). |

---

## 11. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Add valid `amazon.in` URL | Stored, reference-only; never fetched |
| T2 | Add `alibaba.com` URL | Refused, reason named (AC4) |
| T3 | Free tenant adds a 4th URL | Blocked by entitlement |
| T4 | First evidence submission on a new URL | Baseline snapshot; no event (AC11) |
| T5 | Second submission, price −8%, threshold 5% | Event, `threshold_breached = true`, `alert_eligible = true` |
| T6 | Second submission, price −2% | Event recorded, `threshold_breached = false`, no alert |
| T7 | Price static, stock → out | Event fires via D3 |
| T8 | **REVISED.** Two screenshots in one research session report conflicting prices | Field `UNAVAILABLE`, `conflict = true`, both values in `conflict_values`; no event fires until the seller resolves it manually (E12, AC8b) |
| T9 | Prior snapshot's evidence 9 days old | **Reported unavailable**; not displayed with a stamp; no alert (AC7) |
| T10 | **REVISED.** Vision extraction finds no usable price field in any screenshot of a session | `capture_status = PENDING_MANUAL_ENTRY`; seller prompted for manual entry; no event until resolved (E3) |
| T10b | **NEW.** Seller manually enters the missing price after T10 | Field becomes `SELLER_ENTERED`; `capture_status` advances toward `COMPLETE`; comparable in the next change-detection pass |
| T11 | Seller asks "what's their margin?" | Estimated band from Brain 1, labelled, with basis (AC2) |
| T12 | Inspect CI for margin arithmetic | None present (AC1) |
| T13 | Partner without `agent.ci` requests a run | `403` |
| T14 | Partner with `agent.ci`, tenant lacks CI entitlement | Denied by entitlement, not permission |
| T15 | Quota exhausted mid-run | Behaviour pending the entitlement spec; not asserted here (E9) |
| T16 | WhatsApp confirm triggers a run | Run executes under the same permission and entitlement checks |
| T17 | WhatsApp disabled | In-app findings unaffected |
| T18 | CI asked to generate optimised copy | Routed via CEO to CMO; CI does not call CMO (AC10) |
| T19 | Multi-variant page | Deltas computed within `variant_key` (E6) |
| T20 | Cross-tenant snapshot id requested | `404` |
| T21 | Run a capture, then grep all stores for a known review phrase | Zero hits in DB, object storage, logs, traces, Redis and vector store (AC5) |
| T22 | Force an exception mid-derivation | Trace contains no review body (E17) |
| T23 | Source blocks review access | Degraded insight from rating distribution only; `degraded_reason` recorded (E16) |
| T24 | Local model unavailable at derivation time | `DEGRADED` result; **no** outbound call to a hosted provider (AC5d) |
| T25 | Evidence-upload run by a partner with `agent.ci` but not `agent.ceo` | Succeeds on the direct path (`EVIDENCE_UPLOAD`); no CEO call consumed (C20) |
| T26 | Same partner asks CEO for a competitor check | Requires `agent.ceo`; `403` without it (§7 rule 3) |
| T27 | Snapshot ages past retention horizon | Purged; derived insight retained (AC7b) |
| T27b | **NEW.** Evidence image ages past `raw_evidence_image_retention_days` but the snapshot itself has not yet passed `snapshot_retention_days` | Raw image bytes purged (`image_retained_until` stamped); `competitor_evidence` row and the snapshot's extracted fields remain (§6.8) |
| T28 | Inspect CI for a fee rate table | None present (AC10b) |
| T29 | **REVISED.** Grep all stores for a competitor's exact title/description text scraped from a live page | Zero hits — **because there is no such text**; only what the seller submitted as their own evidence, which is the permitted exception, is persisted (AC5's carve-out) |
| T30 | **NEW.** Seller sets a per-URL price threshold override lower than the tenant default | Change detection for that URL uses the override, not `ci_tenant_config.price_threshold_pct` (§6.3, closes Q5) |
| T31 | **NEW (V2).** Grep the codebase for any named search-provider SDK, base URL or API-key config | Zero hits; only `SearchProvider` + `MockSearchProvider` exist (AC13) |
| T32 | **NEW (V2).** Run full discovery end-to-end against `MockSearchProvider` fixtures | Completes without any real provider configured — steps 1–4 of §6.10.1's build order are not blocked on steps 5–8 |
| T33 | **NEW (V2).** Approve a discovered candidate, then request a comparison before uploading evidence | Refused/empty with **"Approved — awaiting evidence"**; no comparison, no mining, no alert (AC14, AC15, E27) |
| T34 | **NEW (V2).** Force a run to exceed `max_discovery_queries_per_run` | `PARTIAL`, `partial_reason` names the query cap; the short list is labelled incomplete (AC19, E21) |
| T35 | **NEW (V2).** Provider returns a 429 after 3 of 20 queries | `PARTIAL` with `error_code` recorded; results from the 3 successful queries shown as incomplete (E22) |
| T36 | **NEW (V2).** Discovery returns zero candidates | `COMPLETE`, zero candidates, manual entry offered — **not** `FAILED` (E23) |
| T37 | **NEW (V2).** Compose a query for a product whose title contains an internal SKU code | The SKU never appears in the sent query, nor in stored `query_text`; the drop is recorded; no pre-redaction draft persisted (AC16, E33) |
| T38 | **NEW (V2).** Set `discovery_enabled = false`, then trigger discovery | Zero queries composed or sent; manual URL entry still works (AC17, E32) |
| T39 | **NEW (V2).** Tenant A runs query "wireless mouse"; tenant B runs the identical query within 24h | Tenant B gets its own provider call and its own cache entry; tenant A's `ci_search_result` rows are unreadable to B (AC18, §7 rule 11) |
| T40 | **NEW (V2).** Candidate resolves `UNCERTAIN` | Blocked at `WAITING_FOR_REVIEW`; sibling `EXACT_MATCH` candidates in the same run proceed without waiting (AC20, E24) |
| T41 | **NEW (V2).** `LIKELY_VARIANT` candidate produces a price comparison | The variant caveat appears on the comparison field and in the `CIHandoff`, not only on the candidate card (AC20, E25) |
| T42 | **NEW (V2).** Score a candidate where the seller's `fulfillment_type` is `UNKNOWN` and the competitor's is known | Axis is `UNKNOWN`, scores 0, and `axis_states` distinguishes it from a genuine 0; no baseline invented (AC22, E26) |
| T43 | **NEW (V2).** Candidate scores total 12 but category similarity = 0 | Band is **not** `HIGH` — the §6.14.3 category/product floor blocks it (AC21) |
| T44 | **NEW (V2).** Feed the LLM a screenshot with availability cropped out and ask for availability | Output is "Availability: `UNKNOWN` — not present in available evidence"; **never** "probably in stock" (AC33, §6.18 rule 5, E36) |
| T45 | **NEW (V2).** Render any relevance band in any surface | The per-axis breakdown is present, including `UNKNOWN` axes shown honestly (AC21, §6.14.4) |
| T46 | **NEW (V2).** Inspect a competitor with relevance `HIGH`, identity `LIKELY_VARIANT`, evidence confidence `LOW`, freshness `STALE` | All four render as distinct labelled attributes; no collapsed score or single badge anywhere (AC23, §6.14.5) |
| T47 | **NEW (V2).** Score a candidate before evidence, then upload evidence that does not contradict any discovery assumption | Label changes from "Discovery relevance (provisional)" to "Relevance"; the score itself is unchanged; no recalculation row written (AC24, §6.14.0) |
| T48 | **NEW (V2).** Upload evidence that contradicts a discovery-stage assumption | Score recalculated under §6.14.3; prior row retained via `recalculated_from` (§6.14.0) |
| T49 | **NEW (V2).** Run discovery producing 50 raw / 20 analyzed / 5 recommended | All three tiers reachable and labelled; the ~30 unanalyzed leads are visible as raw leads with a promote action (AC25, §6.15) |
| T50 | **NEW (V2).** Promote an unanalyzed lead into analysis | It is identity-resolved and scored with the same axis breakdown; `origin = PROMOTED_BY_SELLER` (§6.15 rule 4) |
| T51 | **NEW (V2).** Extraction produces a value from a cropped screenshot | `Evidence.confidence = LOW`; a field that could not be extracted at all is `UNKNOWN`, not `LOW` (AC26, §6.16.1) |
| T52 | **NEW (V2).** Competitor price fact reaches 25 hours old with an open alert referencing it | Fact `is_stale = true`; the finding carries `is_stale`; the run transitions `COMPLETE → STALE`; other fresh findings in that run stay valid (AC27, E31, §6.12.2) |
| T53 | **NEW (V2).** Same run, no active finding references any stale fact | Run remains `COMPLETE` (§6.12.2 locked rule) |
| T54 | **NEW (V2).** Request a price band with 2 tracked competitors | CI passes 2 prices; the engine returns `UNAVAILABLE` / `INSUFFICIENT_COMPETITOR_PRICES` (engine T31); CI shows no band and claims none — raw comparison only (AC28, E28) |
| T55 | **NEW (V2).** Tracked set contains one extreme outlier price | Engine includes the outlier in Q1/Q3 and flags it (engine T32); CI displays it flagged and excludes it only from the "typical competitor range" headline (AC28, E29) |
| T56 | **NEW (V2).** Grep `packages/competitor-intelligence` for percentile / IQR / quartile / fence arithmetic | **Zero occurrences — permanently, not pending anything.** Every band figure traces to a `compute_price_band` `engine_result_ref` (AC28b, D10, `deterministic-engine.md` §5.15.1) |
| T56b | **NEW (D10).** Request a price band with 4 tracked competitors | CI supplies 4 `DERIVED` prices plus `min_competitors_for_price_band`, and renders the returned rows citing `engine_result_ref`; no band number is computed in CI (AC28b) |
| T57 | **NEW (V2).** Competitor drops price 8%; CI emits an alert | Alert text contains the observation only — **no margin, contribution, break-even, fee or cost figure or implication** (AC29, C26) |
| T58 | **NEW (V2).** Ask CI to produce a fused "this puts you below break-even" alert | Refused; CI emits Layer 1 plus a `CIHandoff` suggesting CFO. Layer 2 is CEO's and is deferred (§1a item 8, E34) |
| T59 | **NEW (V2).** Ask a review theme to show its evidence within the retention window | Resolves to its snippet reference(s) (AC30, §6.18.2) |
| T60 | **NEW (V2).** Advance past `evidence_snippet_retention_days` | Snippet purged; theme still visible marked "source evidence expired" (AC30, E30) |
| T61 | **NEW (V2).** Grep vector store, logs, traces and APM for a known retained snippet phrase | Zero hits (AC31, §7 rule 14) |
| T62 | **NEW (V2).** Ask CI for a differentiation claim where the seller's evidence simply lacks a complaint | Output says "available seller evidence does not indicate this problem" — **never** "your product does not have this problem" (AC32, §6.19.2) |
| T63 | **NEW (V2).** Inspect a `CIHandoff` payload's delivery path | Goes to CEO only; never reaches CFO/CMO directly; never surfaced to the seller as-is (AC34, §6.20.3) |
| T64 | **NEW (V2).** Seller supplies their current price and asks for price positioning | CI calls `compute_price_positioning` with `competitor_prices[]` as `DERIVED` and renders the result citing `engine_result_ref`; CI contains no positioning arithmetic (AC35) |
| T65 | **NEW (V2).** Ask CI whether demand for a category is rising | Refused with reason named; no partially-sourced trend claim (AC36, C29, E35) |
| T66 | **NEW (V2).** Cross-tenant read of a `ci_candidate` / `ci_discovery_run` / `ci_search_result` id | `404` (AC37, T20's rule extended to discovery tables) |
| T67 | **NEW (V2).** Discovery background job dispatched with no tenant context | Fails closed (AC37, AC12) |
| T68 | **NEW (V2).** Trigger discovery for a `SellerProduct` with both `title` and `category` `UNKNOWN` | Refused with a named reason; no queries composed (D13, E26) |
| T69 | **NEW (C31).** Seller fills only `category` and `fulfillment_type` in the product profile, leaving `price`, `attributes` and `keywords` blank | The two filled fields are `KNOWN`/`SELLER_ENTERED` and score normally; the three blanks stay `UNKNOWN` and score 0. **No blank is defaulted or inferred** (AC22, AC22b) |
| T70 | **NEW (C31).** A canonical-derived `title` and a seller-entered `title` differ | The seller-entered value is used; `field_source = SELLER_ENTERED`; **no `conflict`/`UNAVAILABLE` state is produced** — same precedent as §5.3 rule 4 (AC22b, E26b) |
| T71 | **NEW (C31).** Seller edits the profile's `price` after candidates were scored | Dependent relevance scores are recomputed and prior rows retained via `recalculated_from`; no score is patched in place (AC22c, E26c) |
| T72 | **NEW (C31).** Cross-tenant read of another tenant's seller-product profile row | `404`; the profile table is `tenant_id`-scoped with RLS `FORCE` like every other tenant table (AC37, §7) |
| T73 | **NEW (C31).** Attempt a CI-side write to the seller-product profile | Refused — CI reads `SellerProduct` and writes neither of its two sources (C30, C31, §5.5.1) |
| T74 | **NEW (V3).** Open the CI dashboard as a brand-new seller (no data) | Every panel shows its §6.29.4 empty state; **no** form, input, upload or image; the two shortcuts present; no fabricated data (AC38, AC58) |
| T75 | **NEW (V3).** Search the backend for a CI chat/message endpoint | None exists (AC38) |
| T76 | **NEW (V3).** Select a SKU and press Research Competitors | CEO Hub opens with a draft message and `CeoEntryContext{RESEARCH_COMPETITORS, product_id}`; **no CI endpoint is called** by the click (AC39) |
| T77 | **NEW (V3).** Send a shortcut/Ask-CEO context with a `product_id` or `finding_id` from another tenant | `404`; no data reaches the CEO (AC39, AC54, §7 rule 18) |
| T78 | **NEW (V3).** Tavily returns a result on a non-allowlisted host | Dropped and recorded; never a candidate (AC40, E47) |
| T79 | **NEW (V3).** Tavily times out / rate-limits / exhausts quota mid-run | Run `FAILED` or `PARTIAL` with queries named; CEO says discovery could not complete; manual add unaffected (AC40) |
| T80 | **NEW (V3).** A Tavily snippet says "₹2,499, in stock" | The candidate shows it only as "reported by search — unverified"; no snapshot row; price band and alerts unchanged (AC41) |
| T81 | **NEW (V3).** Static check: does any snapshot/Brain 1-input/delta/comparison/alert module import a candidate `reported_*` field? | No — the test fails the build if one does (AC41, §6.28.3) |
| T82 | **NEW (V3).** Attach a legible listing screenshot in the CEO Hub | Pipeline runs; evidence stored with `intake_channel = CEO_HUB_ATTACHMENT`; findings appear on the dashboard; the CEO explains extracted values and the comparison (AC42, AC55) |
| T83 | **NEW (V3).** Attach a blurry or tiny image | `REJECTED_LOW_QUALITY` with a named reason; no snapshot; `EVIDENCE_REJECTED_QUALITY` (AC42) |
| T84 | **NEW (V3).** Attach a photo that is not a marketplace page | `REJECTED_NOT_A_LISTING`; no snapshot (AC42) |
| T85 | **NEW (V3).** Attach the same screenshot twice | Second is an exact duplicate: no new snapshot; the CEO shows the existing result; `EVIDENCE_DUPLICATE` (AC42) |
| T86 | **NEW (V3).** Submit evidence through the `WHATSAPP` channel | `CHANNEL_NOT_AVAILABLE`; nothing stored (AC42, C36) |
| T87 | **NEW (V3).** Vision reads ₹1,299 for a listing whose true price is ₹12,999; the seller has not confirmed | Price is `PENDING`; not a Brain 1 input, delta, band entry or alert source (AC43, Q18) |
| T88 | **NEW (V3).** The seller confirms the price when the CEO asks | Stored `SELLER_CONFIRMED`; now a verified observation eligible for Brain 1 (AC43) |
| T89 | **NEW (V3).** Vision reads a `HIGH`-confidence rating | Stored and summarised; **no confirmation prompt** (AC43, D15) |
| T90 | **NEW (V3).** The seller declines to confirm a price | Field stays `UNKNOWN`; `FIELD_CONFIRMATION_DECLINED`; never reaches Brain 1 or an alert (AC43) |
| T91 | **NEW (V3).** Delivery charge is not visible in the screenshot | `UNKNOWN` with a reason; shown as such in comparison; not asked unless the seller requested a landed comparison (AC43, AC52) |
| T92 | **NEW (V3).** Trace how an `InfoRequest` reaches the seller | Only via the CEO; no CI component emits seller-facing text; answer returns through `ci.confirm_field`, idempotent on replay (AC44) |
| T93 | **NEW (V3).** "Track these three competitors" | CEO echoes the three; on the seller's yes: three `COMPETITOR_ADDED` events, entitlement checked, tenant-scoped (AC45) |
| T94 | **NEW (V3).** Reject a candidate, then run discovery again | The rejected candidate is not re-surfaced (AC45, Q21) |
| T95 | **NEW (V3).** Remove a tracked competitor, then re-add it | Excluded while removed; evidence and history retained; re-add restores (AC45, E41) |
| T96 | **NEW (V3).** Add a competitor at the entitlement cap | Refused with the named reason (AC45, C13) |
| T97 | **NEW (V3).** Monitor a SKU with two fresh competitors and one stale | Report carries as-of time and per-competitor evidence dates; the stale one is flagged and the CEO asks for a fresh screenshot; **no outbound request is made** (AC46) |
| T98 | **NEW (V3).** Run the wording eval over CI/CEO monitoring responses | Zero uses of live/real-time/continuous/"tracking" as a currency claim (AC47) |
| T99 | **NEW (V3).** Run the scheduled freshness/reminder job with network access blocked | It completes; it makes no outbound request (AC47, D16) |
| T100 | **NEW (V3).** A price field confirmed on day 6 from a day-0 screenshot | Freshness follows day 0 (inherited), not day 6 (AC48, C41) |
| T101 | **NEW (V3).** The same −9% condition is detected on three consecutive evaluations of the same snapshot pair | One alert; two `ALERT_SUPPRESSED_DEDUP` (AC49) |
| T102 | **NEW (V3).** After an alert at −9%, a new valid snapshot is −1% versus the last alerted value, then another is −5.1% | No alert for the first; an alert for the second (AC49) |
| T103 | **NEW (V3).** A qualifying alert is raised inside quiet hours; the evidence goes stale before the window ends | Held at raise time; at window end it is **not** delivered as a confirmed alert — the seller gets the freshness request instead (AC50) |
| T104 | **NEW (V3).** An other-brand listing with the same function and category; and an unrelated product | The first reaches scoring and is classed `DIRECT_COMPETITOR`; the second is `UNRELATED` and kept out of the recommended flow; existing identity-resolution outcomes are unchanged (AC51) |
| T105 | **NEW (V3).** A competitor shows a bank-card-only coupon | Recorded as an offer with its condition; **not** subtracted from effective price (AC52) |
| T106 | **NEW (V3).** Ask CEO on a finding of your own tenant; on another tenant's; on a finding with no evidence refs | Own: the CEO retrieves its evidence and continues. Other tenant: `404`. No-evidence finding: invalid, never displayed (AC53, AC54) |
| T107 | **NEW (V3).** Cross-tenant read of any V3 table row; dispatch a V3 job with no tenant context | `404`; the job fails closed (AC57) |

---

## 12. Explicit open questions

*Note (V2): §1a now records **eight** deferred items. Three are new at this Checkpoint-0 review and are deferrals, not open questions: **item 6** — real search-provider selection, pending a legal/commercial provider-record decision (C22); **item 7** — market-trend research, pending a licensed acquisition method (C29); **item 8** — Layer 2 fused alerts, pending a real CFO agent (C26). Q1–Q11 are unchanged by V2 and are not renumbered; Q12–Q17 below are new.*

*Note (2026-09-21, post-decision pass): **Q12, Q13, Q14 and Q17 are now closed** — Q12 by C31/D8 (manual seller-product form, R15), Q13 by D9 (freshness layering locked, R16), Q14 by D10 plus the `deterministic-engine.md` §5.15.1 amendment (R17), and Q17 by approval of C27 as scoped, with its legal review reclassified as production-validation blocker **V15** (R18). Numbers are **not** reused. **Genuinely open in this spec: Q1, Q2, Q3, Q4, Q7, Q8, Q9, Q15, Q16** — all pre-existing and none of them a V2/C31 regression.*

*Note: §1a records five items deferred for scope/status reasons (WhatsApp/CEO-routed invocation; the estimated-margin-range Brain-1 interface; WhatsApp evidence intake; the real vision-extraction model; a repeated cross-reference for the margin-range deferral). These are not new open questions and do not renumber Q1–Q10 — see §1a for detail.*

| # | Question | Impact |
|---|---|---|
| Q1 | **Residual WhatsApp items** `whatsapp-integration.md` itself leaves open (credit/cap treatment, mid-thread cap behaviour, decline-alert channel, post-completion messaging) — see its §13 Q3 and this spec's §6.9. | Narrower than before; no longer blocks the whole WhatsApp path (identity, invoke/revoke, and investigation-creation are resolved) |
| Q2 | **Brain 1 entitlement treatment (M13).** OP9 says shared services carry their own caps, but no key or meter exists for Brain 1. CI calls it on every run. | Entitlement spec |
| Q3 | **Paid-tier CI values** (25 URLs, 100 runs/month) are provisional and unlocked; readiness 3.3 defers final tiers (M7). | Entitlement spec |
| Q4 | **Default threshold value.** Is ±5% right for Indian marketplaces, where festive repricing is routine? | Product |
| Q5 | **RESOLVED by this pivot.** Per-URL vs per-tenant threshold — a ₹200 and a ₹20,000 product behave differently. **Resolution:** `competitor_url.price_threshold_pct_override` and `.alert_on_availability_change_override` (§5) let a seller set a per-URL value; `ci_tenant_config` remains the fallback default when no override is set (§6.3). See **R9**. | Closed — see R9 |
| Q6 | **RESOLVED/MOOT by this pivot.** Was "proxy / anti-bot infrastructure — budgeted, or accept a lower success rate?" Metrion never fetches a competitor URL under the evidence model (C2), so there is no request to proxy and no anti-bot posture to budget for. See **R10**. | Closed — see R10 |
| Q7 | **Local derivation model choice and quality — still open; unaffected by Q11's resolution.** C15 mandates local-only; on 4GB VRAM, sentiment and theme extraction quality is unproven at volume. Q11 (§12, resolved) settled *how* review evidence is acquired (reviews-tab screenshot, same evidence pipeline as everything else) — it did not touch *whether the local model is good enough* to extract sentiment/themes/rating-distribution from that screenshot at usable quality. That question is exactly this one, unchanged. **Also connects to §1a item 4** (real vision-extraction model choice, unresolved) and to V10. | 🔴 Feasibility of §6.5 and of §5.3 vision extraction |
| Q8 | **Category taxonomy mapping (BL5).** `observed_category` is captured from the seller's evidence rather than a live listing, but Amazon, Flipkart and Meesho category strings still do not agree with each other or with the fee reference store's taxonomy (`deterministic-engine.md` §5.14). A mapping layer is required and does not exist. Unaffected by the pivot. | 🔴 Blocks fee resolution for the estimated range |
| Q9 | **RESOLVED for CI's scope by C47 (V3, 2026-10-18) — event set and `ci_event` table defined in §5.7/§6.29.3.** Original text: **CI audit event set (MN9).** §6.4 requires audit logging on every execution, but no event set or artefact is defined. `auth.md` `auth_audit` is scoped to security events only. | Orchestration / observability |
| Q10 | **RESOLVED/MOOT by this pivot.** Was "`robots.txt` posture (MN15) — honour strictly, for discovery only, or out of scope for user-initiated single-page fetches?" There is no fetching left to apply a `robots.txt` posture to. See **R11**. | Closed — see R11 |
| Q11 | **RESOLVED by this decision.** Review-insight acquisition was specified in terms of "fetching raw review text" from a live listing page, which no longer exists as a capability under this pivot (C2). **Resolution:** review insight is screenshot-based, on the identical evidence model as everything else in this pivot — the seller submits a reviews-tab screenshot via the same `competitor_evidence` mechanism (§5, §5.3), a vision/derivation model extracts sentiment/themes/rating-distribution from what's visible, with the same manual-entry fallback and confidence vocabulary (`VISION_EXTRACTED`/`SELLER_ENTERED`/`DERIVED`/`UNAVAILABLE`) as the rest of the pivot. See **R12**. | Closed — see R12. Does not resolve Q7 (local model quality), which remains genuinely open and now explicitly feeds from this acquisition method. |
| Q12 | **RESOLVED (2026-09-21) — see C31, D8, §5.5.1 and R15.** Was: *"Where do `SellerProduct`'s missing fields come from?"* **Resolution: option (b) — a minimal, editable manual seller-product form**, whose values are stored as explicit `SellerProduct` field overrides, `SELLER_ENTERED` taking precedence over canonical-derived values. `rating`/`review_count` stay out of scope and `UNKNOWN`. Do not re-raise. | Closed — see R15 |
| Q13 | **RESOLVED (2026-09-21) — see D9, §6.16.2, AC27 and R16.** Was: *"How do §6.16.2's per-field freshness thresholds and D6/§6.8's 7-day OP3 ceiling coexist?"* **Resolution: both layers apply, exactly as D9 proposed.** The per-field thresholds set **only** `is_stale`; **D6's 7-day ceiling is unchanged and governs availability.** Seller-facing wording is a copy/UX task, not a spec ambiguity. Do not re-raise. | Closed — see R16 |
| Q14 | **RESOLVED (2026-09-21) — see D10, §6.16.3, AC28b, R17 and `deterministic-engine.md` §5.15.1.** Was: *"Does the price-band / outlier computation belong in CI or in the deterministic engine?"* **Resolution: the engine.** `deterministic-engine.md` was amended with `compute_price_band` (§5.15.1); CI supplies `DERIVED` competitor prices and renders the result. Do not re-raise. | Closed — see R17 |
| Q15 | **NEW (V2). Does a discovery run consume a CI run unit, or a separate meter?** D12 provisionally says one discovery run = one CI run unit against C13's runs/month, to avoid inventing a second meter before the entitlement spec exists. But a discovery run's cost profile is entirely different from an evidence-upload run's — it makes up to 20 paid provider queries, where an upload makes none — so one shared meter may misprice both. Intersects Q2, Q3 and `billing-and-pricing.md` Q4/V4, which already flag that CI's provisional per-agent numbers must be reconciled. | Entitlement / billing spec. D12 |
| Q16 | **RESOLVED by C47 (V3, 2026-10-18).** Original text: **NEW (V2). What is the audit event set for discovery?** Q9 already flags that CI has no defined audit event set. Discovery widens it materially: a query leaving Metrion to a third party, a seller approving or rejecting a candidate, a provider error, a retention extension under C27, and a privacy-filter drop under §6.11 rule 3 are all events a seller or a regulator may reasonably ask about. `ceo-agent-orchestration.md` C7 names `agent_run` as the artifact for agent invocations, but a per-query/per-decision event set is finer-grained than a run. **Not resolved here** — flagged so it is not discovered late. | Orchestration / observability / DPDP. Extends Q9 |
| Q17 | **RECLASSIFIED, not open (2026-09-21) — moved to V15, see R18.** Was: *"Does the C27 snippet carve-out survive DPDP review?"* **C27's design is approved and locked** — the snippet carve-out, its 90-day default, the named-reason extension and the "source evidence expired" behaviour are all decided and buildable as specified. What remains is a **legal-review-before-launch item, not a design ambiguity**, and it is therefore tracked as **production-validation blocker V15**. Do not re-raise here. | Closed as a question — tracked at V15 / R18 |
| Q18 | **NEW (2026-10-02, evidence-backed). Can a `VISION_EXTRACTED` price be trusted at §6.16.1's `HIGH` at all?** §6.16.1 assigns `HIGH` to a field "extracted cleanly ... with no ambiguity flag from the model". The wired model (llava 7B via Ollama, `evidence/vision_extractor.py`) **never emits an ambiguity flag**, so every vision price is `HIGH` by construction, and `alerts/layer1.py` presents it to the seller as a `HIGH`-confidence validated fact. Measured with the production prompt/parser on a synthetic set of known prices (`packages/competitor-intelligence/scripts/vision_price_eval/`, small n, one layout — evidence, not a population accuracy): price correct **13/31**; by length of the true price 2-digit 3/6, 3-digit 9/13, **4-digit 1/8, 5-digit 0/4** (dropped digits: ₹12,999 → ₹1,299, ₹1,999 → ₹199); MRP correct **0/31**; fields absent from the image reported anyway (rating 55%, rupee discount 23% — and `effective_price = listed − visible_discount`, so a hallucinated discount moves the price delta). Not fixed by resolution (6/9 at 1280 and 640 px), `format: json` (3/12 on the 4-5 digit set), or `temperature: 0` (1/12). A second price-only read by the same model is **not** a validator (4 of its 7 agreements were wrong). A wrong price feeds price events, Layer 1 alerts and the price band unchallenged. **Options (decision needed — not implemented):** (a) cap vision-extracted money fields below `HIGH` and make them alert-ineligible until `SELLER_ENTERED` confirmation (behaviour change to §6.16.1/§6.17; most real listings are ≥ ₹1,000); (b) route vision money fields through the existing `PENDING_MANUAL_ENTRY` path as pre-filled suggestions; (c) add an independent signal (OCR, or a cropped high-resolution read of the price region) before any trust tier is assigned; (d) re-run the evaluation on real seller screenshots first (Q7) — the synthetic set may be harsher or kinder than real listings. Recommended: (d) immediately, then (a) or (b) until (c) exists. | 🔴 Trust (§6.16.1), alerts (§6.17), price band (§6.16.3) |
| Q19 | **NEW (V3). Does a CEO Hub screenshot upload consume a CEO call, a CI run unit, or both?** C20 said a dashboard upload consumed no CEO call; the upload now arrives inside a CEO turn. **Recommendation:** the turn is metered as any CEO turn, and the intake is metered as **one CI run unit** (the D12 unit), with no second meter. Extends Q2/Q15. | Entitlement spec; CP3 |
| Q20 | **NEW (V3). Confirm the reversal of §6.13.2's `NOT_A_MATCH → REJECTED` gate (C43, D17).** The 2026-10-18 audit shows the shipped gate rejects every other-brand competitor. **Recommendation:** approve the split (identity unchanged, rejection moves to `relationship_class = UNRELATED`). It overrides a locked rule, so it is **not built until the owner confirms**; CP2 is blocked on it. | CP2 |
| Q21 | **NEW (V3). Does a rejected candidate stay rejected permanently, or expire (e.g. 90 days)?** **Recommendation:** stays rejected until the seller asks to reconsider. | CP5 |
| Q22 | **NEW (V3). What makes a review finding "significant"?** `review_finding_min_sample` is provisionally 10, and a theme-frequency floor is undecided. **Recommendation:** minimum sample 10 and a theme in at least 20% of the sample, both tenant-configurable, and always shown as N of M. Evidence-backed tuning follows real seller data. | CP5 |
| Q23 | **NEW (V3). Should any alert bypass quiet hours** (e.g. a large price drop or a stock-out)? **Recommendation:** no in V3 — one rule, held and delivered at window end, revisited with seller feedback. | CP5 |
| Q24 | **NEW (V3). Does storing a seller-stated product-profile value or a threshold through the CEO need a plan-approval card, or is an echo-back enough?** **Recommendation:** echo-back, no approval card (low consequence, editable, never destructive); competitor remove and bulk add keep their confirm step (C39). Subject to `ceo-approval-workflow.md`. | CP4 |

### V3 build record — what was built, how it deviates, what is not built (updated 2026-10-19)

Recorded so nothing is silently resolved. **Built and verified on branch `feat/ci-upgrade` (uncommitted):** Tavily provider, listing-URL canonicaliser and daily cost cap (CP1); relationship classification, the split identity/relationship gate, rejected-candidate non-resurfacing, band eligibility (CP2); quality gate, duplicate detection, consequential-field policy, intake pipeline, confirmation settlement, `PENDING`-price exclusion from every consequential read (CP3); watchlist add/remove/approve/reject, monitoring report, wording rule, CEO actions and chat routes (CP4); alert dedup, quiet hours, held-alert delivery with freshness re-validation, and the housekeeping scheduler (CP5); read-only dashboard and `GET /ci/workspace` (CP6); the CEO conversations for screenshot intake, confirmation, correction, add-by-link, approve/reject by number and alert settings; persistent `ci_finding` ids with Ask CEO by id (C46); Brain 1 `compute_competitor_effective_price` (`deterministic-engine.md` §5.15.2) and the "What a buyer pays" column; the CI narration checks inside the CEO composition gate (`tests/unit/test_ci_narration_safety.py`) and CI cases in the `ceo_eval` set. Migrations `20261018_0001`, `20261018_0002`, `20261019_0001` (competitor-intelligence package) and `20261014_0021` (backend) are applied on a clean Postgres 16 + pgvector database and exercised by the integration tests.

**Verified results (this machine, 2026-10-19):**

- Backend integration against a real Postgres (Docker, port 5544): full suite run once on the final code minus the one slow file: 2316 passed, 4 skipped, 1 xfailed, 7 failed. Four of the seven were stale pins or missing registrations and are fixed and re-verified (privilege-boundary guard: the four new CI tables were app-deletable, now revoked; specialist-readiness pins; tenant-data-inventory classification of the new CI tables). Three (`test_pi_payload_pins` and two in `test_pi_usage`) are existing Product Intelligence failures in files this work did not touch: their Tavily test doubles do not accept the `include_domains` argument PI's supplier lookup now passes. They are not CI regressions and are left unfixed. The slow safety-gate file (700 hostile-classifier cases) was run separately: after adding `ci.discover_competitors` to its approval-required set it is re-verified (see the build report). Later targeted re-runs after the final fixes: CEO and CI conversation files 62 passed, approval workflow 44 passed, privilege boundary 27 passed. Backend unit suite: 4948 passed, 6 xfailed. CI package suite including its database tests: 500 passed. Calc-engine including its database tests: 486 passed, 1 skipped.
- CI package unit suite: 422 passed. Calc-engine unit suite: 391 passed, 1 skipped.
- Frontend: tsc clean after deleting the stale `.next` and regenerating route types; eslint 0 errors (2 old warnings); vitest 494 of 495 passed (run with a 60 s per-test timeout because the machine was loaded; the earlier failures were 5 s timeouts). The one failure is `app/premiumLayer.scope.test.ts`, which fails identically with this work stashed (existing, unrelated).
- Live Tavily smoke test (one search, generic keywords, no seller data): 5 leads returned, all on allow-listed marketplace hosts, canonical single-listing URLs, no price fields taken from snippets. Not repeated; no population claim.
- Local Ollama vision, end to end through the CEO chat (opt-in test `tests/integration/test_ci_local_ollama_e2e.py`): on the owner's two real Amazon listing screenshots (a ₹279 bottle, a ₹2,299 watch, both free delivery) and a generated reviews image, the intake read the page, held price, discount and offers until the seller confirmed, took the seller's correction (including an explicit 'discount 0'), and the dashboard then showed the engine's effective price and buyer total with free delivery counted as an observed zero and the card and coupon offers named as not counted. The reviews screenshot produced stored themes from 5 reviews, labelled DERIVED, and a later complaints question was answered instead of being mistaken for naming the image. Two real bugs were found and fixed by this run. The small model also misreads: it invented a ₹260 discount on the watch and added noise words as themes, which is why confirmation is required.

**Deviations from this spec, decided while building (all accepted by the owner on 2026-10-18 unless noted):**

1. **Soft removal reuses `ARCHIVED`**, not a new `REMOVED` status (§6.24): every ACTIVE-only query already excludes it; who/when/why are in `removed_*`.
2. **Provisional relationship** (§6.27.1): with category unknown, the product axis alone may name `DIRECT_COMPETITOR`/`FUNCTIONAL_ALTERNATIVE`; the discovery-time product axis is a deterministic title-token overlap that returns `UNKNOWN`, never "different".
3. **Price-band eligibility (decided):** `SAME_PRODUCT`, `VARIANT` and `DIRECT_COMPETITOR` that are evidence-verified enter the band; `FUNCTIONAL_ALTERNATIVE` is shown but excluded.
4. **`ci.discover_competitors` is `SELLER_DATA_OUT`** (the seller's product search terms go to Tavily), so it is approval-gated like `pi.discover`; from chat it depends on the stored-approval-plan workflow being enabled (`CEO_APPROVAL_ENABLED`). Asking again for the identical search while its plan is open and unexpired re-shows that plan instead of creating a second card; an approved plan stays single-use (approval is bound to the plan hash and expiry, C8), so a repeat after approval is a new request.
5. **Dedup/quiet hours are applied when a price event is written** (`alerts/raise_alert.py`), recorded as `competitor_price_event.alert_suppressed_reason` and `ci_held_alert`; Layer 1 reads hide suppressed and held events. The observation itself is never altered. **Quiet-hours timezone (decided):** the seller's configured tenant timezone, else `Asia/Kolkata`; the reply names the zone used.
6. **Competitor watchlist limit (decided):** a nullable per-tenant `ci_tenant_config.max_active_competitors` plus an operator default `CI_DEFAULT_WATCHLIST_LIMIT`. Neither is set by default, so no limit applies and none is invented; the application role can read the column but not write it. Subscription-plan limits are still undecided (C13/Q3).
7. **Bulk add is echo-confirmed (C39, decided):** a message with more than one link is answered with the list and the product, and nothing is added until the seller says yes. A single link is added directly.
8. **Q19–Q24 recommendations were adopted as built** (one CI run unit per intake; rejected candidates stay rejected; review-finding minimum sample 10; no quiet-hours override; echo-back instead of an approval card for thresholds) — still subject to owner confirmation.
9. **Database security finding fixed while verifying:** migration `20261012_0018` made `ci_tenant_config` SELECT-only for the application role and ran after the competitor-intelligence column grants, so on a fresh database saving quiet hours failed with `permission denied`. `20261014_0021` re-grants exactly the seller-editable alert columns after it. Existing databases are unaffected only if they were upgraded in that order; re-run the backend migration head on any such database.

**Remaining limitations (explicitly open, none hidden):**

- **WhatsApp** remains a placeholder (`CHANNEL_NOT_AVAILABLE`).
- **No real-LLM narration eval was run** (owner instruction: local models only). The CI narration cases (`CI-NR-01..11`) are written in `ceo_eval/fixtures/composer.jsonl` but have never been run against a model; the composition gate itself is tested with scripted adversarial models.
- **Local-model read quality is limited** (Q7, Q18): the small local vision model misreads prices; this is why consequential fields are held until the seller confirms. Real-seller-screenshot accuracy is unmeasured.
- **Production validation:** V15 (DPDP review), V16 (Tavily terms), V17–V18, and a measured Tavily cost per discovery run are not done.
- **Sidebar/logo shell** was not visually re-verified after the dashboard replacement (the dashboard itself was verified at desktop and mobile widths).
- The seven-day freshness ceiling and the scheduler's 15-minute cadence (`CI_SCHEDULER_INTERVAL_SECONDS`) are defaults, not tuned on real traffic.

#### Addendum 2026-10-20 — manual acceptance rounds and completion phases P0–P4 (owner decisions of record)

- **Watchlist cap.** At most 5 ACTIVE tracked competitors per seller across all marketplaces (`ci_tenant_config.max_active_competitors`, else `CI_DEFAULT_WATCHLIST_LIMIT`, else 5), enforced atomically inside the write transaction (per-tenant advisory lock). Pending discovery leads and stopped competitors do not count; "ALL" respects it. The CEO and the dashboard show "N of 5".
- **Conversation.** "Track my competitors" offers names plus ALL; tracking a discovered lead by name resolves that lead's own listing; a seller with one product has it selected; exactly one tracked competitor is assumed for an unnamed screenshot; an unreadable price asks for a clearer screenshot; a partial confirmation keeps the price and stores left-out fields as UNKNOWN; a displayed percentage is never a rupee discount.
- **Price percentages (deterministic-engine.md §5.15 amendment).** `PRICE_POSITIONING` carries the rupee gap, `gap_pct` (relative to the competitor's price) and `gap_pct_of_seller_price`; the CEO labels each denominator.
- **Unbranded leads** are ranked by title relevance; identity stays UNCONFIRMED and is never promoted.
- **CI → CFO.** A pricing decision starts the finance session prefilled from verified data (competitor, product, profile price, the competitor's verified price beside a named target, single fee row, remembered GST basis) and asks only what is missing; a cost is never invented.
- **CI → CEO → CMO (slim-cmo-agent.md §6.7 implemented).** For the listing-writing actions the CEO reads the seller's fresh COMPLETE `competitor_listing_insight` rows (requires `agent.ci` and a passing CI entitlement check; no CI unit consumed) and freezes their ids into the plan card (`ci_insight_ids`). CMO re-checks that each id is the seller's own (404 otherwise), appends derived single words only to the prompt as MARKET CONTEXT, and records `input_mode = CEO_BROKERED_CI` with `ci_inputs_snapshot` only when they were actually used. The saved competitor title / description / bullets are used solely for a deterministic originality check (5-word shared run, or ≥70% word overlap between units, fails); a competitor brand word, or any search-volume / ranking / popularity / conversion claim, also fails. A failed informed draft is rewritten from the seller's own facts alone and the result says so. Competitor prices are never read. No usable insight, stale (>30 days, `CMO_CI_INSIGHT_MAX_AGE_DAYS`), or no `agent.ci` → independent mode with a one-line note on the plan card. "Improve my listing" routes to title options.
- **Reviews, option B.** Review themes come only from review screenshots or seller-confirmed text with a real sample size (`review_finding_min_sample`). A reviews question with no saved review evidence gives deterministic review-page links built from the listing links the seller supplied, says that no page is read and a search snippet is not a review, and asks for a screenshot. Nothing is scraped, searched or invented.
- **Dashboard.** Header shortcuts remain CEO shortcuts: research, monitor, and "Track a competitor".
- **Tests.** `test_ci_p0..p4`, `test_ci_manual_regressions*`, `test_ci_end_to_end_flow`, `slim-cmo tests/unit/test_ci_inputs.py`, and the opt-in local-Ollama evals (`CI_LOCAL_OLLAMA_E2E=1`, `CMO_LOCAL_OLLAMA_EVAL=1`; the CMO eval: informed draft usable in 3 of 3 runs, nothing delivered ever failed the originality/claims check).
- **Top-15 discovery (owner decision 2026-10-20).** "Find my competitors" surfaces the top 15 matches (`max_recommended_candidates` default 15; migration `20261020_0001`), numbered best match first, with the seller's free slots and who holds the others. The seller picks up to their free slots (never more than 5 tracked in all); a pick that does not fit adds nothing and says so; a full list asks the seller to stop tracking one first, then pick. Picked leads become tracked competitors on the list.
- **Category-driven discovery and the pick card (owner decision 2026-10-20).** "Find my competitors" first asks WHICH of the categories in the seller's business profile (one or more, or ALL; numbers or names; a product name still works). One search runs per chosen category (`category:<name>` runs, merged into one ranked list, each lead tagged with its category; identity stays UNCERTAIN). The top 15 are shown as a numbered list AND a `CANDIDATE_PICK` card (`investigation_message.choices`, allowed on a CEO ANSWER by migration `20261020_0023`) with check boxes up to the free slots; Save sends `track <numbers>`, so the same cap checks apply. Picked leads are tracked until the seller removes them, and the dashboard groups them under "Category: <name>".
- **Manual round 4 (owner, 2026-10-21).**
  - *Genuine leads.* `discovery/lead_quality.py`: books / keyword-dump / too-short titles are never surfaced; recognisable brands rank first, then any brand, then title match; at most 2 leads per brand; a tracked competitor is named by its brand-first cleaned title (not "water steel bottle"). This removes plainly-not-a-competitor leads; it cannot prove a business is genuine or successful, and a listing's existence is not re-checked (nothing is fetched). Own-website competitors are not searched (marketplace domains only).
  - *Check-box cards.* One generic `PICK` card (`ci_conversation.pick_card`, rendered by `PickCard.tsx`): categories to search, the top matches to track, the tracked competitors (details / verify / stop), and "which competitor is in this screenshot" (radio, with "None of these"). Pressing a button sends the text its template makes, so the same checks run as for typed text. Migration `20261021_0024` lets a CEO ANSWER carry it.
  - *No link prompts.* The CEO never asks the seller for a listing link; it points to "find my competitors" and the tick boxes. A pasted link is still understood, silently.
  - *Conversation focus.* `ci_conversation.focus_competitor`: "this competitor", "it", "that screenshot", "I am talking about this one" mean the competitor most recently named in the last 14 messages; price, facts, review-sample and screenshot answers use it, and all tracked competitors are read whichever product or category they are grouped under. A message that names no product no longer produces "Which product (SKU)?".
  - *Open questions.* "Cancel ..." (short) closes the open guided question; a sentence of 8+ words that is not a free-text answer is a new request, never swallowed.
  - *Fewer questions.* Skip is never the recommended choice; marketplace choices are the ones in the business profile; the product's saved title/brand/size are not asked again; the title question offers the product name in one click; the use and search-word detail questions were dropped for titles; the four extra per-unit finance costs are one question ("do you know them?"), and "no" leaves them unknown (never guessed).
  - *CMO.* "Analyze my competitors' titles, keywords and selling points" is answered from the saved listing insights (derived words, sample size, no search-volume or ranking claim); "Improve my ... listing ..." routes to title options (competitor themes brokered as before).
  - *Dashboard.* No tabs and no "Ask CEO" labels: each competitor has Verify price / Stop tracking, each lead has Track this, each finding has Explain this, reviews have Add more reviews; "Unavailable" became "Needs a screenshot"; raw relevance scores became Low / Medium / High; the history became a per-day activity summary; a category group shows "Compare your price" instead of a band error; the Monitor button was removed.
- **Not done / known.** Real-LLM evals; WhatsApp; Tavily review-source discovery (links are derived from the seller's own listing links instead, at no search cost); two pre-existing float-literal lint failures in `slim_cmo/generation/prompts.py` (description target) and three Product Intelligence Tavily-fake tests are unrelated to this work.

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Review-text retention boundary | C14, C15, §6.5 — transient, local-only, never persisted or transmitted |
| R2 | Where the margin band is computed | C17, §5.2, §6.7 — Brain 1 only; CI supplies a provenance-tagged observation set |
| R3 | Whether a dashboard button is a CEO path | C20, §6.4 — direct execution path; `agent.ci` alone; no CEO call consumed |
| R4 | Where fee references live | C18 — versioned backend reference store consumed by Brain 1 |
| R5 | Snapshot retention | C19, §6.8 — configurable, default 90 days; revisit after DPDP |
| R6 | Competitor listing copy | C16, §6.6 — expression when scraped (moot, nothing is scraped); seller-submitted title/description/bullets are now a permitted carve-out, plus derived attributes as before |
| R7 | Arithmetic boundary | Front matter + AC1 — observed-fact deltas permitted; all financial arithmetic in Brain 1 |
| R8 | WhatsApp identity, invoke/revoke, and investigation-creation (was Q1) | `whatsapp-integration.md` now exists and resolves all three: identity via `bound_by` (§6.9, `whatsapp-integration.md` C8), `WHATSAPP_CONFIRM` re-entering CI's own §7.1 chain (§6.9), and implicit investigation creation on first contact (§6.9, `ceo-agent-orchestration.md` §6.7). Only billing-cap interaction and post-completion messaging remain open — narrowed into the new Q1. |
| R9 | Per-URL vs per-tenant alert threshold (was Q5) | `competitor_url.price_threshold_pct_override` / `.alert_on_availability_change_override` (§5) let a seller override the tenant default per competitor; `ci_tenant_config` remains the fallback (§6.3). |
| R10 | Proxy / anti-bot infrastructure (was Q6) | **Moot, not merely answered.** Metrion never fetches a competitor URL under the evidence model (C2) — there is no outbound request to protect or proxy. |
| R11 | `robots.txt` posture (was Q10) | **Moot, not merely answered.** No fetching occurs, so no `robots.txt` posture is ever consulted or needed. |
| R13 | **NEW (V2).** Whether CI may discover competitors | **Reversed, deliberately and on the record.** The V1 non-goal "competitor discovery (CI never finds competitors, the seller supplies them)" is superseded by **C21** at the Checkpoint-0 review, 2026-09-21. Discovery finds **candidates only** (C23); manual URL entry is a permanent fallback and is never removed (C21); no marketplace URL is ever fetched (C2, untouched). Do not re-raise this as an inconsistency — it is a decision reversal with its own record, in the same form as C2's acquisition pivot and D7's short-link resolution. |
| R15 | **NEW.** Where `SellerProduct`'s non-canonical fields come from (was Q12; D8) | **A minimal, editable manual seller-product form — decided 2026-09-21, C31.** New UI and API surface (a seller-product-profile form) capturing category, attributes, keywords, current listing price and fulfillment type, stored as explicit `SellerProduct` field overrides (§5.5.1). Two legitimate sources now exist — canonical-derived and `SELLER_ENTERED` — with **seller-entered superseding** on disagreement, mirroring §5.3 rule 4 / `evidence/merge.py::apply_manual_overrides` on the competitor side. **The KNOWN/UNKNOWN discipline is unchanged:** an unfilled field is `UNKNOWN`, never inferred, never defaulted. `rating`/`review_count` are deliberately out of the form's scope and stay `UNKNOWN`. Residual *validation* items (completion rate, price currency) live at V12, not here. |
| R16 | **NEW.** Freshness layering (was Q13; D9) | **Both layers apply — decided 2026-09-21.** §6.16.2's per-field thresholds (24h price/availability, etc.) set **only** `is_stale` on a fact. **D6/OP3's 7-day ceiling is the hard rule and is unchanged**: past 7 days the current answer is reported unavailable and fires no alert. Where the two meet, D6 governs availability. Nothing about existing 7-day behaviour changes; the 24h flag layer is additive new work. |
| R17 | **NEW.** Home of the price-band / outlier arithmetic (was Q14; D10) | **The deterministic engine — decided 2026-09-21, and `deterministic-engine.md` amended accordingly.** The quartile/IQR/fence/outlier computation is `compute_price_band`, `deterministic-engine.md` §5.15.1. CI supplies the tenant's tracked competitor prices as `DERIVED` inputs plus the configured minimum, and renders the returned `metric_result` rows citing their `engine_result_ref` — the same pattern as `compute_price_positioning`/`compute_repricing_scenario`. **CI never computes a quartile, IQR, fence or outlier flag** (AC28b, T56). §6.16.3 keeps the product rules only. |
| R18 | **NEW.** Whether the C27 snippet carve-out is approved (was Q17) | **C27 is approved and locked as scoped — decided 2026-09-21.** The design is not in question and is buildable as written. The remaining DPDP/privacy legal review is a **pre-launch validation item, not a design ambiguity**, and is tracked as **V15**. Do not re-open C27 as a question; if legal review later refuses the carve-out, that is a new decision recorded on the record, not a rediscovery of this one. |
| R14 | **NEW (V2).** Whether an implementation agent may choose a search provider | **No — decided, not open.** C22 and §1a item 6: interface + mock first; a named provider requires the §6.10.1 provider record and explicit human approval. "Clean ToS" by reputation is not a basis for selection. |
| R19 | **NEW (V3).** Whether the dashboard is a seller input surface (was R3's "a dashboard button is a CEO path") | **No — superseded by C32 (2026-10-18).** The CEO Hub is the only seller conversational and input surface; the dashboard is read-only, with two CEO shortcuts and Ask CEO buttons that pass ids, not content (C33). |
| R20 | **NEW (V3).** Which search provider (R14) | **Tavily — approved by the owner 2026-10-18 (C34).** The §6.10.1 record and commercial/terms validation still follow (V16). A Tavily value is a lead, never an observation (C35). |
| R21 | **NEW (V3).** Whether identity and competitive relationship are one concept | **Separate (C43).** Identity answers "same product?"; relationship answers "how does it compete?". The gate split awaits owner confirmation as Q20. |
| R22 | **NEW (V3).** Whether "monitoring" implies watching competitors | **No (C40).** It is re-evaluation of stored evidence with an honest as-of stamp; Tavily refreshes discovery leads only. |
| R12 | Review-insight acquisition mechanism (was Q11) | **Screenshot-based, on the same evidence model as everything else in this pivot (§6.5, C6).** The seller submits a reviews-tab screenshot via the same `competitor_evidence`/`research_session_id` mechanism as listing evidence (§5.3, §6.1); a vision/derivation model extracts sentiment, themes and rating distribution from what's visible, with the same `SELLER_ENTERED` manual-entry fallback for unclear or missing fields, and the same confidence vocabulary (§5.1). Not a new acquisition mechanism — C2 applied to a different evidence type. C14/C15's transient/local-only rule now scopes to the *review text read off the screenshot*, not the screenshot's stored image bytes, which follow the ordinary evidence-image retention policy (§6.8). **Q7 (local model quality) is unaffected and remains open.** |
