"""Reviews, option B: Metrion points the seller to where a competitor's reviews live (a link built from the listing link the seller already gave), reads nothing from it, and never treats a
search snippet as a review."""

from __future__ import annotations

from backend.services.ci_conv_data import review_source_url


def test_amazon_reviews_page_comes_from_the_asin():
    assert review_source_url("AMAZON", "https://www.amazon.in/Some-Bottle/dp/B0BETTERH1/ref=sr_1_1?th=1") == "https://www.amazon.in/product-reviews/B0BETTERH1"
    assert review_source_url("AMAZON", "https://www.amazon.in/dp/B0BETTERH1") == "https://www.amazon.in/product-reviews/B0BETTERH1"


def test_flipkart_reviews_page_keeps_the_product_ids():
    got = review_source_url("FLIPKART", "https://www.flipkart.com/steel-bottle/p/itm123abc?pid=BTLGF3XYZ&lid=LST1")
    assert got == "https://www.flipkart.com/steel-bottle/product-reviews/itm123abc?pid=BTLGF3XYZ"


def test_other_marketplaces_and_odd_links_fall_back_to_the_listing_link():
    assert review_source_url("MEESHO", "https://www.meesho.com/steel-bottle/p/abc12") == "https://www.meesho.com/steel-bottle/p/abc12"
    assert review_source_url("AMAZON", "https://www.amazon.in/gp/aw/d/x") == "https://www.amazon.in/gp/aw/d/x"
