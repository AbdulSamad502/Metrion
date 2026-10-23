# Product Intelligence (PI) — Agent and Dashboard Details

> Describes PI as **built in the repository on 2026-10-21** (branch `feat/ci-upgrade`). It is a readable companion to the specs, not a replacement:
> authority stays with `docs/specs/product-intelligence-agent.md` and `docs/specs/ceo-pi-research-flow.md`. Where this file and a spec disagree, the spec wins — and the disagreement is a bug in this file.

**One line:** PI finds *product opportunities* a seller could sell, shows the evidence behind each, finds supplier leads, and hands the seller a short, explainable list. It **researches; it never calculates money**, and it **never touches a marketplace**.

| | |
|---|---|
| Phase 1 | The agent — how it works and what it does (below) |
| Phase 2 | The dashboard — what is shown and how it is displayed |

---

# PHASE 1 — The agent: how it works and what it does

## 1.1 What PI is (and is not)

| PI **is** | PI is **not** |
|---|---|
| A research agent over open web + video signal (Tavily, YouTube) | A marketplace scraper — no Amazon/Flipkart/Meesho page is ever fetched |
| A finder of *candidate opportunities* and *supplier leads* | A sales-rank or "bestseller" list — it has no sales data |
| A producer of provenance-tagged, explainable scores | A calculator — every rupee figure comes from Brain 1 (the deterministic engine) |
| Triggered by the seller, through the CEO | Scheduled, continuous, or a crawler — every run is explicit and bounded |

**Labelling discipline (applies to every screen, API field and sentence):**
- Results are **"opportunity candidates"** — never "trending", "bestseller" or "popular". `product_candidate.opportunity_label` is database-locked to `CANDIDATE_OPPORTUNITY`.
- Three evidence kinds are never blurred: **editorial image** (always attributed), **viewer/web commentary** (YouTube comments + article text), and **verified buyer reviews** (not available in V1 — shown nowhere).
- Missing data is **named, never zero**. `demand_signal` is always present but `UNAVAILABLE` (Google Ads access pending brand verification).
- Estimates stay estimates at every hop (`estimate_ref`, never `engine_result_ref`).

## 1.2 Where PI sits in Metrion

```
Seller ──► CEO chat ──► (approved plan) ──► PI ──► CEO ──► CFO ──► CEO ──► Seller
                                            │               ▲
                                            └─ never calls ─┘   PI never calls CFO;
                                               CFO directly      the CEO passes facts across
```

- **Star topology:** the seller talks only to the CEO. PI's HTTP routes also exist (and are tested), but the **frontend no longer calls them** — the dashboard is read-only.
- **Permissions:** `agent.ceo` + `agent.pi` for the chat path; running a discovery also needs `research.niche_run` (a spend-control key, separate from "may use PI"). Each is an independent gate from the entitlement (run credit) check — `403` for a missing permission, `402` for no entitlement.
- **Tenancy:** every table carries `tenant_id` under `FORCE ROW LEVEL SECURITY`; no endpoint accepts a client-supplied tenant; another tenant's run id returns 404.

## 1.3 The end-to-end flow

```
1  Seller asks in CEO chat            "Find me products under ₹20,000 on Amazon"
2  CEO fills the brief                 category · budget · marketplaces · target price band
3  CEO shows one plan card             lists discovery AND the supplier lookup; seller approves once
4  pi.discover                         ~30 opportunity candidates (cap), Stage‑1 scored
5  Review insight (shortlist ≤15)      viewer/web commentary → sentiment + themes (local model)
6  Feasibility (shortlist)             Brain 1 price/fee‑spread range, estimate_ref
7  pi.shortlist_top5  (pre‑rank)       deterministic pick of the 5 seller‑facing products
8  Top‑5 image resolution              product photo, or none
9  pi.supplier_lookup (top 5 only)     Google Places + Tavily/B2B directories
10 Finalise the case                   Stage‑4 re‑score → final order → recommendation, saved
11 CEO summary + "View Detailed Research" link → PI dashboard (?run=<id>)
12 Optional: seller gives a quote      CEO → CFO → landed cost / batch size attached to the case
```

Nothing runs before the plan is approved. A failed follow-up (e.g. supplier lookup) becomes a **named gap**; the seller still gets what was found.

