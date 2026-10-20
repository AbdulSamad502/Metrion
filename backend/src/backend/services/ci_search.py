"""The composition root for CI's `SearchProvider` (competitor-intelligence-agent.md C34, §6.28).

`ci_actions.run_discovery` asks this module for "the provider and its name" and knows nothing
else. Everything environment-specific lives here, never inside `competitor_intelligence`:

* `CI_SEARCH_PROVIDER=tavily` (the default, owner-approved 2026-10-18) -> `TavilySearchProvider`
  over PI's existing `HttpTavilyClient` and the existing `TAVILY_API_KEY`. The key never leaves
  the server.
* `CI_SEARCH_PROVIDER=mock` -> `MockSearchProvider` (fixtures only). Selected only on purpose;
  an unset key with the default provider is a failed search, not a silent switch to the mock.

Every Tavily failure — missing key, transport error, non-2xx, quota — is raised as
`SearchProviderUnavailable`, which the discovery run records as a `PARTIAL`/failed run with the
reason. It is never turned into an empty "no competitors exist" result (C34, AC40).

Tavily is a lead source only (C35): this module hands the provider a query and receives a URL,
a title and a snippet. It reads no price, stock or rating out of them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from competitor_intelligence.discovery.listing_url import DroppedLead
from competitor_intelligence.discovery.mock_search_provider import PROVIDER_NAME as MOCK_PROVIDER_NAME
from competitor_intelligence.discovery.mock_search_provider import MockSearchProvider
from competitor_intelligence.discovery.search_provider import SearchProvider, SearchProviderUnavailable
from competitor_intelligence.discovery.tavily_search_provider import (
    PROVIDER_NAME as TAVILY_PROVIDER_NAME,
)
from competitor_intelligence.discovery.tavily_search_provider import TavilyLead, TavilySearchProvider
from competitor_intelligence.repositories import ci_search_query_repo

from backend.config import ci_search_provider, ci_tavily_daily_query_cap, tavily_api_key

_log = logging.getLogger(__name__)

_CAP_WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class SelectedProvider:
    provider: SearchProvider
    provider_name: str


class _TavilyTransport(Protocol):
    """The slice of `market_signals.tavily_client.TavilyClient` this adapter uses."""

    def search(self, query: str, *, max_results: int = ..., include_domains: list[str] | None = ...) -> list: ...


class _HttpTavilyLeadClient:
    """Adapts PI's `HttpTavilyClient` to CI's `TavilyLeadClient`: maps its failure type to
    `SearchProviderUnavailable` and reduces each row to the lead fields discovery may use."""

    def __init__(self, transport: _TavilyTransport, *, api_key_present: bool) -> None:
        self._transport = transport
        self._api_key_present = api_key_present

    def search(self, query: str, *, max_results: int, include_domains: list[str]) -> list[TavilyLead]:
        if not self._api_key_present:
            raise SearchProviderUnavailable("TAVILY_API_KEY is not configured on the server")
        # Imported here: `market_signals` is the shared Tavily transport package, and importing
        # it at module load would make every CI-only import of this file depend on it.
        from market_signals.tavily_client import TavilyUnavailable

        try:
            rows = self._transport.search(query, max_results=max_results, include_domains=include_domains)
        except TavilyUnavailable as exc:
            raise SearchProviderUnavailable(str(exc)) from None
        return [
            TavilyLead(url=row.url, title=row.title or None, content=row.content or None, retrieved_at=row.retrieved_at)
            for row in rows
        ]


def _daily_cap_guard(tenant_id: UUID):
    def guard() -> None:
        cap = ci_tavily_daily_query_cap()
        sent = ci_search_query_repo.count_sent_since(
            tenant_id, provider_name=TAVILY_PROVIDER_NAME, since=datetime.now(timezone.utc) - _CAP_WINDOW
        )
        if sent >= cap:
            raise SearchProviderUnavailable(
                f"daily discovery search limit reached ({sent} of {cap} queries in the last 24 hours)"
            )

    return guard


def _log_drop(drop: DroppedLead) -> None:
    # Host and reason only — a candidate URL is public, but nothing seller-specific is logged.
    _log.info("ci discovery dropped a search lead: reason=%s", drop.reason.value)


def select_search_provider(tenant_id: UUID) -> SelectedProvider:
    if ci_search_provider() == "mock":
        return SelectedProvider(provider=MockSearchProvider(), provider_name=MOCK_PROVIDER_NAME)

    # Imported here for the same reason as above.
    from market_signals.tavily_client import HttpTavilyClient

    key = tavily_api_key()
    client = _HttpTavilyLeadClient(HttpTavilyClient(api_key=key), api_key_present=bool(key))
    return SelectedProvider(
        provider=TavilySearchProvider(client, quota_guard=_daily_cap_guard(tenant_id), on_drop=_log_drop),
        provider_name=TAVILY_PROVIDER_NAME,
    )
