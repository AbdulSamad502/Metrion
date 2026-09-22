"""competitor_url — §5. Every function takes tenant_id first and receives its connection
only via tenant_scope(); no function in this module opens its own connection.

§6.1 rule 1: `url` is reference-only (never fetched, at intake or ever) — the allowlist check
below is now a labeling/format validation (C4/D7), not a fetch gate. `capture/allowlist.py`'s
`is_allowed_host` is reused unchanged here; only its calling context moved.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.capture.allowlist import is_allowed_host
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import Marketplace, UrlStatus


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
        return row[0]


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
