# Metrion — Competitor Intelligence Agent (CI) Specification

**Status:** Draft for review
**Prerequisites:** `deterministic-engine.md` (all margin math) · `data-foundation.md` (provenance, confidence) · `auth.md` (permissions) · `whatsapp-integration.md` (WhatsApp identity, invoke/revoke, and investigation-creation mechanics — CI decides none of this itself; §6.9 records only what that spec resolves)

**The arithmetic boundary (B8).** CI may compute **deltas over its own observed facts** — a price change between two snapshots it captured. CI may **never** compute anything financial: no margin, fee, profit, tax or cost figure. All of those originate in Brain 1. CI normalises observations into a provenance-tagged input object, passes it to Brain 1, and reads the result back unchanged. CI holds no financial formula.

---

## 1. Confirmed decisions

| # | Decision |
|---|---|
| C1 | **Marketplaces:** Amazon, Flipkart and Meesho, all three at V1 (readiness §1, Product shape — Marketplaces). |
| C2 | **Acquisition:** seller-supplied URLs, stored. **On-demand only** — user-triggered or WhatsApp-confirmed. No continuous crawling, no bulk discovery, no live monitoring. |
| C3 | **The upload-only rule applies to seller data, not competitor data** (readiness §1, Product shape — Seller data source; `auth.md` T3–T5). Seller financials remain upload-only. Competitor data is fetched on demand from public listings. The two paths never mix. |
| C4 | **Trusted domains (OP2a):** `amazon.in`, `flipkart.com`, `meesho.com` only. URLs outside the allowlist are refused with a clear message. |
| C5 | **Facts, not expression.** No review text stored or reproduced. No marketplace images rehosted. |
| C6 | **Review output is derived insight only:** sentiment split, complaint themes, positive themes, rating distribution, summarised patterns. Source listing link retained. Provenance and timestamp on every insight. |
| C7 | **No live review monitoring.** Review insight is produced only as part of an on-demand run. |
| C8 | **Scrape-failure fallback (OP3):** serve the cached snapshot with a visible age stamp up to **7 days**; beyond that report unavailable. Never fabricate. |
| C9 | **Margin ownership:** Brain 1 is the single source of truth. CI supplies **observed price, visible discounts, and source metadata only** — never fees or rates, which Brain 1 resolves from its own reference store (C18). CI holds no financial formula. CFO interprets. |
| C10 | **Estimated margin range, never competitor margin** (2A.2). Competitor COGS, fee tier and ad spend are unobservable. |
| C11 | **Star topology.** CI is reachable only through CEO. No agent-to-agent edges. CI may call Brain 1 directly as a shared service. |
| C12 | **No supplier responsibility.** PI discovers suppliers; CFO ranks them from seller quotes. |
| C13 | **Entitlement:** CI free is limited (3 saved URLs, 5 runs/month); complete CI is a paid cart item (25 URLs, 100 runs/month). Values are provisional config. |
| C14 | **Raw review text is transient and local-only.** Fetched and held in memory solely to derive insight; **never persisted** to any surface in the canonical list (§6.5) and **never sent to a hosted model provider**. No review-text corpus. No full reviews or long quotations in user-facing output. |
| C15 | **Local-only derivation (B4).** Review and listing derivation runs in-process or through local models (e.g. local Ollama). Raw expression never crosses the process boundary to a third-party provider. Where local processing is unavailable, CI returns a **degraded result from structured metadata** rather than sending raw text out. |
| C16 | **Competitor listing copy is expression, not fact (M5).** Full titles, descriptions, bullets and copied listing text are **never persisted**. Only derived attributes are stored (§6.6). |
| C17 | **Brain 1 owns all financial arithmetic (B1).** CI normalises scraped observations into a structured, provenance-tagged input object and passes it to Brain 1. Where Brain 1 needs a new interface to accept observed competitor inputs, **Brain 1 is extended** — never CI. Output is always an *estimated margin range*, never a competitor margin. |
| C18 | **Fee references are backend-managed configuration (B9).** Versioned, effective-dated, source-attributed reference data consumed by Brain 1. CI never holds rates. |
| C19 | **Retention (B6):** competitor snapshots are **not** retained indefinitely. Configurable policy, initially **90 days** (§6.8). Retention must never imply continuous monitoring — CI is on-demand only. |
| C20 | **Direct CI execution (B7).** A dashboard/button CI run is a **direct CI execution path**, not a CEO conversational route, and does not consume a CEO call. It enforces the full check set in §6.4. |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Price-change detection basis | **Snapshot-to-snapshot delta**, not continuous monitoring | Without live monitoring, change can only be observed between two on-demand runs. Any other framing over-promises. |
| D2 | Default threshold | **±5% on effective selling price**, tenant-configurable | Small enough to catch real repricing, large enough to ignore rounding and minor promo noise. |
| D3 | Secondary threshold | **Availability transition** (in stock ⇄ out of stock) fires regardless of price | A competitor going out of stock is often more actionable than a price move. |
| D4 | Snapshot retention | **Configurable, initially 90 days** (C19, §6.8). Not indefinite. | Deltas need history, but retention is bounded pending DPDP review. Revisit after legal. |
| D5 | Fee references | Held in a **versioned backend-managed reference store** consumed by Brain 1 (C18, `deterministic-engine.md` §5.14). CI passes only marketplace and category, never rates. | Satisfies F4 and 2B.4 — coefficients are configuration, never constants, and never live in an agent. |
| D6 | Stale-snapshot policy | **OP3 governs:** cached snapshots are served with a visible age stamp **up to 7 days**. **Beyond 7 days the result is reported unavailable** — not displayed with a stamp. Stale data never fires an alert. | OP3 is a locked policy: *report unavailable rather than mislead.* |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | Public listing pages expose price, MRP, rating, rating count and availability without authentication | **High** — the agent has no data source if not |
| A2 | A listing URL remains stable enough to re-fetch across weeks | Medium — URL rot breaks the snapshot series |
| A3 | Meesho listings expose a comparable field set to Amazon and Flipkart | Medium — Meesho may yield a thinner snapshot |
| A4 | Fee references in the Brain 1 store (`deterministic-engine.md` §5.14) are close enough for a *range*, not a point estimate | Medium — range widens and the gap is named; never presented as precise |
| A5 | One URL maps to one sellable variant | Medium — multi-variant pages need a variant key |

