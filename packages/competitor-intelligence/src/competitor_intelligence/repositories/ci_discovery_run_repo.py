"""ci_discovery_run — competitor-intelligence-agent.md §5.4.

Checkpoint 4 scope: enough to create a run and read it back for the candidate/relevance
repositories in this same checkpoint to reference. The `QUEUED -> ... -> COMPLETE/FAILED/
PARTIAL/STALE` state machine itself (§6.12.2) is Checkpoint 5 — this module does not enforce
any transition rules, it just persists whatever status a caller sets.

Every function takes `tenant_id` first and receives its connection only via `tenant_scope()`
(auth.md §7.3), matching every other repository in this package.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope


def create_run(
    tenant_id: UUID,
    *,
    seller_product_ref: str,
    requested_by: UUID,
    status: str = "QUEUED",
    provider_name: str | None = None,
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_discovery_run
                    (tenant_id, seller_product_ref, requested_by, status, provider_name)
                VALUES
                    (:tenant_id, :seller_product_ref, :requested_by, :status, :provider_name)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "seller_product_ref": seller_product_ref,
                "requested_by": str(requested_by),
                "status": status,
                "provider_name": provider_name,
            },
        ).one()
        return row[0]


def get_run(tenant_id: UUID, discovery_run_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM ci_discovery_run WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(discovery_run_id)},
        ).mappings().first()
        return dict(row) if row is not None else None


def update_status(
    tenant_id: UUID,
    discovery_run_id: UUID,
    *,
    status: str,
    partial_reason: str | None = None,
    failed_reason: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE ci_discovery_run
                SET status = :status,
                    partial_reason = :partial_reason,
                    failed_reason = :failed_reason,
                    finished_at = :finished_at
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(discovery_run_id),
                "status": status,
                "partial_reason": partial_reason,
                "failed_reason": failed_reason,
                "finished_at": finished_at,
            },
        )


def update_candidate_counts(
    tenant_id: UUID, discovery_run_id: UUID, *, raw_candidate_count: int, analyzed_candidate_count: int
) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE ci_discovery_run
                SET raw_candidate_count = :raw_candidate_count,
                    analyzed_candidate_count = :analyzed_candidate_count
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(discovery_run_id),
                "raw_candidate_count": raw_candidate_count,
                "analyzed_candidate_count": analyzed_candidate_count,
            },
        )
