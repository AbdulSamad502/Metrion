"""Atomic advertising-report ingestion into `ad_report_line` (docs/specs/cfo-phase3-scope.md AD1, AD2).

A seller-confirmed mapping (`report_kind=ADVERTISING`) turns each row into an ad line. Identity is (marketplace, campaign_ref, sku, report_date):
an identical repeat is skipped and counted; the same identity with different spend or attributed sales is REJECTED with its reason (the earlier figure
stands — nothing is overwritten and nothing is counted twice); an unreadable row is rejected with its reason. The whole file is one transaction and
rolls back when more than the quarantine threshold is rejected. Rows are `PROVISIONAL`: no dedicated adapter has been validated against a real export.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from calc_engine.repositories import read_model_version_repo

from data_foundation.ingestion.pipeline import QUARANTINE_THRESHOLD, AdapterMismatchError, RunQuarantineThresholdExceeded
from data_foundation.ingestion.streaming import RowStream
from data_foundation.repositories import ingestion_run_repo
from data_foundation.repositories.tenant_context import tenant_scope
from data_foundation.types import FileSample, MarketplaceAdapter, ParsedRow

logger = logging.getLogger(__name__)

MAX_REJECTION_EXAMPLES = 25
Key = tuple[str, str, date]  # (campaign_ref or '', sku or '', report_date)


@dataclass(frozen=True, slots=True)
class AdIngestionOutcome:
    ingestion_run_id: UUID
    row_count_read: int
    posted: int
    skipped_exact_duplicates: int
    rejected: int
    rejection_examples: tuple[tuple[int, str], ...]
    no_attributed_sales: int  # posted rows whose report carries no attributed sales (kept as unknown, never zero)
    period_start: date | None
    period_end: date | None
    blank_rows_skipped: int
    ragged_rows: int
    chunks: int


_INSERT = text(
    """INSERT INTO ad_report_line (id, tenant_id, ingestion_run_id, marketplace, campaign_ref, sku, report_date, spend, attributed_sales, impressions, clicks, currency,
                                   source_row_number, source_row_json, confidence)
       VALUES (:id, :t, :run, :mp, :campaign, :sku, :d, :spend, :sales, :imp, :clk, :cur, :n, CAST(:j AS jsonb), 'PROVISIONAL')"""
)


def _int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _existing(conn: Connection, tenant_id: UUID, marketplace: str, lo: date, hi: date) -> dict[Key, tuple[int, int | None]]:
    out: dict[Key, tuple[int, int | None]] = {}
    for campaign, sku, d, spend, sales in conn.execute(
            text("SELECT campaign_ref, sku, report_date, spend, attributed_sales FROM ad_report_line WHERE tenant_id = :t AND marketplace = :m AND report_date BETWEEN :lo AND :hi"),
            {"t": str(tenant_id), "m": marketplace, "lo": lo, "hi": hi}):
        out[(campaign or "", sku or "", d)] = (int(spend), None if sales is None else int(sales))
    return out


def ingest_ad_stream(
    tenant_id: UUID,
    *,
    report_file_id: UUID,
    marketplace: str,
    adapter: MarketplaceAdapter,
    stream: RowStream,
    started_at: datetime,
    on_progress: Callable[[int], None] | None = None,
) -> AdIngestionOutcome:
    sample = FileSample(columns=stream.header.columns)
    detection = adapter.detect(sample)
    run_id = ingestion_run_repo.insert_ingestion_run(
        tenant_id, report_file_id=report_file_id, adapter_id=adapter.adapter_id, adapter_version=adapter.format_version, started_at=started_at)
    if not detection.matched:
        ingestion_run_repo.mark_finished(tenant_id, run_id, status="MISMATCHED", row_count_read=0, row_count_accepted=0, row_count_rejected=0, finished_at=datetime.now())
        raise AdapterMismatchError(detection.missing_columns)

    read = rejected = posted = skipped = no_sales = chunks = 0
    examples: list[tuple[int, str]] = []
    lo: date | None = None
    hi: date | None = None

    def reject(n: int, why: str) -> None:
        nonlocal rejected
        rejected += 1
        if len(examples) < MAX_REJECTION_EXAMPLES:
            examples.append((n, why))

    try:
        with tenant_scope(tenant_id) as conn:  # ONE transaction for the whole file
            seen: dict[Key, tuple[int, int | None]] = {}
            loaded: tuple[date, date] | None = None
            for chunk in stream.chunks():
                chunks += 1
                offset = read
                rows: list[tuple[int, ParsedRow]] = []
                for row in adapter.parse(chunk):
                    read += 1
                    rows.append((row.source_row_number + offset, row))
                dates: list[date] = [d for _, r in rows if isinstance((d := r.canonical_fields.get("report_date")), date)]
                if dates:
                    new_lo, new_hi = min(dates), max(dates)
                    if loaded is None or new_lo < loaded[0] or new_hi > loaded[1]:
                        window = (new_lo, new_hi) if loaded is None else (min(new_lo, loaded[0]), max(new_hi, loaded[1]))
                        seen.update({k: v for k, v in _existing(conn, tenant_id, marketplace, window[0], window[1]).items() if k not in seen})
                        loaded = window
                batch: list[dict[str, object]] = []
                for n, row in rows:
                    if row.parse_errors:
                        col, val = row.parse_errors[0]
                        reject(n, f"column “{col}” has a value that cannot be read: {val!r}")
                        continue
                    c = row.canonical_fields
                    d, spend = c.get("report_date"), c.get("spend")
                    if not isinstance(d, date):
                        reject(n, "the report date is missing")
                        continue
                    if _int(spend) is None:
                        reject(n, "the spend is missing")
                        continue
                    if spend < 0:  # type: ignore[operator]
                        reject(n, "the spend is negative; a refund of advertising is not recorded as spend")
                        continue
                    sales = _int(c.get("attributed_sales"))
                    key: Key = (str(c.get("campaign_ref") or ""), str(c.get("sku") or ""), d)
                    prior = seen.get(key)
                    if prior is not None:
                        if prior == (spend, sales):
                            skipped += 1
                        else:
                            reject(n, "this campaign and day already have different figures recorded; the earlier figures stand")
                        continue
                    seen[key] = (spend, sales)  # type: ignore[assignment]
                    lo = d if lo is None or d < lo else lo
                    hi = d if hi is None or d > hi else hi
                    if sales is None:
                        no_sales += 1
                    batch.append({"id": str(uuid4()), "t": str(tenant_id), "run": str(run_id), "mp": marketplace, "campaign": c.get("campaign_ref") or None,
                                  "sku": c.get("sku") or None, "d": d, "spend": spend, "sales": sales, "imp": _int(c.get("impressions")), "clk": _int(c.get("clicks")),
                                  "cur": "INR", "n": n, "j": json.dumps(row.source_row_json)})
                if batch:
                    conn.execute(_INSERT, batch)
                    posted += len(batch)
                if on_progress is not None:
                    on_progress(read)
            if read > 0 and Fraction(rejected, read) > QUARANTINE_THRESHOLD:
                raise RunQuarantineThresholdExceeded(rejected, read)
            if posted:
                read_model_version_repo.bump_on(conn, tenant_id)
    except Exception as exc:
        status = "QUARANTINE_EXCEEDED" if isinstance(exc, RunQuarantineThresholdExceeded) else "FAILED"
        try:
            ingestion_run_repo.mark_finished(tenant_id, run_id, status=status, row_count_read=read, row_count_accepted=0, row_count_rejected=rejected, finished_at=datetime.now())
        except Exception:  # noqa: BLE001
            logger.exception("could not mark ad ingestion run %s %s", run_id, status)
        raise
    ingestion_run_repo.mark_finished(tenant_id, run_id, status="VALIDATED", row_count_read=read, row_count_accepted=read - rejected, row_count_rejected=rejected,
                                     finished_at=datetime.now())
    return AdIngestionOutcome(run_id, read, posted, skipped, rejected, tuple(examples), no_sales, lo, hi, stream.stats.blank_rows_skipped, stream.stats.ragged_rows, chunks)
