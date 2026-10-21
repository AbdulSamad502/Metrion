"""report_file repository — data-foundation.md §1.3, §3.1."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO report_file
        (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
         byte_size, storage_uri, uploaded_by, uploaded_at)
    VALUES
        (:id, :tenant_id, :marketplace, :report_category, :content_sha256, :original_filename,
         :byte_size, :storage_uri, :uploaded_by, :uploaded_at)
    """
)

_EXISTING_HASHES_SQL = text("SELECT content_sha256 FROM report_file WHERE tenant_id = :tenant_id")

_BY_HASH_SQL = text("SELECT id FROM report_file WHERE tenant_id = :tenant_id AND content_sha256 = :content_sha256")


def insert_report_file(
    tenant_id: UUID,
    *,
    marketplace: str,
    report_category: str,
    content_sha256: str,
    original_filename: str,
    byte_size: int,
    storage_uri: str,
    uploaded_by: UUID,
    uploaded_at: datetime,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(new_id),
                "tenant_id": str(tenant_id),
                "marketplace": marketplace,
                "report_category": report_category,
                "content_sha256": content_sha256,
                "original_filename": original_filename,
                "byte_size": byte_size,
                "storage_uri": storage_uri,
                "uploaded_by": str(uploaded_by),
                "uploaded_at": uploaded_at,
            },
        )
    return new_id


def existing_content_hashes(tenant_id: UUID) -> list[str]:
    """Feeds `ingestion.dedup.is_duplicate_file()` — never queried without tenant scope."""
    with tenant_scope(tenant_id) as conn:
        return [row[0] for row in conn.execute(_EXISTING_HASHES_SQL, {"tenant_id": str(tenant_id)})]


def find_by_content_hash(tenant_id: UUID, content_sha256: str) -> UUID | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_BY_HASH_SQL, {"tenant_id": str(tenant_id), "content_sha256": content_sha256}).first()
        return UUID(str(row[0])) if row is not None else None


# --- Read side: the import viewer (GET /cfo/imports*). ----------------------------------------
# Deliberately never selects `storage_uri` — an internal filesystem location is not something a
# client should ever see, and nothing in the viewer needs it.

_GET_SQL = text(
    """
    SELECT id, marketplace, report_category, original_filename, byte_size, uploaded_at
    FROM report_file
    WHERE tenant_id = :tenant_id AND id = :report_file_id
    """
)

_LIST_SQL = text(
    """
    SELECT f.id, f.marketplace, f.report_category, f.original_filename, f.byte_size, f.uploaded_at,
           r.id AS run_id, r.adapter_id, r.adapter_version, r.status, r.row_count_read,
           r.row_count_accepted, r.row_count_rejected, r.started_at, r.finished_at
    FROM report_file f
    LEFT JOIN LATERAL (
        SELECT * FROM ingestion_run
        WHERE ingestion_run.report_file_id = f.id AND ingestion_run.tenant_id = :tenant_id
        ORDER BY started_at DESC NULLS LAST
        LIMIT 1
    ) r ON TRUE
    WHERE f.tenant_id = :tenant_id
    ORDER BY f.uploaded_at DESC
    LIMIT :limit
    """
)


def get_report_file(tenant_id: UUID, report_file_id: UUID) -> dict[str, object] | None:
    """One report_file of this tenant (None when it does not exist OR belongs to another tenant —
    the two are deliberately indistinguishable)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_GET_SQL, {"tenant_id": str(tenant_id), "report_file_id": str(report_file_id)}).mappings().first()
        return dict(row) if row is not None else None


def list_report_files_with_latest_run(tenant_id: UUID, *, limit: int = 100) -> list[dict[str, object]]:
    """This tenant's imports, newest first, each joined to its latest ingestion run (if any)."""
    with tenant_scope(tenant_id) as conn:
        return [dict(r) for r in conn.execute(_LIST_SQL, {"tenant_id": str(tenant_id), "limit": limit}).mappings()]


def get_report_file_for_ingestion(tenant_id: UUID, report_file_id: UUID) -> dict[str, object] | None:
    """The stored facts a worker needs to read an upload back: where it is stored and its content hash. Kept apart
    from `get_report_file` so the seller-facing read never exposes a storage location."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT id, marketplace, report_category, content_sha256, original_filename, storage_uri "
                 "FROM report_file WHERE tenant_id = :t AND id = :id"),
            {"t": str(tenant_id), "id": str(report_file_id)},
        ).mappings().first()
        return dict(row) if row is not None else None
