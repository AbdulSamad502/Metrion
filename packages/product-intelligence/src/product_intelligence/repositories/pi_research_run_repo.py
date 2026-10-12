"""pi_research_run — `product-intelligence-agent.md` §5, §6.8. Created only from an
already-`READY` `niche_brief_id` (§6.1 rule 4); the `QUEUED -> RUNNING -> PARTIAL|COMPLETE|
FAILED` state machine's transition rules are enforced by the caller (`direct_path/`), this
module only persists whatever status a caller sets, same scope boundary as CI's
`ci_discovery_run_repo`.

**Checkpoint 2 — real implementation.** Every function takes `tenant_id` first and receives
its connection only via `tenant_scope()` (auth.md §7.3), matching every other repository in
this package.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope

_ACTIVE_STATUSES = ("QUEUED", "RUNNING")


def create_run(
    tenant_id: UUID,
    *,
    niche_brief_id: UUID,
    depth: str,
    trigger: str,
    candidate_cap: int,
    status: str = "QUEUED",
) -> UUID:
    """Inserts a `pi_research_run` row. Returns the new row's id. `depth` is `SHALLOW` |
    `COMPLETE`; `trigger` is `DIRECT_UI` | `CEO_REQUEST`."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO pi_research_run
                    (tenant_id, niche_brief_id, depth, trigger, candidate_cap, status, created_at)
                VALUES
                    (:tenant_id, :niche_brief_id, :depth, :trigger, :candidate_cap, :status, now())
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "niche_brief_id": str(niche_brief_id),
                "depth": depth,
                "trigger": trigger,
                "candidate_cap": candidate_cap,
                "status": status,
            },
        ).one()
        return row[0]


def get_run(tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM pi_research_run WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(run_id)},
        ).mappings().first()
        return dict(row) if row is not None else None


def list_runs_for_brief(tenant_id: UUID, niche_brief_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM pi_research_run WHERE tenant_id = :tenant_id AND niche_brief_id = :niche_brief_id "
                "ORDER BY started_at DESC NULLS LAST"
            ),
            {"tenant_id": str(tenant_id), "niche_brief_id": str(niche_brief_id)},
        ).mappings().all()
        return [dict(r) for r in rows]


def count_runs_for_tenant(tenant_id: UUID) -> int:
    """Real, live-queried count of every `pi_research_run` row this tenant has ever had
    inserted — feeds `backend.entitlement.resolve_niche_run_entitlement`'s real usage number,
    the same "real usage, no fabricated cap" precedent `calc_engine.repositories.gst_lookup_
    repo.count_for_tenant` already established for `service.gst_lookup`."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT count(*) FROM pi_research_run WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return int(row[0]) if row is not None else 0


def has_active_run(tenant_id: UUID, niche_brief_id: UUID) -> bool:
    """True when a `QUEUED`/`RUNNING` run already references `niche_brief_id` — used by
    `niche_brief_repo.mark_draft`'s caller to enforce §6.1 rule 2's edit-lock."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM pi_research_run "
                "WHERE tenant_id = :tenant_id AND niche_brief_id = :niche_brief_id "
                "AND status = ANY(CAST(:active_statuses AS text[])) LIMIT 1"
            ),
            {
                "tenant_id": str(tenant_id),
                "niche_brief_id": str(niche_brief_id),
                "active_statuses": list(_ACTIVE_STATUSES),
            },
        ).first()
        return row is not None


def update_status(tenant_id: UUID, run_id: UUID, *, status: str, started_at: datetime | None = None) -> None:
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                """
                UPDATE pi_research_run
                SET status = :status,
                    started_at = COALESCE(:started_at, started_at)
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(run_id),
                "status": status,
                "started_at": started_at,
            },
        )
        if result.rowcount == 0:
            raise ValueError(f"pi_research_run {run_id} not found for tenant {tenant_id}")


def finish_run(tenant_id: UUID, run_id: UUID, *, status: str, finished_at: datetime) -> None:
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                "UPDATE pi_research_run SET status = :status, finished_at = :finished_at "
                "WHERE tenant_id = :tenant_id AND id = :id"
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(run_id),
                "status": status,
                "finished_at": finished_at,
            },
        )
        if result.rowcount == 0:
            raise ValueError(f"pi_research_run {run_id} not found for tenant {tenant_id}")


def record_outcome(tenant_id: UUID, run_id: UUID, *, outcome_code: str, usage_due: bool) -> bool:
    """Stores the run's accounting decision ONCE (first writer wins). Returns True only for the call that stored it, so only that
    caller may write usage events. Legacy rows (created_at IS NULL) are never given a decision (migration 20261011_0002)."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                "UPDATE pi_research_run SET outcome_code = :outcome_code, usage_due = :usage_due "
                "WHERE tenant_id = :tenant_id AND id = :id AND created_at IS NOT NULL AND usage_due IS NULL AND outcome_code IS NULL"
            ),
            {"tenant_id": str(tenant_id), "id": str(run_id), "outcome_code": outcome_code, "usage_due": usage_due},
        )
        return result.rowcount == 1


def operational_counts(tenant_id: UUID) -> dict[str, int]:
    """Operational counts of runs, kept SEPARATE from usage (Q-R3): `started` = every row ever inserted (what `count_runs_for_tenant`
    has always returned), `failed` = status FAILED, `interrupted` = reconciled as interrupted/unknown-outcome, `successful` = runs whose stored
    decision says they were billable. Legacy rows (no decision) are only ever counted as started/failed."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT count(*) AS started, "
                "count(*) FILTER (WHERE status = 'FAILED') AS failed, "
                "count(*) FILTER (WHERE outcome_code IN ('INTERRUPTED', 'OUTCOME_UNKNOWN')) AS interrupted, "
                "count(*) FILTER (WHERE usage_due IS TRUE) AS successful "
                "FROM pi_research_run WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": str(tenant_id)},
        ).one()
    return {"started": int(row.started), "failed": int(row.failed), "interrupted": int(row.interrupted), "successful": int(row.successful)}


def latest_run_for_tenant(tenant_id: UUID, *, finished_only: bool = False) -> dict[str, Any] | None:
    """The tenant's most recent research run (a QUEUED run, which has no `started_at` yet, counts as the newest). With `finished_only`, the most recent
    COMPLETE or PARTIAL run (the only ones that have a report). Status and dates only. A read for the CEO (spec 6.13)."""
    where = "AND status IN ('COMPLETE', 'PARTIAL') " if finished_only else ""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT id, niche_brief_id, depth, trigger, status, started_at, finished_at FROM pi_research_run "
                "WHERE tenant_id = :tenant_id " + where + "ORDER BY (started_at IS NULL) DESC, started_at DESC, id LIMIT 1"
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
    return dict(row) if row is not None else None
