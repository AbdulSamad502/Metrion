"""Manual end-to-end trace: one small constructed Meesho tcs_sales_return.v1 sample, through
detect -> parse -> validate -> persist, then read back through calc-engine's
canonical_repo.py — the first time that repository's queries run against a real row, closing
the cross-package gap it has been flagging since calc-engine's Category B
("not runtime-tested — sales_line and line_component ... no migration for them exists").

Requires DATABASE_URL / DATABASE_URL_APP pointed at a live Postgres with both packages'
migrations applied.

**Honesty note on `dispatch_date`:** no adapter built this pass has a spec-confirmed literal
header for any date column (see adapters/base.py's module docstring) — the real pipeline
therefore cannot itself produce a document date yet. This script sets one manually on the
persisted row, exactly as a future date-column mapping would, so the read-back path can be
demonstrated end-to-end; it does not claim the adapter derived it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from calc_engine.repositories.canonical_repo import components_for_lines, sales_lines_in_period

from data_foundation.adapters.meesho_tcs_sales_return_v1 import adapter
from data_foundation.ingestion.pipeline import run_ingestion
from data_foundation.repositories.ingestion_run_repo import insert_ingestion_run, mark_finished
from data_foundation.repositories.line_component_repo import insert_components
from data_foundation.repositories.report_file_repo import insert_report_file
from data_foundation.repositories.sales_line_repo import insert_sales_line
from data_foundation.repositories.validation_finding_repo import insert_findings
from data_foundation.types import FileSample, RawFile

TENANT_ID = uuid.uuid4()


def step(label: str, value: object) -> None:
    print(f"{label}: {value}")


COLUMNS = ("Sub Order No", "total_taxable_sale_value", "cancel_return")
ROW = {"Sub Order No": "SUB123", "total_taxable_sale_value": "-372.06", "cancel_return": "15-Sep-25"}

print("-- 1. detect() --")
sample = FileSample(columns=COLUMNS)
detection = adapter.detect(sample)
step("matched", detection.matched)
step("missing_columns", detection.missing_columns)

print("\n-- 2. parse() + validate() (ingestion.pipeline.run_ingestion) --")
raw = RawFile(columns=COLUMNS, rows=[ROW])
result = run_ingestion(adapter, sample, raw)
row_result = result.row_results[0]
step("canonical_fields", row_result.row.canonical_fields)
step("confidence", row_result.confidence)
step("findings", row_result.findings)
step("quarantined", row_result.quarantined)

print("\n-- 3. persist (report_file -> ingestion_run -> sales_line -> line_component) --")
now = datetime.now(timezone.utc)
file_id = insert_report_file(
    TENANT_ID,
    marketplace="MEESHO",
    report_category="TAX",
    content_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
    original_filename="tcs_sales_return_demo.csv",
    byte_size=len(str(ROW)),
    storage_uri="s3://demo-bucket/tcs_sales_return_demo.csv",
    uploaded_by=uuid.uuid4(),
    uploaded_at=now,
)
step("report_file_id", file_id)

run_id = insert_ingestion_run(TENANT_ID, report_file_id=file_id, adapter_id=adapter.adapter_id, adapter_version=adapter.format_version, started_at=now)
step("ingestion_run_id", run_id)

canonical_fields = dict(row_result.row.canonical_fields)
canonical_fields["dispatch_date"] = date(2026, 9, 15)  # manual demo augmentation — see module docstring
line_id = insert_sales_line(
    TENANT_ID,
    ingestion_run_id=run_id,
    marketplace="MEESHO",
    canonical_fields=canonical_fields,
    source_row_number=row_result.row.source_row_number,
    source_row_json=row_result.row.source_row_json,
    confidence=row_result.confidence.value,
)
step("sales_line_id", line_id)

component_ids = insert_components(TENANT_ID, sales_line_id=line_id, components=row_result.row.components)
step("line_component_ids", component_ids)

insert_findings(TENANT_ID, ingestion_run_id=run_id, sales_line_id=line_id, findings=row_result.findings)
mark_finished(TENANT_ID, run_id, status="VALIDATED", row_count_read=1, row_count_accepted=1, row_count_rejected=0, finished_at=datetime.now(timezone.utc))

print("\n-- 4. read back via calc-engine's canonical_repo.py --")
lines = sales_lines_in_period(TENANT_ID, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
step("sales_lines_in_period() row count", len(lines))
step("sales_lines_in_period()[0]", lines[0] if lines else None)

if lines:
    components = components_for_lines(TENANT_ID, sales_line_ids=[lines[0]["sales_line_id"]])
    step("components_for_lines() row count", len(components))
    for c in components:
        step("  component", c)

print(
    "\nThis is the first time canonical_repo.py's queries have run against a real row — "
    "closing the gap flagged in its own docstring since calc-engine's Category B."
)
