"""derive_listing_insight() — pure deterministic string analysis over seller-submitted
listing text already stored on a snapshot. No model call, no fabricated `image_count`."""

from __future__ import annotations

from competitor_intelligence.listing_insight.derive import derive_listing_insight
from competitor_intelligence.types import Confidence, DerivationMethod, InsightState


def test_no_text_at_all_is_unavailable() -> None:
    draft = derive_listing_insight(title=None, description=None, bullets=None)
    assert draft.insight_state == InsightState.UNAVAILABLE
    assert draft.confidence == Confidence.UNAVAILABLE
    assert draft.degraded_reason is not None


def test_image_count_is_never_populated() -> None:
    draft = derive_listing_insight(title="Wireless Mouse", description=None, bullets=None)
    assert draft.image_count is None


def test_title_only_is_complete_with_structure_and_length() -> None:
    draft = derive_listing_insight(title="Logitech Wireless Mouse M185", description=None, bullets=None)
    assert draft.insight_state == InsightState.COMPLETE
    assert draft.title_length == len("Logitech Wireless Mouse M185")
    assert draft.title_structure["word_count"] == 4
    assert draft.title_structure["has_numbers"] is True
    assert draft.derivation_method == DerivationMethod.LOCAL_HEURISTIC


def test_no_title_but_description_present_is_degraded() -> None:
    draft = derive_listing_insight(title=None, description="A great mouse for everyday use", bullets=None)
    assert draft.insight_state == InsightState.DEGRADED
    assert draft.degraded_reason is not None


def test_bullet_count_reflects_actual_bullets_not_fabricated_when_none() -> None:
    with_bullets = derive_listing_insight(title="X", description=None, bullets=["a", "b", "c"])
    assert with_bullets.bullet_count == 3

    without_bullets = derive_listing_insight(title="X", description=None, bullets=None)
    assert without_bullets.bullet_count is None


def test_keyword_themes_extracted_from_title_and_bullets() -> None:
    draft = derive_listing_insight(
        title="Waterproof Bluetooth Speaker", description=None, bullets=["Waterproof design", "10 hour battery"]
    )
    assert "waterproof" in draft.keyword_themes
    assert "bluetooth" in draft.keyword_themes


def test_feature_categories_matches_generic_terms() -> None:
    draft = derive_listing_insight(title="Black Silicone Waterproof Case", description=None, bullets=None)
    assert draft.feature_categories.get("color") == 1  # "black"
    assert draft.feature_categories.get("material") == 1  # "silicone"
    assert draft.feature_categories.get("durability") == 1  # "waterproof"


def test_benefit_term_patterns_counts_recognized_terms() -> None:
    draft = derive_listing_insight(
        title="Premium Durable Case", description="Lifetime warranty, fast shipping guaranteed", bullets=None
    )
    assert draft.benefit_term_patterns.get("premium") == 1
    assert draft.benefit_term_patterns.get("durable") == 1
    assert draft.benefit_term_patterns.get("warranty") == 1
    assert draft.benefit_term_patterns.get("guaranteed") == 1


def test_differentiation_opportunities_flags_themes_common_elsewhere_but_missing_here() -> None:
    others = [frozenset({"waterproof", "bluetooth"}), frozenset({"waterproof", "rechargeable"})]
    draft = derive_listing_insight(title="Basic Speaker", description=None, bullets=None, other_competitor_theme_sets=others)
    # "waterproof" appears in >=2 other competitors and is absent from this listing's own themes.
    assert "waterproof" in draft.differentiation_opportunities


def test_differentiation_opportunities_excludes_themes_this_listing_already_has() -> None:
    others = [frozenset({"bluetooth"}), frozenset({"bluetooth"})]
    draft = derive_listing_insight(title="Bluetooth Speaker", description=None, bullets=None, other_competitor_theme_sets=others)
    assert "bluetooth" not in draft.differentiation_opportunities


def test_no_other_competitors_yields_empty_differentiation_list_not_unavailable() -> None:
    draft = derive_listing_insight(title="Standalone Product", description=None, bullets=None)
    assert draft.differentiation_opportunities == []
    assert draft.insight_state == InsightState.COMPLETE
