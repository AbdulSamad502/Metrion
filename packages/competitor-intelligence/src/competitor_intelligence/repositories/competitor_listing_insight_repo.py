"""competitor_listing_insight — §5 / §6.6. One row per snapshot that had listing-copy
evidence to derive from; `snapshot_id` is nullable on the table (`on delete set null`) so a
purged snapshot's derived insight can still outlive it, per §6.8's "derived insights
retained" rule (E18) — this repo never deletes a row when its snapshot is purged.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.listing_insight.derive import ListingInsightDraft
from competitor_intelligence.repositories.tenant_context import tenant_scope


def insert_insight(
    tenant_id: UUID,
    *,
    snapshot_id: UUID,
    source_url: str,
    fetched_at: datetime,
    draft: ListingInsightDraft,
) -> UUID:
    now = datetime.now(fetched_at.tzinfo)
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO competitor_listing_insight (
                  tenant_id, snapshot_id, keyword_themes, title_length, title_structure,
                  feature_categories, benefit_term_patterns, differentiation_opportunities,
                  bullet_count, image_count, confidence, derivation_method, insight_state,
                  source_url, fetched_at, derived_at
                ) VALUES (
                  :tenant_id, :snapshot_id, CAST(:keyword_themes AS jsonb), :title_length,
                  CAST(:title_structure AS jsonb), CAST(:feature_categories AS jsonb),
                  CAST(:benefit_term_patterns AS jsonb), CAST(:differentiation_opportunities AS jsonb),
                  :bullet_count, :image_count, :confidence, :derivation_method, :insight_state,
                  :source_url, :fetched_at, :derived_at
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "snapshot_id": str(snapshot_id),
                "keyword_themes": json.dumps(draft.keyword_themes),
                "title_length": draft.title_length,
                "title_structure": json.dumps(draft.title_structure),
                "feature_categories": json.dumps(draft.feature_categories),
                "benefit_term_patterns": json.dumps(draft.benefit_term_patterns),
                "differentiation_opportunities": json.dumps(draft.differentiation_opportunities),
                "bullet_count": draft.bullet_count,
                "image_count": draft.image_count,
                "confidence": draft.confidence.value,
                "derivation_method": draft.derivation_method.value,
                "insight_state": draft.insight_state.value,
                "source_url": source_url,
                "fetched_at": fetched_at,
                "derived_at": now,
            },
        ).one()
        return cast(UUID, row[0])


def get_by_snapshot(tenant_id: UUID, snapshot_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT id, keyword_themes, title_length, title_structure, feature_categories, "
                "benefit_term_patterns, differentiation_opportunities, bullet_count, image_count, "
                "confidence, derivation_method, insight_state, source_url, fetched_at, derived_at "
                "FROM competitor_listing_insight WHERE tenant_id = :tenant_id AND snapshot_id = :snapshot_id"
            ),
            {"tenant_id": str(tenant_id), "snapshot_id": str(snapshot_id)},
        ).mappings().first()
        return dict(row) if row else None


def keyword_themes_for_category(
    tenant_id: UUID, *, observed_category: str, exclude_competitor_url_id: UUID
) -> list[frozenset[str]]:
    """Every OTHER tracked competitor's most recent listing-insight keyword set in the same
    `observed_category` — the raw material `listing_insight.derive`'s
    `differentiation_opportunities` compares against. One entry per distinct competitor_url,
    each its latest insight only (not a full history)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT ON (s.competitor_url_id) li.keyword_themes
                FROM competitor_listing_insight li
                JOIN competitor_snapshot s ON s.id = li.snapshot_id AND s.tenant_id = li.tenant_id
                WHERE li.tenant_id = :tenant_id
                  AND s.observed_category = :observed_category
                  AND s.competitor_url_id != :exclude_competitor_url_id
                ORDER BY s.competitor_url_id, li.derived_at DESC
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "observed_category": observed_category,
                "exclude_competitor_url_id": str(exclude_competitor_url_id),
            },
        )
        return [frozenset((r[0] or {}).keys()) for r in rows]
