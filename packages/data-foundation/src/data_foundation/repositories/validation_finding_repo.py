"""validation_finding repository — data-foundation.md §4.4 (new table, Category C amendment)."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope
from data_foundation.validation.severity import Finding

_INSERT_SQL = text(
    """
    INSERT INTO validation_finding
        (id, tenant_id, ingestion_run_id, sales_line_id, rule_id, severity, message, source_row_number)
    VALUES
        (:id, :tenant_id, :ingestion_run_id, :sales_line_id, :rule_id, :severity, :message, :source_row_number)
    """
)

_COUNTS_BY_SEVERITY_SQL = text(
    "SELECT severity, count(*) FROM validation_finding WHERE ingestion_run_id = :ingestion_run_id GROUP BY severity"
)


def insert_findings(tenant_id: UUID, *, ingestion_run_id: UUID, sales_line_id: UUID | None, findings: tuple[Finding, ...]) -> None:
    with tenant_scope(tenant_id) as conn:
        for finding in findings:
            conn.execute(
                _INSERT_SQL,
                {
                    "id": str(uuid4()),
                    "tenant_id": str(tenant_id),
                    "ingestion_run_id": str(ingestion_run_id),
                    "sales_line_id": str(sales_line_id) if sales_line_id else None,
                    "rule_id": finding.rule_id,
                    "severity": finding.severity.value,
                    "message": finding.message,
                    "source_row_number": finding.source_row_number,
                },
            )


def counts_by_severity(tenant_id: UUID, ingestion_run_id: UUID) -> dict[str, int]:
    """§4.3's Data Quality Report: "counts by severity" — the exact aggregate that composes
    into the §7.3 disclosure sentence, e.g. "Based on 38 of 40 rows. 2 rows excluded...".
    Composing that sentence is a caller-side concern; this returns only the counts."""
    with tenant_scope(tenant_id) as conn:
        return {row[0]: row[1] for row in conn.execute(_COUNTS_BY_SEVERITY_SQL, {"ingestion_run_id": str(ingestion_run_id)})}
