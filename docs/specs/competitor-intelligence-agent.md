# Metrion — Competitor Intelligence Agent (CI) Specification

**Status:** Draft for review — **revised 2026-09-21 for CI V2 (Checkpoint 0).** The V2 revision is **additive**: it adds discovery, identity resolution, relevance scoring, customer-voice snippet retention, the two-layer alert model, the price-band formula and the generalized handoff contract (C21–C30, D8–D13, A6–A9, §5.4–§5.6, §6.10–§6.20). It changes **one** prior decision — the competitor-discovery non-goal, reversed on the record by **C21** — and leaves the evidence-upload pipeline (C2, C4, C16, the §5.1 confidence vocabulary, and the `competitor_snapshot`/`competitor_evidence`/insight data model) exactly as written.
**Prerequisites:** `deterministic-engine.md` (all margin math) · `data-foundation.md` (provenance, confidence) · `auth.md` (permissions) · `whatsapp-integration.md` (WhatsApp identity, invoke/revoke, and investigation-creation mechanics — CI decides none of this itself; §6.9 records only what that spec resolves)

**The arithmetic boundary (B8).** CI may compute **deltas over its own observed facts** — a price change between two snapshots it captured. CI may **never** compute anything financial: no margin, fee, profit, tax or cost figure. All of those originate in Brain 1. CI normalises observations into a provenance-tagged input object, passes it to Brain 1, and reads the result back unchanged. CI holds no financial formula.

**Boundary restated for V2 (unchanged in substance, two clarifications).** (a) Where a seller's own current price is in hand, **CI supplies `competitor_prices[]` as `DERIVED` inputs to the existing engine functions `compute_price_positioning` and `compute_repricing_scenario` (`deterministic-engine.md` §5.15)** and renders their `metric_result` output unchanged, citing the returned `engine_result_ref`. This spec **does not restate or reimplement** that arithmetic; §5.15 is the authority for it, including its `UNAVAILABLE` rules and its explicit non-margin-awareness. (b) The **price-band / outlier computation (§6.16.3)** is arithmetic over money values and therefore, under the project's hard rule, **does not belong in CI — RESOLVED and LOCKED (2026-09-21, D10/R17).** The quartile/IQR/fence/outlier arithmetic lives in `deterministic-engine.md` **§5.15.1 `compute_price_band`**. CI supplies the tenant's tracked competitor prices as `DERIVED` inputs — the identical pattern it already uses for `compute_price_positioning`/`compute_repricing_scenario` — and renders the returned `metric_result` rows unchanged, citing the returned `engine_result_ref`. **CI never computes a quartile, an IQR, a fence or an outlier flag.**

---

## 1. Confirmed decisions

| # | Decision |
|---|---|
| C1 | **Marketplaces:** Amazon, Flipkart and Meesho, all three at V1 (readiness §1, Product shape — Marketplaces). |
| C2 | **Acquisition — REVISED (locked pivot): seller-submitted evidence, not fetching.** The seller uploads a screenshot of a competitor listing via Metrion's own web dashboard. A vision model extracts structured fields from it, with a **manual-entry fallback** for anything unclear or missing. Multiple screenshots may be submitted per research session and are **merged** (§5.3, §6.1). Metrion's backend **never fetches** a competitor URL, on demand or otherwise. No continuous crawling, no bulk discovery, no live monitoring, no scraping in any form. **See §1a** — WhatsApp evidence intake is a documented **future** channel, once a BSP is contracted; only dashboard upload ships in this pass. |
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
| C20 | **Direct CI execution (B7).** A dashboard **evidence-upload** CI run (trigger `EVIDENCE_UPLOAD`, §6.4, §5) is a **direct CI execution path**, not a CEO conversational route, and does not consume a CEO call. It enforces the full check set in §6.4. **See §1a — only this direct path ships in the next implementation pass.** |

### V2 additions (C21–C31) — Checkpoint-0 review, 2026-09-21

C21–C30 come from the externally-reviewed **CI V2 Master Specification** (five review rounds) accepted at this Checkpoint-0 spec review. They are **additive**: none of them alters C2, C4, C5, C14, C15, C16 or the evidence-upload pipeline, the confidence vocabulary, or the `competitor_snapshot`/`competitor_evidence`/insight data model, all of which stand exactly as written above. **C31 is later (2026-09-21, same review cycle): it records the resolution of D8/Q12 after the decisions were made by the user, and is additive on the same terms.**

