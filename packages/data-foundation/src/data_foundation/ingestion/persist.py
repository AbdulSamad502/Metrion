"""Orchestrates run_ingestion() (pure, real, unchanged) + persistence of accepted rows into
sales_line/settlement_line/line_component, for BOTH sales-side (TAX/ORDER_STATUS) and
settlement-side (SETTLEMENT) adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from calc_engine.types import Confidence

from data_foundation.adapters.registry import ADAPTER_REGISTRY
from data_foundation.ingestion.dedup import find_natural_key_duplicates
from data_foundation.ingestion.pipeline import AdapterMismatchError, run_ingestion
from data_foundation.repositories import (
    ingestion_run_repo,
    line_component_repo,
    sales_line_repo,
    settlement_line_repo,
)
from data_foundation.types import FileSample, RawFile


@dataclass(frozen=True, slots=True)
class IngestionPersistOutcome:
    ingestion_run_id: UUID
    row_count_read: int
    row_count_accepted: int
    row_count_rejected: int
    row_count_duplicate: int  # accepted but skipped as an existing natural-key duplicate
    persisted_sales_line_ids: tuple[UUID, ...]


def ingest_and_persist(
    tenant_id: UUID,
    *,
    report_file_id: UUID,
    adapter_id: str,
    sample: FileSample,
    raw_file: RawFile,
    started_at: datetime,
) -> IngestionPersistOutcome:
    """Detects (confirms) the given `adapter_id` against `sample`, runs `run_ingestion` (real,
    unchanged — parse + validate, §3.1/§7.4's quarantine-threshold rule applies), then persists
    every ACCEPTED, non-duplicate row's `canonical_fields`/`components` via the real
    `sales_line_repo`/`line_component_repo` writers. A duplicate natural key (an overlapping
    re-upload) is counted, never double-persisted (§6 rule 4) — never silently re-ingested,
    never a hard failure either."""
    adapter = ADAPTER_REGISTRY.get(adapter_id)
    if adapter is None:
        raise ValueError(f"unknown adapter_id {adapter_id!r} — not in ADAPTER_REGISTRY")
    if adapter.report_category not in ("TAX", "ORDER_STATUS", "SETTLEMENT"):
        raise ValueError(f"adapter {adapter_id!r} has unsupported report_category={adapter.report_category!r}")
    is_settlement = adapter.report_category == "SETTLEMENT"

    run_id = ingestion_run_repo.insert_ingestion_run(
        tenant_id,
        report_file_id=report_file_id,
        adapter_id=adapter_id,
        adapter_version=adapter.format_version,
        started_at=started_at,
    )

    try:
        result = run_ingestion(adapter, sample, raw_file)
    except AdapterMismatchError:
        ingestion_run_repo.mark_finished(
            tenant_id, run_id, status="MISMATCHED", row_count_read=0, row_count_accepted=0,
            row_count_rejected=0, finished_at=datetime.now(),
        )
        raise

    accepted_rows = [r.row for r in result.row_results if not r.quarantined]
    if is_settlement:
        # No natural-key dedup table for settlement_line yet — file-level content-hash dedup
        # (report_file_repo.find_by_content_hash, checked by the caller before this runs) is
        # the real guard against a re-upload today; disclosed simplification, not silent.
        duplicate_row_numbers: set[int] = set()
    else:
        existing_keys = sales_line_repo.existing_natural_keys(tenant_id)
        duplicate_row_numbers = set(find_natural_key_duplicates(adapter.marketplace, accepted_rows, existing_keys))

    persisted_ids: list[UUID] = []
    for row in accepted_rows:
        if row.source_row_number in duplicate_row_numbers:
            continue
        if is_settlement:
            line_id = settlement_line_repo.insert_settlement_line(
                tenant_id, ingestion_run_id=run_id, marketplace=adapter.marketplace,
                canonical_fields=row.canonical_fields, source_row_number=row.source_row_number,
                source_row_json=row.source_row_json, confidence=Confidence.PROVISIONAL.value,
            )
            if row.components:
                line_component_repo.insert_settlement_components(
                    tenant_id, settlement_line_id=line_id, components=row.components
                )
        else:
            line_id = sales_line_repo.insert_sales_line(
                tenant_id, ingestion_run_id=run_id, marketplace=adapter.marketplace,
                canonical_fields=row.canonical_fields, source_row_number=row.source_row_number,
                source_row_json=row.source_row_json, confidence=Confidence.PROVISIONAL.value,
            )
            if row.components:
                line_component_repo.insert_components(tenant_id, sales_line_id=line_id, components=row.components)
        persisted_ids.append(line_id)

    ingestion_run_repo.mark_finished(
        tenant_id, run_id, status="VALIDATED", row_count_read=result.row_count_read,
        row_count_accepted=result.row_count_accepted, row_count_rejected=result.row_count_rejected,
        finished_at=datetime.now(),
    )

    return IngestionPersistOutcome(
        ingestion_run_id=run_id,
        row_count_read=result.row_count_read,
        row_count_accepted=result.row_count_accepted,
        row_count_rejected=result.row_count_rejected,
        row_count_duplicate=len(duplicate_row_numbers),
        persisted_sales_line_ids=tuple(persisted_ids),
    )
