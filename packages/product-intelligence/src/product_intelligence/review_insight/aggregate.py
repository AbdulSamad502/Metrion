"""Deterministic `Fraction`-based aggregation over per-text classifications — PI build plan
§2/§0b, mirroring `competitor_intelligence.review_insight.aggregate` exactly. The model
(`text_extraction.py`) only ever labels individual texts; this module turns those labels into
`sentiment_split` proportions and theme weights — plain counting, never `float`.

**`YOUTUBE_COMMENTARY` and `WEB_EDITORIAL` are aggregated separately, always** — this module
has no function that accepts a mixed list of both; a caller wanting both figures calls
`aggregate_text_insight` twice, once per source type, exactly mirroring how
`product_review_insight` itself is one row per `(candidate_id, insight_source_type)`, never
one merged "review" row.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from product_intelligence.review_insight.text_extraction import (
    TextExtractionFailed,
    TextExtractionResult,
    TextObservation,
)

_TOP_N_THEMES = 8


@dataclass(frozen=True, slots=True)
class ReviewInsightDraft:
    insight_source_type: str
    sentiment_split: dict[str, str]  # e.g. {"POSITIVE": "3/5", ...}
    positive_themes: dict[str, int]
    complaint_themes: dict[str, int]
    reviews_considered: int
    confidence: str  # DERIVED | UNAVAILABLE
    derivation_method: str  # LOCAL_MODEL | STRUCTURED_ONLY
    insight_state: str  # COMPLETE | DEGRADED | UNAVAILABLE
    degraded_reason: str | None


def aggregate_text_insight(
    insight_source_type: str,
    results: Sequence[TextExtractionResult | TextExtractionFailed],
) -> ReviewInsightDraft:
    """`results` is every extraction call made for this one `(candidate, insight_source_type)`
    pair — typically one call per batch of texts. All results here MUST share the same
    `insight_source_type`; a caller that passes a mixed list has already violated §0b upstream
    and this function raises rather than silently aggregating across the boundary."""
    for result in results:
        if result.insight_source_type != insight_source_type:
            raise ValueError(
                f"aggregate_text_insight({insight_source_type!r}) received a result tagged "
                f"{result.insight_source_type!r} — YOUTUBE_COMMENTARY and WEB_EDITORIAL must "
                "never be aggregated together (§0b)"
            )

    succeeded = [r for r in results if isinstance(r, TextExtractionResult)]
    all_failed = bool(results) and not succeeded

    if not results or all_failed:
        return ReviewInsightDraft(
            insight_source_type=insight_source_type,
            sentiment_split={},
            positive_themes={},
            complaint_themes={},
            reviews_considered=0,
            confidence="UNAVAILABLE",
            derivation_method="LOCAL_MODEL",
            insight_state="UNAVAILABLE",
            degraded_reason="no commentary/editorial text could be classified for this candidate",
        )

    all_observations: list[TextObservation] = [obs for r in succeeded for obs in r.observations]
    considered = len(all_observations)

    if considered == 0:
        return ReviewInsightDraft(
            insight_source_type=insight_source_type,
            sentiment_split={},
            positive_themes={},
            complaint_themes={},
            reviews_considered=0,
            confidence="UNAVAILABLE",
            derivation_method="LOCAL_MODEL",
            insight_state="UNAVAILABLE",
            degraded_reason="no individual texts were classifiable in the submitted batch(es)",
        )

    sentiment_counts = Counter(o.sentiment for o in all_observations)
    sentiment_split = {
        sentiment: str(Fraction(count, considered)) for sentiment, count in sentiment_counts.items()
    }

    positive_themes = Counter(
        theme for o in all_observations if o.sentiment == "POSITIVE" for theme in o.themes
    ).most_common(_TOP_N_THEMES)
    complaint_themes = Counter(
        theme for o in all_observations if o.sentiment == "NEGATIVE" for theme in o.themes
    ).most_common(_TOP_N_THEMES)

    failed_count = len(results) - len(succeeded)
    insight_state = "DEGRADED" if failed_count else "COMPLETE"
    degraded_reason = f"{failed_count} extraction batch(es) failed and were excluded" if failed_count else None

    return ReviewInsightDraft(
        insight_source_type=insight_source_type,
        sentiment_split=sentiment_split,
        positive_themes=dict(positive_themes),
        complaint_themes=dict(complaint_themes),
        reviews_considered=considered,
        confidence="DERIVED",
        derivation_method="LOCAL_MODEL",
        insight_state=insight_state,
        degraded_reason=degraded_reason,
    )
