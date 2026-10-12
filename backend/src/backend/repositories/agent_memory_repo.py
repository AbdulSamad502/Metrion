"""Agent memory persistence — spec agent-memory.md. Append-only, tenant-scoped (FORCE RLS beneath the application filter).

"Active" means: the NEWEST row for its (tenant, scope, agent, kind, key) is status ACTIVE. A correction is a newer row that supersedes the old one; forgetting is a newer FORGOTTEN
row. Deciding by the newest row (not only by who names whom in `supersedes_id`) means one key can never show two active values, even if two writers ever raced, and a forgotten
value cannot resurface as an older duplicate. Writers go through `set_active` / `forget_head`, which serialize per key with a transaction-scoped advisory lock.
A `supersedes_id` must be a row of THIS tenant with the same scope, agent, kind and key (an FK alone would accept another tenant's id).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tenant_context import tenant_scope

SHARED_KINDS = ("BUSINESS_NAME", "NICHE", "MARKETPLACES", "GOAL", "BRAND_TONE", "DECISION")

_HEAD_COLS = "id, scope, agent_code, kind, key, value, basis, source_ref, created_at, status"
_KEY_COLS = ("scope", "agent_code", "kind", "key")


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


def _heads_sql(clauses: str) -> str:
    """The newest row of each key (filters are on the key columns, so they are applied inside), then only the ones still ACTIVE."""
    return (
        f"SELECT id, scope, agent_code, kind, key, value, basis, source_ref, created_at FROM ("
        f"SELECT DISTINCT ON (m.scope, m.agent_code, m.kind, m.key) {_HEAD_COLS} FROM agent_memory m WHERE true{clauses} "
        f"ORDER BY m.scope, m.agent_code, m.kind, m.key, m.created_at DESC, m.id DESC) h WHERE h.status = 'ACTIVE'"
    )


def list_active(tenant_id: UUID, *, scope: str | None = None, agent: str | None = None, kind: str | None = None, key: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    clauses, params = "", {"lim": limit}
    for col, val in (("scope", scope), ("agent_code", agent), ("kind", kind), ("key", key)):
        if val is not None:
            clauses += f" AND m.{col} = :{col}"
            params[col] = val
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(f"{_heads_sql(clauses)} ORDER BY created_at DESC, id LIMIT :lim"), params)  # noqa: S608 - column names are fixed literals above
        return [dict(r._mapping) for r in rows]


def _lock_key(conn: Any, tenant_id: UUID, scope: str, agent: str, kind: str, key: str) -> None:
    """One writer at a time per key, held to the end of this transaction (released by commit or rollback, never leaked)."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"agent_memory|{tenant_id}|{scope}|{agent}|{kind}|{key}"})


def _head(conn: Any, tenant_id: UUID, scope: str, agent: str, kind: str, key: str) -> Any:
    return conn.execute(
        text(f"SELECT {_HEAD_COLS} FROM agent_memory WHERE tenant_id = :t AND scope = :s AND agent_code = :a AND kind = :k AND key = :key ORDER BY created_at DESC, id DESC LIMIT 1"),
        {"t": str(tenant_id), "s": scope, "a": agent, "k": kind, "key": key},
    ).mappings().first()


def _append(conn: Any, tenant_id: UUID, *, scope: str, agent: str, kind: str, key: str, value: str, basis: str, source_ref: Mapping[str, Any] | None, created_by: UUID | None,
            supersedes_id: Any, status: str, head: Any, now: datetime | None) -> UUID:
    new_id = uuid4()
    at = now or datetime.now(timezone.utc)
    if head is not None and at <= head["created_at"]:
        at = head["created_at"] + timedelta(microseconds=1)  # newest-wins must hold even if this host's clock is behind the one that wrote the previous row
    conn.execute(
        text("INSERT INTO agent_memory (id, tenant_id, scope, agent_code, kind, key, value, basis, source_ref, supersedes_id, status, created_by, created_at) "
             "VALUES (:id, :t, :scope, :agent, :kind, :key, :value, :basis, CAST(:src AS jsonb), :sup, :status, :by, :at)"),
        {"id": str(new_id), "t": str(tenant_id), "scope": scope, "agent": agent, "kind": kind, "key": key, "value": value, "basis": basis,
         "src": json.dumps(dict(source_ref)) if source_ref is not None else None, "sup": str(supersedes_id) if supersedes_id else None, "status": status,
         "by": str(created_by) if created_by else None, "at": at},
    )
    return new_id


def set_active(
    tenant_id: UUID, *, scope: str, agent: str, kind: str, key: str, value: str, basis: str, source_ref: Mapping[str, Any] | None, created_by: UUID | None, now: datetime | None = None,
) -> UUID | None:
    """Make `value` the active value of this key. Read, compare and write happen in ONE transaction under the key's lock, so two statements at once cannot both think the
    key was empty or both supersede the same row. Returns the new row's id, or None when it already is the active value (nothing written)."""
    with tenant_scope(tenant_id) as conn:
        _lock_key(conn, tenant_id, scope, agent, kind, key)
        head = _head(conn, tenant_id, scope, agent, kind, key)
        current = head if head is not None and head["status"] == "ACTIVE" else None
        if current is not None and current["value"] == value:
            return None
        return _append(conn, tenant_id, scope=scope, agent=agent, kind=kind, key=key, value=value, basis=basis, source_ref=source_ref, created_by=created_by,
                       supersedes_id=current["id"] if current else None, status="ACTIVE", head=head, now=now)


def forget_head(tenant_id: UUID, memory_id: UUID, created_by: UUID | None) -> bool:
    """Forget the item `memory_id` if, and only if, it is the active value of its key right now (checked under the key's lock, so of several simultaneous forgets exactly
    one succeeds). A foreign, unknown, stale or already-forgotten id is False."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT scope, agent_code, kind, key, basis FROM agent_memory WHERE id = :id AND tenant_id = :t"), {"id": str(memory_id), "t": str(tenant_id)}).mappings().first()
        if row is None:
            return False
        _lock_key(conn, tenant_id, row["scope"], row["agent_code"], row["kind"], row["key"])
        head = _head(conn, tenant_id, row["scope"], row["agent_code"], row["kind"], row["key"])
        if head is None or head["status"] != "ACTIVE" or head["id"] != memory_id:
            return False
        _append(conn, tenant_id, scope=row["scope"], agent=row["agent_code"], kind=row["kind"], key=row["key"], value="(forgotten)", basis=row["basis"],
                source_ref={"forgot": str(memory_id)} if row["basis"] != "AGENT_NOTE" else None, created_by=created_by, supersedes_id=memory_id, status="FORGOTTEN", head=head, now=None)
        return True


def get(tenant_id: UUID, memory_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT id, scope, agent_code, kind, key, value, basis, source_ref, created_at, status FROM agent_memory WHERE id = :id"), {"id": str(memory_id)}).first()
        return dict(row._mapping) if row else None