---

## 4. Goals and non-goals

**Goals** — store seller-supplied competitor URLs; capture on-demand snapshots across all three marketplaces; detect threshold-breaching price and availability changes between snapshots; produce derived review insight; supply observed inputs to Brain 1 for an estimated margin band; surface findings through CEO and, where enabled, WhatsApp.

**Non-goals (V1)** — continuous or scheduled monitoring · competitor discovery (CI never finds competitors, the seller supplies them) · persisting review text, listing copy or images · performing any financial calculation · holding fee rates · indefinite snapshot retention · sending raw expression to a hosted model provider · deciding WhatsApp behaviour · supplier data · automated repricing or any marketplace write · scraping outside the allowlist.

---

## 5. Data model and interfaces

```sql
competitor_url (
  id uuid pk, tenant_id uuid not null,
  marketplace text not null,            -- AMAZON | FLIPKART | MEESHO
  url text not null,
  label text,                           -- seller's own name for this competitor
  linked_sku text,                      -- optional: seller SKU this competes with
  status text not null,                 -- ACTIVE | UNREACHABLE | ARCHIVED
  added_by uuid not null, created_at timestamptz not null,
  unique (tenant_id, url)
)

competitor_snapshot (
  id uuid pk, tenant_id uuid not null,
  competitor_url_id uuid not null,
  ci_capture_run_id uuid not null,
  captured_at timestamptz not null,
  capture_status text not null,         -- OK | BLOCKED | NOT_FOUND | PARSE_FAILED
  -- observed facts only. NO raw listing text (C16) — no title, no description, no bullets.
  seller_name text,                     -- business identity, a fact, not expression
  observed_category text,               -- BL5: as shown on the listing; see Q8 on taxonomy mapping
  category_confidence text,             -- OBSERVED | DERIVED | UNAVAILABLE
  listed_price_paise bigint, mrp_paise bigint,
  visible_discount_paise bigint,
  rating numeric(2,1), rating_count int,
  availability text,                    -- IN_STOCK | OUT_OF_STOCK | UNKNOWN
  variant_key text,                     -- A5
  source_url text not null,             -- always link back, never replace the visit
  confidence text not null              -- §5.1 vocabulary: OBSERVED | DERIVED | UNAVAILABLE
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
  source_url text not null,             -- provenance
  fetched_at timestamptz not null,      -- capture time of the underlying fetch
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

ci_tenant_config (                        -- thresholds and retention only
  tenant_id uuid pk,
  price_threshold_pct numeric(5,2) not null default 5.00,   -- D2
  alert_on_availability_change boolean not null default true, -- D3
  snapshot_retention_days int not null default 90,          -- C19
  updated_by uuid, updated_at timestamptz not null
)
-- No WhatsApp state here. Enablement lives on auth.md `whatsapp_binding.enabled`
-- (owner-controlled, W10); cadence and scheduling belong to whatsapp-integration.md (§6.9).

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
  trigger text not null,                -- DIRECT_UI | CEO_REQUEST | WHATSAPP_CONFIRM
  requested_by uuid not null,
  url_ids uuid[] not null,
  status text not null,                 -- QUEUED | RUNNING | PARTIAL | COMPLETE | FAILED
  started_at timestamptz, finished_at timestamptz
)
```

