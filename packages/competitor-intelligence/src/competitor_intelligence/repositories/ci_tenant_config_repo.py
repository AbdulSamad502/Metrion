"""ci_tenant_config — §5. One row per tenant; the migration gives no default row, so a
tenant with no row yet must get the spec's stated defaults from application code, not from a
seeded row this package doesn't own the decision to create."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.discovery.budget import DiscoveryBudget
from competitor_intelligence.repositories.tenant_context import tenant_scope

# D2/C19 — the spec's own column defaults, used only when no row exists yet for this tenant.
DEFAULT_PRICE_THRESHOLD_PCT = Decimal("5.00")
DEFAULT_SNAPSHOT_RETENTION_DAYS = 90
DEFAULT_ALERT_ON_AVAILABILITY_CHANGE = True
DEFAULT_STALENESS_REMINDER_DAYS = 14
DEFAULT_DIGEST_FREQUENCY = "WEEKLY"
# §6.16.3 / deterministic-engine.md §5.15.1 rule 1 — the engine's own floor of 3 is enforced
# in calc_engine.formulas.price_band, not here; this default only governs the no-row-yet case.
DEFAULT_MIN_COMPETITORS_FOR_PRICE_BAND = 3


def get_min_competitors_for_price_band(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT min_competitors_for_price_band FROM ci_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return row[0] if row else DEFAULT_MIN_COMPETITORS_FOR_PRICE_BAND


def get_price_threshold_pct(tenant_id: UUID) -> Decimal:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT price_threshold_pct FROM ci_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return row[0] if row else DEFAULT_PRICE_THRESHOLD_PCT


def get_config(tenant_id: UUID) -> dict[str, object]:
    """Every `ci_tenant_config` column, defaulted per-field when no row exists yet —
    used by the alert-override resolution path and the CEO Hub's settings surface so
    neither has to know the no-row-yet case individually."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT price_threshold_pct, alert_on_availability_change, snapshot_retention_days, "
                "staleness_reminder_days, digest_default_frequency "
                "FROM ci_tenant_config WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
    if row is None:
        return {
            "priceThresholdPct": DEFAULT_PRICE_THRESHOLD_PCT,
            "alertOnAvailabilityChange": DEFAULT_ALERT_ON_AVAILABILITY_CHANGE,
            "snapshotRetentionDays": DEFAULT_SNAPSHOT_RETENTION_DAYS,
            "stalenessReminderDays": DEFAULT_STALENESS_REMINDER_DAYS,
            "digestDefaultFrequency": DEFAULT_DIGEST_FREQUENCY,
        }
    return {
        "priceThresholdPct": row["price_threshold_pct"],
        "alertOnAvailabilityChange": row["alert_on_availability_change"],
        "snapshotRetentionDays": row["snapshot_retention_days"],
        "stalenessReminderDays": row["staleness_reminder_days"],
        "digestDefaultFrequency": row["digest_default_frequency"],
    }


def get_alert_on_availability_change(tenant_id: UUID) -> bool:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT alert_on_availability_change FROM ci_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return row[0] if row else DEFAULT_ALERT_ON_AVAILABILITY_CHANGE


def get_discovery_enabled(tenant_id: UUID) -> bool:
    """§6.11 rule 1 / D11 — checked BEFORE any query is composed or sent, never as a
    post-hoc filter on results (AC17)."""
    from competitor_intelligence.discovery.budget import DEFAULT_DISCOVERY_ENABLED

    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT discovery_enabled FROM ci_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return row[0] if row else DEFAULT_DISCOVERY_ENABLED


def get_discovery_budget(tenant_id: UUID) -> DiscoveryBudget:
    """§6.12.1 — the seven locked budget knobs, per-tenant, defaulted per the spec's own
    values (`discovery.budget`'s DEFAULT_* constants) when no `ci_tenant_config` row exists
    yet for this tenant. Every discovery/cache/budget-enforcement call site takes the
    resulting `DiscoveryBudget` value object; none hardcodes a limit."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT max_discovery_queries_per_run, max_raw_candidates,
                       max_analyzed_candidates, max_recommended_candidates,
                       max_followup_searches_per_candidate, discovery_run_timeout_seconds,
                       search_cache_ttl_hours
                FROM ci_tenant_config WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
    if row is None:
        return DiscoveryBudget()
    return DiscoveryBudget(
        max_discovery_queries_per_run=row["max_discovery_queries_per_run"],
        max_raw_candidates=row["max_raw_candidates"],
        max_analyzed_candidates=row["max_analyzed_candidates"],
        max_recommended_candidates=row["max_recommended_candidates"],
        max_followup_searches_per_candidate=row["max_followup_searches_per_candidate"],
        discovery_run_timeout_seconds=row["discovery_run_timeout_seconds"],
        search_cache_ttl_hours=row["search_cache_ttl_hours"],
    )
