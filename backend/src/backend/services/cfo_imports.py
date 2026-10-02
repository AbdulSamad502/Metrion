"""Read-only import viewer — what Metrion actually parsed and persisted for an uploaded report.

`GET /cfo/imports` / `GET /cfo/imports/{report_file_id}` are built on this. Two rules:

* **Persisted values only.** Every field below is a column of `report_file`, `ingestion_run`,
  `sales_line`/`settlement_line`, `line_component` or `validation_finding`. Nothing is derived from
  the original upload, no field is invented, and the raw seller row (`source_row_json`), the
  storage location (`storage_uri`) and the content hash are never returned.
* **No money arithmetic** (CLAUDE.md hard rule). Amounts are the persisted paise integers passed
  through unchanged; the only arithmetic is on ROW COUNTS (accepted − persisted = duplicates skipped).

Nothing here writes: viewing an import never creates an ingestion run, even for a re-upload.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from data_foundation.repositories import (
    ingestion_run_repo,
    line_component_repo,
    report_file_repo,
    sales_line_repo,
    settlement_line_repo,
    validation_finding_repo,
)

# Upper bound on diagnostics returned in one response — findings are advisory context, not a table.
_MAX_FINDINGS = 200


def _iso(value: object) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None if value is None else str(value)


def _counts(run: dict[str, object] | None, persisted: int) -> dict[str, int | None]:
    """Row counts from the ingestion run. `duplicate` is the accepted-but-not-persisted gap (rows
    skipped as natural-key duplicates of an earlier import) — only meaningful once the run finished."""
    if run is None:
        return {"read": None, "accepted": None, "rejected": None, "duplicate": None, "persisted": persisted}
    accepted = run["row_count_accepted"]
    duplicate = None
    if run["status"] in ("VALIDATED", "SUPERSEDED") and isinstance(accepted, int) and persisted <= accepted:
        duplicate = accepted - persisted
    return {
        "read": run["row_count_read"],
        "accepted": accepted,
        "rejected": run["row_count_rejected"],
        "duplicate": duplicate,
        "persisted": persisted,
    }


def _summary(file: dict[str, object], run: dict[str, object] | None, persisted: int) -> dict[str, object]:
    return {
        "reportFileId": str(file["id"]),
        "ingestionRunId": str(run["id"]) if run else None,
        "filename": file["original_filename"],
        "marketplace": file["marketplace"],
        "reportCategory": file["report_category"],
        "adapter": run["adapter_id"] if run else None,
        "adapterVersion": run["adapter_version"] if run else None,
        "uploadedAt": _iso(file["uploaded_at"]),
        "status": run["status"] if run else None,
        "counts": _counts(run, persisted),
    }


def list_imports(tenant_id: UUID, *, limit: int = 100) -> list[dict[str, object]]:
    """This tenant's imports, newest first. Persisted-row counts come from one count per file."""
    out: list[dict[str, object]] = []
    for row in report_file_repo.list_report_files_with_latest_run(tenant_id, limit=limit):
        run = (
            {
                "id": row["run_id"], "adapter_id": row["adapter_id"], "adapter_version": row["adapter_version"],
                "status": row["status"], "row_count_read": row["row_count_read"],
                "row_count_accepted": row["row_count_accepted"], "row_count_rejected": row["row_count_rejected"],
            }
            if row["run_id"] is not None
            else None
        )
        persisted = 0
        if run is not None:
            counter = settlement_line_repo.count_for_run if row["report_category"] == "SETTLEMENT" else sales_line_repo.count_for_run
            persisted = counter(tenant_id, row["run_id"])
        out.append(_summary(row, run, persisted))
    return out


def _component_to_dict(c: dict[str, object]) -> dict[str, object]:
    rate = c["rate_pct"]
    return {
        "kind": c["component_kind"],
        "code": c["component_code"],
        "side": c["source_side"],
        "amountPaise": c["amount"],
        "taxAmountPaise": c["tax_amount"],
        "ratePct": str(rate) if isinstance(rate, Decimal) else rate,
    }


