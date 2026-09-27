"""§8.4.1's two-tier GST fetch allowlist — mirrors
`competitor_intelligence/tests/unit/test_allowlist.py`'s structure."""

from __future__ import annotations

import pytest

from calc_engine.gst_lookup.allowlist import TIER_1, TIER_2, is_allowed_gst_host, tier_for_host


@pytest.mark.parametrize(
    "url",
    [
        "https://cbic-gst.gov.in/gst-goods-services-rates.html",
        "https://taxinformation.cbic.gov.in/some-page",
        "https://gst.gov.in/",
        "https://cleartax.in/s/gst-rates",
        "https://taxguru.in/goods-and-service-tax/gst-rate.html",
        "https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517",
        "https://busy.in/gst-rates/stationery/",
        "https://www.gimbooks.com/blog/new-gst-rates-in-india-2025/",
        "https://rushtax.app/gst-rates/electronics-appliances/",
        "https://taxgarden.in/blog/gst-on-mobile-phones-laptops-electronics-india-2026",
    ],
)
def test_allowed_hosts(url: str) -> None:
    assert is_allowed_gst_host(url) is True


@pytest.mark.parametrize(
    "url,expected_tier",
    [
        ("https://cbic-gst.gov.in/gst-goods-services-rates.html", TIER_1),
        ("https://taxinformation.cbic.gov.in/some-page", TIER_1),
        ("https://gst.gov.in/", TIER_1),
        ("https://cleartax.in/s/gst-rates", TIER_2),
        ("https://taxguru.in/goods-and-service-tax/gst-rate.html", TIER_2),
        ("https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517", TIER_2),
        ("https://busy.in/gst-rates/stationery/", TIER_2),
        ("https://www.gimbooks.com/blog/new-gst-rates-in-india-2025/", TIER_2),
        ("https://rushtax.app/gst-rates/electronics-appliances/", TIER_2),
        ("https://taxgarden.in/blog/gst-on-mobile-phones-laptops-electronics-india-2026", TIER_2),
    ],
)
def test_tier_for_host(url: str, expected_tier: str) -> None:
    assert tier_for_host(url) == expected_tier


def test_tier_for_host_none_when_not_allowed() -> None:
    assert tier_for_host("https://notallowed.com/gst-rates") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://notallowed.com/gst-rates",
        "https://busy.in.attacker.com/gst-rates/stationery/",  # look-alike, not a real subdomain
        "https://evil.com/busy.in",
        "https://cleartax.in.co/s/gst-rates",  # different TLD/host, not the confirmed domain
        "not a url at all",
        "",
    ],
)
def test_rejected_hosts(url: str) -> None:
    assert is_allowed_gst_host(url) is False
