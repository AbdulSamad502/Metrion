"""The seam between discovery/supplier-search and Tavily's web search API — mirrors
`competitor_intelligence.discovery.search_provider`'s `Protocol` + frozen dataclass +
real-implementation-wired-once-at-the-composition-root shape.

Confirmed source (PI build plan, Checkpoint 0): Tavily is a live V1 source (free tier, 1,000
credits/mo, no card). Used both by `discovery/` (candidate discovery) and `supplier/`
(web-search supplement to Google Places) — a single client, reused by both callers, per the
PI build plan §2.

**Image attribution — corrected against the real API (quality pass, 2026-10-01).** The
original docstring here claimed `include_images=True` returns "source-linked image URLs per
result" — confirmed FALSE by direct testing against the live API: Tavily's `images` entries
carry no page-URL association with any individual search result at all. `source_url` is in
practice the same value as `url` (the image's own hosting/CDN URL), never a distinct page it
was found on. What the API genuinely offers, with `include_image_descriptions=True` (now
always requested below): an AI-generated `description` of the image's visual content, and a
`title` naming the page/site that hosts it (e.g. "ASICS — Official Store"). `candidate_synthesis.py`
uses both as an honest, approximate, token-overlap signal (never an exact-source claim) — see
its own module docstring.

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
    (§0b of the PI build plan), never implied to be a marketplace listing photo. `source_url`
    is, in practice, the same value as `url` (module docstring) — kept as a separate field
    only because a future Tavily response shape might genuinely distinguish them, not because
    it reliably does today. `title`/`description` are the real page-title/visual-description
    fields `include_image_descriptions=True` returns, used for approximate matching only."""

    url: str
    source_url: str
    description: str | None = None
    title: str | None = None


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
        topic: str | None = None,
        days: int | None = None,
        country: str | None = None,
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
        topic: str | None = None,
        days: int | None = None,
        country: str | None = None,
    ) -> list[TavilySearchResult]:
        # `topic` / `days` / `country` are CMO-only options (market-signals plan 7c-ii). Each is OMITTED from the
        # request when None, so every existing caller (Product Intelligence) sends the byte-identical body it always did.
        retrieved_at = datetime.now(timezone.utc)
        body: dict[str, Any] = {
            "query": query,
            "include_images": include_images,
            "max_results": max_results,
            "search_depth": "basic",
        }
        if topic is not None:
            body["topic"] = topic
        if days is not None:
            body["days"] = days
        if country is not None:
            body["country"] = country
        parsed = self._post(body)
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
        # include_image_descriptions=True (quality pass, 2026-10-01, confirmed via direct
        # live testing): without it, Tavily returns bare image URLs with no title or
        # description at all, leaving candidate_synthesis.py's image-matching nothing to
        # match against beyond an unreliable source_url (module docstring). With it, each
        # entry carries a real AI-generated `description` plus a `title` naming the hosting
        # page/site — the only genuine per-image signal this API offers.
        parsed = self._post(
            {
                "query": query,
                "include_images": True,
                "include_image_descriptions": True,
                "max_results": max_images,
                "search_depth": "basic",
            }
        )
        raw_images = parsed.get("images")
        if not isinstance(raw_images, list):
            return []

        images: list[TavilyImage] = []
        for entry in raw_images[:max_images]:
            # Tavily's `images` entries are either a bare URL string (include_image_descriptions
            # not honored/unsupported) or a {"url", "description", "title"} object — both
            # shapes handled rather than assuming one.
            if isinstance(entry, str):
                images.append(TavilyImage(url=entry, source_url=entry, description=None, title=None))
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
                        title=entry.get("title") if isinstance(entry.get("title"), str) else None,
                    )
                )
        return images
