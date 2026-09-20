"""competitor_snapshot — §5. REVISED for the evidence model: seller-submitted title/
description/bullets are now permitted under C16's carve-out; `capture_status` reflects a
merge outcome (COMPLETE|PARTIAL|PENDING_MANUAL_ENTRY), not a fetch outcome.

Depends on Step 3's migration adding `title`, `description`, `bullets`, `research_session_id`
to `competitor_snapshot` — see migrations/versions/<date>_0002_evidence_model.py. Integration
tests for this module only pass once that migration is applied.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.evidence.snapshot import SnapshotDraft
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import CaptureStatus


def insert_snapshot(
    tenant_id: UUID, *, competitor_url_id: UUID, ci_capture_run_id: UUID, draft: SnapshotDraft
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO competitor_snapshot (
                  tenant_id, competitor_url_id, ci_capture_run_id, research_session_id,
                  captured_at, capture_status, title, description, bullets,
                  seller_name, observed_category, category_confidence, listed_price_paise,
                  mrp_paise, visible_discount_paise, rating, rating_count, availability,
                  variant_key, source_url, confidence
                ) VALUES (
                  :tenant_id, :competitor_url_id, :ci_capture_run_id, :research_session_id,
                  :captured_at, :capture_status, :title, :description, CAST(:bullets AS jsonb),
                  :seller_name, :observed_category, :category_confidence, :listed_price_paise,
                  :mrp_paise, :visible_discount_paise, :rating, :rating_count, :availability,
                  :variant_key, :source_url, :confidence
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "competitor_url_id": str(competitor_url_id),
                "ci_capture_run_id": str(ci_capture_run_id),
                "research_session_id": str(draft.research_session_id),
                "captured_at": draft.captured_at,
                "capture_status": draft.capture_status.value,
                "title": draft.title,
                "description": draft.description,
                "bullets": json.dumps(list(draft.bullets)) if draft.bullets is not None else None,
                "seller_name": draft.seller_name,
                "observed_category": draft.observed_category,
                "category_confidence": draft.category_confidence.value if draft.category_confidence else None,
                "listed_price_paise": draft.listed_price_paise,
                "mrp_paise": draft.mrp_paise,
                "visible_discount_paise": draft.visible_discount_paise,
                "rating": draft.rating,
                "rating_count": draft.rating_count,
                "availability": draft.availability.value if draft.availability else None,
                "variant_key": draft.variant_key,
                "source_url": draft.source_url,
                "confidence": draft.confidence.value,
            },
        ).one()
        return row[0]


def get_by_id(tenant_id: UUID, snapshot_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT id, competitor_url_id, ci_capture_run_id, research_session_id, source_url,
                       variant_key, captured_at, capture_status, listed_price_paise,
                       visible_discount_paise, availability
                FROM competitor_snapshot
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {"tenant_id": str(tenant_id), "id": str(snapshot_id)},
        ).mappings().first()
        return dict(row) if row else None


def apply_correction(tenant_id: UUID, snapshot_id: UUID, *, draft: SnapshotDraft) -> None:
    """Updates a snapshot's mutable columns after a manual correction (§5.3 rule 4) —
    `research_run.submit_manual_correction` rebuilds the full SnapshotDraft from the
    corrected field set and this writes it back over the existing row. The row's identity
    (id, tenant_id, competitor_url_id, ci_capture_run_id, research_session_id) never changes
    — only the resolved field values, capture_status and confidence do, matching §5.3's
    non-destructive-but-superseding spirit (a correction updates the current picture, it
    doesn't create a second snapshot)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE competitor_snapshot SET
                  capture_status = :capture_status, title = :title, description = :description,
                  bullets = CAST(:bullets AS jsonb), seller_name = :seller_name,
                  observed_category = :observed_category, category_confidence = :category_confidence,
                  listed_price_paise = :listed_price_paise, mrp_paise = :mrp_paise,
                  visible_discount_paise = :visible_discount_paise, rating = :rating,
                  rating_count = :rating_count, availability = :availability,
                  variant_key = :variant_key, confidence = :confidence
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(snapshot_id),
                "capture_status": draft.capture_status.value,
                "title": draft.title,
                "description": draft.description,
                "bullets": json.dumps(list(draft.bullets)) if draft.bullets is not None else None,
                "seller_name": draft.seller_name,
                "observed_category": draft.observed_category,
                "category_confidence": draft.category_confidence.value if draft.category_confidence else None,
                "listed_price_paise": draft.listed_price_paise,
                "mrp_paise": draft.mrp_paise,
                "visible_discount_paise": draft.visible_discount_paise,
                "rating": draft.rating,
                "rating_count": draft.rating_count,
                "availability": draft.availability.value if draft.availability else None,
                "variant_key": draft.variant_key,
                "confidence": draft.confidence.value,
            },
        )


