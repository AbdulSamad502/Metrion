"""CMO 3.0 M9: which stored images belong to which product (append-only assignment events) and the immutable image quality reviews. Tenant-scoped (RLS), `SELECT`/`INSERT` only, no model, no inference.

The images themselves live in `seller_image_asset` (written by the existing upload path, untouched here). An assignment never changes or deletes an image; the newest event per (sku, marketplace, asset) is current
and the earlier ones are the audit trail."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.tenant_context import tenant_scope

_INSERT_EVENT = text(
    """
    INSERT INTO cmo_product_image (tenant_id, asset_id, sku, marketplace, role, shot_type, position, assigned_by, assigned_at)
    VALUES (:t, :asset, :sku, :mp, :role, :shot, :pos, :u, clock_timestamp())
    RETURNING id, assigned_at
    """
)
_CURRENT = text(
    """
    SELECT * FROM (
      SELECT DISTINCT ON (pi.asset_id) pi.asset_id, pi.role, pi.shot_type, pi.position, pi.assigned_at, a.sha256, a.storage_uri, a.byte_size, a.content_type
      FROM cmo_product_image pi JOIN seller_image_asset a ON a.tenant_id = pi.tenant_id AND a.id = pi.asset_id
      WHERE pi.tenant_id = :t AND pi.sku = :sku AND pi.marketplace = :mp
      ORDER BY pi.asset_id, pi.assigned_at DESC, pi.id DESC
    ) cur WHERE role <> 'REMOVED'
    ORDER BY (role = 'PRIMARY') DESC, position, assigned_at, asset_id
    """
)
_EVENTS = text(
    """
    SELECT id, asset_id, role, shot_type, position, assigned_at FROM cmo_product_image
    WHERE tenant_id = :t AND sku = :sku AND marketplace = :mp ORDER BY assigned_at DESC, id DESC LIMIT :limit
    """
)
_SETS = text(
    """
    SELECT sku, marketplace, count(*) AS images FROM (
      SELECT DISTINCT ON (sku, marketplace, asset_id) sku, marketplace, role
      FROM cmo_product_image WHERE tenant_id = :t ORDER BY sku, marketplace, asset_id, assigned_at DESC, id DESC
    ) cur WHERE role <> 'REMOVED' GROUP BY sku, marketplace ORDER BY sku, marketplace
    """
)
_SERVABLE = text(
    """
    SELECT a.storage_uri, a.content_type, a.sha256 FROM seller_image_asset a
    WHERE a.tenant_id = :t AND a.id = :asset AND a.status = 'ACTIVE' AND EXISTS (SELECT 1 FROM cmo_product_image pi WHERE pi.tenant_id = a.tenant_id AND pi.asset_id = a.id)
    """
)
_INSERT_REVIEW = text(
    """
    INSERT INTO cmo_image_review (tenant_id, sku, marketplace, method_version, input_hash, score_state, score, image_count, report, created_by)
    VALUES (:t, :sku, :mp, :method, :hash, :state, :score, :n, CAST(:report AS jsonb), :u)
    ON CONFLICT (tenant_id, sku, marketplace, input_hash) DO NOTHING
    RETURNING id, created_at
    """
)
_REVIEW_BY_HASH = text(
    "SELECT id, created_at, score_state, score, image_count, report FROM cmo_image_review WHERE tenant_id = :t AND sku = :sku AND marketplace = :mp AND input_hash = :hash"
)
_LATEST_REVIEW = text(
    "SELECT id, created_at, score_state, score, image_count, input_hash, report FROM cmo_image_review WHERE tenant_id = :t AND sku = :sku AND marketplace = :mp ORDER BY created_at DESC, id DESC LIMIT 1"
)
_REVIEW_HISTORY = text(
    "SELECT id, created_at, score_state, score, image_count, method_version FROM cmo_image_review WHERE tenant_id = :t AND sku = :sku AND marketplace = :mp ORDER BY created_at DESC, id DESC LIMIT :limit"
)
_SKUS_WITH_IMAGES = text("SELECT DISTINCT sku FROM cmo_product_image WHERE tenant_id = :t")


class UnknownAsset(Exception):
    """The image does not exist for this seller (or belongs to another tenant: the composite foreign key refuses it)."""


def current_set(tenant_id: UUID, sku: str, marketplace: str) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_CURRENT, {"t": tenant_id, "sku": sku, "mp": marketplace}).all()
    return [{"assetId": r.asset_id, "role": str(r.role), "shotType": str(r.shot_type), "position": int(r.position), "assignedAt": r.assigned_at, "sha256": str(r.sha256),
             "storageUri": str(r.storage_uri), "byteSize": int(r.byte_size), "contentType": str(r.content_type)} for r in rows]


def add_event(tenant_id: UUID, user_id: UUID, *, asset_id: UUID, sku: str, marketplace: str, role: str, shot_type: str, position: int) -> dict[str, Any]:
    try:
        with tenant_scope(tenant_id) as conn:
            r = conn.execute(_INSERT_EVENT, {"t": tenant_id, "asset": asset_id, "sku": sku, "mp": marketplace, "role": role, "shot": shot_type, "pos": position, "u": user_id}).one()
    except IntegrityError:
        raise UnknownAsset from None
    return {"id": r.id, "assignedAt": r.assigned_at}


def add_events(tenant_id: UUID, user_id: UUID, events: list[dict[str, Any]]) -> None:
    """Several assignment events in ONE transaction (for example demoting the old main image and promoting the new one): all are written or none."""
    try:
        with tenant_scope(tenant_id) as conn:
            for e in events:
                conn.execute(_INSERT_EVENT, {"t": tenant_id, "asset": e["asset_id"], "sku": e["sku"], "mp": e["marketplace"], "role": e["role"], "shot": e["shot_type"], "pos": e["position"], "u": user_id})
    except IntegrityError:
        raise UnknownAsset from None


def events(tenant_id: UUID, sku: str, marketplace: str, limit: int = 50) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_EVENTS, {"t": tenant_id, "sku": sku, "mp": marketplace, "limit": limit}).all()
    return [{"assetId": str(r.asset_id), "role": str(r.role), "shotType": str(r.shot_type), "position": int(r.position), "at": r.assigned_at} for r in rows]


def sets_with_images(tenant_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_SETS, {"t": tenant_id}).all()
    return [{"sku": str(r.sku), "marketplace": str(r.marketplace), "images": int(r.images)} for r in rows]


def skus_with_images(tenant_id: UUID) -> set[str]:
    with tenant_scope(tenant_id) as conn:
        return {str(r.sku) for r in conn.execute(_SKUS_WITH_IMAGES, {"t": tenant_id}).all()}


def servable_asset(tenant_id: UUID, asset_id: UUID) -> dict[str, str] | None:
    """The stored location of an image THIS seller assigned to a product, else None. A chat attachment or an unassigned image is never served by the images page."""
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_SERVABLE, {"t": tenant_id, "asset": asset_id}).first()
    return {"storageUri": str(r.storage_uri), "contentType": str(r.content_type), "sha256": str(r.sha256)} if r else None


def save_review(tenant_id: UUID, user_id: UUID, *, sku: str, marketplace: str, method: str, input_hash: str, state: str, score: int | None, image_count: int, report: dict[str, Any]) -> tuple[UUID, bool]:
    """(review id, created). The same set reviewed again with the same method is the same row: nothing is written twice."""
    args = {"t": tenant_id, "sku": sku, "mp": marketplace, "method": method, "hash": input_hash, "state": state, "score": score, "n": image_count, "report": json.dumps(report, sort_keys=True), "u": user_id}
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_INSERT_REVIEW, args).first()
        if r is not None:
            return r.id, True
        existing = conn.execute(_REVIEW_BY_HASH, {"t": tenant_id, "sku": sku, "mp": marketplace, "hash": input_hash}).one()
    return existing.id, False


def latest_review(tenant_id: UUID, sku: str, marketplace: str) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        r = conn.execute(_LATEST_REVIEW, {"t": tenant_id, "sku": sku, "mp": marketplace}).first()
    if r is None:
        return None
    return {"id": r.id, "createdAt": r.created_at, "scoreState": str(r.score_state), "score": r.score, "imageCount": int(r.image_count), "inputHash": str(r.input_hash), "report": r.report}


def review_history(tenant_id: UUID, sku: str, marketplace: str, limit: int = 20) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_REVIEW_HISTORY, {"t": tenant_id, "sku": sku, "mp": marketplace, "limit": limit}).all()
    return [{"id": str(r.id), "createdAt": r.created_at, "scoreState": str(r.score_state), "score": r.score, "imageCount": int(r.image_count), "method": str(r.method_version)} for r in rows]
