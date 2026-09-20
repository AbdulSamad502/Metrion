"""ci_capture_run — §5. Distinct from PI's paid niche research run."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import RunStatus, Trigger


def create_run(
    tenant_id: UUID,
    *,
    trigger: Trigger,
    requested_by: UUID,
    url_ids: list[UUID],
    started_at: datetime,
    research_session_id: UUID | None = None,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_capture_run (
                  tenant_id, trigger, requested_by, url_ids, research_session_id, status, started_at
                )
                VALUES (
                  :tenant_id, :trigger, :requested_by, CAST(:url_ids AS uuid[]), :research_session_id,
                  :status, :started_at
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "trigger": trigger.value,
                "requested_by": str(requested_by),
                "url_ids": [str(u) for u in url_ids],
                "research_session_id": str(research_session_id) if research_session_id else None,
                "status": RunStatus.RUNNING.value,
                "started_at": started_at,
            },
        ).one()
        return row[0]


def finish_run(tenant_id: UUID, run_id: UUID, *, status: RunStatus, finished_at: datetime) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE ci_capture_run SET status = :status, finished_at = :finished_at WHERE id = :id"),
            {"status": status.value, "finished_at": finished_at, "id": str(run_id)},
        )
