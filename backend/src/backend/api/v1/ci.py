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
from backend.config import (
    ci_evidence_storage_dir,
    ci_max_evidence_bytes,
    ci_review_vision_model,
    ollama_host,
    ollama_keep_alive,
    ollama_vision_timeout_seconds,
)
from backend.entitlement import entitlement_check_value, resolve_ci_entitlement
from backend.uploads import read_upload_capped
from backend.services.ci_actions import load_seller_product, run_discovery, run_price_scenario
from calc_engine.api.compute_metric import MetricResult, compute_price_band
from calc_engine.formulas.price_positioning import CompetitorPrice
from calc_engine.repositories import metric_result_repo
from calc_engine.types import Confidence, Paise
from competitor_intelligence.capture.allowlist import marketplace_for_host
from competitor_intelligence.delta.compute import is_stale
from competitor_intelligence.delta.listing_diff import compute_listing_diff
from competitor_intelligence.digest.build_weekly_digest import build_digest
from competitor_intelligence.landscape.comparison import compute_comparison
from competitor_intelligence.landscape.price_band import eligible_competitor_prices
from competitor_intelligence.evidence.image_store import LocalDiskImageStore
from competitor_intelligence.evidence.ollama_client import HttpOllamaClient
from competitor_intelligence.handoff import build_ci_handoff_snapshot, handoff_snapshot_to_dict
from competitor_intelligence.alerts.layer1 import build_layer1_alerts, layer1_alert_to_dict
from competitor_intelligence.discovery.discovery_run import (
    AnalysisBudgetExceeded,
    CandidateNotAllowlisted,
    CandidateNotFound,
    accept_candidate,
    promote_to_analysis,
    reject_candidate,
)
from competitor_intelligence.discovery.relevance_scoring import AXIS_ORDER
from competitor_intelligence.repositories import (
    ci_candidate_relevance_repo,
    ci_candidate_repo,
    ci_digest_subscription_repo,
    ci_discovery_run_repo,
    ci_search_result_repo,
    ci_tenant_config_repo,
    competitor_price_event_repo,
    competitor_snapshot_field_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
    seller_product_profile_repo,
)
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.review_insight.ollama_extractor import OllamaReviewVisionExtractor
from competitor_intelligence.review_insight.submit import submit_review_research
from competitor_intelligence.seller_product.derive import derive_canonical
from competitor_intelligence.seller_product.merge import merge_seller_product
from competitor_intelligence.seller_product.types import SellerProduct
from competitor_intelligence.types import Marketplace, Unavailable
from sqlalchemy import text

router = APIRouter(prefix="/api/v1/ci")


class CreateCompetitorUrlRequest(BaseModel):
    url: str = Field(min_length=1)
    label: str | None = None
    linked_sku: str | None = None


def _marketplace_for(url: str) -> Marketplace:
    """Delegates entirely to `capture.allowlist.marketplace_for_host` (C4/D7) — this used to
    keep its own separate amazon.in/flipkart.com/meesho.com list, which is exactly how it
    stayed out of sync when short-link domains (amzn.in, fkrt.co) were added to the
    allowlist but not here. One list now, imported, not duplicated."""
    marketplace = marketplace_for_host(url)
    if marketplace is None:
        raise HTTPException(status_code=400, detail=f"'{url}' is not on the trusted-domain allowlist")
    return marketplace


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


_METRIC_CONFIG_VERSION = "CI_PRICE_SCENARIO.v1"


class PriceScenarioRequest(BaseModel):
    """Handoff.py's own docstring names this exact caller as the missing piece: "a caller
    with a seller price should call calc_engine.api.compute_metric.compute_price_positioning
    itself." `seller_price_paise` is the caller-supplied fact §5.15 requires — there is no
    live "current listed price" lookup anywhere in this engine or this codebase (verified by
    grep), so it must come from the request body, never be inferred."""

    seller_price_paise: int = Field(gt=0)
    stance: str | None = Field(
        default=None,
        pattern="^(MATCH_LOWEST|BEAT_LOWEST_BY_PCT|BEAT_LOWEST_BY_PAISE|MATCH_AVERAGE|MATCH_HIGHEST)$",
    )
    # Exactly one of these is meaningful, depending on `stance` — BEAT_LOWEST_BY_PCT needs the
    # percentage form, BEAT_LOWEST_BY_PAISE needs the paise form. Neither is required for the
    # other three stances; compute_repricing_scenario itself returns UNAVAILABLE (never an
    # exception) if a stance that needs one is given without it (§5.15 rule 3).
    stance_param_pct: Decimal | None = None
    stance_param_paise: int | None = None


