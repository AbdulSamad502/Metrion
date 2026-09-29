"""The seam between discovery/review-insight and the YouTube Data API v3 — same
Protocol + frozen dataclass shape as `tavily_client.py` and
`competitor_intelligence.discovery.search_provider`.

Confirmed source (PI build plan, Checkpoint 0): YouTube Data API v3 is a live V1 source
(free, 10,000 units/day quota, search=100 units, most reads=1 unit). Feeds
`product_candidate.engagement_signal` (view/comment counts) and
`product_review_insight` rows tagged `insight_source_type=YOUTUBE_COMMENTARY`
(`review_insight/text_extraction.py`, Checkpoint 2).

**Checkpoint 1 scaffolding only.** `YoutubeClient` (the Protocol) and the result dataclasses
are real and complete. `HttpYoutubeClient` is a stub raising `NotImplementedError`; the real
HTTP call lands in Checkpoint 2. No implementation of `YoutubeClient` beyond this stub exists
in this codebase yet, and nothing under `tests/` may construct `HttpYoutubeClient`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


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


class YoutubeClient(Protocol):
    def search_videos(self, query: str, *, max_results: int = 10) -> list[YoutubeVideo]: ...

    def top_comments_for(self, video_id: str, *, max_comments: int = 20) -> list[str]: ...


class HttpYoutubeClient:
    """The real client, wired up only at the composition root (`direct_path/`). Generic
    YouTube Data API v3 I/O only — no discovery-specific ranking/synthesis logic lives here."""

    def __init__(self, *, api_key: str, timeout_seconds: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search_videos(self, query: str, *, max_results: int = 10) -> list[YoutubeVideo]:
        raise NotImplementedError(
            "HttpYoutubeClient.search_videos: real YouTube Data API call lands in PI build "
            "plan Checkpoint 2 — Checkpoint 1 only scaffolds the Protocol/dataclass shapes."
        )

    def top_comments_for(self, video_id: str, *, max_comments: int = 20) -> list[str]:
        raise NotImplementedError(
            "HttpYoutubeClient.top_comments_for: real YouTube Data API call lands in PI "
            "build plan Checkpoint 2 — Checkpoint 1 only scaffolds the Protocol/dataclass "
            "shapes."
        )
