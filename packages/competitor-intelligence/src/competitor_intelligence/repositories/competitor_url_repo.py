"""competitor_url — §5. Every function takes tenant_id first and receives its connection
only via tenant_scope(); no function in this module opens its own connection.

§6.1 rule 1: `url` is reference-only (never fetched, at intake or ever) — the allowlist check
below is now a labeling/format validation (C4/D7), not a fetch gate. `capture/allowlist.py`'s
`is_allowed_host` is reused unchanged here; only its calling context moved.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import os

from sqlalchemy import text

from competitor_intelligence.capture.allowlist import is_allowed_host
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import Marketplace, UrlStatus


DEFAULT_WATCHLIST_LIMIT = 5  # the most ACTIVE tracked competitors one seller keeps, across every product and marketplace; a tenant's own limit (ci_tenant_config) overrides it


class WatchlistFull(Exception):
    """The seller already tracks the most competitors allowed. `active` names them (so the seller can choose one to stop tracking)."""

    def __init__(self, limit: int, active: list[dict[str, Any]]) -> None:
        super().__init__(f"{len(active)} of {limit} competitor slots are used")
        self.limit, self.active = limit, active


def default_watchlist_limit() -> int:
    raw = (os.environ.get("CI_DEFAULT_WATCHLIST_LIMIT") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_WATCHLIST_LIMIT


def _enforce_watchlist_cap(conn: Any, tenant_id: UUID) -> None:
    """Called inside the transaction that adds (or restores) a competitor. A per-tenant transaction lock serialises concurrent adds, so two requests can never both take the last
    slot; the count and the write happen under the same lock. Stopped competitors and pending discovery leads are not ACTIVE and do not count."""
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"ci-watchlist:{tenant_id}"})
    own = conn.execute(text("SELECT max_active_competitors FROM ci_tenant_config WHERE tenant_id = :t"), {"t": str(tenant_id)}).scalar()
    limit = int(own) if own else default_watchlist_limit()
    rows = conn.execute(text("SELECT id, marketplace, url, label, linked_sku FROM competitor_url WHERE tenant_id = :t AND status = 'ACTIVE' ORDER BY created_at"), {"t": str(tenant_id)}).mappings().all()
    if len(rows) >= limit:
        raise WatchlistFull(limit, [dict(r) for r in rows])


def watchlist_status(tenant_id: UUID) -> dict[str, Any]:
    """The seller's competitor slots: the limit, how many are used and who holds them (read-only)."""
    with tenant_scope(tenant_id) as conn:
        own = conn.execute(text("SELECT max_active_competitors FROM ci_tenant_config WHERE tenant_id = :t"), {"t": str(tenant_id)}).scalar()
        rows = conn.execute(text("SELECT id, marketplace, url, label, linked_sku FROM competitor_url WHERE tenant_id = :t AND status = 'ACTIVE' ORDER BY created_at"), {"t": str(tenant_id)}).mappings().all()
    limit = int(own) if own else default_watchlist_limit()
    return {"limit": limit, "active": [dict(r) for r in rows], "free": max(0, limit - len(rows))}


def create_url(
    tenant_id: UUID,
    *,
    marketplace: Marketplace,
    url: str,
    added_by: UUID,
    label: str | None = None,
    linked_sku: str | None = None,
) -> UUID:
    if not is_allowed_host(url):
        raise ValueError(
            f"'{url}' is not on the trusted-domain allowlist (amazon.in/amzn.in, "
            "flipkart.com/fkrt.co, meesho.com) — refused (C4/D7)."
        )
    with tenant_scope(tenant_id) as conn:
        _enforce_watchlist_cap(conn, tenant_id)
        row = conn.execute(
            text(
                """
                INSERT INTO competitor_url (tenant_id, marketplace, url, label, linked_sku, status, added_by)
                VALUES (:tenant_id, :marketplace, :url, :label, :linked_sku, :status, :added_by)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "marketplace": marketplace.value,
                "url": url,
                "label": label,
                "linked_sku": linked_sku,
                "status": UrlStatus.ACTIVE.value,
                "added_by": str(added_by),
            },
        ).one()
        return cast(UUID, row[0])


def get_by_ids(tenant_id: UUID, url_ids: list[UUID]) -> list[dict[str, Any]]:
    """Only ACTIVE urls owned by this tenant — silently drops ids that are ARCHIVED,
    belong to another tenant (RLS), or don't exist. Caller (direct_path) is responsible for
    treating a shorter result than requested as a partial run, not an error.

    Includes the per-URL alert-override columns (§5) so a caller resolving the effective
    price/availability alert config never needs a second query."""
    if not url_ids:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, marketplace, url, label, linked_sku, status, tags,
                       price_threshold_pct_override, alert_on_availability_change_override
                FROM competitor_url
                WHERE tenant_id = :tenant_id AND id = ANY(CAST(:url_ids AS uuid[])) AND status = 'ACTIVE'
                """
            ),
            {"tenant_id": str(tenant_id), "url_ids": [str(u) for u in url_ids]},
        ).mappings()
        return [dict(r) for r in rows]


