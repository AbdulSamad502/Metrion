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


def title_sets_for_sku(tenant_id: UUID, sku: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """The NEWEST complete title set per marketplace for ONE product (a set written for another product is never offered), newest first, each with its ranked options."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT g.id, g.marketplace, g.sku, g.created_at FROM cmo_generation g WHERE g.tenant_id = :t AND g.sku = :sku AND g.output_type = 'TITLE_SET' AND g.status = 'COMPLETE' "
                 "ORDER BY g.created_at DESC, g.id LIMIT :limit"), {"t": tenant_id, "sku": sku, "limit": limit}).all()
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


def copy_pack_marketplaces(tenant_id: UUID, sku: str) -> set[str]:
    """The marketplaces for which a COMPLETE listing copy pack (description, bullet points and keywords together) is saved for this product."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text("SELECT DISTINCT marketplace FROM cmo_generation WHERE tenant_id = :t AND sku = :sku AND output_type = 'LISTING_COPY' AND status = 'COMPLETE'"), {"t": tenant_id, "sku": sku}).all()
    return {str(r.marketplace) for r in rows}


def has_photo_fact(tenant_id: UUID, sku: str) -> bool:
    """True when the seller confirmed at least one detail from a photo reading for this product (a fact linked to an image analysis)."""
    with tenant_scope(tenant_id) as conn:
        return conn.execute(text("SELECT 1 FROM seller_fact WHERE tenant_id = :t AND sku = :sku AND image_analysis_id IS NOT NULL LIMIT 1"), {"t": tenant_id, "sku": sku}).first() is not None


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


# ------------------------------------------------------------------------------------------------ CMO 3.0 M6: the saved listing, its states, and "approved for use"
_PACK = text(
    """
    SELECT id, marketplace, sku, request_key, grounding_approval_id, grounding_basis, format_constraint_ref, input_mode, ci_inputs_snapshot, output_structured, created_at
    FROM cmo_generation WHERE tenant_id = :t AND id = :g AND output_type = 'LISTING_COPY' AND status = 'COMPLETE'
    """
)
_TERMS = text(
    """
    SELECT output_structured -> 'backend_terms' AS terms FROM cmo_generation
    WHERE tenant_id = :t AND output_type = 'BACKEND_TERMS' AND status = 'COMPLETE' AND request_key = :k
    """
)
_EVENT_STATES = text(
    """
    SELECT event_kind, count(*) AS n, max(occurred_at) AS last_at FROM cmo_result_usage_event
    WHERE tenant_id = :t AND generation_id = :g AND event_kind IN ('GENERATED', 'COPIED', 'MARKED_USED', 'APPROVED') GROUP BY event_kind
    """
)
_AUDITED = text("SELECT verdict, created_at FROM cmo_listing_audit WHERE tenant_id = :t AND generation_id = :g ORDER BY created_at DESC, id LIMIT 1")
_APPROVE = text(
    """
    INSERT INTO cmo_result_usage_event (tenant_id, generation_id, option_id, result_part, event_kind, actor_user_id, surface)
    SELECT :t, :g, NULL, NULL, 'APPROVED', :u, 'CHAT'
    WHERE NOT EXISTS (SELECT 1 FROM cmo_result_usage_event x WHERE x.tenant_id = :t AND x.generation_id = :g AND x.event_kind = 'APPROVED')
    """
)


def listing_pack(tenant_id: UUID, generation_id: UUID) -> dict[str, Any] | None:
    """One saved, complete listing copy pack (the CMO artefact the M6 listing is built on), or None. A foreign or unknown id is None (identical to missing)."""
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_PACK, {"t": tenant_id, "g": generation_id}).first()
    if r is None:
        return None
    s = r.output_structured if isinstance(r.output_structured, dict) else {}
    return {"id": str(r.id), "marketplace": str(r.marketplace), "sku": r.sku, "requestKey": str(r.request_key), "approvalId": r.grounding_approval_id, "groundingBasis": r.grounding_basis,
            "constraintRef": str(r.format_constraint_ref) if r.format_constraint_ref else None, "inputMode": str(r.input_mode), "ciSnapshot": r.ci_inputs_snapshot, "structured": s,
            "revisionOf": s.get("revision_of"), "createdAt": r.created_at}


def backend_terms_for(tenant_id: UUID, pack_request_key: str) -> list[str] | None:
    """The Amazon backend terms written alongside an original pack: the sibling artefact saved under the derived key (`<key>:copy` -> `<key>:terms`). None when there are none."""
    if not pack_request_key.endswith(":copy"):
        return None
    key = pack_request_key[: -len(":copy")] + ":terms"
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_TERMS, {"t": tenant_id, "k": key}).first()
    return [str(x) for x in r.terms] if r is not None and isinstance(r.terms, list) else None


