"""ci.research_now — the direct/fast-path entry point for the evidence model (C20, §5, §6.1,
§6.2, §6.4). Replaces the retired `direct_path/capture_run.py` (the scraping-orchestration
entry point) — same run-bookkeeping/`agent_run`-logging shape, new inputs.

Per spec §1a, only the `EVIDENCE_UPLOAD` trigger is wired in this pass. Per orchestration
spec C7, a direct-path invocation is its own top-level `agent_run` row (`parent_run_id=NULL`)
— wiring a real parent (the CEO Hub) is Step 4's job, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from competitor_intelligence.delta.compute import compute_price_delta, should_emit_price_event
from competitor_intelligence.evidence.extraction import ExtractionFailed, ExtractionResult, VisionExtractor
from competitor_intelligence.evidence.merge import MergedField, apply_manual_entries, merge_extractions
from competitor_intelligence.evidence.snapshot import SnapshotDraft, build_snapshot_draft
from competitor_intelligence.listing_insight.derive import derive_listing_insight
from competitor_intelligence.repositories import (
    agent_run_repo,
    ci_capture_run_repo,
    ci_tenant_config_repo,
    competitor_evidence_repo,
    competitor_listing_insight_repo,
    competitor_price_event_repo,
    competitor_snapshot_field_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.types import (
    Availability,
    CaptureStatus,
    Confidence,
    ExtractionStatus,
    RunStatus,
    Trigger,
    Unavailable,
)


@dataclass(frozen=True, slots=True)
class ResearchSessionResult:
    ci_capture_run_id: UUID
    agent_run_id: UUID
    research_session_id: UUID
    status: RunStatus
    snapshot_id: UUID | None
    capture_status: CaptureStatus | None
    price_event_id: UUID | None


def _run_status_for(capture_status: CaptureStatus) -> RunStatus:
    if capture_status == CaptureStatus.COMPLETE:
        return RunStatus.COMPLETE
    # PARTIAL and PENDING_MANUAL_ENTRY both mean "the run itself succeeded — evidence was
    # accepted and processed." RunStatus.FAILED is reserved for the run never happening at
    # all (permission/entitlement denial, or no ACTIVE url resolved) — the seller having
    # follow-up fields to fill in is not a failure.
    return RunStatus.PARTIAL


def submit_research_session(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    competitor_url_id: UUID,
    image_refs: Sequence[str],
    manual_fields: Mapping[str, Any] | None,
    permission_check: str,
    entitlement_check: str,
    extractor: VisionExtractor,
    now: datetime | None = None,
    parent_run_id: UUID | None = None,
) -> ResearchSessionResult:
    """`parent_run_id` is set only when this call is dispatched by the CEO Hub (Step 4's
    dummy CEO) — `None` for a pure direct-path invocation, matching `agent_run_repo.
    insert_agent_run`'s contract."""
    now = now or datetime.now(timezone.utc)
    manual_fields = manual_fields or {}
    research_session_id = uuid4()

    urls = competitor_url_repo.get_by_ids(tenant_id, [competitor_url_id])
    ci_run_id = ci_capture_run_repo.create_run(
        tenant_id,
        trigger=Trigger.EVIDENCE_UPLOAD,
        requested_by=requested_by,
        url_ids=[competitor_url_id],
        started_at=now,
        research_session_id=research_session_id,
    )

    if permission_check != "PASS" or entitlement_check != "PASS" or not urls:
        reason = (
            "permission or entitlement check did not pass"
            if permission_check != "PASS" or entitlement_check != "PASS"
            else "competitor_url not found, not ACTIVE, or not owned by this tenant"
        )
        ci_capture_run_repo.finish_run(tenant_id, ci_run_id, status=RunStatus.FAILED, finished_at=now)
        agent_run_id = agent_run_repo.insert_agent_run(
            tenant_id,
            trigger_ref="ci.research_now",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status=RunStatus.FAILED,
            output_refs=None,
            error_reason=reason,
            started_at=now,
            finished_at=now,
            parent_run_id=parent_run_id,
        )
        return ResearchSessionResult(
            ci_capture_run_id=ci_run_id,
            agent_run_id=agent_run_id,
            research_session_id=research_session_id,
            status=RunStatus.FAILED,
            snapshot_id=None,
            capture_status=None,
            price_event_id=None,
        )

    source_url = urls[0]["url"]

    per_evidence: list[tuple[UUID, ExtractionResult]] = []
    for image_ref in image_refs:
        evidence_id = competitor_evidence_repo.insert_evidence(
            tenant_id,
            competitor_url_id=competitor_url_id,
            research_session_id=research_session_id,
            image_ref=image_ref,
            uploaded_by=requested_by,
            uploaded_at=now,
        )
        result = extractor.extract(image_ref)
        if isinstance(result, ExtractionFailed):
            competitor_evidence_repo.update_extraction_status(
                tenant_id, evidence_id, status=ExtractionStatus.EXTRACTION_FAILED
            )
        else:
            competitor_evidence_repo.update_extraction_status(
                tenant_id, evidence_id, status=ExtractionStatus.EXTRACTED
            )
            per_evidence.append((evidence_id, result))

    merged = merge_extractions(per_evidence)
    merged = apply_manual_entries(merged, manual_fields)

    draft = build_snapshot_draft(
        fields=merged, source_url=source_url, captured_at=now, research_session_id=research_session_id
    )
    snapshot_id = competitor_snapshot_repo.insert_snapshot(
        tenant_id, competitor_url_id=competitor_url_id, ci_capture_run_id=ci_run_id, draft=draft
    )
    competitor_snapshot_field_repo.replace_fields(tenant_id, snapshot_id, merged)
    _derive_and_persist_listing_insight(tenant_id, snapshot_id=snapshot_id, draft=draft)

    price_event_id = _detect_and_record_price_change(
        tenant_id,
        competitor_url_id=competitor_url_id,
        ci_run_id=ci_run_id,
        current_snapshot_id=snapshot_id,
        draft=draft,
        now=now,
        url_row=urls[0],
    )

    run_status = _run_status_for(draft.capture_status)
    ci_capture_run_repo.finish_run(tenant_id, ci_run_id, status=run_status, finished_at=now)

    agent_run_id = agent_run_repo.insert_agent_run(
        tenant_id,
        trigger_ref="ci.research_now",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status=run_status,
        output_refs=[str(snapshot_id)],
        error_reason=None,
        started_at=now,
        finished_at=now,
        parent_run_id=parent_run_id,
    )

    return ResearchSessionResult(
        ci_capture_run_id=ci_run_id,
        agent_run_id=agent_run_id,
        research_session_id=research_session_id,
        status=run_status,
        snapshot_id=snapshot_id,
        capture_status=draft.capture_status,
        price_event_id=price_event_id,
    )


