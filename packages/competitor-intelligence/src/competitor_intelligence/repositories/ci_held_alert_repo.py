"""ci_held_alert — the quiet-hours queue (spec §5.7, §6.26.2). Held, never dropped: a row is
written when an alert is raised inside the tenant's window and released when the window ends."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope


def insert(tenant_id: UUID, *, finding_id: UUID, hold_until: datetime) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("INSERT INTO ci_held_alert (tenant_id, finding_id, hold_until) VALUES (:tenant_id, :finding_id, :hold_until) RETURNING id"),
            {"tenant_id": str(tenant_id), "finding_id": str(finding_id), "hold_until": hold_until},
        ).one()
        return row[0]


def list_due(tenant_id: UUID, *, now: datetime) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT id, finding_id, hold_until FROM ci_held_alert WHERE tenant_id = :tenant_id AND delivered_at IS NULL AND hold_until <= :now ORDER BY hold_until"),
            {"tenant_id": str(tenant_id), "now": now},
        ).mappings()
        return [dict(r) for r in rows]


def mark_delivered(tenant_id: UUID, held_id: UUID, *, at: datetime) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE ci_held_alert SET delivered_at = :at WHERE tenant_id = :tenant_id AND id = :id AND delivered_at IS NULL"),
            {"tenant_id": str(tenant_id), "id": str(held_id), "at": at},
        )
