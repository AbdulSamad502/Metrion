"""READ-ONLY selects against sales_line/line_component (data-foundation.md §1.3/§1.4).

This repository is structurally complete against the documented schema, but **not
runtime-tested** — `sales_line` and `line_component` are owned by data-foundation.md, and no
migration for them exists anywhere in the repo yet (only calc-engine's own tables, created by
this package's migration 20260917_0001, actually exist in the database at the time of
writing). Do not treat the queries below as verified until data-foundation's own migration
lands and an integration test can run them against a real `sales_line` row — that is out of
this package's scope to create, per migrations/README.md ("this directory never authors DDL
for tables owned by data-foundation.md").

Read-only by convention, not by grant: this package's own migration does not touch these
tables' grants at all, since it doesn't create them.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.repositories.tenant_context import tenant_scope

_LINES_FOR_PERIOD_SQL = text(
    """
    SELECT id AS sales_line_id, marketplace, document_type, quantity, invoice_date,
           dispatch_date, order_date, gross_item_amount, return_status, confidence,
           order_ref, line_ref, taxable_amount
    FROM sales_line
    WHERE tenant_id = :tenant_id
      AND coalesce(invoice_date, dispatch_date, order_date) BETWEEN :period_start AND :period_end
    """
)

_LINES_WITHOUT_DOCUMENT_DATE_SQL = text(
    """
    SELECT id AS sales_line_id, marketplace, document_type, quantity, invoice_date,
           dispatch_date, order_date, gross_item_amount, return_status, confidence,
           order_ref, line_ref, taxable_amount
    FROM sales_line
    WHERE tenant_id = :tenant_id
      AND marketplace = :marketplace
      AND invoice_date IS NULL
      AND dispatch_date IS NULL
      AND order_date IS NULL
    """
)

_COMPONENTS_FOR_LINES_SQL = text(
    """
    SELECT id, sales_line_id, component_kind, component_code, source_side, amount, tax_amount, rate_pct
    FROM line_component
    WHERE tenant_id = :tenant_id AND sales_line_id = ANY(:sales_line_ids)
    """
)


def sales_lines_in_period(tenant_id: UUID, *, period_start: date, period_end: date) -> list[dict[str, Any]]:
    """Fetches raw sales_line rows for a period, keyed by the same invoice->dispatch->order
    fallback dates.py.resolve_document_date() implements — this query and that function must
    stay in agreement, since a mismatch would silently exclude or double-count a line at a
    period boundary. Returns raw rows; assembling a CanonicalLine (including rto_outcome,
    rto_qty, quarantine_rule_ids and the manual_adjustment overlay) is the caller's job, not
    this repository's — this module only reads data-foundation's own tables as declared.

    Also returns `order_ref`, `line_ref` (the Meesho join key, data-foundation.md §5.1) and
    `taxable_amount` (the invoice-side scalar `reconcile()`'s Path B, data-foundation.md §5.8,
    uses for `UNSETTLED_BEYOND_LAG`'s `amount_paise` — the only invoice-side total real Meesho
    adapters currently populate) — added specifically for `calc_engine.api.reconcile.reconcile`
    (coordinator-approved widening of this SELECT; all three columns already existed on
    `sales_line` per `20260917_0001_sales_side_tables.py`, this is additive-only, no schema
    change, same WHERE clause, same signature)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _LINES_FOR_PERIOD_SQL,
            {"tenant_id": str(tenant_id), "period_start": period_start, "period_end": period_end},
        )
        return [dict(row._mapping) for row in rows]


def sales_lines_without_document_date(tenant_id: UUID, *, marketplace: str) -> list[dict[str, Any]]:
    """Fetches sales_line rows with ALL THREE of invoice_date/dispatch_date/order_date NULL —
    deliberately NOT period-bounded, since there is no date on these rows to compare against a
    period at all.

    Exists specifically for `calc_engine.api.reconcile.reconcile`'s Path B (Decision B, this
    session): `sales_lines_in_period()`'s `coalesce(invoice_date, dispatch_date, order_date)
    BETWEEN :period_start AND :period_end` filter correctly evaluates to NULL/false for a fully
    dateless row, silently excluding it from every period-bounded query — correct and
    load-bearing for `sales_lines_in_period()`'s OTHER real callers (`compute_period_pnl`, GST
    period summary, etc.), where a dateless line must never silently enter a period's revenue/
    P&L figure. Widening that function's own WHERE clause to include dateless rows would be a
    real money-correctness regression for those callers, not a reconcile()-only concern — hence
    a separate function here rather than a change to `sales_lines_in_period()`'s filter.

    Same column list as `sales_lines_in_period()` (this function reuses the same widened SELECT
    reconcile() needs), same `tenant_scope()` pattern as every other function in this module.
    Callers combining this with `sales_lines_in_period()` for the same run must dedupe by
    `sales_line_id` if they ever overlap — by construction they cannot (one has all three dates
    NULL, the other requires `coalesce(...)` to be non-NULL and in-range), but that invariant is
    the caller's to note, not this function's to enforce."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _LINES_WITHOUT_DOCUMENT_DATE_SQL,
            {"tenant_id": str(tenant_id), "marketplace": marketplace},
        )
        return [dict(row._mapping) for row in rows]


def components_for_lines(tenant_id: UUID, *, sales_line_ids: list[UUID]) -> list[dict[str, Any]]:
    if not sales_line_ids:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _COMPONENTS_FOR_LINES_SQL,
            {"tenant_id": str(tenant_id), "sales_line_ids": [str(i) for i in sales_line_ids]},
        )
        return [dict(row._mapping) for row in rows]
