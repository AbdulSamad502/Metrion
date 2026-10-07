# Metrion — Product Intelligence Agent (PI) Specification

**Status:** Phase 1 (standalone package) built and reviewed. Phase 2 partially built — plain HTTP routes/permission/entitlement layer only; CEO Hub dispatch and the CFO batch-size handoff are designed but **not implemented** (§6.8). Phase 3 (dashboard) built as an honest test harness against the real Phase-2 routes.
**Prerequisites:** `deterministic-engine.md` (all financial math, incl. §5.13.2 `estimate_product_feasibility`) · `data-foundation.md` (provenance, confidence) · `auth.md` (permissions, execution paths) · `competitor-intelligence-agent.md` (shared RLS/repo/direct-path conventions — **no longer** a shared-fetch-posture reference, since PI no longer fetches marketplace pages at all; see §0/§6.2)
**Pending:** Brain 2 spec (unwritten) · entitlement, metering and billing spec (unwritten)

**PI researches. It never calculates.** Every financial figure — feasibility (wired, 2026-10-01, see §6.7), and (once Phase 2's CFO handoff is built) batch size — comes from Brain 1. PI normalises observations into provenance-tagged inputs and renders what the engine returns.

**V1's discovery design was revised after this spec was first written.** An extended legal/product-fit review ruled out every marketplace-touching discovery path (Amazon PA-API, Flipkart/Meesho on-demand fetch, paid vendor scraping, the Flipkart Affiliate API, IndiaMART bulk search) — see §0 and the revised C2. PI's V1 discovery is now fully marketplace-agnostic: it finds candidate product **opportunities** from open web and video signal (Tavily + YouTube), never from an observed marketplace listing. This is a foundational change from the original design this document described, not a patch — §0, §1 (C2/C5/C6/C14), §2, §5 and §6 below reflect the revised, actually-built design; where the original marketplace-fetch language survives elsewhere in this document it is superseded.

---

## 0. Cross-cutting discipline: honest labeling, never "verified trending" or "reviews"

Seven rules apply everywhere in this spec — every module, every schema field, every narrated
sentence — not just in one section. Listed once here so they don't drift into a single place
and get forgotten elsewhere. These extend D1's pre-existing "proxy score, never units sold"
precedent (C15) into a full labeling discipline, not a new category of rule.

**(a) Candidates are "opportunity candidates," never "trending products" or "bestsellers."**
PI has no sales-rank, no marketplace bestseller list, no verified-purchase data — its signals
are web mentions and video engagement. Every user-facing surface uses language like *"candidate
opportunity,"* *"signal-based estimate,"* or *"worth investigating"* — never *"trending,"*
*"bestseller,"* or *"popular right now"* stated as fact. Enforced structurally by
`product_candidate.opportunity_label` (a `CHECK` constraint fixing it to the single value
`'CANDIDATE_OPPORTUNITY'`, never a caller choice) and by `reasoning/narration_safety.py`'s
dedicated check on Brain 3's free-text output, where the architecture can't enforce it by
construction.

**(b) Three distinct evidence categories, never blurred into one "reviews" concept:**
- **Editorial image** — `product_candidate.image_url`, Tavily-sourced, always rendered with
  visible *"image from [image_source_url domain]"* attribution, never implied to be a
  marketplace listing photo.
- **Viewer/reader commentary** — sentiment and theme tags derived from YouTube top comments and
  web-article text (`review_insight/text_extraction.py`), tagged with a required
  `product_review_insight.insight_source_type` (`YOUTUBE_COMMENTARY | WEB_EDITORIAL`). The word
  "review" is never used unqualified for this data — `narration_safety.py`'s check 3 enforces
  that every narrated occurrence of "review(s)" is qualified by "viewer" or "web" nearby.
- **Verified buyer reviews** — real marketplace customer review data. **Not available in V1**
  (no marketplace access). No PI surface shows this category at all; it is not merged into the
  commentary category above.

**(c) Estimates are never upgraded to "confirmed" anywhere downstream.** A
`product_feasibility_estimate` (`estimate_ref`, `cogs_basis: STATED|UNKNOWN`) is an estimate at
every hop it travels. Once Phase 2's CFO batch-size handoff exists (§6.8, currently
unimplemented), the same discipline must extend through it — see the handoff-safety rules
recorded there now, ahead of that code being written.

**(d) Every candidate's score is explainable, not a black box.** `score_explanation` (Stage 1)
and `final_score_explanation` (Stage 4) must be complete enough that a seller or auditor can see
exactly which signals fired, which didn't, and why — never just a bare number (§6.3).

**(e) Missing data is named, never hidden or defaulted.** The project's hard rule
(`UNAVAILABLE`, never a silent default) applies throughout — `demand_signal` is always present
on every `product_candidate` row but currently always `UNAVAILABLE`-populated (Checkpoint 0's
finding, §1 C2), never silently dropped from the schema or the explanation.

**(f) The full discovery list and the final shortlist are two distinct, explainable stages, not
one score reused twice.** Stage 1 (`discovery/ranking.py`) ranks every discovered candidate on
engagement + source-diversity signal alone. Stage 4 (`discovery/shortlist_scoring.py`) is a
later, independent pass over the post-review/post-supplier-lookup shortlist, combining proxy
score + review-sentiment quality + supplier availability into its own
`final_score_explanation` — never a copy or re-export of Stage 1's number (§6.3).