def _detect_and_record_price_change(
    tenant_id: UUID,
    *,
    competitor_url_id: UUID,
    ci_run_id: UUID,
    current_snapshot_id: UUID,
    draft: SnapshotDraft,
    now: datetime,
    url_row: Mapping[str, Any] | None = None,
) -> UUID | None:
    prior_row = competitor_snapshot_repo.latest_comparable_snapshot(
        tenant_id,
        competitor_url_id=competitor_url_id,
        variant_key=draft.variant_key,
        exclude_snapshot_id=current_snapshot_id,
    )
    if prior_row is None:
        return None  # first-ever snapshot — baseline only (E5)

    prior_draft = _row_to_draft_fields(prior_row)

    # Per-URL override (§5, D2/Q5) beats the tenant-wide default; `url_row` is None only
    # when a caller (e.g. a manual correction) didn't have it on hand, in which case it's
    # re-fetched here rather than silently skipping override resolution.
    if url_row is None:
        rows = competitor_url_repo.get_by_ids(tenant_id, [competitor_url_id])
        url_row = rows[0] if rows else {}
    price_threshold_pct = url_row.get("price_threshold_pct_override") or ci_tenant_config_repo.get_price_threshold_pct(
        tenant_id
    )
    availability_override = url_row.get("alert_on_availability_change_override")
    alert_on_availability_change = (
        availability_override
        if availability_override is not None
        else ci_tenant_config_repo.get_alert_on_availability_change(tenant_id)
    )

    delta = compute_price_delta(
        prior=prior_draft,
        current=draft,
        price_threshold_pct=price_threshold_pct,
        now=now,
        alert_on_availability_change=alert_on_availability_change,
    )
    if isinstance(delta, Unavailable) or not should_emit_price_event(delta):
        return None

    return competitor_price_event_repo.insert_event(
        tenant_id,
        competitor_url_id=competitor_url_id,
        from_snapshot_id=prior_row["id"],
        to_snapshot_id=current_snapshot_id,
        ci_capture_run_id=ci_run_id,
        delta=delta,
    )


