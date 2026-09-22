"""§6.10-§6.12 plumbing: query generation + privacy filter + budget enforcement + tenant-
isolated caching around a SearchProvider call — fully testable against MockSearchProvider
and an in-memory cache fake, no database required."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from competitor_intelligence.discovery.budget import (
    DiscoveryBudget,
    LIMIT_MAX_DISCOVERY_QUERIES_PER_RUN,
    LIMIT_MAX_RAW_CANDIDATES,
)
from competitor_intelligence.discovery.mock_search_provider import MockSearchProvider
from competitor_intelligence.discovery.query_runner import run_discovery_queries
from competitor_intelligence.discovery.search_cache import InMemorySearchResultCache
from competitor_intelligence.discovery.search_provider import SearchResult
from competitor_intelligence.seller_product.types import FieldSource, SellerProduct

_NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def _seller_product() -> SellerProduct:
    return SellerProduct(
        product_id="SKU-WM-001",
        title="Wireless Mouse",
        category="Computer Accessories",
        price_paise=99900,
        attributes=(("colour", "black"),),
        keywords=("ergonomic mouse",),
        fulfillment_type="SELLER_FULFILLED",
        review_count=None,
        rating=None,
        last_updated=None,
        field_source={
            "title": FieldSource.CANONICAL_DERIVED,
            "category": FieldSource.SELLER_ENTERED,
            "attributes": FieldSource.SELLER_ENTERED,
            "keywords": FieldSource.SELLER_ENTERED,
        },
    )


def _result(rank: int, url: str) -> SearchResult:
    return SearchResult(rank=rank, url=url, title="t", snippet="s", source="MOCK", retrieved_at=_NOW)


def test_discovery_enabled_false_sends_zero_queries() -> None:
    """AC17 — with discovery_enabled = false, zero queries are composed or sent."""
    provider = MockSearchProvider(default_results=[_result(1, "https://amazon.in/dp/a")])
    cache = InMemorySearchResultCache()

    result = run_discovery_queries(
        tenant_id=uuid.uuid4(),
        discovery_run_id=uuid.uuid4(),
        seller_product=_seller_product(),
        provider=provider,
        provider_name="MOCK",
        cache=cache,
        budget=DiscoveryBudget(),
        discovery_enabled=False,
    )

    assert result.queries_sent == ()
    assert result.raw_results == ()
    assert result.discovery_enabled is False


def test_runs_end_to_end_against_mock_provider() -> None:
    """T32 — full discovery run against MockSearchProvider fixtures, no real provider."""
    provider = MockSearchProvider(default_results=[_result(1, "https://amazon.in/dp/a")])
    cache = InMemorySearchResultCache()

    result = run_discovery_queries(
        tenant_id=uuid.uuid4(),
        discovery_run_id=uuid.uuid4(),
        seller_product=_seller_product(),
        provider=provider,
        provider_name="MOCK",
        cache=cache,
        budget=DiscoveryBudget(),
        discovery_enabled=True,
    )

    assert len(result.queries_sent) > 0
    assert result.partial_reason is None
    assert {r.url for r in result.raw_results} == {"https://amazon.in/dp/a"}


def test_hits_max_discovery_queries_per_run_and_ends_partial() -> None:
    """E21/AC19 — hitting a budget limit ends the run PARTIAL with the exact limit named,
    never a silently truncated result presented as complete."""
    provider = MockSearchProvider(default_results=[_result(1, "https://amazon.in/dp/a")])
    cache = InMemorySearchResultCache()
    budget = DiscoveryBudget(max_discovery_queries_per_run=1)

    result = run_discovery_queries(
        tenant_id=uuid.uuid4(),
        discovery_run_id=uuid.uuid4(),
        seller_product=_seller_product(),
        provider=provider,
        provider_name="MOCK",
        cache=cache,
        budget=budget,
        discovery_enabled=True,
    )

    assert len(result.queries_sent) == 1
    assert result.partial_reason == LIMIT_MAX_DISCOVERY_QUERIES_PER_RUN


def test_hits_max_raw_candidates_and_ends_partial() -> None:
    """Each generated query returns its own distinct URL (a real provider does the same —
    different queries surface different listings), so accumulating across queries is what
    exceeds the cap, not a single query's own result count."""
    from competitor_intelligence.discovery.query_generation import generate_queries

    generated = generate_queries(_seller_product()).sent
    assert len(generated) >= 3  # sanity: the fixture below needs at least 3 distinct queries
    fixtures = {
        q.query_text: [_result(1, f"https://amazon.in/dp/{i}")] for i, q in enumerate(generated)
    }
    provider = MockSearchProvider(fixtures=fixtures)
    cache = InMemorySearchResultCache()
    budget = DiscoveryBudget(max_raw_candidates=2)

    result = run_discovery_queries(
        tenant_id=uuid.uuid4(),
        discovery_run_id=uuid.uuid4(),
        seller_product=_seller_product(),
        provider=provider,
        provider_name="MOCK",
        cache=cache,
        budget=budget,
        discovery_enabled=True,
    )

    assert len(result.raw_results) == 2
    assert result.partial_reason == LIMIT_MAX_RAW_CANDIDATES


