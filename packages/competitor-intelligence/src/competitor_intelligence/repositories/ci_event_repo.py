"""ci_event — append-only CI history (spec §5.7, C47). INSERT and SELECT only: the application
role has no UPDATE or DELETE on this table (migration 20261018_0002), and this module offers
neither."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.intake.events import CiEvent, safe_detail
from competitor_intelligence.repositories.tenant_context import tenant_scope

SYSTEM_ACTOR = "SYSTEM"


def record(
    tenant_id: UUID,
    event: CiEvent,
    *,
    actor: UUID | str = SYSTEM_ACTOR,
    agent_run_id: UUID | None = None,
    investigation_id: UUID | None = None,
    object_type: str | None = None,
    object_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> UUID:
    payload = safe_detail(detail)  # raises on anything that could be free text
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_event (tenant_id, event_type, actor, agent_run_id, investigation_id,
                                      object_type, object_id, detail, occurred_at)
                VALUES (:tenant_id, :event_type, :actor, :agent_run_id, :investigation_id,
                        :object_type, :object_id, CAST(:detail AS jsonb), :occurred_at)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "event_type": event.value,
                "actor": str(actor),
                "agent_run_id": str(agent_run_id) if agent_run_id else None,
                "investigation_id": str(investigation_id) if investigation_id else None,
                "object_type": object_type,
                "object_id": str(object_id) if object_id else None,
                "detail": json.dumps(payload),
                "occurred_at": occurred_at or datetime.now(timezone.utc),
            },
        ).one()
        return cast(UUID, row[0])


def list_recent(tenant_id: UUID, *, limit: int = 50, object_type: str | None = None, object_id: UUID | None = None) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, event_type, actor, agent_run_id, investigation_id, object_type, object_id, detail, occurred_at
                FROM ci_event
                WHERE tenant_id = :tenant_id
                  AND (CAST(:object_type AS text) IS NULL OR object_type = :object_type)
                  AND (CAST(:object_id AS uuid) IS NULL OR object_id = CAST(:object_id AS uuid))
                ORDER BY occurred_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": str(tenant_id), "limit": limit, "object_type": object_type, "object_id": str(object_id) if object_id else None},
        ).mappings()
        return [dict(r) for r in rows]