## 1.4 Step-by-step: what each stage does

### Step A — Intake (the niche brief)
A `niche_brief` is the structured question: `category_text`, `budget_paise`, `target_price_min/max_paise`, `marketplaces[]` (which fee schedules feasibility uses — never an observed listing), and optional `constraints` (e.g. `exclude_brands`). Lifecycle `DRAFT → READY → ARCHIVED`; a run starts only from a `READY` brief. The CEO extracts values the seller already stated (deterministic parsers, no model), echoes them back for correction, asks only what is missing, and never invents a value. Depth is no longer asked: chat runs use `SHALLOW` because `depth` does not change behaviour today.

### Step B — Discovery (`discovery/discovery_run.py`)
- Queries per niche: the category, `"best {category} india"`, `"{category} review"`.
- Sources: **Tavily** (web search + images) and **YouTube Data API v3** (views, comment counts). Both go through a per-query TTL cache (keyed by query text, not tenant) and a **process-wide rate limiter** (3 concurrent calls per source), so many tenants cannot exhaust the shared free-tier quota.
- A source that errors degrades to `UNAVAILABLE` *for this run* → run status `PARTIAL`, never a hidden gap and never a hard failure.
- **Grouping into candidates (`candidate_synthesis.py`, two tiers):**
  1. *Extraction-first* — a local Ollama pass lists product names literally present in each result ("brand + model"). One roundup article naming five products yields five candidates.
  2. *Jaccard fallback* — token-overlap grouping when extraction found nothing or was unavailable. Confidence is honestly labelled `DERIVED`, `DERIVED_NO_PRODUCT_EXTRACTED` (looked, found nothing) or `DERIVED_EXTRACTION_UNAVAILABLE` (technically failed) — a failure is never narrated as a real negative.
- **Cap and ordering:** up to `candidate_cap` (default **30**). Candidates confirmed by more independent sources survive the cut first, and up to 5 slots are reserved for candidates matched to a real YouTube video so cross-validation is not silently discarded.
- **Seller exclusions:** `exclude_brands` removes dominant brands *before* the cap, so an exclusion frees a slot.
- **Web price reference:** a regex over Tavily text yields `web_price_signal` (average/range, sample count, date, always with a disclaimer). It is **reference only** — the module has no `calc_engine` import, so it can never feed a calculation.

### Step C — Stage 1 score ("proxy score", `discovery/ranking.py`)
A 10-point budget scaled to 0–100 (fixed 2-decimal string, never a float):

| Signal | Points | Basis |
|---|---|---|
| Video views band | 0–3 | YouTube view count |
| Comment-count band | 0–3 | YouTube comments |
| Source diversity | 0–4 | independent domains mentioning it (capped at 4) |
| Demand signal | 0 | always `UNAVAILABLE` (named, never omitted) |

Every candidate stores a `score_explanation` (per-signal breakdown + summary), composed deterministically — never LLM-authored. It is an **interest proxy, never units sold**.

### Step D — Review insight (`review_insight/*`)
For the shortlist (top 15 by Stage 1): a **local Ollama** model classifies YouTube comments and web snippets into a sentiment label + short theme tags. Deterministic code (`Fraction` arithmetic) turns those into `sentiment_split` and theme counts. Rules:
- Rows are scoped by `insight_source_type` — `YOUTUBE_COMMENTARY` or `WEB_EDITORIAL` — and **never aggregated together**.
- Raw comment/article text is **never persisted, logged, embedded, or sent to a hosted model**. Only the derived fields survive.
- Model unavailable → `insight_state = DEGRADED/UNAVAILABLE` with the reason; never fabricated.

### Step E — Feasibility (`discovery/feasibility.py`)
The only module allowed to import `calc_engine`. It builds observations from the seller's stated price band, budget and marketplace, resolves the fee schedule, and calls **`estimate_product_feasibility`** (Brain 1). Result: a **range** with `estimate_ref`, snapshotted onto the candidate. Because no supplier quote exists at this stage, `cogs_basis` is always `UNKNOWN` — the range is a **price-and-fee spread, explicitly not a margin**. Unresolvable category / no budget / no price band → `feasibility_status = UNAVAILABLE` with the reason.

