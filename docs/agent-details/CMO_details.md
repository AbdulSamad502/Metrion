# Slim CMO — Agent and Dashboard Details

> Describes the Slim CMO as **built in the repository on 2026-10-21** (branch `feat/ci-upgrade`). A readable companion to the specs, not a replacement:
> authority stays with `docs/specs/slim-cmo-agent.md` and `docs/specs/ceo-cmo-delegation.md`. Where this file and a spec disagree, the spec wins.

**One line:** the CMO turns a seller's product facts (and optionally a photo) into **marketplace-specific SEO titles, a grounded copy pack, hashtags, catalog answers and dated, source-linked market-trend reports** for Amazon, Flipkart and Meesho. It is **recommend-only**: it writes text the seller copies and pastes. It never publishes, never touches a marketplace, and never states a price, fee or GST rate.

| | |
|---|---|
| Phase 1 | The agent — how it works and what it does |
| Phase 2 | The dashboard — what is shown and how it is displayed |

---

# PHASE 1 — The agent: how it works and what it does

## 1.1 What the CMO is (and is not)

| The CMO **is** | The CMO is **not** |
|---|---|
| A generator of titles, bullets, description, keywords, backend terms, hashtags | A publisher — no marketplace credential, no write-back, ever |
| A catalog Q&A that labels how sure each attribute is | A source of GST, price, fee or margin statements (CEO/CFO handle GST; Brain 1 handles money) |
| A trend-report builder that separates *attention* from *demand* | A competitor researcher (CI) or product discoverer (PI) |
| Reached **only through the CEO** | A direct seller-facing tool — the dashboard has no generate buttons |

The seven-item V1 scope is **exhaustive** (spec C3): image-informed title sets, marketplace-specific listing copy packs, standalone components, optional hashtags, catalog Q&A, seven-section trend reports, and niche-term confirmation. Anything else (posters, ad copy, A+ content, bulk rewrite, image generation) is out of scope and the CEO says so.

## 1.2 Where the CMO sits

```
Seller ──► CEO chat ──► [question cards] ──► plan card (Approve / Decline) ──► CMO ──► CEO ──► Seller
                                                     ▲ click only — typing "yes" never approves
```

- **CEO-first (CD1):** the CEO collects missing inputs, shows the exact plan, handles approval, runs the CMO, and presents the result verbatim.
- **Star topology:** the CMO never calls CI, CFO or PI. CI-derived listing themes can be attached by the CEO as optional input; trend retrieval comes from a shared market-signal service, not PI.
- **Permissions:** `agent.ceo` + `agent.cmo` for chat; trend reports also need `research.market_trends`; catalog-derived niche suggestions need `catalog.view`; image upload needs `files.upload`. Permission and entitlement are separate gates (`403` vs `402`).
- **Tenancy:** every table has `tenant_id` under `FORCE ROW LEVEL SECURITY`, composite `(tenant_id, id)` foreign keys so a row can never point at another tenant's row; provenance tables are append-only for the app role.

## 1.3 The flow, end to end

```
1  Seller asks in CEO chat        "Write titles for my steel bottle on Amazon and Flipkart"
2  CEO asks only what's missing   one question per turn, written by code (closed vocabulary)
3  [Optional] seller attaches photo  → small approval card → vision read → hints to confirm
4  Plan card                      exact inputs, units, what leaves Metrion; seller clicks Approve
5  cmo.generate_title_sets        5 options per marketplace, validated in code
6  Seller picks a title (card)    free; saved as an approval record (or supplies their own)
7  Plan card #2                   cmo.generate_listing_copy per marketplace (separate approval)
8  Result shown verbatim          counts + limits + labels; "read it before you use it"
9  Seller copies it, pastes it on the marketplace themselves
```

A title set and its copy pack are **two plans** because the pack depends on the chosen title. An incomplete task ends `CLARIFIED` (nothing runs, nothing metered).

## 1.4 Actions the CMO offers

