"""ci_search_query — competitor-intelligence-agent.md §5.4, §6.11.

One row per externally-sent query. `query_text` is always the POST-REDACTION text that
actually left Metrion (§6.11 rule 4) — callers must never pass a pre-redaction draft here;
`discovery.query_generation.check_query_privacy` is the gate that runs before this module is
ever called.

Every function takes `tenant_id` first and receives its connection only via `tenant_scope()`
(auth.md §7.3), matching every other repository in this package.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope


def insert_query(
    tenant_id: UUID,
    *,
    discovery_run_id: UUID,
    query_text_value: str,
    query_kind: str,
    provider_name: str,
    sent_at: datetime,
    is_followup: bool = False,
    parent_candidate_id: UUID | None = None,
    result_count: int | None = None,
    error_code: str | None = None,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_search_query
                    (tenant_id, discovery_run_id, query_text, query_kind, is_followup,
                     parent_candidate_id, sent_at, provider_name, result_count, error_code)
                VALUES
                    (:tenant_id, :discovery_run_id, :query_text, :query_kind, :is_followup,
                     :parent_candidate_id, :sent_at, :provider_name, :result_count, :error_code)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "discovery_run_id": str(discovery_run_id),
                "query_text": query_text_value,
                "query_kind": query_kind,
                "is_followup": is_followup,
                "parent_candidate_id": str(parent_candidate_id) if parent_candidate_id else None,
                "sent_at": sent_at,
                "provider_name": provider_name,
                "result_count": result_count,
                "error_code": error_code,
            },
        ).first()
        assert row is not None
        return UUID(str(row[0]))


def find_unexpired_query_id(
    tenant_id: UUID, query_text_value: str, *, now: datetime, ttl_hours: int
) -> UUID | None:
    """The most recent still-live query row for this exact `query_text`, tenant-scoped
    (§6.11 rule 5: never shared across tenants even for an identical string). Returns
    `None` on a cache miss — either no prior query, or its `search_cache_ttl_hours` window
    (measured from `sent_at`, not per-result) has elapsed.

    Cache validity is keyed off the query's own `sent_at + ttl_hours`, not off the presence
    of `ci_search_result` rows — a query that genuinely returned zero results is still a
    valid, live cache entry for its full TTL window (a repeat search shouldn't be re-sent
    just because there was nothing to find last time)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT id
                FROM ci_search_query
                WHERE tenant_id = :tenant_id
                  AND query_text = :query_text
                  AND sent_at + (:ttl_hours || ' hours')::interval > :now
                ORDER BY sent_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "query_text": query_text_value,
                "ttl_hours": ttl_hours,
                "now": now,
            },
        ).first()
        return UUID(str(row[0])) if row is not None else None


def count_sent_since(tenant_id: UUID, *, provider_name: str, since: datetime) -> int:
    """How many queries this tenant actually sent to `provider_name` since `since` — the
    per-tenant cost-cap basis (§6.28.1, C34). Counts `ci_search_query` rows, which are written
    only for a query that really went to the provider (a cache hit writes none)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT count(*)
                FROM ci_search_query
                WHERE tenant_id = :tenant_id
                  AND provider_name = :provider_name
                  AND sent_at >= :since
                """
            ),
            {"tenant_id": str(tenant_id), "provider_name": provider_name, "since": since},
        ).first()
        return int(row[0]) if row is not None else 0
