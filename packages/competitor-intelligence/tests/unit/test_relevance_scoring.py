"""competitor-intelligence-agent.md §6.14 — the locked 8-axis relevance-scoring algorithm."""

from __future__ import annotations

import pytest

from competitor_intelligence.discovery.relevance_scoring import (
    AXIS_ORDER,
    AxisResult,
    AxisState,
    MAX_TOTAL_SCORE,
    ProductSimilarityTier,
    RelevanceBand,
    RelevanceScoreInputs,
    UseCaseSimilarityTier,
    compute_band,
    score_category,
    score_fulfillment,
    score_overlap,
    score_price_proximity,
    score_product_similarity,
    score_relevance,
    score_review_tier,
    score_use_case_similarity,
)

_KNOWN2 = AxisResult(2, AxisState.KNOWN)
_KNOWN1 = AxisResult(1, AxisState.KNOWN)
_KNOWN0 = AxisResult(0, AxisState.KNOWN)
_UNKNOWN = AxisResult(0, AxisState.UNKNOWN)


def _inputs(**overrides: AxisResult) -> RelevanceScoreInputs:
    defaults = dict(
        category=_KNOWN2,
        product=_KNOWN2,
        price_proximity=_KNOWN2,
        features=_KNOWN2,
        keywords=_KNOWN2,
        use_case=_KNOWN2,
        fulfillment=_KNOWN2,
        review_tier=_KNOWN2,
    )
    defaults.update(overrides)
    return RelevanceScoreInputs(**defaults)


# --------------------------------------------------------------------------------------
# The spec's own worked example (§6.14.3 step 3):
#   HIGH (13/16): category=2, product=2, price proximity=2, features=1,
#   keywords=2, use-case=2, fulfillment=UNKNOWN(0), review-tier=1
#
# NOTE: summing the eight axis values the spec itself gives here
# (2+2+2+1+2+2+0+1) yields 12, not the "13/16" the spec's prose states — the worked example
# as written is internally inconsistent (a total does not match the sum of its own listed
# per-axis scores). This is flagged as a spec inconsistency for the spec owner to confirm in
# writing (never silently "corrected" by inventing a fudge factor here). This test
# reproduces the LOCKED RULE exactly (deterministic sum of the eight given axis scores, then
# banded by §6.14.3 step 2) against the spec's own per-axis inputs, and asserts the total the
# rule actually produces (12), plus the HIGH band those inputs and rule produce.
# --------------------------------------------------------------------------------------


def test_worked_example_axis_inputs_reproduce_locked_sum_and_band() -> None:
    inputs = RelevanceScoreInputs(
        category=AxisResult(2, AxisState.KNOWN),
        product=AxisResult(2, AxisState.KNOWN),
        price_proximity=AxisResult(2, AxisState.KNOWN),
        features=AxisResult(1, AxisState.KNOWN),
        keywords=AxisResult(2, AxisState.KNOWN),
        use_case=AxisResult(2, AxisState.KNOWN),
        fulfillment=AxisResult(0, AxisState.UNKNOWN),
        review_tier=AxisResult(1, AxisState.KNOWN),
    )

    breakdown = score_relevance(inputs, is_provisional=True)

    assert breakdown.total_score == 12  # sum of the spec's own listed per-axis values
    assert breakdown.band is RelevanceBand.HIGH  # >=11 AND category>=1 AND product>=1
    assert breakdown.band_label == "HIGH (12/16)"
    assert breakdown.breakdown_line == (
        "HIGH (12/16): category=2, product=2, price proximity=2, features=1, "
        "keywords=2, use-case=2, fulfillment=UNKNOWN(0), review-tier=1"
    )
    assert breakdown.labelled_line() == (
        "Discovery relevance (provisional): " + breakdown.breakdown_line
    )


def test_confirmed_label_once_evidence_exists() -> None:
    inputs = _inputs()
    breakdown = score_relevance(inputs, is_provisional=False)
    assert breakdown.labelled_line().startswith("Relevance: ")


# --------------------------------------------------------------------------------------
# UNKNOWN/CONFLICTED axes always score 0, including seller-side-unknown (§6.14.2)
# --------------------------------------------------------------------------------------


def test_axis_result_rejects_nonzero_score_for_unknown_state() -> None:
    with pytest.raises(ValueError, match="must score 0"):
        AxisResult(2, AxisState.UNKNOWN)


def test_axis_result_rejects_nonzero_score_for_conflicted_state() -> None:
    with pytest.raises(ValueError, match="must score 0"):
        AxisResult(1, AxisState.CONFLICTED)


