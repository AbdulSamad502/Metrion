"""The seam between discovery/supplier-search and Tavily's web search API — mirrors
`competitor_intelligence.discovery.search_provider`'s `Protocol` + frozen dataclass +
real-implementation-wired-once-at-the-composition-root shape.

Confirmed source (PI build plan, Checkpoint 0): Tavily is a live V1 source (free tier, 1,000
credits/mo, no card, `include_images=True` returns source-linked image URLs per result). Used
both by `discovery/` (candidate discovery) and `supplier/` (web-search supplement to Google
Places) — a single client, reused by both callers, per the PI build plan §2.

**Checkpoint 2: real.** `HttpTavilyClient` now makes the actual HTTP call against Tavily's
documented `POST https://api.tavily.com/search` endpoint (`TAVILY_API_KEY` env var, no
default — see `.env.example`/`backend/.env.example`). Caching lives at the call site
(`discovery/discovery_run.py`/`supplier/`), never inside this client — this stays a pure API
wrapper, per this module's own original docstring contract. A non-2xx response, timeout, or
malformed body raises `TavilyUnavailable`, never a fabricated empty/partial result silently
presented as real.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

_SEARCH_URL = "https://api.tavily.com/search"


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

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = {"api_key": self._api_key, **payload}
        try:
            response = httpx.post(_SEARCH_URL, json=body, timeout=self._timeout_seconds)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TavilyUnavailable(f"Tavily request failed: {exc}") from exc
        try:
            parsed = response.json()
        except ValueError as exc:
            raise TavilyUnavailable("Tavily response was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise TavilyUnavailable("Tavily response was not a JSON object")
        return parsed

    def search(
        self,
        query: str,
        *,
        include_images: bool = False,
        max_results: int = 10,
    ) -> list[TavilySearchResult]:
        retrieved_at = datetime.now(timezone.utc)
        parsed = self._post(
            {
                "query": query,
                "include_images": include_images,
                "max_results": max_results,
                "search_depth": "basic",
            }
        )
        raw_results = parsed.get("results")
        if not isinstance(raw_results, list):
            raise TavilyUnavailable("Tavily response had no 'results' list")

        results: list[TavilySearchResult] = []
        for entry in raw_results:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            title = entry.get("title")
            if not isinstance(url, str) or not isinstance(title, str):
                continue
            content = entry.get("content")
            score = entry.get("score")
            results.append(
                TavilySearchResult(
                    url=url,
                    title=title,
                    content=content if isinstance(content, str) else "",
                    score=float(score) if isinstance(score, (int, float)) else None,
                    published_date=entry.get("published_date")
                    if isinstance(entry.get("published_date"), str)
                    else None,
                    retrieved_at=retrieved_at,
                )
            )
        return results

    def images_for(self, query: str, *, max_images: int = 5) -> list[TavilyImage]:
        parsed = self._post(
            {
                "query": query,
                "include_images": True,
                "max_results": max_images,
                "search_depth": "basic",
            }
        )
        raw_images = parsed.get("images")
        if not isinstance(raw_images, list):
            return []

        images: list[TavilyImage] = []
        for entry in raw_images[:max_images]:
            # Tavily's `images` entries are either a bare URL string or, with richer
            # `include_image_descriptions`-style responses, a {"url", "description"} object —
            # both shapes are handled rather than assuming one, since the exact response shape
            # is one of the plan's own "not yet verified" items (Context table).
            if isinstance(entry, str):
                images.append(TavilyImage(url=entry, source_url=entry, description=None))
            elif isinstance(entry, dict) and isinstance(entry.get("url"), str):
                images.append(
                    TavilyImage(
                        url=entry["url"],
                        source_url=entry.get("source_url", entry["url"])
                        if isinstance(entry.get("source_url"), str)
                        else entry["url"],
                        description=entry.get("description")
                        if isinstance(entry.get("description"), str)
                        else None,
                    )
                )
        return images
