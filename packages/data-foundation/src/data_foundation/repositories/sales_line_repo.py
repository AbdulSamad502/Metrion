"""sales_line repository — data-foundation.md §1.3 (quantity nullable, Category C amendment)."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO sales_line
        (id, tenant_id, ingestion_run_id, marketplace, order_ref, line_ref, invoice_ref, sku,
         marketplace_item_id, item_title, hsn_sac, quantity, gross_item_amount, taxable_amount,
         total_invoice_amount, currency, order_date, dispatch_date, invoice_date, document_type,
         supply_type, transaction_type, payment_method, return_status, source_row_number,
         source_row_json, confidence)
    VALUES
        (:id, :tenant_id, :ingestion_run_id, :marketplace, :order_ref, :line_ref, :invoice_ref, :sku,
         :marketplace_item_id, :item_title, :hsn_sac, :quantity, :gross_item_amount, :taxable_amount,
         :total_invoice_amount, :currency, :order_date, :dispatch_date, :invoice_date, :document_type,
         :supply_type, :transaction_type, :payment_method, :return_status, :source_row_number,
         CAST(:source_row_json AS jsonb), :confidence)
    """
)

_EXISTING_NATURAL_KEYS_SQL = text(
    "SELECT marketplace, order_ref, line_ref, invoice_ref FROM sales_line WHERE tenant_id = :tenant_id"
)


def insert_sales_line(
    tenant_id: UUID,
    *,
    ingestion_run_id: UUID,
    marketplace: str,
    canonical_fields: dict[str, object],
    source_row_number: int,
    source_row_json: dict[str, str],
    confidence: str,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(new_id),
                "tenant_id": str(tenant_id),
                "ingestion_run_id": str(ingestion_run_id),
                "marketplace": marketplace,
                "order_ref": canonical_fields.get("order_ref"),
                "line_ref": canonical_fields.get("line_ref"),
                "invoice_ref": canonical_fields.get("invoice_ref"),
                "sku": canonical_fields.get("sku"),
                "marketplace_item_id": canonical_fields.get("marketplace_item_id"),
                "item_title": canonical_fields.get("item_title"),
                "hsn_sac": canonical_fields.get("hsn_sac"),
                "quantity": canonical_fields.get("quantity"),
                "gross_item_amount": canonical_fields.get("gross_item_amount"),
                "taxable_amount": canonical_fields.get("taxable_amount"),
                "total_invoice_amount": canonical_fields.get("total_invoice_amount"),
                "currency": canonical_fields.get("currency") or "INR",
                "order_date": canonical_fields.get("order_date"),
                "dispatch_date": canonical_fields.get("dispatch_date"),
                "invoice_date": canonical_fields.get("invoice_date"),
                "document_type": canonical_fields.get("document_type"),
                "supply_type": canonical_fields.get("supply_type"),
                "transaction_type": canonical_fields.get("transaction_type"),
                "payment_method": canonical_fields.get("payment_method"),
                "return_status": canonical_fields.get("return_status"),
                "source_row_number": source_row_number,
                "source_row_json": json.dumps(source_row_json),
                "confidence": confidence,
            },
        )
    return new_id


def existing_natural_keys(tenant_id: UUID) -> list[tuple[str, str | None, str | None, str | None]]:
    """Feeds `ingestion.dedup.find_natural_key_duplicates()` (§6 rule 4)."""
    with tenant_scope(tenant_id) as conn:
        return [tuple(row) for row in conn.execute(_EXISTING_NATURAL_KEYS_SQL, {"tenant_id": str(tenant_id)})]
