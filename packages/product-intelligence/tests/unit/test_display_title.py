from product_intelligence.discovery.prerank import clean_display_title


def test_video_hashtags_are_removed_from_a_title() -> None:
    assert clean_display_title("Designer Artificial Jewellery #shortvideo #shorts #youtubeshorts #viral") == "Designer Artificial Jewellery"
    assert clean_display_title("Sony WF-1000XM5") == "Sony WF-1000XM5"
    assert clean_display_title(None) == ""
