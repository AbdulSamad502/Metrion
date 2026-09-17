"""report_period repository — data-foundation.md §6 (+ Category C tenant_id amendment)."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO report_period
        (id, tenant_id, report_file_id, period_start, period_end, source,
         declared_filing_month, declared_filing_year)
    VALUES
        (:id, :tenant_id, :report_file_id, :period_start, :period_end, :source,
         :declared_filing_month, :declared_filing_year)
    """
)


def insert_report_period(
    tenant_id: UUID,
    *,
    report_file_id: UUID,
    period_start: date,
    period_end: date,
    source: str,
    declared_filing_month: int | None = None,
    declared_filing_year: int | None = None,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(new_id),
                "tenant_id": str(tenant_id),
                "report_file_id": str(report_file_id),
                "period_start": period_start,
                "period_end": period_end,
                "source": source,
                "declared_filing_month": declared_filing_month,
                "declared_filing_year": declared_filing_year,
            },
        )
    return new_id
