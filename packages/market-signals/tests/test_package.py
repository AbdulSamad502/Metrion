def test_public_modules_import_and_expose_the_pinned_names():
    from market_signals import cache, rate_limiter, tavily_client, youtube_client

    assert hasattr(tavily_client, "HttpTavilyClient") and hasattr(youtube_client, "HttpYoutubeClient")
    assert hasattr(cache, "InProcessQueryCache") and hasattr(rate_limiter, "throttle")


def test_expired_cache_entries_are_swept_on_the_next_put_so_memory_cannot_grow_forever():
    from datetime import datetime, timedelta, timezone

    from market_signals.cache import InProcessQueryCache

    c, t0 = InProcessQueryCache(), datetime(2026, 10, 4, tzinfo=timezone.utc)
    for n in range(50):
        c.put("s", f"q{n}", n, ttl_hours=1, now=t0)
    c.put("s", "fresh", 1, ttl_hours=1, now=t0 + timedelta(hours=2))  # every earlier entry has expired by now; none is ever read again
    assert len(c._store) == 1  # noqa: SLF001
    assert c.get("s", "fresh", now=t0 + timedelta(hours=2)) == 1