def list_snapshots(tenant_id: UUID, competitor_url_id: UUID, *, limit: int = 50) -> list[dict[str, Any]]:
    """§6.8 snapshot history/timeline — every snapshot for this URL (any capture_status,
    unlike `latest_comparable_snapshot`), newest first. Callers wanting only comparable
    (COMPLETE/PARTIAL) history should filter client-side; this is the raw timeline."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, captured_at, capture_status, confidence, title, listed_price_paise,
                       visible_discount_paise, availability, variant_key, source_url
                FROM competitor_snapshot
                WHERE tenant_id = :tenant_id AND competitor_url_id = :competitor_url_id
                ORDER BY captured_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": str(tenant_id), "competitor_url_id": str(competitor_url_id), "limit": limit},
        ).mappings()
        return [dict(r) for r in rows]


def latest_comparable_snapshot(
    tenant_id: UUID,
    *,
    competitor_url_id: UUID,
    variant_key: str | None,
    exclude_snapshot_id: UUID | None = None,
) -> dict[str, Any] | None:
    """Most recent prior COMPLETE-or-PARTIAL snapshot for this (competitor_url_id,
    variant_key) — §6.3 rule 1 permits comparing against PARTIAL too, "for fields it does
    have." `PENDING_MANUAL_ENTRY` snapshots are excluded — they have no resolved required
    field to compare at all (evidence/merge.py's compute_capture_status guarantees this).
    `variant_key IS NOT DISTINCT FROM :variant_key` treats NULL as its own group, matching a
    single-variant listing rather than excluding it entirely.

    `exclude_snapshot_id` MUST be passed by any caller comparing against a snapshot that is
    already persisted at call time (both `research_run.submit_research_session` — which
    inserts the current snapshot before looking for its prior — and `submit_manual_correction`
    — where the "current" snapshot always already exists). Without it, a snapshot with a
    `captured_at` at or after every other row's would match itself as its own "prior" under
    `ORDER BY captured_at DESC LIMIT 1`, silently comparing a snapshot to itself.
    """
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT id, captured_at, capture_status, listed_price_paise, visible_discount_paise,
                       availability, variant_key
                FROM competitor_snapshot
                WHERE tenant_id = :tenant_id
                  AND competitor_url_id = :competitor_url_id
                  AND capture_status = ANY(CAST(:comparable_statuses AS text[]))
                  AND variant_key IS NOT DISTINCT FROM :variant_key
                  AND (CAST(:exclude_snapshot_id AS uuid) IS NULL OR id != CAST(:exclude_snapshot_id AS uuid))
                ORDER BY captured_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "competitor_url_id": str(competitor_url_id),
                "comparable_statuses": [CaptureStatus.COMPLETE.value, CaptureStatus.PARTIAL.value],
                "variant_key": variant_key,
                "exclude_snapshot_id": str(exclude_snapshot_id) if exclude_snapshot_id else None,
            },
        ).mappings().first()
        return dict(row) if row else None
