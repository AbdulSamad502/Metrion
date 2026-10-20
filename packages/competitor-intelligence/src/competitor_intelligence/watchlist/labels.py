"""A readable name for a tracked competitor the seller did not name (a link added without "called ...", or an approved search lead).

The same name is shown on the dashboard and understood by the CEO ("this is Amazon listing B079R9W1B6"), so every tracked competitor can be referred to.
It is derived from the link only (marketplace and the listing's own id), never from page content."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_ASIN = re.compile(r"/(?:dp|gp/product)/([A-Za-z0-9]{10})", re.IGNORECASE)
_FLIPKART_PID = re.compile(r"[?&]pid=([A-Za-z0-9]+)", re.IGNORECASE)
_ITEM = re.compile(r"/p/(itm[A-Za-z0-9]+)", re.IGNORECASE)
_SHORT = re.compile(r"(?:amzn\.in|amzn\.to|a\.co|dl\.flipkart\.com)/(?:d|s)/([A-Za-z0-9]+)", re.IGNORECASE)


def default_label(marketplace: object, url: str | None) -> str:
    market = str(getattr(marketplace, "value", marketplace) or "").title() or "Marketplace"
    u = url or ""
    for rx in (_ASIN, _FLIPKART_PID, _ITEM, _SHORT):
        m = rx.search(u)
        if m:
            return f"{market} listing {m.group(1).upper() if rx is _ASIN else m.group(1)}"
    return f"{market} listing"


def label_of(row: Mapping[str, Any]) -> str:
    """The seller's own name for it when there is one, else the derived one."""
    return str(row.get("label") or "").strip() or default_label(row.get("marketplace"), row.get("url"))
