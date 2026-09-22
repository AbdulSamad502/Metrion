"""competitor_price_event — §5. MN14: ci_capture_run_id is provenance for the event, not just
for the snapshots it derives from."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.delta.compute import PriceDelta
from competitor_intelligence.repositories.tenant_context import tenant_scope


def insert_event(
    tenant_id: UUID,
    *,
    competitor_url_id: UUID,
    from_snapshot_id: UUID,
    to_snapshot_id: UUID,
    ci_capture_run_id: UUID,
    delta: PriceDelta,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO competitor_price_event (
                  tenant_id, competitor_url_id, from_snapshot_id, to_snapshot_id, delta_paise,
                  delta_pct, direction, availability_change, threshold_breached,
                  ci_capture_run_id, observed_span, alert_eligible
                ) VALUES (
                  :tenant_id, :competitor_url_id, :from_snapshot_id, :to_snapshot_id, :delta_paise,
                  :delta_pct, :direction, :availability_change, :threshold_breached,
                  :ci_capture_run_id, :observed_span, :alert_eligible
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "competitor_url_id": str(competitor_url_id),
                "from_snapshot_id": str(from_snapshot_id),
                "to_snapshot_id": str(to_snapshot_id),
                "delta_paise": delta.delta_paise,
                "delta_pct": delta.delta_pct,
                "direction": delta.direction.value,
                "availability_change": delta.availability_change.value if delta.availability_change else None,
                "threshold_breached": delta.threshold_breached,
                "ci_capture_run_id": str(ci_capture_run_id),
                "observed_span": delta.observed_span,
                "alert_eligible": delta.alert_eligible,
            },
        ).one()
        return row[0]


def list_events(tenant_id: UUID, competitor_url_id: UUID, *, limit: int = 50) -> list[dict[str, Any]]:
    """§6.3 change-detection history for one competitor URL, newest first."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, from_snapshot_id, to_snapshot_id, delta_paise, delta_pct, direction,
                       availability_change, threshold_breached, alert_eligible, observed_span, created_at
                FROM competitor_price_event
                WHERE tenant_id = :tenant_id AND competitor_url_id = :competitor_url_id
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": str(tenant_id), "competitor_url_id": str(competitor_url_id), "limit": limit},
        ).mappings()
        return [dict(r) for r in rows]


def list_recent_for_tenant(tenant_id: UUID, *, since: datetime) -> list[dict[str, Any]]:
    """Tenant-wide price events since a timestamp — the digest's raw input (deterministic
    "what changed" aggregation, `digest/build_weekly_digest.py`) and Layer 1 alerts'
    (`alerts/layer1.py`, §6.17) raw input. Includes `from_snapshot_id`/`to_snapshot_id` so a
    Layer 1 alert can cite the actual before/after price, not just the delta."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, competitor_url_id, from_snapshot_id, to_snapshot_id, delta_paise, delta_pct,
                       direction, availability_change, threshold_breached, alert_eligible, created_at
                FROM competitor_price_event
                WHERE tenant_id = :tenant_id AND created_at >= :since
                ORDER BY created_at DESC
                """
            ),
            {"tenant_id": str(tenant_id), "since": since},
        ).mappings()
        return [dict(r) for r in rows]
