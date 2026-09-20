"""C4 — trusted-domain allowlist."""

from __future__ import annotations

import pytest

from competitor_intelligence.capture.allowlist import is_allowed_host


@pytest.mark.parametrize(
    "url",
    [
        "https://amazon.in/dp/xyz",
        "https://www.amazon.in/dp/xyz",
        "https://flipkart.com/p/abc",
        "https://www.flipkart.com/p/abc",
        "https://meesho.com/s/def",
        "https://m.meesho.com/s/def",
    ],
)
def test_allowed_hosts(url: str) -> None:
    assert is_allowed_host(url) is True


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
