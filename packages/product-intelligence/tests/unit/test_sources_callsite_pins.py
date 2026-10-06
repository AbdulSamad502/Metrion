"""7b regression pins for how PI's discovery run USES the source layer: caching (key shape, TTL,
hit/miss, failures not cached), the process-wide throttle around every real outbound call, and
the exact call arguments (quota-sensitive: max results / image counts). Written against
CURRENT behaviour so the extraction (7c) can be proven behaviour-preserving with no test edits.

Not testable here without live providers: real concurrency limits against real latency, and
real quota consumption (see docs/planning/market-signal-extraction-plan.md section 5)."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from product_intelligence.discovery import discovery_run as dr
from product_intelligence.sources import rate_limiter
from product_intelligence.sources.cache import InProcessQueryCache
from product_intelligence.sources.tavily_client import TavilyImage, TavilySearchResult, TavilyUnavailable
from product_intelligence.sources.youtube_client import YoutubeUnavailable, YoutubeVideo

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class FakeTavily:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.search_calls, self.image_calls = fail, [], []

    def search(self, query, *, include_images=False, max_results=10):
        self.search_calls.append((query, include_images, max_results))
        if self.fail:
            raise TavilyUnavailable("down")
        return [TavilySearchResult("https://a.example/x", "T", "C", 0.5, None, NOW)]

    def images_for(self, query, *, max_images=5):
        self.image_calls.append((query, max_images))
        if self.fail:
            raise TavilyUnavailable("down")
        return [TavilyImage("https://i/1", "https://i/1", "d", "t")]


class FakeYoutube:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.calls = fail, []

    def search_videos(self, query, *, max_results=10):
        self.calls.append((query, max_results))
        if self.fail:
            raise YoutubeUnavailable("quota")
        return [YoutubeVideo("v1", "T", "Ch", 10, 2, "th", NOW, (), NOW)]


@pytest.fixture
def throttled(monkeypatch):
    """Record every throttle() entry/exit in discovery_run so we can see what is wrapped."""
    log: list[tuple[str, str]] = []

    @contextmanager
    def fake(source):
        log.append(("enter", source))
        try:
            yield rate_limiter.AcquireOutcome(waited=False)
        finally:
            log.append(("exit", source))

    monkeypatch.setattr(dr, "throttle", fake)
    return log


# ------------------------------------------------------------------ Tavily search call site
def test_tavily_miss_calls_provider_once_each_inside_the_throttle_with_pinned_arguments(throttled):
    t, cache = FakeTavily(), InProcessQueryCache()
    results, images = dr._cached_tavily_search("  Steel   Bottle ", tavily=t, cache=cache, ttl_hours=24, now=NOW)
    assert t.search_calls == [("  Steel   Bottle ", True, dr._MAX_RESULTS_PER_TAVILY_QUERY)]  # raw text goes to the provider
    assert t.image_calls == [("  Steel   Bottle ", 5)]
    assert throttled == [("enter", "tavily"), ("exit", "tavily")]  # ONE slot covers both calls
    assert len(results) == 1 and len(images) == 1


def test_tavily_hit_makes_no_provider_call_and_no_throttle(throttled):
    t, cache = FakeTavily(), InProcessQueryCache()
    first = dr._cached_tavily_search("steel bottle", tavily=t, cache=cache, ttl_hours=24, now=NOW)
    throttled.clear()
    again = dr._cached_tavily_search("STEEL   bottle", tavily=t, cache=cache, ttl_hours=24, now=NOW + timedelta(hours=1))
    assert len(t.search_calls) == 1 and len(t.image_calls) == 1 and throttled == []
    assert again == first  # round-trips through the cache losslessly


def test_tavily_cache_key_shape_and_ttl_are_pinned():
    t, cache = FakeTavily(), InProcessQueryCache()
    dr._cached_tavily_search("Steel  Bottle", tavily=t, cache=cache, ttl_hours=6, now=NOW)
    assert cache.get("tavily", "search::steel bottle", now=NOW + timedelta(hours=6) - timedelta(seconds=1)) is not None
    assert cache.get("tavily", "search::steel bottle", now=NOW + timedelta(hours=6)) is None  # expiry boundary is inclusive-expired


def test_tavily_failure_propagates_and_nothing_is_cached(throttled):
    t, cache = FakeTavily(fail=True), InProcessQueryCache()
    with pytest.raises(TavilyUnavailable):
        dr._cached_tavily_search("q", tavily=t, cache=cache, ttl_hours=24, now=NOW)
    assert cache.get("tavily", "search::q", now=NOW) is None
    assert throttled == [("enter", "tavily"), ("exit", "tavily")]  # slot released on failure


def test_per_candidate_image_lookup_uses_its_own_key_prefix_and_throttle(throttled):
    t, cache = FakeTavily(), InProcessQueryCache()
    imgs = dr._cached_images_for_candidate("Acme Bottle", tavily=t, cache=cache, ttl_hours=24, now=NOW)
    assert t.image_calls == [("Acme Bottle", 5)] and t.search_calls == []
    assert cache.get("tavily", "images::acme bottle", now=NOW) is not None
    assert cache.get("tavily", "search::acme bottle", now=NOW) is None  # never collides with a niche query
    assert throttled == [("enter", "tavily"), ("exit", "tavily")] and len(imgs) == 1
    dr._cached_images_for_candidate("acme  bottle", tavily=t, cache=cache, ttl_hours=24, now=NOW)
    assert len(t.image_calls) == 1  # second lookup is a hit


def test_a_cached_empty_result_is_a_hit_not_a_second_provider_call():
    class EmptyTavily(FakeTavily):
        def search(self, query, **kw):
            self.search_calls.append(query)
            return []

        def images_for(self, query, **kw):
            self.image_calls.append(query)
            return []

    t, cache = EmptyTavily(), InProcessQueryCache()
    dr._cached_tavily_search("q", tavily=t, cache=cache, ttl_hours=1, now=NOW)
    dr._cached_tavily_search("q", tavily=t, cache=cache, ttl_hours=1, now=NOW)
    assert len(t.search_calls) == 1


# ------------------------------------------------------------------ YouTube call site
def test_youtube_miss_then_hit_with_pinned_arguments_and_throttle(throttled):
    y, cache = FakeYoutube(), InProcessQueryCache()
    first = dr._cached_youtube_search("Steel Bottle", youtube=y, cache=cache, ttl_hours=12, now=NOW)
    assert y.calls == [("Steel Bottle", dr._MAX_RESULTS_PER_YOUTUBE_QUERY)]
    assert throttled == [("enter", "youtube"), ("exit", "youtube")]
    throttled.clear()
    again = dr._cached_youtube_search("steel  bottle", youtube=y, cache=cache, ttl_hours=12, now=NOW)
    assert len(y.calls) == 1 and throttled == []
    assert [v.video_id for v in again] == [v.video_id for v in first]
    assert cache.get("youtube", "search::steel bottle", now=NOW + timedelta(hours=12)) is None


def test_youtube_failure_propagates_and_nothing_is_cached(throttled):
    y, cache = FakeYoutube(fail=True), InProcessQueryCache()
    with pytest.raises(YoutubeUnavailable):
        dr._cached_youtube_search("q", youtube=y, cache=cache, ttl_hours=12, now=NOW)
    assert cache.get("youtube", "search::q", now=NOW) is None and throttled[-1] == ("exit", "youtube")


def test_tavily_and_youtube_entries_for_the_same_text_do_not_collide():
    t, y, cache = FakeTavily(), FakeYoutube(), InProcessQueryCache()
    dr._cached_tavily_search("q", tavily=t, cache=cache, ttl_hours=1, now=NOW)
    dr._cached_youtube_search("q", youtube=y, cache=cache, ttl_hours=1, now=NOW)
    assert len(t.search_calls) == 1 and len(y.calls) == 1


# ------------------------------------------------------------------ cache extras (existing tests cover the basics)
def test_cache_expiry_boundary_is_exact():
    c = InProcessQueryCache()
    c.put("s", "q", {"a": 1}, ttl_hours=1, now=NOW)
    assert c.get("s", "q", now=NOW + timedelta(hours=1) - timedelta(microseconds=1)) == {"a": 1}
    assert c.get("s", "q", now=NOW + timedelta(hours=1)) is None


def test_put_overwrites_and_restarts_the_ttl():
    c = InProcessQueryCache()
    c.put("s", "q", 1, ttl_hours=1, now=NOW)
    c.put("s", "q", 2, ttl_hours=1, now=NOW + timedelta(minutes=50))
    assert c.get("s", "q", now=NOW + timedelta(minutes=70)) == 2


def test_evict_removes_one_entry_only_and_unknown_evict_is_harmless():
    c = InProcessQueryCache()
    c.put("s", "a", 1, ttl_hours=1, now=NOW)
    c.put("s", "b", 2, ttl_hours=1, now=NOW)
    c.evict("s", " A ")
    c.evict("s", "never-there")
    assert c.get("s", "a", now=NOW) is None and c.get("s", "b", now=NOW) == 2


def test_cache_is_safe_under_concurrent_put_and_get():
    c, errors = InProcessQueryCache(), []

    def work(n):
        try:
            for i in range(200):
                c.put("s", f"q{i % 5}", n, ttl_hours=1, now=NOW)
                c.get("s", f"q{i % 5}", now=NOW)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []


# ------------------------------------------------------------------ rate limiter extras
def test_default_caps_are_three_per_source_and_an_unknown_source_also_gets_three():
    assert rate_limiter.DEFAULT_MAX_CONCURRENT_BY_SOURCE == {"tavily": 3, "youtube": 3, "google_places": 3}
    sem = rate_limiter._semaphore_for("pin-test-unknown-source")
    assert [sem.acquire(blocking=False) for _ in range(4)] == [True, True, True, False]
    [sem.release() for _ in range(3)]


def test_the_same_source_name_always_maps_to_one_shared_semaphore():
    assert rate_limiter._semaphore_for("pin-test-shared") is rate_limiter._semaphore_for("pin-test-shared")
    assert rate_limiter._semaphore_for("pin-test-a") is not rate_limiter._semaphore_for("pin-test-b")


def test_sources_are_throttled_independently():
    sem_t = rate_limiter._semaphore_for("pin-test-ind-1")
    for _ in range(3):
        sem_t.acquire()
    try:
        with rate_limiter.throttle("pin-test-ind-2") as outcome:  # a different source is unaffected
            assert outcome.waited is False
    finally:
        for _ in range(3):
            sem_t.release()
