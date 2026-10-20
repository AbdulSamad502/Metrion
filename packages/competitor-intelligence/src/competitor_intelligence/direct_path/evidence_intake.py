"""ci.evidence_intake — a seller screenshot arriving through the CEO Hub (spec §6.22, C36–C38).

```
bytes -> quality gate -> duplicate check -> store -> vision extraction (existing research session)
      -> consequential fields held PENDING + InfoRequests for the CEO to ask -> events
```

This is a fixed pipeline invoked by a fixed CEO action; no model chooses what runs. It reuses
`submit_research_session` for extraction, merge and snapshot creation, with one difference:
`require_consequential_confirmation=True`, so a vision-read price, discount or availability is
**held `PENDING` and cannot reach a Brain 1 input, delta or alert** until the seller confirms
(C37). CI never speaks to the seller: every question is an `InfoRequest` the CEO phrases (C38).

The caller must already know which tracked competitor the screenshot belongs to
(`competitor_url_id`). If it does not, the outcome is `NEEDS_COMPETITOR` and **nothing is
stored** — a screenshot of an untracked competitor is never auto-added (§6.22.3, E45); the CEO
asks the seller and calls again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from competitor_intelligence.direct_path.research_run import submit_research_session
from competitor_intelligence.evidence.extraction import VisionExtractor
from competitor_intelligence.intake.events import CiEvent
from competitor_intelligence.intake.policy import CONSEQUENTIAL_FIELDS, AskReason, FieldAction, decide_field
from competitor_intelligence.intake.quality import (
    QualityReason,
    QualityStatus,
    assess_image,
    hamming_distance,
    is_near_duplicate,
)
from competitor_intelligence.repositories import (
    ci_event_repo,
    ci_info_request_repo,
    competitor_evidence_repo,
    competitor_snapshot_field_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.types import Confidence, ExtractionStatus

CHANNEL_CEO_HUB = "CEO_HUB_ATTACHMENT"
CHANNEL_WHATSAPP = "WHATSAPP"
_EVIDENCE_FIELDS = ("listed_price_paise", "title", "rating", "rating_count", "availability", "observed_category")


class IntakeStatus(str, Enum):
    STORED = "STORED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    REJECTED_QUALITY = "REJECTED_QUALITY"
    REJECTED_NOT_A_LISTING = "REJECTED_NOT_A_LISTING"
    DUPLICATE = "DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    NEEDS_COMPETITOR = "NEEDS_COMPETITOR"
    CHANNEL_NOT_AVAILABLE = "CHANNEL_NOT_AVAILABLE"
    COMPETITOR_NOT_FOUND = "COMPETITOR_NOT_FOUND"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class ImageWriter(Protocol):
    def write(self, data: bytes) -> str: ...


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    info_request_id: UUID
    field_name: str
    reason: AskReason
    proposed_value: Any


@dataclass(frozen=True, slots=True)
class IntakeOutcome:
    status: IntakeStatus
    quality_reason: QualityReason | None = None
    evidence_id: UUID | None = None
    snapshot_id: UUID | None = None
    duplicate_of: UUID | None = None
    questions: tuple[PendingQuestion, ...] = field(default_factory=tuple)
    stored_fields: tuple[str, ...] = field(default_factory=tuple)


def _field_value(row: dict[str, Any]) -> Any:
    return row["value"]


def intake_screenshot(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    image_bytes: bytes,
    competitor_url_id: UUID | None,
    extractor: VisionExtractor,
    image_store: ImageWriter,
    max_bytes: int,
    channel: str = CHANNEL_CEO_HUB,
    permission_check: str = "PASS",
    entitlement_check: str = "PASS",
    parent_run_id: UUID | None = None,
    investigation_id: UUID | None = None,
    allow_near_duplicate: bool = False,
    now: datetime | None = None,
) -> IntakeOutcome:
    now = now or datetime.now(timezone.utc)

    if channel == CHANNEL_WHATSAPP:
        return IntakeOutcome(IntakeStatus.CHANNEL_NOT_AVAILABLE)  # placeholder (C36)
    if competitor_url_id is None:
        return IntakeOutcome(IntakeStatus.NEEDS_COMPETITOR)  # nothing stored (§6.22.3)
    if not competitor_url_repo.get_by_ids(tenant_id, [competitor_url_id]):
        return IntakeOutcome(IntakeStatus.COMPETITOR_NOT_FOUND)

    def log(event: CiEvent, *, object_id: UUID | None = None, object_type: str | None = "competitor_evidence", **detail: Any) -> None:
        ci_event_repo.record(
            tenant_id, event, actor=requested_by, agent_run_id=parent_run_id, investigation_id=investigation_id,
            object_type=object_type, object_id=object_id, detail=detail, occurred_at=now,
        )

    verdict = assess_image(image_bytes, max_bytes=max_bytes)
    if not verdict.accepted:
        log(CiEvent.EVIDENCE_REJECTED_QUALITY, object_type="competitor_url", object_id=competitor_url_id,
            reason=verdict.reason.value if verdict.reason else None)
        return IntakeOutcome(IntakeStatus.REJECTED_QUALITY, quality_reason=verdict.reason)

    existing = competitor_evidence_repo.find_by_sha(tenant_id, verdict.sha256)
    if existing is not None:
        log(CiEvent.EVIDENCE_DUPLICATE, object_id=existing["id"], kind="EXACT")
        return IntakeOutcome(IntakeStatus.DUPLICATE, duplicate_of=existing["id"])

    if verdict.perceptual_hash is not None and not allow_near_duplicate:
        for row in competitor_evidence_repo.list_perceptual_hashes(tenant_id, competitor_url_id=competitor_url_id):
            if row["perceptual_hash"] and is_near_duplicate(verdict.perceptual_hash, row["perceptual_hash"]):
                log(CiEvent.EVIDENCE_DUPLICATE, object_id=row["id"], kind="NEAR",
                    distance=hamming_distance(verdict.perceptual_hash, row["perceptual_hash"]))
                return IntakeOutcome(IntakeStatus.NEAR_DUPLICATE, duplicate_of=row["id"])

    image_ref = image_store.write(image_bytes)
    result = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=competitor_url_id,
        image_refs=[image_ref],
        manual_fields=None,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        extractor=extractor,
        now=now,
        parent_run_id=parent_run_id,
        require_consequential_confirmation=True,
    )
    if result.snapshot_id is None:
        return IntakeOutcome(IntakeStatus.EXTRACTION_FAILED)

    evidence_rows = competitor_evidence_repo.get_by_research_session(tenant_id, result.research_session_id)
    evidence_id = evidence_rows[0]["id"] if evidence_rows else None
    extraction_failed = bool(evidence_rows) and all(
        r["extraction_status"] == ExtractionStatus.EXTRACTION_FAILED.value for r in evidence_rows
    )

    fields = competitor_snapshot_field_repo.get_fields(tenant_id, result.snapshot_id)
    by_name = {r["field_name"]: r for r in fields}
    looks_like_a_listing = any(by_name.get(name) is not None and _field_value(by_name[name]) is not None for name in _EVIDENCE_FIELDS)

    if evidence_id is not None:
        competitor_evidence_repo.set_intake_metadata(
            tenant_id, evidence_id,
            content_sha256=verdict.sha256, perceptual_hash=verdict.perceptual_hash, intake_channel=channel,
            quality_status=(QualityStatus.ACCEPTED if looks_like_a_listing else QualityStatus.REJECTED_NOT_A_LISTING).value,
        )

    if extraction_failed:
        return IntakeOutcome(IntakeStatus.EXTRACTION_FAILED, evidence_id=evidence_id, snapshot_id=result.snapshot_id)

    if not looks_like_a_listing:
        log(CiEvent.EVIDENCE_REJECTED_QUALITY, object_id=evidence_id, reason="NOT_A_LISTING")
        return IntakeOutcome(IntakeStatus.REJECTED_NOT_A_LISTING, evidence_id=evidence_id, snapshot_id=result.snapshot_id)

    log(CiEvent.EVIDENCE_RECEIVED, object_id=evidence_id, channel=channel)

    questions: list[PendingQuestion] = []
    stored: list[str] = []
    for name, row in by_name.items():
        decision = decide_field(
            name,
            source=Confidence(row["source"]) if row["source"] else None,
            present=_field_value(row) is not None,
            conflict=bool(row["conflict"]),
            needed_for_request=(name == "listed_price_paise"),  # a listing screenshot with no readable price cannot be used for anything: that is always asked about
        )
        if decision.action is FieldAction.ASK_SELLER and decision.reason is not None:
            request_id = ci_info_request_repo.create(
                tenant_id, field_name=name, reason=decision.reason.value, consequential=decision.consequential,
                competitor_url_id=competitor_url_id, evidence_id=evidence_id, snapshot_id=result.snapshot_id,
                proposed_value=_field_value(row), now=now,
            )
            log(CiEvent.FIELD_CONFIRMATION_REQUESTED, object_id=request_id, object_type="ci_info_request", field=name)
            questions.append(PendingQuestion(request_id, name, decision.reason, _field_value(row)))
        elif decision.action is FieldAction.STORE:
            stored.append(name)

    if "listed_price_paise" not in by_name:  # the model returned no price at all
        request_id = ci_info_request_repo.create(
            tenant_id, field_name="listed_price_paise", reason="MISSING", consequential=True, competitor_url_id=competitor_url_id, evidence_id=evidence_id,
            snapshot_id=result.snapshot_id, proposed_value=None, now=now,
        )
        log(CiEvent.FIELD_CONFIRMATION_REQUESTED, object_id=request_id, object_type="ci_info_request", field="listed_price_paise")
        questions.append(PendingQuestion(request_id, "listed_price_paise", AskReason.MISSING, None))

    return IntakeOutcome(
        IntakeStatus.NEEDS_CONFIRMATION if questions else IntakeStatus.STORED,
        evidence_id=evidence_id,
        snapshot_id=result.snapshot_id,
        questions=tuple(questions),
        stored_fields=tuple(sorted(stored)),
    )


def settle_confirmation(
    tenant_id: UUID,
    *,
    answered_by: UUID,
    answers: dict[UUID, Any],
    declined: tuple[UUID, ...] = (),
    parent_run_id: UUID | None = None,
    investigation_id: UUID | None = None,
    now: datetime | None = None,
) -> UUID | None:
    """C38: the CEO's `ci.confirm_field`. `answers` maps `ci_info_request.id` to the value the
    seller stated or accepted; `declined` lists requests the seller refused. All requests must
    belong to one snapshot. Returns that snapshot id (or `None` if nothing was open)."""
    from competitor_intelligence.direct_path.research_run import confirm_snapshot_fields

    now = now or datetime.now(timezone.utc)
    confirmed: dict[str, Any] = {}
    declined_fields: list[str] = []
    snapshot_id: UUID | None = None

    for request_id, value in answers.items():
        current = ci_info_request_repo.get(tenant_id, request_id)
        if current is None or current["status"] != "OPEN":
            continue  # unknown, expired, or already settled: idempotent, nothing changes
        row = ci_info_request_repo.answer(tenant_id, request_id, value=value, answered_by=answered_by, now=now)
        if row is None or row["status"] != "ANSWERED":
            continue  # unknown, expired, or already settled: idempotent, changes nothing
        snapshot_id = row["snapshot_id"]
        confirmed[row["field_name"]] = value
        ci_event_repo.record(tenant_id, CiEvent.FIELD_CONFIRMED, actor=answered_by, agent_run_id=parent_run_id,
                             investigation_id=investigation_id, object_type="ci_info_request", object_id=request_id,
                             detail={"field": row["field_name"]}, occurred_at=now)
    for request_id in declined:
        current = ci_info_request_repo.get(tenant_id, request_id)
        if current is None or current["status"] != "OPEN":
            continue
        row = ci_info_request_repo.decline(tenant_id, request_id, answered_by=answered_by, now=now)
        if row is None or row["status"] != "DECLINED":
            continue
        snapshot_id = row["snapshot_id"]
        declined_fields.append(row["field_name"])
        ci_event_repo.record(tenant_id, CiEvent.FIELD_CONFIRMATION_DECLINED, actor=answered_by, agent_run_id=parent_run_id,
                             investigation_id=investigation_id, object_type="ci_info_request", object_id=request_id,
                             detail={"field": row["field_name"]}, occurred_at=now)

    if snapshot_id is None:
        return None

    # Decide from the stored state of ALL of this snapshot's questions, not just this call's:
    # the seller may answer price now and availability later.
    requests = ci_info_request_repo.list_for_snapshot(tenant_id, snapshot_id)
    consequential = [r for r in requests if r["consequential"]]
    if any(r["status"] == "OPEN" for r in consequential):
        competitor_snapshot_repo.set_price_confirmation(tenant_id, snapshot_id, "PENDING")
    elif any(r["status"] in ("DECLINED", "EXPIRED") for r in consequential):
        price_answered = any(r["field_name"] == "listed_price_paise" and r["status"] == "ANSWERED" for r in consequential)
        refused = [r["field_name"] for r in consequential if r["status"] == "DECLINED"]
        if price_answered and refused and not any(r["status"] == "EXPIRED" for r in consequential):
            # The seller confirmed the price and explicitly left some other fields out ("keep delivery, offers and stock unknown"): the price is used, and each field they
            # left out is stored as UNKNOWN (never zero, never what the model read), so nothing the seller did not confirm reaches a calculation.
            accepted = {r["field_name"]: r["answered_value"] for r in consequential if r["status"] == "ANSWERED"}
            confirm_snapshot_fields(tenant_id, snapshot_id, confirmed={**accepted, **{f: None for f in refused}}, now=now)
        else:
            confirm_snapshot_fields(tenant_id, snapshot_id, confirmed={}, declined=[r["field_name"] for r in consequential if r["status"] != "ANSWERED"], now=now)
    elif consequential:
        accepted = {r["field_name"]: r["answered_value"] for r in consequential if r["status"] == "ANSWERED"}
        confirm_snapshot_fields(tenant_id, snapshot_id, confirmed=accepted, now=now)
    return snapshot_id


__all__ = ["IntakeOutcome", "IntakeStatus", "PendingQuestion", "intake_screenshot", "settle_confirmation", "CONSEQUENTIAL_FIELDS"]
