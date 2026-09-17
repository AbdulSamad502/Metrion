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