| Action | What it does | Units |
|---|---|---|
| `cmo.generate_title_sets` | 5 constraint-valid title options for **one** marketplace | 1 per marketplace delivered |
| `cmo.approve_title` | Records the seller's chosen (or self-written, re-validated) title | 0 |
| `cmo.generate_listing_copy` | Description + bullets + keywords for one marketplace, grounded in the approved title; atomic | 1 per marketplace |
| `cmo.generate_description` / `bullets` / `keywords` / `backend_terms` | A single standalone component (backend terms: Amazon only) | 1 each |
| `cmo.generate_hashtags` | Separate marketing suggestions — *not* a listing field | 1 |
| `cmo.catalog_answer` | Category, colour, material, size, weight, dimensions, brand — each with a basis label | 1 per marketplace answered |
| `cmo.upload_image` / `cmo.analyze_image` (via an attachment reference) | Normalise, store and read one product photo | 0 |
| `cmo.confirm_image_hint` | Seller confirms/corrects one photo-derived hint | 0 |
| `cmo.suggest_niche_terms` / `cmo.confirm_niche_terms` | Derive and confirm niche terms for research | 0 |
| `cmo.market_trends` | One seven-section trend report | 1 CMO unit + 1 shared-meter unit |

Worked example: one product, all three marketplaces, titles + packs = **6 units**. A `FAILED` artefact, a blocked marketplace, a config error or a denied request costs **0**. Regeneration is a new artefact and a new unit. Duplicate submissions are idempotent on `request_key` (no second unit).

## 1.5 Step-by-step: how each capability works

### Step A — Intake (the CEO builds it from validated inputs only)
The CMO declares what it needs through a **pure requirement function** over a closed vocabulary: `MARKETPLACES` (never defaulted), `PRODUCT_NAME`, `GROUNDING_TITLE`, optional `PRODUCT_FACT(attribute)` (brand, colour, material, size, product type, category hint), optional `IMAGE`, `IMAGE_HINT_CONFIRMATION`, `NICHE_CONFIRMATION`, and `MARKET_TRENDS_PREVIEW_ACK`. Rules:
- One question per turn, at most three options plus "Other" and Cancel; replies are parsed by code, never by a model.
- Limits (configuration): max **8** questions per task, max **2** re-asks of one field, **24 h** idle expiry. At a limit the CEO explains the blocker and offers Restart; on expiry the collected inputs are kept but a fresh confirmation is required.
- Optional high-value details (brand, size, 1–3 features, main use, search words) are asked, each skippable; with fewer than two details beyond the name the result says *"Thin input — add brand/size/features for stronger titles."*
- Confirmed facts are preserved across the exchange; nothing the seller confirmed is asked twice. A changed answer after a plan exists makes a **new plan** (new hash, old one superseded).
- Every seller-supplied text is stored as an append-only `seller_fact` (money only as integer-paise `TARGET_PRICE`, echoed, never written into copy).

### Step B — Image analysis (optional, never blocking)
- The photo arrives as an `attachment_id` in the shared store and is passed **by reference** — no bytes through any model. The CMO loads it by its own tenant-scoped read.
- Pipeline: validate (type allow-list, magic bytes, byte/pixel limits, header size check before decode) → **re-encode to a fresh PNG** (drops EXIF/GPS, ICC, thumbnails, trailing bytes, polyglots) → hash → store → analyse → parse → trust-gate.
- Vision is a **local Ollama model only**, behind `VisionProvider`; an endpoint must be in `LLM_OPERATOR_CONTROLLED_HOSTS` or the hand-off fails closed before any bytes are read. The plan card names the endpoint label and model.
- Closed schema `cmo-vision-v1`: `color`, `material`, `size`, `brand`, `product_type`, `visible_text` — each *observed* or `UNKNOWN`. Anything with a digit, a price/tax/contact/demand/certification wording, weight, dimensions, rating or category is discarded.
- **Trust gate:** until a human-approved evaluation (`vision_eval_run`) passes for the exact provider+model+schema, **every observation is an `UNVERIFIED_HINT`** — shown only as *"from your attachment — suggested, not verified; please confirm"*, never used as a claim. The gate is closed at launch. A seller's confirmation becomes a new `SELLER_PROVIDED` fact; it does not make the photo or provider trusted. Everything works at 100% without the image.
- Analysis is metered at 0 (separate small approval card, option A); outcomes `COMPLETE` / `DEGRADED` / `FAILED`; a vision failure never silently falls to text-only — it needs the seller's confirmation.

