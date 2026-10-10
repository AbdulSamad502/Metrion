"""Persistence for `ceo_need` - spec agent-needs-and-shared-knowledge.md 9.1. Append-only and tenant-scoped (FORCE RLS beneath the application filter).

A need is recorded once, when it ends. The unique key `(tenant_id, idempotency_key)` makes a retry of the same turn a no-op rather than a second record.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tenant_context import tenant_scope


def record(
    tenant_id: UUID, *, investigation_id: UUID, turn_message_id: UUID | None, need_key: str, requester_agent: str, mode: str, provider_key: str | None,
    idempotency_key: str, status: str, provider_run_id: UUID | None = None, requester_run_id: UUID | None = None, slot_digest: str | None = None,
) -> bool:
    """True when a row was written, False when this idempotency key already had one."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ceo_need (id, tenant_id, investigation_id, turn_message_id, need_key, requester_agent, mode, provider_key, slot_digest, idempotency_key,
                                      requester_run_id, provider_run_id, status)
                VALUES (:id, :t, :inv, :msg, :nk, :ra, :mode, :pk, :sd, :ik, :rr, :pr, :st)
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": str(uuid4()), "t": str(tenant_id), "inv": str(investigation_id), "msg": str(turn_message_id) if turn_message_id else None, "nk": need_key,
                "ra": requester_agent, "mode": mode, "pk": provider_key, "sd": slot_digest, "ik": idempotency_key,
                "rr": str(requester_run_id) if requester_run_id else None, "pr": str(provider_run_id) if provider_run_id else None, "st": status,
            },
        ).first()
        return row is not None


def list_for_investigation(tenant_id: UUID, investigation_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT * FROM ceo_need WHERE tenant_id = :t AND investigation_id = :inv ORDER BY created_at"), {"t": str(tenant_id), "inv": str(investigation_id)}
        ).mappings()
        return [dict(r) for r in rows]
