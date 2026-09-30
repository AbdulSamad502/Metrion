"""review_insight/aggregate.py — Fraction-based aggregation, source-type separation."""

from __future__ import annotations

from fractions import Fraction

import pytest

from product_intelligence.review_insight.aggregate import aggregate_text_insight
from product_intelligence.review_insight.text_extraction import TextExtractionFailed, TextExtractionResult, TextObservation


def _result(source_type: str, observations: tuple[TextObservation, ...]) -> TextExtractionResult:
    return TextExtractionResult(insight_source_type=source_type, observations=observations)


def test_no_results_yields_unavailable_draft() -> None:
    draft = aggregate_text_insight("YOUTUBE_COMMENTARY", [])
    assert draft.insight_state == "UNAVAILABLE"
    assert draft.confidence == "UNAVAILABLE"
    assert draft.reviews_considered == 0


def test_all_failed_results_yield_unavailable_draft() -> None:
    results = [TextExtractionFailed(insight_source_type="WEB_EDITORIAL", reason="ollama down")]
    draft = aggregate_text_insight("WEB_EDITORIAL", results)
    assert draft.insight_state == "UNAVAILABLE"


def test_sentiment_split_is_an_exact_fraction_string() -> None:
    observations = (
        TextObservation(sentiment="POSITIVE", themes=("battery life",)),
        TextObservation(sentiment="POSITIVE", themes=("value for money",)),
        TextObservation(sentiment="NEGATIVE", themes=("build quality",)),
    )
    draft = aggregate_text_insight("YOUTUBE_COMMENTARY", [_result("YOUTUBE_COMMENTARY", observations)])

    assert draft.sentiment_split["POSITIVE"] == str(Fraction(2, 3))
    assert draft.sentiment_split["NEGATIVE"] == str(Fraction(1, 3))
    assert draft.insight_state == "COMPLETE"
    assert draft.reviews_considered == 3


def test_positive_and_complaint_themes_are_separated_by_sentiment() -> None:
    observations = (
        TextObservation(sentiment="POSITIVE", themes=("battery life",)),
        TextObservation(sentiment="NEGATIVE", themes=("shipping",)),
    )
    draft = aggregate_text_insight("WEB_EDITORIAL", [_result("WEB_EDITORIAL", observations)])

    assert draft.positive_themes == {"battery life": 1}
    assert draft.complaint_themes == {"shipping": 1}


def test_partial_failures_produce_degraded_state_not_unavailable() -> None:
    results = [
        _result("YOUTUBE_COMMENTARY", (TextObservation(sentiment="POSITIVE", themes=()),)),
        TextExtractionFailed(insight_source_type="YOUTUBE_COMMENTARY", reason="batch 2 failed"),
    ]
    draft = aggregate_text_insight("YOUTUBE_COMMENTARY", results)
    assert draft.insight_state == "DEGRADED"
    assert draft.degraded_reason is not None


def test_mixed_source_types_in_one_call_raises_never_silently_aggregated() -> None:
    results = [_result("WEB_EDITORIAL", (TextObservation(sentiment="POSITIVE", themes=()),))]
    with pytest.raises(ValueError, match="never be aggregated together"):
        aggregate_text_insight("YOUTUBE_COMMENTARY", results)
