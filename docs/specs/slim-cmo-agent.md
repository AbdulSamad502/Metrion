# Metrion — Slim CMO Agent Specification

**Status:** Draft for review — **CP0 amendment 2026-10-03, rounds 2 and 3 applied; P2 review decisions (2026-10-03) applied** (marketplace-specific copy packs; seven-section trend reports; catalog-seeded niche; budgets and evidence rules — §14 is the change log)
**Prerequisites:** `auth.md` (permissions, execution paths) · `ceo-agent-orchestration.md` (routing, multimodal intake §6.9) · `cfo-agent.md` (GST ownership, §6.6/§6.8) · `competitor-intelligence-agent.md` (CI boundary, §6.6/§6.19) · `product-intelligence-agent.md` (source discipline §0, C14) · `data-foundation.md` (provenance, raw-file store) · `entitlement.md` (metering)

> **Superseded / amended 2026-10-12 (owner decisions CD1–CD8, `ceo-cmo-delegation.md`).** Not a rewrite: the sections below stand except where they are listed here.
> - **§8.1 "Registered direct execution paths" and any seller-facing use of them are superseded.** The seller reaches the CMO **only through the CEO** (CEO delegates, collects missing inputs, handles plan approval, presents results). The registered action *keys*, their permissions, units and billing (§8.1.1–§8.5) are unchanged; what changes is that **no frontend control calls the direct HTTP routes**. Whether the routes themselves are retired, kept internal or kept for non-UI use is open (`ceo-cmo-delegation.md` OQ-5).
> - **§6.1 intake:** the CEO builds the intake only from validated inputs (code-parsed seller answers, stored records by id, an `attachment_id`); the CMO declares what it needs through a pure requirement function over a closed vocabulary (`ceo-cmo-delegation.md` §6.3). Marketplaces are still never defaulted.
> - **§6.2 / §6.2.2 images:** the seller's photo arrives as an `attachment_id` in the shared `investigation_attachment` store and is handed over **by reference** to a new reference-taking action (working name `cmo.analyze_attachment`); the CMO loads the bytes by its own tenant-scoped read and runs the existing normalise/store/analyse path. `cmo.upload_image` (raw bytes) is still not callable by the CEO. Trust gate, `UNVERIFIED_HINT` handling and `cmo.confirm_image_hint` are unchanged; the seller-facing label for any unconfirmed image-derived value is **"from your attachment — suggested, not verified"**. Only an endpoint in `LLM_OPERATOR_CONTROLLED_HOSTS` may receive the image.
> - **§6.4 approval:** unchanged as a *choice record* (`cmo_title_approval`); it is distinct from the **plan approval** that now precedes every metered generation (`ceo-approval-workflow.md`), given by buttons on a chat card. The orchestration §6.9 row that lets a UI "Approve & generate copy" button call two direct paths is **superseded**: choosing a title is a chat option card, the copy pack is a separate plan.
> - **Dashboard / frontend:** the CMO page becomes a **read-only showcase** (market trends & news, frequently used titles, grounded copy pack, hashtags & compliance summary) with no generation, regeneration, upload, approval or niche forms (`ceo-cmo-delegation.md` §6.8–§6.10). Niche confirmation moves into chat (reverses orchestration §6.40 "stays on the CMO page"; OQ-14).
> - **§13 open questions Q6, Q7** (image retention, single vs multiple images) gain a dependency: the shared attachment store keeps the original bytes with metadata (`ceo-cmo-delegation.md` OQ-8).

## 0. Recommend-only, no exception

**Slim CMO never writes to a marketplace.** Every output — title, bullets, description, keywords, hashtags, an answer to a catalog question, a trend report — is a **proposal the seller copies and pastes themselves.** This is the system-wide write-back decision (readiness §1, Product shape — Write-back: "None. Recommend-only; every output is a proposal") applied without exception. CMO holds no marketplace credential, no listing-write scope, and no API integration that could publish on the seller's behalf. Seller **approval** (§6.4) is approval of *which proposal to build on*; it is never an instruction to publish. This governs every section below and is restated at AC1.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Recommend-only** (§0). No write-back, ever. | readiness §1 — Write-back |
| C2 | **Free, capped agent.** Cap values are config and provisional (Q1). Units are defined in §8. | readiness §1 — Agent cart, Free-tier caps |
| C3 | **V1 scope — an exhaustive list:** (a) image-informed SEO title sets; (b) a **marketplace-specific listing copy pack** (description + bullets + keywords) per approved title, plus separately requested standalone components (description, bullets, keywords, Amazon backend terms); (c) optional hashtag suggestions; (d) catalog-field Q&A with attribute-basis labels; (e) **seven-section market-trend reports** (§6.8), preceded by seller-confirmed niche terms. **Nothing else is V1.** GST is **not** on this list (C4). | readiness §1, OP7 (amended); 2026-10-03 rounds 1–3 |
| C4 | **CMO has no GST path.** CMO never answers, estimates, or relays a GST rate from its own knowledge and never calls the GST Lookup. Product GST questions are handled by **CEO** (§6.9): to CFO's `cfo.gst_lookup` (full OP13 resolution) when the member holds `agent.cfo`, otherwise through CEO's own call to the shared GST Applicability Lookup service under the safety conditions G1–G7. *Supersedes the former C4 / `cmo.gst_answer` / R3 two-key pattern.* | 2026-10-03 decisions 4 and round 2; OP7 amended |
| C5 | **Seller-supplied product images only.** No marketplace images. Stored per §5 (`seller_image_asset`), analysed through `VisionProvider` (§6.2). **Image-derived facts are not trusted until a provider passes the evaluation gate (§6.2.1); until then they are unverified hints, never facts.** | OP8, OP11; round 2 |
| C6 | **Star topology.** Conversational access needs `agent.ceo` + `agent.cmo`. Registered direct paths need `agent.cmo` alone (+ the shared-service key for `cmo.market_trends`). CMO never calls another agent — not CI, not CFO, not PI. | readiness §1 — Topology |
| C7 | **CMO holds no financial or GST rate data of its own** and writes no price into generated copy. Any number in its output that is not a pure count (character length, option rank, source count) comes from the seller (echoed verbatim), Brain 1, or a cited source. | Brain-boundary rule |
| C8 | **Approval-gated copy.** The listing copy pack (and each individual copy artefact) is generated only after the seller selects one title option (§6.4), or supplies their own existing title. The selection is persisted as an approval record. CEO may never select on the seller's behalf. | 2026-10-03 decision 2 |
| C9 | **Attribute-basis labelling is mandatory** on every catalog attribute and every attribute used in copy: `SELLER_PROVIDED | IMAGE_OBSERVED | ESTIMATED | SOURCE_DERIVED | UNKNOWN` (§6.5). Specifications are never invented; only `SELLER_PROVIDED`, `IMAGE_OBSERVED` and `SOURCE_DERIVED` attributes may be asserted as fact in generated copy. | 2026-10-03 decision 3 |
| C10 | **Trends come from a shared market-signal retrieval service, not from PI.** CMO interprets; the shared service retrieves. No CMO→PI call; no duplication of PI's source clients (§6.8). | 2026-10-03 decision 5; OP9 |
| C11 | **CI input is optional and never blocking** (§6.7). | 2026-10-03 decision 6 |
| C12 | **Hashtags are a separate optional artefact in V1.** No marketplace's hashtag support is established, so none is generated into a listing field (§6.6). | 2026-10-03 decision 7 |
| C13 | **Production generation is blocked unless a VERIFIED, non-stale `format_constraint` row exists for the marketplace** (§6.3). `TEST_FIXTURE` rows exist for automated tests only and are never read by the production path. | round 3 item 1 |
| C14 | **Evidence is computed, not asserted.** Source counts, independence, recency and corroboration strength in trend reports are computed in deterministic code from configured thresholds; the LLM never assigns them. Several mentions from one source are one source. Corroboration of attention is never evidence of demand, sales or profitability. | round 3 item 2 |
| C15 | **Only seller-confirmed niche terms may leave Metrion for research.** Suggestions derived from the seller's own catalog data are shown for confirmation first; raw reports, customer data and financial data never reach a research provider (§6.8.3). | round 3 item 3 |
| C16 | **No silent configuration defaults.** Every trend budget, window and threshold is configuration (§6.8.5). A missing required key blocks the affected action with `CONFIG_MISSING`; it is never replaced by a code default. Provider capabilities are verified, not assumed (§6.8.8). | round 3 item 4 |

---

## 2. Q75 — generation trigger: independent and CI-informed, both first-class

Two independent entry points; neither is a pipeline stage of the other:

1. **Independent.** The seller asks for titles/copy from the product facts and image they supply. No CI context is required, expected, or awaited. This is the default and the common case.
2. **CI-informed (optional).** If — and only if — the seller is discussing listing optimisation and CI-derived listing attributes exist, CEO may attach them (§6.7). CMO never calls CI, and CI never calls CMO (C6, `competitor-intelligence-agent.md` §6.6).

`input_mode` (§5) records which mode actually produced a generation. A missing, stale, `DEGRADED`, or `UNAVAILABLE` CI insight, or a seller without `agent.ci`, **silently falls back to independent mode with a visible note** — it never blocks, delays or fails a generation (C11, E4).

---

## 3. Q12 — "other simple marketplace task" resolved

The planning document's catch-all is **removed, not carried forward** (readiness §2.26 resolved here). C3 is the whole scope. Anything else a seller asks for is **out of scope for V1**; CEO says so and CMO does not improvise. New capabilities enter C3 by spec amendment, never by runtime inference. Bulk catalog rewrite, poster/caption generation, A+ content design, ad-copy and image generation are **not** V1.

---

## 4. Goals and non-goals

**Goals** — turn a seller's product image and details into marketplace-specific, constraint-valid SEO title options; build description/bullets/keywords grounded in the seller-approved title; answer catalog questions with explicit attribute-basis labels; optionally fold in CI-derived competitor listing attributes; produce dated, source-linked market-trend reports that separate attention from demand; cite or label every claimed fact.

**Non-goals (V1)** — any marketplace write-back · GST answers (C4) · pricing, margin or fee statements (CFO / Brain 1) · independent competitor research or any marketplace fetch (CI's job) · ranked product discovery, feasibility or supplier work (PI's job) · image generation or editing · multi-image analysis · publishing, scheduling or social posting of hashtags · "other simple marketplace task" (§3) · V2 CMO scope (posters, captions, catalog automation — planning doc p.5).

---

## 5. Data model

All tables are tenant-owned: `tenant_id uuid not null`, `FORCE ROW LEVEL SECURITY` per `auth.md` §7.3, cross-tenant id → `404`.

```sql
seller_image_asset (                            -- C5/OP8: the previously-missing store (closes old Q3/V3)
  id uuid pk, tenant_id uuid not null,
  storage_uri text not null,                    -- object store, same mechanism family as data-foundation report_file.storage_uri; NEVER bytes in Postgres
  sha256 text not null,                         -- content-addressed, immutable once stored (data-foundation immutability rule)
  content_type text not null, byte_size bigint not null,
  uploaded_by uuid not null, created_at timestamptz not null,
  retention_until timestamptz,                  -- retention policy undecided (Q6) — nullable, not defaulted
  status text not null                          -- ACTIVE | PURGED
)

product_image_analysis (                        -- structured VisionProvider output (OP11); the ONLY thing the text LLM sees of the image
  id uuid pk, tenant_id uuid not null,
  image_asset_id uuid not null,
  schema_version text not null,                 -- the defined extraction schema (§6.2)
  provider text not null, model text not null,
  eval_gate_ref uuid,                           -- fk vision_eval_run that cleared this provider+model+schema_version; NULL = gate not passed → every attribute is UNVERIFIED_HINT
  attributes jsonb not null,                    -- [{name, value, basis, trust_state, confidence?, evidence_note?}], raw basis ∈ IMAGE_OBSERVED | UNKNOWN only; trust_state ∈ UNVERIFIED_HINT | EVAL_PASSED (§6.2.1)
  analysis_state text not null,                 -- COMPLETE | DEGRADED | FAILED
  degraded_reason text,
  created_at timestamptz not null
)

vision_eval_run (                               -- platform-level (no tenant_id; synthetic/consented eval images only, no seller data)
  id uuid pk, provider text not null, model text not null, schema_version text not null,
  dataset_ref text not null,                    -- the labelled evaluation set used
  metrics jsonb not null,                       -- per-attribute-class precision/recall, hallucination rate (fields reported that are not in the image), numeral-error rate
  bar_ref text not null,                        -- the approved pass bar this run was judged against (bar values are a human decision — Q4, never invented in code)
  passed boolean not null, run_at timestamptz not null, run_by text not null
)

cmo_generation (                                -- ONE ROW PER ARTEFACT DELIVERED; each row = billable_units 1 (§8)
  id uuid pk, tenant_id uuid not null,
  sku text, marketplace text,                   -- AMAZON | FLIPKART | MEESHO; null only for trend reports and HASHTAGS not tied to a marketplace
  output_type text not null,                    -- TITLE_SET | LISTING_COPY | DESCRIPTION | BULLETS | KEYWORDS | BACKEND_TERMS | HASHTAGS | CATALOG_ANSWER | TREND_REPORT
  input_mode text not null,                     -- INDEPENDENT | CEO_BROKERED_CI
  ci_inputs_snapshot jsonb,                     -- set only when input_mode = CEO_BROKERED_CI: the exact CI-derived attributes used + their competitor_listing_insight ids (§6.7)
  image_analysis_id uuid,                       -- fk product_image_analysis; null when no image was supplied
  grounding_approval_id uuid,                   -- fk cmo_title_approval; required for LISTING_COPY|DESCRIPTION|BULLETS|KEYWORDS|BACKEND_TERMS unless grounding_basis = SELLER_SUPPLIED_TITLE
  grounding_basis text,                         -- APPROVED_TITLE | SELLER_SUPPLIED_TITLE
  output_text text,                             -- rendered artefact; for TITLE_SET see cmo_title_option
  output_structured jsonb,                      -- LISTING_COPY {description, bullets[], keywords[]} / CATALOG_ANSWER attribute table / TREND_REPORT pointer / per-field results
  format_constraint_ref uuid,                   -- fk format_constraint.id actually applied; null for CATALOG_ANSWER/TREND_REPORT/HASHTAGS
  status text not null,                         -- COMPLETE | FAILED  (only COMPLETE consumes a unit — §8)
  failure_reason text,
  request_key text not null,                    -- client-supplied idempotency key (§8.4); unique per tenant with output_type+marketplace
  billable_units int not null default 1,        -- ALWAYS 1 in V1; reserved column
  agent_run_id uuid,                            -- orchestration agent_run row (ceo-agent-orchestration.md C7)
  generated_by uuid not null, created_at timestamptz not null
)

cmo_title_option (                              -- the 5 options of one TITLE_SET (one marketplace)
  id uuid pk, tenant_id uuid not null,
  generation_id uuid not null,                  -- the TITLE_SET cmo_generation row
  rank int not null,                            -- 1..5 presentation order, NOT a quality score claim
  title_text text not null,
  char_count int not null,                      -- computed deterministically in code, never reported by the LLM
  constraint_check jsonb not null               -- {max_chars, passed:true} evaluated against format_constraint_ref
)

cmo_title_approval (                            -- C8: the persisted seller approval record
  id uuid pk, tenant_id uuid not null,
  generation_id uuid not null, option_id uuid,  -- option_id null when the seller supplied/edited their own text
  approved_text text not null,                  -- exact text approved (option text, or seller-edited text re-validated against the constraint)
  edited_by_seller boolean not null,
  approved_by uuid not null, approved_at timestamptz not null
)

seller_fact (                                   -- provenance for what the seller told CMO
  id uuid pk, tenant_id uuid not null,
  cmo_generation_id uuid,                       -- nullable (P1 amendment): a fact confirmed outside any generation (e.g. an image hint, §6.2.1) has none
  image_analysis_id uuid,                       -- set when this fact confirms an image-derived hint
  sku text, attribute_name text,
  fact_type text not null,                      -- CATEGORY | BRAND | ATTRIBUTE | NICHE | TARGET_PRICE | FREE_TEXT
  fact_value text,                              -- text facts (NULL iff TARGET_PRICE)
  value_paise bigint,                           -- set ONLY for TARGET_PRICE (and then fact_value is NULL): BIGINT paise >= 0, no floats (CLAUDE.md money rule)
  provided_by uuid not null,                    -- attribution (P1 amendment)
  provided_at timestamptz not null
  -- no `source` column: every row is seller-asserted, unconditionally
)

format_constraint (                             -- runtime authority; §6.3 table is illustrative only
  id uuid pk,
  marketplace text not null, category text,     -- null = marketplace-wide default
  title_max_chars int, title_option_count int,  -- option count is policy (5), stored here so it is config, not code
  bullet_count int, bullet_max_chars int,       -- (P1 amendment) per-bullet limit
  description_type text, description_max_chars int,
  keywords_max_count int, keywords_max_chars int,
  -- Every limit above may be NULL = "not stated by the verified source": NOT enforced and NOT guessed (§6.4).
  backend_terms_max_bytes int,                  -- Amazon hidden-field cap; null where none (DB: non-null only for AMAZON)
  hashtags_supported boolean,                   -- NULL = not established (V1 state for all three marketplaces) → treated as NOT supported
  count_rule text,                              -- UTF16_CODE_UNITS | CODE_POINTS: how THIS marketplace counts characters in its length limits. NULL = NOT verified -> production generation is BLOCKED (C13). The code's UTF-16 count is only a conservative implementation fallback, never a verified rule
  source_url text not null,                     -- OP2(a) marketplace domain the rule was verified against
  verified_at timestamptz not null, version int not null,
  row_kind text not null,                       -- VERIFIED | TEST_FIXTURE. Production path reads VERIFIED only (C13). Fixtures are inserted only by test code; the seed tool refuses TEST_FIXTURE outside a test database
  unique (marketplace, category, version, row_kind)
)

cmo_niche_term (                                -- §6.8.3: the ONLY terms allowed to leave Metrion for research
  id uuid pk, tenant_id uuid not null,
  term text not null,                           -- normalised, length-capped, identifier-screened
  origin text not null,                         -- SELLER_STATED | CATALOG_DERIVED | SELLER_FACT
  origin_note text,                             -- e.g. 'derived from sales_line.item_title (n distinct titles)'; never raw titles
  status text not null,                         -- SUGGESTED | CONFIRMED | REJECTED
  confirmed_by uuid, confirmed_at timestamptz,
  created_at timestamptz not null,
  unique (tenant_id, term)
)

cmo_platform_config (                           -- §6.8.5 / §6.3 / §8: every tunable lives here; tenant row beats platform default (reconciliation_tolerance_config pattern)
  id uuid pk, tenant_id uuid,                   -- null = platform default
  key text not null, value jsonb not null,
  effective_from date not null,
  unique (tenant_id, key, effective_from)
  -- NO key is seeded by any migration. Required keys are enumerated in §6.8.5/§6.3/§8.3; absence => CONFIG_MISSING, never a code default.
)

cmo_trend_report (                              -- §6.8
  id uuid pk, tenant_id uuid not null, generation_id uuid not null,
  niche_term_ids uuid[],                        -- the CONFIRMED cmo_niche_term rows used; null/empty only for a broader-only report
  sections_requested text[] not null,           -- subset of NICHE | MARKET_NEWS | REPORTED_TACTICS | NEW_PRODUCTS_BUZZ | ADJACENT
  sections jsonb not null,                      -- per-section {state: COMPLETE|PARTIAL|UNAVAILABLE, reason?, findings[]} per §6.8.2 finding schema
  interpretation jsonb,                         -- 'What this could mean': CMO interpretation items, each citing finding ids (§6.8.2 s6)
  evidence jsonb not null,                      -- §6.8.2 s7: source table, independence/recency results, degraded sections, data gaps, budget used — never empty
  outbound_queries jsonb not null,              -- exact query strings sent to providers (audit; C15)
  config_snapshot jsonb not null,               -- the config values this report was computed under (reproducibility)
  market_signal_run_ref uuid not null,          -- the shared service's retrieval record
  generated_at timestamptz not null
)
```

