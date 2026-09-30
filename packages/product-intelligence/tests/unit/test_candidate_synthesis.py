"""discovery/candidate_synthesis.py — grouping, title synthesis, demand_signal's fixed
UNAVAILABLE shape, web_price_signal extraction, capture_status degrade behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from product_intelligence.discovery.candidate_synthesis import (
    dedupe_by_normalized_title,
    synthesize_candidates,
)
from product_intelligence.discovery.product_extraction import ProductExtractionUnavailable
from product_intelligence.discovery.ranking import DEMAND_UNAVAILABLE_REASON
from product_intelligence.sources.tavily_client import TavilyImage, TavilySearchResult
from product_intelligence.sources.youtube_client import YoutubeVideo

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def _tavily_result(url: str, title: str, content: str, published_date: str | None = None) -> TavilySearchResult:
    return TavilySearchResult(
        url=url, title=title, content=content, score=0.9, published_date=published_date, retrieved_at=_NOW
    )


def _youtube_video(video_id: str, title: str) -> YoutubeVideo:
    return YoutubeVideo(
        video_id=video_id,
        title=title,
        channel_title="Some Channel",
        view_count=1000,
        comment_count=10,
        thumbnail_url="https://img.example.com/thumb.jpg",
        published_at=_NOW,
        retrieved_at=_NOW,
    )


def test_demand_signal_is_always_the_fixed_unavailable_shape() -> None:
    results = [_tavily_result("https://a.com/1", "Wireless Earbuds Review", "great wireless earbuds")]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)

    assert len(candidates) == 1
    assert candidates[0].demand_signal == {"status": "UNAVAILABLE", "reason": DEMAND_UNAVAILABLE_REASON}


def test_candidate_title_is_a_real_lightly_cleaned_title_not_a_word_frequency_mashup() -> None:
    """Bug-fix pass (2026-09-30): candidate_title is now a real, lightly-cleaned title from
    one of the group's actual sources — the old word-frequency synthesis produced unreadable
    mashups like "Shoes Sole Test Red Tape Etpu" for genuinely different, multi-word content.
    This fixture has titles the old frequency-joining algorithm would have mangled."""
    results = [
        _tavily_result(
            "https://a.com/1",
            "Red Tape Men's Running Shoes with EVA Sole | ShoeWorld",
            "durable running shoes for daily training, breathable mesh upper",
        )
    ]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)

    # a real, cleaned title from the actual source — boilerplate " | ShoeWorld" suffix
    # stripped, but the substantive phrase kept intact and in original order.
    assert candidates[0].candidate_title == "Red Tape Men's Running Shoes with EVA Sole"


def test_candidate_title_strips_leading_best_n_listicle_framing() -> None:
    results = [
        _tavily_result(
            "https://a.com/1",
            "10 Best Wireless Earbuds for Gym Use in 2026",
            "wireless earbuds for the gym, sweat resistant, long battery life",
        )
    ]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)

    assert candidates[0].candidate_title == "Wireless Earbuds for Gym Use in 2026"


def test_results_about_the_same_idea_are_grouped_into_one_candidate() -> None:
    results = [
        _tavily_result("https://a.com/1", "Wireless Earbuds Charging Case", "wireless earbuds charging case"),
        _tavily_result("https://b.com/2", "Wireless Earbuds Charging Case Review", "wireless earbuds charging case"),
    ]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)

    assert len(candidates) == 1
    assert candidates[0].source_diversity == 2


def test_web_price_signal_unavailable_when_no_price_mentioned() -> None:
    results = [_tavily_result("https://a.com/1", "Wireless Earbuds", "no price mentioned here at all")]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)

    assert candidates[0].web_price_signal["status"] == "UNAVAILABLE"


def test_web_price_signal_extracts_rupee_prices_and_always_carries_a_disclaimer() -> None:
    results = [
        _tavily_result(
            "https://a.com/1",
            "Wireless Earbuds",
            "priced at ₹1,499 on most sites, sometimes Rs. 1,599 elsewhere",
            "2026-09-15",
        )
    ]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)

    signal = candidates[0].web_price_signal
    assert signal["status"] == "AVAILABLE"
    assert signal["sample_count"] == 2
    assert signal["range_low_paise"] == 149_900
    assert signal["range_high_paise"] == 159_900
    assert "not a verified marketplace price" in signal["disclaimer"]
    assert signal["most_recent_mention"] == "2026-09-15"


def test_capture_status_ok_when_neither_source_degraded() -> None:
    results = [_tavily_result("https://a.com/1", "Wireless Earbuds", "wireless earbuds content")]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)
    assert candidates[0].capture_status == "OK"


def test_capture_status_partial_when_one_source_degraded() -> None:
    results = [_tavily_result("https://a.com/1", "Wireless Earbuds", "wireless earbuds content")]
    candidates = synthesize_candidates(
        tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW, youtube_degraded=True
    )
    assert candidates[0].capture_status == "PARTIAL"


def test_capture_status_unavailable_when_both_sources_degraded() -> None:
    results = [_tavily_result("https://a.com/1", "Wireless Earbuds", "wireless earbuds content")]
    candidates = synthesize_candidates(
        tavily_results=results,
        tavily_images=[],
        youtube_videos=[],
        now=_NOW,
        tavily_degraded=True,
        youtube_degraded=True,
    )
    assert candidates[0].capture_status == "UNAVAILABLE"


def test_raw_text_is_carried_ephemerally_for_the_same_call_chain_only() -> None:
    results = [_tavily_result("https://a.com/1", "Wireless Earbuds", "wireless earbuds snippet text")]
    video = _youtube_video("vid1", "Wireless Earbuds Unboxing")
    candidates = synthesize_candidates(
        tavily_results=results, tavily_images=[], youtube_videos=[video], now=_NOW
    )
    # a title-token overlap groups these into different candidates unless keywords align;
    # assert instead on whichever candidate carries the tavily result's own raw content.
    matching = [c for c in candidates if "wireless earbuds snippet text" in c.web_snippet_texts]
    assert matching, "synthesized candidate must carry the raw snippet ephemerally for review_insight"


def test_dedupe_by_normalized_title_collapses_case_and_whitespace_variants() -> None:
    rows = [
        {"candidate_title": "Wireless Earbuds"},
        {"candidate_title": "  wireless   earbuds "},
        {"candidate_title": "Something Else"},
    ]
    deduped = dedupe_by_normalized_title(rows)
    assert len(deduped) == 2


def test_no_candidates_synthesized_from_empty_input() -> None:
    candidates = synthesize_candidates(tavily_results=[], tavily_images=[], youtube_videos=[], now=_NOW)
    assert candidates == []


# --- Two-tier grouping (product_extraction-first, Jaccard fallback) --------------------------


class _FakeExtractionClient:
    """Fake `ProductExtractionClient` — deterministic, no live Ollama call. `mentions_by_text`
    maps exact combined-text strings to the list of products to "extract" from them; any text
    not in the map raises `ProductExtractionUnavailable` unless `default` is given."""

    def __init__(self, mentions_by_text: dict[str, list[str]] | None = None, *, default: list[str] | None = None) -> None:
        self._mentions_by_text = mentions_by_text or {}
        self._default = default

    def extract_products(self, text: str, *, category_text: str) -> list[str]:
        if text in self._mentions_by_text:
            return self._mentions_by_text[text]
        if self._default is not None:
            return self._default
        raise ProductExtractionUnavailable("no fake mapping for this text")


def test_roundup_article_mentioning_three_products_yields_three_candidates_same_source() -> None:
    """A fixture roundup-article-shaped content string that "mentions" 3 fake products via a
    fake extraction client yields 3 differently-titled candidates, all attributed back to the
    same source_url — the core precision fix this module exists for."""
    content = "a roundup article body mentioning several specific shoes"
    result = _tavily_result("https://roundup.example.com/best-shoes", "The 10 Best Running Shoes for Men in 2026", content)
    combined_text = f"{result.title}\n{result.content}".strip()

    client = _FakeExtractionClient({combined_text: ["Nike Pegasus 41", "Asics Novablast 4", "Adidas Adizero SL"]})

    candidates = synthesize_candidates(
        tavily_results=[result],
        tavily_images=[],
        youtube_videos=[],
        now=_NOW,
        product_extraction_client=client,
        category_text="men's running shoes",
    )

    assert len(candidates) == 3
    titles = {c.candidate_title for c in candidates}
    assert titles == {"Nike Pegasus 41", "Asics Novablast 4", "Adidas Adizero SL"}
    for candidate in candidates:
        assert candidate.confidence == "DERIVED"
        assert candidate.source_urls == [
            {"url": "https://roundup.example.com/best-shoes", "fetched_at": _NOW.isoformat(), "source": "tavily"}
        ]
        assert candidate.primary_web_source_url == "https://roundup.example.com/best-shoes"


def test_extraction_returning_empty_list_falls_back_to_old_whole_title_behavior() -> None:
    """A fixture with a fake client returning an empty list falls back to the old whole-title
    behavior and is honestly marked as such via `confidence`."""
    result = _tavily_result(
        "https://a.com/1",
        "Wireless Earbuds Charging Case",
        "just a general discussion thread, no specific product literally named",
    )
    client = _FakeExtractionClient(default=[])

    candidates = synthesize_candidates(
        tavily_results=[result],
        tavily_images=[],
        youtube_videos=[],
        now=_NOW,
        product_extraction_client=client,
        category_text="wireless earbuds",
    )

    assert len(candidates) == 1
    assert candidates[0].candidate_title == "Wireless Earbuds Charging Case"
    assert candidates[0].confidence == "DERIVED_NO_PRODUCT_EXTRACTED"


def test_extraction_unavailable_falls_back_to_old_whole_title_behavior_never_drops_source() -> None:
    """`ProductExtractionUnavailable` degrades that one source to the fallback path — never
    silently dropped from the run — and is honestly flagged as a technical failure, distinct
    from a genuine "extraction ran and found nothing" result (never narrating a non-result as
    a real negative result)."""
    result = _tavily_result("https://a.com/1", "Wireless Earbuds Charging Case", "wireless earbuds charging case")
    client = _FakeExtractionClient()  # no mapping at all -> always raises ProductExtractionUnavailable

    candidates = synthesize_candidates(
        tavily_results=[result],
        tavily_images=[],
        youtube_videos=[],
        now=_NOW,
        product_extraction_client=client,
        category_text="wireless earbuds",
    )

    assert len(candidates) == 1
    assert candidates[0].candidate_title == "Wireless Earbuds Charging Case"
    assert candidates[0].confidence == "DERIVED_EXTRACTION_UNAVAILABLE"


def test_no_extraction_client_supplied_preserves_exact_previous_behavior() -> None:
    """`product_extraction_client=None` (the default) must produce byte-identical behavior to
    the pre-existing calling convention — full backward compatibility."""
    results = [
        _tavily_result(
            "https://a.com/1",
            "Red Tape Men's Running Shoes with EVA Sole | ShoeWorld",
            "durable running shoes for daily training, breathable mesh upper",
        )
    ]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)

    assert candidates[0].candidate_title == "Red Tape Men's Running Shoes with EVA Sole"
    assert candidates[0].confidence == "DERIVED"


def test_extracted_product_names_group_by_normalized_equality_across_sources() -> None:
    """Two different sources both literally naming the same product (with trivial whitespace
    differences) merge into one candidate, still attributed to both source URLs."""
    result_a = _tavily_result("https://a.com/1", "Roundup A", "mentions a product")
    result_b = _tavily_result("https://b.com/2", "Roundup B", "also mentions the same product")
    text_a = f"{result_a.title}\n{result_a.content}".strip()
    text_b = f"{result_b.title}\n{result_b.content}".strip()

    client = _FakeExtractionClient({text_a: ["Nike Pegasus 41"], text_b: ["nike   pegasus 41"]})

    candidates = synthesize_candidates(
        tavily_results=[result_a, result_b],
        tavily_images=[],
        youtube_videos=[],
        now=_NOW,
        product_extraction_client=client,
        category_text="running shoes",
    )

    assert len(candidates) == 1
    assert len(candidates[0].source_urls) == 2


def test_extraction_never_merges_different_model_numbers() -> None:
    """Different model numbers must stay distinct candidates — the collapsed-key match is
    deliberately conservative (module docstring) and must not merge "Pegasus 40" with
    "Pegasus 41"."""
    result_a = _tavily_result("https://a.com/1", "Roundup A", "mentions one shoe")
    result_b = _tavily_result("https://b.com/2", "Roundup B", "mentions a different shoe")
    text_a = f"{result_a.title}\n{result_a.content}".strip()
    text_b = f"{result_b.title}\n{result_b.content}".strip()

    client = _FakeExtractionClient({text_a: ["Nike Pegasus 40"], text_b: ["Nike Pegasus 41"]})

    candidates = synthesize_candidates(
        tavily_results=[result_a, result_b],
        tavily_images=[],
        youtube_videos=[],
        now=_NOW,
        product_extraction_client=client,
        category_text="running shoes",
    )

    assert len(candidates) == 2
    assert {c.candidate_title for c in candidates} == {"Nike Pegasus 40", "Nike Pegasus 41"}


def test_youtube_video_extraction_combines_title_and_channel_for_context() -> None:
    video = _youtube_video("vid1", "Top 5 running shoes this year")
    combined_text = f"{video.title} — {video.channel_title}".strip(" —")
    client = _FakeExtractionClient({combined_text: ["Hoka Clifton 9"]})

    candidates = synthesize_candidates(
        tavily_results=[],
        tavily_images=[],
        youtube_videos=[video],
        now=_NOW,
        product_extraction_client=client,
        category_text="running shoes",
    )

    assert len(candidates) == 1
    assert candidates[0].candidate_title == "Hoka Clifton 9"
    assert candidates[0].youtube_video_ids == ("vid1",)


def test_image_is_labeled_with_source_url_never_implied_as_marketplace_photo() -> None:
    results = [_tavily_result("https://a.com/1", "Wireless Earbuds", "wireless earbuds content")]
    images = [TavilyImage(url="https://img.example.com/1.jpg", source_url="https://a.com/1", description="wireless earbuds")]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=images, youtube_videos=[], now=_NOW)

    assert candidates[0].image_url == "https://img.example.com/1.jpg"
    assert candidates[0].image_source_url == "https://a.com/1"
