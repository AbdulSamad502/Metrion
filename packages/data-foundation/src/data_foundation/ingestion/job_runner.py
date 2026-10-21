"""Background ingestion jobs (cfo-data-intelligence.md §6.1–§6.5, D1).

`JobRunner.run_job` takes one QUEUED job through: claim -> profile -> resolve the format (a verified adapter,
else a seller-confirmed mapping, else propose a mapping and wait for the seller) -> stream-ingest atomically ->
quality report -> DONE. Every failure becomes a stable `error_code` plus a plain-language, seller-readable detail;
nothing a failed or cancelled job read is left posted (the file is one transaction).

Tenant context comes from the job payload only (auth.md D8): `tenant_id` is required, and every repository call
goes through `tenant_scope`, which fails closed. Cancellation is honoured at every chunk. The runner holds no
state of its own beyond a bounded thread pool; progress and state live in the database, so a restart loses nothing
that was not already all-or-nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

from calc_engine.repositories import read_model_version_repo
from sqlalchemy import Connection

from data_foundation.adapters.mapped import MappedAdapterUnsupported, adapter_from_mapping
from data_foundation.adapters.registry import ADAPTER_REGISTRY
from data_foundation.ingestion.pipeline import AdapterMismatchError, RunQuarantineThresholdExceeded
from data_foundation.ingestion.profiling import collect_profile_input
from data_foundation.ingestion.stream_persist import StreamIngestionOutcome, ingest_stream_and_persist
from data_foundation.ingestion.streaming import StreamError, StreamLimits, open_report
from data_foundation.mapping import service as mapping_service
from data_foundation.mapping.validator import MappingLimits
from data_foundation.repositories import (
    column_mapping_repo,
    data_quality_report_repo,
    ingestion_job_repo as jobs,
    report_file_repo,
    validation_finding_repo,
)
from data_foundation.types import FileSample, MarketplaceAdapter

logger = logging.getLogger(__name__)

_SALES_CATEGORIES = ("TAX", "ORDER_STATUS")


class JobCancelled(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Configuration — supplied by the caller; nothing here is a hidden default."""

    max_workers: int
    stale_after_seconds: int
    profile_rows: int
    sample_rows: int


def _storage_path(storage_uri: str) -> Path:
    if not storage_uri.startswith("file://"):
        raise StreamError("storage_unsupported", "only locally stored uploads can be ingested right now")
    return Path(storage_uri[len("file://"):])


def _outcome_dict(o: StreamIngestionOutcome) -> dict[str, object]:
    d = asdict(o)
    d["ingestion_run_id"] = str(o.ingestion_run_id)
    return d


