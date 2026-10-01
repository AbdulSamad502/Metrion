"""discovery/candidate_synthesis.py — grouping, title synthesis, demand_signal's fixed
UNAVAILABLE shape, web_price_signal extraction, capture_status degrade behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from product_intelligence.discovery.candidate_synthesis import (
    dedupe_by_normalized_title,
    filter_excluded_brands,
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


def test_web_price_signal_paise_conversion_uses_decimal_not_float() -> None:
    """Quality pass (2026-10-01): ₹19.99 * 100 is exactly 1999 paise under Decimal; a float
    conversion can drift (0.1-style binary-fraction imprecision) for values like this. Not
    fed into any calc-engine math (§0g), but still a money figure and the project's
    no-float-in-a-money-path discipline applies to the conversion itself."""
    results = [_tavily_result("https://a.com/1", "Cable", "priced at Rs. 19.99 on most sites")]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=[], youtube_videos=[], now=_NOW)

    signal = candidates[0].web_price_signal
    assert signal["range_low_paise"] == 1_999
    assert signal["range_high_paise"] == 1_999


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


def test_filter_excluded_brands_removes_matching_candidates_only() -> None:
    """New 2026-10-01: seller-stated `niche_brief.constraints.exclude_brands` — a plain,
    structured exclusion list, never an LLM-inferred 'too famous' judgement."""
    rows = [
        {"candidate_title": "Nike Pegasus 41"},
        {"candidate_title": "New Balance 1080v15"},
        {"candidate_title": "Acme Runner Pro"},
    ]
    kept = filter_excluded_brands(rows, ["Nike", "New Balance"])
    assert [r["candidate_title"] for r in kept] == ["Acme Runner Pro"]


def test_filter_excluded_brands_requires_every_brand_token_not_a_substring() -> None:
    """"Nike" must not exclude a candidate that merely contains "nike" inside a longer,
    unrelated token — token-set containment, not substring search."""
    rows = [{"candidate_title": "Nikewear Pro Runner"}]
    # "nikewear" tokenizes as its own distinct token, not "nike" + "wear", so it is NOT a
    # superset-match for the single-token brand set {"nike"} unless literally equal.
    kept = filter_excluded_brands(rows, ["Nike"])
    assert len(kept) == 1


def test_filter_excluded_brands_empty_list_or_none_is_a_no_op() -> None:
    rows = [{"candidate_title": "Nike Pegasus 41"}]
    assert filter_excluded_brands(rows, None) == rows
    assert filter_excluded_brands(rows, []) == rows


def test_filter_excluded_brands_skips_non_string_entries_without_raising() -> None:
    """Bug-hunt regression (2026-10-01): `niche_brief.constraints` is accepted unvalidated at
    the HTTP boundary, so `exclude_brands` could contain a non-string entry. Previously this
    crashed `_tokenize`'s `.lower()` call uncaught, aborting the whole run."""
    rows = [{"candidate_title": "Nike Pegasus 41"}, {"candidate_title": "Acme Runner Pro"}]
    kept = filter_excluded_brands(rows, [123, None, "Nike"])  # type: ignore[list-item]
    assert [r["candidate_title"] for r in kept] == ["Acme Runner Pro"]


def test_filter_excluded_brands_ignores_a_brand_too_short_to_tokenize() -> None:
    """A brand name that tokenizes to nothing (e.g. "On", below the significance floor) must
    never vacuously exclude every candidate (empty set is a subset of everything in Python)."""
    rows = [{"candidate_title": "Nike Pegasus 41"}, {"candidate_title": "Hoka Clifton 9"}]
    kept = filter_excluded_brands(rows, ["On"])
    assert len(kept) == 2


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