def _metric_result_to_dict(result: MetricResult) -> dict[str, object]:
    return {
        "engineResultRef": str(result.id),
        "metricCode": result.metric_code,
        "valuePaise": result.value_paise,
        "isAvailable": result.is_available,
        "confidence": result.confidence,
        "calculationBasis": result.calculation_basis,
        "unavailableReason": result.unavailable_reason,
        "asOfDate": result.as_of_date.isoformat() if result.as_of_date else None,
    }


@router.post("/competitor-urls/{url_id}/price-scenario")
def compute_price_scenario(
    url_id: uuid.UUID, body: PriceScenarioRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """Wires §5.15's `compute_price_positioning`/`compute_repricing_scenario` in for real, via
    the shared `services.ci_actions.run_price_scenario` composition (also used by the CEO
    Hub's `ci.request_price_scenario` action, C20) — per `handoff.py`'s own docstring, CI
    never derives this itself; the shared function only assembles the inputs (this
    competitor's current price, DERIVED per the CI boundary) and passes through whatever the
    engine returns, unchanged. No arithmetic on money happens in this route."""
    assert ctx.tenant_id is not None
    outcome = run_price_scenario(
        ctx.tenant_id,
        url_id,
        seller_price_paise=body.seller_price_paise,
        stance=body.stance,
        stance_param_pct=body.stance_param_pct,
        stance_param_paise=body.stance_param_paise,
    )
    if outcome is None:
        raise HTTPException(status_code=404, detail="competitor_url not found, not ACTIVE, or not owned by this tenant")

    return {
        "pricePositioning": outcome.price_positioning,
        "repricingScenario": outcome.repricing_scenario,
    }


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


@router.get("/alerts")
def get_layer1_alerts(days: int = 7, ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, object]:
    """Layer 1 alerts only (competitor-intelligence-agent.md §6.17, C26) — observational
    price/availability change narration plus each one's backing `CIHandoff` finding (§5.6).
    Layer 2 (a CEO-composed fused alert with a CFO margin figure) is deferred per §1a item 8;
    nothing here computes or implies one (AC29)."""
    assert ctx.tenant_id is not None
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    alerts = build_layer1_alerts(ctx.tenant_id, since=since, now=until)
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "alerts": [layer1_alert_to_dict(a) for a in alerts],
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
    # Size-checked BEFORE anything is created on disk, so an oversized upload leaves no trace.
    contents = await read_upload_capped(file, max_bytes=ci_max_evidence_bytes(), env_var="CI_MAX_EVIDENCE_BYTES")

    storage_dir = Path(ci_evidence_storage_dir())
    storage_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix or ".bin"
    image_ref = f"{uuid.uuid4()}{suffix}"
    destination = storage_dir / image_ref
    destination.write_bytes(contents)

    return {"imageRef": image_ref}


class ReviewResearchRequest(BaseModel):
    competitor_url_id: uuid.UUID
    image_refs: list[str] = Field(min_length=1)
    snapshot_id: uuid.UUID | None = None


@router.post("/review-research")
def submit_review_research_endpoint(
    body: ReviewResearchRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """§6.5 (resolves Q11) — the direct execution path (C20) for reviews-tab screenshot
    evidence, entirely within CI's own router: no CEO Hub involvement, `parent_run_id`
    stays `NULL` on the resulting `agent_run` row, exactly like the pre-Step-4 direct path
    for listing evidence. Real vision classification via Ollama (§6.5's `LOCAL_MODEL`
    tier) — never a hosted provider (C15)."""
    assert ctx.tenant_id is not None
    entitlement_check = entitlement_check_value(resolve_ci_entitlement(ctx.tenant_id))
    extractor = OllamaReviewVisionExtractor(
        image_store=LocalDiskImageStore(ci_evidence_storage_dir()),
        ollama=HttpOllamaClient(
            host=ollama_host(), timeout_seconds=ollama_vision_timeout_seconds(), keep_alive=ollama_keep_alive()
        ),
        model=ci_review_vision_model(),
    )

    result = submit_review_research(
        ctx.tenant_id,
        requested_by=ctx.app_user_id,
        competitor_url_id=body.competitor_url_id,
        image_refs=body.image_refs,
        permission_check="PASS",  # real — require_auth(permission=AGENT_CI) already enforced this
        entitlement_check=entitlement_check,
        extractor=extractor,
        snapshot_id=body.snapshot_id,
    )

    return {
        "agentRunId": str(result.agent_run_id),
        "researchSessionId": str(result.research_session_id),
        "status": result.status.value,
        "reviewInsightId": str(result.review_insight_id) if result.review_insight_id else None,
        "insightState": result.insight_state,
    }


def _seller_product_to_dict(product: SellerProduct) -> dict[str, object]:
    return {
        "productId": product.product_id,
        "title": product.title,
        "category": product.category,
        "pricePaise": product.price_paise,
        "attributes": [{"key": k, "value": v} for k, v in product.attributes] if product.attributes else None,
        "keywords": list(product.keywords) if product.keywords else None,
        "fulfillmentType": product.fulfillment_type,
        "reviewCount": product.review_count,  # always null (C31, §5.5.2) — out of the form's scope
        "rating": product.rating,  # always null (C31, §5.5.2) — out of the form's scope
        "lastUpdated": product.last_updated.isoformat() if product.last_updated else None,
        "fieldSource": {name: source.value for name, source in product.field_source.items()},
    }


@router.get("/seller-products/{product_id}")
def get_seller_product(product_id: str, ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, object]:
    """Reads the merged `SellerProduct` (§5.5) — `derive_canonical` over `sales_line`
    (`packages/data-foundation`) merged with this tenant's `seller_product_profile` override
    row via the same precedence `merge_seller_product` implements (§5.5.1, C31). Matches
    `product_id` against `sales_line`'s `sku` OR `marketplace_item_id` on the canonical side,
    and against `seller_product_profile.product_id` on the manual side — the same identifier
    space (§5.5.2)."""
    assert ctx.tenant_id is not None
    canonical = derive_canonical(ctx.tenant_id, sku=product_id, marketplace_item_id=product_id)
    manual_row = seller_product_profile_repo.get_profile(ctx.tenant_id, product_id)
    manual_overrides = seller_product_profile_repo.profile_to_manual_overrides(manual_row)
    if canonical is None and not manual_overrides:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No SellerProduct for '{product_id}' — no matching sales_line row and no "
                "seller-product-profile entry for this tenant."
            ),
        )
    if canonical is None:
        manual_overrides = dict(manual_overrides)
        manual_overrides.setdefault("product_id", product_id)
    product = merge_seller_product(canonical, manual_overrides)
    return _seller_product_to_dict(product)


