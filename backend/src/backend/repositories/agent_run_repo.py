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
import functools
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.repositories import run_liveness
from backend.tenant_context import tenant_scope

CURRENT_PARENT_RUN_ID: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "agent_run_current_parent_run_id", default=None
)


_OPENED_IN_SCOPE: contextvars.ContextVar[list[tuple[UUID, UUID]] | None] = contextvars.ContextVar("agent_run_opened_in_scope", default=None)


@contextmanager
def settle_open_runs_on_error() -> Iterator[None]:
    """Every run this block inserts as RUNNING is finished FAILED (guarded) if the block raises, so an exception in a specialist can never leave the row RUNNING with a live
    process (nothing would ever recover it, the process being alive). A normal exit is untouched: the block settles its own rows. The exception propagates unchanged and
    its text is NOT stored (only its class), so no internals reach the row."""
    opened: list[tuple[UUID, UUID]] = []
    token = _OPENED_IN_SCOPE.set(opened)
    try:
        yield
    except BaseException as exc:
        for tenant_id, run_id in opened:
            try:
                finish_run_if_unfinished(
                    tenant_id, run_id, status="FAILED", error_reason=f"ERROR: {type(exc).__name__}", finished_at=datetime.now(timezone.utc)
                )
            except Exception:  # noqa: BLE001 — settling is best effort; the original exception is the one that must surface
                pass
        raise
    finally:
        _OPENED_IN_SCOPE.reset(token)


def settles_open_runs(fn):  # noqa: ANN001, ANN201 — a decorator over many differently typed callables
    """`settle_open_runs_on_error` as a decorator, for the CEO Hub's direct-dispatch functions."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        with settle_open_runs_on_error():
            return fn(*args, **kwargs)

    return wrapper


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
    "WHERE id = :id AND NOT (status = 'FAILED' AND (error_reason LIKE 'INTERRUPTED%' OR error_reason LIKE 'TIMED_OUT%'))"
)
# ^ a run that recovery (INTERRUPTED) or the leg-deadline policy (TIMED_OUT...) settled keeps that state even when a late, unguarded finisher arrives.

# The same write, but only while the row has not reached a terminal status: a late finisher can no longer overwrite a status
# someone else already settled (R5 audit L7). `output_refs` keeps the COALESCE rule above.
_UPDATE_IF_UNFINISHED_SQL = text(
    "UPDATE agent_run SET status = :status, error_reason = :error_reason, finished_at = :finished_at, "
    "output_refs = COALESCE(CAST(:output_refs AS jsonb), output_refs) "
    "WHERE id = :id AND status IN ('QUEUED', 'RUNNING')"
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
    owned = status == "RUNNING"
    if owned:  # R5: ownership first, so a visible RUNNING row always had a live owner (repositories/run_liveness.py)
        run_liveness.claim(run_id)
    try:
        _insert(tenant_id, run_id, agent_id, trigger_type, trigger_ref, investigation_id, parent_run_id, requested_by, permission_check, entitlement_check, status, output_refs, error_reason, started_at, finished_at)
    except BaseException:
        if owned:
            run_liveness.release(run_id)  # no row was written, so nothing is left to own
        raise
    if owned and (scope := _OPENED_IN_SCOPE.get()) is not None:
        scope.append((tenant_id, run_id))
    return run_id


def _insert(tenant_id, run_id, agent_id, trigger_type, trigger_ref, investigation_id, parent_run_id, requested_by, permission_check, entitlement_check, status, output_refs, error_reason, started_at, finished_at) -> None:  # noqa: ANN001
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
    _disown(run_id, status)  # after the terminal write, never before: a finisher that won cannot look ownerless


def _disown(run_id: UUID, status: str) -> None:
    if status not in ("QUEUED", "RUNNING"):
        run_liveness.release(run_id)


def finish_run_if_unfinished(
    tenant_id: UUID,
    run_id: UUID,
    *,
    status: str,
    error_reason: str | None,
    finished_at: datetime,
    output_refs: Sequence[Any] | None = None,
) -> bool:
    """Finish a run only if it is still `QUEUED` or `RUNNING`. Returns True when this call wrote the terminal state and False when the
    row was already terminal (or absent), in which case nothing is changed. Two concurrent finishers: exactly one gets True."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            _UPDATE_IF_UNFINISHED_SQL,
            {
                "id": str(run_id),
                "status": status,
                "error_reason": error_reason,
                "finished_at": finished_at,
                "output_refs": json.dumps(list(output_refs)) if output_refs is not None else None,
            },
        )
    _disown(run_id, status)
    return bool(result.rowcount)


