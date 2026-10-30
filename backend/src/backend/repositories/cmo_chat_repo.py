"""Tenant-scoped READS behind the CEO's CMO chat steps (CMO 3.0 M0): which title sets the seller can choose from, which titles they approved (with the copy / mark-used
actions recorded for them), and the facts they already gave for one product.

Every query runs inside `tenant_scope` (RLS, FORCE) and filters `tenant_id` explicitly in SQL. Nothing here writes, calls a model or computes anything beyond counts of
recorded events. Stored text is returned verbatim; nothing is invented.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.tenant_context import tenant_scope

_TITLE_SETS = text(
    """
    SELECT g.id, g.marketplace, g.sku, g.created_at FROM cmo_generation g
    WHERE g.tenant_id = :t AND g.output_type = 'TITLE_SET' AND g.status = 'COMPLETE'
    ORDER BY g.created_at DESC, g.id LIMIT :limit
    """
)
_OPTIONS = text(
    "SELECT id, rank, title_text FROM cmo_title_option WHERE tenant_id = :t AND generation_id = :g ORDER BY rank"
)
_APPROVED = text(
    """
    SELECT a.id, a.generation_id, a.option_id, a.approved_text, a.edited_by_seller, a.approved_at, g.marketplace, g.sku,
           COALESCE((SELECT sf.fact_value FROM seller_fact sf WHERE sf.tenant_id = g.tenant_id AND sf.sku = g.sku
                     AND sf.attribute_name = 'product_name' ORDER BY sf.provided_at DESC LIMIT 1), g.sku) AS label,
           (SELECT count(*) FROM cmo_result_usage_event e WHERE e.tenant_id = a.tenant_id AND e.generation_id = a.generation_id
              AND e.event_kind = 'COPIED' AND (a.option_id IS NULL OR e.option_id = a.option_id)) AS copied,
           (SELECT count(*) FROM cmo_result_usage_event e WHERE e.tenant_id = a.tenant_id AND e.generation_id = a.generation_id
              AND e.event_kind = 'MARKED_USED' AND (a.option_id IS NULL OR e.option_id = a.option_id)) AS marked_used
    FROM cmo_title_approval a JOIN cmo_generation g ON g.tenant_id = a.tenant_id AND g.id = a.generation_id
    WHERE a.tenant_id = :t AND (CAST(:sku AS text) IS NULL OR g.sku = :sku) AND (CAST(:mp AS text) IS NULL OR g.marketplace = :mp)
    ORDER BY a.approved_at DESC, a.id LIMIT :limit
    """
)
_FACTS = text(
    """
    SELECT fact_type, attribute_name, fact_value, provided_at FROM seller_fact
    WHERE tenant_id = :t AND sku = :sku AND fact_value IS NOT NULL ORDER BY provided_at, id
    """
)
_APPROVAL_TEXT = text("SELECT approved_text FROM cmo_title_approval WHERE tenant_id = :t AND id = :a")


def recent_title_sets(tenant_id: UUID, *, limit: int = 12) -> list[dict[str, Any]]:
    """The NEWEST complete title set per marketplace, newest first, each with its ranked options. A title set the seller has not chosen from is what they can choose now."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_TITLE_SETS, {"t": tenant_id, "limit": limit}).all()
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for r in rows:
            if r.marketplace in seen:
                continue
            seen.add(r.marketplace)
            options = conn.execute(_OPTIONS, {"t": tenant_id, "g": r.id}).all()
            if options:
                out.append({"generationId": str(r.id), "marketplace": r.marketplace, "sku": r.sku, "createdAt": r.created_at,
                            "options": [{"id": str(o.id), "rank": int(o.rank), "text": str(o.title_text)} for o in options]})
        return out


def approved_titles(tenant_id: UUID, *, sku: str | None = None, marketplace: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_APPROVED, {"t": tenant_id, "sku": sku, "mp": marketplace, "limit": limit}).all()
    return [{"approvalId": str(r.id), "generationId": str(r.generation_id), "text": str(r.approved_text), "editedBySeller": bool(r.edited_by_seller), "approvedAt": r.approved_at,
             "marketplace": r.marketplace, "sku": r.sku, "label": r.label, "copied": int(r.copied), "markedUsed": int(r.marked_used)} for r in rows]


def saved_facts(tenant_id: UUID, sku: str) -> list[dict[str, Any]]:
    """The facts the seller gave for ONE exact sku, oldest first (a later statement overrides an earlier one). A sku-less lookup never exists: it would mix products."""
    if not sku:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_FACTS, {"t": tenant_id, "sku": sku}).all()
    return [{"type": str(r.fact_type), "name": r.attribute_name, "value": str(r.fact_value), "at": r.provided_at} for r in rows]


_PHOTO = text(
    """
    SELECT a.id, a.filename FROM investigation_plan p
    CROSS JOIN LATERAL jsonb_array_elements(p.plan -> 'legs') leg
    JOIN investigation_attachment a ON a.tenant_id = p.tenant_id AND a.investigation_id = p.investigation_id AND a.id::text = leg -> 'slots' ->> 'attachment_id'
    WHERE p.tenant_id = :t AND p.investigation_id = :inv AND p.status = 'APPROVED' AND leg ->> 'action_key' = 'cmo.analyze_attachment'
      AND a.detected_type IN ('PNG', 'JPEG', 'WEBP')
    ORDER BY p.created_at DESC LIMIT 1
    """
)


def photo_attachment(tenant_id: UUID, investigation_id: UUID) -> dict[str, str] | None:
    """The seller's own product photo in THIS conversation: the image they attached for Slim CMO to read (an approved photo-reading plan names it). Other images in the conversation, such as
    a competitor screenshot, are never taken for the product picture. None when there is none."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_PHOTO, {"t": tenant_id, "inv": investigation_id}).first()
    return {"id": str(row.id), "filename": str(row.filename)} if row else None


def profile_rows(tenant_id: UUID, sku: str) -> list[dict[str, Any]]:
    """Every statement the seller made about ONE exact sku, oldest first, with whether it was confirmed from a photo reading. No user ids leave this function."""
    if not sku:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT fact_type, attribute_name, fact_value, provided_at, image_analysis_id IS NOT NULL AS from_photo FROM seller_fact "
                "WHERE tenant_id = :t AND sku = :sku AND fact_value IS NOT NULL ORDER BY provided_at, id"
            ),
            {"t": tenant_id, "sku": sku},
        ).all()
    return [{"type": str(r.fact_type), "name": r.attribute_name, "value": str(r.fact_value), "at": r.provided_at, "fromPhoto": bool(r.from_photo)} for r in rows]


def product_names(tenant_id: UUID) -> list[tuple[str, str]]:
    """(sku, product name) for each product the seller named in chat, newest name per sku."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT ON (sku) sku, fact_value FROM seller_fact WHERE tenant_id = :t AND sku IS NOT NULL AND attribute_name = 'product_name' "
                "AND fact_value IS NOT NULL ORDER BY sku, provided_at DESC, id"
            ),
            {"t": tenant_id},
        ).all()
    return [(str(r.sku), str(r.fact_value)) for r in rows]


def approval_text(tenant_id: UUID, approval_id: UUID) -> str | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_APPROVAL_TEXT, {"t": tenant_id, "a": approval_id}).first()
    return str(row.approved_text) if row else None
