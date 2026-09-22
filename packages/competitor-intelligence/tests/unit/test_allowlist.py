"""C4/D7 — trusted-domain allowlist."""

from __future__ import annotations

import pytest

from competitor_intelligence.capture.allowlist import is_allowed_host, marketplace_for_host
from competitor_intelligence.types import Marketplace


@pytest.mark.parametrize(
    "url",
    [
        "https://amazon.in/dp/xyz",
        "https://www.amazon.in/dp/xyz",
        "https://flipkart.com/p/abc",
        "https://www.flipkart.com/p/abc",
        "https://meesho.com/s/def",
        "https://m.meesho.com/s/def",
        "https://amzn.in/d/01wB8Cr4",  # D7: Amazon's official short-link domain
        "https://fkrt.co/abc123",  # D7: Flipkart's official short-link domain
    ],
)
def test_allowed_hosts(url: str) -> None:
    assert is_allowed_host(url) is True


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://amazon.in/dp/xyz", Marketplace.AMAZON),
        ("https://amzn.in/d/01wB8Cr4", Marketplace.AMAZON),
        ("https://flipkart.com/p/abc", Marketplace.FLIPKART),
        ("https://fkrt.co/abc123", Marketplace.FLIPKART),
        ("https://meesho.com/s/def", Marketplace.MEESHO),
    ],
)
def test_marketplace_for_host(url: str, expected: Marketplace) -> None:
    assert marketplace_for_host(url) == expected


def test_marketplace_for_host_none_when_not_allowed() -> None:
    assert marketplace_for_host("https://notallowed.com/dp/xyz") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://notallowed.com/dp/xyz",
        "https://amazon.in.attacker.com/dp/xyz",  # look-alike domain, not a real subdomain
        "https://evil.com/amazon.in",
        "https://amazon.co.uk/dp/xyz",  # different TLD, not the confirmed amazon.in
        "not a url at all",
        "",
    ],
)
def test_rejected_hosts(url: str) -> None:
    assert is_allowed_host(url) is False
