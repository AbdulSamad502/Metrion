"""Importing the spreadsheets a seller attached to a CEO conversation into the CFO financial records (docs/specs/cfo-3-growth-advisor.md, Phase 0).

Reading an attachment (`ceo_attachment_analysis`) and importing it are different operations. Reading is by code, writes nothing, and says so. Importing is a financial write: the CEO prepares a
PREVIEW of each file (what it is, how many rows, whether it is a report type the importer knows), shows it on a plan card, and only after the seller presses Approve does this module hand the
stored bytes to the SAME validated pipeline the CFO Data & imports page uses (`cfo_ingestion.register_upload`): its report-type recognition, its duplicate and overlap protection, its held rows, its coverage and
audit trail, its read-model version bump. Nothing here parses a value, writes a canonical row or invents a mapping. A file the importer does not know is NOT guessed at: it needs the seller's
explicit column mapping on the Data & imports page, and the answer says so.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.auth.context import AuthContext
from backend.config import cfo_report_storage_dir, cfo_stream_max_upload_bytes
from backend.repositories import investigation_repo as repo
from backend.services import attachment_tables as tables
from backend.services import cfo_ingestion

MAX_FILES = 5
WAIT_SECONDS = 90.0  # how long an approved import waits for its jobs before saying they are still running (a guard, not a business setting)
POLL_SECONDS = 0.5
SPREADSHEETS = ("CSV", "XLSX")
MARKETPLACE_WORDS = {"AMAZON": ("amazon", "amzn"), "FLIPKART": ("flipkart", "fkrt"), "MEESHO": ("meesho",)}
MARKETPLACE_LABEL = {"AMAZON": "Amazon", "FLIPKART": "Flipkart", "MEESHO": "Meesho"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ImportFile(_Strict):
    attachment_id: UUID
    filename: str = Field(min_length=1, max_length=300)
    marketplace: Literal["AMAZON", "FLIPKART", "MEESHO"]
    report_kind: Literal["SALES", "SETTLEMENT"] = "SALES"
    adapter_id: str | None = Field(default=None, max_length=80)


class ImportSlots(_Strict):
    investigation_id: UUID
    files: list[ImportFile] = Field(min_length=1, max_length=MAX_FILES)
    request_key: str | None = Field(default=None, max_length=200)


def marketplace_in(name: str) -> str | None:
    low = (name or "").casefold()
    hits = [mk for mk, words in MARKETPLACE_WORDS.items() if any(w in low for w in words)]
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------------------------------------ preview (read only)
def _recognise(columns: list[str]) -> list[tuple[str, str, str]]:
    """(adapter id, marketplace, report category) of every verified report type whose declared columns are all present."""
    from data_foundation.adapters.registry import ADAPTER_REGISTRY
    from data_foundation.types import FileSample

    sample = FileSample(columns=tuple(columns))
    return [(a.adapter_id, a.marketplace, a.report_category) for a in ADAPTER_REGISTRY.values() if a.detect(sample).matched]


def preview_file(row: dict[str, Any]) -> dict[str, Any]:
    """What one stored attachment is, for the plan card. `status`: KNOWN (a verified report type), NEEDS_MAPPING (readable, but the importer has no report type for these columns),
    AMBIGUOUS (several report types fit) or UNREADABLE. Nothing is written."""
    base = {"attachment_id": str(row["id"]), "filename": row["filename"], "marketplace": marketplace_in(row["filename"]), "report_kind": "SALES", "adapter_id": None,
            "status": "UNREADABLE", "rows": None, "note": None}
    if row.get("detected_type") not in SPREADSHEETS:
        return {**base, "note": "It is not a CSV or Excel spreadsheet, so it cannot be imported."}
    try:
        wb = tables.read_table(row["content"], row["detected_type"], row["filename"])
    except tables.UnreadableTable as exc:
        return {**base, "note": str(exc)}
    except Exception:  # noqa: BLE001 - a preview never shows a stack trace or the file's content
        return {**base, "note": "It could not be read as a table."}
    sheet = max(wb.sheets, key=lambda s: s.n_rows) if wb.sheets else None
    if sheet is None or sheet.header_row is None:
        return {**base, "note": "I could not find a header row of column names."}
    found = _recognise([c.name for c in sheet.columns])
    base = {**base, "rows": sheet.n_rows}
    if len(found) == 1:
        adapter_id, marketplace, category = found[0]
        return {**base, "status": "KNOWN", "adapter_id": adapter_id, "marketplace": marketplace, "report_kind": "SETTLEMENT" if category == "SETTLEMENT" else "SALES"}
    if len(found) > 1:
        return {**base, "status": "AMBIGUOUS", "note": "More than one report type fits these columns: " + ", ".join(sorted(a for a, _, _ in found)) + "."}
    return {**base, "status": "NEEDS_MAPPING"}


def prepare(tenant_id: UUID, investigation_id: UUID, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    """The previews for the files in this message, or - when the message carries none - the spreadsheets of this conversation's latest attachment batch. Everything is
    read from this tenant's own stored attachments."""
    chosen = [a for a in attachments if a.get("detected_type") in SPREADSHEETS]
    if not chosen:
        latest = repo.latest_attachments(tenant_id, investigation_id, limit=MAX_FILES)
        chosen = [a for a in latest if a.get("detected_type") in SPREADSHEETS]
    chosen = chosen[:MAX_FILES]
    rows = repo.get_attachment_contents(tenant_id, investigation_id, [a["id"] for a in chosen])
    previews = [preview_file(r) for r in rows]
    return {"investigation": str(investigation_id), "previews": previews}