def _sales_row(r: dict[str, object], components: list[dict[str, object]]) -> dict[str, object]:
    return {
        "salesLineId": str(r["id"]),
        "sourceRowNumber": r["source_row_number"],
        "orderRef": r["order_ref"], "lineRef": r["line_ref"], "invoiceRef": r["invoice_ref"],
        "sku": r["sku"], "marketplaceItemId": r["marketplace_item_id"], "itemTitle": r["item_title"],
        "hsnSac": r["hsn_sac"], "quantity": r["quantity"],
        "grossItemAmountPaise": r["gross_item_amount"], "taxableAmountPaise": r["taxable_amount"],
        "totalInvoiceAmountPaise": r["total_invoice_amount"], "currency": r["currency"],
        "orderDate": _iso(r["order_date"]), "dispatchDate": _iso(r["dispatch_date"]), "invoiceDate": _iso(r["invoice_date"]),
        "documentType": r["document_type"], "supplyType": r["supply_type"], "transactionType": r["transaction_type"],
        "paymentMethod": r["payment_method"], "returnStatus": r["return_status"], "confidence": r["confidence"],
        "components": [_component_to_dict(c) for c in components],
    }


def _settlement_row(r: dict[str, object], components: list[dict[str, object]]) -> dict[str, object]:
    return {
        "settlementLineId": str(r["id"]),
        "sourceRowNumber": r["source_row_number"],
        "orderRef": r["order_ref"], "lineRef": r["line_ref"], "settlementId": r["settlement_id"],
        "grossSettlementAmountPaise": r["gross_settlement_amount"], "currency": r["currency"],
        "settlementDate": _iso(r["settlement_date"]), "documentType": r["document_type"], "confidence": r["confidence"],
        "components": [_component_to_dict(c) for c in components],
    }


def get_import(tenant_id: UUID, report_file_id: UUID, *, limit: int, offset: int) -> dict[str, object] | None:
    """One import with a page of its persisted lines. `None` when the report does not exist for
    this tenant (another tenant's report is indistinguishable from a missing one)."""
    file = report_file_repo.get_report_file(tenant_id, report_file_id)
    if file is None:
        return None
    run = ingestion_run_repo.latest_run_for_report_file(tenant_id, report_file_id)
    is_settlement = file["report_category"] == "SETTLEMENT"

    rows: list[dict[str, object]] = []
    persisted = 0
    findings: list[dict[str, object]] = []
    findings_total = 0
    if run is not None:
        run_id = run["id"]
        assert isinstance(run_id, UUID)
        if is_settlement:
            persisted = settlement_line_repo.count_for_run(tenant_id, run_id)
            page = settlement_line_repo.page_for_run(tenant_id, run_id, limit=limit, offset=offset)
            comps = line_component_repo.components_for_lines(
                tenant_id, parent_key="settlement_line_id", parent_ids=[r["id"] for r in page]  # type: ignore[misc]
            )
            rows = [_settlement_row(r, comps.get(str(r["id"]), [])) for r in page]
        else:
            persisted = sales_line_repo.count_for_run(tenant_id, run_id)
            page = sales_line_repo.page_for_run(tenant_id, run_id, limit=limit, offset=offset)
            comps = line_component_repo.components_for_lines(
                tenant_id, parent_key="sales_line_id", parent_ids=[r["id"] for r in page]  # type: ignore[misc]
            )
            rows = [_sales_row(r, comps.get(str(r["id"]), [])) for r in page]
        findings_total = validation_finding_repo.count_for_run(tenant_id, run_id)
        findings = [
            {"ruleId": f["rule_id"], "severity": f["severity"], "message": f["message"], "sourceRowNumber": f["source_row_number"]}
            for f in validation_finding_repo.page_for_run(tenant_id, run_id, limit=_MAX_FINDINGS, offset=0)
        ]

    body = _summary(file, run, persisted)
    body.update(
        {
            "lineKind": "SETTLEMENT_LINE" if is_settlement else "SALES_LINE",
            "rows": rows,
            "pagination": {"limit": limit, "offset": offset, "total": persisted},
            "rejected": {
                "count": run["row_count_rejected"] if run else None,
                # The live upload path records HOW MANY rows were rejected but does not persist the
                # per-row reasons. When findings exist they are returned; when none exist, the UI is
                # told so explicitly instead of being left to imply a rejection has no reason.
                "diagnosticsPersisted": findings_total > 0,
                "findingsTotal": findings_total,
                "findings": findings,
            },
            # Extension point: raw-file retrieval is not exposed by the storage layer, and this
            # viewer deliberately does not read `storage_uri` itself.
            "originalCsv": {
                "available": False,
                "reason": "Retrieving the original uploaded file is not supported yet.",
            },
        }
    )
    return body