### Step F — Pre-rank → top 5 (`discovery/prerank.py`, `pi.shortlist_top5`)
Picks the **five seller-facing products** *before* any supplier lookup (so paid lookups run for five, not thirty):
- Score = Stage 4's own proxy (40 pts) + commentary-sentiment (30 pts) components, out of 70, scaled to 100; the supplier component is shown as `NOT_YET_EVALUATED`.
- Products that **look like a product** (not a deal video, roundup, "best…", "under…", question) come first; products **with commentary** come before those without; then by score; ties by candidate id → fully deterministic.
- A candidate with neither a score nor commentary is never padded in. Fewer than five is a normal, named outcome.

### Step G — Product images (`discovery/top5_images.py`)
Only the five get an image, found *after* selection by the product's own name. Accepted only if the image text names every identity token (≥ 2), it is not on a video site, and it is JPEG/PNG/WEBP with shorter side ≥ 300 px and no banner aspect (largest wins). YouTube thumbnails are **never** used. None found → no image and a plain placeholder, never a guess. Always hotlinked with visible *"image from {domain}"* attribution.

### Step H — Supplier lookup (`direct_path/pi_supplier_lookup.py`, `pi.supplier_lookup`)
For exactly the five (max 5 ids per call), 5 workers, each candidate degrading independently:
- **Google Places (New)** — free `search_place_ids` (up to 5 matches) and the *paid* `enrich_place` (phone/website/address) for the **single best match only**.
- **Tavily** (plus B2B directories: IndiaMART, TradeIndia, ExportersIndia) — up to 4 leads per candidate, run through heuristic filters that drop editorial/listicle pages, major retail storefronts, social-media posts, and the candidate's own brand domain; manufacturer/wholesale/distributor wording boosts a result.
- **Published price (`supplier/published_price.py`)** — if a supplier's own page states a per-unit price ("₹450 per piece"), it is captured as a **range with source URL and capture date**. A bare "₹450" is ignored on purpose. It is **not a quote**, is never saved as one, and never reaches Brain 1. Absence is the common case.
- **PI never scores or ranks suppliers.** The CFO ranks them later, from seller-supplied quotes only. (The recommendation picks a "best-evidenced" lead — most of phone, website, locality, MOQ, published price, source link — which is completeness, not a ranking.)

### Step I — Final score and recommendation (`direct_path/pi_case.py`, `finalize_case`)
- **Stage 4 (`discovery/shortlist_scoring.py`)** re-scores the five independently, out of 100: proxy score **40** + commentary-sentiment quality **30** (positive:negative theme ratio, capped at 3:1) + supplier availability **30** (half credit for any lead, full if a published MOQ fits the budget). Its `final_score_explanation` is its own — never a re-export of Stage 1. This sets the **final order**.
- A **deterministic recommendation** is assembled from PI's fields only: `why_ranked`, `pros`/`cons` (commentary themes), `supplier_option`, the feasibility snapshot, and named `gaps`. Overall pick = the top COMPUTED `final_score`.
- The case is stored (`pi_research_case`), the run is stamped complete, and history is trimmed (Step K).

### Step J — CEO → CFO (optional, seller-driven)
The case alone never states cost, margin or units. Seller says *"how many units should I buy of #1?"*:
1. CEO offers supplier names, published prices and the research budget **as choices**, asks for minimum order / delivery time, and shows exactly what will be saved. **Saved only on a yes** (existing confirm card).
2. The seller's confirmed quote feeds the CFO: `cfo.landed_cost` and `cfo.batch_size`.
3. The CEO attaches the results to the case as references with display text (`engine_result_ref`); missing ones are named gaps.
4. "Most units your budget allows" is always labelled a **budget ceiling, not a recommendation or forecast**. Net margin also needs a selling price after fees and tax, and stays `Unavailable` until supplied.

### Step K — History and retention
- Dashboard history = the newest **10 unpinned** completed reports + **every pinned** one (limit configurable 5–10 per tenant).
- The 11th unpinned completion **archives** (hides) the oldest unpinned; pinned reports are never archived. Unpin re-applies the limit. Only `COMPLETE`/`PARTIAL` runs appear. Archived data is later purged by the retention window (default 90 days).

## 1.5 The CEO chat output

