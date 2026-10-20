"""CI spec C34 / §6.28 — which `SearchProvider` discovery composes, and how Tavily failures surface. No network, no database."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend import config
from backend.config import ConfigInvalid
from backend.services import ci_search
from competitor_intelligence.discovery.mock_search_provider import MockSearchProvider
from competitor_intelligence.discovery.search_provider import SearchProviderUnavailable
from competitor_intelligence.discovery.tavily_search_provider import TavilySearchProvider

_NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


class _Row:
    def __init__(self, url: str, title: str = "t", content: str = "c") -> None:
        self.url, self.title, self.content, self.retrieved_at = url, title, content, _NOW


class _Transport:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows, self.error, self.calls = rows or [], error, []

    def search(self, query, *, max_results=10, include_domains=None):
        self.calls.append((query, max_results, include_domains))
        if self.error is not None:
            raise self.error
        return self.rows


@pytest.fixture(autouse=True)
def _fresh_key_cache():
    config.tavily_api_key.cache_clear()
    yield
    config.tavily_api_key.cache_clear()


def test_the_product_default_is_tavily(monkeypatch) -> None:
    # conftest pins the mock for every test; remove the pin to see the product default.
    monkeypatch.delenv("CI_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    config.tavily_api_key.cache_clear()
    selected = ci_search.select_search_provider(uuid4())
    assert selected.provider_name == "TAVILY" and isinstance(selected.provider, TavilySearchProvider)


def test_mock_is_selected_only_when_asked() -> None:
    selected = ci_search.select_search_provider(uuid4())  # conftest sets CI_SEARCH_PROVIDER=mock
    assert selected.provider_name == "MOCK" and isinstance(selected.provider, MockSearchProvider)


def test_an_unknown_provider_is_a_configuration_error_not_a_silent_mock(monkeypatch) -> None:
    monkeypatch.setenv("CI_SEARCH_PROVIDER", "serper")
    with pytest.raises(ConfigInvalid):
        ci_search.select_search_provider(uuid4())


def test_missing_key_is_an_honest_failed_search_not_an_empty_result(monkeypatch) -> None:
    monkeypatch.setenv("CI_SEARCH_PROVIDER", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    config.tavily_api_key.cache_clear()
    monkeypatch.setattr(ci_search.ci_search_query_repo, "count_sent_since", lambda *a, **k: 0)
    selected = ci_search.select_search_provider(uuid4())
    with pytest.raises(SearchProviderUnavailable, match="TAVILY_API_KEY"):
        selected.provider.search("steel bottle", max_results=5)


def test_transport_failure_maps_to_search_provider_unavailable() -> None:
    from market_signals.tavily_client import TavilyUnavailable

    client = ci_search._HttpTavilyLeadClient(_Transport(error=TavilyUnavailable("boom")), api_key_present=True)
    with pytest.raises(SearchProviderUnavailable, match="boom"):
        client.search("q", max_results=5, include_domains=["amazon.in"])


def test_rows_are_reduced_to_lead_fields_only() -> None:
    client = ci_search._HttpTavilyLeadClient(
        _Transport(rows=[_Row("https://www.amazon.in/dp/B09ABC1234", "Milton 1L", "₹799")]), api_key_present=True
    )
    (lead,) = client.search("q", max_results=5, include_domains=["amazon.in"])
    assert (lead.url, lead.title, lead.content) == ("https://www.amazon.in/dp/B09ABC1234", "Milton 1L", "₹799")
    assert set(lead.__slots__) == {"url", "title", "content", "retrieved_at", "provider_response_ref"}


def test_daily_cap_blocks_the_call_before_it_is_made(monkeypatch) -> None:
    monkeypatch.setenv("CI_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setenv("CI_TAVILY_DAILY_QUERY_CAP", "3")
    config.tavily_api_key.cache_clear()
    monkeypatch.setattr(ci_search.ci_search_query_repo, "count_sent_since", lambda *a, **k: 3)
    selected = ci_search.select_search_provider(uuid4())
    with pytest.raises(SearchProviderUnavailable, match="daily discovery search limit"):
        selected.provider.search("steel bottle", max_results=5)


def test_under_the_cap_the_call_proceeds_and_is_restricted_to_the_marketplaces(monkeypatch) -> None:
    monkeypatch.setenv("CI_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setenv("CI_TAVILY_DAILY_QUERY_CAP", "3")
    config.tavily_api_key.cache_clear()
    monkeypatch.setattr(ci_search.ci_search_query_repo, "count_sent_since", lambda *a, **k: 2)
    transport = _Transport(rows=[_Row("https://www.amazon.in/dp/B09ABC1234")])
    monkeypatch.setattr("market_signals.tavily_client.HttpTavilyClient", lambda api_key: transport)
    results = ci_search.select_search_provider(uuid4()).provider.search("steel bottle", max_results=5)
    assert [r.url for r in results] == ["https://www.amazon.in/dp/B09ABC1234"]
    assert transport.calls[0][2] == ["amazon.in", "flipkart.com", "meesho.com"]
