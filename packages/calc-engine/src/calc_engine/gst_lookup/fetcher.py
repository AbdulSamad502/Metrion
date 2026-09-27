"""The one seam between this subpackage and the network — deterministic-engine.md §8.4.1:
"G2's implementation checkpoint reuses this exact shape [as
`competitor_intelligence.capture.fetcher`] — a `GstFetcher` Protocol, one real implementation,
one allowlist module — not a new one." Mirrors
`packages/competitor-intelligence/src/competitor_intelligence/capture/fetcher.py` deliberately
close, adapted only in name (`Fetcher` -> `GstFetcher`, `HttpxFetcher` -> `HttpxGstFetcher`);
`calc-engine` does not depend on `competitor-intelligence` (no such dependency exists anywhere
in this codebase, checked before writing this module), so the two dataclass shapes are
declared fresh here rather than imported.

`GstFetcher` is a `Protocol`, not a concrete dependency baked into `lookup.py` — every
function in `lookup.py` takes a `GstFetcher` as a parameter rather than importing `httpx`
directly. This is what makes the lookup composition function structurally impossible to test
against a real network domain: `HttpxGstFetcher` (the only implementation that can reach the
network) is wired up only at a real composition root (not yet built — G3's concern), and
nothing under `tests/` ever constructs it. Tests inject a fake `GstFetcher` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RawPage:
    """The unparsed result of a successful fetch. `body` is HTML/text, held only in memory for
    the duration of a single lookup attempt — never persisted verbatim (only the LLM's
    extracted, structured result and its `source_url`/`retrieved_at` citation are ever stored,
    per §8.4's schema)."""

    url: str
    status_code: int
    body: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class FetchError:
    """A failed fetch. `status_code` is None for a transport-level failure (timeout, DNS, TLS
    verification failure, connection refused) rather than an HTTP error response — the same
    distinction §8.4.1 calls out explicitly for the CBIC domains this session found
    unreachable."""

    reason: str
    status_code: int | None = None


class GstFetcher(Protocol):
    def fetch(self, url: str) -> RawPage | FetchError: ...


class HttpxGstFetcher:
    """The real fetcher. Generic HTTP I/O only — no GST-specific logic lives here, that's
    `lookup.py`'s (page selection) and the LLM extraction step's job."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> RawPage | FetchError:
        import httpx

        try:
            response = httpx.get(
                url,
                timeout=self._timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; MetrionGst/0.1)"},
            )
        except httpx.TimeoutException:
            return FetchError(reason="timeout")
        except httpx.TransportError as exc:
            return FetchError(reason=f"transport error: {exc}")

        if response.status_code == 404:
            return FetchError(reason="not found", status_code=404)
        if response.status_code >= 400:
            return FetchError(reason=f"http {response.status_code}", status_code=response.status_code)

        return RawPage(
            url=str(response.url),
            status_code=response.status_code,
            body=response.text,
            fetched_at=datetime.now(timezone.utc),
        )