**Schema guarantees (enforced by the database and proven in `packages/slim-cmo/tests/integration/`, P1):**
every tenant table is `FORCE ROW LEVEL SECURITY`; every parent carries `unique (tenant_id, id)` and every child references it through a composite `(tenant_id, parent_id)` foreign key, so a row can never reference another tenant's row (RI checks bypass RLS, so a plain id FK would not stop this); composite FKs are `DEFERRABLE INITIALLY IMMEDIATE` so a tenant's rows can be erased in one transaction (`cmo_generation` and `cmo_title_approval` reference each other at the table level, never at the row level); provenance tables (`cmo_generation`, `cmo_title_option`, `cmo_title_approval`, `product_image_analysis`, `seller_fact`, `cmo_trend_report`) are **append-only** for the application role; `format_constraint`, `vision_eval_run` and `cmo_platform_config` are not writable by the application role; idempotency is a partial unique index over `COMPLETE` rows (`request_key, output_type, marketplace`, NULLs equal) so a `FAILED` attempt never blocks a retry; and the vision trust gate (§6.2.1) is a CHECK plus a composite FK: an attribute may be `EVAL_PASSED` only if it cites a `vision_eval_run` with `passed = true` for the same provider, model and schema_version, and vision may only ever emit `IMAGE_OBSERVED`/`UNKNOWN`.

**No table stores a GST rate, a fee, or a competitor/seller price as CMO fact.** The only money value CMO holds is the seller's own `TARGET_PRICE`, stored as integer paise, echoed verbatim, never computed on, and never written into generated copy (C7). **Image bytes live only in the object store** behind `storage_uri`; no CMO table holds inline bytes (AC7). `format_constraint_ref` is a FK to the exact row applied, so the rule version is always reconstructable.

---

## 6. Core rules

### 6.1 Seller intake (what CEO hands CMO)

CEO (`ceo-agent-orchestration.md` §6.9) delivers a structured intake; CMO never parses raw chat. Declared fields (the `auth.md` §5.2 "declared fields only" convention):

`image_analysis_id?` (P6 correction, 2026-10-05: generation and catalog requests reference a stored ANALYSIS - created by the explicit `cmo.upload_image` and `cmo.analyze_image` actions - not a raw asset; one image per analysis in V1 — Q7) · `niche_text?` (a typed niche; it becomes a `SELLER_STATED` term and still needs confirmation before research, §6.8.3) · `confirmed_niche_term_ids[]?` (trend actions) · `trend_sections?` (subset of the five researched sections, default all) · `product_name?` · `brand?` · `category_hint?` · `attributes[]?` (seller-stated name/value pairs) · `target_price_paise?` · `marketplaces[]` (subset of AMAZON, FLIPKART, MEESHO; ≥1 for title/copy actions) · `request_key`.

Missing `marketplaces` → CEO asks (D4/OP1); CMO never defaults. Every text field is stored as a `seller_fact`. `target_price_paise` is context only (C7).

### 6.2 Image analysis — `VisionProvider` (OP11)

- Behind a `VisionProvider` Protocol (a separate slot from `LlmProvider`): `analyze(image_ref, schema_version) -> ImageAnalysis`. Output is a **defined structured schema** (product type, visible text/brand, observed colours, observed material cues, form/size cues, packaging, notable visible features, and an explicit `UNKNOWN` for anything not determinable). The text LLM consumes **only** this structure, never the image (OP11).
- Vision may emit only `IMAGE_OBSERVED` or `UNKNOWN`. It never emits `SELLER_PROVIDED`, `ESTIMATED` or `SOURCE_DERIVED`, and never a price, weight in grams, dimension in cm, rating or certification — those are not observable from a product photo and any such value is discarded at parse time.
- **Known hazard (evidence, not assumption):** `competitor-intelligence-agent.md` Q18 measured the local llava 7B reporting fields absent from the image and dropping digits. CMO therefore (a) treats every vision output as `IMAGE_OBSERVED` *only if it names something literally visible*, (b) never lets a vision-read numeral reach copy or a catalog answer as fact, and (c) requires the eval in §7 before any provider is trusted. Provider/model choice is open (Q4, V2).
- `analysis_state = FAILED/DEGRADED` → the seller is told; generation proceeds **text-only only on explicit seller confirmation**, never silently (E7).
- An analysis is stored once per image and **reused** by later requests; re-analysis happens only for a new image or schema version.

#### 6.2.1 Vision trust gate (round 2 — "do not trust image-derived facts until a provider passes evaluation")

- `product_image_analysis.eval_gate_ref` is non-null **only** when a `vision_eval_run` with `passed = true` exists for exactly that `(provider, model, schema_version)`. Otherwise the gate is **NOT PASSED**, which is the default and the state at launch.
- **While the gate is not passed:** every vision attribute is stored with `trust_state = UNVERIFIED_HINT`, is shown to the seller only as *"suggested from your photo — please confirm"*, is **never** used as a claim in title/copy/catalog output, is **never** labelled `IMAGE_OBSERVED` to the seller, and is excluded from the GST/CI/trend context CEO passes on. A seller's confirmation (`cmo.confirm_image_hint`) is stored as a **new** `seller_fact` with basis `SELLER_PROVIDED` — the seller's own, attributable assertion. It records the confirmation **only**: it costs zero units, calls no model, **does not modify the stored `product_image_analysis` row** (append-only for the application role) and **does not make the hint, the vision provider, or any other image-derived attribute trusted**. The hint itself stays `UNVERIFIED_HINT` and ineligible until an approved evaluation passes; a confirmed weight is the seller's statement about their product, not something the photo established.
- **Effect on scope:** everything in C3 works at 100% **without** a passed gate — titles, copy, catalog answers and trends are driven by seller-provided facts. Image analysis only adds *suggestions to confirm* until a provider is cleared. The independent text workflow is never blocked by the vision decision.
- The pass **bar** (metrics and thresholds) is a human decision recorded in `bar_ref`; no threshold is invented in this spec or in code (Q4). At minimum the evaluation must measure the failure class CI Q18 documents: fields reported that are not in the image, and dropped/wrong numerals.

#### 6.2.2 Image intake, analysis and the trust gate (P6, 2026-10-05)

**Pipeline:** upload → validate (type allow-list, magic bytes, byte and pixel limits) → normalise / strip EXIF → hash → store → analyse → parse → trust-gate → immutable analysis. The raw provider reply never becomes a seller fact or claim: only the validated, stamped observation does.

1. **Interface.** `VisionProvider.describe(*, model, schema_version, image) -> str` returns RAW untrusted text; a pure parser makes the structured analysis (this refines the `analyze(image_ref, schema_version) -> ImageAnalysis` shape in §6.2). The provider is a separate slot from `LlmProvider`, lives outside the pure core, is **local Ollama only** (no hosted vision provider in V1) and receives only the fixed schema prompt (it takes no seller fact, product name or price) and the NORMALISED image.
2. **Explicit zero-unit actions.** `cmo.upload_image` (`agent.cmo` + `files.upload`) and `cmo.analyze_image` (`agent.cmo`) are separate from every billable action, so a slow vision call is never hidden inside one. Neither takes an entitlement check, a reservation or a metered event. A per-tenant rate limit (required configuration: analyses per window, window seconds) counted from the tenant's own analysis rows guards the model call; it is checked only when a model call would happen, includes FAILED attempts, and is a soft limit (no in-flight claim system).
3. **Upload.** Required configuration with no defaults: storage directory (local disk), allowed types, maximum bytes, maximum pixels. The decoded size is checked from the header BEFORE decoding (decompression-bomb guard). The original bytes are never stored or sent to a provider: the image is re-encoded to a fresh PNG from decoded pixels only, which drops EXIF (including GPS and capture time), ICC/XMP, comments, thumbnails, trailing bytes and any polyglot payload; EXIF orientation is applied to the pixels first. Mislabelled, corrupt, truncated, animated and over-limit files are refused with a generic reason. The hash is of the normalised bytes (`unique (tenant_id, sha256)`), so the same picture is one asset. Retention/purge remain out of scope (Q6).
4. **Closed schema `cmo-vision-v1`:** `color`, `material`, `size`, `brand`, `product_type`, `visible_text`. Notable features are excluded; weight, dimensions, price, rating, certification, category and vertical are not in the schema and can never be emitted. Every analysis stores one entry per field: an observed value (`IMAGE_OBSERVED`) or an explicit `UNKNOWN`. Values containing any digit, and values the P2 forbidden-content scan flags (price, tax, contact, demand or certification wording), are discarded to `UNKNOWN`.
5. **Outcomes.** `FAILED`: not a single JSON object, over the size ceiling, none of the schema fields present, or no field well-formed (also a provider failure or timeout) — persisted with a reason and no attributes. `DEGRADED`: partially usable but materially incomplete or malformed (schema fields missing or of the wrong JSON type while at least one is well-formed). `COMPLETE`: every field present and well-formed. Policy filtering is NOT degradation.
6. **Trust gate.** All-or-nothing per `(provider, model, schema_version)`; no digest. A triple is trusted iff its LATEST `vision_eval_run` passed; no run or a failing latest run means closed. A new analysis stamps `EVAL_PASSED` and cites the passing run only when the gate is open; otherwise every observation is an `UNVERIFIED_HINT`. Stored analyses are immutable; trust is REVOKED AT READ TIME: a consumer (P3 generation, P4 catalog) sees `EVAL_PASSED` only while the latest evaluation for the analysis's exact triple passed, never a promotion. The database constraint (§6.2.1) remains the backstop.
7. **Evaluation (operator only, no HTTP route).** `scripts/vision_eval.py` requires a named human operator (`--run-by`), a labelled dataset in which every item labels every schema field, and an explicit bar file stating every threshold (integer basis points: per-class precision and recall, maximum hallucination, maximum numeral reliance, minimum items); it refuses to run without any of them and has no default bar. Dataset images and replies pass through the same normaliser and parser as production. A provider outage aborts the run and records nothing (an outage is not a failing evaluation). The result is an immutable `vision_eval_run` (`bar_ref` = bar name + hash of the bar file). A bar with no positive examples for a class, or no "not present" labels, fails.
8. **Idempotency.** Upload is idempotent by hash; a COMPLETE analysis is unique per `(tenant, asset, provider, model, schema_version)` (partial unique index) and is reused; FAILED and DEGRADED attempts never block a retry; a concurrent duplicate loses the index race and is served the winner (a duplicate model call is accepted in V1).
9. **`cmo.confirm_image_hint` is unchanged:** it records the seller's own `SELLER_PROVIDED` fact and never modifies or trusts an analysis. Image evidence never overrides a seller-provided fact (§6.5.1).

### 6.3 Per-marketplace format constraints

Configuration, resolved at generation time, never hardcoded — same principle as `deterministic-engine.md` F4. **The table below is illustrative documentation only, not a source CMO reads from.** At generation time CMO fetches the live `format_constraint` row for the target marketplace (category-specific row beats marketplace-wide default, latest `version` wins); if absent or stale, generation **blocks** per E5 rather than falling back to these values.

| Marketplace | Title | Bullets | Description | Notes |
|---|---|---|---|---|
| Amazon | ~200 chars, brand-first convention | 5, feature-led | Plain or A+ block | Backend search terms are a separate hidden field with its own cap |
| Flipkart | Structured: brand + type + attributes | Key features list | Structured spec fields | Category-specific attribute forms |
| Meesho | Shorter phrasing | Highlights, fewer than Amazon | Brief | Simpler schema |

**Enforcement is deterministic, in code.** Character counts, bullet counts, option counts and byte caps are computed and validated by Python against the fetched row; the LLM never reports its own length and is never trusted to have met a limit. A violating option is regenerated (bounded internal retry, §8.3) or dropped; a title set that cannot reach `title_option_count` valid options is returned **short and labelled**, never padded with invalid text. `source_url` and `verified_at` are cited on every output.

### 6.3a Product identity from chat (CMO 3.0 M0, amendment 2026-10-30)

When the CEO runs a CMO writing action from chat it supplies `sku` = a deterministic slug of the product name the seller gave (lower-case letters, digits and hyphens, at most 120 characters; the same name always gives the same value). This is what lets the facts the seller confirmed (`seller_fact`, loaded by exact non-null `sku`) be found in a later conversation and lets the dashboard list the product under its name. It does not replace a seller's own catalog SKU where one is supplied on the direct path. A name that is too short to identify a product gives no `sku` and nothing is remembered. Authority for the chat behaviour: `ceo-cmo-delegation.md` §6.12.

