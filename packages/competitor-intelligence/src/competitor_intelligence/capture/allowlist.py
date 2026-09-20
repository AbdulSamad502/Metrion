"""Trusted-domain allowlist — C4. Hardcoded, not configurable per tenant.

This check runs before any fetcher call anywhere in this package (see `service.py`). It is
deliberately the first thing evaluated in the capture pipeline: a non-allowlisted URL never
reaches a `Fetcher`, real or fake, which is also what makes it possible to assert in tests
that a rejected URL never triggers network I/O.
"""

from __future__ import annotations

from urllib.parse import urlsplit

ALLOWED_HOSTS: frozenset[str] = frozenset({"amazon.in", "flipkart.com", "meesho.com"})


def is_allowed_host(url: str) -> bool:
    """True if `url`'s host is one of ALLOWED_HOSTS or a subdomain of one (e.g.
    `www.amazon.in`, `m.flipkart.com`). Anything else — a different TLD, a look-alike
    domain, a redirect target outside the allowlist — is rejected."""
    host = urlsplit(url).hostname
    if not host:
        return False
    host = host.lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS)
