"""competitor_evidence — §5 (NEW). One row per screenshot the seller submits. Depends on
Step 3's migration creating this table."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import ExtractionStatus


def insert_evidence(
    tenant_id: UUID,
    *,
    competitor_url_id: UUID,
    research_session_id: UUID,
    image_ref: str,
    uploaded_by: UUID,
    uploaded_at: datetime,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO competitor_evidence (
                  tenant_id, competitor_url_id, research_session_id, image_ref, uploaded_by,
                  uploaded_at, extraction_status
                ) VALUES (
                  :tenant_id, :competitor_url_id, :research_session_id, :image_ref, :uploaded_by,
                  :uploaded_at, :status
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "competitor_url_id": str(competitor_url_id),
                "research_session_id": str(research_session_id),
                "image_ref": image_ref,
                "uploaded_by": str(uploaded_by),
                "uploaded_at": uploaded_at,
                "status": ExtractionStatus.PENDING.value,
            },
        ).one()
        return cast(UUID, row[0])


def set_intake_metadata(
    tenant_id: UUID,
    evidence_id: UUID,
    *,
    content_sha256: str,
    perceptual_hash: str | None,
    intake_channel: str,
    quality_status: str,
    duplicate_of: UUID | None = None,
) -> None:
    """C36/§5.7: hashes for per-tenant duplicate detection, the channel the image arrived by,
    and the quality-gate outcome."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE competitor_evidence
                SET content_sha256 = :sha, perceptual_hash = :phash, intake_channel = :channel,
                    quality_status = :quality, duplicate_of = :duplicate_of
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "sha": content_sha256,
                "phash": perceptual_hash,
                "channel": intake_channel,
                "quality": quality_status,
                "duplicate_of": str(duplicate_of) if duplicate_of else None,
                "tenant_id": str(tenant_id),
                "id": str(evidence_id),
            },
        )


def find_by_sha(tenant_id: UUID, content_sha256: str) -> dict[str, Any] | None:
    """The earliest evidence row in THIS tenant with the same content hash (never across
    tenants: the query is tenant-scoped and RLS-guarded)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT id, competitor_url_id, research_session_id, image_ref, uploaded_at
                FROM competitor_evidence
                WHERE tenant_id = :tenant_id AND content_sha256 = :sha AND duplicate_of IS NULL
                ORDER BY uploaded_at LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "sha": content_sha256},
        ).mappings().first()
        return dict(row) if row else None


def list_perceptual_hashes(tenant_id: UUID, *, competitor_url_id: UUID | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Recent perceptual hashes for near-duplicate comparison (bounded)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, perceptual_hash FROM competitor_evidence
                WHERE tenant_id = :tenant_id AND perceptual_hash IS NOT NULL AND duplicate_of IS NULL
                  AND (CAST(:competitor_url_id AS uuid) IS NULL OR competitor_url_id = CAST(:competitor_url_id AS uuid))
                ORDER BY uploaded_at DESC LIMIT :limit
                """
            ),
            {"tenant_id": str(tenant_id), "competitor_url_id": str(competitor_url_id) if competitor_url_id else None, "limit": limit},
        ).mappings()
        return [dict(r) for r in rows]


def update_extraction_status(
    tenant_id: UUID, evidence_id: UUID, *, status: ExtractionStatus, extraction_model: str | None = None
) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                "UPDATE competitor_evidence SET extraction_status = :status, "
                "extraction_model = COALESCE(:extraction_model, extraction_model) WHERE id = :id"
            ),
            {"status": status.value, "extraction_model": extraction_model, "id": str(evidence_id)},
        )


def get_by_research_session(tenant_id: UUID, research_session_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, competitor_url_id, image_ref, uploaded_at, extraction_status, extraction_model
                FROM competitor_evidence
                WHERE tenant_id = :tenant_id AND research_session_id = :research_session_id
                ORDER BY uploaded_at
                """
            ),
            {"tenant_id": str(tenant_id), "research_session_id": str(research_session_id)},
        ).mappings()
        return [dict(r) for r in rows]


def list_for_competitor(tenant_id: UUID, competitor_url_id: UUID, *, limit: int = 10) -> list[dict[str, Any]]:
    """The newest evidence rows for one tracked competitor (metadata only, never the image bytes)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, competitor_url_id, research_session_id, uploaded_at, extraction_status, intake_channel, quality_status
                FROM competitor_evidence
                WHERE tenant_id = :tenant_id AND competitor_url_id = :url AND duplicate_of IS NULL
                ORDER BY uploaded_at DESC LIMIT :limit
                """
            ),
            {"tenant_id": str(tenant_id), "url": str(competitor_url_id), "limit": limit},
        ).mappings()
        return [dict(r) for r in rows]


def get_many(tenant_id: UUID, evidence_ids: list[UUID]) -> list[dict[str, Any]]:
    """Evidence rows by id, tenant-scoped (an id from another tenant is simply absent)."""
    if not evidence_ids:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT id, competitor_url_id, uploaded_at, extraction_status, extraction_model, intake_channel, quality_status "
                "FROM competitor_evidence WHERE tenant_id = :tenant_id AND id = ANY(CAST(:ids AS uuid[])) ORDER BY uploaded_at"
            ),
            {"tenant_id": str(tenant_id), "ids": [str(i) for i in evidence_ids]},
        ).mappings()
        return [dict(r) for r in rows]
