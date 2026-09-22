"""24h search-result cache — competitor-intelligence-agent.md §6.11 rule 5, §6.12.1.

`SearchResultCache` is a `Protocol` so `query_runner.py`'s orchestration is testable without
a database (an in-memory fake satisfies it in unit tests); `PostgresSearchResultCache` is
the real implementation, backed by the tenant-isolated `ci_search_query`/`ci_search_result`
tables (§5.4) via `repositories/ci_search_query_repo.py` and
`repositories/ci_search_result_repo.py`.

**Never shared across tenants, even for a byte-identical query string** (§6.11 rule 5,
AC18) — every cache operation is keyed by `tenant_id` first, and `PostgresSearchResultCache`
routes every query through `tenant_context.tenant_scope`, the same fail-closed RLS-context
wrapper every other repository in this package uses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from competitor_intelligence.discovery.search_provider import SearchResult


class SearchResultCache(Protocol):
    def get(self, tenant_id: UUID, query_text: str) -> list[SearchResult] | None:
        """`None` means "no live cache entry" (miss, or expired past `search_cache_ttl_hours`)
        — the caller must call the `SearchProvider` and then `put()` the fresh results.
        Never returns an empty list to mean "cached empty" versus `None` meaning "uncached"
        ambiguously: an empty list IS a valid cached result (a query that genuinely returned
        nothing), and callers distinguish it from a miss via the `None` sentinel."""
        ...

    def put(
        self,
        tenant_id: UUID,
        *,
        discovery_run_id: UUID,
        query_kind: str,
        query_text: str,
        provider_name: str,
        results: list[SearchResult],
        ttl_hours: int,
        is_followup: bool = False,
        parent_candidate_id: UUID | None = None,
    ) -> UUID:
        """Persists the sent query (§6.11 rule 4: `query_text` is the post-redaction text
        actually sent) and its results, returning the new `ci_search_query.id`."""
        ...


class InMemorySearchResultCache:
    """A DB-free fake for unit tests. Keys are `(tenant_id, query_text)` — deliberately the
    same tenant-first shape as the real cache, so a test that forgets to scope by tenant
    fails the same way the Postgres implementation would."""

    def __init__(self) -> None:
        self._store: dict[tuple[UUID, str], list[SearchResult]] = {}
        self._queries: list[dict[str, object]] = []

    def get(self, tenant_id: UUID, query_text: str) -> list[SearchResult] | None:
        return self._store.get((tenant_id, query_text))

    def put(
        self,
        tenant_id: UUID,
        *,
        discovery_run_id: UUID,
        query_kind: str,
        query_text: str,
        provider_name: str,
        results: list[SearchResult],
        ttl_hours: int,
        is_followup: bool = False,
        parent_candidate_id: UUID | None = None,
    ) -> UUID:
        import uuid as _uuid

        self._store[(tenant_id, query_text)] = list(results)
        query_id = _uuid.uuid4()
        self._queries.append(
            {
                "id": query_id,
                "tenant_id": tenant_id,
                "discovery_run_id": discovery_run_id,
                "query_kind": query_kind,
                "query_text": query_text,
                "provider_name": provider_name,
                "is_followup": is_followup,
                "parent_candidate_id": parent_candidate_id,
            }
        )
        return query_id


class PostgresSearchResultCache:
    """The real `SearchResultCache`, backed by `ci_search_query`/`ci_search_result` (§5.4).
    Every operation goes through `tenant_scope()` inside the two repository modules — this
    class itself never opens a connection."""

    def get(self, tenant_id: UUID, query_text: str) -> list[SearchResult] | None:
        from competitor_intelligence.repositories import ci_search_query_repo, ci_search_result_repo
        from competitor_intelligence.repositories.ci_tenant_config_repo import get_discovery_budget

        budget = get_discovery_budget(tenant_id)
        now = datetime.now(timezone.utc)
        query_id = ci_search_query_repo.find_unexpired_query_id(
            tenant_id, query_text, now=now, ttl_hours=budget.search_cache_ttl_hours
        )
        if query_id is None:
            return None
        return ci_search_result_repo.get_results_for_query(tenant_id, query_id)

    def put(
        self,
        tenant_id: UUID,
        *,
        discovery_run_id: UUID,
        query_kind: str,
        query_text: str,
        provider_name: str,
        results: list[SearchResult],
        ttl_hours: int,
        is_followup: bool = False,
        parent_candidate_id: UUID | None = None,
    ) -> UUID:
        from competitor_intelligence.repositories import ci_search_query_repo, ci_search_result_repo

        sent_at = datetime.now(timezone.utc)
        query_id = ci_search_query_repo.insert_query(
            tenant_id,
            discovery_run_id=discovery_run_id,
            query_text_value=query_text,
            query_kind=query_kind,
            provider_name=provider_name,
            sent_at=sent_at,
            is_followup=is_followup,
            parent_candidate_id=parent_candidate_id,
            result_count=len(results),
        )
        ci_search_result_repo.insert_results(
            tenant_id,
            search_query_id=query_id,
            results=results,
            fetched_at=sent_at,
            ttl_hours=ttl_hours,
        )
        return query_id
