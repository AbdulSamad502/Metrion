"""sales_line repository — data-foundation.md §1.3 (quantity nullable, Category C amendment)."""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from data_foundation.repositories import line_component_repo
from data_foundation.repositories.tenant_context import tenant_scope
from data_foundation.types import ParsedRow

if TYPE_CHECKING:
    from data_foundation.ingestion.duplicates import ExistingEntry

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


def _sales_params(
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
    }


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
            _sales_params(
                new_id, tenant_id, ingestion_run_id=ingestion_run_id, marketplace=marketplace,
                canonical_fields=canonical_fields, source_row_number=source_row_number,
                source_row_json=source_row_json, confidence=confidence,
            ),
        )
    return new_id


def insert_sales_lines_with_components_on(
    conn: Connection,
    tenant_id: UUID,
    *,
    ingestion_run_id: UUID,
    marketplace: str,
    confidence: str,
    rows: Sequence[ParsedRow],
) -> list[UUID]:
    """Same bulk write as `insert_sales_lines_with_components`, on an ALREADY-OPEN `tenant_scope()`
    connection, so a streaming ingestion can write chunk after chunk inside ONE transaction
    (all-or-nothing for the file) without holding more than a chunk of rows in memory."""
    ids = [uuid4() for _ in rows]
    line_params = [
        _sales_params(
            line_id, tenant_id, ingestion_run_id=ingestion_run_id, marketplace=marketplace,
            canonical_fields=r.canonical_fields, source_row_number=r.source_row_number,
            source_row_json=r.source_row_json, confidence=confidence,
        )
        for line_id, r in zip(ids, rows)
    ]
    if line_params:
        conn.execute(_INSERT_SQL, line_params)
    line_component_repo.insert_components_on(
        conn, tenant_id, parent_key="sales_line_id", items=[(i, r.components) for i, r in zip(ids, rows)]
    )
    return ids


def insert_sales_lines_with_components(
    tenant_id: UUID,
    *,
    ingestion_run_id: UUID,
    marketplace: str,
    confidence: str,
    rows: Sequence[ParsedRow],
) -> list[UUID]:
    """Persists many accepted rows (and their components) in ONE transaction with two
    executemany round trips, instead of two transactions + one round trip per component per
    row. All-or-nothing for the file: a failure part-way persists none of it (the per-row
    path used to leave a partial file behind). Returns the new ids in `rows` order."""
    with tenant_scope(tenant_id) as conn:
        return insert_sales_lines_with_components_on(
            conn, tenant_id, ingestion_run_id=ingestion_run_id, marketplace=marketplace, confidence=confidence, rows=rows
        )


_EXISTING_ENTRIES_SQL = text(
    """
    SELECT s.order_ref, s.line_ref, s.invoice_ref, s.sku, s.marketplace_item_id, s.document_type, s.transaction_type, s.source_row_json,
           ir.adapter_id, cm.fingerprint
    FROM sales_line s
    JOIN ingestion_run ir ON ir.id = s.ingestion_run_id
    LEFT JOIN column_mapping cm ON ir.adapter_id LIKE 'mapped.%' AND cm.tenant_id = s.tenant_id AND cm.id::text = substr(ir.adapter_id, 8)
    WHERE s.tenant_id = :tenant_id AND s.marketplace = :marketplace
      AND (s.order_ref = ANY(CAST(:order_refs AS text[])) OR (:include_null AND s.order_ref IS NULL))
    """
)


def existing_entries_for_orders(
    tenant_id: UUID, marketplace: str, family: str, order_refs: Collection[str | None]
) -> list["ExistingEntry"]:
    """Identity digest + raw-row hash of already-ingested sales rows **of the same report family** that could collide with a chunk
    carrying these `order_ref`s (cfo-data-intelligence.md §6.3). Rows from a different kind of report (an orders report vs a TCS
    report on the same sub-order) are not candidates. Cost scales with the chunk, not the history."""
    from data_foundation.ingestion.duplicates import existing_sales_entry, report_family

    wanted = sorted({o for o in order_refs if o is not None})
    include_null = any(o is None for o in order_refs)
    if not wanted and not include_null:
        return []
    out: list[ExistingEntry] = []
    with tenant_scope(tenant_id) as conn:
        for r in conn.execute(
            _EXISTING_ENTRIES_SQL,
            {"tenant_id": str(tenant_id), "marketplace": marketplace, "order_refs": wanted, "include_null": include_null},
        ):
            m = r._mapping
            if m["adapter_id"].startswith("mapped.") and not m["fingerprint"]:
                continue  # a mapping that no longer exists cannot be matched to a family; never guess
            if report_family(m["adapter_id"], m["fingerprint"]) != family:
                continue
            entry = existing_sales_entry(marketplace, family, dict(m), m["source_row_json"] or {})
            if entry is not None:
                out.append(entry)
    return out


