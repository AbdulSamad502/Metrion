"""CMO 3.0 B8: the seller's own confirmations (SKU link, go-live date) and the plain reads of their uploaded sales rows that a performance observation needs. Tenant-scoped (RLS), append-only writes,
no model, no inference. Money is not touched: the only figure read from sales rows is a count of distinct order references."""

from __future__ import annotations

from datetime import date, timedelta
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


# ------------------------------------------------------------------------------------------------ CMO 3.0 M8: imported performance reports, the window setting, and the history of the seller's statements
_SKU_IN_IMPORTS = text("SELECT 1 FROM cmo_perf_line WHERE tenant_id = :t AND marketplace = :mp AND report_sku = :sku LIMIT 1")
_IMPORT_SKUS = text(
    """
    SELECT report_sku AS sku, count(*) AS rows, min(report_date) AS first_day, max(report_date) AS last_day
    FROM cmo_perf_line WHERE tenant_id = :t AND marketplace = :mp GROUP BY report_sku ORDER BY count(*) DESC, report_sku LIMIT :limit
    """
)
_IMPORT_BY_SHA = text("SELECT id, marketplace, source_name, imported_at, period_start, period_end FROM cmo_perf_import WHERE tenant_id = :t AND sha256 = :h")
_INSERT_IMPORT = text(
    """
    INSERT INTO cmo_perf_import (tenant_id, marketplace, source_name, sha256, period_start, period_end, rows_saved, rows_skipped, metrics, imported_by)
    VALUES (:t, :mp, :name, :h, :a, :b, :saved, :skipped, :metrics, :u) RETURNING id, imported_at
    """
)
_INSERT_LINE = text(
    """
    INSERT INTO cmo_perf_line (tenant_id, import_id, marketplace, report_sku, report_date, impressions, clicks, orders, units, sales_paise)
    VALUES (:t, :i, :mp, :sku, :d, :impressions, :clicks, :orders, :units, :sales) ON CONFLICT (tenant_id, marketplace, report_sku, report_date) DO NOTHING
    """
)
_EXISTING = text(
    """
    SELECT report_sku, report_date, impressions, clicks, orders, units, sales_paise FROM cmo_perf_line
    WHERE tenant_id = :t AND marketplace = :mp AND report_date BETWEEN :a AND :b AND report_sku = ANY(:skus)
    """
)
_IMPORTS = text(
    """
    SELECT id, marketplace, source_name, period_start, period_end, rows_saved, rows_skipped, metrics, imported_at FROM cmo_perf_import
    WHERE tenant_id = :t AND (CAST(:mp AS text) IS NULL OR marketplace = :mp) ORDER BY imported_at DESC, id DESC LIMIT :limit
    """
)
_DAILY = text(
    """
    SELECT report_date AS d, count(*) AS rows,
           sum(impressions) AS impressions, count(impressions) AS n_impressions, sum(clicks) AS clicks, count(clicks) AS n_clicks,
           sum(orders) AS orders, count(orders) AS n_orders, sum(units) AS units, count(units) AS n_units, sum(sales_paise) AS sales, count(sales_paise) AS n_sales
    FROM cmo_perf_line
    WHERE tenant_id = :t AND report_date BETWEEN :a AND :b AND (CAST(:mp AS text) IS NULL OR marketplace = :mp)
      AND (CAST(:pairs AS text[]) IS NULL OR marketplace || '|' || report_sku = ANY(CAST(:pairs AS text[])))
    GROUP BY report_date ORDER BY report_date
    """
)
_COVER = text(
    """
    SELECT marketplace, period_start, period_end FROM cmo_perf_import
    WHERE tenant_id = :t AND period_end >= :a AND period_start <= :b AND (CAST(:mp AS text) IS NULL OR marketplace = :mp)
    """
)
_DATA_MARKETPLACES = text("SELECT DISTINCT marketplace FROM cmo_perf_import WHERE tenant_id = :t ORDER BY marketplace")
_LAST_IMPORT = text("SELECT max(imported_at) AS at, min(period_start) AS lo, max(period_end) AS hi FROM cmo_perf_import WHERE tenant_id = :t AND (CAST(:mp AS text) IS NULL OR marketplace = :mp)")
_SETTING = text("SELECT window_days, set_at FROM cmo_perf_setting WHERE tenant_id = :t ORDER BY set_at DESC, id DESC LIMIT 1")
_INSERT_SETTING = text("INSERT INTO cmo_perf_setting (tenant_id, window_days, set_by) VALUES (:t, :n, :u) RETURNING set_at")
_LINKS = text("SELECT sku, marketplace, report_sku, confirmed_by, confirmed_at FROM cmo_listing_sku_link WHERE tenant_id = :t ORDER BY confirmed_at DESC, id DESC")
_GOLIVE_HISTORY = text(
    """
    SELECT l.generation_id, l.marketplace, l.went_live_on, l.confirmed_by, l.confirmed_at, g.sku
    FROM cmo_listing_golive l JOIN cmo_generation g ON g.tenant_id = l.tenant_id AND g.id = l.generation_id
    WHERE l.tenant_id = :t ORDER BY l.confirmed_at DESC, l.id DESC
    """
)
COUNT_COLUMNS = ("impressions", "clicks", "orders", "units")


def import_skus(tenant_id: UUID, marketplace: str, limit: int = 30) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_IMPORT_SKUS, {"t": tenant_id, "mp": marketplace, "limit": limit}).all()
    return [{"reportSku": str(r.sku), "reportTitle": None, "rows": int(r.rows), "firstOrder": r.first_day, "lastOrder": r.last_day} for r in rows]


