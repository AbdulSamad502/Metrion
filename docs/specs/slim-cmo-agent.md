# Metrion — Slim CMO Agent Specification

**Status:** Draft for review
**Prerequisites:** `auth.md` (permissions, execution paths) · `deterministic-engine.md` (GST Applicability Lookup) · `competitor-intelligence-agent.md` (CI boundary) · `data-foundation.md` (provenance)

## 0. Q11 resolved first — recommend-only, no exception

**Slim CMO never writes to a marketplace.** Every output — title, bullets, description, keywords, an answer to a catalog question — is a **proposal the seller copies and pastes themselves.** This is not a CMO-specific choice; it is the system-wide write-back decision (readiness §1, Product shape — Write-back: "None. Recommend-only; every output is a proposal") applied here without exception. CMO holds no marketplace credential, no listing-write scope, and no API integration that could publish on the seller's behalf. This governs every section below and is restated at AC1.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Recommend-only** (§0). No write-back, ever. | readiness §1 — Write-back |
| C2 | **Free, capped agent** — 10 generations/month, provisional config. | readiness §1 — Agent cart, Free-tier caps |
| C3 | **Scope:** SEO title, keywords, bullet points, description generation; catalog-field Q&A; product GST questions. | readiness §1 — CMO scope; OP7 |
| C4 | **GST questions route to the shared GST Applicability Lookup**, never answered from CMO's own knowledge. Requires `service.gst_lookup` **in addition to** `agent.cmo` — identical two-key pattern to `cfo-agent.md` §6.8 `cfo.gst_lookup`: the shared-service key is granted independently of any agent key, and its OP9 cap meters separately from the agent's own entitlement. `agent.cmo` alone never authorises a lookup. | OP7; `deterministic-engine.md` §8.4; `cfo-agent.md` §6.8, §8 rule 3b |
| C5 | **Seller-supplied product images only.** No marketplace image use. | OP8 |
| C6 | **Star topology.** Conversational access needs `agent.ceo` + `agent.cmo`. Registered direct paths need `agent.cmo` alone. CMO never calls another agent. | readiness §1 — Topology, Execution paths |
| C7 | **CMO holds no financial or GST rate data of its own.** Any number in its output comes from Brain 1 or the GST Lookup, cited. | Brain-boundary rule, all specs |

---

## 2. Q75 — generation trigger: both, not either/or

Two independent entry points, not a pipeline that forces one through the other:

