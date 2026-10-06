# Market-signal provider capabilities (P7-0 probe)

**Status:** measured 2026-10-04 by a read-only probe. Spec ref: `slim-cmo-agent.md` §6.8, V9, Q16.
**Scope of the evidence:** 8 Tavily searches (2 neutral product queries × 4 modes) and 1 YouTube search + 1 statistics lookup. One day, one account, tiny sample. Findings below are "observed", not guaranteed; re-probe before launch. No seller data was sent: queries were generic product words.

## Tavily (web search)

| Question (spec V9) | Observed | Status |
|---|---|---|
| News / recency mode exists and works | **Yes.** `topic="news"` with `time_range="week"` or `days=30` returns results (2–6 per query for niche queries). | MET |
| `published_date` coverage | **0 of 20** results in general mode; **16 of 16** in news mode. Format is RFC-2822 (`Thu, 01 Oct 2026 07:00:00 GMT`); `slim_cmo.trends.sources.parse_published_date` parses it. | MET for news mode only. General-mode items are `DATE_UNKNOWN` by construction. |
| India bias | `country="india"` is accepted in general mode (8–10 results). It was **not** accepted-and-verified for news mode (only general was tested). Whether results are actually India-relevant was not assessed. | PARTIAL — unverified relevance |
| Per-query result volume | `max_results` 10 honoured; news mode returned far fewer (2–6): thin for niche terms, so corroboration will often be WEAK/INSUFFICIENT. | Expect sparse sections; report honestly |
| Extra fields | Results also carry `score`, `raw_content` (null unless requested), `id`; response carries a model-written `answer` — **must never be used** (model output, not evidence). | Ignore `answer` |
| Quota | 8 credits consumed for 8 basic searches (1 per search). Free tier is 1,000 credits/month (PI plan); budgets must be set from this. | MET (config H5) |
| Terms of use for this purpose | Not assessed here. | **OPEN — legal review H9** |

**Consequence for the design:** the News and Competitor-tactics sections should use news mode (dated); general-mode searches feed only sections where `DATE_UNKNOWN` is acceptable and capped at WEAK, exactly as spec §6.8 already requires. No spec change needed.

## YouTube Data API v3

| Question | Observed | Status |
|---|---|---|
| Channel identifier for the independence key | `snippet.channelId` present on **10 of 10**. | MET (use `channelId`, not `channelTitle`) |
| Publication date | `snippet.publishedAt` present on 10 of 10. | MET |
| View counts | `videos.list part=statistics` returned `viewCount` for 10 of 10 (nullable in general; handle absence). | MET |
| India bias | `regionCode="IN"` accepted. Relevance not assessed. | PARTIAL |
| Quota | `search.list` costs ~100 units per call, `videos.list` ~1 (documented YouTube pricing, not measured); default daily quota is 10,000 units → roughly 100 searches/day account-wide. | Budget accordingly (H5) |
| Result cap | 10 returned for `maxResults=10`; API allows up to 50. | MET |

## Gaps that stay open
1. **Legal/ToS review (H9)** for using both providers for trend research — blocks launch of trends, not building.
2. News-mode India relevance and the `country` parameter in news mode: re-probe with the real configured terms before launch.
3. Thin news volume for niche terms: sections will frequently be `INSUFFICIENT`; this is correct behaviour, but the UI must say so.
4. Probe was a single day; recency/volume vary. Provider behaviour is not a contract.

## Requirements the providers cannot meet (reported, never emulated)
- Search **volume / demand** numbers: neither provider offers them. Attention signals only (spec §6.8 "attention ≠ demand").
- Dates on general-mode web results: unavailable → `DATE_UNKNOWN`.
