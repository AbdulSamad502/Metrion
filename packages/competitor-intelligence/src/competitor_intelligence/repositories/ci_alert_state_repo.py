"""ci_alert_state — dedup memory (spec §5.7, §6.26.1): the last value alerted per
(competitor, finding type, direction)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope


def get(tenant_id: UUID, competitor_url_id: UUID, finding_type: str, direction: str) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                SELECT last_alerted_value_paise, last_alerted_snapshot_id, last_alerted_at
                FROM ci_alert_state
                WHERE tenant_id = :tenant_id AND competitor_url_id = :url AND finding_type = :ft AND direction = :dir
                """
            ),
            {"tenant_id": str(tenant_id), "url": str(competitor_url_id), "ft": finding_type, "dir": direction},
        ).mappings().first()
        return dict(row) if row else None


def upsert(
    tenant_id: UUID, competitor_url_id: UUID, finding_type: str, direction: str, *, value_paise: int | None, snapshot_id: UUID | None, at: datetime
) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO ci_alert_state (tenant_id, competitor_url_id, finding_type, direction,
                                            last_alerted_value_paise, last_alerted_snapshot_id, last_alerted_at)
                VALUES (:tenant_id, :url, :ft, :dir, :value, :snapshot, :at)
                ON CONFLICT (tenant_id, competitor_url_id, finding_type, direction)
                DO UPDATE SET last_alerted_value_paise = EXCLUDED.last_alerted_value_paise,
                              last_alerted_snapshot_id = EXCLUDED.last_alerted_snapshot_id,
                              last_alerted_at = EXCLUDED.last_alerted_at
                """
            ),
            {"tenant_id": str(tenant_id), "url": str(competitor_url_id), "ft": finding_type, "dir": direction,
             "value": value_paise, "snapshot": str(snapshot_id) if snapshot_id else None, "at": at},
        )
