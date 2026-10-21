"""Atomic, memory-bounded ingestion from a `RowStream` (cfo-data-intelligence.md §6.3, D2, D3).

The legacy `ingest_and_persist` needed the whole file as one `RawFile`. This variant consumes bounded chunks
and writes each chunk inside ONE database transaction, so:

* memory is set by the chunk size (plus one small digest per distinct row identity), not by the file size;
* the file is all-or-nothing: if the quarantine threshold (data-foundation.md §7.4) is exceeded at the end
  of the stream, or anything fails part-way, the transaction rolls back and no row of the file is persisted
  (spec AC-D5); the run is then marked FAILED / QUARANTINE_EXCEEDED rather than left PENDING;
* **duplicates are classified before posting** (spec §6.3): exact overlap with earlier uploads and exact
  repeats inside the file are skipped and counted; conflicting versions and unexplainable repeats are HELD
  with a plain-language finding; legitimate repeats (partial settlements, adjustments, two items of one
  order) are posted. Held rows are excluded from the quarantine-threshold ratio;
* otherwise the result matches the legacy path: same adapter, same per-row validation, same
  `source_row_number` (1-based over data rows, offset across chunks), same persisted rows.

This is the path for known, verified formats. Mapped (unfamiliar) formats feed rows through the same
persistence once a seller-confirmed mapping produces `ParsedRow`s.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from uuid import UUID

from calc_engine.types import Confidence
from sqlalchemy import Connection

from data_foundation.adapters.registry import ADAPTER_REGISTRY
from data_foundation.ingestion.duplicates import SALES, SETTLEMENT, DupClass, DuplicateTracker
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
from data_foundation.types import FileSample, MarketplaceAdapter, ParsedRow
from data_foundation.validation.severity import Finding

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StreamIngestionOutcome:
    ingestion_run_id: UUID
    row_count_read: int
    row_count_accepted: int  # passed row validation (not quarantined)
    row_count_rejected: int  # failed row validation (quarantined) — the only rows that count toward the threshold
    row_count_duplicate: int  # exact duplicates skipped (cross-file overlap + in-file repeats)
    duplicates_cross_file: int
    duplicates_in_file: int
    held_conflicts: int  # same identity, different content — held, not posted
    held_ambiguous: int  # identical repeats that cannot be told from a double export — held, not posted
    persisted_row_count: int
    blank_rows_skipped: int
    ragged_rows: int
    chunks: int


def _offset(row: ParsedRow, by: int) -> ParsedRow:
    return replace(row, source_row_number=row.source_row_number + by) if by else row


def _offset_finding(f: Finding, by: int) -> Finding:
    return replace(f, source_row_number=f.source_row_number + by) if (by and f.source_row_number is not None) else f


def _existing_entries(tenant_id: UUID, marketplace: str, is_settlement: bool, rows: list[ParsedRow]):  # type: ignore[no-untyped-def]
    if is_settlement:
        return settlement_line_repo.existing_entries_for(
            tenant_id, marketplace,
            order_refs={r.canonical_fields.get("order_ref") for r in rows},  # type: ignore[misc]
            line_refs={r.canonical_fields.get("line_ref") for r in rows},  # type: ignore[misc]
            settlement_ids={r.canonical_fields.get("settlement_id") for r in rows},  # type: ignore[misc]
        )
    return sales_line_repo.existing_entries_for_orders(
        tenant_id, marketplace, {r.canonical_fields.get("order_ref") for r in rows}  # type: ignore[misc]
    )


def ingest_stream_and_persist(
    tenant_id: UUID,
    *,
    report_file_id: UUID,
    adapter_id: str,
    stream: RowStream,
    started_at: datetime,
    on_progress: Callable[[int], None] | None = None,
    required_fields: tuple[str, ...] = (),
    adapter: MarketplaceAdapter | None = None,
    in_transaction: Callable[[Connection], None] | None = None,
) -> StreamIngestionOutcome:
    """`adapter` overrides the registry lookup (a seller-confirmed mapped adapter). `in_transaction` runs inside the
    file's transaction after the threshold check, and only when something was posted: it bumps the read-model version
    so new data and its cache-invalidating version commit together or not at all."""
    if adapter is None:
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

    tracker = DuplicateTracker(SETTLEMENT if is_settlement else SALES, adapter.marketplace)
    read = accepted = rejected = persisted = chunks = 0
    dup_cross = dup_in_file = held_conflicts = held_ambiguous = 0
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
                findings: list[Finding] = [
                    _offset_finding(f, offset) for r in result.row_results if r.quarantined for f in r.findings
                ]

                decisions = tracker.classify(ok_rows, _existing_entries(tenant_id, adapter.marketplace, is_settlement, ok_rows))
                to_persist: list[ParsedRow] = []
                for row, d in zip(ok_rows, decisions):
                    if d.klass is DupClass.NEW:
                        to_persist.append(row)
                    elif d.klass is DupClass.EXACT_DUPLICATE_CROSS_FILE:
                        dup_cross += 1
                    elif d.klass is DupClass.EXACT_DUPLICATE_IN_FILE:
                        dup_in_file += 1
                    elif d.klass is DupClass.AMBIGUOUS_REPEAT:
                        held_ambiguous += 1
                    else:
                        held_conflicts += 1
                    if d.finding is not None:
                        findings.append(d.finding)

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
                if findings:
                    # Diagnostics never fail the import: a savepoint isolates a bad insert from the file's transaction.
                    try:
                        with conn.begin_nested():
                            validation_finding_repo.insert_findings_bulk_on(
                                conn, tenant_id, ingestion_run_id=run_id, findings=tuple(findings)
                            )
                    except Exception:  # noqa: BLE001
                        logger.exception("could not store row findings for ingestion run %s", run_id)
                if on_progress is not None:
                    on_progress(read)

            # Held duplicates are not validation failures: only rows that failed validation count toward the threshold.
            if read > 0 and Fraction(rejected, read) > QUARANTINE_THRESHOLD:
                raise RunQuarantineThresholdExceeded(rejected, read)  # rolls the whole file back
            if persisted and in_transaction is not None:
                in_transaction(conn)
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
        row_count_duplicate=dup_cross + dup_in_file, duplicates_cross_file=dup_cross, duplicates_in_file=dup_in_file,
        held_conflicts=held_conflicts, held_ambiguous=held_ambiguous, persisted_row_count=persisted,
        blank_rows_skipped=stream.stats.blank_rows_skipped, ragged_rows=stream.stats.ragged_rows, chunks=chunks,
    )
