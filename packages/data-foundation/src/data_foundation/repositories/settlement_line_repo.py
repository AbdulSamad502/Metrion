"""settlement_line repository (write side) — data-foundation.md §1.3. Mirrors
sales_line_repo.insert_sales_line's exact shape/contract."""

from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from data_foundation.repositories import line_component_repo
from data_foundation.repositories.tenant_context import tenant_scope
from data_foundation.types import ParsedRow

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


def _settlement_params(
    new_id: UUID,
    tenant_id: UUID,
    *,
    ingestion_run_id: UUID,
    marketplace: str,
    canonical_fields: dict[str, object],
    source_row_number: int,
    source_row_json: dict[str, str],
    confidence: str,
) -> dict[str, object]:
    return {
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
    }


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
            _settlement_params(
                new_id, tenant_id, ingestion_run_id=ingestion_run_id, marketplace=marketplace,
                canonical_fields=canonical_fields, source_row_number=source_row_number,
                source_row_json=source_row_json, confidence=confidence,
            ),
        )
    return new_id


def insert_settlement_lines_with_components_on(
    conn: Connection,
    tenant_id: UUID,
    *,
    ingestion_run_id: UUID,
    marketplace: str,
    confidence: str,
    rows: Sequence[ParsedRow],
) -> list[UUID]:
    """Settlement-side twin of `sales_line_repo.insert_sales_lines_with_components_on` (open connection)."""
    ids = [uuid4() for _ in rows]
    line_params = [
        _settlement_params(
            line_id, tenant_id, ingestion_run_id=ingestion_run_id, marketplace=marketplace,
            canonical_fields=r.canonical_fields, source_row_number=r.source_row_number,
            source_row_json=r.source_row_json, confidence=confidence,
        )
        for line_id, r in zip(ids, rows)
    ]
    if line_params:
        conn.execute(_INSERT_SQL, line_params)
    line_component_repo.insert_components_on(
        conn, tenant_id, parent_key="settlement_line_id", items=[(i, r.components) for i, r in zip(ids, rows)]
    )
    return ids


def insert_settlement_lines_with_components(
    tenant_id: UUID,
    *,
    ingestion_run_id: UUID,
    marketplace: str,
    confidence: str,
    rows: Sequence[ParsedRow],
) -> list[UUID]:
    """Settlement-side twin of `sales_line_repo.insert_sales_lines_with_components` - one
    transaction, two executemany round trips, all-or-nothing for the file."""
    with tenant_scope(tenant_id) as conn:
        return insert_settlement_lines_with_components_on(
            conn, tenant_id, ingestion_run_id=ingestion_run_id, marketplace=marketplace, confidence=confidence, rows=rows
        )


_COUNT_FOR_RUN_SQL = text("SELECT count(*) FROM settlement_line WHERE tenant_id = :tenant_id AND ingestion_run_id = :run_id")

_PAGE_FOR_RUN_SQL = text(
    """
    SELECT id, order_ref, line_ref, settlement_id, gross_settlement_amount, currency, settlement_date,
           document_type, source_row_number, confidence
    FROM settlement_line
    WHERE tenant_id = :tenant_id AND ingestion_run_id = :run_id
    ORDER BY source_row_number, id
    LIMIT :limit OFFSET :offset
    """
)


def count_for_run(tenant_id: UUID, run_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        return int(conn.execute(_COUNT_FOR_RUN_SQL, {"tenant_id": str(tenant_id), "run_id": str(run_id)}).scalar_one())


def page_for_run(tenant_id: UUID, run_id: UUID, *, limit: int, offset: int) -> list[dict[str, object]]:
    """One page of the settlement lines an ingestion run persisted (persisted columns only)."""
    with tenant_scope(tenant_id) as conn:
        return [
            dict(r)
            for r in conn.execute(
                _PAGE_FOR_RUN_SQL, {"tenant_id": str(tenant_id), "run_id": str(run_id), "limit": limit, "offset": offset}
            ).mappings()
        ]