A code-written summary (no model-authored number): top-N headline → per product *Customers say* (liked / watch out), *Supplier* (link, source label, "not verified" for web leads, published price if any), CFO lines only when real → **Strongest opportunity** → one **Recommendation** block (order to consider, supplier, landed cost / units or what is needed, what to improve) → optional next step → **Notes** (gaps, "no verified marketplace reviews", "not a purchase instruction"). Exactly the five products — never the thirty. Ends with a **View Detailed Research** link to `/dashboard/pi?run=<run_id>`.

## 1.6 Data PI stores

| Table | Holds |
|---|---|
| `niche_brief` | The seller's structured question |
| `pi_research_run` | One run: status `QUEUED/RUNNING/PARTIAL/COMPLETE/FAILED`, `candidate_cap`, `pinned_at`, `archived_at`, `completed_at` |
| `product_candidate` | Each opportunity: title, image + source, `engagement_signal`, `demand_signal`, `web_price_signal`, `source_diversity`, `proxy_score` + `score_explanation`, `feasibility_*` snapshot |
| `product_review_insight` | Derived commentary insight per candidate and source type (no raw text) |
| `supplier_lead` | Leads: name, source, contact as published, locality, `candidate_id`; no score |
| `product_embedding` | pgvector (768-d) of **derived attributes only** for near-duplicate detection |
| `pi_research_case` | The seller-facing report: `top5_candidate_ids`, `prerank_explanation`, `recommendation`, `cfo_refs`, `gaps` |
| `pi_tenant_config` | Retention days, cache TTLs, `history_unpinned_limit` |

## 1.7 API surface (`/api/v1/pi/*`)

| Route | Purpose |
|---|---|
| `POST /discover` · `POST /supplier-lookup` | Run discovery / supplier lookup. Invoked by the CEO registry; **not called by the frontend** |
| `/niche-briefs*` | Brief CRUD (server-side; plain tenant write) |
| `GET /report/{run_id}` | Re-render a finished run from saved data — no new fetch |
| `GET /research` | History list (pinned first, then newest unpinned) |
| `GET /research/{run_id}` | The full case |
| `POST /research/{run_id}/pin` · `/unpin` | Idempotent pin toggle |

## 1.8 Hard guarantees (what makes the numbers trustworthy)

1. **No LLM produces a number.** Local models only classify (sentiment/themes, product names). Counts, proportions and scores come from deterministic code.
2. **No raw text kept.** Comments/snippets are transient and local; embeddings use derived attributes only; nothing goes to a hosted provider.
3. **Money stays in Brain 1.** `web_price_signal` and published supplier prices are never fed into any calculation.
4. **Every score is explainable.** `score_explanation` / `final_score_explanation` list each signal, its points and its reason.
5. **PI never calls CFO.** `product_intelligence` imports nothing from CFO; `backend/ceo` contains no SQL (architecture tests).
6. **Fails safe.** Any uncaught error sets the run to `FAILED` rather than leaving it stuck `RUNNING`.

## 1.9 Honest limits today

- **No demand data** (Google Ads keyword volume pending verification) and **no verified buyer reviews**.
- **No marketplace price or competition check** — selling price is the seller's own target band plus an unverified web-mentioned reference.
- `depth` (shallow/complete) is recorded but changes nothing.
- Supplier filtering is heuristic ("narrows the noise, does not eliminate it"); published-price extraction has not been validated against real supplier pages.
- Scoring weights (3/3/4, 40/30/30) are small integers chosen for exact arithmetic, not tuned on seller feedback.
- Category → fee-schedule mapping is raw text; a mismatch yields a named `UNAVAILABLE`, not a guess.
- Real-provider validation (live Tavily/YouTube/Ollama at multi-tenant load) and the Ollama extraction eval suite are **not done**; most tests use mock providers.
- Free-tier quotas and the rate limiter are single-process; a multi-instance deployment needs a Redis-backed limiter.

---

# PHASE 2 — The dashboard: what is shown and how

**Route:** `/dashboard/pi` (component `frontend/components/pi/PiShowcase.tsx`, print view `PiReportPrint.tsx`).
**Nature:** a **read-only showcase of research the CEO already ran**. There is **no form, no input, no "run discovery" or "supplier lookup" button**. The only buttons switch what is displayed, expand a block, or pin/unpin a report. Layout follows `docs/design/Design-Overviews/PI-Dashboard.svg`; colours come from configurable theme tokens (the app is dark-only today), and the sidebar/logo are untouched.

