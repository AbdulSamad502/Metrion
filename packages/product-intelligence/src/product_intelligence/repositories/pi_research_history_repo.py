"""History, pinning and archiving of finished research reports — docs/specs/ceo-pi-research-flow.md C6.

Operates on `pi_research_run` (columns `pinned_at`, `archived_at`, `completed_at`, migration 20261014_0001) and reads `pi_tenant_config.history_unpinned_limit`.
Archiving never deletes: an archived report is hidden from history and purged later by the existing retention window. A pinned report is never archived (the
selection excludes it, and a CHECK constraint makes it impossible even by mistake). Every function takes `tenant_id` first and uses `tenant_scope()` only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope

_REPORT_STATUSES = ["COMPLETE", "PARTIAL"]
DEFAULT_HISTORY_UNPINNED_LIMIT = 10
_SORT_KEY = "COALESCE(r.completed_at, r.finished_at, r.started_at, r.created_at)"


def get_history_unpinned_limit(tenant_id: UUID) -> int:
    """How many unpinned reports stay in history before the oldest is archived (5..10, default 10)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT history_unpinned_limit FROM pi_tenant_config WHERE tenant_id = :tenant_id"), {"tenant_id": str(tenant_id)}
        ).first()
    return int(row[0]) if row is not None else DEFAULT_HISTORY_UNPINNED_LIMIT


def list_history(tenant_id: UUID) -> list[dict[str, Any]]:
    """Visible reports: finished (COMPLETE/PARTIAL) and not archived. Pinned first (latest pin first), then unpinned newest first."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                f"SELECT r.id, r.status, r.depth, r.pinned_at, {_SORT_KEY} AS sort_at, "
                "b.category_text, b.budget_paise, b.target_price_min_paise, b.target_price_max_paise, b.marketplaces "
                "FROM pi_research_run r JOIN niche_brief b ON b.id = r.niche_brief_id AND b.tenant_id = r.tenant_id "
                "WHERE r.tenant_id = :tenant_id AND r.status = ANY(CAST(:statuses AS text[])) AND r.archived_at IS NULL "
                "ORDER BY (r.pinned_at IS NULL), r.pinned_at DESC, sort_at DESC NULLS LAST, r.id"
            ),
            {"tenant_id": str(tenant_id), "statuses": _REPORT_STATUSES},
        ).mappings().all()
    return [dict(r) for r in rows]


def get_visible_run(tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
    """A finished, non-archived run of this tenant, else None (another tenant's id, an archived run and an unfinished run are all None)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT * FROM pi_research_run WHERE tenant_id = :tenant_id AND id = :id AND archived_at IS NULL "
                "AND status = ANY(CAST(:statuses AS text[]))"
            ),
            {"tenant_id": str(tenant_id), "id": str(run_id), "statuses": _REPORT_STATUSES},
        ).mappings().first()
    return dict(row) if row is not None else None


def mark_completed(tenant_id: UUID, run_id: UUID, *, completed_at: datetime) -> None:
    """Stamps the moment the research case was finished (set once)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE pi_research_run SET completed_at = COALESCE(completed_at, :at) WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(run_id), "at": completed_at},
        )


def set_pinned(tenant_id: UUID, run_id: UUID, *, pinned: bool, now: datetime) -> bool:
    """Idempotent pin/unpin. False when the run is not a visible report of this tenant."""
    value = "COALESCE(pinned_at, :now)" if pinned else "NULL"
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                f"UPDATE pi_research_run SET pinned_at = {value} WHERE tenant_id = :tenant_id AND id = :id "
                "AND archived_at IS NULL AND status = ANY(CAST(:statuses AS text[]))"
            ),
            {"tenant_id": str(tenant_id), "id": str(run_id), "now": now, "statuses": _REPORT_STATUSES},
        )
        return result.rowcount == 1


def archive_over_limit(tenant_id: UUID, *, limit: int, now: datetime) -> int:
    """Archives the oldest UNPINNED visible reports beyond the newest `limit`. Idempotent. Returns how many were archived."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                "UPDATE pi_research_run SET archived_at = :now WHERE tenant_id = :tenant_id AND id IN ("
                "SELECT r.id FROM pi_research_run r WHERE r.tenant_id = :tenant_id AND r.pinned_at IS NULL AND r.archived_at IS NULL "
                f"AND r.status = ANY(CAST(:statuses AS text[])) ORDER BY {_SORT_KEY} DESC NULLS LAST, r.id OFFSET :limit)"
            ),
            {"tenant_id": str(tenant_id), "now": now, "limit": int(limit), "statuses": _REPORT_STATUSES},
        )
        return int(result.rowcount)