### Step C — Format constraints (the rule table)
Limits (title length, option count, bullets, description, keyword count, Amazon backend-terms bytes, hashtag support, character-count rule) are **configuration rows**, never hardcoded. The code reads the live `format_constraint` row; **production generation is blocked** for a marketplace with no `VERIFIED`, non-stale row or no verified `count_rule` (`COUNTING_RULE_UNVERIFIED`) — other marketplaces in the same request proceed. `TEST_FIXTURE` rows are never read in production, and a result fitted to one is labelled *"placeholder limits for testing, NOT a verified marketplace rule."* A limit the row doesn't state is neither enforced nor guessed.

### Step D — Title sets
Five distinct options (count from config), varying in emphasis (brand-first, feature-first, use-case-first), grounded only in **claim-eligible** facts. **Character counts are computed in code**, never reported by the model; a violating option is regenerated (bounded retries) or dropped. Fewer valid options → returned **short and labelled**, never padded; zero valid → `FAILED`. Each option stores `char_count` and a `constraint_check` naming the rule applied.

### Step E — Approval of a title
The seller selects exactly one option per marketplace by card click, or supplies/edits their own text (re-validated against the *current* constraint). Stored in `cmo_title_approval`. It is a **choice record**, free, and distinct from plan approval. The CEO can never choose for the seller; "latest approval" is never inferred.

### Step F — Listing copy pack
Per marketplace, in its **own call** from its own approved title and constraint — never adapted from another marketplace. Shapes differ (Amazon/Flipkart/Meesho), not just lengths. **Code enforces:** title consistency, bullet count and per-bullet length, description type/length, keyword count/length/duplicates, UTF-8 byte caps, and a **forbidden-content scan** (price figures and price/discount/savings claims, GST/tax statements, "trending/bestseller" family, unsupported claims, URLs/phone numbers where disallowed). Duplicates are *exact only* after normalisation. The pack is **atomic**: description, bullets and keywords all pass or the result is `FAILED` (0 units), often `NEEDS_FACTS` listing exactly which facts to supply — never padded with guesses. Flipkart structured fields are returned as `NEEDS_SELLER_INPUT` (no verified field taxonomy exists).

### Step G — Attribute-basis labelling (catalog Q&A and copy)
Every attribute carries one basis:

| Basis | Meaning | May be asserted as fact in copy? |
|---|---|---|
| `SELLER_PROVIDED` | The seller said so | Yes |
| `IMAGE_OBSERVED` | Literally visible, **and** the vision gate passed | Yes |
| `SOURCE_DERIVED` | From a cited, dated source (not produced in V1) | Yes, with citation |
| `ESTIMATED` | Model inference, shown as a labelled range "confirm before listing" | **No** |
| `UNKNOWN` | Not determinable; the seller is asked | No |

Precedence per attribute is deterministic: latest seller fact → passed-gate observation → validated estimate → `UNKNOWN`. Weight/dimensions are never `IMAGE_OBSERVED`; category is returned as a plain-words suggestion, never a browse-node id. Catalog answers make no model call and an all-`UNKNOWN` answer is still a delivered answer.

### Step H — Hashtags
A separate optional artefact labelled *"marketing suggestions — not a listing field on any marketplace"*. No marketplace's hashtag support is verified, so none goes into a listing field. Needs the `hashtag_set_size` config key.

### Step I — Optional CI-informed generation
If the seller has `agent.ci` plus a passing CI entitlement, the CEO may attach CI's `competitor_listing_insight` themes. A theme is used in copy **only** if the seller's product has a claim-eligible attribute supporting it; otherwise it's surfaced as "consider adding if true for your product". Competitor text and prices are never consumed. Missing/stale CI silently falls back to independent mode with a note. *(Per the build record this CI-informed mode — "P11" — was not started; generation runs in `INDEPENDENT` mode.)*

### Step J — Market-trend reports (the most elaborate capability)

**Niche confirmation first (C15).** Only seller-**confirmed** terms may leave Metrion. Terms come from what the seller types, stored seller facts, or **catalog-derived suggestions** — deterministic frequency over distinct `item_title` strings only (no amounts, order ids or customers; capped; no LLM sees titles). Every term passes an outbound screen (length, no email/phone/GSTIN/order-id/URL tokens, not numeric) and is shown with its origin for confirm / edit / reject. Confirmation happens in the CEO chat.

