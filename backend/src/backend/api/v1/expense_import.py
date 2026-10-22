"""Expense CSV import (kickoff S5a) under `/api/v1/cfo/expense-ledger/import`: a fixed template, a preview that writes nothing, and a commit.

Same gates as the ledger: `agent.cfo`, the CFO entitlement gate, and `financials.adjust` for the commit (no new permission key); the preview reads the ledger to flag
duplicates, so it needs only the read gate. Parsing, row validation and duplicate detection are `backend.services.expense_import` (pure). Imported rows are written through
the ledger repository as `pending_review` records with `origin = IMPORT`; confirming one is the ordinary review action, which needs `financials.adjust`. The raw CSV is never
stored: only the parsed fields of accepted rows, a short file reference (the start of its SHA-256) and the row number. Re-uploading the same file is safe: each row's
idempotency key is `import:<sha256>:<row>`, so nothing is created twice.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from calc_engine.repositories import expense_ledger_repo as ledger
from calc_engine.repositories.expense_ledger_repo import NewRecord

from backend.api.v1.cfo import _require_cfo_entitlement
from backend.api.v1.expense_ledger import READ_CODE, _iso, _log_write, _require_write
from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CFO
from backend.services import expense_import as imp
from backend.services import expense_ledger_rules as rules

router = APIRouter(prefix="/api/v1/cfo/expense-ledger/import")


@router.get("/template", response_class=PlainTextResponse)
def get_template(ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> PlainTextResponse:
    """The fixed header row. Amounts are rupees (1200 or 1200.50); a refund or credit note is entered through the refund action, not imported."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=READ_CODE)
    return PlainTextResponse(imp.template_csv(), headers={"Content-Disposition": 'attachment; filename="expense-import-template.csv"'}, media_type="text/csv")


async def _read(file: UploadFile) -> bytes:
    return await file.read(imp.MAX_BYTES + 1)  # never more than one byte past the limit


def _classify(tenant: Any, parsed: imp.ParseResult) -> list[imp.Classified]:
    valid = [r for r in parsed.rows if not r.errors and r.date is not None]
    existing = []
    if valid:
        dates = [r.date for r in valid if r.date is not None]
        existing = ledger.import_candidates(tenant, date_from=min(dates), date_to=max(dates), source_references=[r.reference for r in valid if r.reference])
    return imp.classify(parsed.rows, existing)


def _row_json(c: imp.Classified) -> dict[str, object]:
    r = c.row
    return {
        "row": r.number, "status": c.status, "errors": r.errors, "note": c.note, "matchedExpenseIds": c.matches, "date": _iso(r.date), "vendor": r.vendor,
        "description": r.description, "category": r.category, "amountPaise": r.amount_paise, "sourceId": r.source_id, "channel": r.channel,
    }


def _summary(parsed: imp.ParseResult, rows: list[imp.Classified]) -> dict[str, object]:
    counts: dict[str, int] = {imp.OK: 0, imp.ERROR: 0, imp.DUPLICATE: 0, imp.PROBABLE_MATCH: 0}
    for c in rows:
        counts[c.status] += 1
    return {"fileSha256": parsed.sha256, "rowCount": len(rows), "counts": counts, "fileErrors": parsed.file_errors, "rows": [_row_json(c) for c in rows]}


@router.post("/preview")
async def preview(file: UploadFile, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """Validates the file and reports every row (errors, duplicates, probable matches). Writes nothing at all: no ledger row, no run row."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=READ_CODE)
    parsed = imp.parse_csv(await _read(file))
    return _summary(parsed, [] if parsed.file_errors else _classify(ctx.tenant_id, parsed))


@router.post("/commit")
async def commit(file: UploadFile, skip_invalid: bool = False, ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    """Writes the accepted rows as `pending_review` records. A file with invalid rows is refused whole unless `skip_invalid=true`; exact source-id duplicates are skipped and
    listed; probable matches are written and flagged (never dropped). Safe to repeat with the same file."""
    tenant = _require_write(ctx)
    parsed = imp.parse_csv(await _read(file))
    if parsed.file_errors:
        raise HTTPException(status_code=422, detail={"code": "FILE_REFUSED", "errors": parsed.file_errors})
    rows = _classify(tenant, parsed)
    invalid = [c for c in rows if c.status == imp.ERROR]
    if invalid and not skip_invalid:
        raise HTTPException(status_code=422, detail={"code": "ROWS_INVALID", "rows": [_row_json(c) for c in invalid]})
    created: list[str] = []
    replayed = 0
    for c in rows:
        if c.status not in (imp.OK, imp.PROBABLE_MATCH) or c.row.date is None:
            continue
        r = c.row
        category = rules.CATEGORIES[r.category or ""]
        flag = (f":probable:{c.matches[0]}" if c.matches else ":probable") if c.status == imp.PROBABLE_MATCH else ""
        reference = ((f"import:{r.source_id}" if r.source_id else f"import:{parsed.sha256[:12]}:row{r.number}") + flag)[: rules.SOURCE_REFERENCE_MAX]
        result = ledger.insert_record(
            tenant,
            NewRecord(
                effective_date=r.date, category=r.category or "", cost_class=category.cost_class, treatment=category.treatment, amount_paise=r.amount_paise or 0,
                vendor=r.vendor, description=r.description, channel_scope=r.channel, origin="IMPORT", source_validated=False, source_reference=reference,
            ),
            review_state="pending_review", created_by=ctx.app_user_id, idempotency_key=f"import:{parsed.sha256}:{r.number}",
        )
        if result.replayed:
            replayed += 1
        else:
            created.append(str(result.expense_id))
    if created:
        _log_write(ctx)
    return {**_summary(parsed, rows), "created": created, "alreadyImported": replayed, "state": "pending_review"}
