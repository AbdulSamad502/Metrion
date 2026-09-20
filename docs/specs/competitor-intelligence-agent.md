# Metrion — Competitor Intelligence Agent (CI) Specification

**Status:** Draft for review
**Prerequisites:** `deterministic-engine.md` (all margin math) · `data-foundation.md` (provenance, confidence) · `auth.md` (permissions) · `whatsapp-integration.md` (WhatsApp identity, invoke/revoke, and investigation-creation mechanics — CI decides none of this itself; §6.9 records only what that spec resolves)

**The arithmetic boundary (B8).** CI may compute **deltas over its own observed facts** — a price change between two snapshots it captured. CI may **never** compute anything financial: no margin, fee, profit, tax or cost figure. All of those originate in Brain 1. CI normalises observations into a provenance-tagged input object, passes it to Brain 1, and reads the result back unchanged. CI holds no financial formula.

---

## 1. Confirmed decisions

| # | Decision |
|---|---|
| C1 | **Marketplaces:** Amazon, Flipkart and Meesho, all three at V1 (readiness §1, Product shape — Marketplaces). |
| C2 | **Acquisition — REVISED (locked pivot): seller-submitted evidence, not fetching.** The seller uploads a screenshot of a competitor listing via Metrion's own web dashboard. A vision model extracts structured fields from it, with a **manual-entry fallback** for anything unclear or missing. Multiple screenshots may be submitted per research session and are **merged** (§5.3, §6.1). Metrion's backend **never fetches** a competitor URL, on demand or otherwise. No continuous crawling, no bulk discovery, no live monitoring, no scraping in any form. **See §1a** — WhatsApp evidence intake is a documented **future** channel, once a BSP is contracted; only dashboard upload ships in this pass. |
| C3 | **The upload-only rule applies to seller financial data; competitor data acquisition is now also seller-submitted, but through a distinct pipeline** (readiness §1, Product shape — Seller data source; `auth.md` T3–T5). Seller financials remain upload-only, parsed by marketplace-report adapters. **Competitor data is submitted by the seller as evidence** — a screenshot the seller captured, extracted by a vision model with manual-entry fallback — **never fetched by Metrion from a competitor URL, under any circumstance.** The two paths still never mix: financial uploads flow through report adapters into the canonical model; competitor evidence flows through vision extraction into `competitor_snapshot`. |
| C4 | **Trusted domains (OP2a) — repurposed as a labeling/format check, not a fetch gate.** *(Judgment call — flagged for review, see D7 in §2.)* Since Metrion never fetches a `competitor_url`, the allowlist can no longer gate network access — there is no network access to gate. It is retained as a **data-quality validation at intake**: a submitted `competitor_url`'s host must still match `amazon.in`, `flipkart.com` or `meesho.com`, so `marketplace` can be derived from it reliably and the enum stays meaningful. URLs outside the allowlist are still refused at intake with a clear message — the refusal is now about labeling correctness, not about preventing a fetch, because no fetch is ever attempted either way. |
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

---

## 1a. Deferred for this implementation pass

This section is a scope/status annotation, not a re-decision. It defers no confirmed decision, design decision, assumption or open question below — it records which already-decided pieces of this spec are not being built in the next pass, and why.

