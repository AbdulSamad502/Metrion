"""The seam between discovery/supplier-search and Tavily's web search API — mirrors
`competitor_intelligence.discovery.search_provider`'s `Protocol` + frozen dataclass +
real-implementation-wired-once-at-the-composition-root shape.

Confirmed source (PI build plan, Checkpoint 0): Tavily is a live V1 source (free tier, 1,000
credits/mo, no card, `include_images=True` returns source-linked image URLs per result). Used
both by `discovery/` (candidate discovery) and `supplier/` (web-search supplement to Google
Places) — a single client, reused by both callers, per the PI build plan §2.

**Checkpoint 1 scaffolding only.** `TavilyClient` (the Protocol) and `TavilySearchResult`/
`TavilyImage` (the result shapes) are real and complete. `HttpTavilyClient` — the concrete
implementation that would actually call Tavily's HTTP API — is a stub raising
`NotImplementedError`; the real HTTP call, retry/timeout handling and rate-limit degradation
land in Checkpoint 2. No implementation of `TavilyClient` beyond this stub exists in this
codebase yet, and nothing under `tests/` may construct `HttpTavilyClient`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class TavilyUnavailable(Exception):
    """The Tavily API could not be reached, timed out, returned a non-2xx response, or hit
    its own rate/credit limit — never a reason to fabricate results. Callers treat this as
    "this source failed for this run," contributing to a degraded/`PARTIAL` run
    (`discovery_run.py`'s state machine, Checkpoint 2) — never a silently empty result
    presented as complete."""


@dataclass(frozen=True, slots=True)
class TavilyImage:
    """One `include_images=True` result — always rendered with visible source attribution
    (§0b of the PI build plan), never implied to be a marketplace listing photo."""

    url: str
    source_url: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class TavilySearchResult:
    """One row of Tavily search output. Lead/signal data only — `title`/`content` may seed
    candidate synthesis (`candidate_synthesis.py`, Checkpoint 2) but the raw text itself is
    never persisted to `product_candidate.candidate_title` verbatim (D5's "never a verbatim
    paraphrase of any single source")."""

    url: str
    title: str
    content: str
    score: float | None
    published_date: str | None
    retrieved_at: datetime


class TavilyClient(Protocol):
    def search(
        self,
        query: str,
        *,
        include_images: bool = False,
        max_results: int = 10,
    ) -> list[TavilySearchResult]: ...

    def images_for(self, query: str, *, max_images: int = 5) -> list[TavilyImage]: ...


class HttpTavilyClient:
    """The real client, wired up only at the composition root (`direct_path/`). Generic
    Tavily HTTP I/O only — no discovery-specific ranking/synthesis logic lives here."""

    def __init__(self, *, api_key: str, timeout_seconds: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search(
        self,
        query: str,
        *,
        include_images: bool = False,
        max_results: int = 10,
    ) -> list[TavilySearchResult]:
        raise NotImplementedError(
            "HttpTavilyClient.search: real Tavily HTTP call lands in PI build plan "
            "Checkpoint 2 — Checkpoint 1 only scaffolds the Protocol/dataclass shapes."
        )

    def images_for(self, query: str, *, max_images: int = 5) -> list[TavilyImage]:
        raise NotImplementedError(
            "HttpTavilyClient.images_for: real Tavily HTTP call lands in PI build plan "
            "Checkpoint 2 — Checkpoint 1 only scaffolds the Protocol/dataclass shapes."
        )