**Retrieval (shared service, no LLM).** Query text is built only from **fixed versioned templates + confirmed terms + marketplace names**, India-targeted, via Tavily (news mode, date-stamped) and YouTube. An **egress guard** re-renders every query and requires an exact match before each call. The exact queries are shown in a **preview** whose digest is frozen into the plan; if anything changes, the run is `409 PLAN_CHANGED` and nothing is sent. Budgets (queries, results, windows) come from configuration; a missing key is `CONFIG_MISSING`, never a default. A platform-wide **daily provider ceiling** (Asia/Kolkata day) is taken before each call and never refunded; cache hits are free; per-tenant caching protects term privacy.

**Evidence is computed in code, never by the model (C14):**
- *Independence:* web items by registrable domain, videos by channel; many items from one source count once; identical titles collapse to the earliest.
- *Recency:* `FRESH` / `RECENT` / `OLDER` / `DATE_UNKNOWN` — a retrieval date is never treated as a publication date.
- *Corroboration:* `SINGLE_SOURCE` → `WEAK` → `MODERATE` → `STRONG` from configured thresholds, downgraded for old items, capped for undated ones. Always labelled *"corroboration of attention, not of demand."*

**The seven sections (always all seven; a section may be `UNAVAILABLE` with a reason):**
1. **Your niche** — signals for confirmed terms ("attracting attention in [source], [date]", never "selling"/"in demand")
2. **Marketplace & e-commerce news** — policy/fee/seller-program/seasonal updates; official vs third-party by domain; no fee/price figure restated
3. **Reported tactics** — always `REPORTED_NOT_VERIFIED`, with policy-risk grading; risky or unassessed tactics sit in a caution group with **no suggested action**
4. **New products & buzz** — launches, viral products, emerging themes; "attention signal — not proof of sales"; no score, rank or feasibility
5. **Adjacent opportunities** — "worth investigating", unranked
6. **What this could mean for your business** — the model's interpretation, each item citing existing findings, labelled *"CMO's interpretation — not a verified market fact"*
7. **Evidence & limitations** — source table with publication and retrieval dates, degraded sections, budget used, fixed gaps (no sales data, no search-volume data)

The model only proposes themes/summaries/cited item numbers; **code validates** (cited items exist, no attention-as-demand wording, no restated numbers/prices/tax/contact, closed kind sets), rejects rather than edits, and computes all evidence. A finding with no citable source is dropped. A report is `COMPLETE` if at least one finding is citable (degraded sections are named; still one unit + one shared unit); otherwise `FAILED`, nothing billed.

## 1.6 The chat result

Artefacts are shown **verbatim** with a fixed label ("Written by the specialist from the details you gave. Read it before you use it; Metrion has not checked it against your marketplace account"), code-computed character/byte counts beside the limit and its source URL/verified date, and attribute-basis labels. No second model rewrites, merges or re-ranks. A failed artefact is a named gap with the missing detail; a partial multi-marketplace request says which succeeded and what each cost. Next steps (choose a title, request the pack) are offered as chips, never auto-run.

## 1.7 Billing, quota and retries

- One delivered artefact = one `cmo_generation` row = one unit. Only `COMPLETE` consumes a unit; metering is an idempotent `metered_event` (`cmo:<generation_id>`).
- Multi-artefact requests are **all-or-nothing checked up front**; when a cap resolves, the whole unit count is **reserved** under an advisory lock (TTL 300 s, config required) so concurrent requests cannot exceed it. A reservation is quota protection, not a bill.
- Trend reports admit on **two meters** (`cmo.market_trends` and shared `research.market_trends`); denial on either is `402` and releases the first.
- Internal retries (bounded by `internal_retry_bound`) cost no extra unit. No cap is seeded by any migration; until a cap row exists the system resolves `NO_CAP_CONFIGURED` and passes.

## 1.8 Data the CMO stores

