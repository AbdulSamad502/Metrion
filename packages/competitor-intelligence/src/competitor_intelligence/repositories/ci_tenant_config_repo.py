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


DEFAULT_ALERT_DEDUP_WINDOW_HOURS = 24


DEFAULT_REVIEW_FINDING_MIN_SAMPLE = 10  # CI spec Q22 (provisional)


def get_review_min_sample(tenant_id: UUID) -> int:
    """The fewest reviews a screenshot must show before a review finding is raised from it (the tenant's own setting, else the spec default)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT review_finding_min_sample FROM ci_tenant_config WHERE tenant_id = :tenant_id"), {"tenant_id": str(tenant_id)}).first()
    return int(row[0]) if row and row[0] else DEFAULT_REVIEW_FINDING_MIN_SAMPLE


def get_watchlist_limit(tenant_id: UUID) -> int | None:
    """This tenant's own cap on tracked competitors, or None when none is set (no limit is invented). Only an operator can set it."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT max_active_competitors FROM ci_tenant_config WHERE tenant_id = :tenant_id"), {"tenant_id": str(tenant_id)}).first()
    return None if row is None else row[0]


def get_alert_settings(tenant_id: UUID) -> dict[str, object]:
    """Quiet hours (all three unset = none) and the dedup window (§6.26). A tenant with no row gets
    no quiet hours and the default window — never an invented window."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT quiet_hours_start, quiet_hours_end, quiet_hours_tz, alert_dedup_window_hours "
                "FROM ci_tenant_config WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
    if row is None:
        return {"quiet_hours_start": None, "quiet_hours_end": None, "quiet_hours_tz": None, "alert_dedup_window_hours": DEFAULT_ALERT_DEDUP_WINDOW_HOURS}
    return dict(row)


def set_alert_settings(
    tenant_id: UUID,
    *,
    updated_by: UUID,
    quiet_start=None,
    quiet_end=None,
    quiet_tz: str | None = None,
    clear_quiet: bool = False,
    price_threshold_pct: Decimal | None = None,
) -> None:
    """The seller's own alert preferences (C42). Only the columns the app role may write are touched, and a field left out is left as it was.
    Quiet hours are all-or-nothing: set a start, an end and a timezone together, or clear them together."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    sets = ["updated_by = :updated_by", "updated_at = :now"]
    cols, vals = ["tenant_id", "updated_by", "updated_at"], [":tenant_id", ":updated_by", ":now"]
    params: dict[str, object] = {"tenant_id": str(tenant_id), "updated_by": str(updated_by), "now": now}
    if clear_quiet:
        sets += ["quiet_hours_start = NULL", "quiet_hours_end = NULL", "quiet_hours_tz = NULL"]  # nothing to clear when no row exists yet
    elif quiet_start is not None:
        sets += ["quiet_hours_start = :qs", "quiet_hours_end = :qe", "quiet_hours_tz = :qz"]
        cols += ["quiet_hours_start", "quiet_hours_end", "quiet_hours_tz"]
        vals += [":qs", ":qe", ":qz"]
        params.update(qs=quiet_start, qe=quiet_end, qz=quiet_tz)
    if price_threshold_pct is not None:
        sets.append("price_threshold_pct = :pct")
        cols.append("price_threshold_pct")
        vals.append(":pct")
        params["pct"] = price_threshold_pct
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(f"INSERT INTO ci_tenant_config ({', '.join(cols)}) VALUES ({', '.join(vals)}) ON CONFLICT (tenant_id) DO UPDATE SET " + ", ".join(sets)),  # noqa: S608 - fixed column names
            params,
        )
