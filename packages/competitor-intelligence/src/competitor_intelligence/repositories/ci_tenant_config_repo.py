"""ci_tenant_config — §5. One row per tenant; the migration gives no default row, so a
tenant with no row yet must get the spec's stated defaults from application code, not from a
seeded row this package doesn't own the decision to create."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope

# D2/C19 — the spec's own column defaults, used only when no row exists yet for this tenant.
DEFAULT_PRICE_THRESHOLD_PCT = Decimal("5.00")
DEFAULT_SNAPSHOT_RETENTION_DAYS = 90
DEFAULT_ALERT_ON_AVAILABILITY_CHANGE = True
DEFAULT_STALENESS_REMINDER_DAYS = 14
DEFAULT_DIGEST_FREQUENCY = "WEEKLY"


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
