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
from product_intelligence.sources.tavily_client import TavilyImage, TavilySearchResult, TavilyUnavailable
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


def test_cached_tavily_image_round_trip_preserves_title(_patch_repos) -> None:
    """Regression (2026-10-01): `TavilyImage` gained a `title` field for honest image-
    candidate matching, but `_tavily_image_to_dict`/`_dict_to_tavily_image` weren't updated —
    `title` silently became `None` on every cache round-trip (every call after the first, for
    any repeated query), confirmed via live testing. Forces two runs against the SAME query
    text so the second one is served from cache, not a fresh client call, and checks the
    image data a caller reads back still carries its `title`."""

    class _TavilyWithImage:
        def search(self, query, *, include_images=False, max_results=10):
            return [_tavily_result()]

        def images_for(self, query, *, max_images=5):
            return [
                TavilyImage(
                    url="https://img.example.com/1.jpg",
                    source_url="https://img.example.com/1.jpg",
                    description="a shoe",
                    title="Brand — Official Store",
                )
            ]

    cache = InProcessQueryCache()
    tavily = _TavilyWithImage()
    youtube = _FakeYoutubeClient()

    # First call: cache miss, writes the dict-serialized payload.
    discovery_run._cached_tavily_search(
        "wireless earbuds", tavily=tavily, cache=cache, ttl_hours=24, now=_NOW
    )
    # Second call: cache hit — reads back through _dict_to_tavily_image.
    _, images = discovery_run._cached_tavily_search(
        "wireless earbuds", tavily=tavily, cache=cache, ttl_hours=24, now=_NOW
    )

    assert images[0].title == "Brand — Official Store"


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


def test_cross_validated_candidates_survive_the_cap_ahead_of_single_source_ones(_patch_repos) -> None:
    """Real-data regression (live testing, 2026-10-01): a live run found ALL 30 kept
    candidates had engagement_signal=UNAVAILABLE despite YouTube returning 30 real videos for
    the same queries — because Tavily results are processed first and alone already produced
    >= candidate_cap distinct extracted products, so plain insertion-order slicing silently
    discarded every YouTube-matched (cross-validated) group before this fix. Proves a
    candidate confirmed by both Tavily AND YouTube (source_diversity=2) now survives a tight
    cap ahead of single-source (source_diversity=1) candidates, even though the single-source
    ones were synthesized first."""

    class _FixedExtraction:
        """Tavily results 0-4 each name a distinct, never-repeated product (5 single-source
        candidates); the YouTube video names the SAME product as tavily result 0 — forcing a
        real merge into one source_diversity=2 group."""

        def extract_products(self, text, *, category_text):
            if "acme cross validated" in text.lower():
                return ["Acme Cross Validated Shoe"]
            for i in range(5):
                if f"solo product {i}" in text.lower():
                    return [f"Solo Product {i}"]
            return []

    tavily_results = [
        _tavily_result(f"https://a.com/{i}", f"Solo Product {i} Launch", f"content about solo product {i}")
        for i in range(5)
    ]
    tavily_results[0] = _tavily_result(
        "https://a.com/0", "Acme Cross Validated Shoe Launch", "content about the acme cross validated shoe"
    )
    tavily = _FakeTavilyClient(results=tavily_results)
    youtube = _FakeYoutubeClient(videos=[
        YoutubeVideo(
            video_id="v1", title="Acme Cross Validated Shoe Review", channel_title="c",
            view_count=1000, comment_count=10, thumbnail_url="https://i.ytimg.com/vi/v1/hqdefault.jpg",
            published_at=_NOW, retrieved_at=_NOW,
        )
    ])

    outcome = discovery_run.run_discovery(
        _TENANT_ID, run_id=_RUN_ID, niche_brief=_fake_niche_brief(), tavily=tavily, youtube=youtube,
        cache=InProcessQueryCache(), candidate_cap=3, product_extraction_client=_FixedExtraction(), now=_NOW,
    )

    assert outcome.status == "COMPLETE"
    titles = [row["candidate_title"] for row in _patch_repos]
    assert "Acme Cross Validated Shoe" in titles
    merged_row = next(row for row in _patch_repos if row["candidate_title"] == "Acme Cross Validated Shoe")
    assert merged_row["source_diversity"] == 2
    assert merged_row["engagement_signal"]["status"] == "AVAILABLE"