class SellerProductAttribute(BaseModel):
    key: str
    value: str


class UpdateSellerProductRequest(BaseModel):
    """The seller-product-profile manual form (§5.5.1 Source 2, C31) — exactly the five
    fields locked by C31, no more. `rating`/`review_count` are deliberately absent: they are
    out of the form's scope by decision and always stay `UNKNOWN` (§5.5.2). Every field is
    optional and full-replace on submit (`seller_product_profile_repo.upsert_profile`) — a
    field omitted (or sent as `null`) is stored as `NULL`, i.e. `UNKNOWN`, never a default."""

    category: str | None = None
    attributes: list[SellerProductAttribute] | None = None
    keywords: list[str] | None = None
    price_paise: int | None = None
    fulfillment_type: str | None = None


@router.put("/seller-products/{product_id}")
def put_seller_product(
    product_id: str, body: UpdateSellerProductRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """Writes the `SELLER_ENTERED` half of `SellerProduct` (§5.5.1 Source 2). CI itself holds
    no write path here (AC22b, T73) — this is the seller-facing profile surface C31 calls
    for, editable at any time, never write-once (AC22c). Returns the freshly re-merged
    profile so the caller sees the effect of precedence immediately, without a second GET."""
    assert ctx.tenant_id is not None
    seller_product_profile_repo.upsert_profile(
        ctx.tenant_id,
        product_id,
        category=body.category,
        attributes=[{"key": a.key, "value": a.value} for a in body.attributes] if body.attributes else None,
        keywords=body.keywords,
        price_paise=body.price_paise,
        fulfillment_type=body.fulfillment_type,
        updated_by=ctx.app_user_id,
    )
    canonical = derive_canonical(ctx.tenant_id, sku=product_id, marketplace_item_id=product_id)
    manual_row = seller_product_profile_repo.get_profile(ctx.tenant_id, product_id)
    manual_overrides = seller_product_profile_repo.profile_to_manual_overrides(manual_row)
    if canonical is None:
        manual_overrides = dict(manual_overrides)
        manual_overrides.setdefault("product_id", product_id)
    product = merge_seller_product(canonical, manual_overrides)
    return _seller_product_to_dict(product)


class StartDiscoveryRunRequest(BaseModel):
    product_id: str


def _candidate_to_dict(candidate: dict[str, object], relevance: dict[str, object] | None) -> dict[str, object]:
    row: dict[str, object] = {
        "id": str(candidate["id"]),
        "candidateUrl": candidate["candidate_url"],
        "marketplace": candidate["marketplace"],
        "origin": candidate["origin"],
        "tier": candidate["tier"],
        "identityMatch": candidate["identity_match"],
        "identityMatchBasis": candidate["identity_match_basis"],
        "sellerDecision": candidate["seller_decision"],
        "evidenceStatus": candidate["evidence_status"],
        "competitorUrlId": str(candidate["competitor_url_id"]) if candidate["competitor_url_id"] else None,
        "relevance": None,
    }
    if relevance is not None:
        row["relevance"] = {
            "band": relevance["band"],
            "totalScore": relevance["total_score"],
            "isProvisional": relevance["is_provisional"],
            "axisScores": relevance["axis_scores"],
            "axisStates": relevance["axis_states"],
            "axisRationale": relevance["axis_rationale"],
            # §6.14.3 step 3: never render a band without its full per-axis breakdown.
            "breakdownLine": ", ".join(
                f"{axis}={relevance['axis_scores'][axis]}"
                if relevance["axis_states"][axis] == "KNOWN"
                else f"{axis}={relevance['axis_states'][axis]}(0)"
                for axis in AXIS_ORDER
            ),
        }
    return row


@router.post("/discovery-runs")
def post_discovery_run(
    body: StartDiscoveryRunRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """§6.10-§6.15 direct execution path (no CEO Hub involvement, matching §6.4/C20's
    existing direct-path pattern for evidence uploads). Composition root: builds
    `MockSearchProvider` — per C22's locked build order, no named provider may be selected
    here until a provider record (§6.10.1) is approved; wiring a real one is a config
    change behind the same `SearchProvider` interface, not a rewrite of this endpoint."""
    assert ctx.tenant_id is not None
    seller_product = load_seller_product(ctx.tenant_id, body.product_id)
    if seller_product is None:
        raise HTTPException(status_code=404, detail=f"No SellerProduct for '{body.product_id}' — fill in the seller product profile first.")

    entitlement_check = entitlement_check_value(resolve_ci_entitlement(ctx.tenant_id))
    if entitlement_check != "PASS":
        raise HTTPException(status_code=402, detail="CI entitlement check failed")

    outcome = run_discovery(ctx.tenant_id, requested_by=ctx.app_user_id, seller_product=seller_product)
    return {
        "discoveryRunId": str(outcome.discovery_run_id),
        "status": outcome.status,
        "rawCandidateCount": outcome.raw_candidate_count,
        "analyzedCandidateCount": outcome.analyzed_candidate_count,
        "recommendedCandidateIds": [str(c) for c in outcome.recommended_candidate_ids],
        "uncertainCandidateIds": [str(c) for c in outcome.uncertain_candidate_ids],
        "partialReason": outcome.partial_reason,
        "failedReason": outcome.failed_reason,
    }


@router.get("/discovery-runs/{discovery_run_id}")
def get_discovery_run(
    discovery_run_id: uuid.UUID, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """§6.15's three visibility tiers, all returned together and clearly labelled — nothing
    hidden (Recommended / Other analyzed / Unanalyzed), each candidate carrying its
    identity-match/relevance/evidence-status as four separately-visible attributes (§6.14.5),
    never collapsed into one score."""
    assert ctx.tenant_id is not None
    run = ci_discovery_run_repo.get_run(ctx.tenant_id, discovery_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="discovery run not found")

    candidates = ci_candidate_repo.list_candidates_for_run(ctx.tenant_id, discovery_run_id)
    tiers: dict[str, list[dict[str, object]]] = {"RECOMMENDED": [], "ANALYZED": [], "RAW": []}
    for candidate in candidates:
        relevance = ci_candidate_relevance_repo.get_latest_relevance(ctx.tenant_id, uuid.UUID(str(candidate["id"])))
        tiers[candidate["tier"]].append(_candidate_to_dict(candidate, relevance))

    return {
        "discoveryRunId": str(run["id"]),
        "status": run["status"],
        "partialReason": run["partial_reason"],
        "failedReason": run["failed_reason"],
        "rawCandidateCount": run["raw_candidate_count"],
        "analyzedCandidateCount": run["analyzed_candidate_count"],
        "recommended": tiers["RECOMMENDED"],
        "otherAnalyzed": tiers["ANALYZED"],
        "unanalyzed": tiers["RAW"],
    }


class CandidateDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(ACCEPT|REJECT)$")


@router.post("/discovery-runs/{discovery_run_id}/candidates/{candidate_id}/decision")
def post_candidate_decision(
    discovery_run_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: CandidateDecisionRequest,
    ctx: AuthContext = require_auth(permission=AGENT_CI),
) -> dict[str, object]:
    """§6.15 rule 4 (Accept/Reject) + rule 6 (accept promotes into a tracked
    `competitor_url`, subject to the identical C4/D7 allowlist check manual intake already
    enforces). `seller_decision` is written only through this endpoint — a human action,
    never system-computed (§6.13.3)."""
    assert ctx.tenant_id is not None
    candidate = ci_candidate_repo.get_candidate(ctx.tenant_id, candidate_id)
    if candidate is None or str(candidate["discovery_run_id"]) != str(discovery_run_id):
        raise HTTPException(status_code=404, detail="candidate not found on this discovery run")

    try:
        if body.decision == "ACCEPT":
            result = accept_candidate(ctx.tenant_id, candidate_id, decided_by=ctx.app_user_id)
            return {
                "competitorUrlId": str(result.competitor_url_id),
                "runStatus": result.run_outcome.status,
            }
        run_outcome = reject_candidate(ctx.tenant_id, candidate_id, decided_by=ctx.app_user_id)
        return {"competitorUrlId": None, "runStatus": run_outcome.status}
    except CandidateNotAllowlisted as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CandidateNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/discovery-runs/{discovery_run_id}/candidates/{candidate_id}/promote")
def post_candidate_promote(
    discovery_run_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: StartDiscoveryRunRequest,
    ctx: AuthContext = require_auth(permission=AGENT_CI),
) -> dict[str, object]:
    """§6.15 rule 4's "Promote to analysis" — pulls one of the "Unanalyzed search results"
    into identity resolution + relevance scoring by explicit seller action, consuming budget
    on the same terms as any other analyzed candidate (never bypassing the cap)."""
    assert ctx.tenant_id is not None
    candidate = ci_candidate_repo.get_candidate(ctx.tenant_id, candidate_id)
    if candidate is None or str(candidate["discovery_run_id"]) != str(discovery_run_id):
        raise HTTPException(status_code=404, detail="candidate not found on this discovery run")

    seller_product = load_seller_product(ctx.tenant_id, body.product_id)
    if seller_product is None:
        raise HTTPException(status_code=404, detail=f"No SellerProduct for '{body.product_id}'")

    candidate_result = ci_search_result_repo.find_result_by_url(
        ctx.tenant_id, discovery_run_id, str(candidate["candidate_url"])
    )
    if candidate_result is None:
        raise HTTPException(
            status_code=409,
            detail="original search result for this candidate could not be reconstructed",
        )

    budget = ci_tenant_config_repo.get_discovery_budget(ctx.tenant_id)
    try:
        breakdown = promote_to_analysis(
            ctx.tenant_id,
            candidate_id,
            seller_product=seller_product,
            candidate_result=candidate_result,
            budget=budget,
        )
    except AnalysisBudgetExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    updated = ci_candidate_repo.get_candidate(ctx.tenant_id, candidate_id)
    relevance = ci_candidate_relevance_repo.get_latest_relevance(ctx.tenant_id, candidate_id) if breakdown else None
    return _candidate_to_dict(updated, relevance)


_PRICE_BAND_CONFIG_VERSION = "CI_PRICE_BAND.v1"


@router.get("/market-overview/{product_id}")
def get_market_overview(
    product_id: str, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """competitor-intelligence-agent.md §6.16.3 / deterministic-engine.md §5.15.1. CI's role
    is exhaustively: select the tenant's tracked EXACT_MATCH-or-LIKELY_VARIANT competitor
    prices for this product (`landscape.price_band.eligible_competitor_prices`) and pass
    them to the engine as `DERIVED` inputs — no percentile/IQR/fence/outlier arithmetic
    happens in this function or anywhere in `competitor_intelligence` (AC18, AC28)."""
    assert ctx.tenant_id is not None
    seller_product = load_seller_product(ctx.tenant_id, product_id)
    if seller_product is None:
        raise HTTPException(status_code=404, detail=f"No SellerProduct for '{product_id}'")

    eligible = eligible_competitor_prices(ctx.tenant_id, product_id)
    competitor_prices = [
        CompetitorPrice(value_paise=Paise(p.value_paise), confidence=Confidence.DERIVED, source_ref=str(p.snapshot_id))
        for p in eligible
    ]
    min_competitors = ci_tenant_config_repo.get_min_competitors_for_price_band(ctx.tenant_id)

    rows = compute_price_band(
        product_ref=product_id,
        category=seller_product.category,
        competitor_prices=competitor_prices,
        computed_at=datetime.now(timezone.utc),
        min_competitors=min_competitors,
    )
    for row in rows:
        metric_result_repo.save(
            ctx.tenant_id, row, grain="SKU", target_ref=product_id, period=None, config_version=_PRICE_BAND_CONFIG_VERSION
        )

    return {
        "productId": product_id,
        "trackedCompetitorCount": len(eligible),
        "minCompetitorsRequired": min_competitors,
        "rows": [_metric_result_to_dict(r) for r in rows],
    }


def _comparison_entry_to_dict(entry: object) -> dict[str, object]:
    return {"field": entry.field, "state": entry.state.value, "detail": entry.detail, "caveat": entry.caveat}  # type: ignore[attr-defined]


@router.get("/competitor-urls/{url_id}/comparison")
def get_competitor_comparison(
    url_id: uuid.UUID, product_id: str, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """competitor-intelligence-agent.md §6.19 — the four-bucket comparison, computed only
    once this competitor has at least one evidence source (§6.10.3). `product_id` selects
    which `SellerProduct` to compare against (a competitor_url has no implicit product
    linkage beyond what `linked_sku` records)."""
    assert ctx.tenant_id is not None
    seller_product = load_seller_product(ctx.tenant_id, product_id)
    if seller_product is None:
        raise HTTPException(status_code=404, detail=f"No SellerProduct for '{product_id}'")

    urls = competitor_url_repo.get_by_ids(ctx.tenant_id, [url_id])
    if not urls:
        raise HTTPException(status_code=404, detail="competitor_url not found, not ACTIVE, or not owned by this tenant")

    result = compute_comparison(ctx.tenant_id, competitor_url_id=url_id, seller_product=seller_product)
    if isinstance(result, Unavailable):
        return {"available": False, "reason": result.reason}

    return {
        "available": True,
        "competitorUrlId": str(result.competitor_url_id),
        "snapshotId": str(result.snapshot_id),
        "listingGaps": [_comparison_entry_to_dict(e) for e in result.listing_gaps],
        "productStrengths": [_comparison_entry_to_dict(e) for e in result.product_strengths],
        "productWeaknesses": [_comparison_entry_to_dict(e) for e in result.product_weaknesses],
        "differentiationOpportunities": [_comparison_entry_to_dict(e) for e in result.differentiation_opportunities],
    }


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
