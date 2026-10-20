"""ci_info_request — the CI -> CEO -> seller question and its answer (spec §5.7, §6.23.3, C38).

CI never addresses the seller: it writes a request here, the CEO phrases it, and the answer
returns through `answer()` / `decline()`. An answer is bound to one request id, is idempotent
on replay (an already-answered request returns its stored state and changes nothing), and is
tenant-scoped like every other table here."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope

DEFAULT_EXPIRY = timedelta(days=7)  # the D6 ceiling (§6.23.2)


def create(
    tenant_id: UUID,
    *,
    field_name: str,
    reason: str,
    consequential: bool,
    competitor_url_id: UUID | None = None,
    evidence_id: UUID | None = None,
    snapshot_id: UUID | None = None,
    proposed_value: Any = None,
    now: datetime | None = None,
    expires_in: timedelta = DEFAULT_EXPIRY,
) -> UUID:
    now = now or datetime.now(timezone.utc)
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_info_request (tenant_id, competitor_url_id, evidence_id, snapshot_id, field_name,
                                             reason, consequential, proposed_value, created_at, expires_at)
                VALUES (:tenant_id, :competitor_url_id, :evidence_id, :snapshot_id, :field_name,
                        :reason, :consequential, CAST(:proposed AS jsonb), :created_at, :expires_at)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "competitor_url_id": str(competitor_url_id) if competitor_url_id else None,
                "evidence_id": str(evidence_id) if evidence_id else None,
                "snapshot_id": str(snapshot_id) if snapshot_id else None,
                "field_name": field_name,
                "reason": reason,
                "consequential": consequential,
                "proposed": json.dumps(proposed_value),
                "created_at": now,
                "expires_at": now + expires_in,
            },
        ).one()
        return row[0]


def get(tenant_id: UUID, request_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM ci_info_request WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(request_id)},
        ).mappings().first()
        return dict(row) if row else None


def list_open(tenant_id: UUID, *, snapshot_id: UUID | None = None, competitor_url_id: UUID | None = None) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM ci_info_request
                WHERE tenant_id = :tenant_id AND status = 'OPEN'
                  AND (CAST(:snapshot_id AS uuid) IS NULL OR snapshot_id = CAST(:snapshot_id AS uuid))
                  AND (CAST(:competitor_url_id AS uuid) IS NULL OR competitor_url_id = CAST(:competitor_url_id AS uuid))
                ORDER BY created_at
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "snapshot_id": str(snapshot_id) if snapshot_id else None,
                "competitor_url_id": str(competitor_url_id) if competitor_url_id else None,
            },
        ).mappings()
        return [dict(r) for r in rows]


def _settle(tenant_id: UUID, request_id: UUID, *, status: str, value: Any, answered_by: UUID, now: datetime) -> dict[str, Any] | None:
    """OPEN -> ANSWERED/DECLINED exactly once. Returns the row after the call; a request that
    was not OPEN (already answered, declined or expired) is returned unchanged."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE ci_info_request
                SET status = :status, answered_value = CAST(:value AS jsonb), answered_by = :answered_by, answered_at = :now
                WHERE tenant_id = :tenant_id AND id = :id AND status = 'OPEN' AND expires_at > :now
                """
            ),
            {"status": status, "value": json.dumps(value), "answered_by": str(answered_by), "now": now,
             "tenant_id": str(tenant_id), "id": str(request_id)},
        )
    return get(tenant_id, request_id)


def answer(tenant_id: UUID, request_id: UUID, *, value: Any, answered_by: UUID, now: datetime | None = None) -> dict[str, Any] | None:
    return _settle(tenant_id, request_id, status="ANSWERED", value=value, answered_by=answered_by, now=now or datetime.now(timezone.utc))


def decline(tenant_id: UUID, request_id: UUID, *, answered_by: UUID, now: datetime | None = None) -> dict[str, Any] | None:
    return _settle(tenant_id, request_id, status="DECLINED", value=None, answered_by=answered_by, now=now or datetime.now(timezone.utc))


def expire_overdue(tenant_id: UUID, *, now: datetime | None = None) -> int:
    """OPEN requests past `expires_at` become EXPIRED (§6.23.2). Returns how many."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text("UPDATE ci_info_request SET status = 'EXPIRED' WHERE tenant_id = :tenant_id AND status = 'OPEN' AND expires_at <= :now"),
            {"tenant_id": str(tenant_id), "now": now or datetime.now(timezone.utc)},
        )
        return result.rowcount or 0


def list_for_snapshot(tenant_id: UUID, snapshot_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT * FROM ci_info_request WHERE tenant_id = :tenant_id AND snapshot_id = :snapshot_id ORDER BY created_at"),
            {"tenant_id": str(tenant_id), "snapshot_id": str(snapshot_id)},
        ).mappings()
        return [dict(r) for r in rows]
