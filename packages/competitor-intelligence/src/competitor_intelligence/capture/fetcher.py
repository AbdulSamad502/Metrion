"""The one seam between this package and the network.

`Fetcher` is a `Protocol`, not a concrete dependency baked into `service.py` — every function
in `capture/service.py` takes a `Fetcher` as a parameter rather than importing `httpx`
directly. This is what makes the capture pipeline structurally impossible to test against a
real marketplace domain: `HttpxFetcher` (the only implementation that can reach the network)
is wired up exactly once, at the composition root (`direct_path/`), and nothing under
`tests/` ever constructs it. Tests inject a fake `Fetcher` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RawPage:
    """The unparsed result of a successful fetch. `body` is HTML text, held only in memory
    for the duration of a single capture — never persisted (C16: no raw listing text)."""

    url: str
    status_code: int
    body: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class FetchError:
    """A failed fetch. `status_code` is None for a transport-level failure (timeout, DNS,
    connection refused) rather than an HTTP error response."""

    reason: str
    status_code: int | None = None


class Fetcher(Protocol):
    def fetch(self, url: str) -> RawPage | FetchError: ...


class HttpxFetcher:
    """The real fetcher, used only by the composition root in `direct_path/`. Generic HTTP
    I/O only — no marketplace-specific logic lives here, that's `parser.py`'s job."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> RawPage | FetchError:
        import httpx

        try:
            response = httpx.get(
                url,
                timeout=self._timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; MetrionCI/0.1)"},
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