| Table | Holds |
|---|---|
| `seller_image_asset` / `product_image_analysis` | Normalised image (object store) and its immutable structured analysis with trust state |
| `vision_eval_run` | Platform-level evaluation record that opens/closes the trust gate |
| `cmo_generation` | One row per artefact (type, marketplace, mode, status, request key, constraint used) |
| `cmo_title_option` / `cmo_title_approval` | The 5 options and the seller's selection |
| `seller_fact` | Everything the seller stated or confirmed, with provenance |
| `format_constraint` | Per-marketplace rule rows (`VERIFIED` / `TEST_FIXTURE`) |
| `cmo_niche_term` | Suggested / confirmed / rejected niche terms |
| `cmo_trend_report` | Sections, interpretation, evidence, **exact outbound queries**, config snapshot |
| `cmo_platform_config` | Every tunable; nothing seeded, absence = `CONFIG_MISSING` |
| `cmo_result_usage_event` | Append-only view/copy/mark-used/generated events (feeds "Frequently used") |
| `cmo_quota_reservation`, `cmo_provider_usage` | Quota reservations; the daily provider counter |

No table stores a GST rate, a fee or a competitor/seller price as CMO fact.

## 1.9 API surface (`/api/v1/cmo/*`)

- **Generation / action routes** (`/title-sets`, `/listing-copy`, `/description`, `/bullets`, `/keywords`, `/backend-terms`, `/hashtags`, `/catalog-answers`, `/title-approvals`, `/image-hints/confirm`, `/images`, `/image-analyses`, `/niche-terms/*`, `/market-trends[/preview]`): kept as **internal authorized capabilities the CEO runs in-process**. The frontend no longer calls them; they are slated for safe deprecation behind a `CMO_DIRECT_ROUTES_ENABLED` switch (`410 USE_CEO_CHAT` when off), never abruptly deleted.
- **Reads:** `GET /niche-terms`, `GET /market-trends`, `GET /market-trends/{id}` (unknown and cross-tenant ids give an identical 404).
- **Dashboard reads:** `/api/v1/cmo/showcase/{products, trends, titles, copy-packs, hashtags, compliance}` (all `GET`, `agent.cmo`, tenant from the session only) plus the single write `POST /showcase/usage-events` (204).

## 1.10 Hard guarantees

1. **Recommend-only, no exception.** No marketplace credential or write path exists.
2. **No LLM states money, GST or a fee;** the model never reports its own length compliance.
3. **Specs are never invented:** only `SELLER_PROVIDED`, gate-passed `IMAGE_OBSERVED` and cited `SOURCE_DERIVED` attributes may be asserted.
4. **Attention ≠ demand ≠ sales ≠ profitability** — enforced by validators, not just prompts.
5. **Nothing leaves Metrion** to a research provider except template text, confirmed niche terms and marketplace names — every query is audit-persisted.
6. **Evidence is computed in code,** and every finding has a dated (or explicitly `DATE_UNKNOWN`) source link.
7. **Plan approval is a click bound to the plan id and hash;** typed text never approves.
8. **Missing config blocks, it doesn't default** (`CONFIG_MISSING`, `COUNTING_RULE_UNVERIFIED`).

## 1.11 Honest limits today

*(From `docs/planning/slim-cmo-build-status.md` — last updated 2026-10-04 — and the specs. I did not re-run any tests or live checks.)*

- **Launch blockers (owner inputs):** verified marketplace format constraints with `count_rule` and max-age; unset trend configuration (`max_sources_per_report`, `max_findings_per_section`, the freshness windows and corroboration thresholds); a **per-tenant monthly trend cap must be seeded** or one tenant can exhaust the shared daily ceiling; the tactic-risk pattern set (until then every tactic is `UNASSESSED` with no suggested action); the vision pass-bar and image limits/retention; legal review of search providers; provider keys and model settings.
- **Vision trust gate is closed** — all photo-derived values are unverified hints. A real-model vision/generation run and a signed-in click-through of the workspace had not been possible in the build environment.
- **P6 (image intake/vision/evaluation) is explicitly UNVERIFIED** against the development database (its leftover test rows block the shared fixtures); passing evidence exists only on a clean scratch database.
- **CI-informed generation (P11) and close-out (P12) were not started** per the build record; `SOURCE_DERIVED` is vocabulary only.
- **Known validation gaps:** a pack that contradicts its approved title in *meaning* isn't detected; letter-spaced banned phrases aren't recognised; Hindi is the only regional language covered; the provider's India filter is approximate.
- The daily provider ceiling counts CMO searches only — PI shares the same keys and is invisible to it.
- The status document is dated 2026-10-04; the CEO-delegation spec still says "nothing implemented" although the delegation module, showcase routes and showcase components now exist. Treat both documents' status lines as stale and check code before relying on them.