### 5.1 Confidence vocabulary for observed data (M12)

`data-foundation.md` §7.1 defines confidence in terms of *adapter mapping* provenance, which does not describe a directly observed competitor price. CI therefore uses an explicitly scoped vocabulary, declared here rather than borrowed:

| Level | Meaning for CI |
|---|---|
| `OBSERVED` | Read directly from the listing page at `fetched_at` |
| `DERIVED` | Computed or inferred from observed values (themes, patterns, deltas) |
| `UNAVAILABLE` | Could not be captured; reason recorded |

When a CI value is passed into Brain 1 it **always enters as `DERIVED`**, regardless of whether CI recorded it as `OBSERVED` internally. `OBSERVED` never crosses the boundary. This gives a defined ordering against `data-foundation.md` §7.1 — a CI-sourced figure can never present as `VERIFIED` or `PROVISIONAL` — and the monotonic rule then applies to everything downstream.

### 5.2 Interface to Brain 1 (C17 / B1)

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

---

## 6. Core rules

### 6.1 URL intake
1. Seller submits a URL; CI validates it against the OP2(a) allowlist server-side. Non-allowlisted hosts are refused, naming the reason.
2. Marketplace is derived from the host, never asked.
3. Saved-URL count is checked against entitlement before insert.
4. A URL is stored, never fetched at intake — fetching is always an explicit run.

### 6.2 Capture run
1. Triggered only by a direct UI action, a CEO request, or a WhatsApp confirmation. **Never on a schedule** (C2).
2. All checks in §6.4 pass before queuing.
3. Runs execute as background jobs with tenant context set from the job payload, or fail closed.
4. Each URL yields exactly one `competitor_snapshot`, including on failure — `capture_status` records the outcome so the series has no silent gaps.
5. Rate-limited and bounded; a run never expands beyond the URLs it was given.

### 6.3 Change detection
1. On each new snapshot, compare against the most recent prior `OK` snapshot for the same `competitor_url_id` and `variant_key`.
2. Compute `delta_pct` on effective selling price (listed price less visible discount). **This is a delta over CI's own observed facts, permitted by the arithmetic boundary stated in the front matter — it is not a financial calculation.**
3. `threshold_breached` when `|delta_pct| >= ci_tenant_config.price_threshold_pct` **or** availability transitions (D3).
4. `alert_eligible = false` if either snapshot has `capture_status != OK`, or if either exceeds the OP3 freshness ceiling (§6.8).
5. **No prior snapshot means no event.** A first observation is a baseline, never a change.

### 6.4 Execution paths and enforcement (C20 / B7)

CI has two entry paths. Both enforce the same checks; they differ only in whether a CEO call is consumed.

| Path | Trigger | CEO call consumed |
|---|---|---|
| **Direct CI execution** | `DIRECT_UI` — dashboard or button | **No** |
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

### 6.5 Review text handling — transient, local-only (C14, C15)

**Permitted:** fetch raw review text and hold it in process memory, processed in-process or by a **local** model, solely to derive insight.

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

**Persisted output** is limited to `competitor_review_insight` (§5): sentiment split, positive themes, complaint categories, rating distribution, summarised patterns, review count, source URL, `fetched_at`, `derived_at`, confidence, derivation method and insight state.

**Degraded path.** Where local processing is unavailable or a source cannot be processed transiently, CI returns `insight_state = DEGRADED` (or `UNAVAILABLE`) built from structured metadata already captured — rating, rating count, distribution, availability — with `degraded_reason` recorded. It never persists raw expression, and never sends it to a hosted provider, as a workaround.

