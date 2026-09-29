"""sources/cache.py — real logic this checkpoint (not a stub), so it gets a real test."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from product_intelligence.sources.cache import InProcessQueryCache, normalize_query_text

_T0 = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


def test_normalize_query_text_collapses_whitespace_and_case() -> None:
    assert normalize_query_text("  Wireless   Earbuds ") == "wireless earbuds"
    assert normalize_query_text("wireless earbuds") == normalize_query_text("Wireless Earbuds")


def test_miss_returns_none() -> None:
    cache = InProcessQueryCache()
    assert cache.get("tavily", "wireless earbuds", now=_T0) is None


def test_put_then_get_within_ttl_hits() -> None:
    cache = InProcessQueryCache()
    cache.put("tavily", "Wireless Earbuds", ["result"], ttl_hours=24, now=_T0)
    assert cache.get("tavily", "wireless   earbuds", now=_T0 + timedelta(hours=1)) == ["result"]


def test_entry_expires_after_ttl() -> None:
    cache = InProcessQueryCache()
    cache.put("tavily", "wireless earbuds", ["result"], ttl_hours=24, now=_T0)
    assert cache.get("tavily", "wireless earbuds", now=_T0 + timedelta(hours=25)) is None


def test_different_sources_do_not_collide() -> None:
    cache = InProcessQueryCache()
    cache.put("tavily", "wireless earbuds", ["tavily-result"], ttl_hours=24, now=_T0)
    assert cache.get("youtube", "wireless earbuds", now=_T0) is None


def test_cache_is_not_keyed_by_tenant() -> None:
    """The whole point of this module (PI build plan Context): two different tenants asking
    the same query hit the same entry — there is no tenant_id parameter at all."""
    cache = InProcessQueryCache()
    cache.put("tavily", "wireless earbuds", ["shared-result"], ttl_hours=24, now=_T0)
    assert cache.get("tavily", "wireless earbuds", now=_T0) == ["shared-result"]


def test_cached_empty_list_is_a_hit_not_a_miss() -> None:
    cache = InProcessQueryCache()
    cache.put("tavily", "no results here", [], ttl_hours=24, now=_T0)
    assert cache.get("tavily", "no results here", now=_T0) == []
