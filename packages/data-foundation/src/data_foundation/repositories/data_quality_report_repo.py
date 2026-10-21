"""data_quality_report repository (cfo-data-intelligence.md §6.6): one summary per ingestion job."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope


def upsert(tenant_id: UUID, *, ingestion_job_id: UUID, summary: dict[str, Any]) -> UUID:
    rid = uuid4()
    with tenant_scope(tenant_id) as conn:
        got = conn.execute(
            text(
                """INSERT INTO data_quality_report (id, tenant_id, ingestion_job_id, summary)
                   VALUES (:id, :t, :j, CAST(:s AS jsonb))
                   ON CONFLICT (ingestion_job_id) DO UPDATE SET summary = EXCLUDED.summary
                   RETURNING id"""
            ),
            {"id": str(rid), "t": str(tenant_id), "j": str(ingestion_job_id), "s": json.dumps(summary)},
        ).scalar_one()
    return UUID(str(got))


def get_for_job(tenant_id: UUID, ingestion_job_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT summary FROM data_quality_report WHERE tenant_id = :t AND ingestion_job_id = :j"),
            {"t": str(tenant_id), "j": str(ingestion_job_id)},
        ).scalar_one_or_none()
    return dict(row) if row is not None else None
