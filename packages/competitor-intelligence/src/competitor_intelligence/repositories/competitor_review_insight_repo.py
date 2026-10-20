"""competitor_review_insight — §5 / §6.5. `snapshot_id` is nullable (`on delete set null`)
— review evidence is grouped by its own `research_session_id`, not necessarily tied to a
price/listing snapshot from the same session (a seller may submit a reviews-tab screenshot
on its own). Never stores raw review text (AC5/AC5b/AC5c) — only the aggregated structure
`review_insight/aggregate.py` produces.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.review_insight.aggregate import ReviewInsightDraft


def insert_insight(
    tenant_id: UUID,
    *,
    snapshot_id: UUID | None,
    source_url: str,
    fetched_at: datetime,
    draft: ReviewInsightDraft,
) -> UUID:
    now = datetime.now(fetched_at.tzinfo)
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO competitor_review_insight (
                  tenant_id, snapshot_id, sentiment_split, rating_distribution, complaint_themes,
                  positive_themes, summarised_patterns, reviews_considered, confidence,
                  derivation_method, insight_state, degraded_reason, source_url, fetched_at, derived_at
                ) VALUES (
                  :tenant_id, :snapshot_id, CAST(:sentiment_split AS jsonb), CAST(:rating_distribution AS jsonb),
                  CAST(:complaint_themes AS jsonb), CAST(:positive_themes AS jsonb),
                  CAST(:summarised_patterns AS jsonb), :reviews_considered, :confidence,
                  :derivation_method, :insight_state, :degraded_reason, :source_url, :fetched_at, :derived_at
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "snapshot_id": str(snapshot_id) if snapshot_id else None,
                "sentiment_split": json.dumps(draft.sentiment_split),
                "rating_distribution": json.dumps(draft.rating_distribution) if draft.rating_distribution else None,
                "complaint_themes": json.dumps(draft.complaint_themes),
                "positive_themes": json.dumps(draft.positive_themes),
                "summarised_patterns": json.dumps(_summarise(draft)),
                "reviews_considered": draft.reviews_considered,
                "confidence": draft.confidence.value,
                "derivation_method": draft.derivation_method.value,
                "insight_state": draft.insight_state.value,
                "degraded_reason": draft.degraded_reason,
                "source_url": source_url,
                "fetched_at": fetched_at,
                "derived_at": now,
            },
        ).one()
        return cast(UUID, row[0])


def _summarise(draft: ReviewInsightDraft) -> list[str]:
    """A short list of plain observations, built only from the already-aggregated counts
    above — never a re-derivation, and never review text (MN8: code computes from labels,
    it does not go back to source text for this)."""
    patterns = []
    for theme, count in draft.complaint_themes.items():
        patterns.append(f"{count} review(s) raised '{theme}' as a concern")
    for theme, count in draft.positive_themes.items():
        patterns.append(f"{count} review(s) praised '{theme}'")
    return patterns


def get_by_snapshot(tenant_id: UUID, snapshot_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT id, sentiment_split, rating_distribution, complaint_themes, positive_themes, "
                "summarised_patterns, reviews_considered, confidence, derivation_method, insight_state, "
                "degraded_reason, source_url, fetched_at, derived_at "
                "FROM competitor_review_insight WHERE tenant_id = :tenant_id AND snapshot_id = :snapshot_id"
            ),
            {"tenant_id": str(tenant_id), "snapshot_id": str(snapshot_id)},
        ).mappings().first()
        return dict(row) if row else None


def latest_for_url(tenant_id: UUID, source_url: str) -> dict[str, Any] | None:
    """The newest review insight for a competitor listing, whether or not it was tied to a snapshot (a reviews
    screenshot sent before any listing screenshot has no snapshot to hang on)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT id, sentiment_split, rating_distribution, complaint_themes, positive_themes, summarised_patterns, "
                "reviews_considered, confidence, derivation_method, insight_state, degraded_reason, source_url, fetched_at, derived_at "
                "FROM competitor_review_insight WHERE tenant_id = :tenant_id AND source_url = :url ORDER BY derived_at DESC LIMIT 1"
            ),
            {"tenant_id": str(tenant_id), "url": source_url},
        ).mappings().first()
        return dict(row) if row else None
