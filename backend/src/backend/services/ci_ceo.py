"""The CEO-facing CI actions (competitor-intelligence-agent.md §6.21.3): evidence intake, field
confirmation, competitor management, monitoring and review findings.

Every function here is a fixed, registered CEO action body — `invoke(slots, ctx, leg)` — and returns
a structured payload for the CEO to compose; none of them produces seller-facing prose (C32, C38)
and none computes money (CLAUDE.md hard rule). There is no HTTP route for any of them: the seller
reaches them only through the CEO, and the dashboard that displays their results is read-only.

Tenant context comes only from the authenticated `AuthContext`; no id in a slot is trusted to
belong to the tenant — each is resolved through a tenant-scoped repository and a miss is "not
found", never data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from competitor_intelligence.direct_path import evidence_intake as intake
from competitor_intelligence.evidence.image_store import LocalDiskImageStore
from competitor_intelligence.intake.events import CiEvent
from competitor_intelligence.monitor.report import build_monitoring_report
from competitor_intelligence.repositories import (
    ci_event_repo,
    ci_info_request_repo,
    competitor_price_event_repo,
    competitor_review_insight_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.watchlist import manage

from backend.auth.context import AuthContext
from backend.ceo.contract import LegContext
from backend import config
from backend.config import ci_evidence_storage_dir, ci_max_evidence_bytes
from backend.repositories import investigation_repo


def _refused(code: str) -> dict[str, Any]:
    """An expected refusal, returned as data so the CEO can say exactly why in plain words (the choke point turns a raised exception into a generic failure)."""
    return {"status": "REFUSED", "code": code}


class CiActionError(Exception):
    """A refusal the choke point turns into an honest leg status."""

    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _tenant(ctx: AuthContext) -> UUID:
    assert ctx.tenant_id is not None
    return ctx.tenant_id


def _extractor():
    # The same composition the existing CEO Hub research action uses (api/v1/ceo_hub.py): a local,
    # operator-controlled vision model; a screenshot never goes to a hosted provider (C15). The
    # endpoint is verified NOW, before any image is read towards it (approval prerequisite R7).
    from backend.api.v1.ceo_hub import _vision_extractor
    from backend.config import LlmEndpointNotVerified, ollama_host, verified_llm_endpoint

    try:
        verified_llm_endpoint(ollama_host(), setting="OLLAMA_HOST")
    except LlmEndpointNotVerified:
        raise CiActionError("VISION_ENDPOINT_NOT_VERIFIED", 503) from None
    return _vision_extractor()


# ---- evidence intake ----------------------------------------------------------------
def evidence_intake(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    tenant_id = _tenant(ctx)
    if leg.investigation_id is None:
        return _refused("NO_INVESTIGATION")
    try:
        extractor = _extractor()  # refuses first when the vision endpoint is not attested
    except CiActionError as exc:
        return _refused(exc.code)
    rows = investigation_repo.get_attachment_contents(tenant_id, leg.investigation_id, [slots.attachment_id])
    if len(rows) != 1:
        return _refused("ATTACHMENT_NOT_FOUND")
    row = rows[0]
    if slots.sha256 is not None and str(row.get("sha256")) != slots.sha256:
        return _refused("ATTACHMENT_CHANGED")

    outcome = intake.intake_screenshot(
        tenant_id,
        requested_by=ctx.app_user_id,
        image_bytes=bytes(row["content"]),
        competitor_url_id=slots.competitor_url_id,
        extractor=extractor,
        image_store=LocalDiskImageStore(ci_evidence_storage_dir()),
        max_bytes=ci_max_evidence_bytes(),
        channel=intake.CHANNEL_CEO_HUB,
        parent_run_id=leg.turn_run_id,
        investigation_id=leg.investigation_id,
        allow_near_duplicate=slots.allow_near_duplicate,
        now=leg.now,
    )
    summary: dict[str, Any] = {}
    if outcome.snapshot_id is not None:
        from competitor_intelligence.repositories import competitor_snapshot_field_repo

        for row in competitor_snapshot_field_repo.get_fields(tenant_id, outcome.snapshot_id):
            if row["field_name"] == "rating" and row["value"] is not None:
                summary["rating"] = str(row["value"])
            if row["field_name"] == "rating_count" and row["value"] is not None:
                summary["ratingCount"] = row["value"]
    return {
        "status": outcome.status.value,
        "summary": summary,
        "qualityReason": outcome.quality_reason.value if outcome.quality_reason else None,
        "evidenceId": str(outcome.evidence_id) if outcome.evidence_id else None,
        "snapshotId": str(outcome.snapshot_id) if outcome.snapshot_id else None,
        "duplicateOf": str(outcome.duplicate_of) if outcome.duplicate_of else None,
        "storedFields": list(outcome.stored_fields),
        "questions": [
            {"infoRequestId": str(q.info_request_id), "field": q.field_name, "reason": q.reason.value, "proposedValue": q.proposed_value}
            for q in outcome.questions
        ],
    }


# ---- field confirmation -------------------------------------------------------------
def confirm_field(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    tenant_id = _tenant(ctx)
    snapshot_id = intake.settle_confirmation(
        tenant_id,
        answered_by=ctx.app_user_id,
        answers={a.info_request_id: a.value for a in slots.answers},
        declined=tuple(slots.declined),
        parent_run_id=leg.turn_run_id,
        investigation_id=leg.investigation_id,
        now=leg.now,
    )
    open_left = ci_info_request_repo.list_open(tenant_id, snapshot_id=snapshot_id) if snapshot_id else []
    snapshot = competitor_snapshot_repo.get_by_id(tenant_id, snapshot_id) if snapshot_id else None
    change = None
    if snapshot is not None and snapshot["price_confirmation"] == "CONFIRMED":
        events = competitor_price_event_repo.list_events(tenant_id, snapshot["competitor_url_id"], limit=1)
        if events and events[0]["to_snapshot_id"] == snapshot["id"] and events[0]["delta_paise"] != 0:
            change = {"deltaPct": str(events[0]["delta_pct"]), "direction": events[0]["direction"]}
    left_out = [r["field_name"] for r in ci_info_request_repo.list_for_snapshot(tenant_id, snapshot_id) if r["status"] == "DECLINED"] if snapshot_id and snapshot and snapshot["price_confirmation"] == "CONFIRMED" else []
    return {
        "snapshotId": str(snapshot_id) if snapshot_id else None,
        "priceConfirmation": snapshot["price_confirmation"] if snapshot else None,
        "leftOut": sorted(left_out),  # fields the seller chose to leave unknown on a CONFIRMED screenshot
        "verifiedChange": change,
        "stillOpen": [{"infoRequestId": str(r["id"]), "field": r["field_name"]} for r in open_left],
    }


# ---- competitor management ----------------------------------------------------------
def _manage_payload(result: manage.ManageResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "competitorUrlId": str(result.competitor_url_id) if result.competitor_url_id else None,
        "detail": result.detail,
        "limit": result.limit,
        "activeNames": list(result.active_names),
    }


def _watchlist_limit(tenant_id: UUID) -> int | None:
    from competitor_intelligence.repositories import ci_tenant_config_repo  # noqa: PLC0415

    return ci_tenant_config_repo.get_watchlist_limit(tenant_id) or config.ci_default_watchlist_limit()


def competitor_add(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    return _manage_payload(
        manage.add_competitor(
            _tenant(ctx), url=slots.url, product_id=slots.product_id, label=slots.label, added_by=ctx.app_user_id,
            max_active=None,  # the limit is enforced inside the repository's write (per seller, atomically), so chat, shortcuts and the API all meet the same rule
            agent_run_id=leg.turn_run_id, investigation_id=leg.investigation_id,
        )
    )


def competitor_remove(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    return _manage_payload(
        manage.remove_competitor(
            _tenant(ctx), slots.competitor_url_id, removed_by=ctx.app_user_id, reason=slots.reason,
            agent_run_id=leg.turn_run_id, investigation_id=leg.investigation_id,
        )
    )


def competitor_approve(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    return _manage_payload(
        manage.approve_candidate(_tenant(ctx), slots.candidate_id, decided_by=ctx.app_user_id,
                                 agent_run_id=leg.turn_run_id, investigation_id=leg.investigation_id)
    )


def competitor_reject(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    return _manage_payload(
        manage.reject_candidate_decision(_tenant(ctx), slots.candidate_id, decided_by=ctx.app_user_id,
                                         agent_run_id=leg.turn_run_id, investigation_id=leg.investigation_id)
    )


# ---- monitoring ---------------------------------------------------------------------
def monitor_competitors(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    """Re-evaluates stored evidence only (C40): no competitor, marketplace or search-provider call."""
    tenant_id = _tenant(ctx)
    now = leg.now or datetime.now(timezone.utc)
    products = [slots.product_id] if slots.product_id else competitor_url_repo.list_linked_skus(tenant_id)
    reports = [_monitor_one(tenant_id, ctx, leg, product_id, now) for product_id in products]
    return {"asOf": now.isoformat(), "products": reports, "productCount": len(reports)}


def _monitor_one(tenant_id: UUID, ctx: AuthContext, leg: LegContext, product_id: str, now: datetime) -> dict[str, Any]:
    inputs: list[dict[str, Any]] = []
    for url in competitor_url_repo.list_active_by_linked_sku(tenant_id, product_id):
        snapshot = competitor_snapshot_repo.latest_usable_snapshot(tenant_id, url["id"])  # confirmed prices only (C37)
        events = competitor_price_event_repo.list_events(tenant_id, url["id"], limit=1)
        latest = events[0] if events else None
        inputs.append(
            {
                "id": url["id"],
                "label": url["label"],
                "marketplace": url["marketplace"],
                "evidence_date": snapshot["captured_at"] if snapshot else None,
                "price_paise": snapshot["listed_price_paise"] if snapshot else None,
                "delta_pct": str(latest["delta_pct"]) if latest and snapshot and latest["to_snapshot_id"] == snapshot["id"] else None,
                "delta_direction": latest["direction"] if latest and snapshot and latest["to_snapshot_id"] == snapshot["id"] else None,
                "open_questions": len(ci_info_request_repo.list_open(tenant_id, competitor_url_id=url["id"])),
            }
        )
    report = build_monitoring_report(product_id, inputs, now=now)
    ci_event_repo.record(tenant_id, CiEvent.MONITOR_RUN, actor=ctx.app_user_id, agent_run_id=leg.turn_run_id,
                         investigation_id=leg.investigation_id, object_type="product", detail={"tracked": report.tracked_count, "fresh": report.fresh_count})
    return {
        "productId": report.product_id,
        "asOf": report.as_of.isoformat(),
        "trackedCount": report.tracked_count,
        "freshCount": report.fresh_count,
        "needsEvidenceCount": report.needs_evidence_count,
        "notes": list(report.notes),
        "competitors": [
            {
                "competitorUrlId": c.competitor_url_id,
                "label": c.label,
                "marketplace": c.marketplace,
                "evidenceDate": c.evidence_date.isoformat() if c.evidence_date else None,
                "freshness": c.freshness.value,
                "lastVerifiedPricePaise": c.last_verified_price_paise,
                "verifiedDeltaPct": c.verified_delta_pct,
                "deltaDirection": c.delta_direction,
                "openQuestions": c.open_questions,
                "requestedAction": c.requested_action,
            }
            for c in report.competitors
        ],
    }


# ---- review findings ----------------------------------------------------------------
def review_findings(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    """A read of derived review insight (C6): themes with their weights and the sample size, from
    seller-submitted reviews-tab screenshots only. Never raw review text (C14)."""
    tenant_id = _tenant(ctx)
    products = [slots.product_id] if slots.product_id else competitor_url_repo.list_linked_skus(tenant_id)
    findings: list[dict[str, Any]] = []
    tracked = 0
    for product_id in products:
        for url in competitor_url_repo.list_active_by_linked_sku(tenant_id, product_id):
            tracked += 1
            insight = competitor_review_insight_repo.latest_for_url(tenant_id, url["url"])
            if insight is None:
                continue
            findings.append(
                {
                    "productId": product_id,
                    "competitorUrlId": str(url["id"]),
                    "label": url["label"],
                    "complaintThemes": insight["complaint_themes"],
                    "positiveThemes": insight["positive_themes"],
                    "reviewsConsidered": insight["reviews_considered"],
                    "reviewInsightId": str(insight["id"]),
                    "confidence": insight["confidence"],
                    "insightState": insight["insight_state"],
                    "derivedAt": insight["derived_at"].isoformat() if insight["derived_at"] else None,
                }
            )
    return {"findings": findings, "trackedCompetitors": tracked, "competitorsWithoutReviewEvidence": tracked - len(findings)}


# ---- finding retrieval (C46) --------------------------------------------------------
def explain_finding(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    """Re-reads the exact stored finding and the evidence it cites, tenant-scoped (the id comes from the dashboard's
    Ask CEO but is never trusted: an id outside the tenant is simply not found). Returns stored facts only; the CEO
    composes the answer, and nothing is recomputed here."""
    from competitor_intelligence.repositories import ci_finding_repo, competitor_evidence_repo

    tenant_id = _tenant(ctx)
    finding = ci_finding_repo.get(tenant_id, slots.finding_id)
    if finding is None:
        return _refused("FINDING_NOT_FOUND")
    evidence = competitor_evidence_repo.get_many(tenant_id, [UUID(str(r)) for r in finding["evidence_refs"]])
    ci_event_repo.record(tenant_id, CiEvent.CEO_INVESTIGATION_LINKED, actor=ctx.app_user_id, agent_run_id=leg.turn_run_id,
                         investigation_id=leg.investigation_id, object_type="ci_finding", object_id=slots.finding_id)
    return {
        "findingId": str(finding["id"]),
        "productId": finding["product_id"],
        "findingType": finding["finding_type"],
        "competitorUrlId": str(finding["competitor_url_id"]) if finding["competitor_url_id"] else None,
        "confidence": finding["confidence"],
        "freshness": finding["freshness"],
        "sellerConfirmation": finding["seller_confirmation"],
        "sampleSize": finding["sample_size"],
        "sampleTotal": finding["sample_total"],
        "createdAt": finding["created_at"].isoformat(),
        "payload": finding["payload"],
        "evidence": [
            {"evidenceId": str(e["id"]), "uploadedAt": e["uploaded_at"].isoformat(), "channel": e["intake_channel"], "extractionStatus": e["extraction_status"]}
            for e in evidence
        ],
    }


def review_intake(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    """A reviews-tab screenshot the seller attached, read into derived review insight (C6). The vision endpoint is verified first;
    review text never leaves this process (C14, C15)."""
    from competitor_intelligence.evidence.image_store import LocalDiskImageStore as _Store
    from competitor_intelligence.evidence.ollama_client import HttpOllamaClient
    from competitor_intelligence.review_insight.ollama_extractor import OllamaReviewVisionExtractor
    from competitor_intelligence.review_insight.submit import submit_review_research

    from backend.config import LlmEndpointNotVerified, ci_review_vision_model, ollama_host, ollama_keep_alive, ollama_vision_think, ollama_vision_timeout_seconds, verified_llm_endpoint

    tenant_id = _tenant(ctx)
    if leg.investigation_id is None:
        return _refused("NO_INVESTIGATION")
    try:
        verified_llm_endpoint(ollama_host(), setting="OLLAMA_HOST")
    except LlmEndpointNotVerified:
        return _refused("VISION_ENDPOINT_NOT_VERIFIED")
    rows = investigation_repo.get_attachment_contents(tenant_id, leg.investigation_id, [slots.attachment_id])
    if len(rows) != 1:
        return _refused("ATTACHMENT_NOT_FOUND")
    data = bytes(rows[0]["content"])
    from competitor_intelligence.intake.quality import assess_image

    verdict = assess_image(data, max_bytes=ci_max_evidence_bytes())
    if not verdict.accepted:
        return {"status": "REJECTED_QUALITY", "qualityReason": verdict.reason.value if verdict.reason else None}
    store = _Store(ci_evidence_storage_dir())
    image_ref = store.write(data)
    extractor = OllamaReviewVisionExtractor(
        image_store=store,
        ollama=HttpOllamaClient(
            host=ollama_host(),
            timeout_seconds=ollama_vision_timeout_seconds(),
            keep_alive=ollama_keep_alive(),
            think=ollama_vision_think(),
        ),
        model=ci_review_vision_model(),
    )
    snapshot = competitor_snapshot_repo.latest_usable_snapshot(tenant_id, slots.competitor_url_id)
    result = submit_review_research(
        tenant_id, requested_by=ctx.app_user_id, competitor_url_id=slots.competitor_url_id, image_refs=[image_ref],
        permission_check="PASS", entitlement_check="PASS", extractor=extractor,
        snapshot_id=snapshot["id"] if snapshot else None, parent_run_id=leg.turn_run_id,
    )
    out: dict[str, Any] = {"status": result.status.value, "insightState": result.insight_state, "reviewInsightId": str(result.review_insight_id) if result.review_insight_id else None}
    try:  # read back what was stored, so the seller can check it against their screenshot (the counts are the stored ones, never retyped)
        from competitor_intelligence.repositories import ci_tenant_config_repo, competitor_review_insight_repo, competitor_url_repo  # noqa: PLC0415

        url = competitor_url_repo.get_any_by_id(tenant_id, slots.competitor_url_id)
        insight = competitor_review_insight_repo.latest_for_url(tenant_id, url["url"]) if url else None
        if insight is not None and result.review_insight_id and str(insight["id"]) == str(result.review_insight_id):
            out.update(
                reviewsConsidered=int(insight["reviews_considered"] or 0), complaintThemes=dict(insight["complaint_themes"] or {}), positiveThemes=dict(insight["positive_themes"] or {}),
                minSample=ci_tenant_config_repo.get_review_min_sample(tenant_id),
            )
    except Exception:  # noqa: BLE001 - the read-back is a convenience; the stored insight is already saved
        pass
    return out


# ---- alert preferences (C42) --------------------------------------------------------
THRESHOLD_MIN_PCT, THRESHOLD_MAX_PCT = 1, 50


def alert_settings_set(slots: Any, ctx: AuthContext, leg: LegContext) -> dict[str, Any]:
    """Saves the seller's own quiet hours and/or price-change threshold, validated here (a bad timezone, a half-set window or an out-of-range
    threshold is refused, never saved). Returns what is now in force so the CEO can echo it back (spec Q24)."""
    from datetime import time as _time
    from decimal import Decimal

    from competitor_intelligence.alerts.hardening import build_quiet_window
    from competitor_intelligence.repositories import ci_tenant_config_repo

    tenant_id = _tenant(ctx)
    quiet_start = quiet_end = None
    if slots.quiet_start is not None or slots.quiet_end is not None or slots.quiet_tz is not None:
        try:
            quiet_start = _time.fromisoformat(slots.quiet_start)
            quiet_end = _time.fromisoformat(slots.quiet_end)
            build_quiet_window(quiet_start, quiet_end, slots.quiet_tz)
        except (TypeError, ValueError):
            return _refused("INVALID_QUIET_HOURS")
    pct = None
    if slots.price_threshold_pct is not None:
        try:
            pct = Decimal(slots.price_threshold_pct)
        except Exception:  # noqa: BLE001
            return _refused("INVALID_THRESHOLD")
        if not (THRESHOLD_MIN_PCT <= pct <= THRESHOLD_MAX_PCT):
            return _refused("INVALID_THRESHOLD")
    ci_tenant_config_repo.set_alert_settings(
        tenant_id, updated_by=ctx.app_user_id, quiet_start=quiet_start, quiet_end=quiet_end, quiet_tz=slots.quiet_tz, clear_quiet=slots.clear_quiet, price_threshold_pct=pct,
    )
    now = ci_tenant_config_repo.get_alert_settings(tenant_id)
    return {
        "quietHours": None if now["quiet_hours_start"] is None else {"start": now["quiet_hours_start"].strftime("%H:%M"), "end": now["quiet_hours_end"].strftime("%H:%M"), "timezone": now["quiet_hours_tz"]},
        "priceThresholdPct": str(ci_tenant_config_repo.get_price_threshold_pct(tenant_id)),
        "cleared": bool(slots.clear_quiet),
    }
