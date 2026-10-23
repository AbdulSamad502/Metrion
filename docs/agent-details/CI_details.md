# Competitor Intelligence (CI) — Agent and Dashboard Details

> Describes CI as **built in the repository on 2026-10-21** (branch `feat/ci-upgrade`). A readable companion to the spec, not a replacement:
> authority stays with `docs/specs/competitor-intelligence-agent.md` (V3, with its build record) and the manual guide `docs/ci-manual-test-guide.md`. Where this file and the spec disagree, the spec wins.

**One line:** CI helps a seller find competitors for their products, tracks the ones they choose, and reports price, stock and customer-sentiment changes — **only from evidence the seller sends** (screenshots) and leads from a licensed search API. CI **never fetches a competitor page**, never watches anyone "live", and **never computes margin or any money figure** — the deterministic engine (Brain 1) does that.

| | |
|---|---|
| Phase 1 | The agent — how it works and what it does |
| Phase 2 | The dashboard — what is shown and how it is displayed |

---

# PHASE 1 — The agent: how it works and what it does

## 1.1 What CI is (and is not)

| CI **is** | CI is **not** |
|---|---|
| A competitor **finder** (search leads via Tavily) and **tracker** (seller-chosen watchlist) | A scraper — no marketplace or competitor URL is ever fetched |
| A reader of **seller-submitted screenshots** (local vision model) with seller confirmation of risky fields | A live monitor — "monitoring" means re-reading stored evidence, stamped "as of <evidence date>" |
| A producer of **observed-fact deltas** (a price moved from X to Y) | A margin or profit calculator — no fee, tax, cost or margin figure originates in CI |
| A source of **Layer 1 alerts** (observational only) | A chatbot — it has no seller-facing voice; the CEO speaks for it |
| Reached **only through the CEO Hub** | A direct seller input surface — the dashboard is read-only |

**The arithmetic boundary:** CI may compute *deltas over its own observed facts* (a price change between two confirmed screenshots, and the observed "effective price" = listed − visible discount). Everything else money-related — price band, price positioning, repricing scenarios, the buyer's total, any margin — is computed by Brain 1 and rendered unchanged with its `engine_result_ref`.

## 1.2 Where CI sits

```
Seller ─► CEO Hub chat ─► fixed CEO action ─► CI ─► structured result ─► CEO ─► Seller
                                               │
                                               └─► Brain 1 (price band / positioning / effective price) — shared service
```

- **Star topology:** CI is never called by or calling another agent. Cross-agent hand-offs (pricing → CFO, listing themes → CMO) are brokered by the CEO.
- **No CI chatbot:** when CI needs something (a confirmation, a missing field) it emits a structured `InfoRequest`; the CEO phrases the question; the answer returns via the fixed tool `ci.confirm_field`.
- **Fixed dispatch:** the CEO maps what the seller says to a hand-registered action; an LLM never chooses which code runs.
- **Permissions:** `agent.ci` (+ `agent.ceo` for chat); discovery additionally goes through the stored-plan approval workflow. Tenant isolation: every table has `tenant_id` under `FORCE ROW LEVEL SECURITY`; no client-supplied tenant; a foreign id is a 404.

## 1.3 What the seller can ask (CEO actions)

