"""§6.28.1 / C34 — canonical listing URLs for discovery leads. AC40."""

from __future__ import annotations

import pytest

from competitor_intelligence.discovery.listing_url import (
    CanonicalListing,
    DropReason,
    canonicalize_listing_url,
)
from competitor_intelligence.types import Marketplace


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.in/Milton-Thermosteel-Bottle/dp/B09ABC1234/ref=sr_1_3?keywords=bottle&tag=x",
        "https://amazon.in/dp/b09abc1234",
        "https://www.amazon.in/gp/product/B09ABC1234?th=1",
        "http://m.amazon.in/dp/B09ABC1234/",
    ],
)
def test_amazon_listing_variants_collapse_to_one_canonical_url(url: str) -> None:
    result = canonicalize_listing_url(url)
    assert result == CanonicalListing(url="https://www.amazon.in/dp/B09ABC1234", marketplace=Marketplace.AMAZON)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.in/s?k=steel+bottle",
        "https://www.amazon.in/b?node=12345",
        "https://www.amazon.in/",
        "https://www.amazon.in/dp/TOOSHORT",
    ],
)
def test_amazon_non_listing_pages_are_dropped(url: str) -> None:
    assert canonicalize_listing_url(url) is DropReason.NOT_A_LISTING_URL


def test_flipkart_keeps_pid_and_drops_tracking_params() -> None:
    result = canonicalize_listing_url(
        "https://www.flipkart.com/cello-steel-flask/p/itm123abc?pid=BTLGH5F2&lid=LSTx&marketplace=FLIPKART"
    )
    assert result == CanonicalListing(
        url="https://www.flipkart.com/cello-steel-flask/p/itm123abc?pid=BTLGH5F2", marketplace=Marketplace.FLIPKART
    )


def test_flipkart_search_and_category_pages_are_dropped() -> None:
    assert canonicalize_listing_url("https://www.flipkart.com/search?q=steel+bottle") is DropReason.NOT_A_LISTING_URL
    assert canonicalize_listing_url("https://www.flipkart.com/home-kitchen/pr?sid=abc") is DropReason.NOT_A_LISTING_URL


def test_meesho_product_path_kept_query_dropped() -> None:
    result = canonicalize_listing_url("https://www.meesho.com/steel-bottle/p/4abcd?utm_source=x")
    assert result == CanonicalListing(url="https://www.meesho.com/steel-bottle/p/4abcd", marketplace=Marketplace.MEESHO)


def test_meesho_search_page_is_dropped() -> None:
    assert canonicalize_listing_url("https://www.meesho.com/search?q=bottle") is DropReason.NOT_A_LISTING_URL


def test_short_links_are_kept_as_given_and_bare_hosts_dropped() -> None:
    kept = canonicalize_listing_url("https://amzn.in/d/abc123")
    assert kept == CanonicalListing(url="https://amzn.in/d/abc123", marketplace=Marketplace.AMAZON)
    assert canonicalize_listing_url("https://amzn.in/") is DropReason.NOT_A_LISTING_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://www.indiamart.com/proddetail/steel-bottle-123.html",
        "https://www.amazon.in.evil.example/dp/B09ABC1234",
        "https://evil.example/www.amazon.in/dp/B09ABC1234",
        "https://notamazon.in/dp/B09ABC1234",
    ],
)
def test_off_allowlist_and_lookalike_hosts_are_dropped(url: str) -> None:
    assert canonicalize_listing_url(url) is DropReason.OFF_ALLOWLIST


@pytest.mark.parametrize("url", ["ftp://www.amazon.in/dp/B09ABC1234", "javascript:alert(1)", "not a url", ""])
def test_non_http_inputs_are_dropped(url: str) -> None:
    assert canonicalize_listing_url(url) in (DropReason.NOT_HTTP, DropReason.OFF_ALLOWLIST)
