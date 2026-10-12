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


def insert_findings_bulk(tenant_id: UUID, *, ingestion_run_id: UUID, findings: tuple[Finding, ...]) -> int:
    """Run-level / not-yet-linked findings (`sales_line_id` NULL), written with one statement and one transaction for the whole batch — a rejected row has no sales_line to
    link to, so its finding is identified by `source_row_number`. Returns how many were written."""
    if not findings:
        return 0
    rows = [
        {
            "id": str(uuid4()),
            "tenant_id": str(tenant_id),
            "ingestion_run_id": str(ingestion_run_id),
            "sales_line_id": None,
            "rule_id": f.rule_id,
            "severity": f.severity.value,
            "message": f.message,
            "source_row_number": f.source_row_number,
        }
        for f in findings
    ]
    with tenant_scope(tenant_id) as conn:
        conn.execute(_INSERT_SQL, rows)
    return len(rows)


def counts_by_severity(tenant_id: UUID, ingestion_run_id: UUID) -> dict[str, int]:
    """§4.3's Data Quality Report: "counts by severity" — the exact aggregate that composes
    into the §7.3 disclosure sentence, e.g. "Based on 38 of 40 rows. 2 rows excluded...".
    Composing that sentence is a caller-side concern; this returns only the counts."""
    with tenant_scope(tenant_id) as conn:
        return {row[0]: row[1] for row in conn.execute(_COUNTS_BY_SEVERITY_SQL, {"ingestion_run_id": str(ingestion_run_id)})}


_COUNT_FOR_RUN_SQL = text("SELECT count(*) FROM validation_finding WHERE tenant_id = :tenant_id AND ingestion_run_id = :ingestion_run_id")

_PAGE_FOR_RUN_SQL = text(
    """
    SELECT rule_id, severity, message, source_row_number
    FROM validation_finding
    WHERE tenant_id = :tenant_id AND ingestion_run_id = :ingestion_run_id
    ORDER BY source_row_number NULLS LAST, rule_id
    LIMIT :limit OFFSET :offset
    """
)


def count_for_run(tenant_id: UUID, ingestion_run_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        return int(
            conn.execute(_COUNT_FOR_RUN_SQL, {"tenant_id": str(tenant_id), "ingestion_run_id": str(ingestion_run_id)}).scalar_one()
        )


def page_for_run(tenant_id: UUID, ingestion_run_id: UUID, *, limit: int, offset: int) -> list[dict[str, object]]:
    """Persisted validation findings of a run. NOTE: the live upload path does not persist
    findings today (`ingest_and_persist` never calls `insert_findings`), so for a normal upload
    this is empty — callers must say so rather than imply rejections have no reason."""
    with tenant_scope(tenant_id) as conn:
        return [
            dict(r)
            for r in conn.execute(
                _PAGE_FOR_RUN_SQL,
                {"tenant_id": str(tenant_id), "ingestion_run_id": str(ingestion_run_id), "limit": limit, "offset": offset},
            ).mappings()
        ]