1. **WhatsApp-confirmed trigger and CEO-routed conversational invocation are DEFERRED, pending CEO agent implementation.** Neither the CEO orchestrator nor the CFO agent has any implementation code yet (only DB migrations for `agent_run`/`investigation` exist, in `backend/migrations/versions/20260917_0002_orchestration_tables.py`); building CI's conversational/WhatsApp path now would mean coding against a mocked/guessed CEO routing contract, which risks rework once CEO's real classifier/routing shape is actually designed. Only CI's own **direct execution path** (C20 — the fast path that bypasses CEO/the LLM entirely) will be implemented in the next pass.
2. **The estimated-margin-range feature (C17 / §5.2 "Interface to Brain 1" / §6.7 "Estimated margin range") is DEFERRED, pending a Brain-1 extension spec.** This feature depends on an `estimate_ref` type/family, a `CompetitorObservationSet` input struct, and a Brain-1 function to accept competitor observations and return an estimated margin range — none of which exist anywhere in `packages/calc-engine` (verified by grep: zero matches for `estimate_ref`, `competitor_estimate`, `CompetitorObservationSet`, `margin_curve`). This spec already states correctly that "Brain 1 is extended — never CI" when it needs this interface (C17); that extension is an architecture-level decision affecting the deterministic engine and must go through its own spec update to `deterministic-engine.md` before CI implements anything that calls it. **This deferral is unaffected by the acquisition-model pivot (C2–C4, C16) recorded elsewhere in this spec: the pivot changes how CI acquires observations, not whether the estimated-margin-range feature is in scope. It remains deferred for the same reason as before — the Brain-1 interface still does not exist.**
3. **WhatsApp evidence intake is DEFERRED, pending a contracted BSP.** C2 documents "seller-submitted evidence" as the acquisition model, built in this pass as dashboard screenshot upload only. Submitting evidence via WhatsApp (e.g. forwarding a screenshot to the tenant's bound WhatsApp number) is a plausible future intake channel once `whatsapp-integration.md`'s BSP integration exists, but no BSP is contracted yet and no WhatsApp media-ingestion contract is specified anywhere. Building it now would mean coding against a channel that does not exist. Only the dashboard upload path (`EVIDENCE_UPLOAD`, §6.1, §6.4) ships in the next pass.
4. **The real vision-extraction model is DEFERRED, pending model choice and quality validation.** This spec specifies the *interface* a vision-extraction step must satisfy (§5.3, §6.1) — structured fields in, confidence and source per field out, manual-entry fallback on failure — but does not select a concrete model or provider. This connects directly to the existing 🔴-flagged **Q7** (local derivation model choice and quality): whatever is chosen must satisfy the same local-processing constraints already established for review/listing derivation (C14, C15) if it is to avoid sending a seller's screenshot to a hosted provider, and its extraction quality on real competitor listing screenshots is unproven. Until a model is chosen and validated, `extraction_status` on `competitor_evidence` (§5) may legitimately sit at `PENDING`/`EXTRACTION_FAILED` more often than the product experience wants, with manual entry as the working fallback.
5. **The estimated-margin-range feature (C17) remains deferred as stated in item 2 above, and is explicitly unaffected by this acquisition-model pivot.** Listed again here only so a reader scanning "what changed with the pivot" does not mistake its deferred status for something newly introduced by C2–C4/C16 — it was already deferred before the pivot and stays deferred after it, for the original Brain-1-interface reason, not a pivot-related one.

None of these deferrals changes C1–C20, D1–D7, A1–A5 or Q1–Q10 as decisions of record; each only states which of them are not yet in scope for the next build pass.

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
| D7 | Trusted-domain allowlist's role post-pivot (C4) | **Judgment call, flagged for review:** keep the allowlist as a lightweight intake-time labeling/format check (host must match `amazon.in`/`flipkart.com`/`meesho.com`), not a fetch gate — rather than making `competitor_url` fully freeform now that it is reference-only. | Cheap to keep, costs nothing since there is no fetch to gate, and keeps the `marketplace` enum derivable and meaningful instead of asking the seller to self-declare it. The alternative (freeform URL, seller-declared marketplace) is plausible and should be reviewed — see §12. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | **REVISED for the evidence model (judgment call, flagged for review).** A seller's screenshot legibly shows price, MRP, rating, rating count and availability at the moment of capture, well enough for a vision model to extract them | **High** — vision extraction has nothing to extract if the screenshot omits, crops or obscures a field; mitigated, not eliminated, by the manual-entry fallback (C2, §6.1) |
| A2 | **REVISED for the evidence model.** A competitor URL kept as a reference remains stable enough that a human can still open it weeks later to "go check the listing" | Medium — URL rot means the reference link may not resolve when a seller or CFO wants to verify it directly; it no longer breaks the snapshot series, since the series is built from submitted evidence, not re-fetches |
| A3 | Screenshots of Meesho listings expose a comparable field set to Amazon and Flipkart screenshots | Medium — Meesho's listing layout may yield a thinner extraction even from a clear screenshot |
| A4 | Fee references in the Brain 1 store (`deterministic-engine.md` §5.14) are close enough for a *range*, not a point estimate | Medium — range widens and the gap is named; never presented as precise |
| A5 | One URL maps to one sellable variant | Medium — multi-variant pages need a variant key |

---

## 4. Goals and non-goals

**Goals** — store seller-supplied, reference-only competitor URLs; let the seller submit evidence (dashboard screenshot upload) for those competitors; extract structured snapshots from that evidence via a vision model, with manual-entry fallback; detect threshold-breaching price and availability changes between snapshots; produce derived review insight; supply observed inputs to Brain 1 for an estimated margin band; surface findings through CEO and, where enabled, WhatsApp.

**Non-goals (V1)** — **fetching any competitor URL, ever, for any reason** (the pivot's central non-goal) · continuous or scheduled monitoring · competitor discovery (CI never finds competitors, the seller supplies them) · persisting scraped or copied review text, listing copy or images (seller-submitted evidence is the one carved-out exception, C16) · performing any financial calculation · holding fee rates · indefinite snapshot or raw-evidence-image retention · sending raw expression to a hosted model provider · deciding WhatsApp behaviour · WhatsApp evidence intake in this pass (§1a) · supplier data · automated repricing or any marketplace write.

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
| AC5b | No vector embedding is ever generated from review text; no review-text corpus exists. |
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

---

## 12. Explicit open questions

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
| R12 | Review-insight acquisition mechanism (was Q11) | **Screenshot-based, on the same evidence model as everything else in this pivot (§6.5, C6).** The seller submits a reviews-tab screenshot via the same `competitor_evidence`/`research_session_id` mechanism as listing evidence (§5.3, §6.1); a vision/derivation model extracts sentiment, themes and rating distribution from what's visible, with the same `SELLER_ENTERED` manual-entry fallback for unclear or missing fields, and the same confidence vocabulary (§5.1). Not a new acquisition mechanism — C2 applied to a different evidence type. C14/C15's transient/local-only rule now scopes to the *review text read off the screenshot*, not the screenshot's stored image bytes, which follow the ordinary evidence-image retention policy (§6.8). **Q7 (local model quality) is unaffected and remains open.** |
