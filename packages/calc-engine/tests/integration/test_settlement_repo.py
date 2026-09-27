"""`settlement_repo.settlement_lines_in_period` / `components_for_settlement_lines` against a
real Postgres — mirrors `test_fee_reference_config_repo.py`'s seed-via-real-SQL,
read-via-real-function pattern.

**Status (updated 2026-09-24):** `settlement_line` is data-foundation-owned
(data-foundation.md §5.6/§5.7). Its migration
(`packages/data-foundation/migrations/versions/20260924_0002_settlement_line.py`) has landed
and was applied to the shared dev Postgres (`alembic upgrade head` in
`packages/data-foundation`, verified independently) — this package and data-foundation share
one Postgres instance (`packages/data-foundation/migrations/README.md`), so the table exists
here too. Un-skipped and run for real; no longer structurally-complete-only."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from calc_engine.repositories import settlement_repo
from calc_engine.repositories.tenant_context import tenant_scope

pytestmark = [pytest.mark.usefixtures("_clean_engine_tables")]


def _insert_ingestion_run(conn, *, tenant_id) -> uuid.UUID:
    """settlement_line.ingestion_run_id is a real FK to ingestion_run, which is itself a real
    FK to report_file (data-foundation.md §1.3) — both must exist first. Mirrors
    data-foundation's own test_rls_isolation.py fixture chain exactly."""
    file_id = uuid.uuid4()
    conn.execute(
        text(
            """
            INSERT INTO report_file
                (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                 byte_size, storage_uri, uploaded_by, uploaded_at)
            VALUES
                (:id, :tenant_id, 'MEESHO', 'SETTLEMENT', :sha, 'payments.xlsx', 100,
                 's3://bucket/x', :uploaded_by, :uploaded_at)
            """
        ),
        {
            "id": str(file_id),
            "tenant_id": str(tenant_id),
            "sha": uuid.uuid4().hex + uuid.uuid4().hex,
            "uploaded_by": str(uuid.uuid4()),
            "uploaded_at": datetime.now(timezone.utc),
        },
    )
    run_id = uuid.uuid4()
    conn.execute(
        text(
            """
            INSERT INTO ingestion_run (id, tenant_id, report_file_id, adapter_id, adapter_version, status)
            VALUES (:id, :tenant_id, :report_file_id, 'meesho.payments.v1', 'v1', 'PENDING')
            """
        ),
        {"id": str(run_id), "tenant_id": str(tenant_id), "report_file_id": str(file_id)},
    )
    return run_id


def _insert_settlement_line(
    *,
    tenant_id,
    marketplace="MEESHO",
    order_ref="SUB1",
    line_ref=None,
    gross_settlement_amount=6_500,
    settlement_date_="2026-09-10",
    confidence="VERIFIED",
):
    """settlement_line carries real per-tenant FORCE RLS (mirrored from sales_line, §5.6) —
    unlike calc-engine's own platform/nullable-tenant config tables, inserting here requires
    `tenant_scope()` (sets `app.current_tenant_id`), not a bare `migrate_engine` connection.
    Mirrors data-foundation's own `test_rls_isolation.py::_insert_report_file` exactly."""
    settlement_line_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        ingestion_run_id = _insert_ingestion_run(conn, tenant_id=tenant_id)
        conn.execute(
            text(
                """
                INSERT INTO settlement_line
                    (id, tenant_id, ingestion_run_id, marketplace, order_ref, line_ref,
                     settlement_id, gross_settlement_amount, currency, settlement_date,
                     document_type, source_row_number, source_row_json, confidence)
                VALUES
                    (:id, :tenant_id, :ingestion_run_id, :marketplace, :order_ref, :line_ref,
                     NULL, :gross_settlement_amount, 'INR', :settlement_date,
                     'Order Payments', 1, '{}'::jsonb, :confidence)
                """
            ),
            {
                "id": str(settlement_line_id),
                "tenant_id": str(tenant_id),
                "ingestion_run_id": str(ingestion_run_id),
                "marketplace": marketplace,
                "order_ref": order_ref,
                "line_ref": line_ref,
                "gross_settlement_amount": gross_settlement_amount,
                "settlement_date": settlement_date_,
                "confidence": confidence,
            },
        )
    return settlement_line_id


def test_settlement_lines_in_period_filters_on_settlement_date(two_tenants):
    tenant_a, _ = two_tenants
    _insert_settlement_line(tenant_id=tenant_a, settlement_date_="2026-09-10")
    _insert_settlement_line(tenant_id=tenant_a, settlement_date_="2026-11-01")

    rows = settlement_repo.settlement_lines_in_period(
        tenant_a, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)
    )
    assert len(rows) == 1
    assert rows[0]["settlement_date"] == date(2026, 9, 10)


def test_settlement_lines_in_period_excludes_null_settlement_date(two_tenants):
    tenant_a, _ = two_tenants
    _insert_settlement_line(tenant_id=tenant_a, settlement_date_=None)

    rows = settlement_repo.settlement_lines_in_period(
        tenant_a, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31)
    )
    assert rows == []


def test_components_for_settlement_lines_filters_source_side(two_tenants):
    tenant_a, _ = two_tenants
    settlement_line_id = _insert_settlement_line(tenant_id=tenant_a)
    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, NULL, :settlement_line_id, 'FEE', 'COMMISSION',
                     'SETTLEMENT', 6500, NULL, NULL, 'Settlement Commission', false, NULL)
                """
            ),
            {"id": str(uuid.uuid4()), "tenant_id": str(tenant_a), "settlement_line_id": str(settlement_line_id)},
        )

    rows = settlement_repo.components_for_settlement_lines(tenant_a, settlement_line_ids=[settlement_line_id])
    assert len(rows) == 1
    assert rows[0]["source_side"] == "SETTLEMENT"


def test_components_for_settlement_lines_empty_ids_returns_empty(two_tenants):
    tenant_a, _ = two_tenants
    assert settlement_repo.components_for_settlement_lines(tenant_a, settlement_line_ids=[]) == []
