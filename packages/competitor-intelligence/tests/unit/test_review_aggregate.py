"""aggregate_review_evidence() — deterministic code aggregating per-review classifications
(MN8). No model call happens here; every case below only ever supplies already-classified
ReviewObservation/ReviewExtractionResult fixtures."""

from __future__ import annotations

from uuid import uuid4

from competitor_intelligence.review_insight.aggregate import aggregate_review_evidence
from competitor_intelligence.review_insight.extraction import (
    ReviewExtractionFailed,
    ReviewExtractionResult,
    ReviewObservation,
)
from competitor_intelligence.types import Confidence, DerivationMethod, InsightState


def test_no_evidence_at_all_is_unavailable() -> None:
    draft = aggregate_review_evidence([])
    assert draft.insight_state == InsightState.UNAVAILABLE
    assert draft.reviews_considered == 0


def test_all_screenshots_failed_with_no_fallback_is_unavailable() -> None:
    per_evidence = [(uuid4(), ReviewExtractionFailed(reason="illegible"))]
    draft = aggregate_review_evidence(per_evidence)
    assert draft.insight_state == InsightState.UNAVAILABLE
    assert draft.confidence == Confidence.UNAVAILABLE


def test_all_screenshots_failed_with_fallback_is_degraded_not_unavailable() -> None:
    """E16: local processing unavailable degrades to structured metadata, never a hard
    UNAVAILABLE when something (the linked snapshot's own rating/rating_count) is known."""
    per_evidence = [(uuid4(), ReviewExtractionFailed(reason="model unreachable"))]
    draft = aggregate_review_evidence(per_evidence, fallback_rating="4.2", fallback_rating_count=150)
    assert draft.insight_state == InsightState.DEGRADED
    assert draft.derivation_method == DerivationMethod.STRUCTURED_ONLY


def test_extraction_succeeded_but_zero_reviews_found_is_unavailable_e13() -> None:
    per_evidence = [(uuid4(), ReviewExtractionResult(reviews=()))]
    draft = aggregate_review_evidence(per_evidence)
    assert draft.insight_state == InsightState.UNAVAILABLE
    assert draft.reviews_considered == 0
    assert draft.degraded_reason is not None


def test_sentiment_split_computed_as_exact_fractions() -> None:
    reviews = (
        ReviewObservation(sentiment="POSITIVE", themes=("battery",)),
        ReviewObservation(sentiment="POSITIVE", themes=()),
        ReviewObservation(sentiment="NEGATIVE", themes=("delivery",)),
        ReviewObservation(sentiment="NEUTRAL", themes=()),
    )
    per_evidence = [(uuid4(), ReviewExtractionResult(reviews=reviews))]
    draft = aggregate_review_evidence(per_evidence)

    assert draft.reviews_considered == 4
    assert draft.sentiment_split["POSITIVE"] == "1/2"
    assert draft.sentiment_split["NEGATIVE"] == "1/4"
    assert draft.sentiment_split["NEUTRAL"] == "1/4"
    assert draft.insight_state == InsightState.COMPLETE


def test_positive_and_complaint_themes_separated_by_sentiment() -> None:
    reviews = (
        ReviewObservation(sentiment="POSITIVE", themes=("battery life",)),
        ReviewObservation(sentiment="NEGATIVE", themes=("battery life",)),
    )
    per_evidence = [(uuid4(), ReviewExtractionResult(reviews=reviews))]
    draft = aggregate_review_evidence(per_evidence)

    assert draft.positive_themes.get("battery life") == 1
    assert draft.complaint_themes.get("battery life") == 1


def test_reviews_pooled_across_multiple_screenshots() -> None:
    per_evidence = [
        (uuid4(), ReviewExtractionResult(reviews=(ReviewObservation("POSITIVE", ()),))),
        (uuid4(), ReviewExtractionResult(reviews=(ReviewObservation("NEGATIVE", ()), ReviewObservation("NEGATIVE", ())))),
    ]
    draft = aggregate_review_evidence(per_evidence)
    assert draft.reviews_considered == 3


def test_extraction_failed_screenshot_contributes_no_reviews() -> None:
    per_evidence = [
        (uuid4(), ReviewExtractionResult(reviews=(ReviewObservation("POSITIVE", ()),))),
        (uuid4(), ReviewExtractionFailed(reason="illegible")),
    ]
    draft = aggregate_review_evidence(per_evidence)
    assert draft.reviews_considered == 1


def test_agreeing_rating_distributions_are_used() -> None:
    per_evidence = [
        (uuid4(), ReviewExtractionResult(reviews=(ReviewObservation("POSITIVE", ()),), rating_distribution={"5": 10})),
        (uuid4(), ReviewExtractionResult(reviews=(ReviewObservation("POSITIVE", ()),), rating_distribution={"5": 10})),
    ]
    draft = aggregate_review_evidence(per_evidence)
    assert draft.rating_distribution == {"5": 10}
    assert draft.insight_state == InsightState.COMPLETE


def test_conflicting_rating_distributions_are_unavailable_not_picked() -> None:
    """§5.3 rule 3 applied to review evidence: two screenshots disagreeing on the same
    aggregate bar is never silently resolved by picking one."""
    per_evidence = [
        (uuid4(), ReviewExtractionResult(reviews=(ReviewObservation("POSITIVE", ()),), rating_distribution={"5": 10})),
        (uuid4(), ReviewExtractionResult(reviews=(ReviewObservation("POSITIVE", ()),), rating_distribution={"5": 12})),
    ]
    draft = aggregate_review_evidence(per_evidence)
    assert draft.rating_distribution is None
    assert draft.insight_state == InsightState.DEGRADED
    assert draft.degraded_reason is not None