def test_image_matched_via_title_description_containment_when_no_source_url_match() -> None:
    """Real-data regression (2026-10-01): Tavily's `images_for` response, in practice, never
    carries a genuine page-URL association with a search result (`source_url` is just the
    image's own CDN URL) — confirmed via live testing against the real API. The only honest
    fallback signal is the image's own `title`/`description` text genuinely naming the
    candidate, matched via containment of the candidate's own tokens (not diluted Jaccard —
    see `_token_containment`'s docstring for why symmetric IoU under-matches here)."""
    results = [_tavily_result("https://asics.com/gel-nimbus-28", "ASICS GEL-NIMBUS 28 Running Shoe", "content")]
    images = [
        TavilyImage(
            url="https://img.example.com/nimbus28.jpg",
            source_url="https://img.example.com/nimbus28.jpg",  # not any result's own url
            description="A blue and white men's running shoe with a cushioned sole",
            title="ASICS — Official GEL-NIMBUS Store Page",
        )
    ]

    class _Extractor:
        def extract_products(self, text, *, category_text):
            return ["ASICS GEL-NIMBUS 28"]

    candidates = synthesize_candidates(
        tavily_results=results, tavily_images=images, youtube_videos=[], now=_NOW,
        product_extraction_client=_Extractor(), category_text="running shoes",
    )

    assert candidates[0].candidate_title == "ASICS GEL-NIMBUS 28"
    assert candidates[0].image_url == "https://img.example.com/nimbus28.jpg"


def test_image_never_matched_via_a_single_generic_identity_token() -> None:
    """Real-data regression (live testing, 2026-10-01): "UA HB Runner 2" tokenizes to just
    {"runner"} (short abbreviations are filtered below the length-3 floor), which then
    trivially containment-matched an unrelated ASICS image whose description happened to
    mention "running" — confirmed against real Tavily data. A candidate whose own identity
    reduces to fewer than 2 significant tokens must never get an image via containment
    matching; a one-word identity is too generic to honestly claim a match."""
    results = [_tavily_result("https://underarmour.com/ua-hb-runner-2", "UA HB Runner 2", "content")]
    images = [
        TavilyImage(
            url="https://img.example.com/asics.jpg",
            source_url="https://img.example.com/asics.jpg",
            description="A grey and white men's running shoe with cushioned sole",
            title="ASICS — Official Novablast Store Page",
        )
    ]

    class _Extractor:
        def extract_products(self, text, *, category_text):
            return ["UA HB Runner 2"]

    candidates = synthesize_candidates(
        tavily_results=results, tavily_images=images, youtube_videos=[], now=_NOW,
        product_extraction_client=_Extractor(), category_text="running shoes",
    )

    assert candidates[0].candidate_title == "UA HB Runner 2"
    assert candidates[0].image_url is None


def test_video_with_failed_extraction_still_attaches_to_an_already_extracted_product_group() -> None:
    """Real-data regression (live testing, 2026-10-01): a video whose own extraction found
    nothing (a common, legitimate outcome for a vague title) previously could only Jaccard-
    match against OTHER vague fallback entries, never against an already-extracted, richer
    tier-1 product group — even when its title plainly names that exact product. This
    fragmented one real product into two worse candidates (no engagement_signal/thumbnail on
    the real one, an orphan low-signal duplicate elsewhere) instead of merging correctly."""
    results = [
        _tavily_result(
            "https://asics.com/gel-nimbus-28", "ASICS GEL-NIMBUS 28", "The ASICS GEL-NIMBUS 28 running shoe"
        )
    ]
    videos = [
        YoutubeVideo(
            video_id="vid1", title="ASICS Gel Nimbus 28 - Is This Shoe Right For You?",
            channel_title="RunReviews", view_count=5000, comment_count=40,
            thumbnail_url="https://i.ytimg.com/vi/vid1/hqdefault.jpg", published_at=_NOW, retrieved_at=_NOW,
        )
    ]

    class _Extractor:
        def extract_products(self, text, *, category_text):
            # Succeeds for the Tavily result (clean, product-name-shaped text); returns
            # nothing for the video (simulating a real, legitimate "found nothing" outcome
            # for a vaguer, question-shaped title) — the exact asymmetry that caused this bug.
            if "running shoe" in text.lower():
                return ["ASICS GEL-NIMBUS 28"]
            return []

    candidates = synthesize_candidates(
        tavily_results=results, tavily_images=[], youtube_videos=videos, now=_NOW,
        product_extraction_client=_Extractor(), category_text="running shoes",
    )

    assert len(candidates) == 1
    assert candidates[0].candidate_title == "ASICS GEL-NIMBUS 28"
    assert candidates[0].engagement_signal["status"] == "AVAILABLE"
    assert candidates[0].source_diversity == 2