**Images** are never rehosted. Per the locked wording (M6): permitted hotlinks or thumbnails where technically and legally appropriate; otherwise source links or placeholders.

**Enforcement is structural.** Raw text lives in one bounded processing scope that emits only derived structure. Because derivation is local (C15), that boundary is also the process boundary — nothing downstream, and no external service, can observe the text.

**Model output boundary (MN8).** Where `derivation_method = LOCAL_MODEL`, the model performs **classification only** — it labels each review with a sentiment class and theme tags. **Deterministic code then aggregates** those labels into `sentiment_split` proportions, theme weights and the rating distribution. The model never emits a proportion, a weight or a count. This keeps the locked rule intact — models classify, code computes — and makes the numbers reproducible from the same labels.

### 6.6 Listing copy handling (C16 / M5)

Competitor listing copy is seller-authored **expression**, governed exactly as review text is.

**Never persisted:** full titles, descriptions, bullet text, or any substantial copied listing expression.

**Persisted derived attributes only** (`competitor_listing_insight`, §5): keyword themes · title structure and length · feature categories · benefit-term patterns · differentiation opportunities · bullet count · image count — plus source URL, `fetched_at`, confidence and provenance.

Derivation is local-only, on the same terms as §6.5. Where the seller wants *generated* copy, CEO routes to CMO. **CI never calls CMO** (C11).

**Ownership boundary with CMO (MN12).** CI derives what a *competitor's* listing does — themes present, structure used, gaps observed. CMO produces what the *seller's* listing should say. `differentiation_opportunities` is an observation about the competitive field, not drafted copy; the moment output becomes text for the seller to publish, it is CMO's and routes through CEO.

### 6.7 Estimated margin range (C17 / B1)

1. CI assembles a `CompetitorObservationSet` (§5.2) from observed facts only.
2. CI calls Brain 1. **CI performs no part of the calculation** and holds no rates — Brain 1 resolves fee references itself (C18).
3. Brain 1 returns a range with its basis, assumptions and engine metadata.
4. CI renders it unchanged, always labelled **"estimated margin range"**, with the snapshot timestamp and the stated assumptions.
5. CI never emits a single-point competitor margin (C10). Where fee data is unavailable, the range widens and the assumption is stated explicitly rather than the figure being suppressed.
6. **Reproducibility is surfaced, not hidden (MN10).** Per `deterministic-engine.md` §5.13, an estimate is reproducible only for a fixed observation set, not across re-captures. Every rendering states the observation it was computed from (`source_url`, `fetched_at`) so a changed figure is explained by a new capture rather than appearing unstable.
7. **The estimate is never written to `metric_result`** (engine §5.13 rule 5). It carries its own provenance contract — an **`estimate_ref`** (`competitor_estimate.id`, engine §9.1) — which is what a consumer cites when displaying it. An estimate never carries an `engine_result_ref`. Re-rendering an old snapshot recomputes at the current `fee_reference_version`, stamped on the output.

### 6.8 Freshness and retention (C19 / B2 / B6)

**Freshness (OP3, locked):**

| Snapshot age | Behaviour |
|---|---|
| ≤ 7 days | Served, with a visible age stamp |
| > 7 days | **Reported unavailable.** Not displayed with a stamp, never used in an alert |

**Retention (C19):** configurable per tenant via `ci_tenant_config.snapshot_retention_days`, **default 90 days**.

- **OP3's 7-day ceiling governs the *current answer* for a URL, not the historical series.** A trend chart may render snapshots older than 7 days, each with its own capture date; what it may not do is present a >7-day-old snapshot as the current state, or alert on one.
- Keep the latest successful snapshots required for comparison and trend display.
- Failed-fetch status metadata is retained only for the limited period needed to explain a gap.
- Minimal provenance is preserved for snapshots referenced by an existing report or investigation, subject to the policy.
- **Retention must never be presented as monitoring.** CI is on-demand; a 90-day history is a record of runs the seller triggered, not a watch.

