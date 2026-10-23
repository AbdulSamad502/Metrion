"""ci_capture_run — §5. Distinct from PI's paid niche research run."""

from __future__ import annotations

import contextvars
import functools
from collections.abc import Callable
from datetime import datetime, timezone
from typing import ParamSpec, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import text

from competitor_intelligence import ownership
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import RunStatus, Trigger


P = ParamSpec("P")
R = TypeVar("R")

_OPENED: contextvars.ContextVar[list[tuple[UUID, UUID]] | None] = contextvars.ContextVar("ci_capture_runs_opened", default=None)


def create_run(
    tenant_id: UUID,
    *,
    trigger: Trigger,
    requested_by: UUID,
    url_ids: list[UUID],
    started_at: datetime,
    research_session_id: UUID | None = None,
) -> UUID:
    run_id = uuid4()
    ownership.claim(run_id)  # BEFORE the row exists: a visible RUNNING row always had a live owner
    try:
        with tenant_scope(tenant_id) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ci_capture_run (
                      id, tenant_id, trigger, requested_by, url_ids, research_session_id, status, started_at
                    )
                    VALUES (
                      :id, :tenant_id, :trigger, :requested_by, CAST(:url_ids AS uuid[]), :research_session_id,
                      :status, :started_at
                    )
                    """
                ),
                {
                    "id": str(run_id),
                    "tenant_id": str(tenant_id),
                    "trigger": trigger.value,
                    "requested_by": str(requested_by),
                    "url_ids": [str(u) for u in url_ids],
                    "research_session_id": str(research_session_id) if research_session_id else None,
                    "status": RunStatus.RUNNING.value,
                    "started_at": started_at,
                },
            )
    except BaseException:
        ownership.release(run_id)
        raise
    if (opened := _OPENED.get()) is not None:
        opened.append((tenant_id, run_id))
    return run_id


def finish_run(tenant_id: UUID, run_id: UUID, *, status: RunStatus, finished_at: datetime) -> None:
    # Guarded: a run that recovery already settled (its owner was gone) keeps that outcome.
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE ci_capture_run SET status = :status, finished_at = :finished_at WHERE id = :id AND status = 'RUNNING'"),
            {"status": status.value, "finished_at": finished_at, "id": str(run_id)},
        )
    ownership.release(run_id)  # after the terminal write, never before


def settles_open_runs(fn: Callable[P, R]) -> Callable[P, R]:
    """If the wrapped call raises, every `ci_capture_run` it left RUNNING is marked FAILED (the process is alive, so nothing else would ever settle it)."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        opened: list[tuple[UUID, UUID]] = []
        token = _OPENED.set(opened)
        try:
            return fn(*args, **kwargs)
        except BaseException:
            for tenant_id, run_id in opened:
                try:
                    finish_run(tenant_id, run_id, status=RunStatus.FAILED, finished_at=datetime.now(timezone.utc))
                except Exception:  # noqa: BLE001 — the original exception is the one that must surface
                    pass
            raise
        finally:
            _OPENED.reset(token)

    return wrapper
