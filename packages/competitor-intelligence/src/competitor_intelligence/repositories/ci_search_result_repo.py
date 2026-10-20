"""ci_search_result — competitor-intelligence-agent.md §5.4, §6.10.3, §6.12.1.

Raw provider results, cached for `search_cache_ttl_hours` (default 24h). Tenant-isolated:
never shared across tenants, even for an identical query string (§6.11 rule 5, AC18) — every
function here takes `tenant_id` first and reads/writes only through `tenant_scope()`.

`result_title`/`result_snippet` are LEAD ONLY (C23, §6.10.3 rule 4): nothing in this module
renders them as a competitor fact; they exist to seed a later checkpoint's identity
resolution and provisional relevance scoring.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.discovery.search_provider import SearchResult
from competitor_intelligence.repositories.tenant_context import tenant_scope


def insert_results(
    tenant_id: UUID,
    *,
    search_query_id: UUID,
    results: list[SearchResult],
    fetched_at: datetime,
    ttl_hours: int,
) -> None:
    if not results:
        return
    cache_expires_at = fetched_at + timedelta(hours=ttl_hours)
    with tenant_scope(tenant_id) as conn:
        for result in results:
            conn.execute(
                text(
                    """
                    INSERT INTO ci_search_result
                        (tenant_id, search_query_id, result_rank, result_url, result_title,
                         result_snippet, fetched_at, cache_expires_at, provider_response_ref)
                    VALUES
                        (:tenant_id, :search_query_id, :result_rank, :result_url, :result_title,
                         :result_snippet, :fetched_at, :cache_expires_at, :provider_response_ref)
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "search_query_id": str(search_query_id),
                    "result_rank": result.rank,
                    "result_url": result.url,
                    "result_title": result.title,
                    "result_snippet": result.snippet,
                    "fetched_at": fetched_at,
                    "cache_expires_at": cache_expires_at,
                    "provider_response_ref": result.provider_response_ref,
                },
            )


def titles_by_url(tenant_id: UUID, urls: list[str]) -> dict[str, dict[str, str | None]]:
    """The title and snippet a search returned for each listing link (the newest per link), so a lead can be shown by what it is called. Nothing is fetched or invented: a link
    the search did not return a title for simply has none."""
    if not urls:
        return {}
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT ON (result_url) result_url, result_title, result_snippet FROM ci_search_result "
                "WHERE tenant_id = :t AND result_url = ANY(:urls) ORDER BY result_url, fetched_at DESC"
            ),
            {"t": str(tenant_id), "urls": list(urls)},
        ).all()
    return {r[0]: {"title": r[1], "snippet": r[2]} for r in rows}


def find_result_by_url(tenant_id: UUID, discovery_run_id: UUID, url: str) -> SearchResult | None:
    """Reconstructs the original title/snippet for a candidate's URL within one discovery
    run — used by the "Promote to analysis" seller action (§6.15 rule 4), which needs the
    same title/snippet identity resolution originally saw, without discovery_run.py holding
    a long-lived in-memory cache of raw provider output beyond what §5.4's own tables
    already persist."""
    with tenant_scope(tenant_id) as conn:
        row = (
            conn.execute(
                text(
                    """
                    SELECT r.result_rank, r.result_url, r.result_title, r.result_snippet,
                           r.fetched_at, r.provider_response_ref
                    FROM ci_search_result r
                    JOIN ci_search_query q ON q.id = r.search_query_id
                    WHERE r.tenant_id = :tenant_id AND q.discovery_run_id = :discovery_run_id
                          AND r.result_url = :url
                    ORDER BY r.fetched_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id), "discovery_run_id": str(discovery_run_id), "url": url},
            )
            .mappings()
            .first()
        )
    if row is None:
        return None
    return SearchResult(
        rank=row["result_rank"],
        url=row["result_url"],
        title=row["result_title"],
        snippet=row["result_snippet"],
        source="CACHE",
        retrieved_at=row["fetched_at"],
        provider_response_ref=row["provider_response_ref"],
    )


def get_results_for_query(tenant_id: UUID, search_query_id: UUID) -> list[SearchResult]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT result_rank, result_url, result_title, result_snippet, fetched_at,
                       provider_response_ref
                FROM ci_search_result
                WHERE tenant_id = :tenant_id AND search_query_id = :search_query_id
                ORDER BY result_rank ASC
                """
            ),
            {"tenant_id": str(tenant_id), "search_query_id": str(search_query_id)},
        ).mappings().all()
    return [
        SearchResult(
            rank=row["result_rank"],
            url=row["result_url"],
            title=row["result_title"],
            snippet=row["result_snippet"],
            source="CACHE",
            retrieved_at=row["fetched_at"],
            provider_response_ref=row["provider_response_ref"],
        )
        for row in rows
    ]