### 6.14 Keyword intelligence (CMO 3.0 M2, amendment 2026-10-30)

**Status: implemented** (`slim_cmo/keywords/intelligence.py` pure rules; `slim_cmo/service/keywords.py`; route `POST /api/v1/cmo/keyword-intelligence`; CEO action `cmo.keyword_intelligence`; table `cmo_keyword_analysis`, migration `20261030_0004`). Tests: `tests/unit/keywords/`, `backend/tests/integration/test_cmo_m2_integration.py`.

**What it is.** "Research keywords for my AquaNest bottle" returns keyword candidates built **only from the seller's confirmed facts** (claim-eligible attributes, §6.5), optionally corroborated by the derived theme words of the seller's tracked competitors (§6.7, brokered by the CEO) and by niche terms the seller confirmed (§6.8). No model, no network, **0 units** (no entitlement check, no reservation, no metered event); one `agent_run` per new analysis. Writing keywords for a listing remains `cmo.generate_keywords` (metered, a plan card).

**Per candidate, all by named rules in code:** *intent* (BRAND, PRODUCT_TYPE, SPECIFICATION for size/material/colour words, USE_CASE, FEATURE); *placement* (title, bullet points, description, and for weak fits the Amazon backend terms or the Flipkart/Meesho keywords field); *relevance* (HIGH / MEDIUM / LOW = the share of the keyword's words that the seller's own facts or product name support); *evidence strength* (STRONG = fully supported by the seller's facts and also seen in competitor themes or a confirmed niche term; MODERATE = supported by the seller's facts only; WEAK = partly supported; NOT_ASSESSED = no evidence); and the *evidence list* (which facts, how many tracked competitor listings carried the theme, which niche term). A keyword with LOW relevance is shown as not recommended.

**Never assessed.** `searchVolume`, `buyerDemand` and `marketplaceRank` are always `NOT_ASSESSED` (no source exists; spec Q3). Competitor occurrence is a **count of the seller's own tracked listings that carried the word**, or `NOT_ASSESSED` when no competitor evidence was supplied. Relevance and evidence strength describe the fit with the seller's own product, **not** Amazon SEO rankings, search counts, conversion or sales; every result says so.

**Excluded, not offered.** A keyword that needs a product claim the seller has not confirmed (insulated, leakproof, dishwasher safe, microwave/freezer safe, waterproof, BPA free, rustproof, food grade, heat resistant, unbreakable, non toxic, hot and cold; a closed list) is listed under *excluded* with the reason. A claim that exists only as an unverified photo hint or an estimate is named the same way. If the seller later confirms the claim, it becomes eligible. With no confirmed facts at all the result is `NO_FACTS` and asks for them; nothing is invented.