class JobRunner:
    def __init__(
        self,
        *,
        config: RunnerConfig,
        stream_limits: StreamLimits,
        mapping_limits: MappingLimits,
        as_of: Callable[[], date],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        proposer: mapping_service.MappingProposer | None = None,
        proposed_by: str = "MODEL:unspecified",
    ) -> None:
        self._cfg = config
        self._limits = stream_limits
        self._mapping_limits = mapping_limits
        self._as_of = as_of
        self._clock = clock
        self._proposer = proposer
        self._proposed_by = proposed_by
        self._pool = ThreadPoolExecutor(max_workers=config.max_workers, thread_name_prefix="cfo-ingest")

    # ------------------------------------------------------------------------------------ public
    def submit(self, tenant_id: UUID, job_id: UUID) -> Future[str]:
        if tenant_id is None:
            raise ValueError("an ingestion job needs a tenant id (fail closed)")
        return self._pool.submit(self.run_job, tenant_id, job_id)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)

    def run_job(self, tenant_id: UUID, job_id: UUID) -> str:
        """Process one job; returns its final status (DONE, FAILED, CANCELLED, AWAITING_MAPPING_CONFIRMATION, or
        'SKIPPED' when another worker already claimed it)."""
        if tenant_id is None:
            raise ValueError("an ingestion job needs a tenant id (fail closed)")
        now = self._clock
        if not jobs.claim(tenant_id, job_id, now=now()):
            return "SKIPPED"
        try:
            return self._run_claimed(tenant_id, job_id)
        except JobCancelled:
            jobs.transition(tenant_id, job_id, "CANCELLED", error_code="CANCELLED_BY_SELLER", now=now())
            return "CANCELLED"
        except StreamError as exc:
            return self._fail(tenant_id, job_id, exc.code, _stream_message(exc))
        except AdapterMismatchError as exc:
            return self._fail(tenant_id, job_id, "ADAPTER_MISMATCH",
                              f"The file does not have the columns this report type needs (missing: {', '.join(exc.missing_columns)}).")
        except RunQuarantineThresholdExceeded as exc:
            return self._fail(tenant_id, job_id, "QUARANTINE_EXCEEDED",
                              f"{exc.rejected} of {exc.total} rows could not be read, which is too many to trust this file. Nothing from it was saved. "
                              "Please check you uploaded the right report.")
        except MappedAdapterUnsupported as exc:
            return self._fail(tenant_id, job_id, exc.code, exc.detail)
        except mapping_service.MappingProposalFailed:
            return self._fail(tenant_id, job_id, "MAPPING_PROPOSAL_FAILED",
                              "We could not work out this file's columns automatically. Nothing was saved. Please map the columns manually.")
        except Exception:  # noqa: BLE001 - last resort: never leave a job stuck, never leak internals to the seller
            logger.exception("ingestion job %s failed unexpectedly", job_id)
            return self._fail(tenant_id, job_id, "INTERNAL", "An unexpected problem stopped this upload. Nothing from it was saved. Please try again.")

    # ------------------------------------------------------------------------------------ internals
    def _fail(self, tenant_id: UUID, job_id: UUID, code: str, detail: str) -> str:
        jobs.transition(tenant_id, job_id, "FAILED", error_code=code, error_detail=detail, now=self._clock())
        job = jobs.get_job(tenant_id, job_id)
        return str(job["status"]) if job else "FAILED"

    def _resolve(self, tenant_id: UUID, job: dict, rf: dict, columns: tuple[str, ...]) -> tuple[MarketplaceAdapter, UUID | None] | None:  # type: ignore[type-arg]
        marketplace = str(rf["marketplace"])
        kind = str(job["report_kind"])
        if job["mapping_id"] is not None:
            mapping = column_mapping_repo.get_mapping(tenant_id, UUID(str(job["mapping_id"])))
            if mapping is None:
                raise MappedAdapterUnsupported("MAPPING_MISSING", "the confirmed column mapping for this upload could not be found")
            return adapter_from_mapping(mapping, columns, marketplace), UUID(str(mapping["id"]))

        sample = FileSample(columns=columns)
        categories = _SALES_CATEGORIES if kind == "SALES" else ("SETTLEMENT",) if kind == "SETTLEMENT" else ()
        matches = [a for a in ADAPTER_REGISTRY.values()
                   if a.marketplace == marketplace and a.report_category in categories and a.detect(sample).matched]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            raise MappedAdapterUnsupported("AMBIGUOUS_ADAPTER", "this file matches more than one report type (" + ", ".join(sorted(a.adapter_id for a in matches)) + "); please say which one it is")
        # no verified adapter: a mapping this seller already confirmed for this exact file shape?
        from data_foundation.mapping.profile import file_fingerprint  # local import keeps the module header light

        confirmed = column_mapping_repo.find_confirmed(tenant_id, file_fingerprint(columns, job["sheet_name"]))
        if confirmed is not None:
            return adapter_from_mapping(confirmed, columns, marketplace), UUID(str(confirmed["id"]))
        return None

    def _run_claimed(self, tenant_id: UUID, job_id: UUID) -> str:
        now = self._clock
        job = jobs.get_job(tenant_id, job_id)
        assert job is not None
        rf = report_file_repo.get_report_file_for_ingestion(tenant_id, UUID(str(job["report_file_id"])))
        if rf is None:
            return self._fail(tenant_id, job_id, "FILE_MISSING", "The uploaded file could not be found.")
        path = _storage_path(str(rf["storage_uri"]))
        if not path.exists():
            return self._fail(tenant_id, job_id, "FILE_MISSING", "The uploaded file is no longer available. Please upload it again.")

        stream = open_report(path, self._limits, sheet_name=job["sheet_name"])
        resolved = self._resolve(tenant_id, job, rf, stream.header.columns)

        if resolved is None:
            stream.close()
            return self._propose_and_wait(tenant_id, job, rf, path)

        adapter, mapping_id = resolved
        jobs.transition(tenant_id, job_id, "PARSING", adapter_id=None if mapping_id else adapter.adapter_id, mapping_id=mapping_id, now=now())

        def progress(rows_read: int) -> None:
            if jobs.is_cancelled(tenant_id, job_id):
                raise JobCancelled()
            jobs.heartbeat(tenant_id, job_id, rows_read, now=now())

        outcome = ingest_stream_and_persist(
            tenant_id, report_file_id=UUID(str(rf["id"])), adapter_id=adapter.adapter_id, stream=stream, started_at=now(),
            on_progress=progress, adapter=adapter,
            in_transaction=lambda conn: _bump(conn, tenant_id),
        )
        summary = self._quality_summary(tenant_id, outcome, adapter, str(rf["marketplace"]))
        data_quality_report_repo.upsert(tenant_id, ingestion_job_id=job_id, summary=summary)
        jobs.transition(tenant_id, job_id, "DONE", outcome=_outcome_dict(outcome), now=now())
        return "DONE"

    def _propose_and_wait(self, tenant_id: UUID, job: dict, rf: dict, path: Path) -> str:  # type: ignore[type-arg]
        job_id = UUID(str(job["id"]))
        if self._proposer is None:
            return self._fail(tenant_id, job_id, "NO_MATCHING_FORMAT",
                              "This file's format is not one Metrion recognises yet, and automatic column mapping is not switched on. Nothing was saved.")
        stream = open_report(path, self._limits, sheet_name=job["sheet_name"])
        seed = int(str(rf["content_sha256"])[:12], 16)  # deterministic per file
        pinput = collect_profile_input(stream, profile_rows=self._cfg.profile_rows, sample_rows=self._cfg.sample_rows, seed=seed)
        result = mapping_service.propose(
            tenant_id, pinput=pinput, report_kind=str(job["report_kind"]), marketplace=str(rf["marketplace"]), proposer=self._proposer,
            proposed_by=self._proposed_by, limits=self._mapping_limits, as_of=self._as_of(),
        )
        jobs.transition(tenant_id, job_id, "AWAITING_MAPPING_CONFIRMATION", mapping_id=result.mapping_id,
                        total_rows_estimate=pinput.total_rows, now=self._clock())
        return "AWAITING_MAPPING_CONFIRMATION"

    def _quality_summary(self, tenant_id: UUID, o: StreamIngestionOutcome, adapter: MarketplaceAdapter, marketplace: str) -> dict[str, object]:
        by_rule = validation_finding_repo.counts_by_rule(tenant_id, o.ingestion_run_id)
        held = o.held_conflicts + o.held_ambiguous
        needs: list[str] = []
        if o.held_conflicts:
            needs.append(f"{o.held_conflicts} row(s) have the same order line as earlier data but different values and were held; replacing earlier rows needs your confirmation.")
        if o.held_ambiguous:
            needs.append(f"{o.held_ambiguous} identical repeated row(s) were held because they cannot be told apart from a double export.")
        if o.row_count_rejected:
            needs.append(f"{o.row_count_rejected} row(s) could not be read and were excluded; see the reasons by rule.")
        return {
            "marketplace": marketplace,
            "format": {"adapter_id": adapter.adapter_id, "version": adapter.format_version, "mapped": adapter.adapter_id.startswith("mapped.")},
            "rows": {
                "read": o.row_count_read, "posted": o.persisted_row_count, "failed_validation": o.row_count_rejected,
                "duplicate_overlap_with_earlier_uploads": o.duplicates_cross_file, "duplicate_repeats_in_file": o.duplicates_in_file,
                "held_conflicting": o.held_conflicts, "held_ambiguous": o.held_ambiguous, "held_total": held,
                "blank_skipped": o.blank_rows_skipped, "ragged_padded": o.ragged_rows,
            },
            "findings_by_rule": by_rule,
            "needs_seller": needs,
            "confidence": "PROVISIONAL",
        }


def _bump(conn: Connection, tenant_id: UUID) -> None:
    read_model_version_repo.bump_on(conn, tenant_id)


def _stream_message(exc: StreamError) -> str:
    return {
        "empty_file": "The file is empty.",
        "no_header": "We could not find a header row in this file.",
        "too_large": "This file has more rows than can be processed in one upload. Please split it by period.",
        "unsafe_archive": "This Excel file could not be opened safely.",
        "not_xlsx": "This does not look like a valid Excel (.xlsx) file.",
        "unsupported_type": "This file type is not supported. Please upload a .csv or .xlsx file.",
        "no_sheet": "The chosen sheet could not be found in this workbook.",
    }.get(exc.code, exc.detail)
