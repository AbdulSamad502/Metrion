"""reasoning/narration_safety.py — PI's copy of CFO's mechanism plus three PI-specific
checks (§0's estimate-range language, no trending/bestseller/popular, no unqualified
"review")."""

from __future__ import annotations

from product_intelligence.reasoning.narration_safety import FigureToken, check_narration_safety


def _estimate_figure(label: str = "feasibility estimate", value: str = "₹450 - ₹600") -> FigureToken:
    return FigureToken(label=label, formatted_value=value, register="ESTIMATE")


def _unavailable_figure(label: str = "demand signal") -> FigureToken:
    return FigureToken(label=label, formatted_value="UNAVAILABLE", register="UNAVAILABLE")


# --- base mechanism (fabricated numbers, UNAVAILABLE stated as real) ------------------------


def test_narrative_citing_only_source_numbers_is_safe() -> None:
    figures = [FigureToken(label="price", formatted_value="₹500", register="MANUAL")]
    result = check_narration_safety("Your target price is ₹500.", figures)
    assert result.is_safe is True
    assert result.fabricated_numbers == ()


def test_narrative_with_a_number_not_in_any_figure_is_fabricated() -> None:
    figures = [FigureToken(label="price", formatted_value="₹500", register="MANUAL")]
    result = check_narration_safety("Your target price is ₹999.", figures)
    assert result.is_safe is False
    assert "999" in result.fabricated_numbers


def test_unavailable_figure_stated_without_unavailable_language_fails() -> None:
    figures = [_unavailable_figure()]
    result = check_narration_safety("The demand signal for this candidate looks strong.", figures)
    assert result.is_safe is False
    assert "demand signal" in result.unavailable_figures_stated_as_real


def test_unavailable_figure_named_with_unavailable_language_passes() -> None:
    figures = [_unavailable_figure()]
    result = check_narration_safety("The demand signal is unavailable for this candidate.", figures)
    assert result.unavailable_figures_stated_as_real == ()


# --- check 1: estimate-range language required for ESTIMATE-register figures ----------------


def test_estimate_figure_without_qualifying_language_fails() -> None:
    # Label deliberately does not itself contain a qualifier word (e.g. "estimate") — the
    # check inspects a window around the label match in the narrative, so a label that already
    # contains "estimate" would trivially satisfy the qualifier-word scan.
    figures = [_estimate_figure(label="profit potential")]
    result = check_narration_safety("Your profit potential is ₹450 - ₹600.", figures)
    assert result.is_safe is False
    assert "profit potential" in result.estimate_figures_missing_qualifier


def test_estimate_figure_with_qualifying_language_passes() -> None:
    figures = [_estimate_figure()]
    result = check_narration_safety(
        "The feasibility estimate is an approximate range of ₹450 - ₹600, not confirmed.", figures
    )
    assert result.estimate_figures_missing_qualifier == ()


# --- check 2: "trending"/"bestseller"/"popular" never appears -------------------------------


def test_trending_language_is_caught() -> None:
    result = check_narration_safety("This is a trending product opportunity right now.", [])
    assert result.is_safe is False
    assert "trending" in result.trending_language_found


def test_bestseller_language_is_caught() -> None:
    result = check_narration_safety("This candidate is a bestseller in its category.", [])
    assert result.is_safe is False
    assert "bestseller" in result.trending_language_found


def test_popular_language_is_caught() -> None:
    result = check_narration_safety("This is a popular choice among sellers.", [])
    assert "popular" in result.trending_language_found


def test_narrative_with_none_of_the_banned_words_is_clean_on_that_check() -> None:
    result = check_narration_safety("This is a candidate opportunity worth investigating.", [])
    assert result.trending_language_found == ()


# --- check 3: "review" never appears unqualified by "viewer"/"web" --------------------------


def test_unqualified_review_word_is_caught() -> None:
    result = check_narration_safety("Reviews say this product has great battery life.", [])
    assert result.is_safe is False
    assert result.unqualified_review_mentions is True


def test_viewer_qualified_review_word_passes() -> None:
    result = check_narration_safety("Viewer reviews mention great battery life.", [])
    assert result.unqualified_review_mentions is False


def test_web_qualified_review_word_passes() -> None:
    result = check_narration_safety("Web reviews mention great battery life.", [])
    assert result.unqualified_review_mentions is False


def test_narrative_with_no_review_word_at_all_passes() -> None:
    result = check_narration_safety("This candidate has strong viewer commentary.", [])
    assert result.unqualified_review_mentions is False
