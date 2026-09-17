"""RLS fail-closed verification against a real Postgres, connected as metrion_app — same
standard already applied to calc-engine's Category B."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope


def _insert_report_file(tenant_id: uuid.UUID, filename: str) -> uuid.UUID:
    file_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_file
                    (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                     byte_size, storage_uri, uploaded_by, uploaded_at)
                VALUES
                    (:id, :tenant_id, 'MEESHO', 'TAX', :sha, :filename, 100, 's3://bucket/x', :uploaded_by, :uploaded_at)
                """
            ),
            {
                "id": str(file_id),
                "tenant_id": str(tenant_id),
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,  # 64 hex chars, distinct per call
                "filename": filename,
                "uploaded_by": str(uuid.uuid4()),
                "uploaded_at": datetime.now(timezone.utc),
            },
        )
    return file_id


def test_tenant_cannot_see_another_tenants_report_file(two_tenants):
    tenant_a, tenant_b = two_tenants
    _insert_report_file(tenant_a, "a.csv")
    _insert_report_file(tenant_b, "b.csv")

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT original_filename FROM report_file")).fetchall()
    assert [r[0] for r in rows] == ["a.csv"]


def test_tenant_context_none_raises_before_any_query():
    with pytest.raises(ValueError, match="tenant_id=None"):
        with tenant_scope(None):
            pytest.fail("must raise before yielding a connection")


def test_unset_session_context_yields_zero_rows(two_tenants, app_engine):
    tenant_a, _ = two_tenants
    _insert_report_file(tenant_a, "a.csv")
    with app_engine.connect() as conn:
        rows = conn.execute(text("SELECT original_filename FROM report_file")).fetchall()
    assert rows == []


def test_tenant_cannot_write_a_row_under_another_tenants_id(two_tenants):
    tenant_a, tenant_b = two_tenants
    with pytest.raises(Exception):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO report_file
                        (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                         byte_size, storage_uri, uploaded_by, uploaded_at)
                    VALUES
                        (:id, :tenant_id, 'MEESHO', 'TAX', :sha, 'spoof.csv', 1, 's3://x', :uploaded_by, now())
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_b),  # spoofed
                    "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                    "uploaded_by": str(uuid.uuid4()),
                },
            )


def test_isolation_holds_across_the_full_report_file_to_line_component_chain(two_tenants):
    """Cross-tenant isolation must hold at every level of the hierarchy, not just the top."""
    tenant_a, tenant_b = two_tenants
    file_id = _insert_report_file(tenant_a, "a.csv")
    with tenant_scope(tenant_a) as conn:
        run_id = uuid.uuid4()
        conn.execute(
            text(
                """
                INSERT INTO ingestion_run (id, tenant_id, report_file_id, adapter_id, adapter_version, status)
                VALUES (:id, :tenant_id, :report_file_id, 'meesho.orders.v1', 'v1', 'PENDING')
                """
            ),
            {"id": str(run_id), "tenant_id": str(tenant_a), "report_file_id": str(file_id)},
        )
        line_id = uuid.uuid4()
        conn.execute(
            text(
                """
                INSERT INTO sales_line (id, tenant_id, ingestion_run_id, marketplace, source_row_number, source_row_json, confidence)
                VALUES (:id, :tenant_id, :run_id, 'MEESHO', 1, '{}'::jsonb, 'PROVISIONAL')
                """
            ),
            {"id": str(line_id), "tenant_id": str(tenant_a), "run_id": str(run_id)},
        )

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT id FROM sales_line")).fetchall()
    assert rows == []