def test_youtube_matched_candidates_reserved_slots_survive_even_against_higher_diversity_tavily_only(
) -> None:
    """Real-data regression (live testing, 2026-10-01): a live run found that sorting by
    source_diversity alone still wasn't enough — several pure-Tavily-only candidates reached
    source_diversity 2-4 from multiple different websites with ZERO YouTube involvement, and
    those out-ranked every single YouTube-matched candidate (source_diversity 1), so the
    YouTube reservation is needed on top of the diversity sort, not instead of it."""
    from product_intelligence.discovery.discovery_run import _select_candidates_with_cap

    def _tavily_only(title: str, diversity: int) -> dict:
        return {
            "candidate_title": title, "source_diversity": diversity,
            "engagement_signal": {"status": "UNAVAILABLE", "reason": "no matching YouTube video found"},
        }

    def _youtube_matched(title: str, diversity: int) -> dict:
        return {
            "candidate_title": title, "source_diversity": diversity,
            "engagement_signal": {"status": "AVAILABLE", "video_count": 1, "view_count": 100, "comment_count": 5, "source": "youtube"},
        }

    # 6 Tavily-only candidates, all with HIGHER source_diversity than the one YouTube-matched
    # candidate — without the reservation, the YouTube one is cut entirely by a tight cap.
    rows = [_tavily_only(f"Tavily Only {i}", diversity=2) for i in range(6)]
    rows.append(_youtube_matched("Youtube Matched Shoe", diversity=1))

    selected = _select_candidates_with_cap(rows, candidate_cap=3)

    titles = [r["candidate_title"] for r in selected]
    assert "Youtube Matched Shoe" in titles
    assert len(selected) == 3


def test_select_candidates_with_cap_never_pads_with_a_worse_candidate_to_fill_the_reservation() -> None:
    """If a niche genuinely has fewer YouTube-matched candidates than the reservation would
    like, the shortfall must not force a worse candidate into the result just to hit a quota
    — the remaining slots fill from the overall best pool exactly as before."""
    from product_intelligence.discovery.discovery_run import _select_candidates_with_cap

    rows = [
        {"candidate_title": "A", "source_diversity": 3, "engagement_signal": {"status": "UNAVAILABLE"}},
        {"candidate_title": "B", "source_diversity": 2, "engagement_signal": {"status": "UNAVAILABLE"}},
        {"candidate_title": "C", "source_diversity": 1, "engagement_signal": {"status": "UNAVAILABLE"}},
    ]
    selected = _select_candidates_with_cap(rows, candidate_cap=2)
    assert [r["candidate_title"] for r in selected] == ["A", "B"]


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


def test_niche_brief_exclude_brands_constraint_filters_before_persisting(_patch_repos) -> None:
    """New 2026-10-01: `niche_brief.constraints.exclude_brands` reaches `run_discovery` end
    to end — a candidate matching an excluded brand is never persisted (never even consumes a
    `candidate_cap` slot), while an unrelated candidate still is."""
    tavily = _FakeTavilyClient(
        results=[
            _tavily_result("https://a.com/1", "Nike Pegasus 41 Review", "lightweight racing shoe"),
            _tavily_result("https://b.com/1", "Acme Runner Pro Launch", "a new budget running shoe"),
        ]
    )
    youtube = _FakeYoutubeClient()

    outcome = discovery_run.run_discovery(
        _TENANT_ID,
        run_id=_RUN_ID,
        niche_brief={
            "category_text": "running shoes",
            "marketplaces": ["AMAZON"],
            "constraints": {"exclude_brands": ["Nike"]},
        },
        tavily=tavily,
        youtube=youtube,
        cache=InProcessQueryCache(),
        now=_NOW,
    )

    assert outcome.status == "COMPLETE"
    titles = [row["candidate_title"] for row in _patch_repos]
    assert "Nike Pegasus 41 Review" not in titles
    assert "Acme Runner Pro Launch" in titles