## 2.1 Page structure, top to bottom

```
┌────────────────────────────────────────────────────────────────────┐
│ Product Intelligence Workspace                   [ + New Discovery ]│  header
│ Opportunity discovery and supplier leads … · read-only              │
├────────────────────────────────────────────────────────────────────┤
│ ● Top Products from your Old Investigations                         │  strip (up to 3)
│  [1 Product · Score 82/100]  [1 …]  [1 …]                           │
├────────────────────────────────────────────────────────────────────┤
│ ● Recent Investigation: Earbuds  [Current]      [Pin] [Print / PDF] │  current investigation
│ Budget · Target Price · Marketplaces · Top 5 Shortlist · saved date │
│ ┌──────────── carousel ───────────┐ ┌──── Product Information ───┐ │
│ │ [prev] [ RANK #1 image ] [next] │ │ tiles · commentary ·        │ │
│ │       ● ○ ○ ○ ○                 │ │ evidence · supplier lead    │ │
│ └─────────────────────────────────┘ └─────────────────────────────┘ │
│ PI Recommendation for this investigation                            │
│ ▸ What this research could not provide                              │
├────────────────────────────────────────────────────────────────────┤
│ Old Investigation [Historical] [Pinned]   [Pin] [Expand Window]     │  one block per older report
└────────────────────────────────────────────────────────────────────┘
```

## 2.2 Section details

### Header
- Title **"Product Intelligence Workspace"** with the subline "Opportunity discovery and supplier leads from your saved research · read-only".
- **`+ New Discovery`** is a *link to the CEO Hub*, not a form — research is started only in chat.

### States
- **Loading:** "Loading your saved research…".
- **Error:** alert with the plain-language reason and a **Try again** button.
- **Empty (no saved research):** card "No saved research yet" explaining that research starts in a CEO conversation, with an **Ask the CEO to research products** button.

### Top Products from your Old Investigations
Up to three cards, one per earlier report: rank badge **1**, the report's top product title, `category · date`, and **Score NN/100**. Clicking opens that report. Shows "No earlier investigations yet" if none.

