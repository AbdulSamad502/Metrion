"""CMO 3.0 M9: the Product Image Quality Advisor - assigning the seller's own images to a product, reviewing the set, and reading the result. Zero AI credits; no model, not even the vision model.

Uploading reuses the existing validated, metadata-stripped, content-addressed image path (`cmo_images.upload_image`); this module only says WHICH stored image belongs to WHICH product (append-only events) and
runs the deterministic review in `slim_cmo.imagequality`. Nothing is edited, replaced, published or sent anywhere. A review is immutable and keyed by the exact set of images, roles and shot types, so reviewing
the same set again returns the stored review and writes nothing. Marketplace requirements come only from verified official rules in the rules register; otherwise they are NOT_ASSESSED."""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from PIL import Image
from slim_cmo.imagequality import review as quality
from slim_cmo.imagequality.measure import measure
from slim_cmo.imaging.normalize import ImageRejected
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.service import marketplace_rules

from backend.repositories import cmo_chat_repo
from backend.repositories import cmo_image_repo as repo
from backend.services import cmo_actions, cmo_history, cmo_images, cmo_runtime
from backend.services.cmo_actions import Principal

logger = logging.getLogger(__name__)
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
MAX_IMAGES = 12
MAX_FILES = 8
CMO_ASSIGN_IMAGES = "cmo.assign_images"
CMO_REVIEW_IMAGES = "cmo.review_images"
FILE_PATH = "/api/v1/cmo/product-images/{asset_id}/file"
NOT_A_PRODUCT = "That product is not one of yours yet. Tell me about the product in the chat first, or pick one from the list."