def test_youtube_thumbnail_used_as_image_fallback_when_no_tavily_image_matches() -> None:
    """New 2026-10-01: a YouTube video's own `thumbnail_url` is an unambiguous, directly-
    linked image for that specific video (no containment heuristic needed, unlike Tavily
    images) — used as a free fallback when no Tavily image honestly matches this candidate."""
    videos = [
        YoutubeVideo(
            video_id="vid123", title="ASICS GEL-NIMBUS 28 Review", channel_title="RunReviews",
            view_count=1000, comment_count=10, thumbnail_url="https://i.ytimg.com/vi/vid123/hqdefault.jpg",
            published_at=_NOW, retrieved_at=_NOW,
        )
    ]
    candidates = synthesize_candidates(
        tavily_results=[], tavily_images=[], youtube_videos=videos, now=_NOW,
    )

    assert len(candidates) == 1
    assert candidates[0].image_url == "https://i.ytimg.com/vi/vid123/hqdefault.jpg"
    assert candidates[0].image_source_url == "https://www.youtube.com/watch?v=vid123"


def test_youtube_thumbnail_fallback_never_overrides_a_real_tavily_match() -> None:
    results = [_tavily_result("https://a.com/1", "Wireless Earbuds", "wireless earbuds content")]
    images = [TavilyImage(url="https://img.example.com/1.jpg", source_url="https://a.com/1", description="earbuds")]
    videos = [
        YoutubeVideo(
            video_id="vid1", title="Wireless Earbuds Review", channel_title="c",
            view_count=1, comment_count=1, thumbnail_url="https://i.ytimg.com/vi/vid1/hqdefault.jpg",
            published_at=_NOW, retrieved_at=_NOW,
        )
    ]

    candidates = synthesize_candidates(tavily_results=results, tavily_images=images, youtube_videos=videos, now=_NOW)

    assert candidates[0].image_url == "https://img.example.com/1.jpg"


def test_image_never_cross_attributed_to_an_unrelated_candidate_group() -> None:
    """Honesty regression (quality pass, 2026-10-01): a candidate group with no real
    source-matched image must get no image at all, never another candidate's image reused
    as if it were sourced for this one (§0b — an image is always labeled 'image from
    [source domain]', which is false if it wasn't actually sourced from that candidate's
    own contributing result)."""
    results = [
        _tavily_result("https://a.com/earbuds", "Wireless Earbuds Pro", "wireless earbuds content"),
        _tavily_result("https://b.com/speaker", "Bluetooth Speaker X1", "bluetooth speaker content"),
    ]
    # Only the first result has a matching image; the second group must stay imageless
    # rather than inheriting this one.
    images = [
        TavilyImage(url="https://img.example.com/1.jpg", source_url="https://a.com/earbuds", description="earbuds"),
    ]
    candidates = synthesize_candidates(tavily_results=results, tavily_images=images, youtube_videos=[], now=_NOW)

    by_title = {c.candidate_title: c for c in candidates}
    assert by_title["Wireless Earbuds Pro"].image_url == "https://img.example.com/1.jpg"
    assert by_title["Bluetooth Speaker X1"].image_url is None
    assert by_title["Bluetooth Speaker X1"].image_source_url is None