def previews_for_slots(tenant_id: UUID, investigation_id: UUID, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The preview of each file named in a plan's frozen slots, read again from this tenant's stored attachment (so the card shows what will be imported). The marketplace on the plan wins."""
    rows = {str(r["id"]): r for r in repo.get_attachment_contents(tenant_id, investigation_id, [UUID(str(f["attachment_id"])) for f in files])}
    out: list[dict[str, Any]] = []
    for f in files:
        row = rows.get(str(f["attachment_id"]))
        out.append({**preview_file(row), "marketplace": f.get("marketplace")} if row is not None else {"filename": f.get("filename", "a file"), "status": "UNREADABLE", "note": "It is no longer attached.", "rows": None})
    return out


def card_lines(previews: list[dict[str, Any]]) -> list[str]:
    """One plain line per file, written by code from the preview."""
    out: list[str] = []
    for p in previews:
        mk = MARKETPLACE_LABEL.get(p.get("marketplace") or "", "marketplace not stated")
        n = "" if p.get("rows") is None else f", {p['rows']} data rows"
        if p["status"] == "KNOWN":
            out.append(f"{p['filename']}: {mk} {'settlement' if p['report_kind'] == 'SETTLEMENT' else 'sales'} report I recognise{n}. It is added when you approve.")
        elif p["status"] == "NEEDS_MAPPING":
            out.append(f"{p['filename']}: {mk}{n}. I do not recognise this column layout, so it needs your column mapping on the Data & imports page. Nothing is added until you confirm that mapping.")
        elif p["status"] == "AMBIGUOUS":
            out.append(f"{p['filename']}: {mk}{n}. {p['note']} Choose the report type on the Data & imports page.")
        else:
            out.append(f"{p['filename']}: cannot be imported. {p.get('note') or ''}".strip())
    return out


# ------------------------------------------------------------------------------------------------ the approved write
def _store_and_register(ctx: AuthContext, f: ImportFile, content: bytes) -> dict[str, Any]:
    assert ctx.tenant_id is not None and ctx.app_user_id is not None
    ext = cfo_ingestion.validate_upload_request(f.filename, f.marketplace, f.report_kind, f.adapter_id)
    if len(content) > cfo_stream_max_upload_bytes():
        raise cfo_ingestion.UploadRejected(413, "The file is larger than the upload limit.")
    storage = Path(cfo_report_storage_dir())
    storage.mkdir(parents=True, exist_ok=True)
    tmp = storage / f"upload-{uuid4().hex}{ext}"
    tmp.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    return cfo_ingestion.register_upload(
        ctx.tenant_id, ctx.app_user_id, stored_path=tmp, content_sha256=sha, size=len(content), original_filename=f.filename, marketplace=f.marketplace, report_kind=f.report_kind,
        sheet_name=None, adapter_id=f.adapter_id,
    )


def run(slots: ImportSlots, ctx: AuthContext) -> dict[str, Any]:
    """Runs from an approved plan only (the registry gate has already checked permission and entitlement). Each file goes through the importer's own upload path; this function waits a bounded
    time for the jobs and reports what the importer reported, never more."""
    assert ctx.tenant_id is not None
    tenant = ctx.tenant_id
    rows = {str(r["id"]): r for r in repo.get_attachment_contents(tenant, slots.investigation_id, [f.attachment_id for f in slots.files])}
    started: list[tuple[ImportFile, dict[str, Any] | None, str | None]] = []
    for f in slots.files:
        row = rows.get(str(f.attachment_id))
        if row is None:  # a foreign, unknown or other-conversation id is simply absent
            started.append((f, None, "That attachment is no longer in this conversation."))
            continue
        try:
            started.append((f, _store_and_register(ctx, f, row["content"]), None))
        except cfo_ingestion.UploadRejected as exc:
            started.append((f, None, str(exc.detail)))
    deadline = time.monotonic() + WAIT_SECONDS
    out: list[dict[str, Any]] = []
    for f, reg, problem in started:
        item: dict[str, Any] = {"filename": f.filename, "marketplace": f.marketplace, "reportKind": f.report_kind}
        if reg is None:
            out.append({**item, "outcome": "REFUSED", "reason": problem})
            continue
        job_id = UUID(str(reg["job"]["jobId"]))
        view = cfo_ingestion.get_job_view(tenant, job_id) or reg["job"]
        while view.get("status") not in ("DONE", "FAILED", "CANCELLED") and time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
            view = cfo_ingestion.get_job_view(tenant, job_id) or view
        status = view.get("status")
        rowsq = ((view.get("qualityReport") or {}).get("rows")) or {}
        res: dict[str, Any] = {**item, "jobId": str(job_id), "duplicateFile": bool(reg.get("duplicate")), "status": status}
        if status == "DONE":
            already = bool(reg.get("duplicate")) and (reg.get("job") or {}).get("status") == "DONE"  # the stored file's earlier import had already finished when this approval arrived
            res |= {"outcome": "ALREADY_IMPORTED" if already else "IMPORTED",
                    "rows": {k: rowsq.get(k) for k in ("read", "posted", "held_total", "failed_validation", "duplicate_overlap_with_earlier_uploads")}}
        elif status == "FAILED":
            needs_mapping = view.get("errorCode") in ("NO_MATCHING_FORMAT", "MAPPING_PROPOSAL_FAILED")
            res |= {"outcome": "NEEDS_MAPPING" if needs_mapping else "FAILED", "reason": view.get("errorDetail")}
        else:
            res |= {"outcome": "STILL_RUNNING" if status not in ("CANCELLED",) else "CANCELLED"}
        out.append(res)
    return {"status": "OK", "files": out}
