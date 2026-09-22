"""The plumbing around a `SearchProvider` call — competitor-intelligence-agent.md
§6.10-§6.12. Ties query generation, the privacy filter, budget enforcement, tenant-isolated
caching and the `SearchProvider` seam together into one orchestration function, fully
testable against `MockSearchProvider` and `InMemorySearchResultCache` (no database
required).

This is deliberately NOT the discovery run state machine (§6.12.2) — that is a later
checkpoint's job (`QUEUED -> SEARCHING -> DISCOVERING -> ...`, `ci_discovery_run` rows,
identity resolution, relevance scoring). `run_discovery_queries` covers only the
`SEARCHING` stage: composing and dispatching queries within budget, and returns raw,
deduplicated candidate results for a later stage to turn into `ci_candidate` rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from competitor_intelligence.discovery.budget import (
    DiscoveryBudget,
    LIMIT_MAX_DISCOVERY_QUERIES_PER_RUN,
    LIMIT_MAX_RAW_CANDIDATES,
)
from competitor_intelligence.discovery.query_generation import (
    DroppedQuery,
    GeneratedQuery,
    generate_queries,
)
from competitor_intelligence.discovery.search_cache import SearchResultCache
from competitor_intelligence.discovery.search_provider import (
    SearchProvider,
    SearchProviderUnavailable,
    SearchResult,
)
from competitor_intelligence.seller_product.types import SellerProduct


@dataclass(frozen=True, slots=True)
class QueryError:
    query: GeneratedQuery
    error: str


@dataclass(frozen=True, slots=True)
class DiscoveryQueryRunResult:
    """Everything the `SEARCHING` stage produced. `partial_reason` is set — naming the
    exact §6.12.1 limit or provider error — whenever the run could not complete every
    generated query; a later checkpoint's state machine uses this to decide `PARTIAL` vs
    `COMPLETE`/`FAILED` (§6.12.1, AC19: never a silently truncated result presented as
    complete)."""

    queries_sent: tuple[GeneratedQuery, ...]
    queries_dropped_for_privacy: tuple[DroppedQuery, ...]
    query_errors: tuple[QueryError, ...]
    raw_results: tuple[SearchResult, ...]
    partial_reason: str | None
    discovery_enabled: bool


def run_discovery_queries(
    *,
    tenant_id: UUID,
    discovery_run_id: UUID,
    seller_product: SellerProduct,
    provider: SearchProvider,
    provider_name: str,
    cache: SearchResultCache,
    budget: DiscoveryBudget,
    discovery_enabled: bool,
) -> DiscoveryQueryRunResult:
    """§6.11 rule 1: `discovery_enabled` is checked FIRST, before a single query is
    composed — an opt-out honoured after composition would be no opt-out at all."""
    if not discovery_enabled:
        return DiscoveryQueryRunResult(
            queries_sent=(),
            queries_dropped_for_privacy=(),
            query_errors=(),
            raw_results=(),
            partial_reason=None,
            discovery_enabled=False,
        )

    generation = generate_queries(seller_product)

    sent: list[GeneratedQuery] = []
    errors: list[QueryError] = []
    raw_results: list[SearchResult] = []
    seen_urls: set[str] = set()
    partial_reason: str | None = None

    per_query_max_results = max(1, budget.max_raw_candidates)

    for query in generation.sent:
        if len(sent) >= budget.max_discovery_queries_per_run:
            partial_reason = LIMIT_MAX_DISCOVERY_QUERIES_PER_RUN
            break

        cached = cache.get(tenant_id, query.query_text)
        if cached is not None:
            results = cached
        else:
            try:
                results = provider.search(query.query_text, max_results=per_query_max_results)
            except SearchProviderUnavailable as exc:
                errors.append(QueryError(query=query, error=str(exc)))
                sent.append(query)
                continue
            cache.put(
                tenant_id,
                discovery_run_id=discovery_run_id,
                query_kind=query.kind.value,
                query_text=query.query_text,
                provider_name=provider_name,
                results=results,
                ttl_hours=budget.search_cache_ttl_hours,
            )

        sent.append(query)

        for result in results:
            if result.url in seen_urls:
                continue
            if len(raw_results) >= budget.max_raw_candidates:
                partial_reason = LIMIT_MAX_RAW_CANDIDATES
                break
            seen_urls.add(result.url)
            raw_results.append(result)

        if partial_reason == LIMIT_MAX_RAW_CANDIDATES:
            break

    if errors and partial_reason is None:
        partial_reason = f"provider_error:{errors[0].error}"

    return DiscoveryQueryRunResult(
        queries_sent=tuple(sent),
        queries_dropped_for_privacy=generation.dropped,
        query_errors=tuple(errors),
        raw_results=tuple(raw_results),
        partial_reason=partial_reason,
        discovery_enabled=True,
    )