---

# PHASE 2 — The dashboard: what is shown and how

**Route:** `/dashboard/cmo` (`ShowcaseDashboard.tsx`, helpers in `showcaseUi.tsx`, client in `lib/cmoShowcase.ts`).
**Nature:** a **read-only library of what the CEO's CMO already produced and saved**, across **all CEO conversations of the tenant** (not just the latest). There is **no generate, regenerate, upload, approve or niche form**, and no call to any CMO `POST` route. The only inputs are the search box, filters and view toggles. The only write is a fire-and-forget **usage event** when a seller copies, opens or marks something as used. Layout follows `docs/design/Design-Overviews/Slim-CMO-Dashboard.svg` in structure, rendered in Metrion's configurable theme tokens (the app is dark-only today).

## 2.1 Page structure, top to bottom

```
┌──────────────────────────────────────────────────────────────────────┐
│ Slim CMO Dashboard        [Product ▾ All products]  [Search saved …] │ header
│ Saved SEO titles and marketplace copy … - read-only library          │
├──────────────────────────────────────────────────────────────────────┤
│ To create or change anything, ask the CEO. …           [ Ask the CEO ]│ notice
├──────────────────────────────────────────────────────────────────────┤
│ Market Trends & Fresh E-Commerce News                                │ ① news cards (≤9)
├──────────────────────────────────────────────────────────────────────┤
│ Frequently Used SEO Titles   [Recent|Frequently used] ☐ Approved only│ ② titles
│ [ Amazon | Flipkart | Meesho ]                                       │
├──────────────────────────────────────────────────────────────────────┤
│ Grounded Marketplace Copy Pack                    [ Copy Full Pack ] │ ③ pack
├──────────────────────────────────────────────────────────────────────┤
│ Social Marketing Hashtags & Compliance Summary                       │ ④ hashtags + checks
└──────────────────────────────────────────────────────────────────────┘
```

## 2.2 Common elements and states

- **Header:** title "Slim CMO Dashboard"; subline "Saved SEO titles and marketplace copy (Amazon, Flipkart, Meesho) – read-only library".
- **Product filter** (a `select` of products with saved results — a filter only, never an input to anything) and a **debounced (300 ms) search box** across stored titles, packs and hashtags (server-side, parameterised text match; no embeddings, no model).
- **"Ask the CEO" banner:** *"To create or change anything, ask the CEO. This page only shows what is already saved."* with a button to the CEO Hub.
- **Every section** has distinct **loading / empty / error (with retry)** states and never shows placeholder data. Typical empties: "No news fetched yet – ask the CEO for market news", "No saved Amazon titles match. Ask the CEO to create titles.", "No saved … copy pack yet. Ask the CEO to create one."
- **Sample mode:** `?fixture=1` renders obviously-fake fixture data under a warning bar *"SAMPLE DATA – local visual check only"*. The fixture module is excluded from production builds (guarded by `NODE_ENV`).
- All database text is escaped; external links open with `rel="noreferrer noopener"` and only `http(s)` URLs render as links.

## 2.3 ① Market Trends & Fresh E-Commerce News
Source: stored `cmo_trend_report` rows only — the real market-trends workflow run through the CEO. Hint: "From saved market-trend reports only".
- **Context line:** `Niche: <confirmed terms> – Updated <date>` plus the report's interpretation label.
- **Cards (up to 9, 1/2/3-column grid):** each finding shows a **section pill** (e.g. Your niche, Marketplace news), the **source name as a link**, the **finding text** (bold), `Published <date>` or **"Publication date not stated"**, `retrieved <date>`, the **corroboration label** when stored, and "Evidence and limitations: <ref>".
- Never shown: invented dates, percentages, "verified"/"official" badges or scores the record doesn't carry. A report with no findings says so.