def test_deduplicates_raw_candidates_across_queries() -> None:
    provider = MockSearchProvider(default_results=[_result(1, "https://amazon.in/dp/a")])
    cache = InMemorySearchResultCache()

    result = run_discovery_queries(
        tenant_id=uuid.uuid4(),
        discovery_run_id=uuid.uuid4(),
        seller_product=_seller_product(),
        provider=provider,
        provider_name="MOCK",
        cache=cache,
        budget=DiscoveryBudget(),
        discovery_enabled=True,
    )

    urls = [r.url for r in result.raw_results]
    assert len(urls) == len(set(urls))


def test_provider_unavailable_recorded_as_query_error_and_partial() -> None:
    provider = MockSearchProvider(fail=True)
    cache = InMemorySearchResultCache()

    result = run_discovery_queries(
        tenant_id=uuid.uuid4(),
        discovery_run_id=uuid.uuid4(),
        seller_product=_seller_product(),
        provider=provider,
        provider_name="MOCK",
        cache=cache,
        budget=DiscoveryBudget(),
        discovery_enabled=True,
    )

    assert len(result.query_errors) > 0
    assert result.partial_reason is not None
    assert result.raw_results == ()


def test_cache_hit_skips_the_provider_call() -> None:
    """A cached query never reaches the provider — the query whose text is pre-cached is
    served entirely from cache, and never appears in the provider's call log."""
    tenant_id = uuid.uuid4()
    cache = InMemorySearchResultCache()
    cache.put(
        tenant_id,
        discovery_run_id=uuid.uuid4(),
        query_kind="PRODUCT_TERM",
        query_text="Wireless Mouse",
        provider_name="MOCK",
        results=[_result(1, "https://amazon.in/dp/cached")],
        ttl_hours=24,
    )

    class _RecordingProvider:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def search(self, query: str, *, max_results: int) -> list[SearchResult]:
            self.calls.append(query)
            return []

    provider = _RecordingProvider()

    result = run_discovery_queries(
        tenant_id=tenant_id,
        discovery_run_id=uuid.uuid4(),
        seller_product=_seller_product(),
        provider=provider,
        provider_name="MOCK",
        cache=cache,
        budget=DiscoveryBudget(),
        discovery_enabled=True,
    )

    assert "https://amazon.in/dp/cached" in {r.url for r in result.raw_results}
    assert "Wireless Mouse" not in provider.calls


def test_cache_is_tenant_isolated() -> None:
    """AC18/§6.11 rule 5 — the cache is never shared across tenants, even for an identical
    query string."""
    cache = InMemorySearchResultCache()
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()

    cache.put(
        tenant_a,
        discovery_run_id=uuid.uuid4(),
        query_kind="PRODUCT_TERM",
        query_text="Wireless Mouse",
        provider_name="MOCK",
        results=[_result(1, "https://amazon.in/dp/tenant-a-only")],
        ttl_hours=24,
    )

    assert cache.get(tenant_b, "Wireless Mouse") is None
    assert cache.get(tenant_a, "Wireless Mouse") is not None
