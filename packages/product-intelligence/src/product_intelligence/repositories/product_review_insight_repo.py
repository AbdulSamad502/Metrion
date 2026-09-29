"""product_review_insight — `product-intelligence-agent.md` §6.4, PI build plan §0b.
`insight_source_type` (`YOUTUBE_COMMENTARY` | `WEB_EDITORIAL`) is a required column so no
downstream consumer can accidentally present commentary as a marketplace review — see the
migration's CHECK constraint. Raw comment/article text is never a parameter here; only
`review_insight/submit.py` (Checkpoint 2) calls this module, and only with already-derived
fields.

**Checkpoint 1 scaffolding only** — every function below is a `NotImplementedError` stub.
Every function takes `tenant_id` first, per CI's convention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID


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
    raise NotImplementedError("product_review_insight_repo.insert_insight: Checkpoint 2")


def list_insights_for_candidate(tenant_id: UUID, candidate_id: UUID) -> list[dict[str, Any]]:
    """Returns both `YOUTUBE_COMMENTARY` and `WEB_EDITORIAL` rows, never merged into one
    undifferentiated "review" figure by this repository — that separation is the caller's
    (`review_insight/aggregate.py`, Checkpoint 2) to preserve."""
    raise NotImplementedError("product_review_insight_repo.list_insights_for_candidate: Checkpoint 2")
