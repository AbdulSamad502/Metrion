"""formula_definition / discount_bearer_config / gst_slab_reference / fee_reference repository.

`formula_definition`, `gst_slab_reference` and `fee_reference` are platform-owned (no
`tenant_id`) and read-only to metrion_app — this repository never writes them; seeding is a
`metrion_migrate`-run data migration, not an application code path. `discount_bearer_config`
is the one table here with tenant-scoped rows, resolved per §5.3's "tenant row overrides
platform default" order.

severity_config is deferred (plan §J — Category C) and has no repository function here yet.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.repositories.tenant_context import tenant_scope

_BEARER_SQL = text(
    """
    SELECT bearer, source, confidence, effective_from, version
    FROM discount_bearer_config
    WHERE (tenant_id = :tenant_id OR tenant_id IS NULL)
      AND marketplace = :marketplace
      AND component_code = :component_code
      AND effective_from <= :as_of_date
    ORDER BY (tenant_id IS NOT NULL) DESC, effective_from DESC
    LIMIT 1
    """
)

_GST_SLABS_SQL = text(
    """
    SELECT rate_pct, label, source_url, source_title, retrieved_at, effective_from, effective_to, version, confidence
    FROM gst_slab_reference
    WHERE effective_from <= :as_of_date AND (effective_to IS NULL OR effective_to >= :as_of_date)
    """
)

_CURRENT_FORMULA_SQL = text(
    """
    SELECT id, metric_code, formula_version, definition, effective_from
    FROM formula_definition
    WHERE metric_code = :metric_code AND effective_from <= :as_of_date
    ORDER BY effective_from DESC
    LIMIT 1
    """
)

_RECONCILIATION_TOLERANCE_SQL = text(
    """
    SELECT tolerance_paise, tolerance_bps, settlement_lag_days, grace_period_days, effective_from, version
    FROM reconciliation_tolerance_config
    WHERE (tenant_id = :tenant_id OR tenant_id IS NULL)
      AND marketplace = :marketplace
      AND component_code IN (:component_code, '*')
      AND effective_from <= :as_of_date
    ORDER BY (tenant_id IS NOT NULL) DESC, (component_code != '*') DESC, effective_from DESC
    LIMIT 1
    """
)

_SEVERITY_CONFIG_SQL = text(
    """
    SELECT DISTINCT ON (metric) metric, high_threshold, medium_threshold, window_closing_soon_days,
           ordering_basis, effective_from, version
    FROM severity_config
    WHERE (tenant_id = :tenant_id OR tenant_id IS NULL)
      AND effective_from <= :as_of_date
    ORDER BY metric, (tenant_id IS NOT NULL) DESC, effective_from DESC
    """
)


def resolve_discount_bearer(
    tenant_id: UUID, *, marketplace: str, component_code: str, as_of_date: date
) -> dict[str, Any] | None:
    """§5.3 resolution order: a tenant-specific row (if any) beats the platform default
    (tenant_id IS NULL) for the same (marketplace, component_code, as_of_date) — the ORDER BY
    puts tenant_id IS NOT NULL first, so a tenant override always outranks a platform row of
    the same or earlier effective_from. Returns None (never a guessed bearer) when no row
    covers this marketplace/component_code combination at all — callers fall back to
    bearer=UNKNOWN per D2, they do not treat a missing row as a match."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _BEARER_SQL,
            {"tenant_id": str(tenant_id), "marketplace": marketplace, "component_code": component_code, "as_of_date": as_of_date},
        ).first()
        return dict(row._mapping) if row is not None else None


def gst_slabs_effective_on(tenant_id: UUID, *, as_of_date: date) -> list[dict[str, Any]]:
    """gst_slab_reference is platform-owned (no tenant_id column) — tenant_id here is only
    used to open a valid tenant_scope() connection (RLS requires context to be set even for
    a query against a table its own policy doesn't restrict); it plays no role in the WHERE
    clause. Never applied retroactively (§8.2.1): effective_to gates the upper bound."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_GST_SLABS_SQL, {"as_of_date": as_of_date})
        return [dict(row._mapping) for row in rows]


def current_formula_definition(tenant_id: UUID, *, metric_code: str, as_of_date: date) -> dict[str, Any] | None:
    """§4.1: 'current version' = latest formula_definition row with effective_from <= as_of_date.
    No pointer/current-version table needed. Returns None if no version has ever been seeded
    for this metric_code as of that date — never falls back to a hardcoded formula."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_CURRENT_FORMULA_SQL, {"metric_code": metric_code, "as_of_date": as_of_date}).first()
        return dict(row._mapping) if row is not None else None


def resolve_reconciliation_tolerance(
    tenant_id: UUID, *, marketplace: str, component_code: str, as_of_date: date
) -> dict[str, Any] | None:
    """§5.12.1: a tenant-specific row beats a platform default; an exact component_code match
    beats a marketplace-wide '*' row; latest effective_from wins within each. Returns None
    (never a guessed tolerance) when no row covers this marketplace/component_code at all —
    formulas/leak.py's resolve_tolerance_or_unavailable() turns that into Unavailable."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _RECONCILIATION_TOLERANCE_SQL,
            {"tenant_id": str(tenant_id), "marketplace": marketplace, "component_code": component_code, "as_of_date": as_of_date},
        ).first()
        return dict(row._mapping) if row is not None else None


def severity_config_rows(tenant_id: UUID, *, as_of_date: date) -> list[dict[str, Any]]:
    """§5.14.1: at most one row per `metric` (AMOUNT_PAISE/AGE_DAYS/WINDOW_DAYS_REMAINING),
    each the latest tenant-or-platform row effective as of as_of_date. formulas/severity.py
    treats a metric with no row here as simply not applicable to a finding, never a default."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_SEVERITY_CONFIG_SQL, {"tenant_id": str(tenant_id), "as_of_date": as_of_date})
        return [dict(row._mapping) for row in rows]
