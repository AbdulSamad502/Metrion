"""The CMO's side of the CEO -> CMO attachment hand-off (docs/specs/ceo-cmo-delegation.md CD5, DD2, 6.5): `cmo.analyze_attachment`.

The CEO hands over a REFERENCE (`attachment_id`, optionally the `sha256` it saw). Nothing else crosses: no bytes, no thumbnail, no text, no model output. This module is the CMO
side: it re-validates the reference against the tenant AND the investigation under RLS (a foreign or other-conversation id is simply "not found"), loads the bytes through its own
tenant-scoped read, and runs the EXISTING image path - normalise (re-encoded to a fresh PNG, so EXIF/GPS and every other metadata field are dropped), store, analyse - so the
vision model only ever sees the CMO's stripped copy, never the original upload.

Order matters and fails closed: the vision endpoint is checked FIRST (`config.cmo_vision_endpoint_verified`, then the runtime build, which resolves the same endpoint). An endpoint
that is not attested in `LLM_OPERATOR_CONTROLLED_HOSTS` stops the hand-off before a single byte of the photo is read. The action is zero CMO units: it never reaches quota admission
or metering; the analysis is rate-limited per tenant by the existing image path. A failed or refused analysis uses nothing.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from slim_cmo.imaging.normalize import ImageRejected

from backend import config
from backend.repositories import investigation_repo as repo
from backend.services import cmo_images, cmo_runtime
from backend.services.cmo_actions import Principal

IMAGE_TYPES: dict[str, str] = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}  # detected type (from the content) -> the declared type the normaliser expects


def analyze_attachment(principal: Principal, investigation_id: UUID, attachment_id: UUID, sha256: str | None) -> dict[str, Any]:
    """Runs the CMO's vision path over ONE attached photo. Raises `HTTPException` (the choke point turns it into a leg status): 404 not found, 409 the stored file changed,
    415 not a product photo, 503 the vision service is not configured / not operator-controlled, 429 rate limited, 422 the image could not be used."""
    try:
        config.cmo_vision_endpoint_verified()  # BEFORE anything is read: nothing is sent to (or even loaded for) an endpoint the operator has not attested
        rt = cmo_runtime.build_image_runtime(need_vision=True)
    except (config.MissingConfig, cmo_runtime.CmoNotConfigured):
        raise HTTPException(status_code=503, detail={"code": "CMO_NOT_CONFIGURED"}) from None
    rows = repo.get_attachment_contents(principal.tenant_id, investigation_id, [attachment_id])  # the CMO's own tenant-scoped read, again validating tenant + investigation
    if len(rows) != 1:
        raise HTTPException(status_code=404, detail="Not found")
    row = rows[0]
    if sha256 is not None and str(row.get("sha256")) != sha256:
        raise HTTPException(status_code=409, detail={"code": "ATTACHMENT_CHANGED"})  # the table is append-only, so a mismatch is a bug: fail closed
    declared = IMAGE_TYPES.get(str(row["detected_type"]))
    if declared is None:
        raise HTTPException(status_code=415, detail={"code": "NOT_AN_IMAGE"})
    try:
        uploaded = cmo_images.upload_image(principal, rt, bytes(row["content"]), declared)  # raises ImageRejected: nothing is written
        analysis = cmo_images.analyze_image(principal, rt, UUID(uploaded["assetId"]))
    except ImageRejected as exc:
        raise HTTPException(status_code=415 if exc.code in ("NOT_AN_IMAGE", "TYPE_NOT_ALLOWED", "TYPE_MISMATCH", "ANIMATED_NOT_SUPPORTED") else 422, detail={"code": exc.code}) from None
    except cmo_images.RateLimited as exc:
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED"}, headers={"Retry-After": str(exc.retry_after_seconds)}) from None
    return {"assetId": uploaded["assetId"], "analysis": analysis, "unitsBilled": 0, "attachmentId": str(attachment_id)}
