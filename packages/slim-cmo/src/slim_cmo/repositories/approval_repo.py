"""`cmo_title_approval` (spec §5, C8). Append-only: re-approving inserts a NEW row.

The composite foreign keys guarantee the generation and the option belong to this tenant and that
the option belongs to that generation, so a cross-tenant or cross-set id cannot be persisted even
if the service were wrong.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, text

from slim_cmo.service.models import StoredApproval
from slim_cmo.types import Marketplace

_INSERT = text(
    """
    INSERT INTO cmo_title_approval (tenant_id, generation_id, option_id, approved_text, edited_by_seller, approved_by)
    VALUES (:tenant_id, :generation_id, :option_id, :approved_text, :edited_by_seller, :approved_by)
    RETURNING id
    """
)
_INSERT_TYPED = text(
    """
    INSERT INTO cmo_title_approval (tenant_id, generation_id, option_id, approved_text, edited_by_seller, approved_by, title_source, sku, marketplace)
    VALUES (:tenant_id, NULL, NULL, :approved_text, true, :approved_by, 'SELLER_TYPED', :sku, :marketplace)
    RETURNING id
    """
)
_LOAD = text(
    """
    SELECT a.id, a.tenant_id, a.generation_id, a.approved_text, a.edited_by_seller, COALESCE(g.marketplace, a.marketplace) AS marketplace, COALESCE(g.sku, a.sku) AS sku
    FROM cmo_title_approval a
    LEFT JOIN cmo_generation g ON g.tenant_id = a.tenant_id AND g.id = a.generation_id
    WHERE a.tenant_id = :tenant_id AND a.id = :id
    """
)


def insert_approval(
    conn: Connection,
    tenant_id: UUID,
    *,
    generation_id: UUID,
    option_id: UUID | None,
    approved_text: str,
    edited_by_seller: bool,
    approved_by: UUID,
) -> UUID:
    row = conn.execute(
        _INSERT,
        {
            "tenant_id": tenant_id, "generation_id": generation_id, "option_id": option_id,
            "approved_text": approved_text, "edited_by_seller": edited_by_seller, "approved_by": approved_by,
        },
    ).one()
    approval_id: UUID = row.id
    return approval_id


def insert_typed_approval(conn: Connection, tenant_id: UUID, *, sku: str, marketplace: str, approved_text: str, approved_by: UUID) -> UUID:
    """The seller's explicit approval of a title they TYPED: no generation, no option (`title_source = 'SELLER_TYPED'`). Append-only like every approval."""
    row = conn.execute(
        _INSERT_TYPED, {"tenant_id": tenant_id, "approved_text": approved_text, "approved_by": approved_by, "sku": sku, "marketplace": marketplace},
    ).one()
    approval_id: UUID = row.id
    return approval_id


def load_approval(conn: Connection, tenant_id: UUID, approval_id: UUID) -> StoredApproval | None:
    r = conn.execute(_LOAD, {"tenant_id": tenant_id, "id": approval_id}).first()
    if r is None or r.marketplace is None:
        return None
    return StoredApproval(
        r.id, r.tenant_id, r.generation_id, Marketplace(r.marketplace), r.sku, r.approved_text, r.edited_by_seller
    )
