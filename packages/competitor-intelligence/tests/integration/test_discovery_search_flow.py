"""ci_search_query / ci_search_result — competitor-intelligence-agent.md §5.4, §6.11 rule 5,
§6.12.1. RLS isolation for the discovery search-result cache, plus a round trip through
`repositories/ci_search_query_repo.py` and `repositories/ci_search_result_repo.py` /
`discovery/search_cache.py::PostgresSearchResultCache`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from competitor_intelligence.discovery.search_cache import PostgresSearchResultCache
from competitor_intelligence.discovery.search_provider import SearchResult
from competitor_intelligence.repositories import ci_search_query_repo, ci_search_result_repo
from competitor_intelligence.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")

_NOW = datetime.now(timezone.utc)


def _result(rank: int, url: str) -> SearchResult:
    return SearchResult(rank=rank, url=url, title="t", snippet="s", source="MOCK", retrieved_at=_NOW)


def test_put_then_get_round_trips_through_postgres(two_tenants) -> None:
    tenant_a, _ = two_tenants
    cache = PostgresSearchResultCache()

    query_id = cache.put(
        tenant_a,
        discovery_run_id=uuid.uuid4(),
        query_kind="PRODUCT_TERM",
        query_text="wireless mouse",
        provider_name="MOCK",
        results=[_result(1, "https://amazon.in/dp/a"), _result(2, "https://amazon.in/dp/b")],
        ttl_hours=24,
    )
    assert query_id is not None

    cached = cache.get(tenant_a, "wireless mouse")
    assert cached is not None
    assert [r.url for r in cached] == ["https://amazon.in/dp/a", "https://amazon.in/dp/b"]


def test_cache_is_never_shared_across_tenants_for_identical_query_text(two_tenants) -> None:
    """AC18/§6.11 rule 5."""
    tenant_a, tenant_b = two_tenants
    cache = PostgresSearchResultCache()

    cache.put(
        tenant_a,
        discovery_run_id=uuid.uuid4(),
        query_kind="PRODUCT_TERM",
        query_text="wireless mouse",
        provider_name="MOCK",
        results=[_result(1, "https://amazon.in/dp/a")],
        ttl_hours=24,
    )

    assert cache.get(tenant_b, "wireless mouse") is None
    assert cache.get(tenant_a, "wireless mouse") is not None


def test_expired_cache_entry_is_a_miss(two_tenants) -> None:
    tenant_a, _ = two_tenants
    discovery_run_id = uuid.uuid4()
    sent_at = datetime.now(timezone.utc) - timedelta(hours=48)

    query_id = ci_search_query_repo.insert_query(
        tenant_a,
        discovery_run_id=discovery_run_id,
        query_text_value="wireless mouse",
        query_kind="PRODUCT_TERM",
        provider_name="MOCK",
        sent_at=sent_at,
    )
    ci_search_result_repo.insert_results(
        tenant_a,
        search_query_id=query_id,
        results=[_result(1, "https://amazon.in/dp/a")],
        fetched_at=sent_at,
        ttl_hours=24,
    )

    found = ci_search_query_repo.find_unexpired_query_id(
        tenant_a, "wireless mouse", now=datetime.now(timezone.utc), ttl_hours=24
    )
    assert found is None


def test_search_result_tables_are_tenant_isolated_at_the_row_level(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    discovery_run_id = uuid.uuid4()

    query_id = ci_search_query_repo.insert_query(
        tenant_a,
        discovery_run_id=discovery_run_id,
        query_text_value="wireless mouse",
        query_kind="PRODUCT_TERM",
        provider_name="MOCK",
        sent_at=datetime.now(timezone.utc),
    )
    ci_search_result_repo.insert_results(
        tenant_a,
        search_query_id=query_id,
        results=[_result(1, "https://amazon.in/dp/a")],
        fetched_at=datetime.now(timezone.utc),
        ttl_hours=24,
    )

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT * FROM ci_search_query")).fetchall()
        result_rows = conn.execute(text("SELECT * FROM ci_search_result")).fetchall()
    assert rows == []
    assert result_rows == []

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT * FROM ci_search_query")).fetchall()
    assert len(rows) == 1
