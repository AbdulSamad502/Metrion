"""Agent memory persistence — spec agent-memory.md. Append-only, tenant-scoped (FORCE RLS beneath the application filter).

"Active" means: status ACTIVE and no later row names it in `supersedes_id`. A correction supersedes the old row; forgetting is a FORGOTTEN row that supersedes it.
A `supersedes_id` must be a row of THIS tenant with the same scope, agent, kind and key (an FK alone would accept another tenant's id).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tenant_context import tenant_scope

SHARED_KINDS = ("BUSINESS_NAME", "NICHE", "MARKETPLACES", "GOAL", "BRAND_TONE", "DECISION")

_ACTIVE = (
    "SELECT id, scope, agent_code, kind, key, value, basis, source_ref, created_at FROM agent_memory m "
    "WHERE m.status = 'ACTIVE' AND NOT EXISTS (SELECT 1 FROM agent_memory newer WHERE newer.supersedes_id = m.id)"
)


class MemoryError_(ValueError):
    pass


def insert(
    tenant_id: UUID, *, scope: str, agent: str, kind: str, key: str, value: str, basis: str, source_ref: Mapping[str, Any] | None, created_by: UUID | None,
    supersedes_id: UUID | None = None, status: str = "ACTIVE", now: datetime | None = None,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        if supersedes_id is not None:
            old = conn.execute(
                text("SELECT scope, agent_code, kind, key FROM agent_memory WHERE id = :id AND tenant_id = :t"), {"id": str(supersedes_id), "t": str(tenant_id)}
            ).mappings().first()
            if old is None or (old["scope"], old["agent_code"], old["kind"], old["key"]) != (scope, agent, kind, key):
                raise MemoryError_("a correction must replace an item of this tenant with the same scope, agent, kind and key")
        conn.execute(
            text("INSERT INTO agent_memory (id, tenant_id, scope, agent_code, kind, key, value, basis, source_ref, supersedes_id, status, created_by, created_at) "
                 "VALUES (:id, :t, :scope, :agent, :kind, :key, :value, :basis, CAST(:src AS jsonb), :sup, :status, :by, :at)"),
            {"id": str(new_id), "t": str(tenant_id), "scope": scope, "agent": agent, "kind": kind, "key": key, "value": value, "basis": basis,
             "src": json.dumps(dict(source_ref)) if source_ref is not None else None, "sup": str(supersedes_id) if supersedes_id else None, "status": status,
             "by": str(created_by) if created_by else None, "at": now or datetime.now(timezone.utc)},
        )
    return new_id


def list_active(tenant_id: UUID, *, scope: str | None = None, agent: str | None = None, kind: str | None = None, key: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    clauses, params = "", {"lim": limit}
    for col, val in (("scope", scope), ("agent_code", agent), ("kind", kind), ("key", key)):
        if val is not None:
            clauses += f" AND m.{col} = :{col}"
            params[col] = val
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(f"{_ACTIVE}{clauses} ORDER BY m.created_at DESC LIMIT :lim"), params)  # noqa: S608 - column names are fixed literals above
        return [dict(r._mapping) for r in rows]


def get(tenant_id: UUID, memory_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT id, scope, agent_code, kind, key, value, basis, source_ref, created_at, status FROM agent_memory WHERE id = :id"), {"id": str(memory_id)}).first()
        return dict(row._mapping) if row else None
