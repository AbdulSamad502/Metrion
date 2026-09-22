"""The only shipped `SearchProvider` implementation (C22, AC13). Returns deterministic,
caller-configured fixture data — no network I/O, no named provider anywhere in this module.

Per C22's locked build order, this is what the whole discovery pipeline (§6.10-§6.15) is
built and tested against until a provider record clears §6.10.1 review and a human approves
one (step 6, outside an implementation agent's authority).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from competitor_intelligence.discovery.search_provider import (
    SearchProviderUnavailable,
    SearchResult,
)

PROVIDER_NAME = "MOCK"


@dataclass(frozen=True, slots=True)
class MockSearchProvider:
    """`fixtures` maps an exact query string to the `SearchResult`s that query should
    return — the test's/caller's way of controlling exactly what candidates come back for a
    given generated query. `default_results` is returned for any query not present in
    `fixtures` (empty by default: an unrecognised query yields no candidates, never
    fabricated ones). `fail` simulates a provider outage, raising `SearchProviderUnavailable`
    on every call regardless of query — for exercising the budget/state-machine handling of
    E21-style provider errors without needing a real backend to misbehave."""

    fixtures: Mapping[str, Sequence[SearchResult]] = field(default_factory=dict)
    default_results: Sequence[SearchResult] = ()
    fail: bool = False

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        if self.fail:
            raise SearchProviderUnavailable(
                f"MockSearchProvider configured to fail for query {query!r}"
            )
        results = self.fixtures.get(query, self.default_results)
        return list(results[:max_results])