1. **Direct request.** A seller asks for a title, bullets or a description with no competitor context at all. CMO generates from the product facts it is given (seller's own text, image, category). This is the common case and must not be gated behind CI.
2. **CEO-brokered, competitor-informed.** CI observes a competitor's listing structure (`competitor-intelligence-agent.md` §6.6 — themes, keyword patterns, differentiation opportunities; never copied text). CEO receives that finding and, only if the seller is discussing listing optimisation, passes the **derived attributes** to CMO as additional input. **CMO never calls CI, and CI never calls CMO** (C6) — CEO is the only path between them, consistent with the star topology and with `competitor-intelligence-agent.md` §6.6's "CEO routes to CMO; CI never calls CMO."

CMO's output schema (§5) records which mode produced a given generation, so a seller-facing answer can honestly say whether competitor observations informed it.

---

## 3. Q12 — "other simple marketplace task" resolved

The planning document's catch-all is **removed, not carried forward.** An undefined scope item cannot be built or reviewed. What survives is the enumerated list in C3: title, keywords, bullets, description, catalog-field Q&A, and GST questions via the shared lookup. Anything else a seller asks for that isn't on this list is **out of scope for V1** and CEO should say so rather than CMO improvising. New catalog capabilities are added to C3 by spec amendment, never inferred at runtime.

---

## 4. Goals and non-goals

**Goals** — generate SEO-oriented listing copy per marketplace format constraints; answer catalog-field and GST questions; incorporate CI-derived competitor attributes when CEO supplies them; cite every claimed fact to its source (seller input, Brain 1, or GST Lookup).

**Non-goals (V1)** — any marketplace write-back (§0) · independent competitor research (CMO never fetches; that is CI's job) · pricing decisions (CFO's job) · product photography or image generation · "other simple marketplace task" (§3) · full CMO capabilities reserved for V2 (poster/caption generation, full catalog automation — planning doc p.5).

---

## 5. Data model

```sql
cmo_generation (
  id uuid pk, tenant_id uuid not null,
  sku text, marketplace text not null,          -- AMAZON | FLIPKART | MEESHO
  output_type text not null,                    -- TITLE | BULLETS | DESCRIPTION | KEYWORDS | CATALOG_ANSWER | GST_ANSWER
  input_mode text not null,                     -- DIRECT | CEO_BROKERED_CI (§2)
  ci_finding_ref uuid,                          -- set only when input_mode = CEO_BROKERED_CI
  seller_input jsonb,                           -- product facts the seller supplied, as text; see seller_fact below
  image_asset_ref uuid,                         -- fk to a seller-image asset store; NOT YET SPECIFIED (see Q3) — NEVER raw image bytes in this row or table regardless
  output_text text not null,
  format_constraint_ref uuid not null,          -- fk to format_constraint.id (§6) — the exact row applied, not just a name
  gst_lookup_ref uuid,                          -- set only for GST_ANSWER; cites the lookup, never a stored rate
  billable_units int not null default 1,        -- ALWAYS 1 in V1 (AC8); column reserved for a future variable-cost artefact type, not currently variable
  generated_by uuid, created_at timestamptz not null
)

seller_fact (                                   -- provenance for what the seller told CMO (fix 6)
  id uuid pk, cmo_generation_id uuid not null,
  fact_type text not null,                      -- CATEGORY | BRAND | ATTRIBUTE | FREE_TEXT
  fact_value text not null,
  provided_at timestamptz not null
  -- no `source` column: every row is seller-asserted, unconditionally (§0's boundary) —
  -- CMO never infers a fact and presents it as given, so there is no second value this could hold
)
```

**No table stores a GST rate, a fee, or a price.** Those are always fetched live from Brain 1 or the Lookup and cited by reference (`gst_lookup_ref`), never cached as CMO's own fact.

**Images are never stored as bytes on this agent's tables (fix 5).** `image_asset_ref` is a forward reference: OP8 establishes the *policy* that sellers may upload product photos, but **no spec in the current set defines the asset-store schema that reference is meant to point at** — it is not defined by OP8 (a policy statement, not a schema), by `data-foundation.md` (`report_file` is scoped to financial reports), or by OP11 (which defines the vision *extraction* pipeline, not storage). CMO's own commitment is unconditional regardless of where that store ends up living: no row in `cmo_generation` or `seller_fact` ever holds inline image bytes. The FK target itself is tracked as an open dependency — see Q3 and V3.

**Every seller-asserted fact used in a generation is provenanced (fix 6).** A `seller_fact` row records what the seller said and when, so a generation whose title or bullets depend on a category or attribute claim can be traced back to that claim rather than presented as CMO's own knowledge. `format_constraint_ref` is likewise a foreign key to the exact `format_constraint` row (§6), not a free-text label — the specific rule version applied is always reconstructable.

---

## 6. Per-marketplace format constraints

Constraints are **configuration, resolved at generation time, never hardcoded** — marketplace listing rules change without notice, same principle as `deterministic-engine.md` F4 on fee rates. **The table below is illustrative documentation only, not a source CMO reads from.** At generation time CMO fetches the live constraint row for the target marketplace from `format_constraint` (below); if that row is stale or absent, generation blocks per E5 rather than falling back to the illustrative values here.

| Marketplace | Title | Bullets | Description | Notes |
|---|---|---|---|---|
| Amazon | ~200 chars, brand-first convention | 5, feature-led | Plain or A+ block | Backend search terms are a separate hidden field with its own length cap, generated by its own metered trigger (`cmo.generate_backend_terms`, §8) — never bundled into the same call as the title |
| Flipkart | Structured: brand + type + attributes | Key features list | Structured spec fields | Category-specific attribute forms constrain content |
| Meesho | Shorter, price-sensitive phrasing | Highlights, fewer than Amazon | Brief | Simpler schema; less structured than the other two |

```sql
format_constraint (                             -- runtime authority; §6 table is illustrative only
  id uuid pk,
  marketplace text not null,
  category text,                                -- null = marketplace-wide default
  title_max_chars int, bullet_count int, description_type text,
  backend_terms_max_bytes int,                  -- Amazon hidden-field cap; null where the marketplace has no such field
  source_url text not null,                     -- OP2(a) marketplace domain the rule was verified against
  verified_at timestamptz not null,
  version int not null,
  unique (marketplace, category, version)
)
```

A generation request declares its target marketplace; CMO fetches the current row from `format_constraint` and cites both `format_constraint_ref` (§5) and that row's `source_url` + `verified_at` on the output, so a seller can see how current the rule is.

---

## 7. AI requirements

| Brain | Role |
|---|---|
| **Brain 1** | Any number in output (price, margin, fee) — CMO never computes one itself. |
| **Brain 3 (LLM)** | All generation: titles, bullets, descriptions, keyword selection, catalog-question answers. This is CMO's primary function and the one place in the system where free-form LLM *creative* output is the product, not a violation — because nothing generated here is a financial or compliance fact. |

**The one hard boundary inside generation:** if the seller asks a GST question, the LLM does not answer from its own training — it triggers `service.gst_lookup` and relays the cited result with the disclaimer required by `deterministic-engine.md` §8.4 L5. Generation and factual lookup are never blended into one uncited answer.

---

## 8. Authorization

Direct execution paths (per `auth.md` §5.2 guardrail — one action, one key, no free-form input beyond the declared fields):

| Trigger | Action | Permission | Entitlement |
|---|---|---|---|
| `cmo.generate_title` | Generate one title | `agent.cmo` | 1 unit (C2) |
| `cmo.generate_bullets` | Generate one bullet set (all bullets for one SKU/marketplace) | `agent.cmo` | 1 unit |
| `cmo.generate_description` | Generate one description | `agent.cmo` | 1 unit |
| `cmo.generate_keywords` | Generate one keyword set, **visible keywords only** | `agent.cmo` | 1 unit |
| `cmo.generate_backend_terms` | Generate Amazon backend search terms (hidden field) | `agent.cmo` | 1 unit (fix 4 — see R1: metered the same as any other artefact, not free and not bundled) |
| `cmo.catalog_answer` | Answer a catalog-field question | `agent.cmo` | 1 unit |
| `cmo.gst_answer` | Answer a product GST question | `agent.cmo` **and** `service.gst_lookup` | 1 CMO unit **+** the OP9 lookup cap, metered independently (identical two-meter pattern to `cfo-agent.md` AC17b) |

**Entitlement counts per artefact, not per request (fix 3).** Each `cmo_generation` row is exactly one billable unit (`billable_units = 1`, §5), and **one row is written per artefact actually produced**, regardless of which path produced it. This is the same accounting rule on both paths — it does not require, and does not create, a third request mode:

- **Direct path:** the member clicked one button (`cmo.generate_title`, say); one row, one unit. Matches `auth.md` §5.2 exactly — one action, one key, the member's own explicit choice.
- **Conversational path:** the member asked CEO an open-ended question ("help me improve this listing"), which stays conversational end to end and requires `agent.ceo` + `agent.cmo` throughout, per `auth.md` §5.2 and R2. If composing CEO's answer causes CMO to produce a title and three bullet variants, that is **four separate generations, each writing its own `cmo_generation` row**, so four units are consumed — the same total a member would have paid clicking four buttons, arrived at through the conversational route rather than a routing shortcut. **No direct-path trigger is invoked on the member's behalf**; the conversational request is answered as one conversation, and entitlement is simply metered on what CMO actually generated, artefact by artefact, exactly as it already is metered on the direct path.

This resolves fix 3 without inventing any mechanism beyond what `auth.md` §5.2 already defines: the conversational/direct distinction is untouched, and "per artefact, not per request" describes the entitlement counter, not a new orchestration behaviour. **How CEO internally decides to produce four artefacts from one seller question is CEO's orchestration and out of scope for this spec** — see Q4.

All paths enter the `auth.md` §7.1 six-step chain; permission and entitlement are evaluated independently (§7.2).

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Seller asks CMO to publish directly | Refused; explained as recommend-only (§0) |
| E2 | Seller asks for "other marketplace task" outside C3 | Declined; CEO states it is out of V1 scope (§3) |
| E3 | GST question with no product category given | CMO requests it before calling the Lookup; never guesses |
| E4 | CI finding available but seller didn't ask about competitors | Not injected uninvited; CEO decides relevance |
| E5 | Marketplace format constraint unavailable | Generation blocked for that marketplace; seller told why, not silently defaulted |
| E6 | Free-tier count exhausted before the request starts | Denied by entitlement, not permission (`auth.md` §7.2) |
| E6b | Entitlement exhausted **mid-composition** — e.g. 2 units remain but a conversational answer would produce 4 artefacts | **Pending.** Partial answer, full refusal, or another behaviour is undecided — see Q5. Not asserted here, matching `competitor-intelligence-agent.md` E9's treatment of the equivalent gap |
| E7 | Seller supplies no image and none exists | Text-only generation proceeds; image-based detail simply absent, not fabricated |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | Per-marketplace format constraints (§6) are illustrative, unverified against current seller policy | Constraint accuracy at launch |
| V2 | Vision pipeline for seller images (OP11) — external extraction to structured schema, not yet built | Image-informed generation |
| V3 | **No spec defines the asset-store schema `image_asset_ref` points at** — not OP8 (policy, not schema), not `data-foundation.md` (`report_file` is scoped to financial reports), not OP11 (extraction pipeline, not storage) | The FK in `cmo_generation`/`seller_fact` has no defined target; see Q3 |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | No code path in this agent writes to any marketplace. |
| AC2 | Every generation cites `input_mode`; `ci_finding_ref` is set only when CI-derived attributes were actually used. |
| AC3 | No GST figure is answered without a `gst_lookup_ref`; none is answered from model knowledge alone. |
| AC4 | CMO never calls CI or any other agent directly. |
| AC5 | Format constraints are fetched from `format_constraint` at generation time via `format_constraint_ref`, never hardcoded in a prompt or in code, and never read from the illustrative §6 table. |
| AC6 | Requests outside the C3 enumeration are declined, not improvised. |
| AC7 | No `cmo_generation` or `seller_fact` row contains raw image bytes; images are referenced only via `image_asset_ref`. |
| AC8 | Every `cmo_generation` row consumes exactly `billable_units = 1`; no trigger produces more than one artefact type per call. |
| AC9 | `cmo.gst_answer` is denied with `403` if `service.gst_lookup` is absent, even when `agent.cmo` is present — identical behaviour to `cfo-agent.md` T31. |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Seller asks for a title with no competitor context | Direct-mode generation; `ci_finding_ref` null (AC2) |
| T2 | Seller discusses listing optimisation after a CI run | CEO-brokered mode; finding cited |
| T3 | Seller asks CMO to update the live Amazon listing | Refused (AC1, E1) |
| T4 | Seller asks a GST rate question | Lookup triggered; disclaimer attached (AC3) |
| T5 | Seller asks for a bulk catalog rewrite ("other task") | Declined as out of scope (E2) |
| T6 | Free tier at 10/10 generations | Entitlement denial, not permission denial (E6) |
| T7 | Partner without `agent.cmo` requests generation | `403` |
| T8 | Conversational request produces a title and three bullet variants | Request stays conversational (`agent.ceo`+`agent.cmo` throughout, no direct-path trigger invoked); four `cmo_generation` rows written, four units consumed (AC8, R2) |
| T9 | `cmo.gst_answer` with `agent.cmo` but no `service.gst_lookup` | `403` (AC9) |
| T10 | `cmo.generate_backend_terms` invoked | 1 unit consumed, same as any other artefact (fix 4) |
| T11 | Inspect any `cmo_generation`/`seller_fact` row for image data | No raw bytes present, only `image_asset_ref` (AC7) |
| T12 | `format_constraint` row for a marketplace is stale/missing | Generation blocked, not silently sourced from the §6 illustrative table (E5, AC5) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | Exact free-tier count and paid-tier uplift | Provisional; entitlement spec |
| Q2 | Whether V2's full-CMO scope (posters, captions, catalog automation) shares this agent's identity or is a distinct agent | Future scope |
| Q3 | **Seller-image asset store has no owning spec** (V3). Where is it defined — a new spec, folded into `data-foundation.md`, or owned by OP11's vision pipeline? Until answered, `image_asset_ref` is a forward reference with no confirmed target. | 🔴 Blocks image-informed generation end to end |
| Q4 | How CEO internally decides to produce multiple CMO artefacts from one conversational question is CEO's orchestration and is not defined by this spec (§8). Does that decomposition logic live in a CEO/orchestration spec, and does it need its own audit trail distinct from the per-artefact `cmo_generation` rows it produces? | Orchestration spec |
| Q5 | **Mid-composition entitlement exhaustion** (E6b) — if a conversational answer needs 4 artefacts but only 2 units remain, does CMO return a partial answer, refuse the whole request, or something else? Undecided, same class of gap as `competitor-intelligence-agent.md` E9. | Entitlement spec |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | ~~Backend search-term metering~~ (was Q3) | **Resolved.** `cmo.generate_backend_terms` is its own trigger, billed at 1 unit like every other artefact — not free, not bundled with keywords (§8). |
| R2 | Per-artefact vs per-request entitlement | **Resolved, without altering the conversational/direct distinction in `auth.md` §5.2.** One `cmo_generation` row is written per artefact actually produced, on either path, and each row is one unit — never a bundled discount. A multi-artefact conversational answer stays conversational throughout (`agent.ceo` + `agent.cmo`); it is not reframed as CEO invoking direct-path triggers on the member's behalf (§8). How CEO decides to produce several artefacts from one question is out of scope here — see Q4. |
| R3 | `service.gst_lookup` semantics | **Resolved — matches `cfo-agent.md` exactly.** Two independent keys (`agent.cmo` + `service.gst_lookup`), two independent meters (CMO unit + OP9 cap), `403` if either is missing (C4, AC9, T9). |
