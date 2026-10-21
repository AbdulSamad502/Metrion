"""Atomic, memory-bounded ingestion from a `RowStream` (cfo-data-intelligence.md §6.3, D2, D3).

The old `ingest_and_persist` needed the whole file as one `RawFile`. This variant consumes bounded chunks
and writes each chunk inside ONE database transaction, so:

* memory is set by the chunk size, not by the file size;
* the file is still all-or-nothing — if the quarantine threshold (data-foundation.md §7.4) is exceeded at
  the end of the stream, or anything fails part-way, the transaction rolls back and no row of the file is
  persisted (spec AC-D5); the run is then marked FAILED rather than left PENDING;
* results are identical to the old path: the same adapter, the same per-row validation, the same
  natural-key dedup against *existing* rows, the same `source_row_number` (1-based over data rows, offset
  across chunks), the same persisted rows.

Real adapters only: this is the path for known, verified formats. Mapped (unfamiliar) formats feed rows
through the same persistence once a seller-confirmed mapping produces `ParsedRow`s.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from uuid import UUID

from calc_engine.types import Confidence

from data_foundation.adapters.registry import ADAPTER_REGISTRY
from data_foundation.ingestion.dedup import find_natural_key_duplicates
from data_foundation.ingestion.pipeline import (
    QUARANTINE_THRESHOLD,
    AdapterMismatchError,
    RunQuarantineThresholdExceeded,
    run_ingestion,
)
from data_foundation.ingestion.streaming import RowStream
from data_foundation.repositories import (
    ingestion_run_repo,
    sales_line_repo,
    settlement_line_repo,
    validation_finding_repo,
)
from data_foundation.repositories.tenant_context import tenant_scope
from data_foundation.types import FileSample, ParsedRow
from data_foundation.validation.severity import Finding

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StreamIngestionOutcome:
    ingestion_run_id: UUID
    row_count_read: int
    row_count_accepted: int
    row_count_rejected: int
    row_count_duplicate: int
    persisted_row_count: int
    blank_rows_skipped: int
    ragged_rows: int
    chunks: int


def _offset(row: ParsedRow, by: int) -> ParsedRow:
    return replace(row, source_row_number=row.source_row_number + by) if by else row


def _offset_finding(f: Finding, by: int) -> Finding:
    return replace(f, source_row_number=f.source_row_number + by) if (by and f.source_row_number is not None) else f


def ingest_stream_and_persist(
    tenant_id: UUID,
    *,
    report_file_id: UUID,
    adapter_id: str,
    stream: RowStream,
    started_at: datetime,
    on_progress: Callable[[int], None] | None = None,
    required_fields: tuple[str, ...] = (),
) -> StreamIngestionOutcome:
    adapter = ADAPTER_REGISTRY.get(adapter_id)
    if adapter is None:
        raise ValueError(f"unknown adapter_id {adapter_id!r} — not in ADAPTER_REGISTRY")
    if adapter.report_category not in ("TAX", "ORDER_STATUS", "SETTLEMENT"):
        raise ValueError(f"adapter {adapter_id!r} has unsupported report_category={adapter.report_category!r}")
    is_settlement = adapter.report_category == "SETTLEMENT"
    sample = FileSample(columns=stream.header.columns)

    run_id = ingestion_run_repo.insert_ingestion_run(
        tenant_id, report_file_id=report_file_id, adapter_id=adapter_id,
        adapter_version=adapter.format_version, started_at=started_at,
    )

    detection = adapter.detect(sample)
    if not detection.matched:
        ingestion_run_repo.mark_finished(
            tenant_id, run_id, status="MISMATCHED", row_count_read=0, row_count_accepted=0,
            row_count_rejected=0, finished_at=datetime.now(),
        )
        raise AdapterMismatchError(detection.missing_columns)

    read = accepted = rejected = duplicates = persisted = chunks = 0
    try:
        with tenant_scope(tenant_id) as conn:  # ONE transaction for the whole file
            for chunk in stream.chunks():
                chunks += 1
                offset = read
                result = run_ingestion(adapter, sample, chunk, required_fields=required_fields, enforce_quarantine_threshold=False)
                read += result.row_count_read
                rejected += result.row_count_rejected
                accepted += result.row_count_accepted

                ok_rows = [_offset(r.row, offset) for r in result.row_results if not r.quarantined]
                bad_findings = tuple(_offset_finding(f, offset) for r in result.row_results if r.quarantined for f in r.findings)

                if is_settlement:
                    # No natural-key dedup table for settlement_line yet (same disclosed simplification as the
                    # old path): file-level content-hash dedup is the guard.
                    dup_numbers: set[int] = set()
                else:
                    existing = sales_line_repo.existing_natural_keys_for_orders(
                        tenant_id, {r.canonical_fields.get("order_ref") for r in ok_rows}  # type: ignore[misc]
                    )
                    dup_numbers = set(find_natural_key_duplicates(adapter.marketplace, ok_rows, existing))
                to_persist = [r for r in ok_rows if r.source_row_number not in dup_numbers]
                duplicates += len(dup_numbers)

                if to_persist:
                    writer = (
                        settlement_line_repo.insert_settlement_lines_with_components_on
                        if is_settlement
                        else sales_line_repo.insert_sales_lines_with_components_on
                    )
                    persisted += len(
                        writer(conn, tenant_id, ingestion_run_id=run_id, marketplace=adapter.marketplace,
                               confidence=Confidence.PROVISIONAL.value, rows=to_persist)
                    )
                if bad_findings:
                    # Diagnostics never fail the import: a savepoint isolates a bad insert from the file's transaction.
                    try:
                        with conn.begin_nested():
                            validation_finding_repo.insert_findings_bulk_on(
                                conn, tenant_id, ingestion_run_id=run_id, findings=bad_findings
                            )
                    except Exception:  # noqa: BLE001
                        logger.exception("could not store rejected-row reasons for ingestion run %s", run_id)
                if on_progress is not None:
                    on_progress(read)

            if read > 0 and Fraction(rejected, read) > QUARANTINE_THRESHOLD:
                raise RunQuarantineThresholdExceeded(rejected, read)  # rolls the whole file back
    except Exception as exc:
        status = "QUARANTINE_EXCEEDED" if isinstance(exc, RunQuarantineThresholdExceeded) else "FAILED"
        try:
            ingestion_run_repo.mark_finished(
                tenant_id, run_id, status=status, row_count_read=read, row_count_accepted=0,
                row_count_rejected=rejected, finished_at=datetime.now(),
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not mark ingestion run %s %s", run_id, status)
        raise

    ingestion_run_repo.mark_finished(
        tenant_id, run_id, status="VALIDATED", row_count_read=read, row_count_accepted=accepted,
        row_count_rejected=rejected, finished_at=datetime.now(),
    )
    return StreamIngestionOutcome(
        ingestion_run_id=run_id, row_count_read=read, row_count_accepted=accepted, row_count_rejected=rejected,
        row_count_duplicate=duplicates, persisted_row_count=persisted, blank_rows_skipped=stream.stats.blank_rows_skipped,
        ragged_rows=stream.stats.ragged_rows, chunks=chunks,
    )
