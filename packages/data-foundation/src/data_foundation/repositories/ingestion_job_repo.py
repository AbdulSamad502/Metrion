"""ingestion_job repository — cfo-data-intelligence.md §5, §6.1, §6.3.

State machine: QUEUED -> PROFILING -> (AWAITING_MAPPING_CONFIRMATION ->) PARSING -> VALIDATING -> COMMITTING
-> DONE, or FAILED / CANCELLED from any non-terminal state. Terminal states never change again: every
transition is a guarded UPDATE, so a late worker cannot resurrect a cancelled or failed job. One active job
per file is enforced by a partial unique index, not by application code.

Interrupted jobs (a worker or process that died) are recovered lazily, per tenant (`recover_stale`): RLS
means no code can read another tenant's jobs, so there is deliberately no cross-tenant startup sweep.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from data_foundation.repositories.tenant_context import tenant_scope

ACTIVE_STATES = ("QUEUED", "PROFILING", "AWAITING_MAPPING_CONFIRMATION", "PARSING", "VALIDATING", "COMMITTING")
TERMINAL_STATES = ("DONE", "FAILED", "CANCELLED")
_ALL = frozenset(ACTIVE_STATES + TERMINAL_STATES)

_COLUMNS = (
    "id, tenant_id, report_file_id, adapter_id, mapping_id, report_kind, sheet_name, status, progress_rows, "
    "total_rows_estimate, error_code, error_detail, outcome, attempt, created_by, created_at, started_at, finished_at, heartbeat_at"
)


class ActiveJobExists(Exception):
    """A job for this file is already running (or queued). Carries its id so the caller can return it."""

    def __init__(self, job_id: UUID | None) -> None:
        self.job_id = job_id
        super().__init__(f"an ingestion job for this file is already active ({job_id})")


def create_job(
    tenant_id: UUID,
    *,
    report_file_id: UUID,
    report_kind: str,
    created_by: UUID,
    sheet_name: str | None = None,
    attempt: int = 1,
) -> UUID:
    job_id = uuid4()
    try:
        with tenant_scope(tenant_id) as conn:
            conn.execute(
                text(
                    """INSERT INTO ingestion_job (id, tenant_id, report_file_id, report_kind, sheet_name, status, attempt, created_by)
                       VALUES (:id, :t, :f, :k, :s, 'QUEUED', :a, :u)"""
                ),
                {"id": str(job_id), "t": str(tenant_id), "f": str(report_file_id), "k": report_kind, "s": sheet_name,
                 "a": attempt, "u": str(created_by)},
            )
    except IntegrityError as exc:
        if "ingestion_job_one_active_per_file" in str(exc.orig):
            raise ActiveJobExists(active_job_for_file(tenant_id, report_file_id)) from None
        raise
    return job_id


def active_job_for_file(tenant_id: UUID, report_file_id: UUID) -> UUID | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT id FROM ingestion_job WHERE tenant_id = :t AND report_file_id = :f AND status = ANY(CAST(:s AS text[]))"),
            {"t": str(tenant_id), "f": str(report_file_id), "s": list(ACTIVE_STATES)},
        ).first()
    return UUID(str(row[0])) if row else None


def get_job(tenant_id: UUID, job_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(f"SELECT {_COLUMNS} FROM ingestion_job WHERE tenant_id = :t AND id = :id"), {"t": str(tenant_id), "id": str(job_id)}
        ).first()
    return dict(row._mapping) if row else None


def list_jobs(tenant_id: UUID, *, limit: int = 50) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(f"SELECT {_COLUMNS} FROM ingestion_job WHERE tenant_id = :t ORDER BY created_at DESC LIMIT :n"),
            {"t": str(tenant_id), "n": max(1, min(limit, 500))},
        )
        return [dict(r._mapping) for r in rows]


def transition(
    tenant_id: UUID,
    job_id: UUID,
    status: str,
    *,
    adapter_id: str | None = None,
    mapping_id: UUID | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    outcome: dict[str, Any] | None = None,
    total_rows_estimate: int | None = None,
    now: datetime,
) -> bool:
    """Move a job to `status` unless it is already terminal. Returns whether the row changed.
    `now` is explicit (no hidden clock); a start timestamp is set on the first non-QUEUED state, a finish
    timestamp on a terminal one."""
    if status not in _ALL:
        raise ValueError(f"unknown job status {status!r}")
    terminal = status in TERMINAL_STATES
    with tenant_scope(tenant_id) as conn:
        res = conn.execute(
            text(
                """
                UPDATE ingestion_job SET
                  status = :status,
                  adapter_id = COALESCE(:adapter_id, adapter_id),
                  mapping_id = COALESCE(:mapping_id, mapping_id),
                  error_code = COALESCE(:error_code, error_code),
                  error_detail = COALESCE(:error_detail, error_detail),
                  outcome = COALESCE(CAST(:outcome AS jsonb), outcome),
                  total_rows_estimate = COALESCE(:total, total_rows_estimate),
                  started_at = CASE WHEN started_at IS NULL AND :status <> 'QUEUED' THEN :now ELSE started_at END,
                  finished_at = CASE WHEN :terminal THEN :now ELSE finished_at END,
                  heartbeat_at = :now
                WHERE tenant_id = :t AND id = :id AND status NOT IN ('DONE','FAILED','CANCELLED')
                """
            ),
            {"status": status, "adapter_id": adapter_id, "mapping_id": str(mapping_id) if mapping_id else None,
             "error_code": error_code, "error_detail": error_detail,
             "outcome": json.dumps(outcome) if outcome is not None else None,
             "total": total_rows_estimate, "terminal": terminal, "now": now, "t": str(tenant_id), "id": str(job_id)},
        )
        return bool(res.rowcount)


def heartbeat(tenant_id: UUID, job_id: UUID, progress_rows: int, *, now: datetime) -> bool:
    with tenant_scope(tenant_id) as conn:
        res = conn.execute(
            text("UPDATE ingestion_job SET progress_rows = :p, heartbeat_at = :now WHERE tenant_id = :t AND id = :id AND status IN ('PARSING','VALIDATING','COMMITTING')"),
            {"p": progress_rows, "now": now, "t": str(tenant_id), "id": str(job_id)},
        )
        return bool(res.rowcount)


def is_cancelled(tenant_id: UUID, job_id: UUID) -> bool:
    with tenant_scope(tenant_id) as conn:
        s = conn.execute(text("SELECT status FROM ingestion_job WHERE tenant_id = :t AND id = :id"), {"t": str(tenant_id), "id": str(job_id)}).scalar_one_or_none()
    return s == "CANCELLED"


def request_cancel(tenant_id: UUID, job_id: UUID, *, now: datetime) -> bool:
    return transition(tenant_id, job_id, "CANCELLED", error_code="CANCELLED_BY_SELLER", now=now)


def recover_stale(tenant_id: UUID, *, stale_after_seconds: int, now: datetime) -> int:
    """Mark this tenant's active jobs whose heartbeat is older than the threshold as FAILED(INTERRUPTED).
    Their file transaction died with the worker, so nothing was posted (all-or-nothing); the seller may retry."""
    cutoff = now - timedelta(seconds=stale_after_seconds)
    with tenant_scope(tenant_id) as conn:
        res = conn.execute(
            text(
                """
                UPDATE ingestion_job SET status = 'FAILED', error_code = 'INTERRUPTED',
                  error_detail = 'The upload was interrupted before it finished. Nothing from it was saved; please upload it again.',
                  finished_at = :now
                WHERE tenant_id = :t AND status = ANY(CAST(:active AS text[]))
                  AND COALESCE(heartbeat_at, created_at) < :cutoff
                  AND status <> 'AWAITING_MAPPING_CONFIRMATION'
                """
            ),
            {"t": str(tenant_id), "active": list(ACTIVE_STATES), "cutoff": cutoff, "now": now},
        )
        return int(res.rowcount)


def claim(tenant_id: UUID, job_id: UUID, *, now: datetime) -> bool:
    """Atomically take a QUEUED job for processing (QUEUED -> PROFILING). Exactly one caller wins, so a double
    submit or two workers can never run the same job twice."""
    with tenant_scope(tenant_id) as conn:
        res = conn.execute(
            text("UPDATE ingestion_job SET status = 'PROFILING', started_at = COALESCE(started_at, :now), heartbeat_at = :now "
                 "WHERE tenant_id = :t AND id = :id AND status = 'QUEUED'"),
            {"now": now, "t": str(tenant_id), "id": str(job_id)},
        )
        return bool(res.rowcount)


def latest_job_for_file(tenant_id: UUID, report_file_id: UUID) -> dict[str, Any] | None:
    """The newest job of one uploaded file (any state) — how a repeated upload of the same bytes finds what happened last time."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(f"SELECT {_COLUMNS} FROM ingestion_job WHERE tenant_id = :t AND report_file_id = :f ORDER BY created_at DESC LIMIT 1"),
            {"t": str(tenant_id), "f": str(report_file_id)},
        ).first()
    return dict(row._mapping) if row else None
