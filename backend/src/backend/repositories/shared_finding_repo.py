"""Shared findings persistence — spec agent-needs-and-shared-knowledge.md section 6. Append-only, tenant-scoped (FORCE RLS beneath the application filter).

"Active" means: status ACTIVE and no later row names it in `supersedes_id`. The database enforces the gate (no digit in agent/engine text, ENGINE_VERIFIED refs, same-tenant
refs, SELLER_STATED rules, tombstones); this module adds the checks a CHECK cannot make (that a source or an ESTIMATE ref exists for THIS tenant).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tenant_context import tenant_scope

# source_ref kind -> owning table (fixed literals; never built from input)
SOURCE_TABLES: Mapping[str, str] = {
    "agent_run": "agent_run", "investigation_finding": "investigation_finding", "metric_result": "metric_result", "pi_research_run": "pi_research_run",
    "competitor_snapshot": "competitor_snapshot", "cmo_generation": "cmo_generation", "message": "investigation_message",
}

_COLS = "id, tenant_id, agent_code, kind, subject, text, trust, source_ref, figure_refs, dedupe_key, supersedes_id, status, created_by, created_at"
_ACTIVE = f"SELECT {_COLS} FROM shared_finding f WHERE f.status = 'ACTIVE' AND NOT EXISTS (SELECT 1 FROM shared_finding newer WHERE newer.supersedes_id = f.id)"


class FindingRefError(ValueError):
    pass


def _exists(conn: Any, table: str, tenant_id: UUID, ref_id: str) -> bool:
    return conn.execute(text(f"SELECT 1 FROM {table} WHERE id = :id AND tenant_id = :t"), {"id": ref_id, "t": str(tenant_id)}).first() is not None  # noqa: S608 - table is a fixed literal


def resolve_engine_results(tenant_id: UUID, ids: Sequence[str]) -> set[str]:
    """Which of these metric_result ids exist for THIS tenant (the same test the database trigger applies)."""
    if not ids:
        return set()
    with tenant_scope(tenant_id) as conn:
        return {str(r[0]) for r in conn.execute(text("SELECT id FROM metric_result WHERE tenant_id = :t AND id = ANY(CAST(:ids AS uuid[]))"), {"t": str(tenant_id), "ids": list(ids)})}


def insert(
    tenant_id: UUID, *, agent: str, kind: str, subject: str | None, body: str, trust: str, source_ref: Mapping[str, Any], figure_refs: Sequence[Mapping[str, Any]],
    dedupe_key: str, created_by: UUID | None, supersedes_id: UUID | None = None, status: str = "ACTIVE", now: datetime | None = None,
) -> UUID | None:
    """Append one row. Returns None when the same source was already recorded, or when the finding being superseded was already superseded (a repeat is a no-op); a database gate refusal raises. Nothing here relaxes the CHECKs."""
    new_id = uuid4()
    src_table = SOURCE_TABLES.get(str(source_ref.get("kind")))
    with tenant_scope(tenant_id) as conn:
        if src_table is not None and status == "ACTIVE" and not _exists(conn, src_table, tenant_id, str(source_ref.get("id"))):
            raise FindingRefError("the source of a finding must be a record of this tenant")
        if status == "ACTIVE":
            for ref in figure_refs:
                if ref.get("kind") == "ESTIMATE" and not _exists(conn, "product_feasibility_estimate", tenant_id, str(ref.get("id"))):
                    raise FindingRefError("an ESTIMATE ref must be an estimate of this tenant")
        if supersedes_id is not None:
            # One writer at a time per finding chain, held to the end of this transaction: a correction and a forget (or two forgets) of the same finding cannot both land.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"shared_finding|{tenant_id}|{dedupe_key}"})
            old = conn.execute(text("SELECT dedupe_key FROM shared_finding WHERE id = :id AND tenant_id = :t"), {"id": str(supersedes_id), "t": str(tenant_id)}).first()
            if old is None or old[0] != dedupe_key:
                raise FindingRefError("a correction must replace a finding of this tenant for the same source")
            if conn.execute(text("SELECT 1 FROM shared_finding WHERE supersedes_id = :id AND tenant_id = :t LIMIT 1"), {"id": str(supersedes_id), "t": str(tenant_id)}).first() is not None:
                return None  # someone else already corrected or forgot it: this finding is no longer the active one, so nothing is written and nothing is reported as done
        res = conn.execute(
            text(f"INSERT INTO shared_finding ({_COLS}) VALUES (:id, :t, :agent, :kind, :subject, :body, :trust, CAST(:src AS jsonb), CAST(:figs AS jsonb), :dk, :sup, :status, :by, :at) "
                 "ON CONFLICT (tenant_id, dedupe_key) WHERE supersedes_id IS NULL DO NOTHING"),
            {"id": str(new_id), "t": str(tenant_id), "agent": agent, "kind": kind, "subject": subject, "body": body, "trust": trust, "src": json.dumps(dict(source_ref)),
             "figs": json.dumps([dict(r) for r in figure_refs]), "dk": dedupe_key, "sup": str(supersedes_id) if supersedes_id else None, "status": status,
             "by": str(created_by) if created_by else None, "at": now or datetime.now(timezone.utc)},
        )
        return new_id if res.rowcount == 1 else None


def is_forgotten(tenant_id: UUID, dedupe_key: str) -> bool:
    with tenant_scope(tenant_id) as conn:
        return conn.execute(text("SELECT 1 FROM shared_finding WHERE tenant_id = :t AND dedupe_key = :dk AND status = 'FORGOTTEN' LIMIT 1"), {"t": str(tenant_id), "dk": dedupe_key}).first() is not None


def list_active(tenant_id: UUID, *, agents: Sequence[str] | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Active findings, newest first. `agents=None` means all; an empty sequence means none."""
    if agents is not None and not agents:
        return []
    clause, params = "", {"lim": limit, "t": str(tenant_id)}
    if agents is not None:
        clause, params["agents"] = " AND f.agent_code = ANY(:agents)", list(agents)
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(f"{_ACTIVE} AND f.tenant_id = :t{clause} ORDER BY f.created_at DESC, f.id LIMIT :lim"), params)
        return [dict(r._mapping) for r in rows]


def count_active_by_agent(tenant_id: UUID) -> dict[str, int]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(f"SELECT a.agent_code, count(*) FROM ({_ACTIVE} AND f.tenant_id = :t) a GROUP BY a.agent_code"), {"t": str(tenant_id)})
        return {str(r[0]): int(r[1]) for r in rows}


def get(tenant_id: UUID, finding_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text(f"SELECT {_COLS}, EXISTS (SELECT 1 FROM shared_finding newer WHERE newer.supersedes_id = shared_finding.id) AS superseded "
                                "FROM shared_finding WHERE id = :id AND tenant_id = :t"), {"id": str(finding_id), "t": str(tenant_id)}).first()
        return dict(row._mapping) if row else None
