"""READ-ONLY selects against settlement_line/line_component (data-foundation.md §5.6, §5.7).

This repository is structurally complete against the documented `settlement_line` schema
(data-foundation.md §5.6, CONFIRMED Phase C, C1), but **not runtime-tested** — `settlement_line`
is data-foundation-owned (§5.7, CONFIRMED Phase C, C2: "Raw ingested facts, same layer as
`sales_document`/`sales_line`/`line_component`") and, at the time of writing, no migration for it
exists anywhere in the repo yet (only `packages/data-foundation/migrations/versions/
20260917_0001_sales_side_tables.py`'s `sales_line`/`line_component` tables and calc-engine's own
tables actually exist in the database). Do not treat the queries below as verified until
data-foundation's own `settlement_line` migration lands and an integration test can run them
against a real `settlement_line` row — that is out of this package's scope to create, per
migrations/README.md ("this directory never authors DDL for tables owned by
data-foundation.md"). See `tests/integration/test_settlement_repo.py` for the check this
docstring instructs: verify the table exists before claiming the integration test passes, don't
assume it from this docstring or from the parallel task's stated intent.

Read-only by convention, not by grant: this package's own migration does not touch these
tables' grants at all, since it doesn't create them.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.repositories.tenant_context import tenant_scope

_SETTLEMENT_LINES_FOR_PERIOD_SQL = text(
    """
    SELECT id AS settlement_line_id, tenant_id, ingestion_run_id, marketplace, order_ref,
           line_ref, settlement_id, gross_settlement_amount, currency, settlement_date,
           document_type, source_row_number, source_row_json, confidence
    FROM settlement_line
    WHERE tenant_id = :tenant_id
      AND settlement_date BETWEEN :period_start AND :period_end
    """
)

_SETTLEMENT_LINES_FOR_PERIOD_AND_MARKETPLACE_SQL = text(
    """
    SELECT id AS settlement_line_id, tenant_id, ingestion_run_id, marketplace, order_ref,
           line_ref, settlement_id, gross_settlement_amount, currency, settlement_date,
           document_type, source_row_number, source_row_json, confidence
    FROM settlement_line
    WHERE tenant_id = :tenant_id
      AND marketplace = :marketplace
      AND settlement_date BETWEEN :period_start AND :period_end
    """
)

_COMPONENTS_FOR_SETTLEMENT_LINES_SQL = text(
    """
    SELECT id, sales_line_id, settlement_line_id, component_kind, component_code, source_side,
           amount, tax_amount, rate_pct
    FROM line_component
    WHERE tenant_id = :tenant_id
      AND settlement_line_id = ANY(:settlement_line_ids)
      AND source_side = 'SETTLEMENT'
    """
)


def settlement_lines_in_period(
    tenant_id: UUID, *, period_start: date, period_end: date, marketplace: str | None = None
) -> list[dict[str, Any]]:
    """Fetches raw settlement_line rows for a period, filtered on `settlement_date BETWEEN
    :period_start AND :period_end`.

    Unlike `canonical_repo.sales_lines_in_period`'s invoice->dispatch->order fallback chain
    (`calc_engine/dates.py`'s `resolve_document_date()`), `settlement_line` has exactly one date
    column — `settlement_date`, nullable per data-foundation.md §5.6 ("not every settlement row
    carries a computable... date", e.g. ServiceFee/Adjustment/Transfer rows per §2.3). There is
    therefore no fallback chain to implement here: a row with a null `settlement_date` is simply
    excluded by the BETWEEN filter, which is the correct behaviour — an unsettled/dateless row
    cannot belong to a settled period by definition.

    Returns raw rows; matching them against sales_line candidates (collision/duplicate/orphan
    handling, data-foundation.md §5.8) is the caller's job, not this repository's — this module
    only reads data-foundation's own tables as declared.

    `marketplace=None` (the default) returns every marketplace's rows, exactly as before — every
    existing caller is unchanged. Passing a marketplace pushes that filter into SQL, so a
    per-marketplace caller (`reconcile()`, cash reconciliation) no longer pulls every other
    marketplace's rows (including their `source_row_json`) across the wire just to discard them."""
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "period_start": period_start, "period_end": period_end}
    sql = _SETTLEMENT_LINES_FOR_PERIOD_SQL
    if marketplace is not None:
        sql = _SETTLEMENT_LINES_FOR_PERIOD_AND_MARKETPLACE_SQL
        params["marketplace"] = marketplace
    with tenant_scope(tenant_id) as conn:
        return [dict(row._mapping) for row in conn.execute(sql, params)]


def components_for_settlement_lines(tenant_id: UUID, *, settlement_line_ids: list[UUID]) -> list[dict[str, Any]]:
    """Same shape as `canonical_repo.components_for_lines`, but filters
    `line_component.settlement_line_id = ANY(...)` instead of `sales_line_id`, and additionally
    restricts to `source_side = 'SETTLEMENT'` rows — per data-foundation.md §5.4, a
    `line_component` row is either an invoice-side or settlement-side fact
    (`source_side` distinguishes them), and this repository's whole purpose is reading the
    settlement side of that split."""
    if not settlement_line_ids:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _COMPONENTS_FOR_SETTLEMENT_LINES_SQL,
            {"tenant_id": str(tenant_id), "settlement_line_ids": [str(i) for i in settlement_line_ids]},
        )
        return [dict(row._mapping) for row in rows]