## 2.4 ② Frequently Used SEO Titles
- **Marketplace tabs:** Amazon / Flipkart / Meesho (a real accessible tab list).
- **View toggle:** **Recent** (newest generated) or **Frequently used** (ranked **only** from recorded `COPIED` + `MARKED_USED` events). **Approved only** checkbox.
- **Each title card:** an **"Approved"** pill **only when a `cmo_title_approval` record exists** (tooltip shows the date); `chars / limit` (e.g. `68 / 200 chars`, from the stored count and the applied constraint); product label and generation date; the **title text**; a **usage line** when events exist ("copied 3 times, marked used 1 time, recorded since …"); **Copy** and **Details** buttons.
- **Frequently used unavailable:** when no copy/mark-used events are recorded, the view says "Frequently used unavailable – usage is not recorded yet. Switch to Recent." Popularity is never guessed from recency, length or request count; *generation* and *viewing* are never counted as use, and approval is a separate fact.
- **Details drawer:** product (SKU), marketplace, generated date, created via ("CEO chat" / "Earlier workflow"), generation id, investigation and turn ids, length, **limit source URL and verified date**, approval status (including "edited by seller"), and a **Mark as used** button with the note *"Marking as used only records that you used this yourself. Nothing is published for you."*

## 2.5 ③ Grounded Marketplace Copy Pack
- Scoped to the selected marketplace tab; if several packs exist, a **pack switcher** (product – date) appears and the newest is the default.
- **Header line:** "Grounded on: <approved/supplied title> (basis) – product – date", so the seller sees which title the pack was built from.
- **Feature bullets** — one card each with its text, `chars / max`, and Copy.
- **Product description** — text (line breaks kept), `chars / max`, Copy.
- **Backend search terms** (Amazon only) — text, `bytes / max bytes`, Copy.
- **Copy Full Pack** button (bullets + description + backend terms), a labels line (attribute-basis labels), and **Pack details** (drawer: product, marketplace, date, origin, grounded-on title, ids).
- All counts come from the stored artefact and constraint row; nothing is recomputed by a model. A pack missing any required part is not shown as a pack (they are atomic).

## 2.6 ④ Social Marketing Hashtags & Compliance Summary
Hint: "Separate marketing suggestions – not a marketplace listing field".
- **Hashtag sets:** one card per saved set (product – date) with the hashtags in green and a **Copy** button (emits a usage event).
- **Compliance summary (stored checks only):** a list of counts, each with its basis — e.g. constraint-check results on titles and copy, options dropped or returned short, tactic policy-risk groupings from trend reports. Only what is already stored is shown; if nothing is stored: "No stored validation results to summarise yet."
- Footer: *"Recommend-only: nothing here is sent to a marketplace, and this summary is not a marketplace approval."* The summary never claims anything is "compliant" or "approved by the marketplace."

## 2.7 What was removed on purpose
Product/Create/Titles/Listing-copy/One-piece/Catalog/Niche forms; image upload and analysis; approval/"select-and-lock" controls; regenerate and "+ Generate New Pack"; any "(N Unit)" cost button; any direct call to a CMO `POST` route. Mockup sample content (e.g. "+34%", "Verified 2h ago · Official", "Approval ID #APP-7721") is never shipped.

## 2.8 Display rules the UI always follows
1. **Real saved data only** — an empty section says why and how to fill it (ask the CEO).
2. **Counts, limits and dates are stored values,** never recomputed or invented.
3. **"Approved" appears only from a saved approval record;** "Frequently used" only from recorded copy/mark-used events.
4. **Honest wording:** "attention", "reported", "not a verified market fact", "marketing suggestions", "recommend-only" — never "trending" or "in demand" as fact.
5. **Accessible and themed:** tab list semantics, `aria-pressed` on toggles, labelled form controls, keyboard operation, dark theme only today; visual design remains configurable and decoupled from logic.

## 2.9 Dashboard gaps (honest)

- The **"Frequently used" view stays "unavailable"** until real copy / mark-as-used events accumulate; the de-duplication window and any minimum-count or look-back settings are still open decisions (spec OQ-19).
- The spec says the page was not click-tested with a signed-in session at build time; I did not click-test it either — I only read the code.
- Whether the legacy read-only **Usage** (entitlement meter) panel stays is undecided (OQ-11), and the approver's identity is returned only as "approved by you" (OQ-12).
- Results created before the chat-only workflow are labelled "earlier workflow"; whether to include them at all is still an open question (OQ-6).
- Visual styling follows the reference closely in layout but is not final (`docs/design/design_status.md`).
