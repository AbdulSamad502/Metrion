"""The discovery-run orchestrator — PI build plan §2/Context "Rate-limit/scale concern".

Queries Tavily (+images) and YouTube for a niche's category/keyword terms, bounded to
`candidate_cap` (default 30, `pi_tenant_config`-configurable), through `sources/cache.py`
keyed by **normalized query text, not tenant** — the deliberate concurrency/rate-limit fix
this package's cache module's own docstring documents (two tenants asking about "wireless
earbuds" this hour hit the same cache entry, not each their own Tavily/YouTube quota).

A source that errors or hits its own cap degrades to `UNAVAILABLE` **for this run** — never a
hard failure of the whole run (`TavilyUnavailable`/`YoutubeUnavailable` are both caught here
and folded into `capture_status`/`partial_reason`, mirroring CI's own
`query_result.partial_reason` pattern in `competitor_intelligence.discovery.discovery_run`).

This module owns the `QUEUED -> RUNNING` transition and the search/synthesis/Stage-1-ranking
work; it does **not** call `pi_research_run_repo.finish_run` itself — `direct_path/pi_discover.py`
(the caller) finishes the run only after review_insight + embedding have also run against the
resulting shortlist, so a single `pi_research_run.status` value always reflects the *whole*
direct-path call, not just this module's slice of it.

**Concurrency (bug-fix pass, 2026-09-30):** the 3 Tavily queries and 3 YouTube queries were
previously run sequentially — none of this is CPU-bound, it's all I/O-bound network calls, so
they now run through a bounded `ThreadPoolExecutor` (`_MAX_CONCURRENT_QUERIES` workers,
deliberately bounded so a run doesn't hammer free-tier rate limits). Tavily and YouTube each
get their own small pool. Every result/exception is collected per-future and folded into the
shared lists/degradation flags on the *main* thread only, after `as_completed` — worker
threads never mutate `tavily_results`/`youtube_results`/the `*_degraded`/`*_partial_reason`
locals directly, so the existing degrade-not-fail behavior is preserved exactly, just no
longer serialized. `sources/cache.py`'s `InProcessQueryCache` is now internally lock-guarded
for exactly this reason (its own docstring).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from product_intelligence.discovery.candidate_synthesis import dedupe_by_normalized_title, synthesize_candidates
from product_intelligence.discovery.product_extraction import ProductExtractionClient, ProductExtractionUnavailable
from product_intelligence.discovery.ranking import rank_candidate
from product_intelligence.repositories import pi_research_run_repo, pi_tenant_config_repo, product_candidate_repo
from product_intelligence.sources.cache import QueryCache, normalize_query_text
from product_intelligence.sources.tavily_client import TavilyClient, TavilyImage, TavilySearchResult, TavilyUnavailable
from product_intelligence.sources.youtube_client import YoutubeClient, YoutubeUnavailable, YoutubeVideo

DEFAULT_CANDIDATE_CAP = 30
_MAX_RESULTS_PER_TAVILY_QUERY = 10
_MAX_RESULTS_PER_YOUTUBE_QUERY = 10
_MAX_CONCURRENT_QUERIES = 5  # bounded deliberately — see module docstring's concurrency note
_MAX_COMMENTS_PER_VIDEO_FOR_ENGAGEMENT = 0  # engagement uses counts only; comments are read
# separately, only for the post-Stage-1 shortlist, by review_insight/ — never fetched here,
# since top_comments_for() is a comments-read call this module has no use for at discovery time.


@dataclass(frozen=True, slots=True)
class CandidateRawSignals:
    """Ephemeral, in-memory-only bundle for one candidate — never persisted (see
    `candidate_synthesis.SynthesizedCandidate`'s own docstring). `direct_path/pi_discover.py`
    uses this immediately, in the same call chain, to fetch YouTube comments and hand both
    comments and web snippet text to `review_insight/submit.py` — the raw text itself never
    round-trips through a repository."""

    youtube_video_ids: tuple[str, ...]
    web_snippet_texts: tuple[str, ...]
    primary_youtube_source_url: str | None
    primary_web_source_url: str | None


@dataclass(frozen=True, slots=True)
class _PrecomputedExtraction:
    mentions: list[str] | None  # None means extraction failed/was unavailable for this text
    reason: str | None = None


class _PrecomputedProductExtractionClient:
    """Wraps already-computed extraction outcomes (run concurrently, see
    `_run_product_extraction_concurrently`) behind the `ProductExtractionClient` Protocol so
    `candidate_synthesis.synthesize_candidates` can stay simple/sequential/deterministic and
    easily unit-testable, while the actual Ollama calls that fed it ran through a bounded
    `ThreadPoolExecutor` — same "worker threads never mutate shared state directly, results
    are folded in on the main thread after `as_completed`" discipline as this module's own
    Tavily/YouTube concurrency (module docstring)."""

    def __init__(self, results: dict[str, _PrecomputedExtraction]) -> None:
        self._results = results

    def extract_products(self, text: str, *, category_text: str) -> list[str]:
        outcome = self._results.get(text)
        if outcome is None or outcome.mentions is None:
            reason = outcome.reason if outcome else "no precomputed extraction available for this text"
            raise ProductExtractionUnavailable(reason)
        return outcome.mentions


def _run_product_extraction_concurrently(
    texts: list[str], *, category_text: str, client: ProductExtractionClient
) -> dict[str, _PrecomputedExtraction]:
    """Runs one extraction call per distinct non-empty text through the same bounded
    `ThreadPoolExecutor` pattern as the Tavily/YouTube query pools above — potentially ~6-20
    calls per run (module docstring's concurrency note), all I/O-bound. A failure for one
    text degrades only that text's entry (`mentions=None`, caller falls back per-result); it
    never raises out of this function."""
    results: dict[str, _PrecomputedExtraction] = {}
    unique_texts = [t for t in dict.fromkeys(texts) if t.strip()]
    if not unique_texts:
        return results
    with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_QUERIES, len(unique_texts))) as executor:
        future_to_text = {
            executor.submit(client.extract_products, text, category_text=category_text): text
            for text in unique_texts
        }
        for future in as_completed(future_to_text):
            text = future_to_text[future]
            try:
                mentions = future.result()
            except ProductExtractionUnavailable as exc:
                results[text] = _PrecomputedExtraction(mentions=None, reason=str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 — any unexpected client error degrades
                # only this text's entry, same as an explicit ProductExtractionUnavailable.
                results[text] = _PrecomputedExtraction(mentions=None, reason=str(exc))
                continue
            results[text] = _PrecomputedExtraction(mentions=mentions)
    return results


@dataclass(frozen=True, slots=True)
class DiscoveryRunOutcome:
    run_id: UUID
    status: str  # PARTIAL | COMPLETE (never COMPLETE with hidden gaps — see partial_reason)
    candidate_ids: tuple[UUID, ...]
    partial_reason: str | None
    tavily_degraded: bool
    youtube_degraded: bool
    raw_signals_by_candidate: dict[UUID, CandidateRawSignals]


def _queries_for_niche(category_text: str | None) -> list[str]:
    base = (category_text or "").strip()
    if not base:
        return []
    return [base, f"best {base} india", f"{base} review"]


def _tavily_result_to_dict(result: TavilySearchResult) -> dict[str, Any]:
    return {
        "url": result.url,
        "title": result.title,
        "content": result.content,
        "score": result.score,
        "published_date": result.published_date,
        "retrieved_at": result.retrieved_at.isoformat(),
    }


def _dict_to_tavily_result(row: dict[str, Any]) -> TavilySearchResult:
    return TavilySearchResult(
        url=row["url"],
        title=row["title"],
        content=row["content"],
        score=row["score"],
        published_date=row["published_date"],
        retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
    )


def _tavily_image_to_dict(image: TavilyImage) -> dict[str, Any]:
    return {"url": image.url, "source_url": image.source_url, "description": image.description}


def _dict_to_tavily_image(row: dict[str, Any]) -> TavilyImage:
    return TavilyImage(url=row["url"], source_url=row["source_url"], description=row["description"])


def _youtube_video_to_dict(video: YoutubeVideo) -> dict[str, Any]:
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel_title": video.channel_title,
        "view_count": video.view_count,
        "comment_count": video.comment_count,
        "thumbnail_url": video.thumbnail_url,
        "published_at": video.published_at.isoformat(),
        "retrieved_at": video.retrieved_at.isoformat(),
    }


def _dict_to_youtube_video(row: dict[str, Any]) -> YoutubeVideo:
    return YoutubeVideo(
        video_id=row["video_id"],
        title=row["title"],
        channel_title=row["channel_title"],
        view_count=row["view_count"],
        comment_count=row["comment_count"],
        thumbnail_url=row["thumbnail_url"],
        published_at=datetime.fromisoformat(row["published_at"]),
        top_comments=(),
        retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
    )


def _cached_tavily_search(
    query: str, *, tavily: TavilyClient, cache: QueryCache, ttl_hours: int, now: datetime
) -> tuple[list[TavilySearchResult], list[TavilyImage]]:
    cache_key = f"search::{normalize_query_text(query)}"
    cached = cache.get("tavily", cache_key, now=now)
    if cached is not None:
        payload = cached
    else:
        results = tavily.search(query, include_images=True, max_results=_MAX_RESULTS_PER_TAVILY_QUERY)
        images = tavily.images_for(query, max_images=5)
        payload = {
            "results": [_tavily_result_to_dict(r) for r in results],
            "images": [_tavily_image_to_dict(i) for i in images],
        }
        cache.put("tavily", cache_key, payload, ttl_hours=ttl_hours, now=now)

    return (
        [_dict_to_tavily_result(r) for r in payload["results"]],
        [_dict_to_tavily_image(i) for i in payload["images"]],
    )


def _cached_youtube_search(
    query: str, *, youtube: YoutubeClient, cache: QueryCache, ttl_hours: int, now: datetime
) -> list[YoutubeVideo]:
    cache_key = f"search::{normalize_query_text(query)}"
    cached = cache.get("youtube", cache_key, now=now)
    if cached is not None:
        return [_dict_to_youtube_video(v) for v in cached]

    videos = youtube.search_videos(query, max_results=_MAX_RESULTS_PER_YOUTUBE_QUERY)
    cache.put("youtube", cache_key, [_youtube_video_to_dict(v) for v in videos], ttl_hours=ttl_hours, now=now)
    return videos


def run_discovery(
    tenant_id: UUID,
    *,
    run_id: UUID,
    niche_brief: dict[str, Any],
    tavily: TavilyClient,
    youtube: YoutubeClient,
    cache: QueryCache,
    candidate_cap: int = DEFAULT_CANDIDATE_CAP,
    product_extraction_client: ProductExtractionClient | None = None,
    now: datetime | None = None,
) -> DiscoveryRunOutcome:
    """Runs the SEARCHING+DISCOVERING+Stage-1-ranking pass for an already-created
    (`QUEUED`) `pi_research_run` row. `niche_brief` is the dict `niche_brief_repo.get_brief`
    returns. `product_extraction_client=None` (the default) preserves the exact previous
    whole-title/Jaccard-overlap synthesis behavior; when supplied, per-result product-name
    extraction runs first, concurrently (`_run_product_extraction_concurrently`), feeding
    `candidate_synthesis.py`'s two-tier grouping (that module's own docstring)."""
    now = now or datetime.now(timezone.utc)
    pi_research_run_repo.update_status(tenant_id, run_id, status="RUNNING", started_at=now)

    tavily_ttl = pi_tenant_config_repo.get_tavily_cache_ttl_hours(tenant_id)
    youtube_ttl = pi_tenant_config_repo.get_youtube_cache_ttl_hours(tenant_id)

    queries = _queries_for_niche(niche_brief.get("category_text"))

    tavily_results: list[TavilySearchResult] = []
    tavily_images: list[TavilyImage] = []
    tavily_degraded = False
    tavily_partial_reason: str | None = None
    if queries:
        with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_QUERIES, len(queries))) as executor:
            future_to_query = {
                executor.submit(
                    _cached_tavily_search, query, tavily=tavily, cache=cache, ttl_hours=tavily_ttl, now=now
                ): query
                for query in queries
            }
            for future in as_completed(future_to_query):
                query = future_to_query[future]
                try:
                    results, images = future.result()
                except TavilyUnavailable as exc:
                    tavily_degraded = True
                    tavily_partial_reason = f"Tavily unavailable for query {query!r}: {exc}"
                    continue
                tavily_results.extend(results)
                tavily_images.extend(images)

    youtube_videos: list[YoutubeVideo] = []
    youtube_degraded = False
    youtube_partial_reason: str | None = None
    if queries:
        with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_QUERIES, len(queries))) as executor:
            future_to_query = {
                executor.submit(
                    _cached_youtube_search, query, youtube=youtube, cache=cache, ttl_hours=youtube_ttl, now=now
                ): query
                for query in queries
            }
            for future in as_completed(future_to_query):
                query = future_to_query[future]
                try:
                    videos = future.result()
                except YoutubeUnavailable as exc:
                    youtube_degraded = True
                    youtube_partial_reason = f"YouTube unavailable for query {query!r}: {exc}"
                    continue
                youtube_videos.extend(videos)

    category_text = niche_brief.get("category_text")
    precomputed_extraction_client: ProductExtractionClient | None = None
    if product_extraction_client is not None:
        extraction_texts = [f"{r.title}\n{r.content}".strip() for r in tavily_results] + [
            f"{v.title} — {v.channel_title}".strip(" —") for v in youtube_videos
        ]
        precomputed = _run_product_extraction_concurrently(
            extraction_texts, category_text=category_text or "", client=product_extraction_client
        )
        precomputed_extraction_client = _PrecomputedProductExtractionClient(precomputed)

    synthesized = synthesize_candidates(
        tavily_results=tavily_results,
        tavily_images=tavily_images,
        youtube_videos=youtube_videos,
        now=now,
        tavily_degraded=tavily_degraded,
        youtube_degraded=youtube_degraded,
        product_extraction_client=precomputed_extraction_client,
        category_text=category_text,
    )

    rows = [
        {
            "candidate_title": c.candidate_title,
            "title_length": c.title_length,
            "title_structure": c.title_structure,
            "keyword_themes": c.keyword_themes,
            "observed_category": c.observed_category,
            "category_confidence": c.category_confidence,
            "image_url": c.image_url,
            "image_source_url": c.image_source_url,
            "demand_signal": c.demand_signal,
            "engagement_signal": c.engagement_signal,
            "web_price_signal": c.web_price_signal,
            "source_diversity": c.source_diversity,
            "source_urls": c.source_urls,
            "capture_status": c.capture_status,
            "confidence": c.confidence,
            "_raw": CandidateRawSignals(
                youtube_video_ids=c.youtube_video_ids,
                web_snippet_texts=c.web_snippet_texts,
                primary_youtube_source_url=c.primary_youtube_source_url,
                primary_web_source_url=c.primary_web_source_url,
            ),
        }
        for c in synthesized
    ]
    rows = dedupe_by_normalized_title(rows)[:candidate_cap]

    candidate_ids: list[UUID] = []
    raw_signals_by_candidate: dict[UUID, CandidateRawSignals] = {}
    marketplaces = niche_brief.get("marketplaces")
    for row in rows:
        ranked = rank_candidate(
            None, engagement_signal=row["engagement_signal"], source_diversity=row["source_diversity"]
        )
        candidate_id = product_candidate_repo.insert_candidate(
            tenant_id,
            run_id=run_id,
            candidate_title=row["candidate_title"],
            title_length=row["title_length"],
            title_structure=row["title_structure"],
            keyword_themes=row["keyword_themes"],
            observed_category=row["observed_category"],
            category_confidence=row["category_confidence"],
            image_url=row["image_url"],
            image_source_url=row["image_source_url"],
            demand_signal=row["demand_signal"],
            engagement_signal=row["engagement_signal"],
            web_price_signal=row["web_price_signal"],
            source_diversity=row["source_diversity"],
            proxy_score=ranked.proxy_score,
            proxy_state=ranked.proxy_state,
            proxy_basis=ranked.proxy_basis,
            score_explanation=ranked.score_explanation,
            candidate_marketplaces=marketplaces if isinstance(marketplaces, list) else None,
            source_urls=row["source_urls"],
            capture_status=row["capture_status"],
            confidence=row["confidence"],
        )
        candidate_ids.append(candidate_id)
        raw_signals_by_candidate[candidate_id] = row["_raw"]

    partial_reason = None
    if tavily_partial_reason or youtube_partial_reason or not rows:
        parts = [r for r in (tavily_partial_reason, youtube_partial_reason) if r]
        if not rows:
            parts.append("no candidates were synthesized from available search/video signal")
        partial_reason = "; ".join(parts) if parts else None

    status = "PARTIAL" if partial_reason else "COMPLETE"
    pi_research_run_repo.update_status(tenant_id, run_id, status=status)

    return DiscoveryRunOutcome(
        run_id=run_id,
        status=status,
        candidate_ids=tuple(candidate_ids),
        partial_reason=partial_reason,
        tavily_degraded=tavily_degraded,
        youtube_degraded=youtube_degraded,
        raw_signals_by_candidate=raw_signals_by_candidate,
    )
