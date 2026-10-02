"""ingestion_run repository — data-foundation.md §1.3 (+ Category C tenant_id amendment)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO ingestion_run
        (id, tenant_id, report_file_id, adapter_id, adapter_version, status,
         row_count_read, row_count_accepted, row_count_rejected, started_at, finished_at)
    VALUES
        (:id, :tenant_id, :report_file_id, :adapter_id, :adapter_version, :status,
         :row_count_read, :row_count_accepted, :row_count_rejected, :started_at, :finished_at)
    """
)

_UPDATE_STATUS_SQL = text(
    """
    UPDATE ingestion_run
    SET status = :status, row_count_read = :row_count_read, row_count_accepted = :row_count_accepted,
        row_count_rejected = :row_count_rejected, finished_at = :finished_at
    WHERE id = :id
    """
)

_SUPERSEDE_SQL = text("UPDATE ingestion_run SET status = 'SUPERSEDED' WHERE report_file_id = :report_file_id AND id != :new_run_id")


def insert_ingestion_run(
    tenant_id: UUID,
    *,
    report_file_id: UUID,
    adapter_id: str,
    adapter_version: str,
    started_at: datetime,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(new_id),
                "tenant_id": str(tenant_id),
                "report_file_id": str(report_file_id),
                "adapter_id": adapter_id,
                "adapter_version": adapter_version,
                "status": "PENDING",
                "row_count_read": None,
                "row_count_accepted": None,
                "row_count_rejected": None,
                "started_at": started_at,
                "finished_at": None,
            },
        )
    return new_id


def mark_finished(
    tenant_id: UUID,
    run_id: UUID,
    *,
    status: str,
    row_count_read: int,
    row_count_accepted: int,
    row_count_rejected: int,
    finished_at: datetime,
    supersede_previous_runs: bool = True,
) -> None:
    """§1.3: a new run against the same report_file supersedes the previous one, prior rows
    retained for audit (§3.1 rule 4) — supersession is a status flip, never a delete."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _UPDATE_STATUS_SQL,
            {
                "id": str(run_id),
                "status": status,
                "row_count_read": row_count_read,
                "row_count_accepted": row_count_accepted,
                "row_count_rejected": row_count_rejected,
                "finished_at": finished_at,
            },
        )
        if supersede_previous_runs and status == "VALIDATED":
            row = conn.execute(text("SELECT report_file_id FROM ingestion_run WHERE id = :id"), {"id": str(run_id)}).first()
            if row is not None:
                conn.execute(_SUPERSEDE_SQL, {"report_file_id": str(row[0]), "new_run_id": str(run_id)})


_LATEST_FOR_FILE_SQL = text(
    """
    SELECT id, report_file_id, adapter_id, adapter_version, status, row_count_read,
           row_count_accepted, row_count_rejected, started_at, finished_at
    FROM ingestion_run
    WHERE tenant_id = :tenant_id AND report_file_id = :report_file_id
    ORDER BY started_at DESC NULLS LAST
    LIMIT 1
    """
)


def latest_run_for_report_file(tenant_id: UUID, report_file_id: UUID) -> dict[str, object] | None:
    """The most recent ingestion run of a report file (read-only; never creates a run)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _LATEST_FOR_FILE_SQL, {"tenant_id": str(tenant_id), "report_file_id": str(report_file_id)}
        ).mappings().first()
        return dict(row) if row is not None else None
