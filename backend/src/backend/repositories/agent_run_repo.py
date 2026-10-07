"""agent_run — ceo-agent-orchestration.md §5, C7. Owned/migrated by `backend`
(`backend/migrations/versions/20260917_0002_orchestration_tables.py`; CHECKs added by
`20261007_0006_ceo_foundation.py`).

`permission_check`/`entitlement_check` are REQUIRED parameters, matching
`competitor_intelligence.repositories.agent_run_repo`'s own contract for the same table —
this module doesn't compute an auth verdict, it only records one a caller already reached.

**Parent inheritance (CEO CP1, spec §6.15 R5).** `CURRENT_PARENT_RUN_ID` is set ONLY by the CEO
dispatch choke point (`backend.ceo.dispatch`) for the duration of one leg, via `parent_run_scope`.
Any `agent_run` a specialist's own code writes through THIS repository inside that scope becomes
the leg's child without the specialist knowing about the CEO — which is how PI's and CMO's own rows
get linked to the CEO turn without touching them. An explicit `parent_run_id` always wins, and
`inherit_parent=False` opts a row out entirely (the CEO's own anchor row uses it). Outside a
choke-point scope the variable is unset, so direct-path rows still have no parent (AC2).
"""

from __future__ import annotations

import contextvars
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tenant_context import tenant_scope

CURRENT_PARENT_RUN_ID: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "agent_run_current_parent_run_id", default=None
)


@contextmanager
def parent_run_scope(run_id: UUID) -> Iterator[None]:
    """Every `agent_run` inserted through this module inside the block inherits `run_id` as its parent."""
    token = CURRENT_PARENT_RUN_ID.set(run_id)
    try:
        yield
    finally:
        CURRENT_PARENT_RUN_ID.reset(token)


_INSERT_SQL = text(
    """
    INSERT INTO agent_run (
      id, tenant_id, agent_id, trigger_type, trigger_ref, investigation_id, parent_run_id,
      requested_by, permission_check, entitlement_check, status, output_refs,
      error_reason, started_at, finished_at
    ) VALUES (
      :id, :tenant_id, :agent_id, :trigger_type, :trigger_ref, :investigation_id, :parent_run_id,
      :requested_by, :permission_check, :entitlement_check, :status,
      CAST(:output_refs AS jsonb), :error_reason, :started_at, :finished_at
    )
    """
)

# `output_refs` is only overwritten when a value is supplied; a plain status update never erases it.
_UPDATE_SQL = text(
    "UPDATE agent_run SET status = :status, error_reason = :error_reason, finished_at = :finished_at, "
    "output_refs = COALESCE(CAST(:output_refs AS jsonb), output_refs) "
    "WHERE id = :id"
)

_GET_SQL = text(
    "SELECT id, agent_id, trigger_type, trigger_ref, investigation_id, parent_run_id, status, "
    "permission_check, entitlement_check, output_refs, error_reason, started_at, finished_at "
    "FROM agent_run WHERE id = :id"
)

_CHILDREN_SQL = text(
    "SELECT id, agent_id, trigger_type, trigger_ref, investigation_id, parent_run_id, status, "
    "permission_check, entitlement_check, output_refs, error_reason, started_at, finished_at "
    "FROM agent_run WHERE parent_run_id = :parent_id ORDER BY started_at, id"
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
    output_refs: Sequence[Any] | None = None,
    error_reason: str | None = None,
    parent_run_id: UUID | None = None,
    investigation_id: UUID | None = None,
    inherit_parent: bool = True,
    run_id: UUID | None = None,
) -> UUID:
    # `run_id` lets a caller that must stamp the id on other rows BEFORE the run row exists (CMO: the
    # artefacts carry it, the run row is written only once a request is actually accepted) choose it.
    run_id = run_id or uuid4()
    if parent_run_id is None and inherit_parent:
        parent_run_id = CURRENT_PARENT_RUN_ID.get()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(run_id),
                "tenant_id": str(tenant_id),
                "agent_id": agent_id,
                "trigger_type": trigger_type,
                "trigger_ref": trigger_ref,
                "investigation_id": str(investigation_id) if investigation_id else None,
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "requested_by": str(requested_by),
                "permission_check": permission_check,
                "entitlement_check": entitlement_check,
                "status": status,
                "output_refs": json.dumps(list(output_refs)) if output_refs is not None else None,
                "error_reason": error_reason,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
    return run_id


def finish_run(
    tenant_id: UUID,
    run_id: UUID,
    *,
    status: str,
    error_reason: str | None,
    finished_at: datetime,
    output_refs: Sequence[Any] | None = None,
) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _UPDATE_SQL,
            {
                "id": str(run_id),
                "status": status,
                "error_reason": error_reason,
                "finished_at": finished_at,
                "output_refs": json.dumps(list(output_refs)) if output_refs is not None else None,
            },
        )


def get_run(tenant_id: UUID, run_id: UUID) -> dict[str, object] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_GET_SQL, {"id": str(run_id)}).first()
        return dict(row._mapping) if row is not None else None


def list_children(tenant_id: UUID, parent_run_id: UUID) -> list[dict[str, object]]:
    """The rows one CEO turn fanned out to — the flow-visualization grouping key (spec §6.8)."""
    with tenant_scope(tenant_id) as conn:
        return [dict(r._mapping) for r in conn.execute(_CHILDREN_SQL, {"parent_id": str(parent_run_id)})]
