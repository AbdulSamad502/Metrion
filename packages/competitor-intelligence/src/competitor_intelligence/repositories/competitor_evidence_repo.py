"""competitor_evidence — §5 (NEW). One row per screenshot the seller submits. Depends on
Step 3's migration creating this table."""

from __future__ import annotations

from datetime import datetime
from typing import Any
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
        return row[0]


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
