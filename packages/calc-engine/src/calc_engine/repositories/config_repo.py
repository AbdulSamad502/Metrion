"""formula_definition / discount_bearer_config / gst_slab_reference / fee_reference /
hsn_gst_reference repository.

`formula_definition`, `gst_slab_reference`, `fee_reference` and `hsn_gst_reference` are
platform-owned (no `tenant_id`) and read-only to metrion_app — this repository never writes
them; seeding is a `metrion_migrate`-run data migration, not an application code path.
`discount_bearer_config` is the one table here with tenant-scoped rows, resolved per §5.3's
"tenant row overrides platform default" order.

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

_FEE_REFERENCE_SQL = text(
    """
    SELECT rate_pct, rate_low_pct, rate_high_pct, source, confidence, version, effective_from, effective_to
    FROM fee_reference
    WHERE marketplace = :marketplace
      AND category = :category
      AND fee_type = :fee_type
      AND effective_from <= :as_of_date
      AND (effective_to IS NULL OR effective_to >= :as_of_date)
    ORDER BY effective_from DESC
    LIMIT 1
    """
)

_ANOMALY_DETECTION_CONFIG_SQL = text(
    """
    SELECT min_series_length, z_score_threshold, percentile_low, percentile_high,
           delta_severity_bands, effective_from, version
    FROM anomaly_detection_config
    WHERE (tenant_id = :tenant_id OR tenant_id IS NULL)
      AND metric = :metric
      AND method = :method
      AND effective_from <= :as_of_date
    ORDER BY (tenant_id IS NOT NULL) DESC, effective_from DESC
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