_EXISTING_KEYS_FOR_ORDERS_SQL = text(
    """
    SELECT marketplace, order_ref, line_ref, invoice_ref FROM sales_line
    WHERE tenant_id = :tenant_id AND order_ref = ANY(CAST(:order_refs AS text[]))
    """
)
_EXISTING_KEYS_NULL_ORDER_SQL = text(
    "SELECT marketplace, order_ref, line_ref, invoice_ref FROM sales_line "
    "WHERE tenant_id = :tenant_id AND order_ref IS NULL"
)


def existing_natural_keys_for_orders(
    tenant_id: UUID, order_refs: Collection[str | None]
) -> list[tuple[str, str | None, str | None, str | None]]:
    """The existing natural keys that can possibly collide with an incoming file whose rows
    carry exactly these `order_ref`s — result-equivalent to `existing_natural_keys()` for
    `find_natural_key_duplicates()` (a key only matters if the incoming file has a key with the
    same `order_ref`), but cost scales with the incoming file instead of the tenant's whole
    history (uses `sales_line_tenant_natural_key_idx`). A `None` in `order_refs` also pulls the
    tenant's NULL-`order_ref` keys, since `dedup.natural_key()` allows a key with no `order_ref`."""
    wanted = sorted({o for o in order_refs if o is not None})
    keys: list[tuple[str, str | None, str | None, str | None]] = []
    with tenant_scope(tenant_id) as conn:
        if wanted:
            keys.extend(
                tuple(row)
                for row in conn.execute(_EXISTING_KEYS_FOR_ORDERS_SQL, {"tenant_id": str(tenant_id), "order_refs": wanted})
            )
        if any(o is None for o in order_refs):
            keys.extend(tuple(row) for row in conn.execute(_EXISTING_KEYS_NULL_ORDER_SQL, {"tenant_id": str(tenant_id)}))
    return keys


def existing_natural_keys(tenant_id: UUID) -> list[tuple[str, str | None, str | None, str | None]]:
    """Feeds `ingestion.dedup.find_natural_key_duplicates()` (§6 rule 4)."""
    with tenant_scope(tenant_id) as conn:
        return [tuple(row) for row in conn.execute(_EXISTING_NATURAL_KEYS_SQL, {"tenant_id": str(tenant_id)})]


_COUNT_FOR_RUN_SQL = text("SELECT count(*) FROM sales_line WHERE tenant_id = :tenant_id AND ingestion_run_id = :run_id")

_PAGE_FOR_RUN_SQL = text(
    """
    SELECT id, order_ref, line_ref, invoice_ref, sku, marketplace_item_id, item_title, hsn_sac,
           quantity, gross_item_amount, taxable_amount, total_invoice_amount, currency, order_date,
           dispatch_date, invoice_date, document_type, supply_type, transaction_type, payment_method,
           return_status, source_row_number, confidence
    FROM sales_line
    WHERE tenant_id = :tenant_id AND ingestion_run_id = :run_id
    ORDER BY source_row_number, id
    LIMIT :limit OFFSET :offset
    """
)


def count_for_run(tenant_id: UUID, run_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        return int(conn.execute(_COUNT_FOR_RUN_SQL, {"tenant_id": str(tenant_id), "run_id": str(run_id)}).scalar_one())


def page_for_run(tenant_id: UUID, run_id: UUID, *, limit: int, offset: int) -> list[dict[str, object]]:
    """One page of the sales lines an ingestion run persisted, in source-file row order. The
    persisted columns only — `source_row_json` (the raw seller row) is deliberately not selected."""
    with tenant_scope(tenant_id) as conn:
        return [
            dict(r)
            for r in conn.execute(
                _PAGE_FOR_RUN_SQL, {"tenant_id": str(tenant_id), "run_id": str(run_id), "limit": limit, "offset": offset}
            ).mappings()
        ]
