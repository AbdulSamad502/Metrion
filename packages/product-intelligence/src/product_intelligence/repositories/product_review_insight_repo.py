"""product_review_insight — `product-intelligence-agent.md` §6.4, PI build plan §0b.
`insight_source_type` (`YOUTUBE_COMMENTARY` | `WEB_EDITORIAL`) is a required column so no
downstream consumer can accidentally present commentary as a marketplace review — see the
migration's CHECK constraint. Raw comment/article text is never a parameter here; only
`review_insight/submit.py` (Checkpoint 2) calls this module, and only with already-derived
fields.

**Checkpoint 2 — real implementation.** Every function takes `tenant_id` first and receives
its connection only via `tenant_scope()` (auth.md §7.3), matching every other repository in
this package.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope


def insert_insight(
    tenant_id: UUID,
    *,
    candidate_id: UUID,
    insight_source_type: str,
    sentiment_split: dict[str, Any] | None,
    rating_distribution: dict[str, Any] | None,
    complaint_themes: dict[str, Any] | None,
    positive_themes: dict[str, Any] | None,
    summarised_patterns: dict[str, Any] | None,
    reviews_considered: int | None,
    confidence: str,
    derivation_method: str,
    insight_state: str,
    degraded_reason: str | None,
    source_url: str,
    fetched_at: datetime,
    derived_at: datetime,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO product_review_insight
                    (tenant_id, candidate_id, insight_source_type, sentiment_split,
                     rating_distribution, complaint_themes, positive_themes, summarised_patterns,
                     reviews_considered, confidence, derivation_method, insight_state,
                     degraded_reason, source_url, fetched_at, derived_at)
                VALUES
                    (:tenant_id, :candidate_id, :insight_source_type, CAST(:sentiment_split AS jsonb),
                     CAST(:rating_distribution AS jsonb), CAST(:complaint_themes AS jsonb),
                     CAST(:positive_themes AS jsonb), CAST(:summarised_patterns AS jsonb),
                     :reviews_considered, :confidence, :derivation_method, :insight_state,
                     :degraded_reason, :source_url, :fetched_at, :derived_at)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "candidate_id": str(candidate_id),
                "insight_source_type": insight_source_type,
                "sentiment_split": json.dumps(sentiment_split) if sentiment_split is not None else None,
                "rating_distribution": (
                    json.dumps(rating_distribution) if rating_distribution is not None else None
                ),
                "complaint_themes": json.dumps(complaint_themes) if complaint_themes is not None else None,
                "positive_themes": json.dumps(positive_themes) if positive_themes is not None else None,
                "summarised_patterns": (
                    json.dumps(summarised_patterns) if summarised_patterns is not None else None
                ),
                "reviews_considered": reviews_considered,
                "confidence": confidence,
                "derivation_method": derivation_method,
                "insight_state": insight_state,
                "degraded_reason": degraded_reason,
                "source_url": source_url,
                "fetched_at": fetched_at,
                "derived_at": derived_at,
            },
        ).one()
        return row[0]


def list_insights_for_candidate(tenant_id: UUID, candidate_id: UUID) -> list[dict[str, Any]]:
    """Returns both `YOUTUBE_COMMENTARY` and `WEB_EDITORIAL` rows, never merged into one
    undifferentiated "review" figure by this repository — that separation is the caller's
    (`review_insight/aggregate.py`, Checkpoint 2) to preserve."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM product_review_insight "
                "WHERE tenant_id = :tenant_id AND candidate_id = :candidate_id "
                "ORDER BY derived_at DESC"
            ),
            {"tenant_id": str(tenant_id), "candidate_id": str(candidate_id)},
        ).mappings().all()
        return [dict(r) for r in rows]
