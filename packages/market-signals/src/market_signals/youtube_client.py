"""The seam between discovery/review-insight and the YouTube Data API v3 — same
Protocol + frozen dataclass shape as `tavily_client.py` and
`competitor_intelligence.discovery.search_provider`.

Confirmed source (PI build plan, Checkpoint 0): YouTube Data API v3 is a live V1 source
(free, 10,000 units/day quota, search=100 units, most reads=1 unit). Feeds
`product_candidate.engagement_signal` (view/comment counts) and
`product_review_insight` rows tagged `insight_source_type=YOUTUBE_COMMENTARY`
(`review_insight/text_extraction.py`, Checkpoint 2).

**Checkpoint 2: real.** `HttpYoutubeClient` now calls the real `search`/`videos`/
`commentThreads` endpoints under `https://www.googleapis.com/youtube/v3/`
(`YOUTUBE_API_KEY` env var, no default). `search_videos` costs one `search.list` call
(100 units) plus one `videos.list` call (1 unit) to backfill view/comment counts and
published date in a single batched read, per this module's own quota discipline note
(search is the expensive call — never called more than once per query here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from market_signals.errors import describe

_BASE_URL = "https://www.googleapis.com/youtube/v3"


class YoutubeUnavailable(Exception):
    """The YouTube Data API could not be reached, timed out, returned a non-2xx response, or
    hit its daily quota — never a reason to fabricate results. Same degraded-run contribution
    as `TavilyUnavailable`."""


@dataclass(frozen=True, slots=True)
class YoutubeVideo:
    """One search/read result. `top_comments` is raw text — held only in memory for the
    duration of a single `review_insight/text_extraction.py` classification pass (Checkpoint
    2), never persisted verbatim to Postgres (mirrors CI's `capture/fetcher.py` RawPage
    convention: transient, never stored)."""

    video_id: str
    title: str
    channel_title: str
    view_count: int | None
    comment_count: int | None
    thumbnail_url: str
    published_at: datetime
    top_comments: tuple[str, ...] = ()
    retrieved_at: datetime = datetime.min
    channel_id: str | None = None  # snippet.channelId; the stable independence key (market-signals plan 7c-ii)


class YoutubeClient(Protocol):
    def search_videos(
        self,
        query: str,
        *,
        max_results: int = 10,
        region_code: str | None = None,
        order: str | None = None,
        published_after: datetime | None = None,
    ) -> list[YoutubeVideo]: ...

    def top_comments_for(self, video_id: str, *, max_comments: int = 20) -> list[str]: ...


class HttpYoutubeClient:
    """The real client, wired up only at the composition root (`direct_path/`). Generic
    YouTube Data API v3 I/O only — no discovery-specific ranking/synthesis logic lives here."""

    def __init__(self, *, api_key: str, timeout_seconds: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{_BASE_URL}/{path}",
                params={**params, "key": self._api_key},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise YoutubeUnavailable(f"YouTube Data API request failed: {describe(exc)}") from None  # never chain: the original carries the key-bearing URL
        try:
            parsed = response.json()
        except ValueError as exc:
            raise YoutubeUnavailable("YouTube Data API response was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise YoutubeUnavailable("YouTube Data API response was not a JSON object")
        return parsed

    def search_videos(
        self,
        query: str,
        *,
        max_results: int = 10,
        region_code: str | None = None,
        order: str | None = None,
        published_after: datetime | None = None,
    ) -> list[YoutubeVideo]:
        # `region_code` / `order` / `published_after` are CMO-only options (market-signals plan 7c-ii): each is OMITTED
        # from the request when None, so Product Intelligence's search request is byte-identical to before.
        retrieved_at = datetime.now(timezone.utc)
        search_params: dict[str, Any] = {"part": "snippet", "q": query, "type": "video", "maxResults": max_results}
        if region_code is not None:
            search_params["regionCode"] = region_code
        if order is not None:
            search_params["order"] = order
        if published_after is not None:
            search_params["publishedAfter"] = published_after.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        search_body = self._get("search", search_params)
        items = search_body.get("items")
        if not isinstance(items, list):
            raise YoutubeUnavailable("YouTube Data API search response had no 'items' list")

        video_ids: list[str] = []
        snippets: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = item.get("id", {}).get("videoId") if isinstance(item.get("id"), dict) else None
            snippet = item.get("snippet")
            if not isinstance(video_id, str) or not isinstance(snippet, dict):
                continue
            video_ids.append(video_id)
            snippets[video_id] = snippet

        if not video_ids:
            return []

        # One batched videos.list read (1 unit) backfills view/comment counts for every
        # result from the single search.list call above — the module docstring's quota
        # discipline: search is the expensive call, never repeated per-video.
        stats_body = self._get(
            "videos",
            {"part": "statistics", "id": ",".join(video_ids)},
        )
        stats_items = stats_body.get("items")
        stats_by_id: dict[str, dict[str, Any]] = {}
        if isinstance(stats_items, list):
            for item in stats_items:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    statistics = item.get("statistics")
                    stats_by_id[item["id"]] = statistics if isinstance(statistics, dict) else {}

        videos: list[YoutubeVideo] = []
        for video_id in video_ids:
            snippet = snippets[video_id]
            statistics = stats_by_id.get(video_id, {})
            thumbnails = snippet.get("thumbnails")
            thumbnail_url = ""
            if isinstance(thumbnails, dict):
                for size in ("high", "medium", "default"):
                    candidate = thumbnails.get(size)
                    if isinstance(candidate, dict) and isinstance(candidate.get("url"), str):
                        thumbnail_url = candidate["url"]
                        break
            published_raw = snippet.get("publishedAt")
            try:
                published_at = (
                    datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                    if isinstance(published_raw, str)
                    else retrieved_at
                )
            except ValueError:
                published_at = retrieved_at

            view_count_raw = statistics.get("viewCount")
            comment_count_raw = statistics.get("commentCount")

            videos.append(
                YoutubeVideo(
                    video_id=video_id,
                    title=str(snippet.get("title", "")),
                    channel_title=str(snippet.get("channelTitle", "")),
                    view_count=int(view_count_raw) if isinstance(view_count_raw, str) and view_count_raw.isdigit() else None,
                    comment_count=int(comment_count_raw)
                    if isinstance(comment_count_raw, str) and comment_count_raw.isdigit()
                    else None,
                    thumbnail_url=thumbnail_url,
                    published_at=published_at,
                    top_comments=(),
                    retrieved_at=retrieved_at,
                    channel_id=snippet["channelId"] if isinstance(snippet.get("channelId"), str) and snippet["channelId"] else None,
                )
            )
        return videos

    def top_comments_for(self, video_id: str, *, max_comments: int = 20) -> list[str]:
        try:
            body = self._get(
                "commentThreads",
                {
                    "part": "snippet",
                    "videoId": video_id,
                    "maxResults": max_comments,
                    "order": "relevance",
                    "textFormat": "plainText",
                },
            )
        except YoutubeUnavailable:
            # Comments can be disabled per-video (moderation restriction, Context's own
            # "not yet verified" flag) — that degrades this one video's comments to empty,
            # never a hard failure of the whole search_videos() call.
            return []

        items = body.get("items")
        if not isinstance(items, list):
            return []

        comments: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet", {})
            top_level = snippet.get("topLevelComment", {}) if isinstance(snippet, dict) else {}
            comment_snippet = top_level.get("snippet", {}) if isinstance(top_level, dict) else {}
            text = comment_snippet.get("textDisplay") if isinstance(comment_snippet, dict) else None
            if isinstance(text, str) and text.strip():
                comments.append(text.strip())
        return comments