**Storage.** `cmo_keyword_analysis`: one immutable row per analysis (candidates, exclusions, evidence, limits exactly as shown), `FORCE` RLS, `SELECT, INSERT` only for the application role, idempotent per `(tenant, request_key)`. No volume, demand or rank column exists. **Open decisions (not invented):** whether analyses should ever be metered (V1: free, because they are derived from the seller's own data with no model); how long analyses are kept; a keyword-demand source (PI 2.0 may add one, which would fill the `NOT_ASSESSED` slots without changing this structure).

### 6.4 Title sets, approval and marketplace-specific copy packs

**Workflow, per marketplace the seller selected:** title set → seller approval → copy pack. Each marketplace runs this workflow independently with its own constraint row, its own approval and its own pack.

1. **Title set.** CMO produces `title_option_count` (5, from config) distinct, constraint-valid SEO title options grounded in claim-eligible facts (+ CI attributes if attached, §6.7). One marketplace = one `TITLE_SET` row = one unit; three marketplaces = three rows = three units (§8). Options may differ in emphasis (brand-first, feature-first, use-case-first) but may assert only claim-eligible attributes (C9).
2. **Presentation.** CEO shows the options **verbatim** from the structured report (`ceo-agent-orchestration.md` AC12) — it may not rewrite, merge or re-rank them.
3. **Approval.** The seller selects exactly one option per marketplace, or supplies/edits their own text, which is re-validated deterministically against the same constraint. The selection is persisted to `cmo_title_approval` (`approved_by`, `approved_at`). **Approval consumes no unit.** CEO cannot infer approval from ambiguous language; ambiguity → clarifying question. Re-approving a different title creates a *new* approval row; existing packs stay tied to the approval they were built from.
4. **Marketplace-specific copy pack (`LISTING_COPY`, 1 unit per marketplace).** For each approved title CMO produces a separate pack of **description + bullet points + keywords** for *that* marketplace:
   - **Inputs, and only these:** (a) that marketplace's approved title text; (b) that marketplace's VERIFIED, non-stale `format_constraint` row (C13); (c) **claim-eligible** seller facts and evidence only (§6.5: `SELLER_PROVIDED`; `SOURCE_DERIVED` with citation; `IMAGE_OBSERVED` only when the vision gate has passed — never `ESTIMATED`, `UNKNOWN` or `UNVERIFIED_HINT`); (d) the seller's product details. Trend ideas and CI themes enter only via §6.7's claim-eligibility rule or because the seller explicitly added them as facts — they are never injected automatically.
   - **Separate per marketplace.** A pack is generated in its own call from its own approved title and constraint. It is never derived from, adapted from or copied out of another marketplace's output. Structure follows the constraint row (bullet count, description type, structured fields), so Amazon, Flipkart and Meesho packs differ in shape, not merely in length.
   - **Deterministic enforcement in code, never trusted to the LLM:** title consistency (the pack must not contradict the approved title or introduce a non-eligible attribute), bullet count and per-bullet length, description type and length, keyword count/length/duplication, UTF-8 byte caps, forbidden-content scan (price figures and unsupported price/discount/savings claims — the neutral word "price", as in "fair price", is allowed —, GST/tax statements, "trending/bestseller" family, unsupported claims, URLs/contact details where the constraint disallows them). Any limit the constraint row does not state is **not enforced and not guessed** — the pack notes which limits were unverified.
   - **Atomic outcome.** The pack is `COMPLETE` only if description, bullets and keywords all pass validation. Otherwise it is `FAILED` with 0 units and a plain reason (e.g. *"needs more confirmed product facts: material, capacity"*); no partial pack is delivered or billed. Where claim-eligible facts are too thin to write valid copy without non-eligible claims, the result is `FAILED / NEEDS_FACTS` listing exactly which facts to supply — never padded with guesses.
   - **Flipkart structured fields.** Fields in a category's attribute form are filled only from claim-eligible facts; the rest are returned as `NEEDS_SELLER_INPUT` with the caveat that the required-field list for a category is not verified (Q5) — CMO does not invent required fields.
5. **Constraint blocking (C13).** If the marketplace has no `VERIFIED` row, or the newest row's `verified_at` is older than `format_constraint_max_age_days` (config, §6.3), or that config key is missing, **or the row does not state a verified `count_rule`** (how the marketplace counts characters; backend search terms are exempt because their cap is in UTF-8 bytes), production generation for **that marketplace** is blocked (E5) with the reason; other marketplaces in the same request proceed. `TEST_FIXTURE` rows are never read by the production path.
6. **Standalone artefacts remain separate products,** each with its own trigger, validation and billing (§8.1.1): `DESCRIPTION`, `BULLETS`, `KEYWORDS`, Amazon `BACKEND_TERMS`, `HASHTAGS`. A standalone artefact requested after a pack is a new artefact and a new unit (no dedupe); it never silently alters the pack row, which stays immutable.
7. **No publishing, no write-back.** Output is displayed with copy buttons only; nothing is sent to a marketplace (§0).

#### 6.4.1 Deterministic-core decisions (P2 review, 2026-10-03)

1. **Duplicates are exact only.** Two titles, bullets, keywords or hashtags are duplicates iff they are identical after normalisation (case, punctuation, spacing, Unicode form). There is **no similarity threshold**; "steel bottle" and "steel bottles" are different options.
2. **Character counting is a verified, per-marketplace rule.** Each `format_constraint` row states a `count_rule`. The code ships only two (`UTF16_CODE_UNITS`, the conservative reading in which an emoji counts 2, and `CODE_POINTS`); grapheme counting is unsupported until a marketplace is verified to need it. The UTF-16 count is an **implementation fallback, not a marketplace rule**: with no verified `count_rule` on the winning row, production generation for that marketplace is blocked (`COUNTING_RULE_UNVERIFIED`), exactly like a missing or stale constraint. The rule applied is recorded in each option's `constraint_check`.
3. **Phone-number detection recognises phone shapes, not "eight digits".** Blocked in copy: an Indian mobile (10 digits starting 6–9, optionally `0`- or `91`-prefixed), a `0`-prefixed STD landline, and an explicit `+`-international number (8–15 digits), however separated and however disguised (full-width or non-Latin digits, zero-width characters), including after year-looking groups. **Not** blocked: years and year ranges, dates, model/part numbers, HSN and PIN codes, and barcodes (EAN-13, UPC-A). A 10-digit identifier starting 6–9 (an ISBN-10) looks like a mobile and is refused — the privacy-first side of the trade. The stricter outbound rule for niche terms (§6.8.3) refuses any run of 8+ digits after discounting year-looking groups.
4. **Price wording.** The neutral word "price" ("fair price", "reasonable price", "value for money", "affordable") is allowed. Blocked: price figures (currency symbols/words, MRP, "% off") and unsupported **claims** about price, discounts or savings — comparative or absolute ("best/lowest/cheapest/competitive price", "cheap", "unbeatable"), promotional ("special/offer/sale/discounted price", "on sale", "price drop/cut/match", "priced to sell", "great deal", "clearance") and savings ("save big", "savings", "money-saving"). CMO may assert a price fact only if it is an eligible seller fact; in V1 it states none (C7).
5. **Request keys.** The 128-character limit on `request_key` is an **internal implementation limit** (it bounds a client-supplied identifier), not a business, plan or marketplace rule; the character set is letters, digits and `. _ : -`.
6. **Niche stop words are configuration** (`niche_stopwords_extra`, `niche_stopwords_exclude`, §6.8.5) over built-in English, listing-filler, Hindi and Romanised-Hindi sets; they are tested on English, Hindi and mixed-language titles. No regional language other than Hindi is claimed (Q23).
7. **Fail-safes are preserved:** no tactic-risk pattern set ⇒ every tactic is `UNASSESSED` with no suggested action; no official-domain configuration ⇒ nothing is labelled `OFFICIAL_MARKETPLACE`.

#### 6.4.2 Generator decisions (P3 review, 2026-10-03)

1. **Short title set.** At least one valid option → `COMPLETE` (1 unit) with the shortfall recorded in `output_structured` (`expected_option_count`, `delivered_option_count`, `short`, a label); options are never invented to fill the gap. Zero valid options → `FAILED`.
2. **Facts used for generation.** Stored `seller_fact` rows load only by exact non-null `sku`; the latest row per `(fact_type, attribute_name)` wins; with no `sku` only the request's inline facts are used. `NICHE` and `TARGET_PRICE` never feed copy (the `TARGET_PRICE` value is never read). `FREE_TEXT` is context only (shown to the model as a seller note, never a structured factual attribute, and not part of the text the output checks treat as grounded). Attributes named as a price (`price`, `pricing`, `mrp`) are excluded. A product name is the `ATTRIBUTE` fact `product_name`. Identical unnamed `FREE_TEXT` notes for a sku are inserted once.
3. **`NEEDS_FACTS`** has no minimum-fact threshold. It is returned when the model declares missing facts instead of content, or when the retries are exhausted on a reply that stated an ineligible attribute (the ineligible attribute's name is the fact to supply). Fact names are screened (short, no digits or symbols, no forbidden or price words) before they are persisted or shown.
4. **Failed rows.** After a request is accepted (valid key, known approval/option ids), every per-artefact failure persists a `FAILED` `cmo_generation` row (0 units) whose `output_structured` carries `failure_code`, `missing_facts` and counts/rule ids only. Request-level validation errors persist nothing.
5. **Approval re-validation.** A seller-edited title is validated against the CURRENT resolved constraint for the marketplace; if that cannot be resolved the approval is refused. The historical constraint of the title set is not trusted. The category context is the one the title set was resolved under, persisted in its `output_structured.category_context` (`category_hint`, `resolved_category`); approval never takes a caller-supplied hint.
6. **Approval selection.** Copy actions take an explicit `approval_id` or an explicit `seller_title`; "latest approval" is never inferred (C8).
7. **Parse-safety ceilings** are technical implementation limits (`generation/safety_limits.py`), not marketplace or business rules. They are never shown as a marketplace rule, never recorded in `constraint_check`, and never substitute for a limit the verified row does not state. A reply beyond a ceiling is `OUTPUT_TOO_LARGE` (0 units), never truncated.
8. **Hashtags** (separate marketing artefact; no marketplace format constraint) require the configuration key `hashtag_set_size` (a positive integer; the maximum number of hashtags per set); absent or invalid → `CONFIG_MISSING`, 0 units. It never blocks titles or copy.
9. **Flipkart structured fields.** No field taxonomy exists (Q5); a Flipkart pack echoes `description_type` and carries `structured_fields.state = NEEDS_SELLER_INPUT` with no fields, and never claims the fields are filled or enforced.
10. **Cross-marketplace text.** Prompts are marketplace-isolated (no other marketplace's output is ever in scope). Identical description/bullet text across packs delivered in one request is recorded as a diagnostic only; no cross-marketplace rule fails a pack.
11. **Composition-root configuration.** The model name and the provider timeout come from the composition root, not `cmo_platform_config`. A category hint matches `format_constraint.category` by exact normalised equality, then the marketplace-wide row.
12. **Known validation limitation.** A pack that contradicts its approved title in MEANING is not detected. Enforced deterministically: unsupported/ineligible attributes, unsupported numbers, forbidden content, structure.
13. **CI input.** P3 generates in `INDEPENDENT` mode only; CI-informed generation is P11.

### 6.5 Catalog Q&A and attribute-basis labelling

`CATALOG_ANSWER` covers category, vertical, colour, approximate weight, material, size and similar catalog fields, per marketplace where the answer is marketplace-specific. Each returned attribute carries one basis:

| Basis | Meaning | May be asserted in copy? |
|---|---|---|
| `SELLER_PROVIDED` | The seller stated it (traceable to a `seller_fact`) | Yes |
| `IMAGE_OBSERVED` | Literally visible in the seller's image per the structured analysis (§6.2) | Yes — only the observed fact |
| `SOURCE_DERIVED` | Taken from a cited, dated source (URL + `retrieved_at`) | Yes, with citation |
| `ESTIMATED` | Model inference (e.g. an approximate weight range from product type). Shown as a **range with its stated basis**, labelled an estimate, with a "confirm before listing" note | **No** — never as a specification |
| `UNKNOWN` | Not determinable. Stated plainly; CMO asks the seller | No |

- **Approximate weight / dimensions** are never observable from a photo: they are `SELLER_PROVIDED`, `SOURCE_DERIVED`, `ESTIMATED` (labelled, ranged) or `UNKNOWN` — never `IMAGE_OBSERVED`.
- **Category / vertical:** no marketplace category taxonomy source exists in the spec set (Q5). V1 therefore returns a *suggested category path in plain terms*, basis `ESTIMATED`, with an explicit instruction to confirm in the marketplace's own category tool. CMO **never asserts browse-node ids, category ids or required-attribute schemas** it cannot cite.
- The seller's reply to a confirmation request is stored as a `seller_fact`, upgrading that attribute to `SELLER_PROVIDED` for later generations.
- Unknown attributes are listed as unknown. They are never filled to make an answer look complete.

#### 6.5.1 Catalog Q&A decisions (P4)

1. **Closed question set:** category, vertical, colour, material, size, weight, dimensions, brand. Aliases ("colour"/"color", "net weight") are linguistic synonyms for recognising the seller's own attribute names and never supply a value. Free-form "any attribute" questions are not V1.
2. **Precedence, per attribute, deterministic:** the latest seller fact (`SELLER_PROVIDED`, same latest-wins rule as §6.4.2 item 2; a later EMPTY statement clears it and the older value is not resurrected) → a passed-gate, observable `IMAGE_OBSERVED` attribute → a validated `ESTIMATED` value → `UNKNOWN` with an explicit seller-input requirement. Earlier different seller values are reported as `superseded_values`; a passed observation that disagrees with the seller is reported as `conflicting_observation` and never overrides the seller.
3. **Image evidence.** Weight and dimensions are never `IMAGE_OBSERVED`; category and vertical are marketplace taxonomy and are not established by a photo. An `UNVERIFIED_HINT` is never an answer: it appears only as a "suggested from your photo - please confirm" suggestion on an attribute that stays `UNKNOWN`.
4. **`ESTIMATED` only through an injected `Estimator`, none wired in P4** (unresolved estimable questions answer `UNKNOWN`). Only weight and dimensions may be estimated, as an integer range with a known unit and never a point value; only category and vertical may be estimated, as digit-free plain words (no category id, browse-node id or taxonomy code). Colour, material, size and brand are never estimated. Every estimate states its basis in plain words, is labelled "Estimate - confirm before listing", is never claim-eligible, and never overrides a seller fact or a passed observation. An estimator outage never fails an answer.
5. **`SOURCE_DERIVED`** is part of the vocabulary but is not produced in V1: no cited-source store exists.
6. **Billing.** One `CATALOG_ANSWER` per marketplace answered (one product-level artefact when no marketplace is given), 1 unit, idempotent on `(request_key, CATALOG_ANSWER, marketplace)`. An accepted request is always `COMPLETE`: a mostly-`UNKNOWN` answer is a delivered answer (it tells the seller what to supply). No model call is made.
7. **`cmo.confirm_image_hint`** records one new `SELLER_PROVIDED` `seller_fact` (attribute type, linked to the analysis through `image_analysis_id`, attached to a required sku), costs 0 units, calls no model, and never modifies the analysis row or trusts the hint. Re-confirming an identical value is a no-op.

### 6.6 Hashtags (C12)

A hashtag is generated **inside a listing artefact only where `format_constraint.hashtags_supported` is true** for that marketplace. In V1 every row is `NULL` (not established), which is treated as *not supported*. Therefore hashtags are produced **only** as a separate optional `HASHTAGS` artefact (`cmo.generate_hashtags`), explicitly labelled *"marketing suggestions — not a listing field on any marketplace"*, usable by the seller on social/marketing channels of their choice. CMO never states or implies a marketplace supports hashtags without a verified `format_constraint` row. Establishing support for a marketplace is a data change (a verified row with `source_url`/`verified_at`), not a code change.

### 6.7 CI-informed generation (optional, never blocking — C11)

**What CI actually produces today** (verified against code, 2026-10-03): `competitor_listing_insight` rows (`keyword_themes`, `title_structure`, `feature_categories`, `benefit_term_patterns`, `differentiation_opportunities`, `bullet_count`; `confidence = DERIVED`, `derivation_method = LOCAL_HEURISTIC`). `CIHandoff` findings of type `LISTING_GAP` / `DIFFERENTIATION_OPPORTUNITY` are **defined in the schema but not emitted by any code**. V1 CEO-brokered mode therefore consumes `competitor_listing_insight` rows only; if CI later emits real `LISTING_GAP` findings, this section is amended.

- **Attachment path.** CEO reads the tenant's `competitor_listing_insight` rows through a read-only CI repository function and passes their ids + attribute payload as declared fields. This is a data read, not a CI agent invocation: no CI run, no CI unit consumed. It requires **both** `agent.ci` (permission) **and** a passing CI entitlement check (`resolve_ci_entitlement`, evaluated but **not consumed** — no CI run occurs, so no CI unit is spent). Failing either check → independent mode with a note; CMO never errors on it (round 2, resolves old Q8). CMO validates each id belongs to the tenant (`404` otherwise) and **snapshots the exact attributes used** into `ci_inputs_snapshot`, so provenance survives CI-side purges.
- **Use rules.** `differentiation_opportunities` are *single keyword themes other tracked competitors use that a given listing lacks* — an observation about the competitive field, never a claim about the seller's product (`competitor-intelligence-agent.md` §6.19.2: absence of evidence is not evidence of absence). CMO may use such a theme in copy **only if** the seller's product has a claim-eligible attribute supporting it; otherwise it is surfaced as *"consider adding if true for your product"* and never asserted. Competitor text is never copied (C16 facts-not-expression; only derived attributes are consumed).
- **Fallback.** No rows, stale, `DEGRADED`/`UNAVAILABLE`, seller lacks `agent.ci` or fails the CI entitlement check, or any read error → independent mode, with a one-line note. `ci_inputs_snapshot` is set only when attributes were actually used; `input_mode = CEO_BROKERED_CI` is recorded only then (AC2).
- Competitor prices are never consumed by CMO.

### 6.8 Market trends

#### 6.8.1 Architecture decision (C10) — unchanged in principle

**Problem.** The seller asks *"What's trending in the market right now?"* and expects (1) signals for their own niche, (2) e-commerce and marketplace news, (3) reported tactics, (4) new products and buzz, (5) adjacent opportunities, (6) a clearly labelled interpretation for their business, and (7) the evidence behind all of it — **without CMO calling PI and without duplicating PI's retrieval infrastructure.**

**Facts established.** PI has no "Market Outlook" feature (readiness §1's term is the unbuilt forecasting-gate fallback). PI **dropped Google Trends** and reassigned trend work to CMO (`product-intelligence-agent.md` C14). PI's reusable asset is its source layer: `sources/tavily_client.py`, `youtube_client.py`, `rate_limiter.py`, `cache.py`. PI's discovery pipeline (candidate synthesis, `proxy_score`, feasibility, suppliers) is PI's product and is not reused.

**Decision — a shared Market Signal Retrieval service (OP9 pattern).**

| Layer | Owner | What it does |
|---|---|---|
| **Market Signal Retrieval** (shared service, new) | Neither agent | Bounded, deterministic retrieval. Input: server-built query strings from **fixed templates + seller-confirmed niche terms** (§6.8.3) and the section being researched; `region = IN`. Output: dated, cited items `{source_url, source_title, source_type, published_at?, retrieved_at, attention_metrics?}` plus a run record. **No LLM, no interpretation, no ranking of products.** Built by lifting PI's `sources/` clients, throttle and cache into a shared package; PI is re-pointed at it behind the R9 gate (plan + regression tests before any PI code moves). |
| **Evidence computation** | CMO deterministic code | Independence, recency, corroboration (§6.8.4). |
| **CMO trend interpretation** | CMO (Brain 3) | Groups retrieved items into themes, writes finding summaries and the interpretation section; local-derivation posture as PI C9 (raw snippets processed in memory, never persisted, never sent to a hosted provider). |
| **PI** | PI | Unchanged. Ranked candidates, feasibility, suppliers. A finding may *suggest* "investigate with Product Intelligence"; **CEO** offers it. CMO never invokes or imitates PI. |

Importing `product_intelligence.sources` directly would couple the two agents' packages; having CEO fetch PI output would run PI's paid discovery for a free agent's question and breach CEO C4. A shared service is OP9's rule: *bounded services are shared; agent reasoning is CEO-brokered.*

#### 6.8.2 The seven report sections

A trend report always renders all seven headings. A section may be `UNAVAILABLE` with a reason, but is never silently omitted.

| # | Section | Contents | Required per finding | Labelling rule |
|---|---|---|---|---|
| 1 | **Your niche** | Signals related to the seller's **confirmed** niche terms and products | ≥1 dated source; theme; summary; attention metric if the source gives one; recency; corroboration | "Attracting attention in [source], [date]" — never "selling", "in demand" or "trending" as fact |
| 2 | **Marketplace and e-commerce news** | Dated platform **policy, fee, seller-program and seasonal** updates relevant to the sellers' marketplaces and niche | `news_kind` (`POLICY | FEE | SELLER_PROGRAM | SEASONAL | OTHER`); `source_class` (`OFFICIAL_MARKETPLACE` if the registrable domain is one of the OP2(a) domains — `amazon.in`, `flipkart.com`, `meesho.com` — otherwise `THIRD_PARTY`); `published_at`; `effective_date` **only if stated verbatim in the source**, else null — CMO never infers a date from its own knowledge | States *what changed* and links the source. **No numeric claim (fee %, price, threshold) is restated in V1** (§6.8.7 rule 5); FEE items point to Brain 1's fee reference / CFO for margin impact. A third-party report of a policy is labelled as such, not as an official announcement |
| 3 | **Reported tactics** | Tactics, tricks and approaches **attributed to** dated sources | `attributed_to[]`; `claim_status = REPORTED_NOT_VERIFIED` (constant); `policy_risk` (`NONE_IDENTIFIED | POSSIBLE | LIKELY | UNASSESSED`) with `policy_risk_basis` (`PATTERN_MATCH | MODEL_FLAG | BOTH | NONE`); evidence limitations | Shown as "reported by [source]", never as proven and never as advice. §6.8.7 rule 3 governs rule-breaking tactics |
| 4 | **New products and buzz** | Launches, viral products and emerging themes | `buzz_kind` (`LAUNCH | VIRAL_PRODUCT | EMERGING_THEME`); ≥1 dated source; attention metric as reported by the source (e.g. view count, attributed) | Always "attention signal — not proof of sales". Ordered deterministically by corroboration then recency, with the ordering stated; **no score, rank, `proxy_score`, feasibility or supplier work** (that is PI's) |
| 5 | **Adjacent opportunities** | Related categories and product ideas worth investigating | `relation_to_niche`; ≥1 dated source | "Worth investigating". Not ranked, sized or called winners. Separate from PI product discovery; a hand-off hint to PI is offered by CEO, never executed by CMO |
| 6 | **What this could mean for your business** | CMO's **interpretation** (Brain 3) | Each item cites ≥1 finding id from sections 1–5 (`derived_from_finding_ids`) and an `action_type` (`LISTING_KEYWORD_IDEA | CONTENT_ANGLE | WATCHLIST | INVESTIGATE_WITH_PI | NO_ACTION`) | Heading and every item carry *"CMO's interpretation — not a verified market fact."* Introduces no new facts or numbers; a deterministic checker rejects items citing missing findings, containing numerals absent from the findings, or using banned phrasing |
| 7 | **Evidence and limitations** | Source table (URL, title, source type, **publication date, retrieval date**, independence key, source class), per-finding independent-source count and recency, degraded sections with reasons, budget used vs allowed, providers/modes actually used, explicit data gaps | Never empty | Fixed gaps always listed: no marketplace sales data; no search-volume/keyword-demand data; coverage limited to the retrieval service's configured sources; source dates may be missing |

Finding record (sections 1–5): `{finding_id, section, theme, summary, sources[{url, title, source_type, published_at|null, retrieved_at, independence_key, source_class}], mention_count, independent_source_count, freshest_published_at, recency_class, corroboration, is_stale, limitation_note, section-specific fields above}`.

#### 6.8.3 Catalog-seeded niche — confirmation before any external research (C15)

1. **Term sources.** (a) terms the seller types (`SELLER_STATED`); (b) terms already held as `seller_fact` CATEGORY/NICHE (`SELLER_FACT`); (c) **catalog-derived suggestions** (`CATALOG_DERIVED`) from the seller's own ingested data.
2. **What may be read for suggestions.** A typed, read-only function returning **only distinct `item_title` strings** from the tenant's stored sales lines (`data-foundation.md` §`sales_line.item_title`; no category column exists in the canonical model, so category terms are not derivable from reports). It returns no amounts, quantities, order ids, customer fields, settlement data or file bytes, and it is bounded by a row cap (config `catalog_titles_read_cap`). Suggestion derivation is **deterministic** (normalise, drop stopwords, frequency over distinct titles, bounded count); no LLM sees catalog titles in V1. Requires `agent.cmo` and the member's right to view the underlying data (`catalog.view`, Q18 resolved). If the tenant has no usable titles, suggestions are `UNAVAILABLE` and the seller types a niche.
3. **Outbound screen.** Every candidate term, whatever its origin, passes a deterministic screen: length bounds (config), no email/phone/GSTIN-pattern/order-id-pattern/URL tokens, not purely numeric. A term failing the screen is never offered and never sent.
4. **Confirmation.** Suggested terms are shown with their origin; the seller **confirms, edits (an edit becomes a new `SELLER_STATED` term) or rejects** each. Only `CONFIRMED` terms, up to `max_confirmed_niche_terms` (config), may enter a query. Before the first send of a report, the exact `outbound_queries` are displayed. Confirmed terms persist for reuse until the seller changes them; suggestions refresh only on explicit request.
5. **Egress rule.** A research provider request may contain only: fixed template text, confirmed niche terms, and section/marketplace names. Never raw reports, customer data, financial figures, SKUs' sales data, images, prices or target price. Every sent query is persisted in `cmo_trend_report.outbound_queries` for audit.
6. **No confirmed terms** → sections 1 and 5 are `UNAVAILABLE` with reason *"confirm a niche to research your products"*; the broader sections (2–4) may still run.

7. **Implementation decisions (P7d, 2026-10-04).** (a) *Config subset:* the niche actions require only `max_confirmed_niche_terms`, `max_term_chars` and `catalog_titles_read_cap` (plus the optional stop-word keys); a missing or invalid value is `503 CONFIG_MISSING` naming the keys and blocks only the niche actions - the rest of the trend set (§6.8.5) is still required for a report. (b) *Routes:* `POST /api/v1/cmo/niche-terms/suggest` (`agent.cmo` + `catalog.view` (changed from `catalog.view` on 2026-10-04, see Q18)), `GET /api/v1/cmo/niche-terms` (`agent.cmo`), `POST /api/v1/cmo/niche-terms/confirm` (`agent.cmo`); all zero-unit, one `agent_run` per accepted suggest/confirm, no metered event, no provider call. (c) *Read:* distinct `item_title` strings only, most-frequently-sold first so the cap keeps the most representative titles (frequency orders the rows and is never returned), at most `catalog_titles_read_cap`. (d) *Suggestions* are stored `SUGGESTED`; a term already stored in any status (including `REJECTED`) is never re-offered; `origin_note` carries counts only, never titles; the number of new suggestions per call is bounded by `max_confirmed_niche_terms`. Seller `CATEGORY`/`NICHE` facts are offered with origin `SELLER_FACT`. (e) *Confirm* takes per-term decisions (`CONFIRM`, `REJECT`, `EDIT` with new text) and seller-typed `new_terms`. A typed or edited term is the seller's own assertion made in that call, so it is stored `SELLER_STATED` and `CONFIRMED`; an edit also marks the original `REJECTED` (an edit that changes nothing is a confirmation; an edit onto an existing term confirms that term). Every typed/edited text passes the outbound screen (`422 NICHE_TERM_REFUSED` with reasons). The request is all-or-nothing and the `max_confirmed_niche_terms` cap is re-checked inside a per-tenant locked transaction (`422 TOO_MANY_CONFIRMED_TERMS`), so concurrent requests cannot exceed it. (f) `NicheService.confirmed_terms` is the only accessor the research layer may use to obtain terms that can leave Metrion. (g) *Deferred to 7e:* the fixed query templates, the exact `outbound_queries` preview and the egress guard that checks each query contains only template text and confirmed terms (AC30 is completed there).

#### 6.8.4 Evidence computed in code (C14)

- **Independence key.** Web items: the registrable domain of the item URL as returned (no fetching, no redirect following). Video items: the channel identifier (`channel_title` if no id is available — verified in P7-0). **Several items with the same key count as one independent source.** `mention_count` (raw) is stored and shown but is never used for strength.
- **Syndication collapse.** Items in one report whose normalised titles are identical collapse to the earliest-published one. Common ownership across different domains cannot be detected; that limitation is printed in the evidence section.
- **Recency.** Per item, from `published_at` vs `retrieved_at`: `FRESH` (≤ `fresh_window_days`), `RECENT` (≤ `recent_window_days`), `OLDER`, or `DATE_UNKNOWN` (no publication date: the retrieval date is shown but is **never** treated as the publication date, and the item can never be `FRESH`). Finding recency = the freshest item's class. `is_stale = true` when the freshest class is `OLDER` or all items are `DATE_UNKNOWN`.
- **Corroboration (not strength of demand).** From `independent_source_count` n and config thresholds: `SINGLE_SOURCE` (n = 1), `WEAK` (1 < n < `moderate_min_independent_sources`), `MODERATE`, `STRONG` (n ≥ `strong_min_independent_sources`); downgraded one level if recency is `OLDER`; capped at `WEAK` if every item is `DATE_UNKNOWN`. Labelled everywhere *"corroboration of attention, not of demand."* The LLM never assigns or edits these fields.
- **Agreement ≠ demand.** Source agreement and online attention are never equated with actual demand, sales or profitability (§6.8.7 rule 1).

#### 6.8.5 Budgets and configuration (C16) — all unset until you decide (Q15)

Required `cmo_platform_config` keys for a trend report: `max_queries_per_report`, `section_query_budgets` (per section; must sum to ≤ the report cap), `section_priority` (order in which sections consume budget), `max_results_per_query`, `max_sources_per_report`, `max_findings_per_section`, `fresh_window_days`, `recent_window_days`, `news_window_days`, `moderate_min_independent_sources`, `strong_min_independent_sources`, `max_confirmed_niche_terms`, `max_term_chars`, `catalog_titles_read_cap`, `provider_call_timeout_seconds`, `provider_cache_ttl_hours`, `provider_daily_search_ceiling`. Every integer key must be a true integer (not a boolean, not a float, not a string) and positive unless noted; `moderate_min_independent_sources` must be ≥ 2 and `strong_min_independent_sources` must exceed it; `fresh_window_days` must be ≤ `recent_window_days`; each section needs an explicit budget and the section budgets must sum to ≤ `max_queries_per_report`; `section_priority` must list every section exactly once. **Two keys are OPTIONAL, each with an explicit fail-safe rather than a default value** (P2 clarification): `tactic_risk_pattern_set_ref` — absent means no pattern set, so every reported tactic is `UNASSESSED` with no suggested action (§6.8.7 rule 3c; an *empty* set counts as absent); and `official_marketplace_domains` — absent means nothing is ever labelled `OFFICIAL_MARKETPLACE` (seeded only from the OP2(a) list when you approve). Two further optional keys adjust built-in linguistic data rather than supply a policy value: `niche_stopwords_extra` and `niche_stopwords_exclude` (lists of single words added to / removed from the built-in English, listing-filler, Hindi and Romanised-Hindi stop-word sets used to split catalog titles into suggestion phrases, §6.8.3; absent means the built-in sets apply unchanged). **No migration seeds any key and no code supplies a default.** If any required key is absent or invalid the action returns `CONFIG_MISSING` naming each missing key, consumes no unit, and calls no provider. `config_snapshot` records the values actually used.

#### 6.8.5.1 Provider retrieval decisions (P7e, 2026-10-04)

**Starting values (set by the owner as `cmo_platform_config` data - none is a code default; unset or invalid = `CONFIG_MISSING`, no provider call):** `max_queries_per_report` = 10; `section_query_budgets` = 2 for each of the five sections; `section_priority` = `NICHE`, `MARKET_NEWS`, `REPORTED_TACTICS`, `NEW_PRODUCTS_BUZZ`, `ADJACENT`; `max_results_per_query` = 5 (both providers); `news_window_days` = 30; `provider_cache_ttl_hours` = 24; `provider_call_timeout_seconds` = 15 (CMO's client instances only; Product Intelligence keeps its own 10 s); `provider_daily_search_ceiling` = 20 (a **launch-week** value, to be revisited). The remaining trend keys (`max_sources_per_report`, `max_findings_per_section`, `fresh_window_days`, `recent_window_days`, `moderate_min_independent_sources`, `strong_min_independent_sources`) are still unset and still block a report.

1. **Fixed templates and allocation.** Query text is built only from the versioned templates in `slim_cmo.trends.queries` (`*_V1`), filled with at most one confirmed niche term and/or marketplace display names ("Amazon India", "Flipkart", "Meesho"; the seller's selection in canonical order, default all three). Allocation per section, truncated (never extended) by that section's budget: niche = 1 Tavily news + 1 YouTube; marketplace news = 2 Tavily news; tactics = 2 Tavily news; new product buzz = 2 YouTube; adjacent = 2 Tavily news. Sections 1 and 5 need confirmed terms (else `UNAVAILABLE`: "Confirm a niche to research your products."); sections 2-4 never contain a term. One confirmed term per query, in sorted order, across the term-needing queries in section-priority order; terms no query used are listed as unresearched.
2. **Provider options (CMO only).** Tavily: `topic=news`, `days=news_window_days`, `country=india`, `max_results`. YouTube: `regionCode=IN`, `publishedAfter = now - news_window_days`, `maxResults`; exactly one `search.list` plus one batched `videos.list` per search. Product Intelligence's requests are unchanged (options are omitted when unset; pinned by tests). The 2026-10-04 India probe (4 Tavily credits, no seller data): `country` is accepted in news mode and all 11 results carried a publication date; relevance to India is partial (about half of the niche-query hosts were Indian outlets), so the evidence section states that the provider's India filter is approximate. General (non-news) Tavily mode returns no dates and is not used.
3. **Exact preview and egress guard.** The exact outbound queries (text, provider, options) are shown before the first send and persisted in `cmo_trend_report.outbound_queries`. `validate_egress` re-renders every query from template id + term + marketplaces and requires an exact match, the permitted options exactly, confirmed-and-screened terms only, and the budgets; it runs on the whole plan and again before each provider call. Catalog titles, SUGGESTED / REJECTED / unconfirmed terms, seller facts, notes, SKUs, prices and any tenant identifier cannot reach a provider.
4. **Accounting.** One "search" = one Tavily `/search` call or one YouTube search (plus its single statistics batch). A **cache hit** makes no call and takes no daily slot. A daily slot is taken **before** a call and is never refunded, so a **failed attempt counts**. The per-report budget counts every planned query (cache hit or not), so a report's shape is deterministic. Per-provider counts are tracked separately; the ceiling is enforced on the combined total.
5. **Daily ceiling.** Database table `cmo_provider_usage` (platform-wide, no seller data) behind two `SECURITY DEFINER` functions: `cmo_take_provider_slot(provider, ceiling)` (atomic under a per-day advisory lock; derives the day itself from `now()` in **Asia/Kolkata**; refuses when the combined total has reached the ceiling) and `cmo_provider_usage_today()`. The application role has **no privilege on the table** and may only execute the functions. A counter error means no provider call (fail closed). **This ceiling counts CMO's searches only. Product Intelligence uses the same Tavily and YouTube keys and is invisible to it, so it does not protect total provider quota.** Providers' own quota windows differ (YouTube resets at midnight Pacific; Tavily is monthly) and are not mirrored.
6. **Concurrency.** CMO reuses the shared process-wide limiter (3 concurrent calls per provider, **per process**, shared with Product Intelligence); with N server processes up to 3 x N calls may run at once. No separate CMO pool exists.
7. **Cache.** In-process, 24 h, in a `cmo_*` namespace distinct from Product Intelligence's; keys contain the template id, normalised query text and the exact provider options (so different options never share an entry); deliberately not tenant-keyed because keys are built from template text and confirmed terms only and payloads are public search results. Failures are never cached; an empty answer is.
8. **Partial results.** A failed, refused or counter-blocked query degrades only its section (`PARTIAL` if another query answered, else `UNAVAILABLE`, with the reason); other sections proceed. After the ceiling is reached, remaining uncached queries are refused without further database calls while cache hits are still served.
9. **Monthly cap.** 5 trend reports per tenant per month is intended to be enforced through the existing entitlement system on the CMO trend meter (`cmo.market_trends`, month in the tenant's timezone); the shared `research.market_trends` meter is deliberately left unseeded. Cap rows are data: see `packages/slim-cmo/scripts/seed_trend_report_cap.sql` (reviewable, not run by any migration). Two-meter admission for the trend route is implemented in 7f.

#### 6.8.6 Source degradation and completeness

- Each provider/mode fails independently (timeout, quota, HTTP error, unsupported feature). A section is built from the sources that returned; if none did, it is `UNAVAILABLE` with the reason. Nothing is fabricated or back-filled from model knowledge.
- **Budget exhaustion** skips remaining queries in `section_priority` order; skipped sections are `UNAVAILABLE` with reason `BUDGET_EXHAUSTED`.
- **Report state.** `COMPLETE` iff at least one section has ≥1 finding with ≥1 dated-or-date-unknown cited source **and** the evidence section names every degraded section. Otherwise `FAILED` (0 units). A `COMPLETE` report with degraded sections is still one artefact / one unit (Q19), and the seller is told which sections are missing.
- A finding with no citable source is dropped, not asserted.

#### 6.8.7 Honesty and safety rules (extend PI §0 to CMO)

1. **Attention ≠ demand ≠ sales ≠ profitability.** `demand_evidence` is `UNOBSERVED` in V1 (no sales-volume source exists; Q3). CMO never writes "selling well", "high demand", "bestseller", "trending" (as a fact), or any profitability claim; only *"attracting attention in [source], [date]"*. Enforced by the narration-safety check (modelled on PI's `narration_safety.py`) and evals (§7).
2. **Every finding has ≥1 dated source link;** undated sources are flagged `DATE_UNKNOWN`, never assigned a date.
3. **Tactics.** (a) Always `REPORTED_NOT_VERIFIED`; never "proven", "works", or "guaranteed". (b) Every tactic carries the line *"Check the marketplace's current seller policy before trying this."* (c) `policy_risk` is set by a **curated pattern set** (`tactic_risk_pattern_set_ref`, human-maintained — e.g. review manipulation, fake discounts, keyword abuse; contents are Q17, not invented here) **and** may be raised — never lowered — by a model flag. (d) A tactic with `policy_risk ≠ NONE_IDENTIFIED` (including `UNASSESSED`, which is the fail-safe when no pattern set is configured) is shown in a caution group with **no suggested action**; CMO never recommends rule-breaking. (e) Even `NONE_IDENTIFIED` tactics yield at most `WATCHLIST` or `CONTENT_ANGLE`.
4. **Interpretation is labelled and traceable** (section 6); it adds no facts.
5. **No numeric restatement in news/tactics in V1.** Figures, percentages and prices found in sources are not restated; the item says what changed and links the source. Any figure that appears is shown only when verbatim in the retrieved snippet, attributed to the source, and marked "from the source, not verified by Metrion" — and V1 ships with this off (Q22). Margin and fee figures come only from Brain 1/CFO.
6. **No marketplace is fetched** (OP2(a) is not CMO's allowlist). Approved trend sources are the retrieval service's configured sources (Tavily, YouTube — PI C6); adding a source requires a spec amendment. Marketplace pages that surface as web results are cited by link only; their listing copy is never reproduced or persisted (C7 facts-not-expression); quotes, if any, are short and attributed.
7. **Privacy.** §6.8.3 rule 5.
8. **Region/language.** Queries target India and English in V1; Hinglish and regional-language coverage is not claimed (Q23).

#### 6.8.8 Provider capability verification (do not assume)

**Verified in code today:** PI's Tavily client returns per result `url`, `title`, `content`, `score`, `published_date` (nullable) and `retrieved_at`; PI's YouTube client returns `published_at`, `view_count` (nullable) and `channel_title`. Neither client currently uses a news, topic or time-range mode.

**Not verified — to be tested and recorded in `docs/planning/market-signals-provider-capabilities.md` before the retrieval service is built (build step P7-0):** whether a news or recency filter exists and works for India; how often Tavily returns `published_date`; whether a YouTube channel *id* is available for the independence key; per-query result caps; quota/rate behaviour at the configured budgets; regional bias; and the providers' terms for this use. **Any requirement a provider cannot meet is reported as unmet** in that document and in the relevant report section (`UNAVAILABLE` or `DATE_UNKNOWN`); it is never emulated silently or papered over with model output.

#### 6.8.9 Entitlement

One trend report = **1 CMO unit** plus the shared service's own meter (`research.market_trends`) — two independent keys, two independent meters, the `pi.discover` two-key pattern. Suggesting and confirming niche terms consume no units (§8.1.1). Cap values unset (Q1). Provider calls are made only after both the permission and entitlement checks pass.

#### 6.8.10 Trend report execution decisions (P7f, 2026-10-04)

1. **Routes** (all need `agent.cmo` AND `research.market_trends`, checked server-side): `POST /api/v1/cmo/market-trends/preview` (zero units; no provider or model call), `POST /api/v1/cmo/market-trends` (the run), `GET /api/v1/cmo/market-trends` (recent reports, summary), `GET /api/v1/cmo/market-trends/{generation_id}` (one stored report; unknown and cross-tenant ids are an identical 404).
2. **Preview-bound run.** The preview returns the exact outbound queries, the unavailable sections, the disclosed unresearched terms and a `digest`. The run must carry that `plan_digest`; if the confirmed terms, sections, marketplaces or configuration changed since, the run is `409 PLAN_CHANGED` and nothing is sent, reserved or billed. This is how "the exact queries are displayed before the first send" is enforced rather than hoped for.
3. **Two meters.** Admission reserves one unit on the CMO meter (`cmo.market_trends`) and one on the shared meter (`research.market_trends`, agent code `SHARED`) wherever a cap resolves; a denial on either is `402` naming the meter and releases any reservation already taken. Configuration is verified before anything is reserved. A COMPLETE, newly delivered report records exactly one idempotent metered event on each meter; a FAILED report records none. Idempotent replay under the same key returns the stored report with no admission, run, call or units. No cap is seeded (§6.8.5.1 item 9).
4. **Pipeline.** plan -> retrieval (egress-guarded, cached, daily-slot, throttled) -> per-section findings -> interpretation -> evidence -> persistence. The model only proposes themes, summaries and cited item numbers; code validates them (cited items exist and at least one is citable; no attention-as-demand wording; no restated numbers, prices, tax or contact content; closed kind sets), computes all evidence (independent sources, syndication collapse, recency, corroboration, staleness), sets tactic policy risk (pattern set, fail-safe `UNASSESSED`; a model flag only raises) and attaches attention metrics only from the provider's structured fields. Rejected proposals are counted by rule id in the evidence block, never edited into compliance; a section with nothing supportable is `UNAVAILABLE`, never filled from model knowledge. Retrieved items whose own text addresses the model are withheld from the prompt and counted. Findings per section are capped by `max_findings_per_section` and retrieved items per report by `max_sources_per_report` (dropped items disclosed).
5. **Report state.** `COMPLETE` iff at least one finding has a citable source (degraded sections are named in the evidence block with their reasons and the report is still one artefact: 1 CMO unit + 1 shared unit); otherwise a `FAILED` generation row is persisted (no report row) and nothing is billed. A FAILED attempt does not block a retry under the same key. The model being unavailable fails the report; an unavailable interpretation step does not.
6. **No tactic-risk pattern set exists yet** (launch blocker H6): every tactic is `UNASSESSED`, shown in the caution group with no suggested action, and interpretation items on it can only be `NO_ACTION`.
7. **Persistence.** One `cmo_generation` row (`TREND_REPORT`, no marketplace) plus one `cmo_trend_report` row (sections, interpretation, evidence, outbound queries, config snapshot, confirmed term ids) in one tenant-scoped transaction; append-only for the application role.
8. **Independent review fixes (P10, 2026-10-04).** A read-only `code-reviewer` pass over the trend/niche/GST code found no defect in the money, tenant-isolation, egress, fail-closed or recommend-only invariants, and three medium and several low issues, handled as follows. (a) *Interpretation* now gets the same content checks as findings (price / tax / contact / URL wording via the forbidden scan, bidi controls, and any figure that has no source in the cited findings). (b) *Replay* is per output type (a COMPLETE title set under the same key no longer blocks a trend report) and per plan: the stored report records the `plan_digest` it was built from, and the same key with a different plan is `409 REQUEST_KEY_REUSED`; losing a race to an identical in-flight request serves the winner's report as a free replay instead of a 500. (c) *Cache privacy:* provider results for a query that carries a seller's niche term are cached per tenant (so a cache hit can never reveal that another seller researched the same term); term-free queries are shared; expired entries are swept on every put. (d) `GET /niche-terms` without `catalog.view` returns only the seller's CONFIRMED terms. (e) `target_price_paise` is bounded to the BIGINT range (a technical bound) so an absurd value is a `422`. (f) The GST route-B "verified" guard fails the runs before they are marked complete. **Accepted / documented, not changed:** (g) *one tenant can consume the shared daily ceiling* because a tenant with no cap configured is unlimited and a FAILED report still uses its provider slots: **seeding the per-tenant monthly cap (§6.8.5.1 item 9) before launch is therefore a launch gate**, and the ceiling is a launch-week guard only; (h) the daily ceiling is passed to the database function by the application: it must be set at platform level (`tenant_id` NULL) by an operator (the application role cannot write configuration), and a holder of the application credential could already do more harm directly; (i) the CEO-hub dispatch functions take the tenant, role and permissions as arguments and are not safe to call with request-derived values: the future CEO caller must pass the authenticated session's values; (j) a letter-spaced multi-word banned phrase (`h i g h  d e m a n d`) is not recognised (single words are).

### 6.9 GST — not a CMO capability (C4); CEO-handled, two routes

CMO never touches GST. A product GST question in a CMO conversation is classified by **CEO** and handled through exactly one of two routes, chosen by the **member's permissions**, never by the model:

| Route | When | What runs |
|---|---|---|
| **A — CFO** | Member holds `agent.ceo` + `agent.cfo` + `service.gst_lookup` | CEO delegates `cfo.gst_lookup` (C4 one action). CFO's existing OP13 layered resolution (observed → curated HSN KB → provisional cited lookup) applies unchanged. |
| **B — CEO shared-service call** | Member holds `agent.ceo` + `service.gst_lookup` but **not** `agent.cfo` | CEO calls the shared **GST Applicability Lookup service** directly (a shared service — `ceo-agent-orchestration.md` C1/§6.1; OP9 — not agent delegation, so no CFO entitlement and no CFO output is involved). **Tier 3 only**: tiers 1–2 of OP13 read CFO-owned data (seller reports, curated KB) and remain CFO's. |
| **Neither** | Member lacks `service.gst_lookup` | Permission wall explained; no model-knowledge answer ever. |

**Safety conditions for Route B — all must hold; the route is not shipped if any cannot be shown by test (G1–G7):**
- **G1 No permission bypass.** `service.gst_lookup` is enforced server-side exactly as `cfo.gst_lookup` enforces it (`403` if absent); `agent.ceo` is required; CEO's routing is advisory (CEO C8) and the key is checked inside the shared-service entry point, not in the CEO classifier.
- **G2 Independent metering.** The call meters the shared GST meter (`resolve_gst_lookup_entitlement`) and CEO's turn unit; it consumes **no** CFO or CMO unit. An exhausted GST cap is an entitlement denial.
- **G3 Provisional only.** The result is stored as a `gst_lookup_result` with `status = PROVISIONAL`, carrying `source_url`, `retrieved_at`, `ambiguity_note`, `alternatives` and the L5 disclaimer. It is never labelled verified.
- **G4 No calculation effect.** A Route-B result can never become a `gst_rate_override`: acceptance into any calculation remains CFO's flow, requiring `agent.cfo` **and** `financials.adjust`. A member without CFO cannot influence a P&L through this route.
- **G5 No paid-output leakage.** Route B returns the lookup result and nothing derived from CFO analyses, reconciliation or the seller's financial data.
- **G6 Input integrity.** Product name/category passed in carry their basis (`SELLER_PROVIDED | ESTIMATED`); an `UNVERIFIED_HINT` image attribute is **not** passed as a category (§6.2.1). If the category basis is only estimated, the answer says so.
- **G7 Audit.** Every call writes an `agent_run` row (`trigger_ref = "service.gst_lookup"`, `parent_run_id` = the CEO turn row).

In both routes the rate shown is copied from the structured `gst_lookup_result` — never generated by an LLM — and the composed answer states the source, retrieval date and uncertainty, and never says "verified" unless the record's status is `SELLER_VERIFIED`. CMO-generated copy never states a GST rate or tax treatment.

---

## 7. AI requirements

| Brain | Role |
|---|---|
| **Brain 1** | Not called by CMO in V1. CMO performs no money arithmetic and consumes no engine result. (`TARGET_PRICE` is echoed, not computed on.) |
| **Vision slot (`VisionProvider`)** | Structured extraction from the seller's image only (§6.2). |
| **Brain 3 (LLM)** | Title options, description, bullets, keywords, hashtags, catalog answers, trend interpretation. Creative output is the product here *because nothing generated is a financial or compliance fact*. |
| **Deterministic code** | Constraint validation (lengths, counts, bytes), option count, `char_count`, claim-eligibility filtering, source counts/dating, idempotency and metering. |

**Hard boundaries inside generation:** the LLM never states a GST rate, a fee, a margin or a price; never asserts an `ESTIMATED`/`UNKNOWN` attribute as a specification; never reports its own length compliance; never presents attention as demand.

**Evals required before any narration surface ships** (`CLAUDE.md` LLM-evals rule), at minimum: (1) no number appears in output that is absent from seller input, structured analysis, or cited sources; (2) no `ESTIMATED`/`UNKNOWN` attribute appears as a fact in copy; (3) no GST rate/tax claim appears in any CMO output; (4) no "trending/selling well/high demand" assertion without the attention/demand distinction; (5) every trend finding carries a dated source; (6) a `DEGRADED`/`UNAVAILABLE` input is never narrated as a real result; (7) vision outputs: no field reported that is not literally visible (regression against the Q18 failure class); (8) CI `differentiation_opportunities` never asserted as a claim about the seller's product; (9) a tactic matching a risk pattern, or with `UNASSESSED` risk, never receives a suggested action and is never described as working; (10) duplicate-source items never raise corroboration; (11) news/tactic items contain no restated numeric claims; (12) every interpretation item cites existing findings and adds no new fact or number; (13) no unconfirmed niche term, catalog title or financial/customer field appears in any outbound provider query; (14) copy packs contain no attribute that is not claim-eligible and no content copied across marketplaces; (15) sparse-fact inputs yield `NEEDS_FACTS`, not invented content.

---

## 8. Authorization, entitlement and billing semantics

### 8.1 Registered direct execution paths

> **Amended 2026-10-12:** seller-facing use of these paths is superseded by CEO-first delegation (see the note at the top of this spec and `ceo-cmo-delegation.md`). The table below remains the authority for action keys, permissions and units; the routes are no longer a seller entry point.

Per `auth.md` §5.2 guardrail — one named action, declared fields only (§6.1), no generic "invoke CMO" endpoint. Each writes one `agent_run` row (`ceo-agent-orchestration.md` C7).

| Trigger | Action | Permission | CMO units |
|---|---|---|---|
| `cmo.generate_title_sets` | One 5-option `TITLE_SET` per selected marketplace (1–3) | `agent.cmo` | **1 per marketplace delivered** |
| `cmo.generate_listing_copy` | After approval: one `LISTING_COPY` artefact (description + bullets + keywords) for one marketplace, grounded in the approval | `agent.cmo` | **1 per marketplace delivered** (round 2: copy pack = 1 unit) |
| `cmo.generate_description` / `cmo.generate_bullets` / `cmo.generate_keywords` / `cmo.generate_backend_terms` | One component artefact, grounded (for a seller who wants only that piece; Amazon backend terms are always their own artefact) | `agent.cmo` | 1 each |
| `cmo.generate_hashtags` | Separate optional hashtag suggestions | `agent.cmo` | 1 |
| `cmo.catalog_answer` | Answer catalog question(s) with basis labels | `agent.cmo` | 1 per marketplace answered (product-level, marketplace-independent question = 1) |
| `cmo.suggest_niche_terms` | Derive niche-term suggestions from the seller's catalog titles (deterministic; no provider call) | `agent.cmo` and `catalog.view` (Q18 resolved 2026-10-04) | **0** |
| `cmo.confirm_niche_terms` | Confirm / edit / reject niche terms | `agent.cmo` | **0** |
| `cmo.market_trends` | One seven-section trend report (§6.8) from **confirmed** niche terms (+ broader sections) | `agent.cmo` **and** `research.market_trends` | 1 CMO unit **+** the shared-service meter, independent |
| `cmo.approve_title` | Persist an approval (no LLM) | `agent.cmo` | **0** |
| `cmo.confirm_image_hint` | Record the seller's confirmation (or correction) of an image-derived hint as a new `SELLER_PROVIDED` `seller_fact`; changes no analysis row and trusts nothing (no LLM, §6.2.1) | `agent.cmo` | **0** |
| `cmo.upload_image` | Validate, normalise (EXIF/GPS and all metadata stripped), hash and store ONE seller image (P6, §6.2.2) | `agent.cmo` **and** `files.upload` | **0** |
| `cmo.analyze_image` | Run the local vision model over a stored image and persist an immutable analysis (P6, §6.2.2) | `agent.cmo` | **0** (per-tenant rate limit) |

(`cmo.gst_answer` is **removed** — C4; GST is CEO-handled, §6.9.) Image upload is `files.upload`-gated and unmetered by CMO.

#### 8.1.1 Complete billing table (every artefact and action)

| Artefact / action | Output | Units | Notes |
|---|---|---|---|
| `TITLE_SET` | 5 options for **one** marketplace | **1 per marketplace delivered** | 3 marketplaces = 3 |
| Title approval / edit-and-revalidate | approval record | **0** | no LLM |
| `LISTING_COPY` | description + bullets + keywords for **one** marketplace | **1 per marketplace delivered** | atomic: all three valid or `FAILED` / 0 |
| `DESCRIPTION`, `BULLETS`, `KEYWORDS` standalone | one component | **1 each** | new artefact even if a pack exists; no dedupe; pack row immutable |
| `BACKEND_TERMS` | Amazon hidden search terms | **1** | Amazon only; other marketplaces refused |
| `HASHTAGS` | separate marketing suggestions | **1** | never inside a listing field unless `hashtags_supported` is verified |
| `CATALOG_ANSWER` | attribute answers | **1 per marketplace answered** (1 if marketplace-independent) | |
| Niche-term suggest / confirm | term rows | **0** | |
| `TREND_REPORT` | seven-section report | **1 CMO unit + 1 shared-service meter event** | `COMPLETE` iff §6.8.6; refresh/regeneration = new artefact |
| Image analysis | structured analysis | **0** separately (bundled; reuse free) | Q4 may revisit |
| Hint confirmation, viewing past artefacts | | **0** | |
| Any `FAILED` artefact, `CONFIG_MISSING`, `E5` block, denied request | | **0** | |

Worked totals: one product, all three marketplaces, titles + packs = **6 units**; adding hashtags (3 sets) = 9; adding Amazon backend terms = 10; a trend report adds 1 CMO unit (+ shared meter).

### 8.2 Units — one artefact, one row, one unit

`billable_units = 1` per `cmo_generation` row. A **five-title set for one marketplace is one artefact = one unit**; three marketplaces = three rows = **three units**. Rows are written, and units counted, **only for artefacts actually delivered** (`status = COMPLETE`). **Worked example (one product, all three marketplaces, full workflow): 3 title-set units + 3 listing-copy-pack units = 6 units**; one marketplace = 2 units. Everything else is billed per §8.1.1. Image analysis is **not separately metered** in V1 (its cost is bundled into the first generation that uses it; stored analyses are reused free) — Q4 asks whether that stays true once a vision provider and its cost are chosen.

### 8.3 Retries, regeneration, failures

| Situation | Behaviour |
|---|---|
| **Internal automatic retry** (transport error, LLM error, constraint violation repaired by regeneration) | Bounded by `internal_retry_bound` (configuration, unset — Q1; an explicit `0` is legitimate and means no internal retries; a missing value blocks generation with `CONFIG_MISSING`, it is never defaulted). The staleness policy `format_constraint_max_age_days` is likewise a required positive-integer key. Consumes **no additional unit**; one delivered artefact = one unit regardless of internal attempts. |
| **Failed artefact** (retries exhausted, constraint block E5, vision failure with no seller-confirmed text-only fallback, provider outage) | `status = FAILED`, `failure_reason` recorded, **0 units**, no `metered_event` (entitlement.md rule 3). The seller is told exactly why. |
| **Seller-initiated regeneration** ("give me 5 new titles") | A **new artefact**: new `cmo_generation` row, **1 new unit**, new `request_key`. The earlier set and any approval on it remain intact and auditable. |
| **Partial multi-marketplace request** (e.g. 3 marketplaces, one fails) | Delivered marketplaces are billed (`n` units); the failed one is reported with its reason and billed 0. `agent_run.status = PARTIAL`. |
| **Edit of an approved title** | Not a generation. Re-validated deterministically; 0 units. |
| **Duplicate submission / double-click / client retry** | Idempotent on `request_key` (+ output_type + marketplace; the key is 1–128 characters of letters, digits and `. _ : -` — an internal implementation limit, §6.4.1): returns the existing artefact, **no second row, no second unit** (`entitlement.md` rule 4). |
| **Approval, viewing, reading past artefacts** | 0 units. |
| **Metering write fails after delivery** | Result still returned; metering retried/reconciled out of band (`entitlement.md` D4). |

### 8.4 Monthly caps and the pre-check

- Caps are `entitlement_cap_config` rows keyed `(agent_code = 'CMO', meter_code)`, `scope = TENANT`, period = tenant-timezone month (`entitlement.md`). **No cap value is seeded and none is invented here;** the provisional free figure "10/month" (readiness §1) remains Q1. Until a row is seeded the chokepoint resolves `NO_CAP_CONFIGURED` and passes — this spec states that plainly rather than implying a limit is enforced.
- **Up-front, all-or-nothing check for multi-artefact requests.** Before any generation runs, the chokepoint is asked for the request's full unit count `N` (e.g. 3 marketplaces → 3). If remaining < `N`, the **whole request is denied** (entitlement denial, not permission denial — `auth.md` §7.2) with the remaining count, and the seller may re-request fewer marketplaces. No partial generation is started in order to "use up" remaining units. *(This is the CMO resolution of old Q5/E6b for registered actions — flagged for confirmation, Q10.)*
- Exhaustion **after** an artefact is delivered never revokes or hides it.
- **Serialised quota reservations (P5, 2026-10-04).** The up-front check above is made atomic so concurrent requests cannot exceed a cap (`entitlement.md` E2/Q5 amended). When a cap resolves for the request's meter, the whole request's unit count is RESERVED (`cmo_quota_reservation`) in one short transaction under `pg_advisory_xact_lock` on `(tenant, agent, meter, period)`; usage = recorded `metered_event` units + unexpired reservations, and `billing.precheck` decides all-or-nothing. A denial is `402` and executes nothing; an identical request (same key) already in flight is `409`. No reservation is made when no cap resolves, and none is needed for replays (a reused artefact is free). No database connection is held while a model runs. A reservation is **quota protection, never a billing record**: billing is the persisted terminal artefact `status` (`COMPLETE` only) plus an idempotent `metered_event` per artefact (`cmo:<generation_id>`); `billable_units` is not read. After execution the reservation is `SETTLED` once every delivered unit is a recorded event; if a metering write failed it stays `RESERVED` until its TTL so the unmetered unit still counts against the cap, and replaying the same request key re-asserts the idempotent event (reconciliation, `entitlement.md` E3). A reservation expires after `CMO_QUOTA_RESERVATION_TTL_SECONDS` (**300 s**; required configuration with no code default: if a cap exists and it is missing the request is `503 CMO_NOT_CONFIGURED`). The CMO model, Ollama host and timeout are likewise required configuration (`CMO_LLM_MODEL`, `CMO_OLLAMA_HOST`, `CMO_LLM_TIMEOUT_SECONDS`) with no defaults.
- **HTTP behaviour (P5).** An accepted, executed request is `200` with `runStatus` and per-artefact results (a `FAILED` artefact is a persisted result, not an HTTP error); `401/403` auth chain; `402` quota; `404` unknown or cross-tenant id (identical); `409` identical request in flight; `422` invalid request; `503 CMO_NOT_CONFIGURED`; any unexpected failure is a generic `500`. One `agent_run` is written per accepted, executed request; an idempotent replay reuses the existing result and run and writes none. `cmo.approve_title` and `cmo.confirm_image_hint` are zero-unit: no entitlement check, no reservation, no metered event. There is no route that publishes to or updates a marketplace.
- Conversational requests (`agent.ceo` + `agent.cmo`) meter identically; CEO's own per-turn unit (`ceo-agent-orchestration.md` D5) is separate and additional.

### 8.5 Chain

All paths enter the `auth.md` §7.1 six-step chain; permission and entitlement are evaluated independently (§7.2). `research.market_trends` is a shared-service key granted independently of `agent.*` and metered under its own `meter_code` (OP9; `entitlement.md` A3, rule 7). Adding it requires the `auth.md` §5.2 grid and `entitlement.md` amendments listed in §14 (not made in this CP0 pass).

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Seller asks CMO to publish/update a live listing | Refused; explained as recommend-only (§0) |
| E2 | Request outside C3 ("other marketplace task", bulk rewrite, ad copy, images) | Declined as out of V1 scope (§3); CEO says so |
| E3 | GST question reaches CMO | Not a CMO capability; CEO handles it by Route A (CFO) or Route B (shared lookup) per permissions (§6.9); neither permitted → wall explained |
| E4 | CI insight missing/stale/`DEGRADED`/`UNAVAILABLE`, or no `agent.ci` | Independent generation proceeds with a one-line note; never blocks (C11) |
| E5 | `format_constraint` missing/stale for a marketplace | Generation blocked **for that marketplace only**, 0 units, seller told why; never silently defaulted to §6.3 |
| E6 | Cap exhausted before the request starts | Entitlement denial (not permission) |
| E6b | Remaining units < request's unit count | Whole request denied up-front, remaining count shown (§8.4); no partial run |
| E7 | No image / vision `FAILED` or `DEGRADED` | Text-only generation only on explicit seller confirmation; image-derived detail absent, never fabricated |
| E8 | Seller selects an option id that is not in this tenant / not in this set | `404` / rejected; CEO never picks an option on the seller's behalf |
| E9 | Seller wants copy but has neither an approval nor a title | CEO asks for a title or offers a title set first (OP1) |
| E10 | Seller edits the approved title to violate the constraint | Rejected deterministically with the limit shown; no unit |
| E11 | Hashtags requested for a marketplace | Produced as separate marketing suggestions; no claim of marketplace support (§6.6) |
| E12 | Trend request with no confirmed niche terms | Superseded by E19: CEO offers catalog-derived suggestions or asks the seller to type a niche; sections 1 and 5 are `UNAVAILABLE`, sections 2–4 may still run |
| E13 | Retrieval sources degrade (one `UNAVAILABLE`) | Sections degrade independently (§6.8.6); the gap is named in the evidence section; never fabricated |
| E14 | A catalog question needs a spec not provided and not observable (e.g. exact weight) | `UNKNOWN` (or labelled `ESTIMATED` range), with a request to the seller; never a point value |
| E15 | Image contains text/branding the seller does not own | Observed text is reported as observed only; CMO makes no ownership/authenticity claim |
| E16 | Constraint row present but `verified_at` older than `format_constraint_max_age_days`, or that config key missing | Production generation blocked for that marketplace with the reason (C13); 0 units |
| E17 | Only a `TEST_FIXTURE` constraint exists | Treated as missing in production; fixtures are test-only |
| E18 | Pack generation cannot reach valid copy without non-eligible claims | `FAILED / NEEDS_FACTS` listing exactly which facts to supply; 0 units; no partial pack |
| E19 | Trend request, no confirmed niche terms | Sections 1 and 5 `UNAVAILABLE` ("confirm a niche"); sections 2–4 may still run; suggestions offered |
| E20 | A suggested catalog term fails the outbound screen (looks like an email/phone/GSTIN/order id) | Never offered, never sent |
| E21 | A required trend-config key is missing | `CONFIG_MISSING` naming the keys; no provider call; 0 units |
| E22 | Provider returns items with no publication date | Item kept as `DATE_UNKNOWN`; never `FRESH`; corroboration capped at `WEAK` |
| E23 | Several articles from one domain, or syndicated copies of one story | One independent source; `mention_count` shown separately |
| E24 | A reported tactic matches the risk pattern set, or no pattern set is configured | Caution group, no suggested action, `UNASSESSED` when no set (fail-safe) |
| E25 | Search budget runs out mid-report | Remaining sections `UNAVAILABLE / BUDGET_EXHAUSTED` in priority order; report `COMPLETE` iff §6.8.6 |
| E26 | Seller asks to "just send my sales report to research it" | Refused: only confirmed niche terms ever leave (C15) |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | `format_constraint` rows are unseeded and unverified; §6.3 is illustrative | Any generation (E5 blocks until verified rows exist) |
| V2 | **Vision quality is unproven.** Local llava 7B is measured unreliable on CI's task (CI Q18). No `VisionProvider` implementation, provider choice, or CMO vision eval exists | Image-informed generation |
| V3 | Seller-image object store: mechanism defined (§5) but no implementation, size/type limits, or retention policy | Image intake |
| V4 | Shared Market Signal Retrieval service does not exist; PI's `sources/` is not yet shared; Tavily/YouTube keys and quotas are PI-sized | `cmo.market_trends` |
| V5 | No marketplace category taxonomy source (Q5) | Authoritative category/vertical answers |
| V6 | No hashtag-support verification for any marketplace | Hashtags inside listing fields |
| V7 | Narration/claim-safety evals (§7) not yet written | Shipping any CMO narration surface |
| V8 | **No trend-config key is decided or seeded** (§6.8.5) | Any trend report (`CONFIG_MISSING`) |
| V9 | **Provider capabilities unverified** (§6.8.8); P7-0 report not written | Section 2 (news/recency), date handling, independence key for video |
| V10 | **Tactic risk pattern set does not exist** (Q17) | Safe fallback applies (`UNASSESSED`, no actions) but section 3 is low-value until it exists |
| V11 | **No verified `format_constraint` rows (including each marketplace's `count_rule`); `format_constraint_max_age_days` undecided** (H1, Q21) | All production generation |
| V12 | **Legal/ToS review of search-provider use for trend research** has not happened (analogous to readiness 3.1) | Launch of `cmo.market_trends` |
| V13 | Catalog-title read function does not exist; whether titles are populated for all three marketplaces is unverified | Catalog-seeded suggestions |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | No code path in this agent writes to any marketplace. |
| AC2 | Every generation records `input_mode`; `ci_inputs_snapshot` is set only when CI attributes were actually used, and a missing CI input never fails or blocks a generation. |
| AC3 | No CMO output contains a GST rate or tax classification; GST questions are never answered by CMO and never call the GST Lookup (C4). |
| AC4 | CMO never calls CI, CFO, PI, CEO or any other agent. Trend retrieval goes only through the shared Market Signal Retrieval service. |
| AC5 | Format constraints are fetched from `format_constraint` at generation time via `format_constraint_ref`; never hardcoded and never read from §6.3. |
| AC6 | Requests outside C3 are declined, not improvised. |
| AC7 | No CMO row contains raw image bytes; images are referenced only via `seller_image_asset` / `image_asset_id`. |
| AC8 | Every `cmo_generation` row consumes exactly 1 unit and only when `COMPLETE`. A five-option title set for one marketplace is one row; a multi-marketplace request writes one row per marketplace; no artefact is double-counted. |
| AC9 | A `TITLE_SET` contains exactly `title_option_count` options **or** is returned short and labelled; every option's `char_count` and constraint check is computed in code, not reported by the LLM. |
| AC10 | `LISTING_COPY`/`DESCRIPTION`/`BULLETS`/`KEYWORDS`/`BACKEND_TERMS` rows carry `grounding_approval_id` or `grounding_basis = SELLER_SUPPLIED_TITLE`; none is generated without one. A `LISTING_COPY` row is one artefact and one unit, `COMPLETE` only if description, bullets and keywords all validate against the marketplace constraint. |
| AC11 | A `cmo_title_approval` row exists for every approved title, with `approved_by`/`approved_at`; no approval is created by CEO or CMO on inference. |
| AC12 | Every catalog attribute carries a basis; no `ESTIMATED` or `UNKNOWN` attribute is asserted as fact in generated copy; weight/dimensions are never `IMAGE_OBSERVED`. |
| AC13 | Hashtags are never placed in a listing artefact unless `hashtags_supported = true` on a verified row; in V1 they appear only as a labelled separate artefact. |
| AC14 | Every trend finding carries ≥1 cited source with dates per §6.8.4; `demand_evidence` is `UNOBSERVED` unless a real sales-demand source exists; the evidence-and-limitations section is never empty. (Extended by AC27–AC33.) |
| AC15 | A repeated `request_key` returns the existing artefact and consumes no second unit. |
| AC16 | A multi-marketplace request is entitlement-checked for its full unit count before any generation starts; insufficient remainder denies the whole request. |
| AC17 | `cmo.market_trends` is denied `403` without `research.market_trends` even when `agent.cmo` is present; and it meters the CMO unit and the shared-service unit independently. |
| AC18 | No price or money value is written into generated copy; `TARGET_PRICE` is stored as integer paise and never computed on. |
| AC20 | While no `vision_eval_run` has `passed = true` for the analysis's `(provider, model, schema_version)`, every image-derived attribute is `UNVERIFIED_HINT`: never used as a claim in any output, never labelled `IMAGE_OBSERVED`, never passed to GST/CI/trend context. |
| AC21 | CEO's Route-B GST call satisfies G1–G7: `403` without `service.gst_lookup`, metered on the shared GST meter only, result `PROVISIONAL`, never convertible to a `gst_rate_override` without `agent.cfo` + `financials.adjust`. |
| AC22 | CI attributes are attached only when `agent.ci` **and** `resolve_ci_entitlement` both pass; failing either falls back to independent mode without error. |
| AC23 | A `LISTING_COPY` pack for a marketplace is generated from that marketplace's approved title and its own VERIFIED constraint row, only from claim-eligible facts, and never from another marketplace's output. |
| AC24 | Production generation is blocked (0 units) when the marketplace has no `VERIFIED` row, the newest row is older than `format_constraint_max_age_days`, or that config key is missing; `TEST_FIXTURE` rows are never read by the production path. |
| AC25 | A pack is `COMPLETE` only if description, bullets and keywords all pass deterministic validation; otherwise `FAILED` (0 units) with a plain reason, and no partial pack is delivered. |
| AC26 | Standalone `DESCRIPTION`/`BULLETS`/`KEYWORDS`/`BACKEND_TERMS`/`HASHTAGS` artefacts follow §8.1.1 exactly (1 unit each, no dedupe, pack row immutable, backend terms Amazon-only). |
| AC27 | A trend report renders all seven sections; every substantive finding has ≥1 cited source with publication (or `DATE_UNKNOWN`) and retrieval dates; the interpretation section is separate, labelled and traceable to finding ids. |
| AC28 | Independence, recency, `is_stale` and corroboration are computed deterministically from configuration; items sharing an independence key count once; the LLM never assigns them. |
| AC29 | Every reported tactic is `REPORTED_NOT_VERIFIED`, carries the policy-check line, and has `policy_risk`; any tactic with risk ≠ `NONE_IDENTIFIED` has no suggested action; no output recommends rule-breaking. |
| AC30 | No unconfirmed niche term, raw report, customer datum or financial figure is sent to any provider; the exact `outbound_queries` are shown before sending and persisted. |
| AC31 | A missing required configuration key yields `CONFIG_MISSING` (named keys), no provider call and 0 units; no code default substitutes for it. |
| AC32 | Sections degrade independently; a report is `COMPLETE` iff ≥1 section has ≥1 cited finding; the evidence section names every degraded section and its reason; nothing is fabricated to fill a gap. |
| AC33 | News and tactic items restate no numeric claim in V1; fee-related items direct the seller to Brain 1 / CFO for margin impact. |
| AC34 | Catalog-seeded suggestions use only distinct `item_title` strings, require `agent.cmo` + `catalog.view`, are bounded by `catalog_titles_read_cap`, pass the outbound screen, and are shown for confirmation. |
| AC35 | Provider-capability gaps found in P7-0 are recorded and surfaced as unmet requirements in reports; no capability is emulated silently. |
| AC36 | No constraint-bound artefact is generated for a marketplace whose winning `format_constraint` row has no verified `count_rule`; the rule used is recorded in each option's `constraint_check`; the code's UTF-16 count is never presented as a marketplace rule. |
| AC37 | Neutral wording about price ("fair price") passes the content scan; price figures and unsupported price, discount and savings claims are blocked (§6.4.1 item 4). |
| AC38 | Phone-number detection blocks real phone shapes and does not block years, dates, model numbers, HSN/PIN codes or barcodes; outbound niche terms additionally refuse 8+ digit runs after discounting years (§6.4.1 item 3). |
| AC39 | `cmo.confirm_image_hint` writes one `SELLER_PROVIDED` `seller_fact`, costs 0 units, changes no analysis row, and leaves the hint `UNVERIFIED_HINT` and ineligible until the vision gate passes. |
| AC40 | Duplicate detection is exact-after-normalisation only; no similarity threshold exists. |
| AC19 | All CMO tables are `FORCE ROW LEVEL SECURITY`-scoped; cross-tenant ids return `404`; no endpoint accepts a client `tenant_id`. |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Title request, no CI context | `INDEPENDENT`; `ci_inputs_snapshot` null (AC2) |
| T2 | Same request after CI insights exist and seller has `agent.ci` | `CEO_BROKERED_CI`; snapshot stored; gap themes only asserted if claim-eligible (AC2, §6.7) |
| T2b | CI insight `UNAVAILABLE` / seller lacks `agent.ci` | Independent generation succeeds with a note (E4) |
| T3 | Seller asks CMO to update the live Amazon listing | Refused (AC1, E1) |
| T4 | Seller with `agent.cfo` asks "what GST applies to this product?" | CEO delegates to CFO (Route A); no CMO run, no `cmo_generation` row; result carries source, date, L5 disclaimer, no "verified" (C4, AC3) |
| T4b | Same question, member has `service.gst_lookup` but not `agent.cfo` | Route B: CEO calls the shared lookup; `PROVISIONAL` result; no CFO/CMO unit consumed; accepting it into a calculation is refused without `agent.cfo` + `financials.adjust` (AC21, G1–G7) |
| T4c | Member lacks `service.gst_lookup` | `403`, wall explained, no model-knowledge answer (G1) |
| T19 | Image attribute from an unevaluated provider | Stored `UNVERIFIED_HINT`; absent from titles/copy/catalog claims and from GST input; seller prompted to confirm (AC20) |
| T20 | Seller confirms a hinted attribute | Stored as `seller_fact`; becomes `SELLER_PROVIDED` and claim-eligible (§6.2.1) |
| T21 | CI attach with `agent.ci` but failing CI entitlement | Independent mode with note; no error (AC22) |
| T22 | Approved Amazon, Flipkart and Meesho titles, then three packs | Three separate `LISTING_COPY` rows, each shaped by its own constraint row; no text shared across packs; 3 units (AC23) |
| T23 | Generate a pack with no VERIFIED constraint row (only a `TEST_FIXTURE`) | Blocked in production path, 0 units (AC24, E17) |
| T24 | Newest constraint older than the max-age config; and the config key absent | Blocked in both cases with the specific reason (AC24, E16) |
| T25 | LLM returns bullets over the limit, a 6th bullet, a price, a GST rate | Retried then `FAILED`/0 units, or repaired and revalidated; none delivered invalid (AC25) |
| T26 | Sparse facts | `FAILED / NEEDS_FACTS` listing missing facts; no invented content (E18) |
| T27 | Standalone bullets requested after a pack | New artefact, 1 unit; pack unchanged (AC26) |
| T28 | Backend terms requested for Flipkart | Refused (Amazon-only) (AC26) |
| T29 | Trend report with all providers up | Seven sections; each finding dated, sourced; interpretation labelled with finding ids (AC27) |
| T30 | Ten articles from one domain + a syndicated copy on two other domains | Independence counts per rules; corroboration not raised by repeats (AC28, E23) |
| T31 | Items with no publication date | `DATE_UNKNOWN`, never `FRESH`, corroboration ≤ `WEAK` (AC28, E22) |
| T32 | Tactic matching a risk pattern; tactic with no pattern set configured | Caution group, no action, `UNASSESSED` fail-safe (AC29, E24) |
| T33 | News item containing a fee percentage | Percentage not restated; source linked; pointer to CFO/Brain 1 (AC33) |
| T34 | Catalog with 40 item titles incl. one containing a phone number | Suggestions derived from titles only; the screened term is never offered; seller confirms two; only those two appear in `outbound_queries` (AC30, AC34, E20) |
| T35 | Trend request with no confirmed terms | Sections 1, 5 `UNAVAILABLE`; 2–4 run (E19) |
| T36 | Required trend-config key missing | `CONFIG_MISSING`, no provider call, 0 units (AC31, E21) |
| T37 | Tavily down, YouTube up; and budget exhausted mid-run | Sections degrade independently; report `COMPLETE` iff ≥1 cited finding; evidence names gaps (AC32, E25) |
| T38 | Member without `catalog.view` requests suggestions | `403` (AC34) |
| T39 | Seller tries to send their sales report for research | Refused (E26, AC30) |
| T40 | Interpretation item citing a non-existent finding id | Rejected by the checker (AC27) |
| T5 | "Rewrite my whole catalog" / "other task" | Declined (E2, AC6) |
| T6 | Free tier at cap | Entitlement denial, not permission denial (E6) |
| T7 | Member without `agent.cmo` requests generation | `403` |
| T8 | Image + Amazon+Flipkart+Meesho title request | 3 `TITLE_SET` rows, 5 options each, 3 units; each option within its marketplace constraint (AC8, AC9). Full workflow for all three marketplaces = 6 units (§8.2) |
| T8b | Same request with 2 units remaining | Whole request denied up-front, remaining shown, nothing generated (AC16, E6b) |
| T8c | One marketplace's constraint row missing | Other two delivered (2 units); third reported blocked, 0 units (E5, §8.3) |
| T9 | Seller approves option 3 for Flipkart, then requests the copy pack | Approval row persisted; one `LISTING_COPY` row (description+bullets+keywords) references it; 1 unit (AC10, AC11) |
| T9d | Copy pack where bullets cannot be made valid | Artefact `FAILED`, 0 units, reason stated, nothing partial billed (AC10, §8.3) |
| T9b | Seller requests copy with no approval and no title | CEO asks for one (E9, AC10) |
| T9c | Seller edits approved title past the limit | Rejected deterministically; no unit (E10) |
| T10 | Regeneration of a title set | New row, new unit; prior set and approval intact (§8.3) |
| T10b | Double-submitted identical request | One artefact, one unit (AC15) |
| T11 | Inspect any CMO row for image data | No bytes; only asset references (AC7) |
| T12 | `format_constraint` stale/missing | Blocked for that marketplace; not sourced from §6.3 (E5, AC5) |
| T13 | "What colour and weight is this?" (colour visible, weight not) | Colour `IMAGE_OBSERVED`; weight `UNKNOWN` or labelled `ESTIMATED` range — never a point value (AC12, E14) |
| T13b | Seller states weight in chat, then asks for bullets | Weight is `SELLER_PROVIDED` and may appear in copy (C9) |
| T14 | Hashtags requested | Separate artefact labelled as marketing suggestions; none inside listing fields (AC13) |
| T15 | "What's trending right now?" with confirmed niche terms | Seven-section report (see T29), dated links, `demand_evidence = UNOBSERVED`, limitations listed (AC14, AC27) |
| T15b | Same, no confirmed niche | See T35 / E19: sections 1 and 5 `UNAVAILABLE`, 2–4 run |
| T15c | `cmo.market_trends` with `agent.cmo` but no `research.market_trends` | `403` (AC17) |
| T15d | A trend finding with no citable source | Dropped (AC14) |
| T15e | Eval: model output says "this is selling like crazy" | Fails narration-safety check (§7, §6.8.7 rule 1) |
| T16 | Vision output reports a price/weight numeral on a photo | Discarded at parse; never reaches copy (§6.2) |
| T17 | Seller supplies `target_price_paise` | Stored as integer paise; absent from all generated text (AC18) |
| T18 | Cross-tenant image/asset/option id | `404` (AC19) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | **Cap and retry values:** free-tier count (provisional 10/month), paid uplift, the internal-retry bound, `title_option_count` seed (policy says 5; the config row must be seeded), and the freshness window for trend sources. None invented here. | Entitlement spec; config seeding |
| Q2 | ~~Shared-service extraction~~ | **Approved with a gate, round 2 — see R9.** |
| Q3 | **Demand evidence source.** No sales-volume or keyword-demand source exists (Google Ads access pending brand verification; Google Trends dropped from PI, not adopted for CMO V1). Is a demand source wanted, and which (pytrends vs paid vs keyword-demand client revival)? | Whether `demand_evidence` can ever be non-`UNOBSERVED` (readiness 2.11) |
| Q4 | **`VisionProvider` choice, eval bar values and cost.** The *gate* is decided (§6.2.1, R13). Still open: which provider/model to evaluate, the pass-bar numbers (a human decision recorded in `bar_ref`), whether image analysis becomes a separately metered cost, and whether sending the seller's own product photo to a hosted provider is acceptable (OP11 permits "external"). | Image trust; cost model; DPDP |
| Q5 | **Marketplace category taxonomy source.** Where do authoritative category/vertical/required-attribute data come from (seller upload, curated KB, none)? Until answered V1 returns `ESTIMATED` suggestions only. (Related: CI Q8.) | Catalog-answer accuracy |
| Q6 | **Image retention and deletion** (DPDP, readiness 2.21): `retention_until` default, deletion on request, purge of derived analyses. | Privacy; storage |
| Q7 | **Single vs multiple images per request.** V1 proposes one; multi-angle photos would improve analysis but multiply cost and parse risk. Also upload size/type limits (config, unset). | Intake |
| Q8 | ~~CI read-through authorisation~~ | **Resolved, round 2 — both `agent.ci` and the CI entitlement check (R12).** |
| Q9 | ~~Trend freshness window~~ | **Now configuration (`fresh_window_days`, `recent_window_days`, `news_window_days`, §6.8.5); values are Q15.** Retrieval cache TTL: Q20. |
| Q10 | **Mid-request exhaustion:** copy pack = 1 unit is decided (R10). Still to confirm: the all-or-nothing up-front check (§8.4) as the resolution of old Q5/E6b — retained as the default unless you object. | Entitlement spec |
| Q11 | ~~GST access for CMO-only sellers~~ | **Resolved, round 2 — Route B (R11), subject to G1–G7.** Build note: neither a `cfo.gst_lookup` CEO dispatch nor a CEO shared-lookup entry point exists in `agents/ceo_hub.py` today; both must be built. |
| Q12 | **Workflow state across turns.** Approved option ids and image analysis live in tables referenced from `agent_run.output_refs`, not in LLM context — confirm that is sufficient for the investigation summary (`ceo-agent-orchestration.md` D2), and whether the orchestration spec needs its own audit entry for the approval turn (old Q4). | Orchestration spec |
| Q13 | **Hashtag unit:** 1 unit per hashtag set as written, or free as an add-on to a copy pack? | Entitlement |
| Q14 | **V2 identity:** whether full-CMO (posters, captions, catalog automation) shares this agent's identity (old Q2). | Future scope |
| Q15 | **Trend configuration values:** every key in §6.8.5 (budgets, windows, thresholds, caps). Not invented. | V8 |
| Q16 | **Outcomes of the P7-0 provider capability probe** may force changes (e.g. no news mode, no dates, no channel id). | §6.8.8 |
| Q17 | **Who curates the tactic risk pattern set** and its initial contents; how often it is reviewed. | V10 |
| Q18 | **RESOLVED 2026-10-04:** the catalog-title read requires the dedicated key `catalog.view` (auth.md §5.2), not `files.view` (which no route enforced). Still open: whether `item_title` is populated for Meesho (`marketplace_item_id` is "none observed"). Original question: **Permission for the catalog-title read:** is `files.view` the right key, or does the canonical catalog need its own? Also whether `item_title` is populated for Meesho (`marketplace_item_id` is "none observed" there). | `auth.md` grid; V13 |
| Q19 | **Is a `COMPLETE` report with degraded sections one full unit?** (Proposed: yes, and the seller is told which sections are missing.) | Entitlement |
| Q20 | **Refresh/cache semantics for trend reports** — a regeneration within the retrieval cache TTL reuses fetched items but is still a new artefact and unit; is that acceptable? | Cost/entitlement |
| Q21 | **`format_constraint_max_age_days` value and the operational process** that verifies and refreshes marketplace rules (who, how often, from which official pages). | V11 |
| Q22 | **Numeric restatement in news/tactics:** V1 off. Revisit after launch evidence? | §6.8.7 rule 5 |
| Q23 | **Language/region:** English + India only in V1; Hinglish/regional-language support is not claimed. | Quality |
| Q24 | **Standalone-after-pack pricing:** a standalone component after a pack is a new unit with no dedupe — acceptable? | Entitlement |
| Q25 | **Failed or degraded trend reports and the shared `research.market_trends` meter:** provider quota is spent even on a failed report; should the shared meter count it? | Entitlement |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Backend search-term metering | `cmo.generate_backend_terms` is its own artefact, 1 unit, never bundled (§8.1). |
| R2 | Per-artefact vs per-request entitlement | One row per artefact delivered, 1 unit each, on either path; conversational/direct distinction in `auth.md` §5.2 untouched. Now extended: a five-title set = 1 artefact (§8.2). |
| R3 | ~~`service.gst_lookup` semantics for CMO~~ | **Superseded 2026-10-03.** CMO has no GST path; CEO routes to CFO (C4, §6.9). The CMO-side two-key pattern, `cmo.gst_answer`, old AC9/T9 are removed. |
| R4 | Q11 — recommend-only | Resolved, no exception (§0). |
| R5 | Q12 — "other simple marketplace task" | Removed from V1 (§3). |
| R6 | Q75 — generation trigger | Both independent and CI-informed; CI optional and non-blocking (§2, §6.7). |
| R7 | Old Q3/V3 — seller-image asset store had no owning spec | Owned here (§5 `seller_image_asset`); implementation, limits and retention remain V3/Q6/Q7. |
| R8 | Hashtag support | None established → separate optional artefact (§6.6). |
| R9 | Shared-service extraction (was Q2) | **Approved 2026-10-03 with a gate:** no PI code is touched until a written extraction plan is approved *and* regression tests pinning PI's current behaviour exist and pass (build plan phase P5). |
| R10 | Post-approval copy unit count (was part of Q10) | **Decided:** the copy pack (description + bullets + keywords) is one `LISTING_COPY` artefact = 1 unit per marketplace. Worked total: 6 units for the full three-marketplace workflow. |
| R11 | GST for CMO-only sellers (was Q11) | **Decided:** CEO may use the shared GST lookup (Route B) if G1–G7 hold; otherwise the route is not shipped. Route A (CFO) for members with `agent.cfo`. |
| R12 | CI read-through authorisation (was Q8) | **Decided:** `agent.ci` **and** CI entitlement check, evaluated not consumed; failure → independent mode. |
| R13 | Vision trust | **Decided:** image-derived facts are `UNVERIFIED_HINT` until a provider passes a recorded evaluation (§6.2.1); the independent text workflow is never blocked by it. |
| R14 | `auth.md` / `entitlement.md` amendments | **Applied 2026-10-03:** `research.market_trends` in the permission grid and shared-service sentence; CMO event kinds and the shared meter in `entitlement.md`. No cap values seeded. |
| R15 | Near-duplicate detection (P2 review) | **Decided: none.** Exact normalised duplicates only (§6.4.1.1, AC40). |
| R16 | UTF-16 counting (P2 review) | **Decided:** an implementation fallback, not a marketplace rule; production generation is blocked until each marketplace's `count_rule` is verified (§6.4.1.2, AC36). |
| R17 | Phone-number heuristic (P2 review) | **Refined:** phone shapes, not "8 digits"; years, dates, model numbers, HSN/PIN and barcodes pass (§6.4.1.3, AC38). |
| R18 | The word "price" (P2 review) | **Refined:** neutral wording allowed; figures and unsupported price/discount/savings claims blocked (§6.4.1.4, AC37). |
| R19 | Request-key length (P2 review) | **Documented** as an internal implementation limit (§6.4.1.5). |
| R20 | Niche stop words (P2 review) | **Configurable** (extend/exclude) over English, listing-filler, Hindi and Romanised-Hindi sets; tested on mixed titles (§6.4.1.6). |
| R21 | Optional-config fail-safes (P2 review) | **Preserved** (§6.4.1.7). |
| R22 | Image-hint confirmation (P2 review) | **Clarified:** records the seller's assertion only; zero units; trusts nothing (§6.2.1, AC39). |

---

## 14. CP0 change log (2026-10-03)

**Supersedes:** old C4 / `cmo.gst_answer` / `service.gst_lookup` for CMO / AC9 / T9 / R3 (GST now CEO→CFO); old AC8 "no trigger produces more than one artefact type per call" (now: one row per artefact; two enumerated multi-row actions); old §2 "ci_finding_ref" (now `ci_inputs_snapshot`, because CI emits no persisted `LISTING_GAP` finding); old `image_asset_ref` forward reference (now `seller_image_asset`).

**Added:** image intake + `VisionProvider` + `product_image_analysis`; 5-option title sets; persisted approval; grounded copy; attribute-basis labelling; hashtags-as-separate-artefact; trend reports + shared Market Signal Retrieval service; explicit retry/regeneration/failure/cap semantics.

**Round 2 (same day):** GST Route B with safety conditions G1–G7; copy pack = 1 unit (`LISTING_COPY`); extraction approved behind a plan + regression-test gate; vision trust gate; CI read-through checks permission + entitlement; `auth.md` and `entitlement.md` amended (done).

**Round 3 (same day):** per-marketplace copy-pack workflow made explicit with constraint blocking and `TEST_FIXTURE` isolation (§6.4, C13); full billing table (§8.1.1); trend feature expanded to seven sections with computed evidence, deterministic independence/recency/corroboration, tactic policy-risk handling, no-numeric-restatement rule (§6.8, C14); catalog-seeded niche with confirmation and an egress rule (§6.8.3, C15); configuration-only budgets/windows/thresholds with `CONFIG_MISSING` fail-closed behaviour and source-degradation rules (§6.8.5–6.8.6, C16); provider capabilities listed as unverified pending probe P7-0 (§6.8.8); new ACs 23–35, tests T22–T40, edge cases E16–E26, blockers V8–V13, questions Q15–Q25. Supersedes round 2's single "trend finding schema" and its three-scope model.

**P6 (2026-10-05):** image intake, `VisionProvider`, immutable analyses, the trust gate with read-time revocation, and the operator evaluation CLI recorded in §6.2.2; `image_analysis_id` correction in §6.1; `cmo.upload_image` / `cmo.analyze_image` added to §8.1.

**P5 (2026-10-04):** serialised quota reservations, HTTP behaviour and required model/TTL configuration recorded in §8.4; `entitlement.md` E2/V1/Q5 amended for CMO.

**P3 review (same day):** generator decisions recorded in §6.4.2 (short title sets, fact selection, `NEEDS_FACTS`, failed-row persistence, approval re-validation, parse-safety ceilings, `hashtag_set_size`, Flipkart structured fields, composition-root model/timeout).

**P2 review (same day):** exact-duplicates-only decision; verified per-marketplace `count_rule` gate (column added to `format_constraint`, resolver blocks without it); phone/identifier heuristic redesigned; "price" rule split into figures versus unsupported claims; request-key limit documented as internal; configurable English/Hindi/mixed stop words; fail-safes preserved; image-hint confirmation clarified. See §6.4.1, AC36–AC40, R15–R22.

**P7d (2026-10-04):** catalog-seeded niche flow implemented (§6.8.3 item 7); extraction of the market-signal source layer (P7c) changed no behaviour. 

**Dependent amendments still NOT made (separate spec edits, made in the build phase where each becomes relevant):**
3. `product-intelligence-agent.md` — note that `sources/` becomes a shared package (only if Q2 is answered "extract").
4. `cfo-agent.md` — record that `cfo.gst_lookup` is reachable conversationally via CEO (it is currently direct-path only) and the product-context input from CEO.
5. `competitor-intelligence-agent.md` — note CMO consumes `competitor_listing_insight` via a read-only repository function and that `LISTING_GAP` is not yet emitted.