def test_price_proximity_seller_side_unknown_never_invents_a_baseline() -> None:
    result = score_price_proximity(None, 99900)
    assert result.score == 0
    assert result.state is AxisState.UNKNOWN


def test_price_proximity_candidate_unknown_is_unknown_not_zero_match() -> None:
    result = score_price_proximity(99900, None)
    assert result.score == 0
    assert result.state is AxisState.UNKNOWN


def test_category_missing_on_either_side_is_unknown() -> None:
    assert score_category(None, "Electronics").state is AxisState.UNKNOWN
    assert score_category("Electronics", None).state is AxisState.UNKNOWN


def test_fulfillment_missing_on_either_side_is_unknown() -> None:
    assert score_fulfillment(None, "FBA").state is AxisState.UNKNOWN
    assert score_fulfillment("SELLER_FULFILLED", None).state is AxisState.UNKNOWN


def test_review_tier_missing_is_unknown() -> None:
    assert score_review_tier(None, 500).state is AxisState.UNKNOWN
    assert score_review_tier(500, None).state is AxisState.UNKNOWN


def test_overlap_missing_set_is_unknown_not_zero_overlap() -> None:
    result = score_overlap(None, frozenset({"wireless", "ergonomic"}), axis_label="keywords")
    assert result.state is AxisState.UNKNOWN
    assert result.score == 0


def test_overlap_known_but_disjoint_is_known_zero_not_unknown() -> None:
    """A genuinely-0 axis and an UNKNOWN axis are different facts (§6.14.2) — this must
    render as KNOWN(0), not UNKNOWN(0)."""
    result = score_overlap(frozenset({"a", "b"}), frozenset({"c", "d"}), axis_label="features")
    assert result.state is AxisState.KNOWN
    assert result.score == 0


def test_product_similarity_none_tier_is_unknown() -> None:
    assert score_product_similarity(None).state is AxisState.UNKNOWN


def test_use_case_similarity_none_tier_is_unknown() -> None:
    assert score_use_case_similarity(None).state is AxisState.UNKNOWN


def test_unknown_axes_never_contribute_to_a_higher_band() -> None:
    all_unknown = RelevanceScoreInputs(
        category=_UNKNOWN,
        product=_UNKNOWN,
        price_proximity=_UNKNOWN,
        features=_UNKNOWN,
        keywords=_UNKNOWN,
        use_case=_UNKNOWN,
        fulfillment=_UNKNOWN,
        review_tier=_UNKNOWN,
    )
    breakdown = score_relevance(all_unknown, is_provisional=True)
    assert breakdown.total_score == 0
    assert breakdown.band is RelevanceBand.LOW


# --------------------------------------------------------------------------------------
# HIGH is unreachable when category or product scored 0, even if every other axis is 2
# --------------------------------------------------------------------------------------


def test_high_unreachable_when_category_scored_zero() -> None:
    inputs = _inputs(category=_KNOWN0)
    breakdown = score_relevance(inputs, is_provisional=True)
    assert breakdown.total_score == 14  # 7 axes at 2 + category at 0
    assert breakdown.band is not RelevanceBand.HIGH
    assert breakdown.band is RelevanceBand.MEDIUM


def test_high_unreachable_when_product_scored_zero() -> None:
    inputs = _inputs(product=_KNOWN0)
    breakdown = score_relevance(inputs, is_provisional=True)
    assert breakdown.total_score == 14
    assert breakdown.band is not RelevanceBand.HIGH
    assert breakdown.band is RelevanceBand.MEDIUM


def test_high_reachable_when_category_and_product_both_known_and_total_high_enough() -> None:
    breakdown = score_relevance(_inputs(), is_provisional=True)
    assert breakdown.total_score == MAX_TOTAL_SCORE
    assert breakdown.band is RelevanceBand.HIGH


# --------------------------------------------------------------------------------------
# Band cutoffs (§6.14.3 step 2)
# --------------------------------------------------------------------------------------


def test_low_band_at_or_below_five() -> None:
    total, band = compute_band(
        {
            "category": _KNOWN1,
            "product": _KNOWN1,
            "price_proximity": _KNOWN1,
            "features": _KNOWN0,
            "keywords": _KNOWN0,
            "use_case": _KNOWN0,
            "fulfillment": _UNKNOWN,
            "review_tier": _UNKNOWN,
        }
    )
    assert total == 3
    assert band is RelevanceBand.LOW


def test_medium_band_at_six_to_ten() -> None:
    total, band = compute_band(
        {
            "category": _KNOWN2,
            "product": _KNOWN1,
            "price_proximity": _KNOWN1,
            "features": _KNOWN1,
            "keywords": _KNOWN1,
            "use_case": _KNOWN0,
            "fulfillment": _UNKNOWN,
            "review_tier": _UNKNOWN,
        }
    )
    assert total == 6
    assert band is RelevanceBand.MEDIUM


