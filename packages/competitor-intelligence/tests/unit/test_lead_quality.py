"""Search leads: junk is never surfaced, brands come first, and a competitor is named by its brand."""

from competitor_intelligence.discovery.lead_quality import brand_of, clean_title, is_junk, is_known_brand, lead_label, rank_key


def test_junk_leads_are_dropped():
    assert is_junk("These Cheap Ass Shoes eBook")
    assert is_junk("men casual shoes, men sneakers, stylish shoes for men, daily wear shoes, lightweight sneakers")
    assert is_junk("Shoes")
    assert not is_junk("MILTON Glide 1000 Stainless Steel Water Bottle")


def test_titles_are_cleaned_the_way_a_seller_says_them():
    assert clean_title("Buy Reebok Men Stride Runner Running Shoes All Black 6 ...") == "Reebok Men Stride Runner Running Shoes All Black 6"
    assert clean_title("CLEEVORA Corporate Stainless Steel Water Bottle 1L : Amazon.in: Home & Kit") == "CLEEVORA Corporate Stainless Steel Water Bottle 1L"
    assert clean_title("Amazon Brand - Solimo Stainless Steel Cubix Water Bottles") == "Solimo Stainless Steel Cubix Water Bottles"


def test_brand_is_what_the_title_leads_with_and_generic_words_are_not_a_brand():
    assert brand_of("MILTON Glide 1000 Stainless Steel Water Bottle") == "MILTON"
    assert brand_of("Buy Reebok Men Stride Runner") == "Reebok"
    assert brand_of("The Better Home Stainless Steel Water Bottle 1 Litre") == "The Better Home"
    assert brand_of("Budget Men's Shoes Size-6") is None
    assert brand_of("Comfortable Running Shoes for Active Men") is None
    assert brand_of("Men's Black Sports Shoes | Lightweight") is None


def test_known_brands_rank_first_then_any_brand_then_relevance():
    titles = {"Budget Men's Shoes Size-6": 3, "VANETIEN Casual Sneakers For Men": 1, "Puma Men Softride Running Shoes": 0}
    ordered = sorted(titles, key=lambda t: rank_key(t, titles[t]), reverse=True)
    assert ordered == ["Puma Men Softride Running Shoes", "VANETIEN Casual Sneakers For Men", "Budget Men's Shoes Size-6"]
    assert is_known_brand("Puma Men Softride") and not is_known_brand("VANETIEN Casual")


def test_the_tracked_name_leads_with_the_brand_and_stays_short():
    assert lead_label("Buy ASIAN Hypercushion Carbon-07 Men's Running Shoes for Sports & Training with Energy-Return Midsole | Bounce Cushioning").startswith("ASIAN Hypercushion")
    assert len(lead_label("A" * 200 + " shoes")) <= 70