def listing_states(tenant_id: UUID, generation_id: UUID) -> dict[str, Any]:
    """The separate recorded facts about ONE saved version: generated, audited, approved for use, copied, marked used. There is no published/live state: Metrion cannot know it."""
    with tenant_scope(tenant_id) as conn:
        ev = {r.event_kind: (int(r.n), r.last_at) for r in conn.execute(_EVENT_STATES, {"t": tenant_id, "g": generation_id})}
        aud = conn.execute(_AUDITED, {"t": tenant_id, "g": generation_id}).first()

    def at(kind: str) -> str | None:
        return ev[kind][1].isoformat() if kind in ev else None

    return {
        "generated": {"done": "GENERATED" in ev, "at": at("GENERATED")},
        "audited": {"done": aud is not None, "at": aud.created_at.isoformat() if aud else None, "verdict": str(aud.verdict) if aud else None},
        "approvedForUse": {"done": "APPROVED" in ev, "at": at("APPROVED"), "meaning": "Approved for use in Metrion; not published."},
        "copied": {"count": ev.get("COPIED", (0, None))[0], "at": at("COPIED")},
        "markedUsed": {"count": ev.get("MARKED_USED", (0, None))[0], "at": at("MARKED_USED")},
        "published": {"known": False, "note": "Metrion cannot see or change what is on a marketplace."},
    }


def record_approved(tenant_id: UUID, user_id: UUID, generation_id: UUID) -> bool:
    """Append the seller's approval of this exact saved version (once per version). True when newly written. 0 units; never a metered event; not a publication."""
    with tenant_scope(tenant_id) as conn:
        if conn.execute(_PACK, {"t": tenant_id, "g": generation_id}).first() is None:
            return False
        return conn.execute(_APPROVE, {"t": tenant_id, "g": generation_id, "u": user_id}).rowcount == 1


_LATEST_PACK = text(
    """
    SELECT id FROM cmo_generation WHERE tenant_id = :t AND output_type = 'LISTING_COPY' AND status = 'COMPLETE'
      AND (CAST(:sku AS text) IS NULL OR sku = :sku) AND (CAST(:mp AS text) IS NULL OR marketplace = :mp)
    ORDER BY created_at DESC, id LIMIT 1
    """
)


def latest_listing_pack(tenant_id: UUID, *, sku: str | None = None, marketplace: str | None = None) -> UUID | None:
    """The id of the seller's newest complete listing pack (for one product / marketplace when given), or None."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_LATEST_PACK, {"t": tenant_id, "sku": sku, "mp": marketplace}).first()
    return row.id if row else None


# ------------------------------------------------------------------------------------------------ CMO 3.0 M6: is a saved listing built from the title approved NOW (N-15d)?
_APPROVAL_REF = text("SELECT id, approved_text, approved_at FROM cmo_title_approval WHERE tenant_id = :t AND id = :a")
_CURRENT_APPROVAL = text(
    """
    SELECT a.id, a.approved_text, a.approved_at FROM cmo_title_approval a JOIN cmo_generation g ON g.tenant_id = a.tenant_id AND g.id = a.generation_id
    WHERE a.tenant_id = :t AND g.sku = :sku AND g.marketplace = :mp ORDER BY a.approved_at DESC, a.id DESC LIMIT 1
    """
)
_PRODUCT_LABEL = text(
    "SELECT fact_value FROM seller_fact WHERE tenant_id = :t AND sku = :sku AND attribute_name = 'product_name' AND fact_value IS NOT NULL ORDER BY provided_at DESC LIMIT 1"
)


def approval_ref(tenant_id: UUID, approval_id: UUID) -> dict[str, Any] | None:
    """One of the seller's title approvals (id, text, when), or None. A foreign or unknown id is None."""
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_APPROVAL_REF, {"t": tenant_id, "a": approval_id}).first()
    return {"id": str(r.id), "text": str(r.approved_text), "approvedAt": r.approved_at} if r else None


def current_approval(tenant_id: UUID, sku: str, marketplace: str) -> dict[str, Any] | None:
    """The seller's NEWEST approved title for this product and marketplace, or None. Only an approval counts: a title option nobody chose is never "current"."""
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_CURRENT_APPROVAL, {"t": tenant_id, "sku": sku, "mp": marketplace}).first()
    return {"id": str(r.id), "text": str(r.approved_text), "approvedAt": r.approved_at} if r else None


def product_label(tenant_id: UUID, sku: str) -> str | None:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_PRODUCT_LABEL, {"t": tenant_id, "sku": sku}).first()
    return str(r.fact_value) if r else None


_SET_PRODUCT = text("SELECT sku, marketplace FROM cmo_generation WHERE tenant_id = :t AND id = :g AND output_type = 'TITLE_SET'")


def title_set_product(tenant_id: UUID, generation_id: UUID) -> tuple[str, str] | None:
    """(sku, marketplace) of one of the seller's title sets, or None."""
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_SET_PRODUCT, {"t": tenant_id, "g": generation_id}).first()
    return (str(r.sku), str(r.marketplace)) if r and r.sku else None