class ImageReviewRefused(Exception):
    def __init__(self, code: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def _mp(marketplace: str) -> str:
    m = str(marketplace or "").upper()
    if m not in MARKETPLACES:
        raise ImageReviewRefused("BAD_MARKETPLACE", "Choose Amazon, Flipkart or Meesho.")
    return m


def known_products(tenant: UUID) -> dict[str, str]:
    """sku -> product name, for the products this seller has told Metrion about (chat facts, saved listings) or already attached images to. An image can only be attached to one of these."""
    out: dict[str, str] = {}
    for sku, name in cmo_chat_repo.product_names(tenant):
        out[sku] = name
    for g in cmo_history.history(tenant, limit=1)["groups"]:
        out.setdefault(g["sku"], g["product"] or g["sku"])
    for sku in repo.skus_with_images(tenant):
        out.setdefault(sku, sku)
    return out


def _check_product(tenant: UUID, sku: str, marketplace: str) -> tuple[str, str, str]:
    mp = _mp(marketplace)
    sku = str(sku or "").strip()
    names = known_products(tenant)
    if sku not in names:
        raise ImageReviewRefused("UNKNOWN_PRODUCT", NOT_A_PRODUCT, 404)
    return sku, mp, names[sku]


def products_view(tenant: UUID) -> dict[str, Any]:
    names = known_products(tenant)
    sets: dict[str, list[dict[str, Any]]] = {}
    for s in repo.sets_with_images(tenant):
        sets.setdefault(s["sku"], []).append({"marketplace": s["marketplace"], "images": s["images"]})
    return {"products": [{"sku": k, "name": v, "sets": sets.get(k, [])} for k, v in sorted(names.items(), key=lambda kv: (kv[1].casefold(), kv[0]))],
            "marketplaces": list(MARKETPLACES), "shotTypes": [{"key": k, "label": quality.SHOT_LABEL[k]} for k in quality.SHOT_TYPES],
            "limits": {"maxImages": MAX_IMAGES, "maxFilesPerRequest": MAX_FILES}}


def _dims(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def _reader() -> Callable[[str], bytes]:
    return cmo_runtime.build_image_runtime(need_vision=False).images.read_stored


def _current(tenant: UUID, sku: str, mp: str) -> list[dict[str, Any]]:
    return repo.current_set(tenant, sku, mp)


def _image_row(r: dict[str, Any], read: Callable[[str], bytes] | None) -> dict[str, Any]:
    w = h = None
    if read is not None:
        try:
            w, h = _dims(read(r["storageUri"]))
        except Exception:  # noqa: BLE001 - a missing file shows without dimensions; it never breaks the page
            logger.exception("could not read a stored product image")
    return {"assetId": str(r["assetId"]), "role": r["role"], "shotType": r["shotType"], "position": r["position"], "widthPx": w, "heightPx": h, "sha256": r["sha256"],
            "fileUrl": FILE_PATH.format(asset_id=r["assetId"]), "assignedAt": r["assignedAt"]}


def input_hash(rows: Sequence[dict[str, Any]]) -> str:
    parts = [quality.METHOD_VERSION] + [f"{r['sha256']}|{r['role']}|{r['shotType']}|{r['position']}" for r in rows]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _apply(principal: Principal, sku: str, mp: str, changes: Sequence[dict[str, Any]]) -> int:
    """Writes the assignment events needed to reach `changes` (one per image: asset, role PRIMARY/SECONDARY/REMOVED, shot type, optional position). Identical-to-current changes write nothing. At most one
    PRIMARY: promoting one image demotes the previous main image to SECONDARY in the same transaction. Returns the number of events written."""
    cur = {r["assetId"]: r for r in _current(principal.tenant_id, sku, mp)}
    want = dict(cur)
    for c in changes:
        aid = c["asset_id"]
        base = cur.get(aid)
        pos = c.get("position") or (base["position"] if base else max([r["position"] for r in want.values()] + [0]) + 1)
        want[aid] = {"assetId": aid, "role": c["role"], "shotType": c["shot_type"], "position": min(20, max(1, int(pos)))}
    promoted = [a for a, r in want.items() if r["role"] == "PRIMARY" and (a not in cur or cur[a]["role"] != "PRIMARY")]
    if len(promoted) > 1 or sum(1 for r in want.values() if r["role"] == "PRIMARY") > 1 and not promoted:
        raise ImageReviewRefused("ONE_PRIMARY", "Only one image can be the main image.")
    if promoted:
        for a, r in want.items():
            if a not in promoted and r["role"] == "PRIMARY":
                want[a] = {**r, "role": "SECONDARY"}
    if sum(1 for r in want.values() if r["role"] != "REMOVED") > MAX_IMAGES:
        raise ImageReviewRefused("TOO_MANY_IMAGES", f"A product can have at most {MAX_IMAGES} images.")
    events = []
    for aid, r in want.items():
        b = cur.get(aid)
        if b is None and r["role"] == "REMOVED":
            continue
        if b is not None and (b["role"], b["shotType"], b["position"]) == (r["role"], r["shotType"], r["position"]):
            continue
        events.append({"asset_id": aid, "sku": sku, "marketplace": mp, "role": r["role"], "shot_type": r["shotType"], "position": r["position"]})
    if events:
        try:
            repo.add_events(principal.tenant_id, principal.user_id, events)
        except repo.UnknownAsset:
            raise ImageReviewRefused("UNKNOWN_IMAGE", "That image was not found.", 404) from None
    return len(events)


def upload(principal: Principal, rt: cmo_runtime.CmoImageRuntime, sku: str, marketplace: str, files: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """`files`: dicts {name, data, declared, role, shotType}. Each file goes through the existing upload (validation, metadata removal, hashing); a bad file is reported and the others still proceed.
    The same picture uploaded again is one image. Zero units."""
    sku, mp, _name = _check_product(principal.tenant_id, sku, marketplace)
    if not files:
        raise ImageReviewRefused("NO_FILES", "Choose at least one image.")
    if len(files) > MAX_FILES:
        raise ImageReviewRefused("TOO_MANY_FILES", f"Upload at most {MAX_FILES} images at a time.")
    results: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for f in files:
        role, shot = str(f.get("role") or "SECONDARY").upper(), str(f.get("shotType") or "OTHER").upper()
        if role not in ("PRIMARY", "SECONDARY") or shot not in quality.SHOT_TYPES:
            results.append({"name": f.get("name"), "status": "REJECTED", "code": "BAD_LABEL", "detail": "Choose main or additional, and a kind of shot from the list."})
            continue
        try:
            up = cmo_images.upload_image(principal, rt, f["data"], f["declared"])
        except ImageRejected as exc:
            results.append({"name": f.get("name"), "status": "REJECTED", "code": exc.code, "detail": exc.detail})
            continue
        changes.append({"asset_id": UUID(up["assetId"]), "role": role, "shot_type": shot})
        results.append({"name": f.get("name"), "status": "ACCEPTED", "assetId": up["assetId"], "alreadyStored": not up["created"], "widthPx": up["width"], "heightPx": up["height"]})
    written = 0
    if changes:
        # two files can carry the same picture (one asset): the last label wins, once
        dedup = {c["asset_id"]: c for c in changes}
        prim = [c for c in dedup.values() if c["role"] == "PRIMARY"]
        if len(prim) > 1:
            raise ImageReviewRefused("ONE_PRIMARY", "Only one of the uploaded images can be the main image.")
        written = _apply(principal, sku, mp, list(dedup.values()))
        if written:
            cmo_actions.record_free_run(principal, rt, CMO_ASSIGN_IMAGES, uuid4(), rt.clock())
    return {"results": results, "assignmentsWritten": written, "unitsBilled": 0}


def assign(principal: Principal, sku: str, marketplace: str, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Change the role, shot type, position of images already assigned to this product, or remove one from the set (the stored image itself is never deleted). Zero units."""
    sku, mp, _name = _check_product(principal.tenant_id, sku, marketplace)
    changes = []
    for it in items:
        role, shot = str(it.get("role") or "").upper(), str(it.get("shotType") or "").upper()
        if role not in ("PRIMARY", "SECONDARY", "REMOVED") or shot not in quality.SHOT_TYPES:
            raise ImageReviewRefused("BAD_LABEL", "Choose main, additional or remove, and a kind of shot from the list.")
        changes.append({"asset_id": UUID(str(it["assetId"])), "role": role, "shot_type": shot, "position": it.get("position")})
    written = _apply(principal, sku, mp, changes)
    if written:
        rt = cmo_runtime.build_image_runtime(need_vision=False)
        cmo_actions.record_free_run(principal, rt, CMO_ASSIGN_IMAGES, uuid4(), rt.clock())
    return {"assignmentsWritten": written, "unitsBilled": 0}


def attach_from_chat(principal: Principal, investigation_id: UUID, attachment_id: UUID, sku: str, marketplace: str, role: str, shot_type: str) -> dict[str, Any]:
    """The seller pressed 'add to this product' on a photo they attached in the CEO chat. Reuses the chat-attachment reader (tenant and conversation checked), the existing upload path and the assignment
    above. Never happens without that explicit press."""
    from backend.repositories import investigation_repo as irepo  # noqa: PLC0415
    from backend.services.cmo_attachment import IMAGE_TYPES  # noqa: PLC0415

    sku, mp, _ = _check_product(principal.tenant_id, sku, marketplace)
    rows = irepo.get_attachment_contents(principal.tenant_id, investigation_id, [attachment_id])
    if len(rows) != 1:
        raise ImageReviewRefused("NOT_FOUND", "That photo was not found in this conversation.", 404)
    declared = IMAGE_TYPES.get(str(rows[0]["detected_type"]))
    if declared is None:
        raise ImageReviewRefused("NOT_AN_IMAGE", "That attachment is not a PNG, JPEG or WebP picture.", 415)
    rt = cmo_runtime.build_image_runtime(need_vision=False)
    return upload(principal, rt, sku, mp, [{"name": str(rows[0].get("filename") or "photo"), "data": bytes(rows[0]["content"]), "declared": declared,
                                            "role": role, "shotType": shot_type}])


def _live_compliance(tenant: UUID, mp: str, report: dict[str, Any]) -> dict[str, Any]:
    reg = marketplace_rules.load()
    rt = cmo_runtime.build_image_runtime(need_vision=False)
    today: date = rt.clock().date()
    age = None
    try:
        v = PostgresGenerationStore().load_config(tenant, ("format_constraint_max_age_days",), today).get("format_constraint_max_age_days")
        age = v if isinstance(v, int) else None
    except Exception:  # noqa: BLE001 - no configured age: an official rule would be accepted only if fresh by date; none exists today
        logger.exception("could not read the rule age setting")
    imgs = [{"role": i["role"], "measures": {"long_side": max(int(i["widthPx"]), int(i["heightPx"]))}} for i in report.get("images", [])]
    return quality.compliance(reg, mp, imgs, today=today, max_age_days=age)


def review(principal: Principal, sku: str, marketplace: str) -> dict[str, Any]:
    """Reviews the product's current image set. The same set and method return the stored review (nothing is measured or written again)."""
    sku, mp, name = _check_product(principal.tenant_id, sku, marketplace)
    rows = _current(principal.tenant_id, sku, mp)
    if not rows:
        empty = quality.review([])
        return {"saved": False, "reviewId": None, "created": False, "report": empty, "compliance": _live_compliance(principal.tenant_id, mp, empty), "unitsBilled": 0,
                "message": "No images are attached to this product yet."}
    h = input_hash(rows)
    latest = repo.latest_review(principal.tenant_id, sku, mp)
    if latest and latest["inputHash"] == h:
        return {"saved": True, "reviewId": str(latest["id"]), "created": False, "report": latest["report"], "compliance": _live_compliance(principal.tenant_id, mp, latest["report"]),
                "unitsBilled": 0, "createdAt": latest["createdAt"]}
    read = _reader()
    items = []
    for r in rows:
        try:
            m = measure(read(r["storageUri"]))
        except Exception:  # noqa: BLE001 - an unreadable stored image fails the whole review: no partial report is saved
            logger.exception("could not measure a stored product image")
            raise ImageReviewRefused("IMAGE_UNREADABLE", "One of the stored images could not be read. Remove it and upload it again.", 422) from None
        items.append({"id": str(r["assetId"]), "role": r["role"], "shotType": r["shotType"], "measures": m})
    report = quality.review(items)
    report["product"] = {"sku": sku, "name": name}
    report["marketplace"] = mp
    rid, created = repo.save_review(principal.tenant_id, principal.user_id, sku=sku, marketplace=mp, method=quality.METHOD_VERSION, input_hash=h, state=report["scoreState"], score=report["score"],
                                    image_count=len(items), report=report)
    if created:
        rt = cmo_runtime.build_image_runtime(need_vision=False)
        cmo_actions.record_free_run(principal, rt, CMO_REVIEW_IMAGES, uuid4(), rt.clock())
    return {"saved": True, "reviewId": str(rid), "created": created, "report": report, "compliance": _live_compliance(principal.tenant_id, mp, report), "unitsBilled": 0}


def dashboard(tenant: UUID, sku: str, marketplace: str) -> dict[str, Any]:
    sku, mp, name = _check_product(tenant, sku, marketplace)
    rows = _current(tenant, sku, mp)
    read = _reader() if rows else None
    latest = repo.latest_review(tenant, sku, mp)
    current = bool(latest and rows and latest["inputHash"] == input_hash(rows))
    return {"product": {"sku": sku, "name": name}, "marketplace": mp, "images": [_image_row(r, read) for r in rows],
            "review": ({"reviewId": str(latest["id"]), "createdAt": latest["createdAt"], "report": latest["report"], "isCurrent": current} if latest else None),
            "compliance": _live_compliance(tenant, mp, latest["report"]) if latest else _live_compliance(tenant, mp, {"images": []}),
            "history": repo.review_history(tenant, sku, mp), "assignmentHistory": repo.events(tenant, sku, mp),
            "shotTypes": [{"key": k, "label": quality.SHOT_LABEL[k]} for k in quality.SHOT_TYPES], "limits": {"maxImages": MAX_IMAGES, "maxFilesPerRequest": MAX_FILES},
            "notes": ["Image quality is separate from marketplace compliance and from listing readiness.", "Nothing is edited, replaced or published; recommendations are advice."]}


def file_bytes(tenant: UUID, asset_id: UUID) -> tuple[bytes, str] | None:
    """The stored (metadata-stripped) picture of an image this seller attached to a product, for their own images page. Anything else is None."""
    ref = repo.servable_asset(tenant, asset_id)
    if ref is None:
        return None
    return _reader()(ref["storageUri"]), ref["contentType"]


def image_summary(tenant: UUID, sku: str, marketplace: str) -> dict[str, Any]:
    """What readiness and the CEO card need: whether a main image is attached and the latest review's headline. Missing images are 'none', never a pass."""
    rows = _current(tenant, sku, marketplace)
    latest = repo.latest_review(tenant, sku, marketplace)
    current = bool(latest and rows and latest["inputHash"] == input_hash(rows))
    return {"images": len(rows), "hasPrimary": any(r["role"] == "PRIMARY" for r in rows), "review": ({"score": latest["score"], "scoreState": latest["scoreState"], "isCurrent": current,
                                                                                                       "highFindings": sum(1 for f in latest["report"].get("findings", []) if f["severity"] == "HIGH")} if latest else None)}