Revisit after DPDP and legal review (`auth.md` Q9).

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
5. **Allowlist enforcement is server-side.** A client-supplied URL is validated on the server; the UI is not a control.
6. Outbound fetches are rate-limited and identify honestly. `robots.txt` handling is deliberately unresolved — see Q10 — and must be settled by the legal review (V6) rather than by a conditional in this spec.
7. Snapshots store facts; review text, listing copy and images are never persisted (C5, C14, C16).
8. **Raw review and listing text is excluded from every observability surface** and from every hosted provider — logs, exception traces, debug output, APM spans, payload capture, and any external model call — by keeping it inside a bounded, local processing scope that emits only derived structure (§6.5, §6.6).
9. A seller may only ever see their own tenant's competitor URLs and snapshots.

---

## 8. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | URL outside allowlist | Refused at intake, reason named |
| E2 | Listing removed (404) | `capture_status = NOT_FOUND`; URL marked `UNREACHABLE`; no event generated |
| E3 | Fetch blocked | `capture_status = BLOCKED`; prior snapshot served with age stamp **only if ≤ 7 days**; otherwise reported unavailable (§6.8); no alert |
| E4 | Snapshot older than 7 days | **Reported unavailable** per OP3 — not displayed with a stamp; no alert (§6.8) |
| E5 | First-ever snapshot | Baseline only; no `competitor_price_event` |
| E6 | Multi-variant page | Keyed by `variant_key`; deltas compared within a variant only (A5) |
| E7 | Price unchanged, availability flips | Event fires on D3 with `delta_pct = 0` |
| E8 | Competitor raises price above seller's | Still an event; direction recorded; interpretation left to CFO/CEO |
| E9 | Entitlement exhausted mid-run | **Pending** — cap behaviour belongs to the entitlement and WhatsApp specs (readiness 2A.7). Not decided here (M10) |
| E10 | Seller deletes a URL | URL `ARCHIVED`; snapshots retained only within the retention policy (§6.8) |
| E11 | Same URL added twice | Rejected by unique constraint |
| E12 | Marketplace changes page structure | `PARSE_FAILED`; no fabricated values; adapter flagged for revision |
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
| V1 | Real page structure per marketplace — field presence and stability (A1, A3) | Every adapter |
| V2 | Anti-bot behaviour under realistic volume | Feasibility of on-demand fetching at all |
| V3 | Populating the Brain 1 fee reference store per marketplace and category (A4, `deterministic-engine.md` §5.14) | The estimated range's usefulness |
| V4 | Items `whatsapp-integration.md` itself still leaves open (credit/cap treatment, mid-thread cap behaviour, decline-alert channel, post-completion messaging) | The residual items in §6.9, not the whole WhatsApp path |
| V6 | Legal review of on-demand fetching before launch | Launch, not build |
| V7 | Variant-key derivation per marketplace (A5) | Delta correctness on multi-variant listings |
| V8 | Local derivation quality on target hardware (Q7) — sentiment and theme extraction at volume on 4GB VRAM | §6.5, §6.6 |
| V9 | Category capture and taxonomy mapping (BL5, Q8) | The estimated margin range cannot resolve fees without it |

---

## 10. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | CI contains **no financial formula of any kind** — margin, fee, profit, tax or cost. Every such figure traces to a Brain 1 call. Price deltas over CI's own observed facts are permitted and are not financial calculations. |
| AC2 | No competitor margin is ever emitted as a point value — only a labelled range. |
| AC3 | No scheduled or background crawling exists. Every fetch traces to an explicit trigger. |
| AC4 | Non-allowlisted hosts are refused server-side. |
| AC5 | No review text, no listing copy and no rehosted image is persisted anywhere — including logs, traces, APM, Redis and vector stores. |
| AC5d | No raw review or listing text is ever transmitted to a hosted model provider (C15). |
| AC5b | No vector embedding is ever generated from review text; no review-text corpus exists. |
| AC5c | User-facing output contains no full review and no long quotation. |
| AC6 | Every displayed figure carries a source link and capture timestamp. |
| AC7 | Snapshots older than 7 days are reported unavailable and never fire an alert (OP3). |
| AC7b | Snapshots are purged per the configured retention policy; none is retained indefinitely (C19). |
| AC8 | A failed fetch produces a snapshot row with a status, never a gap and never a fabricated value. |
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
| T1 | Add valid `amazon.in` URL | Stored; not fetched |
| T2 | Add `alibaba.com` URL | Refused, reason named (AC4) |
| T3 | Free tenant adds a 4th URL | Blocked by entitlement |
| T4 | First run on a new URL | Baseline snapshot; no event (AC11) |
| T5 | Second run, price −8%, threshold 5% | Event, `threshold_breached = true`, `alert_eligible = true` |
| T6 | Second run, price −2% | Event recorded, `threshold_breached = false`, no alert |
| T7 | Price static, stock → out | Event fires via D3 |
| T8 | Fetch blocked | `BLOCKED`; cached shown with age; no alert (E3) |
| T9 | Prior snapshot 9 days old | **Reported unavailable**; not displayed with a stamp; no alert (AC7) |
| T10 | Listing 404s | `NOT_FOUND`; URL `UNREACHABLE`; no event |
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
| T25 | Dashboard-button run by a partner with `agent.ci` but not `agent.ceo` | Succeeds on the direct path; no CEO call consumed (C20) |
| T26 | Same partner asks CEO for a competitor check | Requires `agent.ceo`; `403` without it (§7 rule 3) |
| T27 | Snapshot ages past retention horizon | Purged; derived insight retained (AC7b) |
| T28 | Inspect CI for a fee rate table | None present (AC10b) |
| T29 | Grep all stores and outbound request logs for a known listing title | Zero hits (AC5, AC5d) |