| Seller says / does | CEO action | What CI does |
|---|---|---|
| "Find my competitors" | `ci.discover_competitors` | Asks which business categories to search, runs Tavily discovery (needs plan approval; the seller's search terms leave Metrion), returns the **top 15** leads |
| Ticks leads / "track 1 and 3" | `ci.competitor_approve` | Moves leads to the tracked list (cap-checked) |
| "Reject 2" | `ci.competitor_reject` | Stores the decision; a rejected lead is not re-surfaced |
| "Track <link>" | `ci.competitor_add` | Adds a marketplace link (allow-listed hosts only); several links are echoed back and need a "yes" |
| "Stop tracking X" | `ci.competitor_remove` | Soft-removes (history kept); re-adding restores it |
| Attaches a screenshot | `ci.evidence_intake` | Quality gate → duplicate check → local vision read → match to a competitor → hold risky fields for confirmation |
| Answers a question | `ci.confirm_field` | Stores the seller's answer with provenance |
| "How are my competitors doing?" | `ci.monitor_competitors` | Re-evaluates stored evidence; no outside call |
| "What do customers complain about?" | `ci.review_findings` | Reads saved review themes with the sample size |
| "Should I lower my price?" | `ci.request_price_scenario` | Hands to the CEO to compose with the CFO's figures; CI states no margin |
| Clicks a dashboard link | per `CeoEntryContext` | CEO re-reads the finding/competitor **by id** server-side |
| "Quiet hours …", "alert me at 5%" | `ci.threshold_set` / alert settings | Updates alert settings, echoes them back |
| `ci.seller_product_set` | seller product facts (category, price, keywords…) | Stored `SELLER_ENTERED`, echoed back |

## 1.4 The core pipeline, step by step

### Step A — Discovery (find leads)
- **Category-driven:** the CEO first asks *which categories from the seller's business profile* to search (one, several or ALL; a product name still works). One search runs per chosen category and the results are merged into one ranked list, each lead tagged with its category.
- **Provider:** **Tavily** behind a `SearchProvider` interface (a mock exists for tests). Only Tavily *leads* come back — never marketplace facts. Every returned URL must be on an allow-listed marketplace host (Amazon, Flipkart, Meesho and their official short links); others are dropped and recorded. Results are canonicalised to a single listing and de-duplicated.
- **Privacy:** queries are built from the seller's product terms after a privacy filter; the plan card says the terms leave Metrion. Per-run query budgets and a daily cost cap apply. A provider outage yields an honest `FAILED`/`PARTIAL` run, never "no competitors exist" and never a stale cache dressed as fresh.
- **Lead quality (`lead_quality.py`):** books, keyword-dump and too-short titles are never surfaced; recognisable brands rank first, then any brand, then title match; at most 2 leads per brand. This removes plainly-not-a-competitor leads but cannot prove a business is genuine or that a listing still exists (nothing is fetched).
- **A search snippet is a lead, never a verified observation:** any price/stock/rating read from a snippet is shown only on the lead as "reported by search — unverified" and is statically barred from every observation path (deltas, bands, alerts, hand-offs).

### Step B — Identity, relationship and relevance
- **Identity** answers *"is this the same sellable product as mine?"* → `EXACT_MATCH`, `LIKELY_VARIANT`, `UNCERTAIN`, `NOT_A_MATCH`.
- **Relationship** answers *"how does it compete with mine?"* → `SAME_PRODUCT`, `VARIANT`, `DIRECT_COMPETITOR`, `FUNCTIONAL_ALTERNATIVE`, `UNRELATED`, `UNKNOWN`. Derived deterministically from identity and the scored axes. (This split fixed a real defect: every other-brand competitor used to be auto-rejected as `NOT_A_MATCH`. Now `NOT_A_MATCH` proceeds to scoring and is rejected only if the relationship is `UNRELATED`.) At discovery, with category unknown, a deterministic **title-token overlap** may name a *provisional* relationship; low overlap is `UNKNOWN`, never "different".
- **Relevance:** a locked **eight-axis** score (each axis 0/1/2, max 16 → `HIGH`/`MEDIUM`/`LOW`); every unknown axis scores 0, never guessed upward. A score before any evidence is labelled provisional. The band is never shown without its breakdown.
- Relevance, identity, relationship, evidence confidence and freshness are **five separate attributes**, never merged into one badge.
- Only `SAME_PRODUCT`, `VARIANT`, `DIRECT_COMPETITOR` or `FUNCTIONAL_ALTERNATIVE` leads may fill the Recommended top-15; others stay visible in lower tiers.

### Step C — Choosing what to track (the watchlist)
- The CEO shows the **top 15** numbered, best match first, plus a check-box **pick card**, with the seller's free slots. The seller may pick up to the free slots; a pick that doesn't fit adds nothing and says so.
- **Cap: at most 5 active tracked competitors per seller**, across marketplaces (`max_active_competitors`, else `CI_DEFAULT_WATCHLIST_LIMIT`, else 5), enforced atomically under a per-tenant lock. Stopped competitors and pending leads don't count. A full list asks the seller to stop one first.
- States: `CANDIDATE` → `APPROVED` (tracked, **"awaiting evidence"** until a screenshot arrives) / `REJECTED` / `REMOVED` (soft, stored as archived; restorable with history).
- Every action writes an append-only audit event.

### Step D — Screenshot evidence intake (the heart of CI)
```
CEO Hub attachment → quality gate → duplicate check → local vision extraction
   → match to a competitor → confirm risky fields → store evidence + snapshot → finding(s) → CEO explains
```
1. **Quality gate (before any model):** type checked by magic bytes; size and minimum pixels; blur/legibility; "looks like a listing or reviews page". Rejections name the reason ("too blurry to read the price"); no snapshot is stored.
2. **Duplicates (per tenant):** identical bytes → "I already have exactly this screenshot"; a near-identical image is stored as a possible duplicate and creates no snapshot unless the seller says it's a fresh capture.
3. **Extraction:** a **local Ollama vision model** reads structured fields (price, MRP/discount, delivery, fulfillment, rating, review count, offers with conditions, stock, listing text). Text visible in the image is data, never instructions. Nothing is sent to a hosted provider.
4. **Matching:** the seller names the competitor, or the title/URL is matched to a tracked one, else the CEO asks. **A screenshot of an untracked competitor is never auto-added.**
5. **Risk-based confirmation:**

| Field | Behaviour |
|---|---|
| **Consequential** (price, effective price, stock change, "exact match") | From vision → **held `PENDING`** until the seller confirms; excluded from engine inputs, deltas, bands, comparisons and alerts. Seller-stated values are verified on entry |
| Non-consequential, high confidence | Stored as read, shown, correctable, never prompted |
| Non-consequential, medium/low | Stored with its confidence label, not asked |
| Missing | `UNKNOWN` with a reason; asked only if needed |
| Conflicting across screenshots | The seller picks or states the value |
| Declined | Stays `UNKNOWN`; never enters a consequential path |

   A seller-stated value always beats the extracted one (the original is kept in the audit trail). An unanswered question expires (default 7 days).
6. **Why so cautious:** the small local vision model measurably misreads prices (the spec records ~13/31 exact on its own eval, and it once invented a ₹260 discount on a watch). Confirmation is what keeps wrong numbers out of every downstream calculation.

### Step E — Change detection, findings and alerts
- A second confirmed screenshot of the same competitor creates a **verified observed-fact delta** (e.g. "price down 10.75%, ₹279 → ₹249"; or a stock transition). Each important result becomes a persistent `ci_finding` with a stable id, tied to its evidence records (evidence date, confidence, sample size, confirmation state). A finding with no evidence is not displayable.
- **Layer 1 alerts only:** observational ("Competitor X dropped price 8%"), stamped with the evidence date, never mentioning margin or contribution. Any financially-aware alert is composed by the CEO with the CFO, not by CI.
- **Hardening:** one alert per (competitor, finding type, direction); a repeat fires only on a new valid snapshot whose change versus the *last alerted value* again meets the threshold. **Quiet hours** (tenant timezone, else India time) *hold* alerts, never drop them; at delivery the evidence is re-checked and a now-stale alert becomes a freshness request instead. Thresholds (price % between 1 and 50, availability) are configurable tenant-wide and per competitor through chat. Freshness reminders go through the CEO.
- A housekeeping scheduler (default every 15 minutes) re-reads stored data only to release held alerts and compute reminders; it fetches nothing.

### Step F — Monitoring and freshness
`ci.monitor_competitors` re-evaluates stored evidence per competitor: freshness, verified deltas, open alerts, review findings, open questions. **No outbound call of any kind.** The report is stamped with the time it ran and each competitor's evidence date; the CEO must say "as of <evidence date>" and may never say "live", "real-time", "continuously" or "I'm tracking". Stale or missing evidence produces a request for a fresh screenshot.

| Source | Marked stale | Hard ceiling |
|---|---|---|
| Screenshot price / availability | 24 h | 7 days — after that the current answer is unavailable and nothing alerts |
| Screenshot rating, review count, listing content | 7 days | — |
| Review themes | 30 days | — |
| A seller confirmation | inherits the age of the evidence it confirms | as above |
| Search lead | never fresh — always unverified | — |

### Step G — Comparison and "what a buyer pays"
Compared where observed: selling price, MRP and discount, effective price, delivery charge, fulfillment, rating, review count, visible offers. **Offers carry their condition**; a card/coupon/first-order offer is *named but not subtracted*. Free delivery counts as an observed zero only when stated. Every unobserved value is `UNKNOWN` with a reason — never blank or zero. Brain 1 supplies:
- **Effective price / buyer total** (`compute_competitor_effective_price`): listed price after confirmed discounts, and with delivery.
- **Price positioning** — rupee gap plus percentage gap with a labelled denominator (relative to the competitor's price and to the seller's own price).
- **Price band** (`compute_price_band`): Q1, Q3 and typical low/high from verified competitor prices, only when a configured minimum number of verified prices exists and only from band-eligible relationships (`SAME_PRODUCT`, `VARIANT`, evidence-verified `DIRECT_COMPETITOR`; `FUNCTIONAL_ALTERNATIVE` is shown but excluded).

CI computes no quartile, fence or outlier itself.

### Step H — Review insight (customer voice)
Only from a **seller-submitted reviews-tab screenshot** (or seller-confirmed text). A local model derives sentiment, complaint themes and positive themes; **raw review text is held in memory only and never persisted or sent to a hosted model**. Themes are always reported with the sample ("from N reviews read") and a minimum sample (`review_finding_min_sample`, adopted as 10) before a finding counts as significant. With no review evidence, the CEO gives deterministic review-page links built from listing links the seller already supplied, says no page was read and that a search snippet is not a review, and asks for a screenshot. Nothing is scraped, searched or invented. A bounded cited snippet may be kept up to 90 days (marked "source evidence expired" after).

### Step I — Cross-agent hand-offs (all brokered by the CEO)
- **CI → CFO:** a pricing decision starts the finance flow pre-filled from verified data (the competitor's verified price beside a named target, the seller's product price, remembered GST basis) and asks only what's missing; no cost is invented. CI states no margin.
- **CI → CMO:** for listing-writing actions the CEO reads the seller's fresh (≤30 days) `competitor_listing_insight` rows, freezes their ids into the plan, and the CMO uses derived single words as market context with an originality check; competitor brand words, copied runs and search-volume/ranking claims fail it. Competitor prices are never passed. No insight / stale / no `agent.ci` → the CMO runs independently with a one-line note.

## 1.5 Data CI stores (selected)

| Table | Holds |
|---|---|
| `competitor_url` | A tracked competitor (marketplace, status, per-competitor alert overrides, soft-removal fields) |
| `competitor_evidence` / `competitor_snapshot(_field)` | The seller's screenshot record, extracted fields with confidence and source, merge/override rules |
| `competitor_price_event` | Verified deltas, with dedup / quiet-hour suppression reasons |
| `competitor_review_insight` / `competitor_listing_insight` | Derived themes (no raw text) and derived listing attributes |
| `ci_candidate` / `ci_search_query` / `ci_search_result` / `ci_discovery_run` | Discovery leads, queries sent (audit), raw lead rows, run state |
| `ci_finding` | Stable, tenant-scoped findings the dashboard and Ask-CEO resolve by id |
| `ci_info_request` | Open questions awaiting the seller |
| `ci_alert_state` / `ci_held_alert` | Dedup memory and alerts held by quiet hours |
| `ci_event` | Append-only audit stream (evidence received/rejected/duplicate, confirmations, competitor decisions, discovery, alerts, monitor runs) — never raw review text |
| `ci_tenant_config` | Thresholds, quiet hours, staleness reminder, watchlist limit, recommended-candidate count (15) |
| `seller_product_profile` | The seller's own product baseline, `KNOWN`/`UNKNOWN` per field, `SELLER_ENTERED` wins over derived |

## 1.6 API surface (selected)

`GET /api/v1/ci/workspace` (the dashboard read), plus the existing `/ci/summary`, `/competitor-urls`, `/market-overview`, `/comparison`, `/discovery-runs`, snapshots and events routes. The dashboard calls only reads. Evidence, confirmation, tracking and settings all go through CEO chat actions.

## 1.7 Hard guarantees

1. **No fetching:** CI makes no outbound request to any competitor or marketplace; Tavily gives leads only.
2. **No money from CI:** no margin, fee, tax, cost or band arithmetic; Brain 1 owns it and CI cites `engine_result_ref`.
3. **Unconfirmed = unused:** a vision-read consequential field never reaches an engine input, delta, band, comparison or alert until the seller confirms.
4. **Honest currency:** every statement is "as of <evidence date>"; stale or missing evidence is asked for, not papered over.
5. **Discovery is not intelligence:** a lead is never compared, mined or alerted on as if it had evidence.
6. **No raw review text** stored or sent to a hosted model.
7. **Everything is auditable:** structured append-only events with actor, tenant and CEO-investigation link.
8. **Deliberately not built (owner decision):** competitor sales prediction, speculative competitor margins, automatic repricing, market-share estimates, continuous scraping.

## 1.8 Honest limits today

*(From the spec's V3 build record, updated through 2026-10-21. I did not re-run any tests.)*

- **Local vision misreads prices** (Q7/Q18); real-seller-screenshot accuracy is unmeasured. This is why confirmation is mandatory.
- **WhatsApp** is a declared placeholder returning `CHANNEL_NOT_AVAILABLE`.
- **No real-LLM narration eval has been run**; the CI narration cases (`CI-NR-01..11`) exist but never ran against a model.
- **Production validation not done:** DPDP review (V15), Tavily terms and per-tenant cost ceiling (V16), measured Tavily cost per discovery run, V17–V18.
- **Lead quality is heuristic:** token overlap misses true competitors that share few words with the seller's title; own-website competitors aren't searched.
- **Watchlist cap of 5 is a decision of record**, but subscription-plan limits are still undecided.
- The seven-day ceiling and 15-minute scheduler cadence are defaults, not tuned.
- **Branch state:** the V3 work was recorded as built and uncommitted on `feat/ci-upgrade`; the git log shows a V3 commit (`e1cc9f3`) but I did not verify whether every later round-4 change is committed.
- **Known test failures outside CI:** three Product Intelligence Tavily-fake tests and one frontend scope test failed in the spec's last full run; they predate or are independent of this work.
- The ownership of DB grants matters: migration `20261014_0021` re-grants seller-editable alert columns; databases upgraded out of order need the backend migration head re-run.

---

# PHASE 2 — The dashboard: what is shown and how

**Route:** `/dashboard/competitors` (`frontend/components/ci/CiDashboard.tsx`, data from `GET /ci/workspace`, plus the market band per product).
**Nature:** a **read-only visual workspace** over what CEO–CI conversations already produced. There is **no form, no input, no upload and no control that changes data**. Every action is a **link into the CEO Hub** carrying structured ids (never content). Technical identifiers are hidden by default. Original logo and theme tokens are kept (dark theme only today). Nothing is estimated and there is no sample data.

## 2.1 Page structure, top to bottom

```
┌──────────────────────────────────────────────────────────────────────┐
│ ( Product A ) ( Product B ) ( Category: … )   [Find competitors]     │ header
│                                               [Track a competitor]   │
├──────────────────────────────────────────────────────────────────────┤
│ What to do next — <deterministic sentence>          [ one action ]   │ next-step bar
├──────────────────────────────────────────────────────────────────────┤
│ [Competitors tracked] [Need fresh evidence] [Verified changes] [Customer insights]  │ KPI row
├──────────────────────────────────────────────────────────────────────┤
│ Your competitors                                                     │
│   Tracked competitors (table)  ·  Found, awaiting your decision      │
├──────────────────────────────────────────────────────────────────────┤
│ Where your price stands                                              │
│   Where your price sits (Q1/Q3/typical)  ·  Insights and next steps  │
├──────────────────────────────────────────────────────────────────────┤
│ What changed:  Verified changes  ·  Freshness                        │
├──────────────────────────────────────────────────────────────────────┤
│ Evidence and reviews: Waiting on you · Review insights · History     │
└──────────────────────────────────────────────────────────────────────┘
```

## 2.2 Section details

### Header
- **Product selector:** one pill per seller product (`aria-pressed`); picking one reloads the workspace for it and fetches its market band. A selection like `category:<name>` represents competitors tracked for a business category rather than one SKU. "No products yet" if none.
- **Two CEO shortcuts:** **Find competitors** and **Track a competitor** — links that open the CEO Hub with a pre-composed message the seller sends. They never run anything.
- Role without CI access sees a clear "Your role does not include Competitor Intelligence" state; load errors show a retryable alert.

### "What to do next"
One code-written sentence from the stored counts, with one button: no tracked competitors → *Find competitors*; pending questions → *Confirm in chat*; competitors with no recent screenshot → *Verify prices*; otherwise → *Compare my price*.

### KPI row (four cards; "Not available" rather than 0 when empty)
| KPI | Shows | Hint |
|---|---|---|
| Competitors tracked | `N of 5` (watchlist usage) or count | "List is full: stop tracking one to add another" / "K with a verified price" |
| Need fresh evidence | count (warning colour when >0) | "Send the CEO a new screenshot" / "All evidence is recent" |
| Verified changes | count | "Price or stock, from confirmed screenshots" |
| Customer insights | count | "From review screenshots you sent" |

### Empty state (new seller)
A calm explanation of what CI does ("Nothing here is estimated or sample data") with a *Find competitors* button. The sections below appear only once there is something tracked or any candidate.

### Your competitors
**Tracked competitors table** — columns:
| Column | Content |
|---|---|
| Competitor | Brand-first cleaned name and marketplace |
| Price | The **verified** listed price with ▼/▲ % since the previous screenshot; otherwise "Awaiting your confirmation" or "No current price" |
| What a buyer pays | Brain 1's effective price "after discounts", "…with delivery" (or why the total is unavailable), and a line naming offers not counted (card/coupon conditions) |
| Match | Relevance as Low / Medium / High (tooltip: relationship class); "Not scored" if unscored |
| Last evidence | Date of the screenshot + freshness label |
| Status | Verified / Unverified badge |
| Actions | **Verify price** (or **Update price**) and **Stop tracking** — both link to the CEO |

**Found, awaiting your decision** — discovery leads (title or "Direct competitor on Amazon"-style label, marketplace, relationship, "Open listing" link, match band, always "not verified yet") each with **Track this**. If none, the empty text reports the last discovery's state honestly (failed / partial / complete) — "nothing found" is never presented as "no competitors exist".

### Where your price stands
- **Where your price sits:** Q1, Q3, Typical low, Typical high — computed by Brain 1 from verified competitor prices. When unavailable: "No price band yet" with the engine's reason and the minimum number of verified competitors needed. For a category-level selection it explains the competitors are tracked for a category and offers *Compare my price* (the seller states a price to the CEO). Verified competitor prices are also listed as chips (`Competitor · ₹price`).
- **Insights and next steps:** up to six findings (the stored finding text), each with "N screenshot(s) behind it · confirmed by you" and an **Explain this** link that passes the stable finding id.

### What changed
- **Verified changes:** per change — competitor, "price down/up N%" or "stock …", the rupee change, "from the screenshot of <date>", and **Explain this**. Empty state: appears only after a second confirmed screenshot. The subtitle states competitors are not watched between screenshots.
- **Freshness:** each competitor with the date of its latest evidence (or "no screenshot yet") and a Fresh / stale badge.

### Evidence and reviews
- **Waiting on you:** each unanswered confirmation ("Confirm the price") with its expiry and a **Confirm in chat** link.
- **Review insights:** per competitor — "N reviews read · date · confidence", **Complaints:** and **Praised:** theme lists, plus **Add more reviews** and **Explain this**. If the sample size isn't stated it says so.
- **History:** a per-day activity summary (e.g. "Screenshot received × 2", alerts, confirmations) rendered from the stored event stream, not recomputed in the browser.

## 2.3 Display rules the UI always follows

1. **No invented data and no zeros for missing data** — a missing value says it is missing and why ("Needs a screenshot", "Awaiting your confirmation").
2. **"Verified" means** seller-screenshot evidence, consequential fields confirmed, within the freshness ceiling. Everything else is "Unverified" with the reason; search leads are always "not verified yet".
3. **Every figure traces:** prices/deltas come from stored evidence; band, gap and buyer-total come from Brain 1; findings resolve to their evidence.
4. **Stale evidence is shown, flagged with its date** — never hidden and never presented as current.
5. **Relevance is never a bare number:** shown as Low/Medium/High; the full breakdown lives in details.
6. **No competitor or marketplace product images** are shown (insights only).
7. **Honest wording:** "as of <date>", "from the screenshot you sent"; never "live" or "tracking in real time".
8. **Accessible and themed:** grouped buttons with `aria-pressed`, a labelled table, `role="alert"` for errors, skeleton loading, theme tokens (dark only today).

## 2.4 What was removed on purpose
Tabs (Overview / Competitors / Changes / Evidence), the "Ask CEO" button label, the Monitor button, raw relevance scores and `UNAVAILABLE` wording (now "Needs a screenshot"), every form (URL, evidence upload, manual entry, seller-product profile, threshold) — all of that now happens in the CEO chat.

## 2.5 Dashboard gaps (honest)

- The sidebar/logo shell was not visually re-verified after the dashboard replacement (the dashboard itself was checked at desktop and mobile widths).
- I read the component code; I did not run or click-test the dashboard. The spec also mentions category-grouped competitor display ("Category: <name>") that I did not locate in `CiDashboard.tsx` itself — it may be handled in the workspace data builder.
- A price-history chart is specified (D18) but I did not see one in the current component; the market band is shown as four numbers.
- KPI "Your price vs market median" in the spec's layout table is not a separate card in the current component.
- Plan-based watchlist limits remain undecided; the "N of 5" display reflects the current default.
