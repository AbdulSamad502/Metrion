"""Orchestrates extraction + aggregate + persist for one candidate's commentary — PI build
plan §2/§6.4/C7/C9. **Raw comment/article text is held only in local variables inside this
call chain, never passed to a repo insert, never logged, never sent to a hosted provider** —
grep-verifiable: no `product_review_insight_repo.insert_insight` call anywhere in this module
passes anything but already-classified/aggregated fields, and no `print`/`logging` call in
this module ever touches `youtube_comments`/`web_snippets`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from product_intelligence.repositories import product_review_insight_repo
from product_intelligence.review_insight.aggregate import ReviewInsightDraft, aggregate_text_insight
from product_intelligence.review_insight.text_extraction import (
    TextExtractionFailed,
    TextExtractionResult,
    TextInsightExtractor,
)

_BATCH_SIZE = 20  # texts per Ollama call — keeps prompts bounded regardless of how many
# comments/snippets a candidate accumulated.


def _batched(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


@dataclass(frozen=True, slots=True)
class SubmitInsightResult:
    insight_id: UUID | None
    insight_state: str
    draft: ReviewInsightDraft


def _extract_and_aggregate(
    texts: Sequence[str], *, insight_source_type: str, extractor: TextInsightExtractor
) -> ReviewInsightDraft:
    if not texts:
        return aggregate_text_insight(insight_source_type, [])

    results: list[TextExtractionResult | TextExtractionFailed] = []
    for batch in _batched(texts, _BATCH_SIZE):
        results.append(extractor.extract(batch, insight_source_type=insight_source_type))
    return aggregate_text_insight(insight_source_type, results)


def submit_candidate_review_insight(
    tenant_id: UUID,
    *,
    candidate_id: UUID,
    youtube_comments: Sequence[str],
    youtube_source_url: str | None,
    web_snippets: Sequence[str],
    web_source_url: str | None,
    extractor: TextInsightExtractor,
    now: datetime | None = None,
) -> list[SubmitInsightResult]:
    """Runs both source types independently (§0b — never merged) and persists whichever of
    the two actually had text to classify. Returns one `SubmitInsightResult` per source type
    that had at least one text (an empty source type produces no row at all — not a fabricated
    UNAVAILABLE row for commentary that was never attempted, same distinction
    `product_review_insight_repo`'s own docstring draws for a genuine zero vs. an
    unavailable-derivation)."""
    now = now or datetime.now(timezone.utc)
    results: list[SubmitInsightResult] = []

    if youtube_comments and youtube_source_url:
        draft = _extract_and_aggregate(
            youtube_comments, insight_source_type="YOUTUBE_COMMENTARY", extractor=extractor
        )
        insight_id = product_review_insight_repo.insert_insight(
            tenant_id,
            candidate_id=candidate_id,
            insight_source_type="YOUTUBE_COMMENTARY",
            sentiment_split=draft.sentiment_split or None,
            rating_distribution=None,
            complaint_themes=draft.complaint_themes or None,
            positive_themes=draft.positive_themes or None,
            summarised_patterns=None,
            reviews_considered=draft.reviews_considered,
            confidence=draft.confidence,
            derivation_method=draft.derivation_method,
            insight_state=draft.insight_state,
            degraded_reason=draft.degraded_reason,
            source_url=youtube_source_url,
            fetched_at=now,
            derived_at=now,
        )
        results.append(SubmitInsightResult(insight_id=insight_id, insight_state=draft.insight_state, draft=draft))

    if web_snippets and web_source_url:
        draft = _extract_and_aggregate(web_snippets, insight_source_type="WEB_EDITORIAL", extractor=extractor)
        insight_id = product_review_insight_repo.insert_insight(
            tenant_id,
            candidate_id=candidate_id,
            insight_source_type="WEB_EDITORIAL",
            sentiment_split=draft.sentiment_split or None,
            rating_distribution=None,
            complaint_themes=draft.complaint_themes or None,
            positive_themes=draft.positive_themes or None,
            summarised_patterns=None,
            reviews_considered=draft.reviews_considered,
            confidence=draft.confidence,
            derivation_method=draft.derivation_method,
            insight_state=draft.insight_state,
            degraded_reason=draft.degraded_reason,
            source_url=web_source_url,
            fetched_at=now,
            derived_at=now,
        )
        results.append(SubmitInsightResult(insight_id=insight_id, insight_state=draft.insight_state, draft=draft))

    return results
