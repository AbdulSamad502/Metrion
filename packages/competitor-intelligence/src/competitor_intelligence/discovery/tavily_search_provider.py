"""The Tavily-backed `SearchProvider` — competitor-intelligence-agent.md C34, §6.28.

Owner-approved provider (2026-10-18). It sits behind the same `SearchProvider` seam as
`MockSearchProvider`; the discovery pipeline does not know which one it is talking to.

What this module is, and is not (C2, C23, C35):

* It returns **leads** — a listing URL, a title and a snippet. It never fetches a marketplace
  page, never scrapes a search frontend, and never parses a price, stock status or rating out
  of a snippet. A snippet is carried through verbatim as lead text for identity resolution and
  provisional relevance; nothing here turns it into a fact.
* It does **no HTTP itself.** The HTTP client (and the API key, which lives only on the server)
  is injected by the backend composition root as a `TavilyLeadClient`, so this package gains no
  dependency on the market-signals/PI packages and is testable with a fake. A client failure
  surfaces as `SearchProviderUnavailable` — never as a silently empty result.

Per lead it enforces, in order: the marketplace-host allowlist (C4/D7), "is this a single-product
listing page" (a category or search page is not a competitor), and de-duplication by canonical
listing. Every drop is reported through `on_drop`, so it can be recorded (AC40).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from competitor_intelligence.discovery.listing_url import (
    CanonicalListing,
    DroppedLead,
    canonicalize_listing_url,
)
from competitor_intelligence.discovery.search_provider import SearchProviderUnavailable, SearchResult

PROVIDER_NAME = "TAVILY"

# The marketplace domains Tavily is asked to search (C1). Subdomains are included by the
# provider. Kept in step with `capture/allowlist.py` — short-link hosts are not searchable
# domains, only pasted/returned links, so they are not listed here.
SEARCH_DOMAINS: tuple[str, ...] = ("amazon.in", "flipkart.com", "meesho.com")

# Tavily's per-request ceiling. Dropped leads (category pages, off-allowlist hosts) shrink a
# result set, so the adapter over-asks, then trims back to the caller's `max_results`.
_PROVIDER_MAX_RESULTS = 20
_OVERSAMPLE = 2


@dataclass(frozen=True, slots=True)
class TavilyLead:
    """One raw row from the Tavily client, reduced to what discovery may use."""

    url: str
    title: str | None
    content: str | None
    retrieved_at: datetime
    provider_response_ref: str | None = None


class TavilyLeadClient(Protocol):
    def search(self, query: str, *, max_results: int, include_domains: list[str]) -> list[TavilyLead]:
        """Must raise `SearchProviderUnavailable` on any transport, auth, quota or malformed-
        response failure."""
        ...


class TavilySearchProvider:
    def __init__(
        self,
        client: TavilyLeadClient,
        *,
        quota_guard: Callable[[], None] | None = None,
        on_drop: Callable[[DroppedLead], None] | None = None,
    ) -> None:
        self._client = client
        self._quota_guard = quota_guard
        self._on_drop = on_drop

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        if max_results < 1:
            return []
        if self._quota_guard is not None:
            self._quota_guard()  # raises SearchProviderUnavailable when a cost cap is reached

        requested = min(_PROVIDER_MAX_RESULTS, max_results * _OVERSAMPLE)
        leads = self._client.search(query, max_results=requested, include_domains=list(SEARCH_DOMAINS))

        results: list[SearchResult] = []
        seen: set[str] = set()
        for lead in leads:
            canonical = canonicalize_listing_url(lead.url)
            if not isinstance(canonical, CanonicalListing):
                if self._on_drop is not None:
                    self._on_drop(DroppedLead(url=lead.url, reason=canonical))
                continue
            if canonical.url in seen:
                continue
            seen.add(canonical.url)
            results.append(
                SearchResult(
                    rank=len(results) + 1,
                    url=canonical.url,
                    title=lead.title,
                    snippet=lead.content,
                    source=PROVIDER_NAME,
                    retrieved_at=lead.retrieved_at,
                    provider_response_ref=lead.provider_response_ref,
                )
            )
            if len(results) >= max_results:
                break
        return results


__all__ = [
    "PROVIDER_NAME",
    "SEARCH_DOMAINS",
    "SearchProviderUnavailable",
    "TavilyLead",
    "TavilyLeadClient",
    "TavilySearchProvider",
]
