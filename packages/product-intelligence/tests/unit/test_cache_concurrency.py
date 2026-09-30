"""Cache/queue concurrency — PI build plan Checkpoint 3's own named check: two (simulated
concurrent) discovery requests for the same normalized niche/keyword must hit
`sources/cache.py` once, not fan out to Tavily/YouTube twice, within the TTL window."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from product_intelligence.discovery import discovery_run
from product_intelligence.repositories import pi_research_run_repo, pi_tenant_config_repo, product_candidate_repo
from product_intelligence.sources.cache import InProcessQueryCache
from product_intelligence.sources.tavily_client import TavilySearchResult
from product_intelligence.sources.youtube_client import YoutubeVideo

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
_TENANT_ID_A = uuid4()
_TENANT_ID_B = uuid4()


class _CountingTavilyClient:
    def __init__(self) -> None:
        self.call_count = 0

    def search(self, query, *, include_images=False, max_results=10):
        self.call_count += 1
        return [
            TavilySearchResult(
                url="https://a.com/1", title="Wireless Earbuds", content="wireless earbuds content",
                score=0.9, published_date=None, retrieved_at=_NOW,
            )
        ]

    def images_for(self, query, *, max_images=5):
        return []


class _CountingYoutubeClient:
    def __init__(self) -> None:
        self.call_count = 0

    def search_videos(self, query, *, max_results=10):
        self.call_count += 1
        return [
            YoutubeVideo(
                video_id="v1", title="Wireless Earbuds Unboxing", channel_title="c", view_count=5000,
                comment_count=50, thumbnail_url="https://img.example.com/t.jpg", published_at=_NOW, retrieved_at=_NOW,
            )
        ]

    def top_comments_for(self, video_id, *, max_comments=20):
        return []


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pi_research_run_repo, "update_status", lambda *a, **kw: None)
    monkeypatch.setattr(pi_tenant_config_repo, "get_tavily_cache_ttl_hours", lambda tenant_id: 24)
    monkeypatch.setattr(pi_tenant_config_repo, "get_youtube_cache_ttl_hours", lambda tenant_id: 24)
    monkeypatch.setattr(product_candidate_repo, "insert_candidate", lambda tenant_id, **kw: uuid4())


def test_two_tenants_same_niche_share_one_underlying_source_call(_patch_repos) -> None:
    """The deliberate cross-tenant sharing this cache exists for (module docstring, Context's
    'rate-limit/scale concern'): tenant B's discovery run for the identical niche within the
    TTL window must NOT re-call Tavily/YouTube — it must reuse tenant A's cached result."""
    tavily = _CountingTavilyClient()
    youtube = _CountingYoutubeClient()
    shared_cache = InProcessQueryCache()
    niche_brief = {"category_text": "wireless earbuds", "marketplaces": ["AMAZON"]}

    discovery_run.run_discovery(
        _TENANT_ID_A, run_id=uuid4(), niche_brief=niche_brief, tavily=tavily, youtube=youtube,
        cache=shared_cache, now=_NOW,
    )
    calls_after_first_run = tavily.call_count
    youtube_calls_after_first_run = youtube.call_count
    assert calls_after_first_run > 0

    discovery_run.run_discovery(
        _TENANT_ID_B, run_id=uuid4(), niche_brief=niche_brief, tavily=tavily, youtube=youtube,
        cache=shared_cache, now=_NOW,
    )

    assert tavily.call_count == calls_after_first_run
    assert youtube.call_count == youtube_calls_after_first_run


def test_a_second_identical_request_by_the_same_tenant_also_hits_cache_not_the_source(_patch_repos) -> None:
    tavily = _CountingTavilyClient()
    youtube = _CountingYoutubeClient()
    shared_cache = InProcessQueryCache()
    niche_brief = {"category_text": "wireless earbuds", "marketplaces": ["AMAZON"]}

    discovery_run.run_discovery(
        _TENANT_ID_A, run_id=uuid4(), niche_brief=niche_brief, tavily=tavily, youtube=youtube,
        cache=shared_cache, now=_NOW,
    )
    first_call_count = tavily.call_count

    discovery_run.run_discovery(
        _TENANT_ID_A, run_id=uuid4(), niche_brief=niche_brief, tavily=tavily, youtube=youtube,
        cache=shared_cache, now=_NOW,
    )

    assert tavily.call_count == first_call_count
