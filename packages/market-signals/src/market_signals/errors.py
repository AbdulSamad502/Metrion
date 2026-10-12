"""Provider error text that is safe to show and to log.

`str(httpx.HTTPStatusError)` contains the FULL request URL, and the YouTube Data API takes its key as a `key=` query parameter, so an unredacted error message carries a live API
key into `YoutubeUnavailable`, and from there into a PI run's `partialReason` (shown to the seller) and into logs. This module is the single place a provider exception becomes
text: a short, key-free description, never the library's own message."""

from __future__ import annotations

import httpx


def describe(exc: BaseException) -> str:
    """What happened, in words a seller or a log reader can use, with no URL, no query string and no credential."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"the service answered HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "the service did not answer in time"
    if isinstance(exc, httpx.TransportError):
        return "the service could not be reached"
    return f"unexpected {type(exc).__name__}"
