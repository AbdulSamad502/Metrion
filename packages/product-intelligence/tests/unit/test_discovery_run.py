"""discovery/discovery_run.py — orchestrator. Repository calls are monkeypatched (no live
Postgres) so this stays a unit test; `TavilyClient`/`YoutubeClient` are in-memory fakes (never
a live network call)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from product_intelligence.discovery import discovery_run
from product_intelligence.repositories import pi_research_run_repo, pi_tenant_config_repo, product_candidate_repo
from product_intelligence.sources.cache import InProcessQueryCache
from product_intelligence.sources.tavily_client import TavilySearchResult, TavilyUnavailable
from product_intelligence.sources.youtube_client import YoutubeUnavailable, YoutubeVideo

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
_TENANT_ID = uuid4()
_RUN_ID = uuid4()


class _FakeTavilyClient:
    def __init__(self, results: list[TavilySearchResult] | None = None, raises: bool = False) -> None:
        self._results = results or []
        self._raises = raises
        self.call_count = 0

    def search(self, query, *, include_images=False, max_results=10):
        self.call_count += 1
        if self._raises:
            raise TavilyUnavailable("rate limit hit")
        return self._results

    def images_for(self, query, *, max_images=5):
        return []


class _FakeYoutubeClient:
    def __init__(self, videos: list[YoutubeVideo] | None = None, raises: bool = False) -> None:
        self._videos = videos or []
        self._raises = raises
        self.call_count = 0

    def search_videos(self, query, *, max_results=10):
        self.call_count += 1
        if self._raises:
            raise YoutubeUnavailable("quota exceeded")
        return self._videos

    def top_comments_for(self, video_id, *, max_comments=20):
        return []


def _fake_niche_brief() -> dict:
    return {"category_text": "wireless earbuds", "marketplaces": ["AMAZON"]}


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pi_research_run_repo, "update_status", lambda *a, **kw: None)
    monkeypatch.setattr(pi_tenant_config_repo, "get_tavily_cache_ttl_hours", lambda tenant_id: 24)
    monkeypatch.setattr(pi_tenant_config_repo, "get_youtube_cache_ttl_hours", lambda tenant_id: 24)

    inserted: list[dict] = []

    def _fake_insert(tenant_id, **kwargs):
        inserted.append(kwargs)
        return uuid4()

    monkeypatch.setattr(product_candidate_repo, "insert_candidate", _fake_insert)
    yield inserted


def _tavily_result(url="https://a.com/1", title="Wireless Earbuds", content="wireless earbuds content"):
    return TavilySearchResult(url=url, title=title, content=content, score=0.9, published_date=None, retrieved_at=_NOW)


def test_complete_run_persists_candidates_with_score_explanation(_patch_repos) -> None:
    tavily = _FakeTavilyClient(results=[_tavily_result()])
    youtube = _FakeYoutubeClient()
    outcome = discovery_run.run_discovery(
        _TENANT_ID,
        run_id=_RUN_ID,
        niche_brief=_fake_niche_brief(),
        tavily=tavily,
        youtube=youtube,
        cache=InProcessQueryCache(),
        now=_NOW,
    )

    assert outcome.status == "COMPLETE"
    assert len(outcome.candidate_ids) >= 1
    assert len(_patch_repos) == len(outcome.candidate_ids)
    for row in _patch_repos:
        assert row["score_explanation"]["signals"]
        assert row["demand_signal"]["status"] == "UNAVAILABLE"


def test_tavily_degraded_run_is_partial_not_failed(_patch_repos) -> None:
    tavily = _FakeTavilyClient(raises=True)
    youtube = _FakeYoutubeClient(videos=[
        YoutubeVideo(
            video_id="v1", title="Wireless Earbuds Unboxing", channel_title="c", view_count=5000,
            comment_count=50, thumbnail_url="https://img.example.com/t.jpg", published_at=_NOW, retrieved_at=_NOW,
        )
    ])
    outcome = discovery_run.run_discovery(
        _TENANT_ID,
        run_id=_RUN_ID,
        niche_brief=_fake_niche_brief(),
        tavily=tavily,
        youtube=youtube,
        cache=InProcessQueryCache(),
        now=_NOW,
    )

    assert outcome.status == "PARTIAL"
    assert outcome.tavily_degraded is True
    assert "Tavily unavailable" in outcome.partial_reason


def test_both_sources_degraded_and_no_candidates_synthesized_is_partial_with_reason(_patch_repos) -> None:
    tavily = _FakeTavilyClient(raises=True)
    youtube = _FakeYoutubeClient(raises=True)
    outcome = discovery_run.run_discovery(
        _TENANT_ID,
        run_id=_RUN_ID,
        niche_brief=_fake_niche_brief(),
        tavily=tavily,
        youtube=youtube,
        cache=InProcessQueryCache(),
        now=_NOW,
    )

    assert outcome.status == "PARTIAL"
    assert outcome.candidate_ids == ()
    assert "no candidates were synthesized" in outcome.partial_reason


def test_candidate_cap_bounds_the_number_of_persisted_candidates(_patch_repos) -> None:
    many_results = [_tavily_result(url=f"https://a.com/{i}", title=f"Product Idea {i}", content=f"unique product idea number {i}") for i in range(10)]
    tavily = _FakeTavilyClient(results=many_results)
    youtube = _FakeYoutubeClient()

    outcome = discovery_run.run_discovery(
        _TENANT_ID,
        run_id=_RUN_ID,
        niche_brief=_fake_niche_brief(),
        tavily=tavily,
        youtube=youtube,
        cache=InProcessQueryCache(),
        candidate_cap=3,
        now=_NOW,
    )

    assert len(outcome.candidate_ids) <= 3


def test_empty_category_text_yields_no_queries_and_no_candidates(_patch_repos) -> None:
    tavily = _FakeTavilyClient(results=[_tavily_result()])
    youtube = _FakeYoutubeClient()

    outcome = discovery_run.run_discovery(
        _TENANT_ID,
        run_id=_RUN_ID,
        niche_brief={"category_text": None, "marketplaces": []},
        tavily=tavily,
        youtube=youtube,
        cache=InProcessQueryCache(),
        now=_NOW,
    )

    assert tavily.call_count == 0
    assert outcome.candidate_ids == ()
