"""CFO 2.0 upload / job / mapping service (cfo-data-intelligence.md §6.1–§6.5). The HTTP routes in `api/v1/cfo.py` stay
thin; everything about *how* a job is created, run, confirmed and presented lives here.

The runner is one process-wide `JobRunner` (a bounded thread pool; all state is in the database). Tests replace it with
`set_runner_for_tests` so jobs run synchronously with a fake proposer.
"""

from __future__ import annotations

import os
import threading
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID

from data_foundation.ingestion.job_runner import JobRunner, RunnerConfig
from data_foundation.ingestion.profiling import collect_profile_input
from data_foundation.ingestion.streaming import StreamError, StreamLimits, open_report
from data_foundation.mapping import service as mapping_service
from data_foundation.mapping.validator import MappingLimits
from data_foundation.repositories import (
    column_mapping_repo,
    data_quality_report_repo,
    held_row_repo,
    ingestion_job_repo as jobs,
    report_file_repo,
)

from backend.config import (
    cfo_ingest_workers,
    cfo_job_stale_seconds,
    cfo_mapping_model,
    cfo_mapping_sample_rows,
    cfo_mapping_thresholds,
    cfo_profile_rows,
    cfo_stream_chunk_rows,
    cfo_stream_max_rows,
    cfo_stream_max_upload_bytes,
    ollama_host,
)

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
UPLOAD_KINDS = ("SALES", "SETTLEMENT", "EXPENSE", "ADVERTISING")  # An ADVERTISING file belongs to one marketplace and is read through a confirmed mapping. An EXPENSE file is the business's, not a marketplace's: marketplace "ALL"
ALLOWED_EXTENSIONS = (".csv", ".txt", ".xlsx")

_lock = threading.Lock()
_runner: JobRunner | None = None


def stream_limits() -> StreamLimits:
    cap = cfo_stream_max_upload_bytes()
    return StreamLimits(
        chunk_rows=cfo_stream_chunk_rows(), max_rows=cfo_stream_max_rows(), header_scan_rows=30, min_header_fill=Fraction(6, 10),
        max_uncompressed_bytes=8 * cap,  # derived: an .xlsx may legitimately expand several times over; 8x the upload cap bounds a bomb
        max_zip_ratio=200, max_zip_members=500, max_sheets=50,
    )


def mapping_limits() -> MappingLimits:
    t = cfo_mapping_thresholds()
    return MappingLimits(
        min_parse_rate=t["min_parse_rate"], tax_consistency_rate=t["tax_consistency_rate"], tax_tolerance_paise=int(t["tax_tolerance_paise"]),  # type: ignore[arg-type]
        key_unique_rate=t["key_unique_rate"], mixed_sign_low=t["mixed_sign_low"], max_date_span_years=int(t["max_date_span_years"]),  # type: ignore[arg-type]
        unit_fraction_share=t["unit_fraction_share"],
    )


def _build_proposer() -> tuple[mapping_service.MappingProposer | None, str]:
    model = cfo_mapping_model()
    if model is None:
        return None, "MODEL:none"
    from cfo.reasoning.ollama_provider import OllamaLlmProvider

    from backend.services.cfo_mapping_proposer import LlmMappingProposer

    return LlmMappingProposer(OllamaLlmProvider(host=ollama_host()), model), f"MODEL:{model}"


def _suggest_classes_for_new_categories(tenant_id: UUID, categories: tuple[str, ...]) -> None:
    """After an expense file is committed: record rule-based class SUGGESTIONS for categories that have none. A suggestion changes no figure."""
    from calc_engine.repositories import expense_ledger_repo

    from backend.services import cfo_expense_ledger

    known = expense_ledger_repo.categories_with_assignment(tenant_id)
    for category in categories:
        if category in known:
            continue
        hit = cfo_expense_ledger.suggest_for_category(category)
        if hit is not None:
            expense_ledger_repo.suggest_class(tenant_id, klass=hit[0], suggested_by="RULE", reason=hit[1], category=category)


def _scan_after_ingest(tenant_id: UUID) -> None:
    from backend.services import cfo_risk_scan

    cfo_risk_scan.scan_in_background(tenant_id)


def get_runner() -> JobRunner:
    global _runner
    with _lock:
        if _runner is None:
            proposer, label = _build_proposer()
            _runner = JobRunner(
                config=RunnerConfig(max_workers=cfo_ingest_workers(), stale_after_seconds=cfo_job_stale_seconds(),
                                    profile_rows=cfo_profile_rows(), sample_rows=cfo_mapping_sample_rows()),
                stream_limits=stream_limits(), mapping_limits=mapping_limits(), as_of=lambda: datetime.now(timezone.utc).date(),
                proposer=proposer, proposed_by=label, after_expense_commit=_suggest_classes_for_new_categories, after_done=_scan_after_ingest,
            )
        return _runner


