"""ci.review_research — the direct-path entry point for review-screenshot evidence (§6.5,
resolves Q11). Same evidence-submission shape as `direct_path/research_run.py`
(`competitor_evidence` rows, `ci_capture_run`/`agent_run` bookkeeping, `research_session_id`
grouping) — a distinct function because the extraction and persistence targets differ
(review classifications -> `competitor_review_insight`, not `competitor_snapshot`), not
because the surrounding orchestration needed reinventing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID, uuid4

from competitor_intelligence.repositories import (
    agent_run_repo,
    ci_capture_run_repo,
    competitor_evidence_repo,
    competitor_review_insight_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.review_insight.aggregate import aggregate_review_evidence
from competitor_intelligence.review_insight.extraction import ReviewExtractionFailed, ReviewVisionExtractor
from competitor_intelligence.types import ExtractionStatus, RunStatus, Trigger


@dataclass(frozen=True, slots=True)
class ReviewResearchResult:
    ci_capture_run_id: UUID
    agent_run_id: UUID
    research_session_id: UUID
    status: RunStatus
    review_insight_id: UUID | None
    insight_state: str | None


@ci_capture_run_repo.settles_open_runs
def submit_review_research(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    competitor_url_id: UUID,
    image_refs: Sequence[str],
    permission_check: str,
    entitlement_check: str,
    extractor: ReviewVisionExtractor,
    snapshot_id: UUID | None = None,
    now: datetime | None = None,
    parent_run_id: UUID | None = None,
) -> ReviewResearchResult:
    """`snapshot_id`, when given, links this review evidence to an already-submitted
    price/listing snapshot for the same competitor (`competitor_review_insight.snapshot_id`)
    and supplies E16's structured-metadata fallback (the snapshot's own `rating`/
    `rating_count`) if every screenshot here fails extraction outright. It is never required
    — a seller may submit review evidence with no linked snapshot at all."""
    now = now or datetime.now(timezone.utc)
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
            trigger_ref="ci.review_research",
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
        return ReviewResearchResult(
            ci_capture_run_id=ci_run_id,
            agent_run_id=agent_run_id,
            research_session_id=research_session_id,
            status=RunStatus.FAILED,
            review_insight_id=None,
            insight_state=None,
        )

    source_url = urls[0]["url"]

    per_evidence = []
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
        competitor_evidence_repo.update_extraction_status(
            tenant_id,
            evidence_id,
            status=ExtractionStatus.EXTRACTION_FAILED
            if isinstance(result, ReviewExtractionFailed)
            else ExtractionStatus.EXTRACTED,
        )
        per_evidence.append((evidence_id, result))

    fallback_rating: str | None = None
    fallback_rating_count: int | None = None
    if snapshot_id is not None:
        snapshot_row = competitor_snapshot_repo.get_by_id(tenant_id, snapshot_id)
        if snapshot_row is not None:
            fallback_rating = str(snapshot_row["rating"]) if snapshot_row.get("rating") is not None else None
            fallback_rating_count = snapshot_row.get("rating_count")

    draft = aggregate_review_evidence(
        per_evidence, fallback_rating=fallback_rating, fallback_rating_count=fallback_rating_count
    )
    review_insight_id = competitor_review_insight_repo.insert_insight(
        tenant_id, snapshot_id=snapshot_id, source_url=source_url, fetched_at=now, draft=draft
    )

    # Mirrors `direct_path.research_run._run_status_for`'s convention: the run itself
    # succeeded — evidence was accepted and processed — even when the resulting insight is
    # DEGRADED/UNAVAILABLE; RunStatus.FAILED stays reserved for the run never happening at
    # all (permission/entitlement/no-url, handled above).
    run_status = RunStatus.COMPLETE if draft.insight_state.value == "COMPLETE" else RunStatus.PARTIAL
    ci_capture_run_repo.finish_run(tenant_id, ci_run_id, status=run_status, finished_at=now)

    agent_run_id = agent_run_repo.insert_agent_run(
        tenant_id,
        trigger_ref="ci.review_research",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status=run_status,
        output_refs=[str(review_insight_id)],
        error_reason=None,
        started_at=now,
        finished_at=now,
        parent_run_id=parent_run_id,
    )

    return ReviewResearchResult(
        ci_capture_run_id=ci_run_id,
        agent_run_id=agent_run_id,
        research_session_id=research_session_id,
        status=run_status,
        review_insight_id=review_insight_id,
        insight_state=draft.insight_state.value,
    )
