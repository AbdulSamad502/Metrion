"""C22/AC13 — MockSearchProvider is the only shipped SearchProvider implementation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from competitor_intelligence.discovery.mock_search_provider import MockSearchProvider
from competitor_intelligence.discovery.search_provider import (
    SearchProviderUnavailable,
    SearchResult,
)

_NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def _result(rank: int, url: str) -> SearchResult:
    return SearchResult(rank=rank, url=url, title="t", snippet="s", source="MOCK", retrieved_at=_NOW)


def test_returns_configured_fixtures_for_exact_query() -> None:
    fixtures = {"wireless mouse": [_result(1, "https://amazon.in/dp/a"), _result(2, "https://amazon.in/dp/b")]}
    provider = MockSearchProvider(fixtures=fixtures)

    results = provider.search("wireless mouse", max_results=10)

    assert [r.url for r in results] == ["https://amazon.in/dp/a", "https://amazon.in/dp/b"]


def test_unrecognised_query_returns_default_results_not_fabricated_data() -> None:
    provider = MockSearchProvider(fixtures={"known query": [_result(1, "https://amazon.in/dp/a")]})

    results = provider.search("unknown query", max_results=10)

    assert results == []


def test_default_results_used_when_configured() -> None:
    default = [_result(1, "https://amazon.in/dp/default")]
    provider = MockSearchProvider(default_results=default)

    results = provider.search("anything", max_results=10)

    assert results == default


def test_max_results_truncates() -> None:
    fixtures = {"q": [_result(i, f"https://amazon.in/dp/{i}") for i in range(5)]}
    provider = MockSearchProvider(fixtures=fixtures)

    results = provider.search("q", max_results=2)

    assert len(results) == 2


def test_fail_flag_raises_search_provider_unavailable() -> None:
    provider = MockSearchProvider(fail=True)

    with pytest.raises(SearchProviderUnavailable):
        provider.search("anything", max_results=10)