def set_runner_for_tests(runner: JobRunner | None) -> None:
    global _runner
    with _lock:
        _runner = runner


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, (datetime, date)) else None


def job_view(job: dict[str, Any], *, quality: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "jobId": str(job["id"]), "reportFileId": str(job["report_file_id"]), "status": job["status"], "reportKind": job["report_kind"],
        "adapterId": job["adapter_id"], "mappingId": str(job["mapping_id"]) if job["mapping_id"] else None,
        "progressRows": job["progress_rows"], "totalRowsEstimate": job["total_rows_estimate"], "errorCode": job["error_code"],
        "errorDetail": job["error_detail"], "outcome": job["outcome"], "attempt": job["attempt"],
        "createdAt": _iso(job["created_at"]), "startedAt": _iso(job["started_at"]), "finishedAt": _iso(job["finished_at"]),
        "heartbeatAt": _iso(job["heartbeat_at"]),
    }
    if quality is not None:
        out["qualityReport"] = quality
    return out


class UploadRejected(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


def validate_upload_request(filename: str, marketplace: str, report_kind: str, adapter_id: str | None = None) -> str:
    """Returns the lower-cased extension to store the file under; raises `UploadRejected` for anything unsupported."""
    if report_kind not in UPLOAD_KINDS:
        raise UploadRejected(400, f"report_kind must be one of {list(UPLOAD_KINDS)} ")
    if report_kind == "ADVERTISING":
        if marketplace not in MARKETPLACES:
            raise UploadRejected(400, f"marketplace must be one of {list(MARKETPLACES)}")
        if adapter_id is not None:
            raise UploadRejected(400, "advertising files are read through a column mapping; there is no report type to choose")
    elif report_kind == "EXPENSE":
        if marketplace != "ALL":
            raise UploadRejected(400, "an expense file belongs to the business, not to one marketplace: use marketplace ALL")
        if adapter_id is not None:
            raise UploadRejected(400, "expense files are read through a column mapping; there is no report type to choose")
    elif marketplace not in MARKETPLACES:
        raise UploadRejected(400, f"marketplace must be one of {list(MARKETPLACES)}")
    if adapter_id is not None:
        from data_foundation.adapters.registry import ADAPTER_REGISTRY

        adapter = ADAPTER_REGISTRY.get(adapter_id)
        if adapter is None:
            raise UploadRejected(400, f"unknown report type {adapter_id!r}; choose one of {sorted(ADAPTER_REGISTRY)}")
        if adapter.marketplace != marketplace:
            raise UploadRejected(400, f"{adapter_id!r} is a {adapter.marketplace} report type, not {marketplace}")
        wanted = ("SETTLEMENT",) if report_kind == "SETTLEMENT" else ("TAX", "ORDER_STATUS")
        if adapter.report_category not in wanted:
            raise UploadRejected(400, f"{adapter_id!r} is not a {report_kind} report type")
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(400, "Please upload a .csv or .xlsx file.")
    return ext


def register_upload(
    tenant_id: UUID, user_id: UUID, *, stored_path: Path, content_sha256: str, size: int, original_filename: str,
    marketplace: str, report_kind: str, sheet_name: str | None, adapter_id: str | None = None,
) -> dict[str, Any]:
    """Create the report_file + job for an already-stored upload and hand the job to the runner. A byte-identical
    re-upload reuses the stored file: it returns the existing active job, or the finished one, or starts a fresh attempt if
    the last attempt failed or was cancelled (so a seller can simply upload again)."""
    jobs.recover_stale(tenant_id, stale_after_seconds=cfo_job_stale_seconds(), now=datetime.now(timezone.utc))
    existing = report_file_repo.find_by_content_hash(tenant_id, content_sha256)
    if existing is not None:
        stored_path.unlink(missing_ok=True)  # the bytes are already stored under the earlier upload; drop this temporary copy
        last = jobs.latest_job_for_file(tenant_id, existing)
        if last is not None and last["status"] in (*jobs.ACTIVE_STATES, "DONE"):
            return {"reportFileId": str(existing), "duplicate": True, "job": job_view(last)}
        attempt = (last["attempt"] + 1) if last else 1
        job_id = jobs.create_job(tenant_id, report_file_id=existing, report_kind=report_kind, created_by=user_id, sheet_name=sheet_name, attempt=attempt, adapter_id=adapter_id)
        get_runner().submit(tenant_id, job_id)
        return {"reportFileId": str(existing), "duplicate": True, "job": job_view(jobs.get_job(tenant_id, job_id) or {})}

    final_path = stored_path.parent / f"{content_sha256}{stored_path.suffix}"
    os.replace(stored_path, final_path)  # atomic: the stored name is the content hash
    stored_path = final_path
    category = {"SETTLEMENT": "SETTLEMENT", "EXPENSE": "EXPENSE", "ADVERTISING": "ADVERTISING"}.get(report_kind, "ORDER_STATUS")
    rf = report_file_repo.insert_report_file(
        tenant_id, marketplace=marketplace, report_category=category, content_sha256=content_sha256, original_filename=original_filename,
        byte_size=size, storage_uri=f"file://{stored_path}", uploaded_by=user_id, uploaded_at=datetime.now(timezone.utc),
    )
    job_id = jobs.create_job(tenant_id, report_file_id=rf, report_kind=report_kind, created_by=user_id, sheet_name=sheet_name, adapter_id=adapter_id)
    get_runner().submit(tenant_id, job_id)
    return {"reportFileId": str(rf), "duplicate": False, "job": job_view(jobs.get_job(tenant_id, job_id) or {})}


def get_job_view(tenant_id: UUID, job_id: UUID) -> dict[str, Any] | None:
    jobs.recover_stale(tenant_id, stale_after_seconds=cfo_job_stale_seconds(), now=datetime.now(timezone.utc))
    job = jobs.get_job(tenant_id, job_id)
    if job is None:
        return None
    quality = data_quality_report_repo.get_for_job(tenant_id, job_id) if job["status"] == "DONE" else None
    return job_view(job, quality=quality)


def list_job_views(tenant_id: UUID, limit: int) -> list[dict[str, Any]]:
    jobs.recover_stale(tenant_id, stale_after_seconds=cfo_job_stale_seconds(), now=datetime.now(timezone.utc))
    return [job_view(j) for j in jobs.list_jobs(tenant_id, limit=limit)]


def cancel_job(tenant_id: UUID, job_id: UUID) -> tuple[str, dict[str, Any] | None]:
    """('ok'|'not_found'|'already_finished', view)."""
    job = jobs.get_job(tenant_id, job_id)
    if job is None:
        return "not_found", None
    if job["status"] in jobs.TERMINAL_STATES:
        return "already_finished", job_view(job)
    jobs.request_cancel(tenant_id, job_id, now=datetime.now(timezone.utc))
    return "ok", job_view(jobs.get_job(tenant_id, job_id) or job)


MANUAL_MAPPING_CODES = ("MAPPING_PROPOSAL_FAILED", "NO_MATCHING_FORMAT")


def start_manual_mapping(tenant_id: UUID, user_id: UUID, job_id: UUID, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """The seller maps the columns by hand when no automatic proposal could be made (no model, or the proposal was unusable). The seller's choices become a PROPOSED
    mapping (proposed_by SELLER) on a fresh attempt of the same file, and go through exactly the same validation and explicit confirmation as a model's proposal.
    Nothing is saved from the file until that confirmation."""
    from data_foundation.mapping.proposal import FieldProposal, MappingProposal

    job = jobs.get_job(tenant_id, job_id)
    if job is None:
        raise UploadRejected(404, "job not found")
    if job["status"] != "FAILED" or job["error_code"] not in MANUAL_MAPPING_CODES:
        raise UploadRejected(409, "this upload did not stop for want of a column mapping, so there is nothing to map by hand")
    if not fields:
        raise UploadRejected(400, "choose at least one column to use")
    rf = report_file_repo.get_report_file_for_ingestion(tenant_id, UUID(str(job["report_file_id"])))
    if rf is None:
        raise UploadRejected(404, "the uploaded file could not be found")
    path = Path(str(rf["storage_uri"])[len("file://"):])
    try:
        stream = open_report(path, stream_limits(), sheet_name=job["sheet_name"])
        pinput = collect_profile_input(stream, profile_rows=cfo_profile_rows(), sample_rows=cfo_mapping_sample_rows(), seed=int(str(rf["content_sha256"])[:12], 16))
    except StreamError as exc:
        raise UploadRejected(422, exc.detail) from None
    seen: set[int] = set()
    proposals: list[FieldProposal] = []
    for f in fields:
        idx = f.get("index")
        if not isinstance(idx, int) or not 0 <= idx < len(pinput.columns):
            raise UploadRejected(400, "a chosen column is not in the file")
        if idx in seen:
            raise UploadRejected(400, "a column was chosen twice")
        seen.add(idx)
        proposals.append(FieldProposal(source_column=pinput.columns[idx], index=idx, canonical_field=str(f.get("canonical_field") or ""), component_code=f.get("component_code"),
                                       transform=str(f.get("transform") or "IDENTITY"), tax_inclusion=f.get("tax_inclusion"), sign_convention=f.get("sign_convention")))
    unmapped = tuple(c for i, c in enumerate(pinput.columns) if i not in seen)
    proposal = MappingProposal(fields=tuple(proposals), unmapped_columns=unmapped)
    result = mapping_service.propose(
        tenant_id, pinput=pinput, report_kind=str(job["report_kind"]), marketplace=str(rf["marketplace"]), proposer=lambda _inp: proposal,
        proposed_by="SELLER", limits=mapping_limits(), as_of=datetime.now(timezone.utc).date())
    new_job = jobs.create_job(tenant_id, report_file_id=UUID(str(job["report_file_id"])), report_kind=str(job["report_kind"]), created_by=user_id,
                              sheet_name=job["sheet_name"], attempt=int(job["attempt"]) + 1, adapter_id=job["adapter_id"])
    jobs.transition(tenant_id, new_job, "AWAITING_MAPPING_CONFIRMATION", mapping_id=result.mapping_id, total_rows_estimate=pinput.total_rows, now=datetime.now(timezone.utc))
    return job_view(jobs.get_job(tenant_id, new_job) or {})


def held_view(tenant_id: UUID, job_id: UUID, *, status: str, page: int, page_size: int) -> dict[str, Any] | None:
    job = jobs.get_job(tenant_id, job_id)
    if job is None:
        return None
    rows, total, unresolved = held_row_repo.list_for_file(tenant_id, UUID(str(job["report_file_id"])), status=status, page=page, page_size=page_size)
    return {"items": rows, "page": page, "pageSize": page_size, "total": total, "pageCount": max(1, -(-total // page_size)), "unresolved": unresolved}


def mapping_view(tenant_id: UUID, job_id: UUID) -> dict[str, Any] | None:
    job = jobs.get_job(tenant_id, job_id)
    if job is None or job["mapping_id"] is None:
        return None
    m = column_mapping_repo.get_mapping(tenant_id, UUID(str(job["mapping_id"])))
    if m is None:
        return None
    return {
        "mappingId": str(m["id"]), "status": m["status"], "version": m["version"], "reportKind": m["report_kind"], "proposedBy": m["proposed_by"],
        "verified": m["verified"], "evidence": m["evidence"],
        "fields": [
            {"index": f["source_column_index"], "sourceColumn": f["source_column"], "canonicalField": f["canonical_field"],
             "componentCode": f["component_code"], "transform": f["transform"], "taxInclusion": f["tax_inclusion"],
             "signConvention": f["sign_convention"], "decision": f["decision"], "evidence": f["evidence"]}
            for f in m["fields"]
        ],
    }


def confirm_mapping(
    tenant_id: UUID, user_id: UUID, job_id: UUID, *, decisions: dict[int, str], overrides: dict[int, mapping_service.FieldOverride]
) -> dict[str, Any]:
    """Confirm the proposed mapping for a job waiting on the seller (re-validated against the file first), then re-queue
    the job. Raises `mapping_service.MappingRefused` (nothing changed) or `UploadRejected` for a job in the wrong state."""
    job = jobs.get_job(tenant_id, job_id)
    if job is None:
        raise UploadRejected(404, "job not found")
    if job["status"] != "AWAITING_MAPPING_CONFIRMATION" or job["mapping_id"] is None:
        raise UploadRejected(409, "this upload is not waiting for a column mapping")
    rf = report_file_repo.get_report_file_for_ingestion(tenant_id, UUID(str(job["report_file_id"])))
    if rf is None:
        raise UploadRejected(404, "the uploaded file could not be found")
    path = Path(str(rf["storage_uri"])[len("file://"):])
    try:
        stream = open_report(path, stream_limits(), sheet_name=job["sheet_name"])
        pinput = collect_profile_input(stream, profile_rows=cfo_profile_rows(), sample_rows=cfo_mapping_sample_rows(), seed=1)
    except StreamError as exc:
        raise UploadRejected(422, exc.detail) from None
    mapping_service.confirm(
        tenant_id, UUID(str(job["mapping_id"])), confirmed_by=user_id, decisions=decisions, overrides=overrides, pinput=pinput,
        limits=mapping_limits(), as_of=datetime.now(timezone.utc).date(), now=datetime.now(timezone.utc),
    )
    jobs.transition(tenant_id, job_id, "QUEUED", mapping_id=UUID(str(job["mapping_id"])), now=datetime.now(timezone.utc))
    get_runner().submit(tenant_id, job_id)
    return job_view(jobs.get_job(tenant_id, job_id) or job)
