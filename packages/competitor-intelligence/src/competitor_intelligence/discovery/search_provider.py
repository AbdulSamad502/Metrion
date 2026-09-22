"""The one seam between discovery and a real search backend — mirrors
`evidence/ollama_client.py`'s `OllamaClient` pattern exactly (Protocol + frozen error type,
real implementation wired up once at the composition root, never constructed under
`tests/`).

C22/AC13: no implementation of `SearchProvider` beyond `MockSearchProvider`
(`mock_search_provider.py`) exists in this codebase. Selecting and wiring a named provider
(Serper, SerpApi, Google, Bing, Tavily, Brave, or any other) requires the §6.10.1 provider
record and human approval — both explicitly outside an implementation agent's authority
(C22 build order, steps 5-6). Adding an `Http...SearchProvider` here without that approval
having happened first would violate the locked build order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class SearchProviderUnavailable(Exception):
    """The search backend could not be reached, timed out, returned a non-2xx response, or
    hit its own rate limit — never a reason to fabricate results. Callers treat this the same
    way `OllamaUnavailable` is treated: as "this step failed," which in the discovery run
    state machine (§6.12.2, a later checkpoint) contributes to a `PARTIAL` run with a
    recorded `partial_reason` (§6.12.1) — never a silently empty result presented as
    complete."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One row of provider output — the shape `ci_search_result` persists (§5.4). Lead data
    only (§6.10.2, C23): `title`/`snippet` may seed identity resolution and provisional
    relevance scoring in a later checkpoint, but must never be rendered to a seller as a
    competitor fact, written into a `competitor_snapshot` field, or used as an `Evidence`
    record (§6.10.3 rule 4)."""

    rank: int
    url: str
    title: str | None
    snippet: str | None
    source: str
    """Which provider produced this result (`ci_search_result`/`ci_search_query.provider_name`
    — e.g. `"MOCK"` until C22's approval lands)."""
    retrieved_at: datetime
    provider_response_ref: str | None = None
    """The provider's own result/response id, when it has one — carried through for
    `Evidence.source_reference` once a licensed provider is in use (C28). `None` for
    `MockSearchProvider`."""


class SearchProvider(Protocol):
    def search(self, query: str, *, max_results: int) -> list[SearchResult]: ...