def list_active_by_linked_sku(tenant_id: UUID, linked_sku: str) -> list[dict[str, Any]]:
    """Checkpoint 6 — every ACTIVE tracked competitor scoped to one seller product, the
    grouping `landscape/price_band.py` and the comparison module need. Only returns rows
    whose `linked_sku` was actually set at accept-time (discovery_run.py's
    `accept_candidate`) or manual intake — a competitor_url with no linkage recorded is
    correctly excluded here, never guessed into a product it wasn't tracked against."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, marketplace, url, label, linked_sku, status, tags
                FROM competitor_url
                WHERE tenant_id = :tenant_id AND linked_sku = :linked_sku AND status = 'ACTIVE'
                """
            ),
            {"tenant_id": str(tenant_id), "linked_sku": linked_sku},
        ).mappings()
        return [dict(r) for r in rows]


def count_active(tenant_id: UUID) -> int:
    """Real, already-queryable per-tenant usage — the number an entitlement cap would
    compare against once one is locked (auth.md: "entitlement spec (not yet written)").
    This function makes no claim about what any cap should be."""
    with tenant_scope(tenant_id) as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM competitor_url WHERE tenant_id = :tenant_id AND status = 'ACTIVE'"),
                {"tenant_id": str(tenant_id)},
            ).scalar_one()
        )


def set_tags(tenant_id: UUID, url_id: UUID, tags: list[str]) -> None:
    """§5 `competitor_url.tags` — free-form tenant labels (e.g. 'DIRECT_RIVAL',
    'ASPIRATIONAL'). Replaces the full tag list; the caller (API layer) owns any
    add/remove-single-tag semantics on top of this."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE competitor_url SET tags = CAST(:tags AS text[]) WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(url_id), "tags": tags},
        )


def set_alert_overrides(
    tenant_id: UUID,
    url_id: UUID,
    *,
    price_threshold_pct_override: Decimal | None,
    alert_on_availability_change_override: bool | None,
) -> None:
    """§5 per-URL alert config override (D2/Q5) — `None` for either argument clears that
    override back to the tenant-wide default in `ci_tenant_config`, it does not leave the
    prior override untouched (this always sets both columns explicitly)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE competitor_url
                SET price_threshold_pct_override = :price_threshold_pct_override,
                    alert_on_availability_change_override = :alert_on_availability_change_override
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(url_id),
                "price_threshold_pct_override": price_threshold_pct_override,
                "alert_on_availability_change_override": alert_on_availability_change_override,
            },
        )


def archive_url(tenant_id: UUID, url_id: UUID) -> None:
    """Sets status to ARCHIVED — an archived URL is excluded from `get_by_ids` (the ACTIVE
    filter), so it stops being eligible for `ci.research_now`, but its snapshots/price
    events/evidence are never deleted (history is never destroyed by an archive)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE competitor_url SET status = :status WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(url_id), "status": UrlStatus.ARCHIVED.value},
        )


def list_active_with_url(tenant_id: UUID) -> list[dict[str, Any]]:
    """The tenant's ACTIVE tracked competitors in the order they were added, with the listing link the seller gave (read-only)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text("SELECT id, marketplace, url, label FROM competitor_url WHERE tenant_id = :t AND status = 'ACTIVE' ORDER BY created_at, id"), {"t": str(tenant_id)}).mappings().all()
    return [dict(r) for r in rows]


