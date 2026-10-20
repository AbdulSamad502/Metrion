"""Canonical marketplace-listing URLs for discovery leads — competitor-intelligence-agent.md
§6.28.1 (C34).

A search provider returns whatever it indexed: product pages, category pages, search-result
pages, tracking-parameter variants of the same page. Discovery needs exactly one thing per
lead — *which listing is this* — so that the same product surfaced by two queries is one
candidate, and a page that is not a product listing is never offered to the seller as one.

Nothing here fetches anything (C2). It only reads the URL string it was handed.

Per-marketplace rules, deliberately conservative — a URL that does not positively look like a
single-product listing is dropped with a named reason rather than guessed at:

* Amazon: `/dp/<ASIN>` or `/gp/product/<ASIN>` (10 alphanumerics) -> `https://www.amazon.in/dp/<ASIN>`.
  The short-link host `amzn.in` is kept as given (a short link cannot be canonicalised without
  following it, which this module never does).
* Flipkart: a `/p/` product path, with the `pid` query parameter retained when present (it is
  what distinguishes variants of one listing path). `fkrt.co` is kept as given.
* Meesho: a `/p/<id>` product path; query string dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import parse_qs, urlsplit

from competitor_intelligence.capture.allowlist import marketplace_for_host
from competitor_intelligence.types import Marketplace

_AMAZON_ASIN = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Za-z0-9]{10})(?:[/?]|$)")
_FLIPKART_PRODUCT = re.compile(r"/p/")
_MESHO_PRODUCT = re.compile(r"/p/([A-Za-z0-9]+)(?:[/?]|$)")

_SHORT_LINK_HOSTS = frozenset({"amzn.in", "fkrt.co"})


class DropReason(str, Enum):
    NOT_HTTP = "NOT_HTTP"
    OFF_ALLOWLIST = "OFF_ALLOWLIST"
    NOT_A_LISTING_URL = "NOT_A_LISTING_URL"


@dataclass(frozen=True, slots=True)
class CanonicalListing:
    url: str
    marketplace: Marketplace


@dataclass(frozen=True, slots=True)
class DroppedLead:
    """A lead the provider adapter refused, and why — recorded, never silently discarded
    (C34, AC40)."""

    url: str
    reason: DropReason


def canonicalize_listing_url(url: str) -> CanonicalListing | DropReason:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return DropReason.NOT_HTTP

    marketplace = marketplace_for_host(url)
    if marketplace is None:
        return DropReason.OFF_ALLOWLIST

    host = parts.hostname.lower()
    path = parts.path or "/"

    if host in _SHORT_LINK_HOSTS:
        if path.strip("/") == "":
            return DropReason.NOT_A_LISTING_URL
        return CanonicalListing(url=f"https://{host}{path.rstrip('/')}", marketplace=marketplace)

    if marketplace is Marketplace.AMAZON:
        match = _AMAZON_ASIN.search(path + "/")
        if match is None:
            return DropReason.NOT_A_LISTING_URL
        return CanonicalListing(url=f"https://www.amazon.in/dp/{match.group(1).upper()}", marketplace=marketplace)

    if marketplace is Marketplace.FLIPKART:
        if _FLIPKART_PRODUCT.search(path) is None:
            return DropReason.NOT_A_LISTING_URL
        pid = parse_qs(parts.query).get("pid", [None])[0]
        suffix = f"?pid={pid}" if pid else ""
        return CanonicalListing(url=f"https://www.flipkart.com{path.rstrip('/')}{suffix}", marketplace=marketplace)

    if marketplace is Marketplace.MEESHO:
        if _MESHO_PRODUCT.search(path + "/") is None:
            return DropReason.NOT_A_LISTING_URL
        return CanonicalListing(url=f"https://www.meesho.com{path.rstrip('/')}", marketplace=marketplace)

    return DropReason.NOT_A_LISTING_URL