| # | Decision |
|---|---|
| C21 | **Competitor discovery — DECISION REVERSAL (locked).** The V1 non-goal *"competitor discovery (CI never finds competitors, the seller supplies them)"* is **superseded**. CI now generates research queries from the seller's own product and surfaces **candidate** competitors for seller review. This is a real reversal of a locked non-goal, recorded here in the same way C2 recorded the scraping→evidence pivot and D7 recorded the short-link resolution — **not** a silent edit. **Reason:** the Checkpoint-0 review (2026-09-21) accepted the V2 Master Specification's finding that manual-URL-only entry makes CI a screenshot-processing utility rather than a competitive-intelligence product. **Two hard limits ride with the reversal, and neither is negotiable:** (a) discovery finds *candidates only* and never populates competitive intelligence (C23); (b) **manual URL entry remains a permanent, always-available path**, independent of discovery, and is never removed or deprecated. §4's non-goal list is amended accordingly. |
| C22 | **Search acquisition is contract-first, and no provider is named in this spec.** Discovery uses a **licensed search provider**, never scraping, never a marketplace fetch (C2 is untouched: search results are *leads*, never live marketplace facts). **No named provider may be selected or integrated by an implementation agent on its own initiative.** Implementation builds, in order: domain models → a `SearchProvider` interface → a `MockSearchProvider` returning fixture data → the discovery pipeline against that interface. Only after a **provider record** (§6.10.1 — allowed use, data retention, redistribution/display rights, attribution, region, query limits, cost) is completed for at least two candidates and **explicitly approved by a human** may a real adapter be written behind the interface. Selecting a provider is a legal/commercial decision, not an engineering one. **See §1a item 6 — deferred.** |
| C23 | **Discovery is not intelligence (the load-bearing V2 rule).** Search discovery finds candidates; it does **not** populate live competitor intelligence. **Every field used in comparison (§6.19), customer-voice mining (§6.18.2) or alerting (§6.17) must trace to an evidence-bearing source — a seller screenshot or a licensed data provider — never to a search snippet alone.** A candidate that has passed discovery, identity resolution and relevance scoring is still an *unevidenced candidate*: it is shown as **"Approved — awaiting evidence"**, a distinct and visible state, and is **never silently compared, mined or alerted on as if evidence existed.** The acquisition matrix in §6.10.2 is the field-by-field statement of this rule. |
| C24 | **Product/entity identity resolution is a distinct, required pipeline stage.** A candidate is not assumed to be the competitor's actual product. Identity resolution extracts brand, model/variant, pack size and bundle status and compares them against the seller's own product record, emitting an explicit `EXACT_MATCH` / `LIKELY_VARIANT` / `UNCERTAIN` / `NOT_A_MATCH` field — never a silent assumption of exactness. Gating per §6.13.2. The entity model separates **Brand · Seller · Product · Listing · Competitor** (§6.13.3). |
| C25 | **Relevance scoring uses the locked eight-axis algorithm in §6.14 — implemented exactly, not reinvented.** Eight axes scored 0/1/2, summed to a max of 16, banded `HIGH`/`MEDIUM`/`LOW`. Every `UNKNOWN` or `CONFLICTED` axis scores **0** and is never guessed upward, including the seller-side-unknown case. A band is **never rendered without its per-axis breakdown**. **Relevance, identity-match confidence, evidence confidence and freshness are four separate attributes and are never collapsed into one number or badge** (§6.14.5). A score computed before evidence exists is labelled **"Discovery relevance (provisional)"** (§6.14.0). This is a first-pass rule set, tunable post-launch with real seller feedback, but implementation builds *this* scheme. |
| C26 | **Two-layer alert model.** **Layer 1 (CI, observational only):** *"Competitor X dropped price 8% (₹999 → ₹919)."* CI computes and states nothing about margin, contribution or break-even. **Layer 2 (CEO-composed fusion):** the CEO orchestrator receives the CI alert, requests margin/contribution impact from CFO, and delivers the combined alert. **CI produces Layer 1 only**, and only for evidenced candidates (C23). The fused alert is never something CI computes internally — this is the structural enforcement of C9/C17/AC1. **Layer 2 is DEFERRED — see §1a item 8:** no CFO agent implementation exists in this codebase (CEO Hub reports CFO as `NOT_CONNECTED`). |
| C27 | **Customer-voice mining retains evidence-snippet references under one rule, not two.** Themes are reported with stated frequency (*"this theme appeared in N of M sampled reviews"*, never "some people complained"). A theme's supporting **evidence-snippet reference** — the cited one-to-two-sentence extract, its theme, the source competitor/listing reference, and the extraction date — is retained for a **configurable default of 90 days from extraction**, tenant-aware, extendable per competitor by a seller or Metrion admin for a named reason, and **never exceeding any retention ceiling imposed by a source or licensed provider's terms**. On expiry the **aggregate theme remains visible** but is marked **"source evidence expired"** — not deleted, not silently kept traceable forever. This mechanism never retains the raw screenshot image (that follows §6.8's own policy) nor full review text beyond the cited snippet. **This narrows C14, it does not contradict it:** C14 forbids a review-text *corpus* and any granular body beyond the derived aggregate; C27 permits exactly one bounded, auditable exception — the specific snippet a theme cites — under an explicit expiry. Where C14 and C27 appear to disagree, **C27 governs the cited snippet only** and C14 governs everything else. |
| C28 | **Generalized `Evidence` / `CIHandoff` contract, routed `CI → CEO` only.** Every finding type (price, availability, listing content, review theme, differentiation, market position) traces through one common `Evidence` record carrying a `source_type` discriminator — `SELLER_SCREENSHOT | LICENSED_PROVIDER | REVIEW_SNIPPET` — of which the C27 snippet reference is one subtype. Schema in §5.6. **Routing is `CI → CEO`, never `CI → CFO` or `CI → CMO` directly** — this is C11 restated, not a new rule, and must not regress. A `CIHandoff` payload is **never shown to the seller as-is**: it is always composed into a Competitive Brief (§6.20.2) or a CEO-orchestrated cross-agent alert first. |
| C29 | **Market trend signals are DEFERRED, explicitly.** Any trend claim must state geography, time window, comparison baseline, search term(s), source and data freshness — a bare *"demand is rising"* is meaningless and is never emitted. The common `pytrends` route scrapes Google Trends' public frontend: **the same acquisition-risk shape as marketplace scraping, aimed at a different target**, and therefore forbidden under C2's reasoning. Trend research waits for a licensed/approved acquisition method. **This deferral does not block discovery (C21–C22), which has its own separately-resolved licensed search path.** See §1a item 7. |
| C30 | **`SellerProduct` is a read-only baseline contract with explicit `KNOWN`/`UNKNOWN` per field.** Every seller-side value the relevance and comparison logic reads comes from this one structure (§5.5), sourced from Metrion's existing seller data. **Any field Metrion does not capture for a given seller is `UNKNOWN` — never inferred from other fields, never backfilled with an implementer's guess, never silently defaulted.** CI never writes to it. A seller-side `UNKNOWN` propagates as an `UNKNOWN` comparison scoring 0 (§6.14, C25) rather than producing an invented baseline. **See D8 (RESOLVED) and C31 — the fields with no `sales_line` source are populated by a seller-maintained product profile, which is a second legitimate *source*, not a relaxation of this rule.** |
| C31 | **NEW — RESOLVED D8/Q12 (LOCKED, 2026-09-21). A minimal, one-time-but-editable manual seller-product form is built, and its values are stored as explicit `SellerProduct` field overrides.** Metrion ships a **seller-product-profile form — new UI and new API surface, not merely a backend view** — capturing **category, attributes (key/value pairs), keywords, current listing price (signed BIGINT paise), and fulfillment type** for the seller's own product. **This does not weaken C30's discipline in any way:** every field remains exactly `KNOWN` (the seller entered it) or `UNKNOWN` (nobody entered it) — nothing is inferred, defaulted, backfilled or derived from another field, and an unfilled form field stays `UNKNOWN` and scores 0. What C31 adds is a **second legitimate source** for populating a field, alongside the `sales_line`-derived one — `field_source` is `SELLER_ENTERED` or `CANONICAL_DERIVED` (§5.5; note this is a *source* marker, distinct from §5.1's `DERIVED` confidence value and never conflated with it). **Precedence when both exist and disagree: the seller-entered value wins**, explicitly mirroring the established competitor-side precedent — §5.3 rule 4, implemented in `packages/competitor-intelligence/.../evidence/merge.py::apply_manual_overrides`, where a `SELLER_ENTERED` value always supersedes a `VISION_EXTRACTED` one. Same pattern, seller side. Every field records which source produced it, and the override is editable at any time, never write-once. CI still **never writes** to `SellerProduct`; the profile form is a seller-facing surface, not a CI surface. Model in §5.5; scope of what the form does *not* cover in V12. |

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

None of these deferrals changes C1–C31, D1–D13, A1–A9 or Q1–Q17 as decisions of record; each only states which of them are not yet in scope for the next build pass.

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

---

## 4. Goals and non-goals

**Goals** — store seller-supplied, reference-only competitor URLs; let the seller submit evidence (dashboard screenshot upload) for those competitors; extract structured snapshots from that evidence via a vision model, with manual-entry fallback; detect threshold-breaching price and availability changes between snapshots; produce derived review insight; supply observed inputs to Brain 1 for an estimated margin band; surface findings through CEO and, where enabled, WhatsApp.

**Goals — V2 additions (C21–C30).** Generate research queries from the seller's own product and surface **candidate** competitors for seller review (C21), within a locked query-privacy boundary (§6.11) and query/cost budget (§6.12) · resolve each candidate's product identity explicitly (C24) · score candidate relevance on the locked eight-axis algorithm and always show the breakdown (C25) · keep every candidate visible across three labelled tiers, filtering nothing silently (§6.15) · mine customer voice into themes with stated frequency and bounded, auditable snippet retention (C27) · emit Layer 1 observational alerts (C26) · emit a structured Competitive Brief and `CIHandoff` payloads to CEO (C28) · **supply `competitor_prices[]` as `DERIVED` inputs to `deterministic-engine.md` §5.15 and render its results unchanged.**

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

#### 6.13.2 Gating rule — tuned for friction

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
| Q9 | **CI audit event set (MN9).** §6.4 requires audit logging on every execution, but no event set or artefact is defined. `auth.md` `auth_audit` is scoped to security events only. | Orchestration / observability |
| Q10 | **RESOLVED/MOOT by this pivot.** Was "`robots.txt` posture (MN15) — honour strictly, for discovery only, or out of scope for user-initiated single-page fetches?" There is no fetching left to apply a `robots.txt` posture to. See **R11**. | Closed — see R11 |
| Q11 | **RESOLVED by this decision.** Review-insight acquisition was specified in terms of "fetching raw review text" from a live listing page, which no longer exists as a capability under this pivot (C2). **Resolution:** review insight is screenshot-based, on the identical evidence model as everything else in this pivot — the seller submits a reviews-tab screenshot via the same `competitor_evidence` mechanism (§5, §5.3), a vision/derivation model extracts sentiment/themes/rating-distribution from what's visible, with the same manual-entry fallback and confidence vocabulary (`VISION_EXTRACTED`/`SELLER_ENTERED`/`DERIVED`/`UNAVAILABLE`) as the rest of the pivot. See **R12**. | Closed — see R12. Does not resolve Q7 (local model quality), which remains genuinely open and now explicitly feeds from this acquisition method. |
| Q12 | **RESOLVED (2026-09-21) — see C31, D8, §5.5.1 and R15.** Was: *"Where do `SellerProduct`'s missing fields come from?"* **Resolution: option (b) — a minimal, editable manual seller-product form**, whose values are stored as explicit `SellerProduct` field overrides, `SELLER_ENTERED` taking precedence over canonical-derived values. `rating`/`review_count` stay out of scope and `UNKNOWN`. Do not re-raise. | Closed — see R15 |
| Q13 | **RESOLVED (2026-09-21) — see D9, §6.16.2, AC27 and R16.** Was: *"How do §6.16.2's per-field freshness thresholds and D6/§6.8's 7-day OP3 ceiling coexist?"* **Resolution: both layers apply, exactly as D9 proposed.** The per-field thresholds set **only** `is_stale`; **D6's 7-day ceiling is unchanged and governs availability.** Seller-facing wording is a copy/UX task, not a spec ambiguity. Do not re-raise. | Closed — see R16 |
| Q14 | **RESOLVED (2026-09-21) — see D10, §6.16.3, AC28b, R17 and `deterministic-engine.md` §5.15.1.** Was: *"Does the price-band / outlier computation belong in CI or in the deterministic engine?"* **Resolution: the engine.** `deterministic-engine.md` was amended with `compute_price_band` (§5.15.1); CI supplies `DERIVED` competitor prices and renders the result. Do not re-raise. | Closed — see R17 |
| Q15 | **NEW (V2). Does a discovery run consume a CI run unit, or a separate meter?** D12 provisionally says one discovery run = one CI run unit against C13's runs/month, to avoid inventing a second meter before the entitlement spec exists. But a discovery run's cost profile is entirely different from an evidence-upload run's — it makes up to 20 paid provider queries, where an upload makes none — so one shared meter may misprice both. Intersects Q2, Q3 and `billing-and-pricing.md` Q4/V4, which already flag that CI's provisional per-agent numbers must be reconciled. | Entitlement / billing spec. D12 |
| Q16 | **NEW (V2). What is the audit event set for discovery?** Q9 already flags that CI has no defined audit event set. Discovery widens it materially: a query leaving Metrion to a third party, a seller approving or rejecting a candidate, a provider error, a retention extension under C27, and a privacy-filter drop under §6.11 rule 3 are all events a seller or a regulator may reasonably ask about. `ceo-agent-orchestration.md` C7 names `agent_run` as the artifact for agent invocations, but a per-query/per-decision event set is finer-grained than a run. **Not resolved here** — flagged so it is not discovered late. | Orchestration / observability / DPDP. Extends Q9 |
| Q17 | **RECLASSIFIED, not open (2026-09-21) — moved to V15, see R18.** Was: *"Does the C27 snippet carve-out survive DPDP review?"* **C27's design is approved and locked** — the snippet carve-out, its 90-day default, the named-reason extension and the "source evidence expired" behaviour are all decided and buildable as specified. What remains is a **legal-review-before-launch item, not a design ambiguity**, and it is therefore tracked as **production-validation blocker V15**. Do not re-raise here. | Closed as a question — tracked at V15 / R18 |
| Q18 | **NEW (2026-10-02, evidence-backed). Can a `VISION_EXTRACTED` price be trusted at §6.16.1's `HIGH` at all?** §6.16.1 assigns `HIGH` to a field "extracted cleanly ... with no ambiguity flag from the model". The wired model (llava 7B via Ollama, `evidence/vision_extractor.py`) **never emits an ambiguity flag**, so every vision price is `HIGH` by construction, and `alerts/layer1.py` presents it to the seller as a `HIGH`-confidence validated fact. Measured with the production prompt/parser on a synthetic set of known prices (`packages/competitor-intelligence/scripts/vision_price_eval/`, small n, one layout — evidence, not a population accuracy): price correct **13/31**; by length of the true price 2-digit 3/6, 3-digit 9/13, **4-digit 1/8, 5-digit 0/4** (dropped digits: ₹12,999 → ₹1,299, ₹1,999 → ₹199); MRP correct **0/31**; fields absent from the image reported anyway (rating 55%, rupee discount 23% — and `effective_price = listed − visible_discount`, so a hallucinated discount moves the price delta). Not fixed by resolution (6/9 at 1280 and 640 px), `format: json` (3/12 on the 4-5 digit set), or `temperature: 0` (1/12). A second price-only read by the same model is **not** a validator (4 of its 7 agreements were wrong). A wrong price feeds price events, Layer 1 alerts and the price band unchallenged. **Options (decision needed — not implemented):** (a) cap vision-extracted money fields below `HIGH` and make them alert-ineligible until `SELLER_ENTERED` confirmation (behaviour change to §6.16.1/§6.17; most real listings are ≥ ₹1,000); (b) route vision money fields through the existing `PENDING_MANUAL_ENTRY` path as pre-filled suggestions; (c) add an independent signal (OCR, or a cropped high-resolution read of the price region) before any trust tier is assigned; (d) re-run the evaluation on real seller screenshots first (Q7) — the synthetic set may be harsher or kinder than real listings. Recommended: (d) immediately, then (a) or (b) until (c) exists. | 🔴 Trust (§6.16.1), alerts (§6.17), price band (§6.16.3) |

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
| R12 | Review-insight acquisition mechanism (was Q11) | **Screenshot-based, on the same evidence model as everything else in this pivot (§6.5, C6).** The seller submits a reviews-tab screenshot via the same `competitor_evidence`/`research_session_id` mechanism as listing evidence (§5.3, §6.1); a vision/derivation model extracts sentiment, themes and rating distribution from what's visible, with the same `SELLER_ENTERED` manual-entry fallback for unclear or missing fields, and the same confidence vocabulary (§5.1). Not a new acquisition mechanism — C2 applied to a different evidence type. C14/C15's transient/local-only rule now scopes to the *review text read off the screenshot*, not the screenshot's stored image bytes, which follow the ordinary evidence-image retention policy (§6.8). **Q7 (local model quality) is unaffected and remains open.** |