---

## 12. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | **Residual WhatsApp items** `whatsapp-integration.md` itself leaves open (credit/cap treatment, mid-thread cap behaviour, decline-alert channel, post-completion messaging) — see its §13 Q3 and this spec's §6.9. | Narrower than before; no longer blocks the whole WhatsApp path (identity, invoke/revoke, and investigation-creation are resolved) |
| Q2 | **Brain 1 entitlement treatment (M13).** OP9 says shared services carry their own caps, but no key or meter exists for Brain 1. CI calls it on every run. | Entitlement spec |
| Q3 | **Paid-tier CI values** (25 URLs, 100 runs/month) are provisional and unlocked; readiness 3.3 defers final tiers (M7). | Entitlement spec |
| Q4 | **Default threshold value.** Is ±5% right for Indian marketplaces, where festive repricing is routine? | Product |
| Q5 | **Per-URL vs per-tenant threshold.** A ₹200 and a ₹20,000 product behave differently; `ci_tenant_config` currently holds one value. | Product |
| Q6 | **Proxy / anti-bot infrastructure** — budgeted, or accept a lower success rate? | Ops |
| Q7 | **Local derivation model choice and quality.** C15 mandates local-only; on 4GB VRAM, sentiment and theme extraction quality is unproven at volume. | 🔴 Feasibility of §6.5 |
| Q8 | **Category taxonomy mapping (BL5).** `observed_category` is captured from the listing, but Amazon, Flipkart and Meesho category strings do not agree with each other or with the fee reference store's taxonomy (`deterministic-engine.md` §5.14). A mapping layer is required and does not exist. | 🔴 Blocks fee resolution for the estimated range |
| Q9 | **CI audit event set (MN9).** §6.4 requires audit logging on every execution, but no event set or artefact is defined. `auth.md` `auth_audit` is scoped to security events only. | Orchestration / observability |
| Q10 | **`robots.txt` posture (MN15).** Honour strictly, honour for discovery only, or treat user-initiated single-page fetches as out of scope? A legal question, not a technical one. | Legal review (V6) |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Review-text retention boundary | C14, C15, §6.5 — transient, local-only, never persisted or transmitted |
| R2 | Where the margin band is computed | C17, §5.2, §6.7 — Brain 1 only; CI supplies a provenance-tagged observation set |
| R3 | Whether a dashboard button is a CEO path | C20, §6.4 — direct execution path; `agent.ci` alone; no CEO call consumed |
| R4 | Where fee references live | C18 — versioned backend reference store consumed by Brain 1 |
| R5 | Snapshot retention | C19, §6.8 — configurable, default 90 days; revisit after DPDP |
| R6 | Competitor listing copy | C16, §6.6 — expression; derived attributes only |
| R7 | Arithmetic boundary | Front matter + AC1 — observed-fact deltas permitted; all financial arithmetic in Brain 1 |
| R8 | WhatsApp identity, invoke/revoke, and investigation-creation (was Q1) | `whatsapp-integration.md` now exists and resolves all three: identity via `bound_by` (§6.9, `whatsapp-integration.md` C8), `WHATSAPP_CONFIRM` re-entering CI's own §7.1 chain (§6.9), and implicit investigation creation on first contact (§6.9, `ceo-agent-orchestration.md` §6.7). Only billing-cap interaction and post-completion messaging remain open — narrowed into the new Q1. |
