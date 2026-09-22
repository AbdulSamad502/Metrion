"""Deterministic aggregation over per-review classifications (§6.5, MN8). The model
(`ollama_extractor.py`) only ever labels individual reviews; this module turns those labels
into `sentiment_split` proportions, theme weights, and a merged rating distribution — plain
counting, `Fraction`-based (never `float`, matching this codebase's general discipline for
any proportion derived from an observed count, even outside the money hard rule).

Multi-screenshot handling mirrors `evidence/merge.py`'s §5.3 rules, adapted to review
evidence's shape: per-review observations from different screenshots are POOLED (they are
distinct reviews, not competing readings of the same field), but `rating_distribution` — the
marketplace's own single aggregate bar — behaves like a §5.3 rule-3 field: if two screenshots
report it and disagree, it is surfaced as unavailable rather than one being silently picked.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Sequence
from uuid import UUID

from competitor_intelligence.review_insight.extraction import ReviewExtractionFailed, ReviewExtractionResult
from competitor_intelligence.types import Confidence, DerivationMethod, InsightState

_TOP_N_THEMES = 8


@dataclass(frozen=True, slots=True)
class ReviewInsightDraft:
    sentiment_split: dict[str, str]  # e.g. {"POSITIVE": "3/5", "NEGATIVE": "1/5", "NEUTRAL": "1/5"}
    positive_themes: dict[str, int]
    complaint_themes: dict[str, int]
    rating_distribution: dict[str, int] | None
    reviews_considered: int
    confidence: Confidence
    derivation_method: DerivationMethod
    insight_state: InsightState
    degraded_reason: str | None


def _merge_rating_distributions(readings: Sequence[Mapping[str, int]]) -> tuple[dict[str, int] | None, str | None]:
    if not readings:
        return None, None
    first = dict(readings[0])
    for other in readings[1:]:
        if dict(other) != first:
            return None, "screenshots disagreed on the visible rating-distribution bar"
    return first, None


def aggregate_review_evidence(
    per_evidence: Sequence[tuple[UUID, ReviewExtractionResult | ReviewExtractionFailed]],
    *,
    fallback_rating: str | None = None,
    fallback_rating_count: int | None = None,
) -> ReviewInsightDraft:
    """`fallback_rating`/`fallback_rating_count` are the linked snapshot's own already-known
    `rating`/`rating_count` fields (E16: "insight_state = DEGRADED... built from structured
    metadata already captured") — used only when every screenshot failed extraction outright,
    never when extraction ran and simply found zero reviews (that is E13's UNAVAILABLE case,
    a different outcome from "local processing was unavailable")."""
    succeeded = [r for _, r in per_evidence if isinstance(r, ReviewExtractionResult)]
    all_failed = bool(per_evidence) and not succeeded

    if all_failed:
        if fallback_rating is not None or fallback_rating_count is not None:
            return ReviewInsightDraft(
                sentiment_split={},
                positive_themes={},
                complaint_themes={},
                rating_distribution=None,
                reviews_considered=0,
                confidence=Confidence.DERIVED,
                derivation_method=DerivationMethod.STRUCTURED_ONLY,
                insight_state=InsightState.DEGRADED,
                degraded_reason="local review-screenshot processing was unavailable; falling back to the "
                "snapshot's own rating/rating_count only (E16)",
            )
        return ReviewInsightDraft(
            sentiment_split={},
            positive_themes={},
            complaint_themes={},
            rating_distribution=None,
            reviews_considered=0,
            confidence=Confidence.UNAVAILABLE,
            derivation_method=DerivationMethod.STRUCTURED_ONLY,
            insight_state=InsightState.UNAVAILABLE,
            degraded_reason="no review evidence could be processed and no structured fallback was available",
        )

    all_reviews = [review for result in succeeded for review in result.reviews]
    reviews_considered = len(all_reviews)

    if reviews_considered == 0:
        return ReviewInsightDraft(
            sentiment_split={},
            positive_themes={},
            complaint_themes={},
            rating_distribution=None,
            reviews_considered=0,
            confidence=Confidence.UNAVAILABLE,
            derivation_method=DerivationMethod.LOCAL_MODEL,
            insight_state=InsightState.UNAVAILABLE,
            degraded_reason="no individual reviews were legible in the submitted screenshot(s) (E13)",
        )

    sentiment_counts = Counter(r.sentiment for r in all_reviews)
    sentiment_split = {
        sentiment: str(Fraction(count, reviews_considered)) for sentiment, count in sentiment_counts.items()
    }

    positive_themes = Counter(
        theme for r in all_reviews if r.sentiment == "POSITIVE" for theme in r.themes
    ).most_common(_TOP_N_THEMES)
    complaint_themes = Counter(
        theme for r in all_reviews if r.sentiment == "NEGATIVE" for theme in r.themes
    ).most_common(_TOP_N_THEMES)

    distribution_readings = [r.rating_distribution for r in succeeded if r.rating_distribution]
    rating_distribution, conflict_reason = _merge_rating_distributions(distribution_readings)

    insight_state = InsightState.DEGRADED if conflict_reason else InsightState.COMPLETE

    return ReviewInsightDraft(
        sentiment_split=sentiment_split,
        positive_themes=dict(positive_themes),
        complaint_themes=dict(complaint_themes),
        rating_distribution=rating_distribution,
        reviews_considered=reviews_considered,
        confidence=Confidence.DERIVED,
        derivation_method=DerivationMethod.LOCAL_MODEL,
        insight_state=insight_state,
        degraded_reason=conflict_reason,
    )