### Current Investigation (the selected report)
- **Header:** `Recent Investigation: {category}` (or `Investigation:` when an older report is selected) with a **Current/Selected** badge and a **Partial** badge for partial runs. Subline: `Budget: ₹… · Target Price: ₹… – ₹… · Marketplaces · Top N Shortlist · saved {date}`.
- **Controls:** **Pin/Pinned** toggle (`aria-pressed`) and **Print / Export PDF** (opens the print page in a new tab).
- Default is the latest report; `?run=<id>` deep-links a specific one (this is what the CEO's *View Detailed Research* link opens). Reports are cached client-side while switching.

### Rank carousel (left)
- The selected product's image in a framed card with a **Rank #n** badge, the product title, and *"image from {domain}"* attribution. The photo sits on a light backing so dark/transparent images stay visible.
- Faded neighbours (previous/next, "Prod #n") on wider screens; **‹ ›** buttons and a dot strip (active dot elongated) to move between the five.
- No usable image → "No clear product image found" (never a guess; a broken link falls back to the same).

### Product Information (right) — for the selected product
Header line: *title · category · score NN/100 · "opportunity candidate from public web signal"*.

**Four tiles:**

| Tile | Shows | When missing |
|---|---|---|
| **Selling price** | The seller's **target band** (`₹a – ₹b`), with the web-mentioned reference as "(not verified)" beneath; or the web reference alone, labelled "not verified" | "Unavailable — No target price stated" |
| **Cost price** | CFO **landed cost** per unit, labelled "From your confirmed supplier quote (CFO result)" | "Unavailable" + the exact thing to say to the CEO |
| **Net margin** | CFO margin if one exists | "Unavailable", with the price-and-fee **spread range** shown as an estimate "before product cost" |
| **Units to buy** | CFO figure, always followed by "a budget ceiling, not a forecast" | "Unavailable" + what quote detail is needed |

**Viewer / web commentary insights (not verified buyer reviews)** — two panels:
- **Positive** (green-tinted) with the sentiment split, e.g. "Viewer commentary positive 3/5", and the liked themes.
- **Defects to address** with the complaint themes.
- Empty panels say "No commentary themes were available" / "No complaint themes were found".

**Research evidence and trend signals** — the audit trail for the score:
- *Independent sources:* count, with one link per domain tagged by kind (web/video).
- *Video engagement (YouTube):* videos · views · comments, or why it is missing.
- *Search demand:* "unavailable — {reason}".
- *Score signal, {name}:* `points/max` with its reason, per signal.
- Footnote: "attention, not verified demand or sales".

**Supplier lead** — the best-evidenced lead: supplier name (link), `locality · source label`, phone, "MOQ published/not published", and, when present, **"Published price: ₹x per piece (the supplier's own page, {date}; not a quote)"**. A *Supplier Link ↗* button opens it (`rel="noopener noreferrer"`; only http/https links are rendered). A line says details are "not checked by Metrion". No lead → "No supplier lead was found for this product."

**Missing evidence:** a final line listing the product's named gaps.

### PI Recommendation block
- Heading **"PI Recommendation for this investigation ({category})"** with an **Ask the CEO for batch size →** link to the CEO Hub.
- **"Strongest opportunity: {title}"** + the reason (highest combined score across proxy score, commentary sentiment and supplier availability).
- "Consider them in this order. Nothing here is a purchase instruction."
- An ordered list, one entry per product: `{rank}. {title} · score` then **Supplier** (link, published price flagged "not a quote"), **Landed cost**, **Units / batch size** (a ceiling, or the exact CEO phrase that gets it), **Improve / watch** (complaints to address, or what customers like).
- Footer: estimates from public web signal; profit also needs a selling price after fees and tax.

### "What this research could not provide" (collapsible)
Always lists: verified buyer reviews, demand signal (with the Ads reason), marketplace price & competition — plus a *run completeness* entry for partial runs.

### Old Investigation blocks (one per other saved report)
- Header: **Old Investigation** `[Historical]` `[Pinned]`; subline `category · date · budget · target price · marketplaces`.
- **Pin** toggle and **Expand Window / Collapse** (the report is fetched only on expand).
- Expanded: up to **three product cards** (image, title, "Score NN/100 · Supplier: {name | no lead found}", **View Details ↗** which makes that report the current one at that rank), then a **Recommendation summary** line and a **Full Audit Report ↗** link to the print page.

## 2.3 Print / Save-as-PDF page (`/reports/pi/{runId}/print`)
Outside `/dashboard`, so there is no sidebar or header; black on white; **Print / Save as PDF** uses the browser's print (hidden when printing). Contents: report title bar (budget, target price, marketplaces, saved date, "partial run" if so, run id), the strongest-opportunity line, then one section per product — image + attribution, category and score, **research evidence**, **why it ranks here**, **liked** / **watch out for**, selling price, supplier lead with phone/website and published price, **CFO results** (or "Not calculated: they need a supplier quote you confirm with the CEO"), missing evidence — and a closing "what this research could not provide" with the standing disclaimers (opportunity candidates, viewer/web commentary, supplier leads unchecked, estimates not a purchase instruction).

## 2.4 Display rules the UI always follows

1. **Never a blank or zero for missing data** — the cell says "Unavailable" and why.
2. **Authoritative vs estimate never mix** — quote-based CFO figures are labelled as such; the spread is labelled an estimate.
3. **Wording:** "opportunity candidate", "viewer / web commentary", "published price (not a quote)", "budget ceiling, not a forecast". Never "trending", "bestseller", or an unqualified "review".
4. **Only the top five** are shown — the ~30 discovered candidates stay internal.
5. **Untrusted text is escaped**; external links are validated and `noopener noreferrer`.
6. **Accessible:** roles/`aria` labels on regions, `aria-pressed` on pin, `aria-expanded` on expanders, `aria-current` on the carousel dots, `role="alert"/"status"` on messages. A test asserts the page has no input elements.

## 2.5 Dashboard gaps (honest)

- Net margin and units show `Unavailable` until the seller confirms a quote through the CEO — by design, not a bug.
- Published supplier prices are rare and unvalidated against real pages.
- Print layout still needs a manual Chrome/Edge check (spec §10).
- The "Ask the CEO for batch size →" button navigates to the CEO Hub; it does not pre-fill the question.
- Pinned reports have no per-tenant cap yet (open question Q4).