# --------------------------------------------------------------------------------------
# Deterministic axis thresholds (§6.14.3 step 1)
# --------------------------------------------------------------------------------------


def test_price_proximity_within_15_pct_scores_2() -> None:
    result = score_price_proximity(100_000, 114_000)  # 14% higher
    assert result.score == 2


def test_price_proximity_exactly_at_15_pct_boundary_scores_2() -> None:
    result = score_price_proximity(100_000, 115_000)  # exactly 15%
    assert result.score == 2


def test_price_proximity_within_40_pct_scores_1() -> None:
    result = score_price_proximity(100_000, 135_000)  # 35% higher
    assert result.score == 1


def test_price_proximity_beyond_40_pct_scores_0() -> None:
    result = score_price_proximity(100_000, 200_000)  # 100% higher
    assert result.score == 0
    assert result.state is AxisState.KNOWN


def test_overlap_at_60_pct_scores_2() -> None:
    seller = frozenset({"a", "b", "c", "d", "e"})
    candidate = frozenset({"a", "b", "c"})  # intersection 3 / union 5 = 60%
    result = score_overlap(seller, candidate, axis_label="features")
    assert result.score == 2


def test_overlap_below_25_pct_scores_0() -> None:
    seller = frozenset({"a", "b", "c"})
    candidate = frozenset({"a", "d", "e", "f"})  # intersection 1 / union 6 = 16.7%
    result = score_overlap(seller, candidate, axis_label="keywords")
    assert result.score == 0


def test_overlap_between_25_and_59_pct_scores_1() -> None:
    seller = frozenset({"a", "b", "c"})
    candidate = frozenset({"a", "b", "d"})  # intersection 2 / union 4 = 50%
    result = score_overlap(seller, candidate, axis_label="keywords")
    assert result.score == 1


def test_category_exact_match_scores_2() -> None:
    assert score_category("Electronics > Mouse", "Electronics > Mouse").score == 2


def test_category_parent_match_scores_1() -> None:
    assert score_category("Electronics > Mouse", "Electronics > Keyboard").score == 1


def test_category_different_root_scores_0() -> None:
    result = score_category("Electronics > Mouse", "Apparel > Shoes")
    assert result.score == 0
    assert result.state is AxisState.KNOWN


def test_product_similarity_tiers() -> None:
    assert score_product_similarity(ProductSimilarityTier.SAME_LINE).score == 2
    assert score_product_similarity(ProductSimilarityTier.SAME_TYPE_DIFFERENT_LINE).score == 1
    assert score_product_similarity(ProductSimilarityTier.DIFFERENT).score == 0


def test_use_case_similarity_tiers() -> None:
    assert score_use_case_similarity(UseCaseSimilarityTier.SAME).score == 2
    assert score_use_case_similarity(UseCaseSimilarityTier.ADJACENT).score == 1
    assert score_use_case_similarity(UseCaseSimilarityTier.DIFFERENT).score == 0


def test_fulfillment_match_scores_2() -> None:
    assert score_fulfillment("SELLER_FULFILLED", "SELLER_FULFILLED").score == 2


def test_fulfillment_mismatch_scores_0_known() -> None:
    result = score_fulfillment("SELLER_FULFILLED", "MARKETPLACE_FULFILLED")
    assert result.score == 0
    assert result.state is AxisState.KNOWN


def test_review_tier_same_bucket_scores_2() -> None:
    assert score_review_tier(500, 600).score == 2


def test_review_tier_adjacent_bucket_scores_1() -> None:
    assert score_review_tier(50, 500).score == 1


def test_review_tier_distant_bucket_scores_0() -> None:
    result = score_review_tier(10, 50_000)
    assert result.score == 0
    assert result.state is AxisState.KNOWN


# --------------------------------------------------------------------------------------
# Structural guarantee: a breakdown can never omit an axis from its render
# --------------------------------------------------------------------------------------


def test_breakdown_requires_all_eight_axes() -> None:
    incomplete = {axis: _KNOWN2 for axis in AXIS_ORDER[:-1]}
    with pytest.raises(ValueError, match="missing"):
        compute_band(incomplete)


def test_render_always_includes_all_eight_axis_labels() -> None:
    breakdown = score_relevance(_inputs(), is_provisional=True)
    for axis in AXIS_ORDER:
        assert breakdown.axis_results[axis] is not None
    line = breakdown.breakdown_line
    for label in ("category", "product", "price proximity", "features", "keywords", "use-case", "fulfillment", "review-tier"):
        assert label in line
