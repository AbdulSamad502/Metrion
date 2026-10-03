"""agent_run — ceo-agent-orchestration.md §5, C7. Owned/migrated by `backend`
(`backend/migrations/versions/20260917_0002_orchestration_tables.py`).

`permission_check`/`entitlement_check` are REQUIRED parameters, matching
`competitor_intelligence.repositories.agent_run_repo`'s own contract for the same table —
this module doesn't compute an auth verdict, it only records one a caller already reached.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO agent_run (
      id, tenant_id, agent_id, trigger_type, trigger_ref, investigation_id, parent_run_id,
      requested_by, permission_check, entitlement_check, status, output_refs,
      error_reason, started_at, finished_at
    ) VALUES (
      :id, :tenant_id, :agent_id, :trigger_type, :trigger_ref, NULL, :parent_run_id,
      :requested_by, :permission_check, :entitlement_check, :status,
      CAST(:output_refs AS jsonb), :error_reason, :started_at, :finished_at
    )
    """
)

_UPDATE_SQL = text(
    "UPDATE agent_run SET status = :status, error_reason = :error_reason, finished_at = :finished_at "
    "WHERE id = :id"
)

_GET_SQL = text(
    "SELECT id, agent_id, trigger_type, trigger_ref, parent_run_id, status, "
    "permission_check, entitlement_check, started_at, finished_at "
    "FROM agent_run WHERE id = :id"
)


def insert_run(
    tenant_id: UUID,
    *,
    agent_id: str,
    trigger_type: str,
    trigger_ref: str,
    requested_by: UUID,
    permission_check: str,
    entitlement_check: str,
    status: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    output_refs: list[str] | None = None,
    error_reason: str | None = None,
    parent_run_id: UUID | None = None,
    run_id: UUID | None = None,
) -> UUID:
    # `run_id` lets a caller that must stamp the id on other rows BEFORE the run row exists (CMO: the
    # artefacts carry it, the run row is written only once a request is actually accepted) choose it.
    run_id = run_id or uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(run_id),
                "tenant_id": str(tenant_id),
                "agent_id": agent_id,
                "trigger_type": trigger_type,
                "trigger_ref": trigger_ref,
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "requested_by": str(requested_by),
                "permission_check": permission_check,
                "entitlement_check": entitlement_check,
                "status": status,
                "output_refs": json.dumps(output_refs) if output_refs is not None else None,
                "error_reason": error_reason,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
    return run_id


def finish_run(tenant_id: UUID, run_id: UUID, *, status: str, error_reason: str | None, finished_at: datetime) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _UPDATE_SQL,
            {"id": str(run_id), "status": status, "error_reason": error_reason, "finished_at": finished_at},
        )


def get_run(tenant_id: UUID, run_id: UUID) -> dict[str, object] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_GET_SQL, {"id": str(run_id)}).first()
        return dict(row._mapping) if row is not None else None
