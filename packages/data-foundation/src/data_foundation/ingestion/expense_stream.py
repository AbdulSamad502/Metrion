"""Atomic, memory-bounded expense-file ingestion into the expense ledger (docs/specs/cfo-expense-ledger.md §6.1, cfo-data-intelligence.md AC-D11).

A seller-confirmed mapping (`report_kind=EXPENSE`) turns each row into a ledger entry. The whole file is ONE transaction (all-or-nothing, like the
order and settlement paths): an exact repeat is skipped and counted, a possible duplicate or a marketplace-deduction-like category is stored on hold
(excluded from every total until the seller resolves it), a row that cannot be read is rejected with its reason, and when too many rows are rejected the
whole file rolls back. The read-model version is bumped by the ledger write itself, inside the same transaction.

Amounts are taken exactly as entered (spec E5/A2): no GST is extracted or assumed; a mapped GST column is stored beside the amount with its treatment
unconfirmed, and the quality report says so.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from fractions import Fraction
from uuid import UUID

from calc_engine.expense_ledger import LedgerRuleError, NewEntry, validate_new_entry
from calc_engine.repositories import expense_ledger_repo

from data_foundation.ingestion.pipeline import QUARANTINE_THRESHOLD, RunQuarantineThresholdExceeded
from data_foundation.ingestion.streaming import RowStream
from data_foundation.repositories import ingestion_run_repo
from data_foundation.repositories.tenant_context import tenant_scope
from data_foundation.types import MarketplaceAdapter, ParsedRow

logger = logging.getLogger(__name__)

MAX_REJECTION_EXAMPLES = 25


@dataclass(frozen=True, slots=True)
class ExpenseIngestionOutcome:
    ingestion_run_id: UUID
    row_count_read: int
    posted: int  # new ledger rows (including those stored on hold)
    held_possible_duplicates: int
    held_overlap: int
    skipped_exact_duplicates: int
    rejected: int
    rejection_examples: tuple[tuple[int, str], ...]  # (source row number, plain reason), capped
    gst_unconfirmed: int  # rows carrying a GST amount whose treatment is not confirmed
    categories: tuple[str, ...]  # distinct categories posted, for class suggestions after commit
    blank_rows_skipped: int
    ragged_rows: int
    chunks: int
    held_ids: tuple[str, ...] = field(default=())


def _entry_from_row(row: ParsedRow, run_id: UUID) -> NewEntry:
    c = row.canonical_fields

    def text(name: str) -> str | None:
        v = c.get(name)
        return None if v is None else str(v)

    d = c.get("expense_date")
    amount = c.get("expense_amount")
    category = text("expense_category")
    if not isinstance(d, date):
        raise LedgerRuleError("the expense date is missing")
    if category is None or not category.strip():
        raise LedgerRuleError("the expense category is missing")
    if amount is None or isinstance(amount, bool) or not isinstance(amount, int):
        raise LedgerRuleError("the expense amount is missing")
    paid = c.get("expense_paid_date")
    gst = c.get("expense_gst_amount")
    return NewEntry(
        entry_date=d, amount_paise=amount, category=category, paid_date=paid if isinstance(paid, date) else None,
        gst_amount_paise=gst if isinstance(gst, int) and not isinstance(gst, bool) else None, gst_treatment=None,
        vendor=text("expense_vendor"), description=text("expense_description"), payment_ref=text("expense_payment_ref"),
        source="FILE", ingestion_run_id=str(run_id), source_row_number=row.source_row_number,
    )


def ingest_expense_stream(
    tenant_id: UUID,
    *,
    report_file_id: UUID,
    adapter: MarketplaceAdapter,
    stream: RowStream,
    started_at: datetime,
    created_by: UUID,
    on_progress: Callable[[int], None] | None = None,
) -> ExpenseIngestionOutcome:
    from data_foundation.types import FileSample

    sample = FileSample(columns=stream.header.columns)
    detection = adapter.detect(sample)
    run_id = ingestion_run_repo.insert_ingestion_run(
        tenant_id, report_file_id=report_file_id, adapter_id=adapter.adapter_id, adapter_version=adapter.format_version, started_at=started_at)
    if not detection.matched:
        ingestion_run_repo.mark_finished(tenant_id, run_id, status="MISMATCHED", row_count_read=0, row_count_accepted=0, row_count_rejected=0, finished_at=datetime.now())
        from data_foundation.ingestion.pipeline import AdapterMismatchError

        raise AdapterMismatchError(detection.missing_columns)

    read = rejected = posted = skipped = poss = overlap = gst_unconfirmed = chunks = 0
    examples: list[tuple[int, str]] = []
    categories: set[str] = set()
    held: list[str] = []
    try:
        with tenant_scope(tenant_id) as conn:  # ONE transaction for the whole file
            for chunk in stream.chunks():
                chunks += 1
                offset = read
                batch: list[NewEntry] = []
                for row in adapter.parse(chunk):
                    read += 1
                    n = row.source_row_number + offset
                    if row.parse_errors:
                        rejected += 1
                        if len(examples) < MAX_REJECTION_EXAMPLES:
                            col, val = row.parse_errors[0]
                            examples.append((n, f"column “{col}” has a value that cannot be read: {val!r}"))
                        continue
                    try:
                        batch.append(validate_new_entry(replace(_entry_from_row(row, run_id), source_row_number=n)))
                    except LedgerRuleError as exc:
                        rejected += 1
                        if len(examples) < MAX_REJECTION_EXAMPLES:
                            examples.append((n, str(exc)))
                if batch:
                    res = expense_ledger_repo.add_entries_on(conn, tenant_id, batch, created_by)
                    posted += len(res.inserted_ids)
                    skipped += res.skipped_exact_duplicates
                    poss += res.held_possible_duplicates
                    overlap += res.held_overlap
                    held.extend(str(i) for i in res.held_ids)
                    categories.update(e.category for e in batch)
                    gst_unconfirmed += sum(1 for e in batch if e.gst_amount_paise is not None)
                if on_progress is not None:
                    on_progress(read)
            if read > 0 and Fraction(rejected, read) > QUARANTINE_THRESHOLD:
                raise RunQuarantineThresholdExceeded(rejected, read)  # rolls the whole file back
    except Exception as exc:
        status = "QUARANTINE_EXCEEDED" if isinstance(exc, RunQuarantineThresholdExceeded) else "FAILED"
        try:
            ingestion_run_repo.mark_finished(tenant_id, run_id, status=status, row_count_read=read, row_count_accepted=0, row_count_rejected=rejected, finished_at=datetime.now())
        except Exception:  # noqa: BLE001
            logger.exception("could not mark expense ingestion run %s %s", run_id, status)
        raise

    ingestion_run_repo.mark_finished(tenant_id, run_id, status="VALIDATED", row_count_read=read, row_count_accepted=read - rejected, row_count_rejected=rejected,
                                     finished_at=datetime.now())
    return ExpenseIngestionOutcome(
        ingestion_run_id=run_id, row_count_read=read, posted=posted, held_possible_duplicates=poss, held_overlap=overlap, skipped_exact_duplicates=skipped,
        rejected=rejected, rejection_examples=tuple(examples), gst_unconfirmed=gst_unconfirmed, categories=tuple(sorted(categories)),
        blank_rows_skipped=stream.stats.blank_rows_skipped, ragged_rows=stream.stats.ragged_rows, chunks=chunks, held_ids=tuple(held),
    )
