"""settlement_line repository (write side) — data-foundation.md §1.3. Mirrors
sales_line_repo.insert_sales_line's exact shape/contract."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO settlement_line
        (id, tenant_id, ingestion_run_id, marketplace, order_ref, line_ref, settlement_id,
         gross_settlement_amount, currency, settlement_date, document_type, source_row_number,
         source_row_json, confidence)
    VALUES
        (:id, :tenant_id, :ingestion_run_id, :marketplace, :order_ref, :line_ref, :settlement_id,
         :gross_settlement_amount, :currency, :settlement_date, :document_type, :source_row_number,
         CAST(:source_row_json AS jsonb), :confidence)
    """
)


def insert_settlement_line(
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
                "settlement_id": canonical_fields.get("settlement_id"),
                "gross_settlement_amount": canonical_fields.get("gross_settlement_amount"),
                "currency": canonical_fields.get("currency") or "INR",
                "settlement_date": canonical_fields.get("settlement_date"),
                "document_type": canonical_fields.get("document_type"),
                "source_row_number": source_row_number,
                "source_row_json": json.dumps(source_row_json),
                "confidence": confidence,
            },
        )
    return new_id