def sku_in_imports(tenant_id: UUID, marketplace: str, report_sku: str) -> bool:
    with tenant_scope(tenant_id) as conn:
        return conn.execute(_SKU_IN_IMPORTS, {"t": tenant_id, "mp": marketplace, "sku": report_sku}).first() is not None


def import_by_sha(tenant_id: UUID, sha256: str) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_IMPORT_BY_SHA, {"t": tenant_id, "h": sha256}).first()
    return {"id": str(r.id), "marketplace": r.marketplace, "sourceName": r.source_name, "importedAt": r.imported_at, "periodStart": r.period_start, "periodEnd": r.period_end} if r else None


def existing_lines(tenant_id: UUID, marketplace: str, skus: list[str], start: date, end: date) -> dict[tuple[str, date], dict[str, int | None]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_EXISTING, {"t": tenant_id, "mp": marketplace, "a": start, "b": end, "skus": skus}).all()
    return {(str(r.report_sku), r.report_date): {"impressions": r.impressions, "clicks": r.clicks, "orders": r.orders, "units": r.units, "sales": r.sales_paise} for r in rows}


def save_import(tenant_id: UUID, user_id: UUID, *, marketplace: str, source_name: str, sha256: str, period: tuple[date, date], metrics: list[str], lines: list[dict[str, Any]], skipped: int) -> dict[str, Any]:
    """One transaction: the import row, then its new lines. A line that already exists (same marketplace, SKU, date) is never overwritten. Raises sqlalchemy IntegrityError on a repeated file."""
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_INSERT_IMPORT, {"t": tenant_id, "mp": marketplace, "name": source_name, "h": sha256, "a": period[0], "b": period[1], "saved": len(lines), "skipped": skipped, "metrics": metrics, "u": user_id}).one()
        if lines:
            conn.execute(_INSERT_LINE, [{"t": tenant_id, "i": r.id, "mp": marketplace, "sku": x["sku"], "d": x["date"], **{m: x.get(m) for m in ("impressions", "clicks", "orders", "units")}, "sales": x.get("sales")} for x in lines])
    return {"id": str(r.id), "importedAt": r.imported_at}


def imports(tenant_id: UUID, marketplace: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_IMPORTS, {"t": tenant_id, "mp": marketplace, "limit": limit}).all()
    return [{"id": str(r.id), "marketplace": r.marketplace, "sourceName": r.source_name, "periodStart": r.period_start, "periodEnd": r.period_end, "rowsSaved": int(r.rows_saved),
             "rowsSkipped": int(r.rows_skipped), "metrics": list(r.metrics), "importedAt": r.imported_at} for r in rows]


def daily(tenant_id: UUID, start: date, end: date, marketplace: str | None = None, pairs: list[str] | None = None) -> list[dict[str, Any]]:
    """One row per day: the sum of each metric over the rows in scope, and how many of those rows carry it. `pairs` = 'MARKETPLACE|report sku' strings (None = everything)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_DAILY, {"t": tenant_id, "a": start, "b": end, "mp": marketplace, "pairs": pairs}).all()
    return [{"date": r.d, "rows": int(r.rows), **{m: int(getattr(r, m) or 0) for m in (*COUNT_COLUMNS, "sales")}, **{f"n_{m}": int(getattr(r, f"n_{m}")) for m in (*COUNT_COLUMNS, "sales")}} for r in rows]


def covered_days(tenant_id: UUID, start: date, end: date, marketplace: str | None = None) -> dict[str, set[date]]:
    """marketplace -> the days in [start, end] that some import for it declares (its first to last report date). A marketplace with no import in the range is present with an empty set."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_COVER, {"t": tenant_id, "a": start, "b": end, "mp": marketplace}).all()
        all_mps = [r.marketplace for r in conn.execute(_DATA_MARKETPLACES, {"t": tenant_id}).all()]
    out: dict[str, set[date]] = {m: set() for m in all_mps if marketplace is None or m == marketplace}
    for r in rows:
        lo, hi = max(r.period_start, start), min(r.period_end, end)
        out.setdefault(r.marketplace, set()).update(lo + timedelta(days=i) for i in range((hi - lo).days + 1))
    return out


def data_span(tenant_id: UUID, marketplace: str | None = None) -> dict[str, Any]:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_LAST_IMPORT, {"t": tenant_id, "mp": marketplace}).one()
    return {"lastImportAt": r.at, "first": r.lo, "last": r.hi}


def window_setting(tenant_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_SETTING, {"t": tenant_id}).first()
    return {"days": int(r.window_days), "setAt": r.set_at} if r else None


def set_window(tenant_id: UUID, user_id: UUID, days: int) -> dict[str, Any]:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_INSERT_SETTING, {"t": tenant_id, "n": days, "u": user_id}).one()
    return {"days": days, "setAt": r.set_at}


def link_history(tenant_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_LINKS, {"t": tenant_id}).all()
    return [{"sku": str(r.sku), "marketplace": r.marketplace, "reportSku": str(r.report_sku), "confirmedBy": str(r.confirmed_by), "confirmedAt": r.confirmed_at} for r in rows]


def golive_history(tenant_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_GOLIVE_HISTORY, {"t": tenant_id}).all()
    return [{"generationId": str(r.generation_id), "sku": str(r.sku), "marketplace": r.marketplace, "wentLiveOn": r.went_live_on, "confirmedBy": str(r.confirmed_by), "confirmedAt": r.confirmed_at} for r in rows]
