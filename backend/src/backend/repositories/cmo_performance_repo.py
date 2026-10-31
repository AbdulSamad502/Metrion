"""CMO 3.0 B8: the seller's own confirmations (SKU link, go-live date) and the plain reads of their uploaded sales rows that a performance observation needs. Tenant-scoped (RLS), append-only writes,
no model, no inference. Money is not touched: the only figure read from sales rows is a count of distinct order references."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.tenant_context import tenant_scope

_REPORT_SKUS = text(
    """
    SELECT sku, max(item_title) AS item_title, count(*) AS rows, min(order_date) AS first_order, max(order_date) AS last_order
    FROM sales_line WHERE tenant_id = :t AND upper(marketplace) = :mp AND sku IS NOT NULL AND btrim(sku) <> ''
    GROUP BY sku ORDER BY count(*) DESC, sku LIMIT :limit
    """
)
_REPORT_SKU_EXISTS = text("SELECT 1 FROM sales_line WHERE tenant_id = :t AND upper(marketplace) = :mp AND sku = :sku LIMIT 1")
_INSERT_LINK = text(
    "INSERT INTO cmo_listing_sku_link (tenant_id, sku, marketplace, report_sku, confirmed_by) VALUES (:t, :sku, :mp, :rs, :u) RETURNING id, confirmed_at"
)
_CURRENT_LINK = text(
    "SELECT id, report_sku, confirmed_at FROM cmo_listing_sku_link WHERE tenant_id = :t AND sku = :sku AND marketplace = :mp ORDER BY confirmed_at DESC, id DESC LIMIT 1"
)
_INSERT_GOLIVE = text(
    "INSERT INTO cmo_listing_golive (tenant_id, generation_id, marketplace, went_live_on, confirmed_by) VALUES (:t, :g, :mp, :d, :u) RETURNING id, confirmed_at"
)
_GOLIVES = text(
    """
    SELECT DISTINCT ON (l.generation_id) l.generation_id, l.went_live_on, l.confirmed_at
    FROM cmo_listing_golive l JOIN cmo_generation g ON g.tenant_id = l.tenant_id AND g.id = l.generation_id
    WHERE l.tenant_id = :t AND g.sku = :sku AND g.marketplace = :mp
    ORDER BY l.generation_id, l.confirmed_at DESC, l.id DESC
    """
)
_DATA_RANGE = text("SELECT min(order_date) AS lo, max(order_date) AS hi FROM sales_line WHERE tenant_id = :t AND upper(marketplace) = :mp AND order_date IS NOT NULL")
_ORDERS = text(
    """
    SELECT count(DISTINCT order_ref) FILTER (WHERE order_ref IS NOT NULL) AS orders, count(*) FILTER (WHERE order_ref IS NULL) AS unreferenced
    FROM sales_line WHERE tenant_id = :t AND upper(marketplace) = :mp AND sku = :sku AND order_date BETWEEN :a AND :b
    """
)


def report_sku_candidates(tenant_id: UUID, marketplace: str, limit: int = 30) -> list[dict[str, Any]]:
    """The SKUs that actually appear in THIS seller's uploaded reports for the marketplace (what they can choose from), with the title in the report and the row count."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_REPORT_SKUS, {"t": tenant_id, "mp": marketplace, "limit": limit}).all()
    return [{"reportSku": str(r.sku), "reportTitle": r.item_title, "rows": int(r.rows), "firstOrder": r.first_order, "lastOrder": r.last_order} for r in rows]


def report_sku_exists(tenant_id: UUID, marketplace: str, report_sku: str) -> bool:
    with tenant_scope(tenant_id) as conn:
        return conn.execute(_REPORT_SKU_EXISTS, {"t": tenant_id, "mp": marketplace, "sku": report_sku}).first() is not None


def add_link(tenant_id: UUID, user_id: UUID, *, sku: str, marketplace: str, report_sku: str) -> dict[str, Any]:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_INSERT_LINK, {"t": tenant_id, "sku": sku, "mp": marketplace, "rs": report_sku, "u": user_id}).one()
    return {"id": str(r.id), "confirmedAt": r.confirmed_at}


def current_link(tenant_id: UUID, sku: str, marketplace: str) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_CURRENT_LINK, {"t": tenant_id, "sku": sku, "mp": marketplace}).first()
    return {"id": str(r.id), "reportSku": str(r.report_sku), "confirmedAt": r.confirmed_at} if r else None


def add_golive(tenant_id: UUID, user_id: UUID, *, generation_id: UUID, marketplace: str, went_live_on: date) -> dict[str, Any]:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_INSERT_GOLIVE, {"t": tenant_id, "g": generation_id, "mp": marketplace, "d": went_live_on, "u": user_id}).one()
    return {"id": str(r.id), "confirmedAt": r.confirmed_at}


def golives(tenant_id: UUID, sku: str, marketplace: str) -> list[dict[str, Any]]:
    """The newest go-live statement per saved version of this product on this marketplace."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_GOLIVES, {"t": tenant_id, "sku": sku, "mp": marketplace}).all()
    return [{"generationId": str(r.generation_id), "wentLiveOn": r.went_live_on, "confirmedAt": r.confirmed_at} for r in rows]


def data_range(tenant_id: UUID, marketplace: str) -> tuple[date, date] | None:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_DATA_RANGE, {"t": tenant_id, "mp": marketplace}).first()
    return (r.lo, r.hi) if r and r.lo is not None and r.hi is not None else None


def orders_between(tenant_id: UUID, marketplace: str, report_sku: str, start: date, end: date) -> int | None:
    """Distinct order references for this report SKU in the window. None when any row in the window has no order reference (the count would be unreliable)."""
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_ORDERS, {"t": tenant_id, "mp": marketplace, "sku": report_sku, "a": start, "b": end}).one()
    return None if int(r.unreferenced or 0) > 0 else int(r.orders or 0)