**(g) A web-mentioned price is a rough reference, never a verified market price.**
`product_candidate.web_price_signal` (Tavily-sourced) is an average/range of prices *mentioned
in web content*, with sample count, most-recent-mention date and an explicit disclaimer always
shown alongside it. It is never fed into `estimate_product_feasibility` or any Brain-1
calculation — `discovery/candidate_synthesis.py` (the module that computes it) has no import of,
or dependency on, `calc_engine` at all, which is itself part of the enforcement (§6.7, AC-new).

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Marketplaces:** Amazon, Flipkart and Meesho, all three at V1 — for fee-schedule/feasibility purposes only (`candidate_marketplaces`, §5). No marketplace is fetched from or scraped. | readiness §1 — Marketplaces; revised per §0 |
| C2 | **Discovery sources — revised, marketplace-agnostic.** PA-API 5.0 (deprecated, Creators API needs 10 qualifying sales/30 days), Flipkart/Meesho on-demand fetch (same scraping risk CI itself pivoted away from), paid vendor scraping (Oxylabs/Bright Data, rejected for cost), the Flipkart Affiliate API (sign-up restricted to individual creators, license scoped to referral use not research) and IndiaMART bulk directory search (no third-party API, ToS bars automated harvesting) were all **ruled out for V1**. **Confirmed V1 source stack: Tavily** (web search + `include_images=True`, 1,000 credits/mo free, own index) **and the YouTube Data API v3** (review/unboxing video view counts, comment counts, thumbnails; 10,000 units/day free). A third source, **Google Ads API's `KeywordPlanIdeaService`** (real search-volume-range demand data), was planned but **dropped at Checkpoint 0 (2026-09-30)**: it requires Google Ads "Basic" developer-token access, which requires brand verification (owned domain + Google Cloud project) Metrion doesn't have ready yet — no spend requirement, so not a permanent block. The schema field (`product_candidate.demand_signal`) is kept and always `UNAVAILABLE`-populated with the reason named, never removed or silently omitted; `ranking.py`'s Stage 1 score composes from `engagement_signal` + `source_diversity` only until Ads access is added later. | plan `replicated-whistling-russell.md` Context, Checkpoint 0 |
| C3 | **Niche discovery is a paid, on-demand research run.** Structured niche + budget input (`niche_brief`); user-triggered; bounded by `candidate_cap` (default 30); results label estimates, sources, timestamps and unavailable data. | readiness §1 — Niche discovery |
| C4 | **PI discovers suppliers; it never ranks them.** Output is a qualified lead list with contact details. CFO ranks, from seller-supplied quotes only. Confirmed in the built code: `supplier/` and `direct_path/pi_supplier_lookup.py` persist leads with no score/rank field. | readiness §1 — Supplier ownership |
| C5 | **Supplier sources:** Google Places API (New) primary — a cheap free/Pro-tier split, `search_place_ids` (free ID+name only) used broadly, `enrich_place` (paid phone/website/address) called only for the seller's chosen top-5-or-fewer at `pi_supplier_lookup.py` — plus **Tavily** as a secondary web-search source for suppliers Places doesn't list, filtered through `_looks_like_supplier`/`_has_supplier_signal` heuristics (excludes retail storefronts, listicle/review articles, "buy X online" framing; boosts results carrying an explicit manufacturer/wholesale/distributor signal word). **Extended 2026-10-01** after a second live run surfaced two more non-supplier shapes slipping through: social-media posts (`_SOCIAL_MEDIA_DOMAINS` — Instagram/Facebook/Twitter-X/Pinterest/TikTok/YouTube/Reddit/Threads/LinkedIn, none of which carry contact info at all) and the candidate's own brand selling direct-to-consumer on its own domain (`_is_candidates_own_brand_domain` — e.g. newbalance.com for a "New Balance 1080v15" candidate; matched via collapsed-token prefix against the domain's own first label, not a hardcoded brand list). Still a heuristic, not a guarantee, same "narrows the noise, does not eliminate it" honesty `narration_safety.py` already models elsewhere. **IndiaMART user-initiated single lookups only** stays in the schema's `source` enum (`INDIAMART_LOOKUP`) but is **not implemented** — no bulk contact harvesting (DPDP exposure), deferred pending an actual commercial partnership. | OP2(b); plan Context "Supplier discovery is unaffected"; real code in `supplier/google_places_client.py`, `direct_path/pi_supplier_lookup.py` |
| C6 | **Allowlists are purpose-scoped — revised.** There is no fixed marketplace-domain allowlist for discovery any more (no marketplace is fetched at all, §0/C2) — Tavily and YouTube are themselves the licensed, purpose-scoped sources, not domain-restricted crawlers. Supplier discovery: Google Places, Tavily (filtered per C5), IndiaMART (schema-only, not implemented). Trends: **no longer PI's allowlist at all** (C14). | revised from OP2 |
| C7 | **Facts, not expression — with a confirmed, deliberate exception for `candidate_title`.** No *marketplace* listing copy or product description is ever persisted (unchanged — PI has no marketplace access to copy from in the first place). `product_candidate.candidate_title` **is** a real, lightly-cleaned title text (not a word-frequency synthetic mashup, and not a derived-attribute-only placeholder) — copied from the single best-representative Tavily/YouTube source in a grouped candidate (`candidate_synthesis.py`'s `_select_representative_title`), or the literal product name a local-Ollama extraction pass found named in that source's own text (`discovery/product_extraction.py`). This is a confirmed reversal of this spec's original "never a verbatim title" caution (§2 old-D5): that caution fit CI's marketplace-listing-copy concern specifically, which doesn't apply here — these are general web article/video titles, already attributed via `source_urls`, not scraped marketplace listings passed off as a seller's own copy. Only the *embedding* path (`embedding/embed.py`) still embeds derived attributes only, never the title text (D5 below, unchanged for that one purpose). | real code: `candidate_synthesis.py`, `embedding/embed.py`; was readiness §1 — Review handling |
| C8 | **No image rehosting.** `product_candidate.image_url`/`image_source_url` are Tavily- or YouTube-sourced hotlinks, rendered via a plain `<img>` tag (no `next/image` allowlist fits arbitrary domains), always with visible *"image from [domain]"* attribution (§0b). **Image-to-candidate attribution (corrected 2026-10-01 against the real Tavily API) requires either an exact `source_url` match to one of the candidate's own contributing results, or full containment of the candidate's own name tokens within the image's title+description text, with a minimum of 2 significant identity tokens required** — a candidate whose name reduces to a single generic token (e.g. short brand abbreviations like "UA"/"HB" both fall below the 3-character significance floor, leaving a name like "UA HB Runner 2" as just `{"runner"}`) never gets a Tavily image via this path, confirmed as a real live-data bug (a 1-token identity trivially contained in almost any running-shoe image description, misattributing an unrelated brand's photo) and fixed with a hard floor, not a loosened heuristic. **A second, free fallback (added 2026-10-01): when no Tavily image matches, a grouped YouTube video's own `thumbnail_url` is used instead** — an unambiguous, directly-linked official image for that exact video (no containment heuristic needed, since the video is already grouped into the candidate via the same extraction/Jaccard match as every other signal), `image_source_url` set to the video's own watch URL so attribution honestly renders "image from youtube.com." A candidate matching neither path gets no image at all, never a misattributed one — Tavily-image coverage alone stays low given the real API's limitations (no genuine per-result page link), but the YouTube fallback meaningfully improves overall coverage at zero added cost (thumbnails are already fetched as part of the normal video search call). | readiness §1 — Image handling; real code: `candidate_synthesis.py`, `frontend/app/dashboard/pi/page.tsx` |
| C9 | **Local-only derivation.** Raw fetched text (YouTube comments, web article snippets, Tavily/YouTube result text fed to product-name extraction) is processed in memory or by a local Ollama model, never sent to a hosted provider, never persisted. Confirmed: `review_insight/text_extraction.py`, `discovery/product_extraction.py` and `embedding/embed.py` all point at `OLLAMA_HOST`, never a hosted API. | `competitor-intelligence-agent.md` C15 |
| C10 | **Scrape-failure fallback — superseded for discovery, unaffected for the general principle.** There is no "cached marketplace snapshot" any more — discovery has no marketplace fetch to cache a snapshot of. The underlying principle (never fabricate on failure) is carried forward by `sources/cache.py`'s per-niche/keyword TTL cache (not a failure fallback — a rate-limit/cost control, see C-new below) and by `discovery_run.py`'s degrade-to-`UNAVAILABLE`-for-this-run behavior on a source error. | superseded from OP3 |
| C11 | **Star topology — design confirmed, wiring partially built.** Conversational access via CEO requires `agent.ceo` + `agent.pi` (design, not yet wired — no `dispatch_pi_*` exists in `ceo_hub.py`, see §6.8). Registered direct execution paths require `agent.pi`, **plus a shared-service key where the action triggers one** — `pi.discover` additionally requires `research.niche_run` (§6.8), matching the two-key pattern CFO and CMO use. These two plain-HTTP routes (`pi.discover`, `pi.supplier_lookup`, `pi.report`) are real and callable today, independent of CEO; conversational/CEO-brokered access is designed but not implemented. | readiness §1 — Topology, Execution paths; §6.8 |
| C12 | **Entitlement:** free PI is limited (5 shallow runs/month); complete PI is a paid cart item. Values provisional. `resolve_pi_entitlement`/`resolve_niche_run_entitlement` are real and wired into `pi.discover`/`pi.supplier_lookup` (§6.8); the underlying free/paid *values* remain provisional. | readiness §1 — Agent cart |
| C13 | **pgvector, not Qdrant.** All similarity and semantic search in V1 uses pgvector on the existing Postgres. `product_embedding` (768-dim, `nomic-embed-text`) is real and built (`embedding/embed.py`). | readiness §1 — RAG |
| C14 | **Google Trends is dropped from PI entirely.** There is no `trend_signal` table in the real schema (migration `20260929_0001_pi_tables.py`'s own docstring states this explicitly) and no Trends module anywhere in `packages/product-intelligence`. Trend/keyword-trend work is reassigned to CMO — **not this spec's problem to solve**; if and how CMO builds it is out of scope here. | plan `replicated-whistling-russell.md` §2, §5; supersedes the original C14/§6.5 |
| C15 | **Proxy ranking, never "units sold."** Marketplaces do not publish unit volumes. Extended by §0's full labeling discipline (a-g) — not just "never units sold," but never "trending"/"bestseller" either, and every score must carry a visible explanation. | 2A.1; extended by §0 |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Candidate ranking basis — **revised, two-stage** | **Stage 1** (`ranking.py`, runs on every discovered candidate): a composite `proxy_score` out of 100 points, built from a small fixed point budget — `engagement_signal` (YouTube view-count band, 0-3 pts; comment-count band, 0-3 pts) + `source_diversity` (count of independent domains mentioning the candidate, capped at 4, 0-4 pts). `demand_signal` is always present in `score_explanation` but contributes 0 points and is named `UNAVAILABLE` (C2). `proxy_state=UNAVAILABLE` only when *no* base signal fired at all. **Stage 4** (`shortlist_scoring.py`, runs only on the post-review/post-supplier shortlist): an independent `final_score` out of 100, from `proxy_score` (40 pts, Stage 1's score rescaled), review-sentiment quality (30 pts, positive:negative theme ratio capped at 3:1), supplier availability (30 pts, half credit for a lead existing at all, full credit if a lead's published MOQ fits the stated budget). Never a copy of Stage 1's number (§0f) | C15, §0d/§0f. A first run with no history is never penalised for lacking a signal it structurally cannot produce; two independent, inspectable stages make "why is this one of the final picks" always answerable with specifics. |
| D2 | Discovery breadth | **Capped per run by `candidate_cap`**, default 30, configurable via the `pi.discover` request body or `pi_tenant_config`. **`depth` (`SHALLOW`/`COMPLETE`) is recorded on `pi_research_run` but, in the real built code, does not currently change `candidate_cap`, enrichment scope, or any other discovery behavior** — see the open question in §13. This is a real divergence from this decision's original "shallow=5/marketplace, complete=15/marketplace, complete strictly exceeds shallow" design (old D6) — that design was never implemented, and AC19/T23 (below) describing it have been dropped rather than left falsely claiming current behavior. **Cap-ordering fix (2026-10-01, real live-data bug):** candidates are sorted by `source_diversity` (descending, stable) before slicing to `candidate_cap` — previously a plain insertion-order slice, which meant Tavily results (processed before YouTube in `synthesize_candidates`) could fill the entire cap before any YouTube-matched candidate was even considered. Confirmed via a live run where Tavily extraction alone produced ≥30 distinct products and **every one of the 30 kept candidates had `engagement_signal=UNAVAILABLE`**, despite YouTube returning 30 real videos for the same queries — silently discarding the cross-validation the plan's own Context explicitly designed PI around. Now a candidate confirmed by more than one independent source always survives a cap cut ahead of a single-source one | C3 requires a cap; it exists (`DEFAULT_CANDIDATE_CAP = 30` in `discovery/discovery_run.py`). The depth/cap coupling does not exist yet — flagged, not silently assumed. |
| D3 | Trends dependency posture | **Removed — moot.** PI has no Trends dependency of any kind (C14). This decision no longer applies to PI | Superseded by C14. |
| D4 | Feasibility figures | **Two distinct sources, never conflated.** A candidate the seller does not yet own is priced via `estimate_product_feasibility` (`deterministic-engine.md` §5.13.2, real and built — `calc_engine/api/estimate_product_feasibility.py`) — an estimate, `estimate_ref`, range only. A seller's *own* SKU is priced via `margin_curve` (canonical, `engine_result_ref`) — that path belongs to CFO, not PI (`cfo-agent.md` §6.7). **`estimate_product_feasibility`'s real inputs come from the seller's stated `target_price_min_paise`/`target_price_max_paise`/`budget_paise` on `niche_brief`, never an observed marketplace listing price** — PI discovers candidates without observing any marketplace listing at all | PI holds no rates and no formulas; a discovered candidate has no owned COGS or `metric_result` lineage, so it cannot be dressed as a canonical figure (see §6.7). |
| D5 | pgvector use | Embed **derived attributes only** — `title_length`, `title_structure`, `keyword_themes` (never `candidate_title` itself) — via `nomic-embed-text` through Ollama. Used for near-duplicate candidate grouping (E12), a second, more precise pass after `candidate_synthesis.py`'s own cheap keyword-overlap first pass | C9/C13. Confirmed real and unchanged: `embedding/embed.py`'s `derived_attribute_text()` composes only from these three fields. Note C7 above records the separate, confirmed reversal for *storage* (not embedding) of `candidate_title` itself. |
| D6 | Discovery grouping/synthesis method — **new, not in the original spec** | `candidate_synthesis.py` groups raw Tavily/YouTube results into candidates on **two tiers**: (1) extraction-first — a local-Ollama pass (`discovery/product_extraction.py`) lists specific product names (brand+model) literally named in a result's own text; each extracted name becomes its own candidate seed, grouped by normalized-name equality, so one roundup article naming 5 products correctly yields 5 candidates, not 1. (2) Jaccard-token-overlap fallback — used only when extraction was never attempted, found nothing, or failed technically; groups by significant-token-set overlap ≥0.5 over the raw title/content. A tier-2 group's `confidence` is honestly distinguished: `DERIVED` (normal), `DERIVED_NO_PRODUCT_EXTRACTED` (extraction ran, found nothing — a real, expected negative result), or `DERIVED_EXTRACTION_UNAVAILABLE` (extraction technically failed — never conflated with a genuine negative result, per CLAUDE.md's guidance against narrating a non-result as a real one) | Confirmed bug-fix history in `candidate_synthesis.py`'s own docstring — an earlier exact-signature/word-frequency-mashup approach produced unreadable, near-duplicate candidate titles against a real Tavily/YouTube run; this is the corrected, shipped design. |
| D7 | Seller-stated brand exclusion — **new, 2026-10-01, not in the original plan** | `niche_brief.constraints.exclude_brands: string[]` (plain seller-specified list, e.g. `["Nike","Puma"]`) is applied in `discovery_run.py` via `candidate_synthesis.filter_excluded_brands()` — every one of a brand name's own significant tokens must be a subset of a candidate's token set (not substring search, so "Nike" never matches "Nikewear"; multi-word brands need every word present). Filtering happens **before** `candidate_cap` slicing, so an excluded brand frees up a shortlist slot rather than just hiding a result. **Deliberately not LLM-inferred** — no signal in this codebase could honestly support an automated "this brand is too famous/established" judgement, so this stays a plain, seller-authored structured list, matching `pi_supplier_lookup.py`'s own deterministic-filter precedent. Non-string list entries are skipped, never raised (bug-hunt pass, below) | Seller-requested (2026-10-01): a seller researching opportunity gaps often explicitly wants already-dominant brands excluded, since those aren't realistic white-space opportunities. Free-text constraint extraction (seller types a sentence, a local model turns it into this same structured list) is a legitimate future enhancement, not built here — flagged in §13, not silently assumed. |
| D8 | Tier-1-first grouping for a result/video whose own extraction found nothing — **new, 2026-10-01, real live-data bug fix** | When a Tavily result's or YouTube video's own product-name extraction returns `EMPTY`/`FAILED`, it is now matched against the already-extracted tier-1 `product_groups` FIRST (via `_find_tier1_group_by_containment` — full containment of the group's own short identity tokens within the result's full text, same discipline as image matching below, never diluted symmetric Jaccard) before falling back to the isolated tier-2 `fallback_groups`. Confirmed via a live run where ALL 30 kept candidates had `engagement_signal=UNAVAILABLE` despite YouTube returning 30 real videos for the same queries — every video's extraction legitimately found nothing for a vaguer/question-shaped title, and the old code could only match such a video against *other* vague entries, never against the richer product it was plainly about, permanently losing its engagement_signal/thumbnail/cross-validation | Previously, one real product could silently fragment into two worse candidates (a well-evidenced tier-1 one missing all YouTube signal, plus an orphan single-source duplicate) instead of correctly merging into one. This is the direct mechanism behind low image/engagement coverage — not just the image-matching heuristic itself. |
| D9 | Candidate-cap ordering by `source_diversity`, plus a YouTube-match reservation — **new, 2026-10-01, real live-data bug fix, extended same day** | `discovery_run._select_candidates_with_cap` replaces plain insertion-order slicing. First pass (same-day fix): sort by `source_diversity` descending before capping. **Found insufficient by a further live run** (0/30 kept candidates had `engagement_signal=AVAILABLE` even after the diversity sort, several reaching `source_diversity` 2-4 from multiple Tavily-only *websites* with zero video involvement, out-ranking every YouTube-matched candidate on the same metric) — extended to reserve up to `_MIN_YOUTUBE_MATCHED_SLOTS` (5) cap slots specifically for candidates with a real grouped YouTube video, best-`source_diversity`-first among them, before filling the rest of the cap from the overall pool exactly as before. Never pads with a worse candidate if a niche has fewer YouTube-matched candidates than the reservation would like | Confirmed by the same live-run family as D8 — restores the plan's own "cross-validating independent signal types is what gives this a real accuracy story" design intent, which a diversity-only sort still wasn't enough to protect. |
| D10 | Top-level run-failure safety net — **new, 2026-10-01, forward-looking bug-hunt fix** | `submit_pi_discover` previously had no top-level exception handling at all between `pi_research_run_repo.update_status(..., "RUNNING")` and `finish_run(...)` — any uncaught exception anywhere in discovery, review-insight, feasibility, or embedding left `pi_research_run.status` stuck at `RUNNING` **forever**, which `pi_research_run_repo.has_active_run`'s own contract then uses to permanently block that `niche_brief` from being edited or re-run (no code path ever un-stuck it). The entire post-fail-closed-check body is now wrapped in `try: return _run_the_work() except Exception: finish_run(status="FAILED")` — a genuine safety net, not a replacement for the specific degrade-not-fail handling every individual step already has | Found by a forward-looking bug-hunt pass (not a live-triggered crash yet, but three concrete, independent trigger paths were identified and fixed at their source too — D7's non-string brand entries, D11's malformed Ollama JSON, D12's malformed `fee_reference` row — any one of which would have hit this exact failure mode before the safety net existed. |
| D11 | `OllamaEmbeddingClient.embed()` JSON-parse guard — **new, 2026-10-01, forward-looking bug-hunt fix** | Unlike every other HTTP client in this package, `embed()` called `response.json()` with no guard at all — a malformed/non-JSON Ollama response (truncated stream, a proxy's HTML error page) raised `json.JSONDecodeError` uncaught, which is not `EmbeddingUnavailable`, so `pi_discover.py`'s per-candidate handler didn't catch it. Now wrapped in `try/except ValueError`, raising `EmbeddingUnavailable`, matching `tavily_client.py`/`youtube_client.py`/`google_places_client.py`'s existing pattern; `_run_embedding_for_candidate` also now catches generic `Exception` (not just `EmbeddingUnavailable`), matching `_run_review_insight_for_candidate`'s own broader discipline one function above it | Bug-hunt finding — embedding runs for every candidate (not just the shortlist) on every run, so this was a realistic, frequent trigger path for D10's failure mode. |
| D12 | Malformed `fee_reference` config row degrades to `UNAVAILABLE` — **new, 2026-10-01, forward-looking bug-hunt fix** | `calc_engine.formulas.fee_resolution.resolve_fee_or_unavailable` deliberately raises `ValueError` when a `fee_reference` row exists but all three rate fields are NULL (a malformed row — real operational data drift, not a programming error). `discovery/feasibility.py` now catches this specific `ValueError` and degrades that one candidate's feasibility to `feasibility_status=UNAVAILABLE` with the malformed-config reason named, rather than letting it abort the whole run — consistent with every other missing-data gap in that module's own "never silently skipped" contract | Bug-hunt finding — once such a row exists, every future run touching that category would otherwise hit D10's failure mode repeatedly until the bad row was manually fixed. |
| D13 | Own-brand-domain filter collapses both sides — **new, 2026-10-01, bug-hunt fix** | `_is_candidates_own_brand_domain` (C5/§6.6) previously compared the domain's raw first label (hyphens/digits intact) against the fully alphanumeric-collapsed candidate title — a domain like "new-balance.com" could never match even when the brand genuinely is that domain, silently under-excluding it. Both sides are now collapsed identically before comparison | Bug-hunt finding — a real gap in one of today's two live-tested supplier-domain filters, never a crash, only under-exclusion. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | Tavily's and YouTube Data API v3's free tiers remain usable at Metrion's real concurrent-tenant volume without a paid upgrade | Medium — `sources/rate_limiter.py` (process-wide semaphore, 3 concurrent calls/source) and `sources/cache.py` (per-niche/keyword TTL cache, not per-tenant) bound this, but a sustained high-tenant-count load could still exhaust the shared free-tier quota faster than caching alone absorbs |
| A2 | A local Ollama model can reliably extract literal product names from Tavily/YouTube result text at run volume, without hallucinating names not actually present | Medium — `product_extraction.py`'s prompt explicitly forbids inventing names and the tier-2 Jaccard fallback degrades gracefully when extraction finds nothing or fails technically; a model that *does* hallucinate a plausible-but-absent name would not be caught by any check in this build |
| A3 | Category strings (`niche_brief.category_text`, seller-authored free text) can be resolved to a `fee_reference` category for `estimate_product_feasibility`'s fee lookup | **High** — fee resolution depends on it (Q3, unresolved — same open gap as CI's own Q8) |
| A4 | A local model can derive usable sentiment/theme classifications from YouTube comments and web-article snippets at run volume | Medium — degrades to `insight_state=DEGRADED`/`UNAVAILABLE`, never fabricated |
| A5 | Google Ads API's `KeywordPlanIdeaService` becomes available to Metrion once brand verification (owned domain + Google Cloud project) is completed | Low-risk to current build (already excluded, C2) — only affects whether `demand_signal` is ever populated later |

---

## 4. Goals and non-goals

**Goals** — accept a structured niche + budget brief; discover candidate **opportunities** (never marketplace listings) from open web/video signal within a bounded, rate-limited run; rank candidates on a labelled, explainable proxy score (Stage 1) and independently re-score a narrowed shortlist (Stage 4); derive viewer/web commentary insight without persisting raw comment/article text; discover qualified supplier leads, filtered against obvious non-supplier noise; request feasibility figures from Brain 1 against the seller's own stated target price; return a structured research report — currently served directly over HTTP (`pi.report`), with CEO-brokered synthesis designed but not yet implemented (§6.8).

**Non-goals (V1)** — any marketplace fetch or scrape of any kind · bulk or continuous crawling · any financial calculation outside Brain 1 · supplier *ranking* · persisting raw comment/article/review text · sending raw expression to a hosted LLM provider · writing to any marketplace · demand forecasting · Google Trends (reassigned to CMO, C14) · Google Ads keyword-demand data (deferred pending brand verification, C2) · Qdrant.

---

## 5. Data model and interfaces

**Schema below is the real, built migration** (`packages/product-intelligence/migrations/versions/20260929_0001_pi_tables.py` + `20260930_0001_supplier_lead_candidate_id.py`), verified field-by-field against those files, not the plan's draft shape. `trend_signal` no longer exists (C14) — Trends work is CMO's, not PI's.

```sql
niche_brief (                             -- §6.1: structured intake. Authoring is NOT a direct execution path.
  id uuid pk default gen_random_uuid(), tenant_id uuid not null,
  status text not null,                   -- DRAFT | READY | ARCHIVED — a run may only start from READY
  category_text text,                     -- seller's own words; open-ended, authored via a plain form or CEO conversation, never via a direct-path trigger
  budget_paise bigint,                    -- total procurement budget
  target_price_min_paise bigint, target_price_max_paise bigint,
  marketplaces text[],                    -- subset of AMAZON|FLIPKART|MEESHO — which marketplace(s) feasibility is fee-schedule-checked against, never an observed listing's marketplace
  constraints jsonb,                      -- e.g. {fragile:false, max_lead_days:30, exclude_brands:["Nike","Puma"]}
  created_by uuid not null, created_at timestamptz not null default now(), readied_at timestamptz
)

pi_research_run (
  id uuid pk default gen_random_uuid(), tenant_id uuid not null,
  niche_brief_id uuid not null references niche_brief(id),  -- fk to an ALREADY-READY brief; the direct path never accepts free text
  depth text not null,                    -- SHALLOW | COMPLETE — recorded, but does NOT currently change candidate_cap or any discovery behavior (§2 D2, open question §13)
  trigger text not null,                  -- DIRECT_UI | CEO_REQUEST
  candidate_cap int not null,             -- D2: default 30, configurable per request or pi_tenant_config
  status text not null,                   -- QUEUED|RUNNING|PARTIAL|COMPLETE|FAILED
  started_at timestamptz, finished_at timestamptz
  -- NOTE: no trends_status column — Trends is not part of PI's schema at all (C14)
)

product_candidate (                       -- a discovered OPPORTUNITY IDEA (§0a), never an observed marketplace listing
  id uuid pk default gen_random_uuid(), tenant_id uuid not null, run_id uuid not null references pi_research_run(id),
  candidate_title text not null,          -- a real, lightly-cleaned title — confirmed exception to the "no listing copy" rule (C7); never a word-frequency mashup
  title_length int, title_structure jsonb, keyword_themes jsonb,  -- derived attributes, embedded (D5); never the ONLY representation of the title — candidate_title above also stores real text (C7)
  observed_category text, category_confidence text,
  image_url text, image_source_url text,  -- Tavily-sourced hotlink, source-labeled (C8, §0b)
  demand_signal jsonb,                    -- keyword volume band; ALWAYS {"status":"UNAVAILABLE","reason":"Google Ads API access pending brand verification"} this build (C2, Checkpoint 0)
  engagement_signal jsonb,                -- {"status":"AVAILABLE","video_count","view_count","comment_count","source":"youtube"} | {"status":"UNAVAILABLE","reason"}
  web_price_signal jsonb,                 -- §0g: {status, average_paise, range_low_paise, range_high_paise, sample_count, most_recent_mention, disclaimer} | {status:"UNAVAILABLE", reason} — regex-extracted from Tavily result text; reference-only, NEVER fed into Brain-1 math (candidate_synthesis.py has zero calc_engine dependency, enforcing this structurally)
  source_diversity int not null default 0, -- count of independent domains mentioning the candidate
  proxy_score numeric(6,2),               -- D1 Stage 1; null when proxy_state != COMPUTED; fixed 2-decimal string at the DB boundary, never a float in the calculation path
  proxy_state text not null,              -- COMPUTED | UNAVAILABLE — COMPUTED whenever at least one base signal (engagement or diversity) fired
  proxy_basis jsonb not null,             -- which signals produced it, raw values
  score_explanation jsonb not null,       -- §0d: {"signals":[{signal,status,points,max_points,reason}...], "summary"} — per-signal breakdown, plain-language, deterministically composed, never LLM-authored
  opportunity_label text not null default 'CANDIDATE_OPPORTUNITY',  -- §0a: CHECK constraint fixes this to exactly this one value
  candidate_marketplaces text[],          -- which of the seller's chosen marketplaces this candidate is fee-schedule-checked against (not observed)
  source_urls jsonb not null,             -- every source_url this candidate was synthesized from, each with fetched_at and source ("tavily"|"youtube")
  capture_status text not null,           -- OK|PARTIAL|UNAVAILABLE — per-run source degradation (Tavily/YouTube), not per-item fetch status
  confidence text not null,               -- OBSERVED|DERIVED|UNAVAILABLE|DERIVED_NO_PRODUCT_EXTRACTED|DERIVED_EXTRACTION_UNAVAILABLE — PI-scoped; the last two are real, additional states the built code emits (D6) beyond the original three-value vocabulary; see §5.1
  -- Added 20261001_0001 (feasibility wiring, §6.7) — a denormalized snapshot of calc-engine's
  -- product_feasibility_estimate row, not a cross-package FK (that table lives in calc-engine's
  -- own alembic history; feasibility_estimate_ref still carries full provenance back to it):
  feasibility_status text not null default 'UNAVAILABLE',  -- COMPUTED | UNAVAILABLE, CHECK-constrained
  feasibility_estimate_ref uuid,          -- calc_engine.product_feasibility_estimate.id
  feasibility_low_paise bigint, feasibility_high_paise bigint,
  feasibility_cogs_basis text,            -- STATED | UNKNOWN — NULL only when status=UNAVAILABLE; always UNKNOWN in the current build (no supplier.quote mechanism yet)
  feasibility_assumptions jsonb,
  feasibility_unavailable_reason text     -- named reason when status=UNAVAILABLE (e.g. "seller has not stated a budget"), never silently absent
)
-- Fields removed from this spec's original version: marketplace, marketplace_item_id,
-- listed_price_paise, mrp_paise, rating, rating_count, rank_position — none are obtainable
-- without marketplace access (C2). An unobtainable field is omitted and named in unavailable[]
-- (§6.9), never defaulted or faked.

product_review_insight (                  -- derived only; one row per (candidate_id, insight_source_type) — never merged (§0b)
  id uuid pk default gen_random_uuid(), tenant_id uuid not null, candidate_id uuid not null references product_candidate(id),
  insight_source_type text not null,      -- YOUTUBE_COMMENTARY | WEB_EDITORIAL — CHECK constraint; §0b, new required column vs. this spec's original shape
  sentiment_split jsonb,                  -- e.g. {"POSITIVE":"3/5", ...} — Fraction-derived strings, never float
  rating_distribution jsonb,              -- always null in this build — no star-rating source exists (commentary/editorial only, not structured ratings)
  complaint_themes jsonb, positive_themes jsonb, summarised_patterns jsonb,
  reviews_considered int,
  confidence text not null,               -- DERIVED | UNAVAILABLE
  derivation_method text not null,        -- LOCAL_MODEL | STRUCTURED_ONLY
  insight_state text not null,            -- COMPLETE|DEGRADED|UNAVAILABLE
  degraded_reason text,
  source_url text not null, fetched_at timestamptz not null, derived_at timestamptz not null
)

supplier_lead (                           -- C4: discovery only, never ranked here
  id uuid pk default gen_random_uuid(), tenant_id uuid not null, run_id uuid not null references pi_research_run(id),
  candidate_id uuid references product_candidate(id),  -- added 20260930_0001: attributes a lead to the specific candidate it was found for; nullable (a category-wide search with no single matching candidate is still valid)
  supplier_name text not null,
  source text not null,                   -- GOOGLE_PLACES | TAVILY | INDIAMART_LOOKUP (C5 — TAVILY added vs. this spec's original enum; INDIAMART_LOOKUP schema-only, not implemented)
  contact jsonb,                          -- as published by the source, e.g. {"phone","website","moq":{"quantity","unit_price_paise"}|null}
  locality text, distance_km numeric(6,2),
  category_match text,
  source_url text, fetched_at timestamptz not null
)

-- NO trend_signal table — Trends/keyword-trend work stays CMO's, not PI's (C14). This is a
-- deliberate removal from this spec's original schema, not an oversight.

product_embedding (                       -- C13: pgvector, no Qdrant
  id uuid pk default gen_random_uuid(), tenant_id uuid not null,
  subject_type text not null,             -- CANDIDATE | THEME | CATEGORY
  subject_id uuid not null,
  embedding vector(768),                  -- nomic-embed-text, dimension fixed
  model_name text not null, model_dim int not null,
  created_at timestamptz not null default now()
)

pi_tenant_config (                        -- retention policy + per-source cache TTL
  tenant_id uuid pk,
  candidate_retention_days int not null default 90,   -- product_candidate, product_review_insight
  supplier_lead_retention_days int not null default 90,
  tavily_cache_ttl_hours int not null default 24,     -- new vs. this spec's original shape: per-niche/keyword cache TTL (sources/cache.py), not retention
  youtube_cache_ttl_hours int not null default 24,
  updated_by uuid, updated_at timestamptz not null default now()
)
```

**Module list — real, built package layout** (`packages/product-intelligence/src/product_intelligence/`), including modules not named in this spec's original version:

| Module | Role |
|---|---|
| `repositories/*` | Tenant-scoped CRUD per table above, `tenant_scope()` context manager (CI's pattern, verbatim) |
| `sources/tavily_client.py` | `TavilyClient` Protocol + real HTTP client — `search()`, `images_for()`. **Corrected 2026-10-01**: confirmed via live testing that Tavily's `images` response carries no real page-URL association per result (`source_url` is, in practice, the image's own CDN URL, not a page); `images_for()` now requests `include_image_descriptions=True` and `TavilyImage` gained a `title` field (the hosting page/site's own title) — the only genuine per-image signal the API provides, used for approximate title/description containment matching in `candidate_synthesis.py` |
| `sources/youtube_client.py` | `YoutubeClient` Protocol + real HTTP client — `search_videos()`, comment reads |
| `sources/cache.py` | `InProcessQueryCache` — per-niche/keyword TTL cache, keyed by normalized query text **not tenant** (the concurrency/rate-limit fix); thread-safe (`threading.Lock`) |
| `sources/rate_limiter.py` | **New, not in the original plan's module list.** Process-wide outbound-call throttle — `throttle(source)` context manager wrapping a `threading.Semaphore` per source (`tavily`/`youtube`/`google_places`, default 3 concurrent each), acquired around every real (non-cache-hit) outbound call. Bounds the shared free-tier quota across *all* tenants' concurrently-running runs — `discovery_run.py`'s own `ThreadPoolExecutor` pools only bound concurrency within one run; this is the system-wide layer on top. Single-process, in-memory; a multi-instance deployment needs a Redis-backed equivalent later (documented limitation, not silently assumed away) |
| `discovery/discovery_run.py` | Orchestrator — `QUEUED→RUNNING` transition, Tavily+YouTube queries (bounded `ThreadPoolExecutor`, 5 workers), through `cache.py` and `rate_limiter.py`, degrades a source to `UNAVAILABLE`-for-this-run on error (never a hard run failure), calls synthesis + Stage 1 ranking, persists `product_candidate` rows |
| `discovery/candidate_synthesis.py` | Two-tier extraction-first/Jaccard-fallback grouping (D6); `web_price_signal` regex extraction; image attribution |
| `discovery/product_extraction.py` | **New module, not named in the original plan's §2 module list.** Local-Ollama classification-only pass listing literal product names (brand+model) named in a raw result's text — never invents a name, empty list is a normal outcome, raises `ProductExtractionUnavailable` (not a returned Result) on technical failure |
| `discovery/ranking.py` | Stage 1 scoring (D1) |
| `discovery/shortlist_scoring.py` | Stage 4 scoring (D1) |
| `discovery/feasibility.py` | **New, wired 2026-10-01.** `compute_candidate_feasibility()` — the one module allowed to import `calc_engine` (deliberately isolated from `candidate_synthesis.py`/`discovery_run.py`, which have zero `calc_engine` dependency, keeping `web_price_signal`'s isolation structurally obvious, §0g). Builds a `ProspectiveObservationSet` from the seller's `niche_brief` price band/budget, resolves `fee_reference`, calls `estimate_product_feasibility`, persists via `calc_engine.repositories.product_feasibility_estimate_repo`, returns a `FeasibilityOutcome` for the caller to snapshot onto `product_candidate` (§6.7) |
| `review_insight/text_extraction.py` | Local-Ollama sentiment+theme classification over YouTube comments / web snippets, source-type-scoped (§0b) |
| `review_insight/aggregate.py` | `Fraction`-based aggregation into `sentiment_split`/theme counts; never aggregates `YOUTUBE_COMMENTARY` and `WEB_EDITORIAL` together |
| `review_insight/submit.py` | Persists `product_review_insight`; raw text never reaches a repo call, a log line, or anywhere outside this call chain |
| `supplier/google_places_client.py` | Places API (New) — free `search_place_ids` / paid `enrich_place` cost-bounding split |
| `direct_path/pi_discover.py` | `submit_pi_discover(...)` — create run row, fail-closed on permission/entitlement, run discovery+synthesis+ranking+review_insight+embedding, finish run |
| `direct_path/pi_supplier_lookup.py` | `lookup_suppliers_for_candidates(...)` — Places+Tavily lookup for the seller's chosen top-5-or-fewer, filtered via `_looks_like_supplier`/`_has_supplier_signal` (C5), bounded `ThreadPoolExecutor` (5 workers), each candidate degrades independently |
| `direct_path/pi_report.py` | Re-renders a completed run from persisted data, no new fetch |
| `embedding/embed.py` | `embed_candidate()`/`find_near_duplicate_candidates()` — derived-attribute-only embeddings (D5), pgvector cosine-distance near-dup lookup (E12) |
| `reasoning/narration_safety.py` | `check_narration_safety()` — PI's own `FigureToken`/number-diff mechanism (not an import from `packages/cfo`, a structural duplicate) plus three PI-specific checks: estimate-qualifier language present for ESTIMATE-register figures, no "trending"/"bestseller"/"popular" anywhere (§0a), no unqualified "review" (§0b) |

**Similarity needs, served by pgvector (C13):** near-duplicate candidate detection (via `title_structure`/`keyword_themes`, never `candidate_title` — E12) · grouping complaint themes into clusters · matching a seller's niche text to observed categories. All operate on **derived attributes** (D5) for the embedding itself, never on raw marketplace expression (there is none to operate on — C2). `model_name` and `model_dim` are stored so a model change is a detectable, scriptable re-index rather than silent corruption.

### 5.1 Confidence vocabulary boundary (fix 2)

PI's `confidence` column uses a scoped vocabulary rooted in `competitor-intelligence-agent.md` §5.1's `OBSERVED | DERIVED | UNAVAILABLE`, **extended in the real built code** by two additional states `candidate_synthesis.py` emits — `DERIVED_NO_PRODUCT_EXTRACTED` and `DERIVED_EXTRACTION_UNAVAILABLE` (§2 D6) — both honest refinements of `DERIVED`, never a stronger claim than it. **The same boundary rule applies without exception: nothing on `product_candidate` ever crosses into Brain 1 as anything stronger than `DERIVED`.** This preserves the monotonic-confidence rule (`data-foundation.md` §7.1, `deterministic-engine.md` §9): a figure built on a PI observation can never present as `VERIFIED` or `PROVISIONAL`.

**Interfaces PI calls** — all Brain 1 unless noted:

| Interface | Purpose | Returns | Status |
|---|---|---|---|
| `estimate_product_feasibility(...)` | Feasibility for a **discovered candidate the seller does not yet own** (`deterministic-engine.md` §5.13.2) | `product_feasibility_estimate`, **`estimate_ref` — never an `engine_result_ref`** | **Wired, 2026-10-01.** `discovery/feasibility.py`'s `compute_candidate_feasibility()` is the one call site — invoked from `direct_path/pi_discover.py` for every shortlisted candidate (same `_SHORTLIST_SIZE`-scoped `ThreadPoolExecutor` pass as review-insight/embedding), using the seller's stated `target_price_min_paise`/`target_price_max_paise`/`budget_paise` on `niche_brief`. Persisted via the new `calc_engine.repositories.product_feasibility_estimate_repo` (mirrors `metric_result_repo`'s save/get shape) and snapshotted onto `product_candidate` via six new columns (§5) so `pi.report` can render it without a cross-package join. `stated_cogs_paise` is always `None` today — no `supplier.quote` mechanism exists in PI's data model yet (Phase 2/3 scope) — so every real estimate currently has `cogs_basis=UNKNOWN`, honestly rendered as a price/fee-spread range, never a margin claim. Verified via a unit test (`test_pi_discover.py`), two integration tests against real Postgres (`test_product_feasibility_estimate_repo.py`), and a live run against real Tavily/YouTube data (§10 live-verification note) |
| `resolve_fee_reference(marketplace, category, fee_type, as_of_date)` | Fees for feasibility; PI holds no rates | `fee_reference` row or a declared gap | **Wired** — called from `discovery/feasibility.py` with `fee_type="COMMISSION"` (the dominant fee component). A missing `fee_reference` row degrades to `Unavailable`, which `estimate_product_feasibility` turns into a honestly-widened range (never a suppressed or defaulted figure), per its own rule 2 |

**`landed_cost` is not a PI interface** — it belongs to CFO for a seller's own owned SKU and was removed from this table; PI never had a code path to it. **PI does not call `margin_curve` and does not call `estimate_competitor_margin_range` (fix 3, fix 7).** `margin_curve` is reserved for a seller's own SKU and belongs to CFO (`cfo-agent.md` §6.7) — a discovered candidate has no owned COGS or `metric_result` lineage to price canonically. `estimate_competitor_margin_range` and its `competitor_estimate` table are **CI-exclusive** (`deterministic-engine.md` §5.13.1); PI reaching that surface from a discovered candidate would bypass CI's own entitlement gate and blur "seller-supplied competitor" (CI's job) with "PI-discovered candidate" (a different thing). Where a discovered candidate is genuinely worth comparing to competitors, that is a CEO-brokered handoff to CI (Q8), never a direct PI call.

---

## 6. Core rules

### 6.1 Intake — authoring is not a direct path (fix 5)

Two separate steps, deliberately not one:

1. **Authoring a `niche_brief`.** The seller describes what they want, in their own words, with CEO's conversational help if needed. This is open-ended by nature — `category_text` is free text, `constraints` is open `jsonb` — and per `auth.md` §5.2's guardrail ("no direct path may accept free-form input... anything open-ended requires `agent.ceo`"), it is **never** a direct execution path. It is either a **plain CRUD form** — a standard authenticated tenant-write, gated only by ordinary membership (no `agent.*` key, since no agent is invoked) — or a **conversational exchange** (`agent.ceo` + `agent.pi`) where CEO helps compose the brief. Either path writes the same `DRAFT` row.
2. **`DRAFT` → `READY`.** Any member who could author the brief may mark it `READY`, and only once budget, category and at least one marketplace are present — missing either blocks the transition and raises a data request rather than assuming a default. **A `READY` brief may be edited back to `DRAFT`** at any time before a run starts against it (correcting a mistake is always allowed); it may not be edited while a `pi_research_run` referencing it is `QUEUED` or `RUNNING`.
3. **`ARCHIVED`.** Set by the same member (or the owner) once the brief is no longer wanted for future runs. Archiving is a soft state, not a delete — prior runs and their `niche_brief_id` references remain valid and readable.
4. **Triggering a run from a `READY` brief.** The direct path `pi.discover` (§6.8) takes only `niche_brief_id` — a UUID referencing an already-authored, already-bounded, `READY` brief. No free text ever reaches a direct-path call. A brief in `DRAFT` or `ARCHIVED` cannot be passed to `pi.discover`.

### 6.2 Discovery — revised, marketplace-agnostic (C2, §0)

1. **Tavily web search** (`search()`, `include_images=True`) and **YouTube Data API v3** (`search_videos()`) against query terms derived from `niche_brief.category_text` (`discovery_run.py`'s `_queries_for_niche`: the base category plus `"best {category} india"` and `"{category} review"`), bounded by `candidate_cap` (default 30). No marketplace is ever fetched or scraped (C2).
2. **Through `sources/cache.py`'s per-niche/keyword TTL cache, keyed by normalized query text, not tenant.** Two tenants researching the same category hit the same cache entry — the deliberate fix for fanning every tenant's concurrent run out 1:1 to Tavily/YouTube's shared free-tier quota.
3. **Through `sources/rate_limiter.py`'s process-wide `throttle(source)`** around every real (non-cache-hit) outbound call — a bounded semaphore (3 concurrent per source: `tavily`/`youtube`/`google_places`) shared across *every* tenant's concurrently-running calls, not just one run's own `ThreadPoolExecutor` pool.
4. **Raw results are grouped into candidates two-tier (D6):** extraction-first via a local-Ollama product-name pass (`discovery/product_extraction.py`), falling back to Jaccard-token-overlap grouping only when extraction was unavailable, found nothing, or failed technically.
5. **A source that errors or hits its cap degrades to `UNAVAILABLE` for that run** (`tavily_degraded`/`youtube_degraded`), never a hard run failure — `capture_status` on resulting candidates reflects `OK`/`PARTIAL`/`UNAVAILABLE` accordingly, and `pi_research_run.status` becomes `PARTIAL` (never silently `COMPLETE` with a hidden gap).
6. **Never a crawl.** A run touches only the queries its `candidate_cap` and the cache/rate-limiter above permit, then stops.

### 6.3 Ranking — two-stage (C15, D1, §0d/§0f)

**Stage 1 (`discovery/ranking.py`), runs on every discovered candidate:** `proxy_score` composes from `engagement_signal` (YouTube view-count band 0-3 pts, comment-count band 0-3 pts) and `source_diversity` (independent-domain count, capped at 4, 0-4 pts) — a fixed 10-point budget, scaled to a 0-100 `proxy_score` string (never a float). `demand_signal` (would-be Google Ads keyword-volume) is always named in `score_explanation` as `UNAVAILABLE` with its reason, and contributes 0 points — never silently omitted, never suppressing the rest of the score (C2). `proxy_state=UNAVAILABLE` only when **neither** engagement nor diversity signal fired at all; `proxy_state=COMPUTED` whenever at least one did.

**Stage 4 (`discovery/shortlist_scoring.py`), runs only on the post-review/post-supplier-lookup shortlist:** an independent `final_score`, from `proxy_score` (rescaled to 40 pts), review-sentiment quality (positive:negative theme ratio across `product_review_insight` rows, capped 3:1, 30 pts), and supplier availability (half credit for any lead existing, full credit if a lead's published MOQ fits the stated budget, 30 pts). **Never a copy or re-export of Stage 1's number** (§0f) — each stage's `*_score_explanation` is independently composed and inspectable.

**This spec's original "review velocity across runs" refinement (old D1/§6.3) is not implemented in the real code.** `ranking.py` has no cross-run comparison logic of any kind — Stage 1 scores a single run's candidates from that run's own signals alone. If and when a multi-run velocity enrichment is wanted, it is a new, undecided addition — not a currently-working feature this spec can describe as built (see §13).

Every surface renders either score as an estimated interest proxy, never as units sold or revenue (C15), and never as "trending"/"bestseller"/"popular" (§0a).

### 6.4 Review insight (C7, C9, §0b)
Raw YouTube comment/web-snippet text is transient, local-only, and never persisted to PostgreSQL, object storage, files, logs, traces, APM, Redis, vector stores, generated reports **or a hosted model provider** (`review_insight/submit.py`'s own grep-verifiable contract). Only the derived fields on `product_review_insight` survive, scoped by the required `insight_source_type` (`YOUTUBE_COMMENTARY | WEB_EDITORIAL`) — the two are never aggregated together (`aggregate.py` raises if a caller tries). Where local derivation is unavailable or finds nothing classifiable, `insight_state = DEGRADED` or `UNAVAILABLE` with `degraded_reason` recorded — there is no `rating_distribution` fallback in the real build (no structured-rating source exists for commentary/editorial data), unlike this spec's original "degrades to rating-only insight" language.

### 6.5 Google Trends — removed from PI entirely (C14)
**Superseded.** PI has no Trends dependency, no `trend_signal` table, and no Trends module anywhere in the package. Trend/keyword-trend work is CMO's to design and build — not referenced further in this spec. (This section is kept, empty of content, only so downstream cross-references to "§6.5" elsewhere in the codebase resolve to an explicit "removed" marker rather than a dangling pointer.)

### 6.6 Supplier discovery (C4, C5)
Google Places (New) by category-derived query (`"{candidate_title} manufacturer supplier wholesale india"`) — free `search_place_ids` used to find up to 5 place matches per candidate, paid `enrich_place` called only for the single best match, and only for the seller's chosen top-5-or-fewer candidates (`pi_supplier_lookup.py`'s own cost-bounding enforcement). **Tavily web search is a secondary source**, filtered through `_looks_like_supplier`/`_has_supplier_signal` (excludes editorial/listicle titles, known major retail-storefront domains, "buy X online"/"official store" framing; boosts results carrying a manufacturer/wholesale/distributor signal word) — a heuristic filter, not a guarantee, confirmed via a real bug found in live testing (unfiltered results previously included a brand's own retail store and review-roundup articles). IndiaMART single-lookup stays schema-only (`supplier_lead.source` enum includes `INDIAMART_LOOKUP`), **not implemented**. Output is a **qualified lead list** — name, contact as published, locality (Places only), `candidate_id` attribution (added 20260930). PI attaches **no score and no ranking**. Contact data is retained per `pi_tenant_config.supplier_lead_retention_days` (default 90 days — the final DPDP-appropriate value is still open, Q6) and is never bulk-harvested into a standing directory.

### 6.7 Feasibility (fix 3, fix 7) — wired 2026-10-01

**Real, built, and exercised end-to-end.** `discovery/feasibility.py`'s `compute_candidate_feasibility()` assembles observations and calls **`estimate_product_feasibility`** (`deterministic-engine.md` §5.13.2) for every shortlisted candidate the seller does not yet own, performing no arithmetic itself. The returned figure carries an **`estimate_ref`**, always a range, persisted with its assumptions and any fee-reference gaps intact — never an `engine_result_ref`, and never `margin_curve` (CFO's canonical-SKU surface). Called from `direct_path/pi_discover.py`'s shortlist pass (same bounded-concurrency pattern as review-insight/embedding); the outcome is snapshotted onto `product_candidate`'s six `feasibility_*` columns (§5) via `product_candidate_repo.update_feasibility()`.

**Never silently skipped — `feasibility_status=UNAVAILABLE` with a named reason** when it genuinely can't be computed: no marketplace selected on the brief, no category resolvable, no stated budget, or no stated target-price band. This is the same "missing data is named, never hidden" discipline as every other PI field (§0e), not a special case.

**PI never derives, estimates, or supplies a cost figure itself — it has no costing capability at all** (front matter: "PI researches. It never calculates"). The two cases §5.13.2 defines:

1. **The seller has an actual `supplier.quote` for the candidate.** PI would pass that quote's stated cost as `stated_cogs_paise`, and the engine's `cogs_basis` would be `STATED`. **Not reachable in the current build** — no `supplier.quote` mechanism exists anywhere in PI's data model yet (`supplier_lead` carries contact info only, never a cost figure); this is real Phase 2/3 scope, not invented here.
2. **No quote exists (today, always this case).** PI passes nothing for `stated_cogs_paise` — never guesses, averages, or infers a cost from `web_price_signal` (§0g) or any other observed figure. The engine returns `cogs_basis = UNKNOWN` and a range describing price-and-fee spread only, explicitly **not** a margin estimate. **Every real feasibility estimate this build produces is `cogs_basis=UNKNOWN`** — honestly rendered as such, never presented as a margin figure.

Persistence is a new calc-engine repository, `repositories/product_feasibility_estimate_repo.py` (`save()`/`get()`, mirrors `metric_result_repo`'s shape exactly — `estimate_product_feasibility` itself stays "pure and DB-free," per its own docstring, so persistence is the caller's job). Verified via `test_pi_discover.py::test_feasibility_is_computed_and_written_back_for_every_shortlisted_candidate`, two real-Postgres integration tests, and a live run against real Tavily/YouTube signal and the seller's own stated price band.

### 6.8 Registered direct execution paths — real routes, CEO/CFO wiring deferred

**Built and real today — plain HTTP, no CEO in the loop** (`backend/src/backend/api/v1/pi.py`, confirmed: no import of `agents/ceo_hub.py` anywhere in this file):

| Trigger id | Action | CEO call | Permission | Entitlement | Audit |
|---|---|---|---|---|---|
| `pi.discover` (`POST /api/v1/pi/discover`, body `{niche_brief_id, depth, candidate_cap?}`) | Run discovery from an already-`READY` brief (§6.1) | No | `require_auth(permission=AGENT_PI)` as the route dependency **plus** an in-handler `has_permission(..., key=RESEARCH_NICHE_RUN)` check — two independent keys, same two-gate shape as `api/v1/cfo.py`'s `post_gst_lookup` | Resolves **both** `resolve_pi_entitlement` and `resolve_niche_run_entitlement` — `402` if either denies, `403` if either permission key is missing | `agent_run_repo.insert_run`/`finish_run`, `agent_id="PI"`, `trigger_type="DIRECT"` |
| `pi.supplier_lookup` (`POST /api/v1/pi/supplier-lookup`, body `{run_id, candidate_ids[1..5]}`) | Supplier lookup for the seller's chosen top-5-or-fewer candidates | No | `require_auth(permission=AGENT_PI)` only (single key) | `resolve_pi_entitlement` | Same agent_run pattern |
| `pi.report` (`GET /api/v1/pi/report/{run_id}`) | Re-render a completed run from persisted data, no new fetch | No | `require_auth(permission=AGENT_PI)` only | None — read-only, matches `GET /ci/summary`'s own precedent | N/A, read-only |

Niche-brief CRUD (`/pi/niche-briefs*`) is plain authenticated tenant-write, no `agent.*` key — matches §6.1's "authoring invokes no agent" design exactly.

**Designed but NOT YET IMPLEMENTED — flagged explicitly, not silently presented as done and not silently omitted either:**

- **CEO Hub dispatch.** The design (per the approved plan) is `backend/src/backend/agents/ceo_hub.py` gaining `PI_DISCOVER`/`PI_SUPPLIER_LOOKUP`/`PI_REPORT` constants and three `dispatch_pi_*` functions shaped like `dispatch_ci_discover_competitors`, enabling conversational access (`agent.ceo` + `agent.pi`, C11). **Grep-confirmed: no such constant or function exists in `ceo_hub.py` today.** Conversational PI access does not work. *Update 2026-10-07:* the dispatch design is superseded by the CEO action registry (`ceo-agent-orchestration.md` §6.11): `pi.discover` (also needs `research.niche_run` and an existing READY niche brief), `pi.supplier_lookup` and `pi.report` become registry entries; the CEO→CFO batch-size handoff becomes the playbook `NEW_PRODUCT_DECISION` (§6.12) with independent parallel legs. Still **not implemented** — specification only.
- **The CEO→CFO batch-size handoff.** Design: once a seller has a final top-5 with supplier leads, CEO calls CFO's existing `assemble_batch_size_estimate` (`backend/src/backend/services/cfo_actions.py:2909`, already real and working for CFO's own purposes) once per product, passing the `cogs_basis` from `estimate_product_feasibility` through unchanged. Handoff-safety rules recorded now, ahead of the code: `recommended_quantity` must never narrate as guaranteed/final when `cogs_basis=UNKNOWN`; a candidate with no real `supplier.quote` must never be presented as "ready to buy"; `narration_safety.py`'s check 1 (estimate-qualifier language) is the enforcement point once this exists. **Not implemented** — no such CFO call exists anywhere in PI or CEO Hub code today.
- **`final_recommendation` composition.** Design: a per-finalist response shape (`candidate_title`, image+attribution, positive/negative themes, a "consider addressing" list from `negative_themes`, supplier name/link/MOQ, `web_price_signal` reference, seller's `target_price_paise`, `estimated_margin`, `recommended_quantity`, `final_score_explanation`) assembled by CEO from PI + CFO data — not a new stored table. **Not implemented.** The dashboard (`frontend/app/dashboard/pi/page.tsx`) renders this section as an honest, clearly-labeled "not yet available" `ConfidenceBadge`, never a faked or partial version (§6.8's own design intent, Phase 3).

This deferral is a confirmed, explicit scope decision, not an oversight — the plan's Phase 2 section states it is excluded "even within Phase 2," pending separate approval, per the user's standing instruction that this work never starts silently.

**Why `research.niche_run` is a separate key, even though only PI consumes it.** The mechanism matches CFO's `service.gst_lookup` and CMO's `service.gst_lookup` — two independent keys, two independent meters — but the rationale is different, not a literal precedent: GST Lookup is genuinely shared across two agents. `research.niche_run` is consumed only here. Its purpose is **spend control**: niche discovery is a paid, on-demand research run (C3), and a tenant's OWNER may want a permission boundary between "may use PI at all" and "may spend the tenant's paid-research budget" — e.g. granting a partner `agent.pi` for reading past reports without granting them the ability to trigger a new billable run.

### 6.9 Output to CEO — design, partially realized today

**Design (unchanged):** a run returns a **structured report object**, not prose — brief echo · ranked candidates with `score_explanation` · review insight per candidate · supplier leads · feasibility figures with `estimate_ref` (once §6.7's wiring exists) · an explicit **`unavailable[]`** list. CEO would synthesize; PI would never address the seller directly.

**Today's reality:** `pi.report` (§6.8) returns exactly this structured shape directly over HTTP — real and working — but there is no CEO in the loop to synthesize it (§6.8's CEO Hub gap). The dashboard (Phase 3, `frontend/app/dashboard/pi/page.tsx`) renders the structured report as-is, test-harness style, with no narrated prose layer on top. "CEO synthesises; PI does not" remains the design target for conversational access, not a description of the current direct-HTTP path's behavior.

---

## 7. AI requirements

| Brain | Role in PI |
|---|---|
| **Brain 1** | Every financial figure — feasibility (wired, §6.7), and batch size once the CFO handoff (§6.8) exists. No LLM. |
| **Brain 2** | Statistical signals only. Spec unwritten — see Q5. PI has no Brain-2 dependency in the current build (no trend-direction/outlier-pricing module exists). |
| **Brain 3** | Interpreting the brief, classifying review/commentary themes (`text_extraction.py`) and extracting literal product names from search results (`product_extraction.py`) — both classification-only, never a number. Composing a narrated structured report is designed (§6.9) but has no real call site yet, since no CEO orchestration exists to invoke it. |

**Model output boundary — confirmed in both local-model modules.** `review_insight/text_extraction.py` returns only a sentiment label + short theme tags per text; `discovery/product_extraction.py` returns only a plain list of product-name strings, explicitly instructed never to rank/score/count and never to invent a name not literally present. Deterministic code (`aggregate.py`, `ranking.py`, `shortlist_scoring.py`, `candidate_synthesis.py`) turns those labels into proportions, counts, `proxy_score`, and candidate groupings. **The model never emits a proportion, a weight, a score or a count, anywhere in this package.**

**Brain 3 emits no number of its own, anywhere (fix 8).** Every number in PI's structured report — `proxy_score`, `final_score`, engagement/diversity counts, `web_price_signal` figures — is copied verbatim from a `product_candidate` row or (once wired) an engine result (`estimate_ref`). `reasoning/narration_safety.py`'s number-diff check is the concrete enforcement mechanism for any future narration surface. This is the same rule as `cfo-agent.md` AC2.

Raw rows and raw text never enter a hosted provider (C9) — `OLLAMA_HOST`-pointed local calls only, confirmed in `text_extraction.py`, `product_extraction.py`, `embedding/embed.py`.

---

## 8. Authorization and security

1. Every request enters the `auth.md` §7.1 six-step chain; PI adds no bypass.
2. Permission (`agent.pi`) and entitlement (cart, run credit) are independent gates; both must pass — confirmed real for `pi.discover`/`pi.supplier_lookup` (§6.8).
3. Conversational access additionally requires `agent.ceo` **by design** — not currently reachable, since no CEO dispatch exists yet (§6.8). Direct paths (§6.8) require only `agent.pi` (+`research.niche_run` for `pi.discover`).
4. **Allowlists, revised (C6).** There is no fixed marketplace-domain allowlist to enforce any more — Tavily/YouTube are the purpose-scoped, licensed sources, not domain-restricted crawlers. Supplier discovery still applies a server-side heuristic filter (`_looks_like_supplier`/`_has_supplier_signal`, §6.6) against obvious non-supplier noise, not a hard domain allowlist/denylist.
5. Tenant-scoped throughout; RLS (`FORCE ROW LEVEL SECURITY`) is the final boundary — confirmed on every table in `20260929_0001_pi_tables.py`, including `pi_tenant_config`. Background runs set tenant context from the job payload or fail closed.
6. Outbound calls are rate-limited **process-wide** (`sources/rate_limiter.py`, §6.2) and per-niche cached (`sources/cache.py`) — a real, confirmed mechanism, not a design aspiration. `robots.txt` posture is moot for Tavily/YouTube (licensed APIs, not a direct-fetch crawler); it remains CI's own open question where CI still fetches directly.
7. Supplier contact data is personal data under DPDP where the supplier is a proprietor — retained per run, never accumulated (C5).

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Tavily unavailable (errors or hits its process-wide rate-limit cap) for one or more queries | `tavily_degraded=True` for the run; candidates still synthesize from YouTube signal alone; `capture_status=PARTIAL`/`UNAVAILABLE` named on affected candidates; never a hard run failure (§6.2) |
| E2 | YouTube unavailable | Symmetric to E1 — `youtube_degraded=True`, candidates synthesize from Tavily signal alone |
| E3 | Both Tavily and YouTube unavailable for a run | `capture_status=UNAVAILABLE` on every resulting candidate (or zero candidates — E6); `pi_research_run.status=PARTIAL`, `partial_reason` names both failures |
| E4 | Local Ollama model unavailable (review-insight classification or product-name extraction) | Review insight `insight_state=DEGRADED`/`UNAVAILABLE` with `degraded_reason`; `candidate_synthesis.py` falls back to Jaccard-overlap grouping with `confidence=DERIVED_EXTRACTION_UNAVAILABLE` (D6) — never conflated with a genuine "model looked and found nothing" result; **never** sent to a hosted provider (C9) |
| E4b | Local model reachable but finds no product name in a result's text | A normal, expected outcome (`product_extraction.py`'s own contract) — `confidence=DERIVED_NO_PRODUCT_EXTRACTED` (D6), distinct from E4's technical-failure case |
| E5 | Fewer candidates than `candidate_cap` | Reported honestly; never padded |
| E6 | Zero candidates, or a candidate with no signal at all | Empty result / `proxy_state = UNAVAILABLE`, reasons named; never fabricated (§6.3) |
| E7 | Category unresolvable against `fee_reference` | `feasibility_status=UNAVAILABLE`, reason="no category available... to resolve a fee reference against" — named, never silently skipped (§6.7) |
| E7c | Seller authors free-text niche details | Handled by a plain form or CEO conversation; never reaches `pi.discover` directly — only the resulting `niche_brief_id` does (§6.1) |
| E7d | Seller asks PI for a competitor-margin-style estimate on a discovered candidate | Refused; PI has no access to `estimate_competitor_margin_range`. Whether and how CEO can hand the candidate to CI as an observation is **pending Q8** — no mechanism exists yet in either spec |
| E8 | No supplier leads found (Places + Tavily both empty/filtered out) | Reported as none found, `degraded_reason` names it |
| E9 | Seller asks PI to rank suppliers | Refused; routed via CEO to CFO once quotes exist (C4) — the CEO routing itself is undesigned/unimplemented (§6.8) |
| E10 | Seller asks for units sold | Explained as unavailable; proxy offered with its basis (C15) |
| E11 | A candidate's Stage-4 inputs (review insight, supplier leads) are incomplete | `shortlist_scoring.py`'s per-component `UNAVAILABLE` status names exactly which of proxy/sentiment/supplier was missing; `final_score_state=UNAVAILABLE` only if *none* of the three contributed (§6.3) |
| E12 | Duplicate/near-duplicate candidate across sources | Two-tier grouping at synthesis time (D6) merges exact/near-identical product names and Jaccard-similar titles; `embedding/`'s pgvector cosine-distance lookup is a second, later refinement pass for near-dups the cheap first pass missed |
| E13 | Run exceeds latency budget | `PARTIAL`; completed candidates retained |
| E14 | Embedding model changed | Detected via `model_name`/`model_dim`; re-index required before similarity is trusted |
| E15 | A real, cited price is unusually formatted and `_PRICE_PATTERN`'s regex misses or misparses it | `web_price_signal.status=UNAVAILABLE` for that candidate (no silent zero or guessed figure) — the regex extraction is a best-effort heuristic, not a guarantee (§0g) |
| E16 | Many tenants trigger discovery concurrently | `sources/rate_limiter.py`'s process-wide semaphore (3 concurrent/source) queues the overflow rather than fanning out 1:1 to Tavily/YouTube's shared quota; a caller that waits gets `AcquireOutcome.waited=True` internally, never a user-visible failure purely from queuing |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | **Tavily's and YouTube's real per-account rate limits under concurrent multi-tenant load** (A1) — not yet load-tested against real Metrion tenant volume | Discovery reliability at scale |
| V2 | **Category taxonomy mapping** (A3, Q3) — `discovery/feasibility.py` passes `niche_brief.category_text` to `resolve_fee_reference` as a raw string with no taxonomy normalization; a category spelled differently than a `fee_reference` row's own category text silently resolves to `Unavailable` (a named gap, never a crash, but likely a common one until this is solved) | Feasibility quality (§6.7 is wired; this affects how often it finds a real fee rate) |
| V3 | **Local Ollama extraction/classification quality and hallucination risk at run volume** (A2, A4) — no eval suite exists yet for either `product_extraction.py` or `text_extraction.py` (CLAUDE.md's "LLM evals required for any new Brain-3 narration surface" note applies once a real narration layer exists; classification-only prompts arguably need the same scrutiny sooner) | §6.3, §6.4 quality |
| V4 | Google Places quota and cost at scale | §6.6 |
| V5 | Legal review of Tavily/YouTube ToS at Metrion's actual commercial-use volume, and of supplier-contact retention under DPDP | Launch |
| V6 | **Dropped — resolved.** `estimate_product_feasibility` is wired (§6.7, 2026-10-01). | — |
| V7 | Google Ads API `KeywordPlanIdeaService` Basic-tier access, pending brand verification (C2) | `demand_signal` population only, not run completion |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | PI contains no financial formula. |
| AC1c | Every **feasibility estimate** for a discovered candidate carries an `estimate_ref` (`product_feasibility_estimate.id`) and never an `engine_result_ref`, per `estimate_product_feasibility`'s own contract — **wired and exercised end-to-end** (§6.7). PI never calls `margin_curve` for a candidate the seller does not own. |
| AC1d | PI never calls `estimate_competitor_margin_range`; `competitor_estimate` is CI-exclusive. |
| AC2 | `proxy_score`/`final_score` are never labelled as units sold, sales or revenue. |
| AC2b | **New.** No narrated or schema-fixed PI output ever uses "trending," "bestseller," "best-seller," or "popular" to describe a candidate (§0a). `opportunity_label`'s `CHECK` constraint and `narration_safety.py`'s check 2 are the structural/narrative enforcement points respectively. |
| AC2c | **New.** The word "review"/"reviews" never appears in narrated PI output unqualified by "viewer" or "web" nearby (§0b). `narration_safety.py`'s check 3 is the enforcement point. |
| AC3 | No raw YouTube comment or web-article snippet text is persisted anywhere, including vector storage. (Revised from "no review text, listing copy or rehosted image" — `candidate_title`/`image_url` are confirmed, deliberate exceptions, C7/C8, not covered by this AC.) |
| AC4 | No raw expression (comment/snippet text, or text fed to product-name extraction) is transmitted to a hosted model provider. |
| AC5 | No embedding is generated from `candidate_title` or any other raw source text — derived attributes only (D5). |
| AC6 | Every run is explicitly triggered; no scheduled discovery exists. |
| AC7 | Every run respects `candidate_cap`. (Allowlist language dropped — no domain allowlist applies to discovery any more, C6.) |
| AC8 | PI emits no supplier score or ranking. |
| AC10 | Every report carries an `unavailable[]` list. |
| AC11 | Qdrant is not used; all similarity runs on pgvector with `model_name`/`model_dim` recorded. |
| AC12 | PI output is structured. CEO composing seller-facing narrative is the design target (§6.9) — **not currently true end-to-end**, since no CEO orchestration exists; today's `pi.report` returns the structured object directly with no narration layer. |
| AC13 | Permission and entitlement are evaluated independently (confirmed real for `pi.discover`/`pi.supplier_lookup`, §6.8). |
| AC14 | Background runs without tenant context fail closed. |
| AC15 | No `product_candidate` field crosses into a Brain 1 call as anything stronger than `DERIVED` (§5.1) — confirmed live: `discovery/feasibility.py`'s `ProspectiveObservationSet.confidence` defaults to `Confidence.DERIVED` and is never overridden by a caller (§6.7). |
| AC16 | `pi.discover` accepts only `niche_brief_id` (+`depth`, +optional `candidate_cap`); no free-text or open `jsonb` field reaches a direct-path call (§6.1, §6.8). |
| AC17 | `pi.discover` is denied with `403` if either `agent.pi` or `research.niche_run` is missing (§6.8) — confirmed real in `api/v1/pi.py`. |
| AC18 | `embedding/embed.py` never embeds `candidate_title` or any other raw text — only `title_length`/`title_structure`/`keyword_themes` (D5). (Revised — `candidate_title` itself IS stored as real text on `product_candidate`, C7; this AC is scoped to the embedding path only, not storage.) |
| AC19 | **Dropped.** The original "complete strictly exceeds shallow" guarantee (old D2/D6) is not implemented — `depth` does not currently affect `candidate_cap` or any discovery behavior (§2 D2, §13). Restoring this AC requires the depth/cap coupling to actually be built first. |
| AC20 | No number in PI's structured report is emitted by an LLM; every number traces to a stored observation or (once wired) an engine result (§7). |
| AC21 | **New.** `score_explanation` (Stage 1) and `final_score_explanation` (Stage 4) are non-empty on every persisted `product_candidate`/scored shortlist entry — never a bare number with no explanation (§0d). |
| AC22 | **New.** `final_score_explanation` (Stage 4) is never byte-identical to, or a trivial rescaling comment of, Stage 1's `score_explanation` — it is independently composed from three distinct components (§0f, §6.3). |
| AC23 | **New.** `web_price_signal` is never read by `estimate_product_feasibility`, `margin_curve`, or any other calc-engine function — enforced structurally by `candidate_synthesis.py` having zero `calc_engine` import (§0g). |
| AC24 | **New.** Every real (non-cache-hit) outbound call to Tavily, YouTube, or Google Places passes through `sources/rate_limiter.py`'s `throttle()` — process-wide bounded concurrency per source, verifiable by inspecting each client call site (§6.2, §6.6). |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Complete-depth run, valid `READY` brief | Candidates synthesized from Tavily+YouTube signal, Stage-1-ranked, capped at `candidate_cap` |
| T2 | Tavily returns an error/times out for a query | That query's results degrade; YouTube-only candidates still synthesize; `capture_status` reflects it (E1) |
| T4 | Local Ollama model down for review-insight classification | Review insight `DEGRADED`/`UNAVAILABLE`; no outbound hosted-provider call (AC4, E4) |
| T4b | Local Ollama model down for product-name extraction | `candidate_synthesis.py` falls back to Jaccard grouping, `confidence=DERIVED_EXTRACTION_UNAVAILABLE`, distinct from a genuine empty-extraction result (E4/E4b, D6) |
| T5 | Grep all persisted stores for a known YouTube comment/web-snippet phrase | Zero hits (AC3) |
| T6 | Inspect `product_embedding` rows/prompts for raw `candidate_title` text | None; derived attributes only (AC5, AC18) |
| T7 | Seller asks "how many units sell?" | Proxy with basis, explicitly not a volume (AC2) |
| T7b | Scan any PI module/narration output for "trending"/"bestseller"/"popular" | Zero hits (AC2b, §0a) |
| T7c | Scan narrated output for an unqualified "review" | Zero hits — every occurrence qualified by "viewer"/"web" nearby (AC2c, §0b) |
| T8 | Seller asks PI to rank suppliers | Refused; CFO path named as the design, not a working route yet (E9, AC8) |
| T9 | **Dropped** — depended on the removed shallow/complete gating (old T9); no current behavior to test | — |
| T10 | Same product named across two Tavily/YouTube sources | Grouped by extraction-first or Jaccard-fallback matching; both sources retained in `source_urls` (E12, D6) |
| T11 | **Dropped** — depended on the removed marketplace-domain allowlist (old T11); no current enforcement point exists (C6) | — |
| T12 | Supplier lookup Tavily result that is an editorial/listicle article or a major retail storefront | Filtered out by `_looks_like_supplier` before ever becoming a `supplier_lead` row (C5, §6.6) |
| T13 | `pi.discover` by a partner with `agent.pi` **and** `research.niche_run`, no `agent.ceo` | Succeeds on the direct path — `agent.ceo` is never required off the conversational route (§6.8, C11) |
| T14 | Conversational PI request (no direct-path HTTP call) | Fails — no CEO dispatch exists for PI yet (§6.8); distinct from the original "403 for missing agent.ceo" expectation, since the conversational route itself isn't built |
| T15 | No run credit | Denied by entitlement (`402`), not permission (AC13) |
| T16 | Inspect PI for a fee rate table | None present (AC1) |
| T17 | Embedding model swapped | Mismatch detected; re-index required (E14) |
| T18 | Zero candidates found | Empty result with reasons (E6) |
| T20 | `pi.discover` called with a `category_text` field instead of `niche_brief_id` | Rejected by the Pydantic request model — direct paths accept only the enumerated fields (AC16) |
| T21 | `pi.discover` with `agent.pi` but no `research.niche_run` | `403` (AC17) |
| T22 | Inspect `product_candidate.candidate_title` | Real, lightly-cleaned source-derived text present (confirmed exception, C7) — distinct from the embedding path, which never includes it (T6) |
| T23 | **Dropped** — depended on the removed depth/cap coupling (old D2/D6); see AC19 | — |
| T24 | PI attempts `estimate_competitor_margin_range` | Not callable; interface absent from PI's surface (AC1d) |
| T25 | A full `pi.discover` run against a `niche_brief` with a stated target-price band and budget | Every shortlisted candidate's `feasibility_status=COMPUTED`, with `feasibility_estimate_ref`/`feasibility_low_paise`/`feasibility_high_paise`/`feasibility_cogs_basis` populated and a real row in calc-engine's `product_feasibility_estimate` table — exercised via `test_pi_discover.py`'s dedicated wiring test, `product_feasibility_estimate_repo`'s integration tests, and a live run (AC1c, §6.7) |
| T26 | **New.** Run `shortlist_scoring.score_shortlist` twice on the same input, once with real review/supplier data and once with all three components UNAVAILABLE | First run's `final_score_explanation` differs substantively from a would-be Stage-1-only re-export; second run yields `final_score_state=UNAVAILABLE` (AC22, §0f) |
| T27 | **New.** Inspect every `product_candidate.score_explanation` in a completed run | Non-empty `signals`/`summary` on every row, including `UNAVAILABLE`-state candidates (AC21, §0d) |
| T28 | **New.** Submit 10 concurrent `pi.discover` calls for different niches in a test harness | No more than 3 concurrent real Tavily calls, 3 real YouTube calls, observed at any instant (AC24, `rate_limiter.py`) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q3 | **Category taxonomy mapping** — the same gap as CI Q8. `niche_brief.category_text` (free text) to `fee_reference`'s category vocabulary. | 🔴 Feasibility, once wired |
| Q4 | **`proxy_score`/`final_score` point weights** (`ranking.py`'s 3/3/4 split, `shortlist_scoring.py`'s 40/30/30 split) — chosen as "deliberately small integers" for exact-`Fraction` arithmetic, not validated against real seller feedback on what should matter most. | §6.3 |
| Q5 | **Brain 2 spec does not exist** (readiness §7 item 8); PI has no Brain-2 dependency today. | §7 |
| Q6 | **Supplier contact retention window** under DPDP — 90-day default is provisional. | §6.6, V5 |
| Q9 | **Dropped — resolved.** `estimate_product_feasibility` is wired into `pi_discover.py`'s shortlist pass; `pi.report`/`pi_report.py` surfaces it per-candidate via the `feasibility_*` columns (§6.7, §5). Remaining open question is Q3 (category-taxonomy mapping affecting how often a real fee rate resolves), not whether the wiring exists. | — |
| Q10 | **`depth` (SHALLOW/COMPLETE)'s real effect.** `pi_research_run.depth` is recorded but doesn't currently change `candidate_cap`, enrichment scope, or entitlement cost. Is a real shallow/complete distinction (free vs. paid tier) still wanted, and if so, where does it get implemented — the HTTP layer, `discovery_run.py`, or entitlement resolution? | §2 D2, C12 |
| Q11 | **CEO Hub wiring timing.** `dispatch_pi_*` functions, conversational access, the CFO batch-size handoff, and `final_recommendation` composition are all designed (§6.8) but explicitly **not started**, per the user's standing instruction that this work is never begun without separate, explicit approval — not a silent next step after this spec update. | 🔴 §6.8, §6.9 |
| Q12 | **Google Ads API `KeywordPlanIdeaService` access.** Brand verification (owned domain + Google Cloud project) is a precondition Metrion doesn't have ready; once it does, Basic-tier access is expected to be fast (minutes-to-hours, no spend requirement per Checkpoint 0's finding). Tracked here so `demand_signal`'s permanent `UNAVAILABLE` state isn't mistaken for a dead end. | C2, §1 |
| Q13 | **Free-text constraint extraction.** `niche_brief.constraints.exclude_brands` (D7) is seller-authored structured input only. Should a seller's free-text brief ("skip anything from a big established brand") be turned into this same structured list via a local-model classification pass? Legitimate, same classify-only discipline as `product_extraction.py` — not started. | D7 |
| Q14 | **Supplier-lead images.** Google Places API (New) supports a separate, paid Photos endpoint for a business's own storefront photo — not called anywhere in this build. Would add real cost and a new API surface; raised here, not silently assumed to exist. | §6.6, C5 |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Supplier ranking | **PI discovers only** (C4). CFO ranks from seller quotes. |
| R2 | Units sold | **Not obtainable.** Proxy score with declared basis (C15, D1). |
| R3 | Qdrant | **Not used.** pgvector, dimension pinned (C13). |
| R4 | Review/commentary text | **Transient, local-only, never persisted** (C7, C9). |
| R5 | Trends in V1 | **No — reversed.** Trends is dropped from PI entirely and reassigned to CMO; not this spec's concern (C14, supersedes the original "Yes, best-effort" resolution). |
| R6 | Feasibility provenance contract | **Resolved and wired** via `deterministic-engine.md` §5.13.2 (§6.7, 2026-10-01). Discovered candidates get a dedicated `estimate_product_feasibility` interface returning `estimate_ref`, structurally separate from CFO's `margin_curve` (`engine_result_ref`) and from CI's `competitor_estimate`. PI never calls either of the other two (D4, §6.7, AC1c/AC1d). **`stated_cogs_paise` is optional and seller-quote-sourced only — always absent in the current build, since no supplier-quote mechanism exists in PI yet; every real estimate is `cogs_basis=UNKNOWN`.** |
| R13 | Retention policy for observed data | **Resolved.** `pi_tenant_config` (§5), default 90 days. |
| R14 | `agent.pi` vs `research.niche_run` in C11 | **Resolved.** C11 states the two-key requirement explicitly; confirmed real in `api/v1/pi.py` (§6.8). |
| R7 | `research.niche_run` permission treatment | **Resolved — matches `cfo-agent.md`/`slim-cmo-agent.md`.** Two independent keys, `403` if either is missing (§6.8, AC17). |
| R8 | Free-form input on a direct path | **Resolved.** Authoring a `niche_brief` is a plain form, never a direct-path trigger. `pi.discover` accepts only the enumerated fields (§6.1, §6.8, AC16). |
| R9 | Title embedding vs storage | **Resolved, with a confirmed exception.** Embedding is derived-attribute-only (D5, AC18 as revised). Storage of `candidate_title` as real text is a deliberate, confirmed reversal from this spec's original "never a paraphrase" stance — scoped to storage only, not embedding (C7). |
| R10 | Shallow/complete candidate-count inversion | **Reversed — not implemented.** See Q10/AC19 (dropped). |
| R11 | `proxy_score` suppression on first run | **Resolved, differently than originally described.** There is no cross-run "review velocity" concept in the real code at all (§6.3) — `proxy_state` distinguishes "no signal this run" from "computed this run," full stop, not "no prior-run history." |
| R12 | Brain 3 number-emission boundary | **Resolved.** Same rule as `cfo-agent.md` AC2 — no LLM-originated number anywhere in PI's output (§7, AC20). |
| R15 | Discovery source stack | **Resolved.** Tavily + YouTube Data API v3, marketplace-agnostic; Google Ads Keyword demand deferred pending brand verification (C2, Q12). |
| R16 | Allowlist enforcement for discovery | **Resolved — removed.** No domain allowlist applies; Tavily/YouTube are themselves the licensed sources (C6). |
| R17 | Review velocity / multi-run comparison | **Resolved — not built.** No cross-run signal exists in `ranking.py`; dropped from this spec's description of current behavior (§6.3). |
