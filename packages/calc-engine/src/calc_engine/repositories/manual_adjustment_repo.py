"""manual_adjustment repository — append-only, deterministic-engine.md §7.1.

Every write is an INSERT. There is no update()/delete() function here at all — not because
application logic declines to call one, but because the migration (20260917_0001) revokes
UPDATE and DELETE on this table from metrion_app at the grant level (auth.md-style
defence-in-depth: enforced by the database, not just trusted application code). A correction
is a new row whose `supersedes_id` points at the row it replaces.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from calc_engine.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO manual_adjustment
        (id, tenant_id, target_type, target_ref, field, value, reason, created_by, created_at, supersedes_id, status)
    VALUES
        (:id, :tenant_id, :target_type, :target_ref, :field, CAST(:value AS jsonb), :reason, :created_by, :created_at, :supersedes_id, 'ACTIVE')
    """
)

_ACTIVE_FOR_TARGET_SQL = text(
    """
    SELECT id, target_type, target_ref, field, value, reason, created_by, created_at, supersedes_id, status
    FROM manual_adjustment
    WHERE target_type = :target_type AND target_ref = :target_ref AND field = :field AND status = 'ACTIVE'
    ORDER BY created_at DESC
    """
)


def insert_adjustment(
    tenant_id: UUID,
    *,
    target_type: str,
    target_ref: str,
    field: str,
    value: Any,
    created_by: UUID,
    created_at: datetime,
    reason: str | None = None,
    supersedes_id: UUID | None = None,
) -> UUID:
    """Appends a new manual_adjustment row. `value` must already be JSON-serialisable — this
    repository does not interpret the §7.2.1 field registry's shapes, it only persists them."""
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(new_id),
                "tenant_id": str(tenant_id),
                "target_type": target_type,
                "target_ref": target_ref,
                "field": field,
                "value": json.dumps(value),
                "reason": reason,
                "created_by": str(created_by),
                "created_at": created_at,
                "supersedes_id": str(supersedes_id) if supersedes_id else None,
            },
        )
    return new_id


def active_adjustments_for_target(
    tenant_id: UUID, *, target_type: str, target_ref: str, field: str
) -> list[dict[str, Any]]:
    """Returns ACTIVE rows for one (target_type, target_ref, field), newest first. A field
    with more than one ACTIVE row is a data anomaly this repository does not resolve —
    §7.1's "conflict is surfaced, not resolved" is a caller-level (formula/UI) concern."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _ACTIVE_FOR_TARGET_SQL,
            {"target_type": target_type, "target_ref": target_ref, "field": field},
        )
        return [dict(row._mapping) for row in rows]