def _derive_and_persist_listing_insight(tenant_id: UUID, *, snapshot_id: UUID, draft: SnapshotDraft) -> None:
    """§6.6 — only attempted when this research session actually submitted listing-copy
    evidence (C16 carve-out); a price/availability-only submission has nothing to derive
    and produces no `competitor_listing_insight` row at all (not an UNAVAILABLE one — there
    was no attempt, which is a different thing from an attempt that found nothing)."""
    if draft.title is None and draft.description is None and draft.bullets is None:
        return

    other_theme_sets: list[frozenset[str]] = []
    if draft.observed_category:
        rows = competitor_snapshot_repo.get_by_id(tenant_id, snapshot_id)
        competitor_url_id = rows["competitor_url_id"] if rows else None
        if competitor_url_id is not None:
            other_theme_sets = competitor_listing_insight_repo.keyword_themes_for_category(
                tenant_id, observed_category=draft.observed_category, exclude_competitor_url_id=competitor_url_id
            )

    insight_draft = derive_listing_insight(
        title=draft.title,
        description=draft.description,
        bullets=draft.bullets,
        other_competitor_theme_sets=other_theme_sets,
    )
    competitor_listing_insight_repo.insert_insight(
        tenant_id, snapshot_id=snapshot_id, source_url=draft.source_url, fetched_at=draft.captured_at, draft=insight_draft
    )


@dataclass(frozen=True, slots=True)
class ManualCorrectionResult:
    snapshot_id: UUID
    capture_status: CaptureStatus
    price_event_id: UUID | None


def submit_manual_correction(
    tenant_id: UUID, snapshot_id: UUID, *, manual_fields: Mapping[str, Any], now: datetime | None = None
) -> ManualCorrectionResult:
    """§5.3 rule 4 / T10b — the seller fills in a field extraction missed or that conflicted,
    after the initial research session already produced a snapshot. Re-merges, recomputes
    capture_status/confidence, updates the snapshot row and its field rows in place (no new
    snapshot row — §5.3's "never transitions backward silently" note is about field values,
    not about spawning a duplicate snapshot for the same research session), and re-runs price-
    change detection since a field that was `PENDING_MANUAL_ENTRY` may now make this snapshot
    comparable for the first time.
    """
    now = now or datetime.now(timezone.utc)

    existing_row = competitor_snapshot_repo.get_by_id(tenant_id, snapshot_id)
    if existing_row is None:
        raise ValueError(f"no snapshot {snapshot_id} for this tenant")

    existing_fields = competitor_snapshot_field_repo.get_fields_as_merged(tenant_id, snapshot_id)
    corrected_fields = apply_manual_entries(existing_fields, manual_fields)

    draft = build_snapshot_draft(
        fields=corrected_fields,
        source_url=existing_row["source_url"],
        captured_at=existing_row["captured_at"],
        research_session_id=existing_row["research_session_id"],
    )

    competitor_snapshot_repo.apply_correction(tenant_id, snapshot_id, draft=draft)
    competitor_snapshot_field_repo.replace_fields(tenant_id, snapshot_id, corrected_fields)

    price_event_id = _detect_and_record_price_change(
        tenant_id,
        competitor_url_id=existing_row["competitor_url_id"],
        # A correction isn't a new capture run — competitor_price_event.ci_capture_run_id is
        # NOT NULL, so this reuses the snapshot's own originating run for provenance (MN14),
        # rather than fabricating a second run for what is still, conceptually, the same
        # research session's outcome.
        ci_run_id=existing_row["ci_capture_run_id"],
        current_snapshot_id=snapshot_id,
        draft=draft,
        now=now,
    )

    return ManualCorrectionResult(
        snapshot_id=snapshot_id, capture_status=draft.capture_status, price_event_id=price_event_id
    )


def _row_to_draft_fields(row: dict) -> SnapshotDraft:
    """Adapts a DB row from latest_comparable_snapshot() into the subset of SnapshotDraft
    fields compute_price_delta() actually reads."""
    return SnapshotDraft(
        captured_at=row["captured_at"],
        capture_status=CaptureStatus(row["capture_status"]),
        source_url="",
        confidence=Confidence.VISION_EXTRACTED,
        research_session_id=uuid4(),
        listed_price_paise=row["listed_price_paise"],
        visible_discount_paise=row["visible_discount_paise"],
        availability=Availability(row["availability"]) if row["availability"] else None,
    )
