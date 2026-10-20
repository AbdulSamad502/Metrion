"""C34/C35 — the Tavily `SearchProvider` adapter, against a fake client (never a network). AC40, AC41."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from competitor_intelligence.discovery.listing_url import DropReason, DroppedLead
from competitor_intelligence.discovery.search_provider import SearchProvider, SearchProviderUnavailable, SearchResult
from competitor_intelligence.discovery.tavily_search_provider import (
    PROVIDER_NAME,
    SEARCH_DOMAINS,
    TavilyLead,
    TavilySearchProvider,
)

_NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def _lead(url: str, title: str = "t", content: str | None = "c") -> TavilyLead:
    return TavilyLead(url=url, title=title, content=content, retrieved_at=_NOW)


@dataclass
class FakeClient:
    leads: list[TavilyLead] = field(default_factory=list)
    fail: bool = False
    calls: list[dict] = field(default_factory=list)

    def search(self, query: str, *, max_results: int, include_domains: list[str]) -> list[TavilyLead]:
        self.calls.append({"query": query, "max_results": max_results, "include_domains": include_domains})
        if self.fail:
            raise SearchProviderUnavailable("tavily down")
        return list(self.leads)


def test_is_a_search_provider() -> None:
    provider: SearchProvider = TavilySearchProvider(FakeClient())
    assert provider.search("steel bottle", max_results=5) == []


def test_restricts_the_search_to_the_three_marketplaces_and_over_asks() -> None:
    client = FakeClient()
    TavilySearchProvider(client).search("steel bottle", max_results=5)
    call = client.calls[0]
    assert call["include_domains"] == list(SEARCH_DOMAINS) == ["amazon.in", "flipkart.com", "meesho.com"]
    assert call["max_results"] == 10  # oversampled; trimmed back below


def test_oversample_is_capped_at_the_provider_ceiling() -> None:
    client = FakeClient()
    TavilySearchProvider(client).search("q", max_results=50)
    assert client.calls[0]["max_results"] == 20


def test_results_are_tagged_tavily_ranked_and_carry_lead_text_unchanged() -> None:
    client = FakeClient(leads=[_lead("https://www.amazon.in/dp/B09ABC1234", title="Milton 1L", content="₹799 in stock")])
    (result,) = TavilySearchProvider(client).search("q", max_results=5)
    assert isinstance(result, SearchResult)
    assert result.source == PROVIDER_NAME == "TAVILY"
    assert result.rank == 1
    assert result.url == "https://www.amazon.in/dp/B09ABC1234"
    # C35: the snippet is lead text, carried verbatim — never parsed into a price/stock fact here.
    assert (result.title, result.snippet) == ("Milton 1L", "₹799 in stock")
    assert not hasattr(result, "price") and not hasattr(result, "price_paise") and not hasattr(result, "availability")


def test_off_allowlist_and_non_listing_leads_are_dropped_and_recorded() -> None:
    dropped: list[DroppedLead] = []
    client = FakeClient(
        leads=[
            _lead("https://www.indiamart.com/proddetail/x.html"),
            _lead("https://www.amazon.in/s?k=steel+bottle"),
            _lead("https://www.amazon.in/dp/B09ABC1234"),
        ]
    )
    results = TavilySearchProvider(client, on_drop=dropped.append).search("q", max_results=5)
    assert [r.url for r in results] == ["https://www.amazon.in/dp/B09ABC1234"]
    assert [(d.url, d.reason) for d in dropped] == [
        ("https://www.indiamart.com/proddetail/x.html", DropReason.OFF_ALLOWLIST),
        ("https://www.amazon.in/s?k=steel+bottle", DropReason.NOT_A_LISTING_URL),
    ]


def test_same_listing_under_different_urls_is_one_result() -> None:
    client = FakeClient(
        leads=[
            _lead("https://www.amazon.in/Milton-Bottle/dp/B09ABC1234/ref=sr_1_1"),
            _lead("https://www.amazon.in/dp/B09ABC1234?th=1"),
            _lead("https://www.amazon.in/dp/B09XYZ9999"),
        ]
    )
    results = TavilySearchProvider(client).search("q", max_results=5)
    assert [r.url for r in results] == ["https://www.amazon.in/dp/B09ABC1234", "https://www.amazon.in/dp/B09XYZ9999"]
    assert [r.rank for r in results] == [1, 2]


def test_trims_to_the_callers_max_results() -> None:
    client = FakeClient(leads=[_lead(f"https://www.amazon.in/dp/B09ABC12{i:02d}") for i in range(10)])
    assert len(TavilySearchProvider(client).search("q", max_results=3)) == 3


def test_provider_failure_is_raised_never_an_empty_result() -> None:
    with pytest.raises(SearchProviderUnavailable):
        TavilySearchProvider(FakeClient(fail=True)).search("q", max_results=5)


def test_quota_guard_runs_before_any_call_and_blocks_it() -> None:
    client = FakeClient(leads=[_lead("https://www.amazon.in/dp/B09ABC1234")])

    def guard() -> None:
        raise SearchProviderUnavailable("daily cap reached")

    with pytest.raises(SearchProviderUnavailable, match="daily cap"):
        TavilySearchProvider(client, quota_guard=guard).search("q", max_results=5)
    assert client.calls == []


def test_zero_max_results_makes_no_call() -> None:
    client = FakeClient()
    assert TavilySearchProvider(client).search("q", max_results=0) == []
    assert client.calls == []