_FINANCIAL_HEALTH_CONFIG_SQL = text(
    """
    SELECT DISTINCT ON (metric) metric, direction, at_risk_threshold_pct, watch_threshold_pct,
           effective_from, version
    FROM financial_health_config
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


def resolve_fee_reference(
    tenant_id: UUID, *, marketplace: str, category: str, fee_type: str, as_of_date: date
) -> dict[str, Any] | None:
    """fee_reference is platform-owned (no tenant_id column) — tenant_id here is only used to
    open a valid tenant_scope() connection (RLS requires context to be set even for a query
    against a table its own policy doesn't restrict); it plays no role in the WHERE clause,
    mirroring gst_slabs_effective_on's precedent above. Matches on the exact
    (marketplace, category, fee_type) triple; effective_to gates the upper bound the same way
    as gst_slab_reference, never applied retroactively. Latest effective_from wins when more
    than one row covers as_of_date. Returns None (never a guessed/defaulted rate) when no row
    covers this (marketplace, category, fee_type) at all — formulas/fee_resolution.py's
    resolve_fee_or_unavailable() turns that into Unavailable."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _FEE_REFERENCE_SQL,
            {"marketplace": marketplace, "category": category, "fee_type": fee_type, "as_of_date": as_of_date},
        ).first()
        return dict(row._mapping) if row is not None else None


_FEE_REFERENCE_OPTIONS_SQL = text(
    """
    SELECT DISTINCT marketplace, category, fee_type
    FROM fee_reference
    WHERE effective_from <= :as_of_date AND (effective_to IS NULL OR effective_to >= :as_of_date)
    ORDER BY marketplace, category, fee_type
    """
)


def fee_reference_options(tenant_id: UUID, *, as_of_date: date) -> list[dict[str, str]]:
    """The distinct (marketplace, category, fee_type) triples with a fee reference in effect on `as_of_date` (platform-owned data; `tenant_id` only opens the
    scope, as in `resolve_fee_reference`). For a form to offer real choices; it resolves nothing."""
    with tenant_scope(tenant_id) as conn:
        return [dict(r._mapping) for r in conn.execute(_FEE_REFERENCE_OPTIONS_SQL, {"as_of_date": as_of_date})]


_HSN_GST_REFERENCE_CANDIDATES_SQL = text(
    """
    SELECT hsn_code, description, rate_pct, source_url, source_title, retrieved_at,
           effective_from, effective_to, version, confidence
    FROM hsn_gst_reference
    WHERE :hsn_code LIKE hsn_code || '%'
      AND effective_from <= :as_of_date
      AND (effective_to IS NULL OR effective_to >= :as_of_date)
    ORDER BY length(hsn_code) DESC, effective_from DESC
    """
)


def resolve_hsn_gst_reference(tenant_id: UUID, *, hsn_code: str, as_of_date: date) -> dict[str, Any] | None:
    """§8.2.2's curated HSN->rate knowledge base — OP13 tier (b), consulted only when tier (a)
    (an observed rate on the seller's own uploaded data) has nothing for this line. Mirrors
    resolve_fee_reference's docstring/resolution-order style above.

    hsn_gst_reference is platform-owned (no tenant_id column) — tenant_id here is only used
    to open a valid tenant_scope() connection (RLS requires context to be set even for a
    query against a table its own policy doesn't restrict, per gst_slabs_effective_on's
    precedent); it plays no role in the WHERE clause.

    Matching rule (§8.2.2, kept deliberately simple in V1):
    1. A stored hsn_code matches when it is a leading-digit prefix of, or exactly equal to,
       the queried hsn_code (`:hsn_code LIKE hsn_code || '%'` expresses exactly this: a
       stored '6109' matches a queried '61091000'; a stored '61091000' matches only a queried
       '61091000').
    2. Among matches, the longest (most specific) matching prefix wins; ties broken by the
       latest effective_from — both expressed in the ORDER BY, with the first row taken.
    3. effective_from <= as_of_date and (effective_to IS NULL OR effective_to >= as_of_date)
       gate every candidate — never applied retroactively, same rule as gst_slab_reference
       and fee_reference.
    4. If the queried code is SHORTER than every candidate row's stored code (the seller only
       knows a shallower classification level than anything on file), no row can satisfy the
       `:hsn_code LIKE hsn_code || '%'` predicate — a longer stored prefix can never be a
       prefix-match of a shorter queried string — so the query naturally returns zero rows in
       this case, without any separate branch needed to detect it.
    5. No match under rules 1-4 -> None. Never a guessed or defaulted rate, matching every
       other resolver in this engine (§5.14, §8.2.1) — callers fall through to the GST
       Applicability Lookup (§8.4, tier c), per OP13's ordering (AC20)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _HSN_GST_REFERENCE_CANDIDATES_SQL,
            {"hsn_code": hsn_code, "as_of_date": as_of_date},
        ).first()
        return dict(row._mapping) if row is not None else None


def resolve_anomaly_detection_config(
    tenant_id: UUID, *, metric: str, method: str, as_of_date: date
) -> dict[str, Any] | None:
    """docs/specs/anomaly-detection.md §6.5: resolution order mirrors
    `resolve_reconciliation_tolerance`/`discount_bearer_config`/`severity_config` exactly — a
    tenant-specific row for the same (metric, method) overrides the platform default
    (tenant_id IS NULL); latest effective_from wins within each. Returns None (never a
    silently-assumed threshold, per E9/AC13) when no row covers this (metric, method) at all
    — `calc_engine.anomaly`'s pure functions never resolve config themselves (B8), so a caller
    receiving None here must surface an explicit configuration-gap outcome
    (`AnomalyConfigurationGap`) rather than calling any anomaly method with an invented
    threshold."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _ANOMALY_DETECTION_CONFIG_SQL,
            {"tenant_id": str(tenant_id), "metric": metric, "method": method, "as_of_date": as_of_date},
        ).first()
        return dict(row._mapping) if row is not None else None


def severity_config_rows(tenant_id: UUID, *, as_of_date: date) -> list[dict[str, Any]]:
    """§5.14.1: at most one row per `metric` (AMOUNT_PAISE/AGE_DAYS/WINDOW_DAYS_REMAINING),
    each the latest tenant-or-platform row effective as of as_of_date. formulas/severity.py
    treats a metric with no row here as simply not applicable to a finding, never a default."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_SEVERITY_CONFIG_SQL, {"tenant_id": str(tenant_id), "as_of_date": as_of_date})
        return [dict(row._mapping) for row in rows]


def financial_health_config_rows(tenant_id: UUID, *, as_of_date: date) -> list[dict[str, Any]]:
    """cfo-agent.md §6.15: at most one row per `metric` (CONTRIBUTION_MARGIN_PCT/
    FEE_RATIO_PCT/RETURN_RATE_PCT), each the latest tenant-or-platform row effective as of
    as_of_date — same resolution order as `severity_config_rows` immediately above.
    `formulas/financial_health.py` treats a metric with no row here as simply not scored for
    that tenant, never a default band."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _FINANCIAL_HEALTH_CONFIG_SQL, {"tenant_id": str(tenant_id), "as_of_date": as_of_date}
        )
        return [dict(row._mapping) for row in rows]
