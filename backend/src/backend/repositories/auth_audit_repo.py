"""auth_audit repository — auth.md §7.6. Every security-relevant event (sign-in, tenant
creation, permission denial at steps 2-6, webhook-driven changes) is written here."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO auth_audit (id, tenant_id, actor_user_id, event, subject, metadata, occurred_at)
    VALUES (:id, :tenant_id, :actor_user_id, :event, :subject, CAST(:metadata AS jsonb), now())
    """
)


def record(
    tenant_id: UUID,
    *,
    actor_user_id: UUID | None,
    event: str,
    subject: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "actor_user_id": str(actor_user_id) if actor_user_id else None,
                "event": event,
                "subject": subject,
                "metadata": json.dumps(metadata or {}),
            },
        )