def get_run(tenant_id: UUID, run_id: UUID) -> dict[str, object] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_GET_SQL, {"id": str(run_id)}).first()
        return dict(row._mapping) if row is not None else None


def list_children(tenant_id: UUID, parent_run_id: UUID) -> list[dict[str, object]]:
    """The rows one CEO turn fanned out to — the flow-visualization grouping key (spec §6.8)."""
    with tenant_scope(tenant_id) as conn:
        return [dict(r._mapping) for r in conn.execute(_CHILDREN_SQL, {"parent_id": str(parent_run_id)})]


def list_running_unconversational(tenant_id: UUID) -> list[dict[str, object]]:
    """RUNNING rows other than the seller-turn CEO anchors (those are settled, with their answer and turn row, by `ceo/recovery.py` under the turn lock)."""
    with tenant_scope(tenant_id) as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT id, agent_id, trigger_type, trigger_ref, investigation_id, parent_run_id, started_at FROM agent_run "
                    "WHERE status = 'RUNNING' AND NOT (agent_id = 'CEO' AND trigger_type = 'CONVERSATIONAL') ORDER BY started_at, id"
                )
            )
        ]


def has_running_agent(tenant_id: UUID, agent_id: str) -> list[UUID]:
    """Ids of this tenant's RUNNING rows of one agent (used to ask whether any of them still has a live owner)."""
    with tenant_scope(tenant_id) as conn:
        return [r[0] for r in conn.execute(text("SELECT id FROM agent_run WHERE status = 'RUNNING' AND agent_id = :a"), {"a": agent_id})]


def settle_orphan_pi_research_runs(tenant_id: UUID, *, finished_at: datetime, created_before: datetime) -> int:
    """Marks this tenant's QUEUED/RUNNING `pi_research_run` rows FAILED. The CALLER has established that no live PI run exists for the tenant. Guarded: a row that
    reached a terminal status in the meantime is left alone, and so is a row created at/after `created_before` (the instant the caller started looking: a run that started
    since belongs to a live owner the caller never saw). No usage is recorded (`usage_due` stays unset)."""
    with tenant_scope(tenant_id) as conn:
        return int(
            conn.execute(
                text("UPDATE pi_research_run SET status = 'FAILED', finished_at = :at WHERE tenant_id = :t AND status IN ('QUEUED', 'RUNNING') AND COALESCE(created_at, started_at, :before - interval '1 second') < :before"),
                {"at": finished_at, "t": str(tenant_id), "before": created_before},
            ).rowcount
        )


_PACKAGE_RUN_TABLES = frozenset({"reconciliation_run", "ci_capture_run"})  # fixed names: never interpolated from input


def list_running_package_runs(tenant_id: UUID, table: str) -> list[UUID]:
    """Ids of this tenant's RUNNING rows in a specialist package's own run table (see `run_liveness.PACKAGE_RUN_KINDS`)."""
    if table not in _PACKAGE_RUN_TABLES:
        raise ValueError("not a package run table")
    with tenant_scope(tenant_id) as conn:
        return [r[0] for r in conn.execute(text(f"SELECT id FROM {table} WHERE status = 'RUNNING' ORDER BY started_at, id"))]  # noqa: S608 - whitelisted above


def settle_package_run_failed(tenant_id: UUID, table: str, run_id: UUID, *, finished_at: datetime) -> bool:
    """Guarded: only a row still RUNNING is written, so a finisher that won keeps its result and two sweepers settle a row once."""
    if table not in _PACKAGE_RUN_TABLES:
        raise ValueError("not a package run table")
    with tenant_scope(tenant_id) as conn:
        return bool(conn.execute(text(f"UPDATE {table} SET status = 'FAILED', finished_at = :at WHERE id = :id AND status = 'RUNNING'"), {"at": finished_at, "id": str(run_id)}).rowcount)  # noqa: S608


def list_running_all(tenant_id: UUID) -> list[dict[str, object]]:
    """Every RUNNING row of this tenant, seller-turn anchors included (diagnostics only; recovery uses the narrower lists above)."""
    with tenant_scope(tenant_id) as conn:
        return [dict(r._mapping) for r in conn.execute(text("SELECT id, agent_id, trigger_type, started_at FROM agent_run WHERE status = 'RUNNING' ORDER BY started_at, id"))]


def count_active_pi_research_runs(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        return int(conn.execute(text("SELECT count(*) FROM pi_research_run WHERE status IN ('QUEUED', 'RUNNING')")).scalar_one())
