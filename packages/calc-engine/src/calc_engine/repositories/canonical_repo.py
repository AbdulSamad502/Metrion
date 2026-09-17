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
           dispatch_date, order_date, gross_item_amount, return_status, confidence
    FROM sales_line
    WHERE tenant_id = :tenant_id
      AND coalesce(invoice_date, dispatch_date, order_date) BETWEEN :period_start AND :period_end
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
    this repository's — this module only reads data-foundation's own tables as declared."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _LINES_FOR_PERIOD_SQL,
            {"tenant_id": str(tenant_id), "period_start": period_start, "period_end": period_end},
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
