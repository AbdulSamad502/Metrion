"""CI's own resource management — competitor URLs (reference-only, C2/C3), evidence upload,
and a summary for the main dashboard's Agent Status section. The actual research dispatch
(`ci.research_now`) goes through `/api/v1/ceo-hub/research-now` (api/v1/ceo_hub.py), not here
— this router only manages CI's own data, matching the star topology's separation between
"CI's resources" and "the CEO's routing surface."
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CI
from backend.config import ci_evidence_storage_dir
from competitor_intelligence.delta.compute import is_stale
from competitor_intelligence.delta.listing_diff import compute_listing_diff
from competitor_intelligence.digest.build_weekly_digest import build_digest
from competitor_intelligence.handoff import build_ci_handoff_snapshot, handoff_snapshot_to_dict
from competitor_intelligence.repositories import (
    ci_digest_subscription_repo,
    ci_tenant_config_repo,
    competitor_price_event_repo,
    competitor_snapshot_field_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import Marketplace, Unavailable
from sqlalchemy import text

router = APIRouter(prefix="/api/v1/ci")


class CreateCompetitorUrlRequest(BaseModel):
    url: str = Field(min_length=1)
    label: str | None = None
    linked_sku: str | None = None


def _marketplace_for(url: str) -> Marketplace:
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    if host.endswith("amazon.in"):
        return Marketplace.AMAZON
    if host.endswith("flipkart.com"):
        return Marketplace.FLIPKART
    if host.endswith("meesho.com"):
        return Marketplace.MEESHO
    raise HTTPException(status_code=400, detail=f"'{url}' is not on the trusted-domain allowlist")


@router.post("/competitor-urls")
def create_competitor_url(
    body: CreateCompetitorUrlRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, str]:
    assert ctx.tenant_id is not None  # require_auth(permission=...) guarantees an ACTIVE tenant
    marketplace = _marketplace_for(body.url)
    try:
        url_id = competitor_url_repo.create_url(
            ctx.tenant_id,
            marketplace=marketplace,
            url=body.url,
            added_by=ctx.app_user_id,
            label=body.label,
            linked_sku=body.linked_sku,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"id": str(url_id)}


@router.get("/competitor-urls")
def list_competitor_urls(ctx: AuthContext = require_auth(permission=AGENT_CI)) -> list[dict[str, object]]:
    assert ctx.tenant_id is not None
    with tenant_scope(ctx.tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT id, marketplace, url, label, linked_sku, status, tags, created_at "
                "FROM competitor_url WHERE tenant_id = :tenant_id ORDER BY created_at DESC"
            ),
            {"tenant_id": str(ctx.tenant_id)},
        ).mappings()
        return [
            {
                "id": str(r["id"]),
                "marketplace": r["marketplace"],
                "url": r["url"],
                "label": r["label"],
                "linkedSku": r["linked_sku"],
                "status": r["status"],
                "tags": list(r["tags"] or []),
                "createdAt": r["created_at"].isoformat(),
            }
            for r in rows
        ]


class UpdateCompetitorUrlRequest(BaseModel):
    tags: list[str] | None = None
    price_threshold_pct_override: Decimal | None = None
    alert_on_availability_change_override: bool | None = None
    archive: bool = False


@router.patch("/competitor-urls/{url_id}")
def update_competitor_url(
    url_id: uuid.UUID, body: UpdateCompetitorUrlRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, str]:
    """Tags and per-URL alert-threshold overrides (§5, D2/Q5) plus archiving. Each field is
    only applied when the request actually sends it — `tags`/overrides are full-replace
    when present (matching the repo functions), not merged."""
    assert ctx.tenant_id is not None
    if body.tags is not None:
        competitor_url_repo.set_tags(ctx.tenant_id, url_id, body.tags)
    if body.price_threshold_pct_override is not None or body.alert_on_availability_change_override is not None:
        competitor_url_repo.set_alert_overrides(
            ctx.tenant_id,
            url_id,
            price_threshold_pct_override=body.price_threshold_pct_override,
            alert_on_availability_change_override=body.alert_on_availability_change_override,
        )
    if body.archive:
        competitor_url_repo.archive_url(ctx.tenant_id, url_id)
    return {"id": str(url_id)}


@router.get("/competitor-urls/{url_id}/snapshots")
def get_snapshot_history(
    url_id: uuid.UUID, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> list[dict[str, object]]:
    """§6.8 snapshot history/timeline — newest first, each stamped with a staleness flag
    (OP3's >7-day rule) computed the same way alert eligibility is, not re-derived."""
    assert ctx.tenant_id is not None
    now = datetime.now(timezone.utc)
    rows = competitor_snapshot_repo.list_snapshots(ctx.tenant_id, url_id)
    return [
        {
            "id": str(r["id"]),
            "capturedAt": r["captured_at"].isoformat(),
            "isStale": is_stale(r["captured_at"], now=now),
            "captureStatus": r["capture_status"],
            "confidence": r["confidence"],
            "title": r["title"],
            "listedPricePaise": r["listed_price_paise"],
            "visibleDiscountPaise": r["visible_discount_paise"],
            "availability": r["availability"],
            "variantKey": r["variant_key"],
        }
        for r in rows
    ]


@router.get("/competitor-urls/{url_id}/price-events")
def get_price_event_history(
    url_id: uuid.UUID, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> list[dict[str, object]]:
    """§6.3 change-detection history for one competitor — newest first."""
    assert ctx.tenant_id is not None
    rows = competitor_price_event_repo.list_events(ctx.tenant_id, url_id)
    return [
        {
            "id": str(r["id"]),
            "fromSnapshotId": str(r["from_snapshot_id"]) if r["from_snapshot_id"] else None,
            "toSnapshotId": str(r["to_snapshot_id"]) if r["to_snapshot_id"] else None,
            "deltaPaise": r["delta_paise"],
            "deltaPct": str(r["delta_pct"]),
            "direction": r["direction"],
            "availabilityChange": r["availability_change"],
            "thresholdBreached": r["threshold_breached"],
            "alertEligible": r["alert_eligible"],
            "createdAt": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/competitor-urls/{url_id}/listing-diff")
def get_listing_diff(url_id: uuid.UUID, ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, object]:
    """Listing-change detection (title/description/bullets/category) between the two most
    recent snapshots — computed on read from `competitor_snapshot_field` rows, not a
    separately persisted event stream (Step 5 reuses existing plumbing rather than adding a
    new table)."""
    assert ctx.tenant_id is not None
    snapshots = competitor_snapshot_repo.list_snapshots(ctx.tenant_id, url_id, limit=2)
    if len(snapshots) < 2:
        return {"available": False, "reason": "fewer than two snapshots exist for this competitor yet"}

    current_fields = {
        f["field_name"]: f["value"] for f in competitor_snapshot_field_repo.get_fields(ctx.tenant_id, snapshots[0]["id"])
    }
    prior_fields = {
        f["field_name"]: f["value"] for f in competitor_snapshot_field_repo.get_fields(ctx.tenant_id, snapshots[1]["id"])
    }
    diff = compute_listing_diff(prior_fields, current_fields)
    if isinstance(diff, Unavailable):
        return {"available": False, "reason": diff.reason}

    return {
        "available": True,
        "priorSnapshotId": str(snapshots[1]["id"]),
        "currentSnapshotId": str(snapshots[0]["id"]),
        "changedFields": [
            {"fieldName": c.field_name, "priorValue": c.prior_value, "currentValue": c.current_value}
            for c in diff.changed_fields
        ],
    }


@router.get("/competitor-urls/{url_id}/handoff")
def get_handoff_payload(url_id: uuid.UUID, ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, object]:
    """CI's side of the CEO/CFO/CMO handoff contract (§6.6/§6.9) — a stable fact payload a
    future real CEO/CFO/CMO can consume; this endpoint doesn't call any other agent."""
    assert ctx.tenant_id is not None
    result = build_ci_handoff_snapshot(ctx.tenant_id, url_id)
    if isinstance(result, Unavailable):
        raise HTTPException(status_code=404, detail=result.reason)
    return handoff_snapshot_to_dict(result)


@router.get("/digest/preview")
def get_digest_preview(days: int = 7, ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, object]:
    """Deterministic "what changed" aggregation over the last N days — foundation for the
    weekly digest (§5 `ci_digest_subscription`); no delivery, preview only."""
    assert ctx.tenant_id is not None
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    summary = build_digest(ctx.tenant_id, since=since, until=until)
    return {
        "since": summary.since.isoformat(),
        "until": summary.until.isoformat(),
        "competitorsWithActivity": summary.competitors_with_activity,
        "entries": [
            {
                "competitorUrlId": str(e.competitor_url_id),
                "label": e.label,
                "priceIncreaseCount": e.price_increase_count,
                "priceDecreaseCount": e.price_decrease_count,
                "availabilityChangeCount": e.availability_change_count,
                "thresholdBreachedCount": e.threshold_breached_count,
            }
            for e in summary.entries
        ],
    }


class DigestSubscriptionRequest(BaseModel):
    frequency: str = Field(pattern="^(NONE|DAILY|WEEKLY)$")
    channel: str = "IN_APP"
    enabled: bool = True


@router.get("/digest/subscription")
def get_digest_subscription(ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, object]:
    assert ctx.tenant_id is not None
    sub = ci_digest_subscription_repo.get_subscription(ctx.tenant_id, ctx.app_user_id)
    if sub is None:
        config = ci_tenant_config_repo.get_config(ctx.tenant_id)
        return {
            "frequency": config["digestDefaultFrequency"],
            "channel": "IN_APP",
            "enabled": True,
            "lastSentAt": None,
            "isDefault": True,
        }
    return {
        "frequency": sub["frequency"],
        "channel": sub["channel"],
        "enabled": sub["enabled"],
        "lastSentAt": sub["last_sent_at"].isoformat() if sub["last_sent_at"] else None,
        "isDefault": False,
    }


@router.put("/digest/subscription")
def put_digest_subscription(
    body: DigestSubscriptionRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, str]:
    assert ctx.tenant_id is not None
    ci_digest_subscription_repo.upsert_subscription(
        ctx.tenant_id, ctx.app_user_id, frequency=body.frequency, channel=body.channel, enabled=body.enabled
    )
    return {"status": "OK"}


@router.post("/evidence")
async def upload_evidence(file: UploadFile, ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, str]:
    """Stores the uploaded screenshot on local disk and returns an `image_ref` the caller
    passes to `/api/v1/ceo-hub/research-now`. Local disk is a Step-4 functional stand-in for
    real object storage — swapping the storage backend later doesn't change this endpoint's
    contract (it always returns an opaque `image_ref` string)."""
    storage_dir = Path(ci_evidence_storage_dir())
    storage_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix or ".bin"
    image_ref = f"{uuid.uuid4()}{suffix}"
    destination = storage_dir / image_ref

    contents = await file.read()
    destination.write_bytes(contents)

    return {"imageRef": image_ref}


@router.get("/summary")
def ci_summary(ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, object]:
    """Basic activity summary for the main dashboard's Agent Status section — deliberately
    minimal per Step 4's scope (counts and a timestamp, not charts)."""
    assert ctx.tenant_id is not None
    with tenant_scope(ctx.tenant_id) as conn:
        tracked = conn.execute(
            text("SELECT count(*) FROM competitor_url WHERE tenant_id = :t AND status = 'ACTIVE'"),
            {"t": str(ctx.tenant_id)},
        ).scalar_one()
        last_research_at = conn.execute(
            text("SELECT max(captured_at) FROM competitor_snapshot WHERE tenant_id = :t"),
            {"t": str(ctx.tenant_id)},
        ).scalar_one()
        recent_events = conn.execute(
            text(
                "SELECT count(*) FROM competitor_price_event "
                "WHERE tenant_id = :t AND created_at > now() - interval '7 days'"
            ),
            {"t": str(ctx.tenant_id)},
        ).scalar_one()
        pending_manual_entry = conn.execute(
            text(
                "SELECT count(DISTINCT competitor_url_id) FROM competitor_snapshot "
                "WHERE tenant_id = :t AND capture_status = 'PENDING_MANUAL_ENTRY'"
            ),
            {"t": str(ctx.tenant_id)},
        ).scalar_one()
        # Stale = every competitor's most recent snapshot is older than OP3's 7-day ceiling
        # (or has no snapshot at all) — computed with the same STALE_SNAPSHOT_CEILING the
        # per-snapshot staleness badge uses, not a re-derived threshold.
        stale_competitors = conn.execute(
            text(
                """
                SELECT count(*) FROM competitor_url u
                WHERE u.tenant_id = :t AND u.status = 'ACTIVE'
                  AND NOT EXISTS (
                    SELECT 1 FROM competitor_snapshot s
                    WHERE s.tenant_id = :t AND s.competitor_url_id = u.id
                      AND s.captured_at > now() - interval '7 days'
                  )
                """
            ),
            {"t": str(ctx.tenant_id)},
        ).scalar_one()

    return {
        "trackedCompetitors": tracked,
        "lastResearchAt": last_research_at.isoformat() if last_research_at else None,
        "recentPriceEvents7d": recent_events,
        "pendingManualEntry": pending_manual_entry,
        "staleCompetitors": stale_competitors,
    }
