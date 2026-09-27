"""agent_data_request — cfo-agent.md §5 (OP1: CFO asks rather than assumes). Every function
takes tenant_id first and receives its connection only via tenant_scope(); no function in
this module opens its own connection.

CP1 scaffolding only (`twinkly-mapping-canyon.md`): this defines the record CFO writes, not
the request/prompt/validation flow — that interaction belongs to the orchestration spec
(cfo-agent.md §5 note, Q9) and is out of scope here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from cfo.repositories.tenant_context import tenant_scope


def insert(
    tenant_id: UUID,
    *,
    requested_field: str,
    reason: str,
    status: str = "OPEN",
    blocking_metric: str | None = None,
) -> UUID:
    """Writes one OPEN agent_data_request row."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO agent_data_request (
                  tenant_id, requested_field, reason, blocking_metric, status, created_at
                )
                VALUES (:tenant_id, :requested_field, :reason, :blocking_metric, :status, now())
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "requested_field": requested_field,
                "reason": reason,
                "blocking_metric": blocking_metric,
                "status": status,
            },
        ).one()
        return row[0]


def count_open(tenant_id: UUID) -> int:
    """Real, already-queryable per-tenant usage (mirrors `competitor_url_repo.count_active`'s
    shape exactly) — for `backend.entitlement.resolve_cfo_entitlement`'s TEMPORARY scaffold to
    compare a future cap against actual numbers from day one. Makes no claim about what any
    cap should be."""
    with tenant_scope(tenant_id) as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM agent_data_request WHERE tenant_id = :tenant_id AND status = 'OPEN'"),
                {"tenant_id": str(tenant_id)},
            ).scalar_one()
        )


def list_for_tenant(tenant_id: UUID) -> list[dict[str, Any]]:
    """All agent_data_request rows visible to this tenant, most recently created first."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT * FROM agent_data_request WHERE tenant_id = :tenant_id ORDER BY created_at DESC"),
            {"tenant_id": str(tenant_id)},
        ).mappings()
        return [dict(r) for r in rows]


def mark_answered(
    tenant_id: UUID,
    request_id: UUID,
    *,
    answered_with_kind: str,
    answered_with_id: UUID,
) -> None:
    """Transitions a request to ANSWERED and records what answered it. V1 only ever answers
    with MANUAL_ADJUSTMENT (cfo-agent.md §5) — this function does not enforce that choice,
    the caller does."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE agent_data_request
                SET status = 'ANSWERED', answered_with_kind = :answered_with_kind,
                    answered_with_id = :answered_with_id
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(request_id),
                "answered_with_kind": answered_with_kind,
                "answered_with_id": str(answered_with_id),
            },
        )