def list_active(tenant_id: UUID, *, limit: int) -> list[dict[str, Any]]:
    """The tenant's ACTIVE tracked competitors, newest first, at most `limit`. A read for the CEO's Business State (spec 6.13): ids, marketplace and
    the seller's own label only; the capture itself is read through `build_ci_handoff_snapshot`."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT id, marketplace, label, status, url FROM competitor_url "
                "WHERE tenant_id = :tenant_id AND status = 'ACTIVE' ORDER BY created_at DESC, id LIMIT :limit"
            ),
            {"tenant_id": str(tenant_id), "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def set_label_if_blank(tenant_id: UUID, url_id: UUID, label: str) -> bool:
    """Gives a tracked competitor the seller's own name when it has none. A name the seller already gave is never overwritten."""
    with tenant_scope(tenant_id) as conn:
        n = conn.execute(
            text("UPDATE competitor_url SET label = :label WHERE tenant_id = :t AND id = :id AND (label IS NULL OR btrim(label) = '')"),
            {"label": label[:120], "t": str(tenant_id), "id": str(url_id)},
        ).rowcount
    return n > 0


def list_archived(tenant_id: UUID, *, limit: int = 50) -> list[dict[str, Any]]:
    """Competitors the seller stopped tracking (history kept), newest removal first."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT id, marketplace, url, label, linked_sku, removed_at FROM competitor_url WHERE tenant_id = :t AND status = 'ARCHIVED' ORDER BY removed_at DESC NULLS LAST LIMIT :n"),
            {"t": str(tenant_id), "n": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def find_by_url(tenant_id: UUID, url: str) -> dict[str, Any] | None:
    """Any row (ACTIVE or ARCHIVED) for this exact URL in this tenant — used to avoid
    duplicating a tracked competitor and to restore a removed one (§6.24)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT id, status, linked_sku FROM competitor_url WHERE tenant_id = :tenant_id AND url = :url ORDER BY created_at LIMIT 1"),
            {"tenant_id": str(tenant_id), "url": url},
        ).mappings().first()
        return dict(row) if row else None


def get_any_by_id(tenant_id: UUID, url_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT id, status, linked_sku, label, marketplace, url FROM competitor_url WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(url_id)},
        ).mappings().first()
        return dict(row) if row else None


def soft_remove(tenant_id: UUID, url_id: UUID, *, removed_by: UUID, reason: str | None) -> None:
    """C39: archive + who/when/why. Evidence, snapshots and events are never deleted."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                "UPDATE competitor_url SET status = 'ARCHIVED', removed_at = now(), removed_by = :removed_by, removal_reason = :reason "
                "WHERE tenant_id = :tenant_id AND id = :id"
            ),
            {"tenant_id": str(tenant_id), "id": str(url_id), "removed_by": str(removed_by), "reason": reason},
        )


def restore_url(tenant_id: UUID, url_id: UUID, *, linked_sku: str | None) -> None:
    with tenant_scope(tenant_id) as conn:
        if conn.execute(text("SELECT status FROM competitor_url WHERE tenant_id = :t AND id = :id"), {"t": str(tenant_id), "id": str(url_id)}).scalar() != "ACTIVE":
            _enforce_watchlist_cap(conn, tenant_id)  # bringing one back takes a slot like adding a new one
        conn.execute(
            text(
                "UPDATE competitor_url SET status = 'ACTIVE', removed_at = NULL, removed_by = NULL, removal_reason = NULL, "
                "linked_sku = COALESCE(:linked_sku, linked_sku) WHERE tenant_id = :tenant_id AND id = :id"
            ),
            {"tenant_id": str(tenant_id), "id": str(url_id), "linked_sku": linked_sku},
        )


def list_linked_skus(tenant_id: UUID) -> list[str]:
    """Distinct seller products that have at least one ACTIVE tracked competitor."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT DISTINCT linked_sku FROM competitor_url WHERE tenant_id = :tenant_id AND status = 'ACTIVE' AND linked_sku IS NOT NULL ORDER BY linked_sku"),
            {"tenant_id": str(tenant_id)},
        )
        return [r[0] for r in rows]
