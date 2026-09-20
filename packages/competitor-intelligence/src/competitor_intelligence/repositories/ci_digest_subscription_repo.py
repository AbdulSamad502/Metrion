"""ci_digest_subscription — §5 (NEW in the 0002 migration, unused until this pass). One row
per (tenant_id, member_id): a seller's own preference for the digest CI will assemble.
Delivery (WhatsApp, email, in-app push) is out of scope here — see `digest/build_weekly_digest.py`
for the deterministic aggregation this subscription eventually gates; this module only
persists the preference.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope


def upsert_subscription(
    tenant_id: UUID,
    member_id: UUID,
    *,
    frequency: str,
    channel: str = "IN_APP",
    enabled: bool = True,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_digest_subscription (tenant_id, member_id, frequency, channel, enabled)
                VALUES (:tenant_id, :member_id, :frequency, :channel, :enabled)
                ON CONFLICT (tenant_id, member_id) DO UPDATE SET
                  frequency = EXCLUDED.frequency, channel = EXCLUDED.channel, enabled = EXCLUDED.enabled
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "member_id": str(member_id),
                "frequency": frequency,
                "channel": channel,
                "enabled": enabled,
            },
        ).one()
        return row[0]


def get_subscription(tenant_id: UUID, member_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT id, frequency, channel, enabled, last_sent_at FROM ci_digest_subscription "
                "WHERE tenant_id = :tenant_id AND member_id = :member_id"
            ),
            {"tenant_id": str(tenant_id), "member_id": str(member_id)},
        ).mappings().first()
        return dict(row) if row else None
