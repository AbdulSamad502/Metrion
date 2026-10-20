"""Turning CI observations into persistent findings (spec C45, C46).

A finding is created only from something CI already holds as evidence — a confirmed snapshot, a review
insight derived from a seller-submitted reviews screenshot, a competitor's latest screenshot — and carries
the ids of that evidence. Nothing here reads a Tavily lead (C35), computes money, or writes review text:
the payload holds derived facts and ids.

Each builder is idempotent (`dedup_key`): deriving the same observation twice yields one finding.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from competitor_intelligence.intake.events import CiEvent
from competitor_intelligence.monitor.report import Freshness, freshness_of
from competitor_intelligence.repositories import (
    ci_event_repo,
    ci_finding_repo,
    competitor_evidence_repo,
    competitor_price_event_repo,
    competitor_review_insight_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def evidence_ids_for_snapshot(tenant_id: UUID, snapshot_id: UUID) -> list[UUID]:
    snapshot = competitor_snapshot_repo.get_by_id(tenant_id, snapshot_id)
    if snapshot is None or snapshot.get("research_session_id") is None:
        return []
    return [UUID(str(r["id"])) for r in competitor_evidence_repo.get_by_research_session(tenant_id, UUID(str(snapshot["research_session_id"])))]


def _created(tenant_id: UUID, finding_id: UUID, created: bool, finding_type: str, now: datetime) -> None:
    if created:
        ci_event_repo.record(tenant_id, CiEvent.FINDING_CREATED, object_type="ci_finding", object_id=finding_id, detail={"type": finding_type}, occurred_at=now)


def record_price_finding(tenant_id: UUID, event_id: UUID, *, now: datetime | None = None) -> UUID | None:
    """A verified price or stock change that reached the seller as an alert. Evidence = the screenshot(s) of the
    snapshot it rests on. `None` when the event, its competitor's product link or its evidence is missing: a
    finding is never made without them."""
    now = now or datetime.now(timezone.utc)
    event = competitor_price_event_repo.get_event(tenant_id, event_id)
    if event is None:
        return None
    url = competitor_url_repo.get_any_by_id(tenant_id, UUID(str(event["competitor_url_id"])))
    to_snapshot = competitor_snapshot_repo.get_by_id(tenant_id, UUID(str(event["to_snapshot_id"])))
    from_snapshot = competitor_snapshot_repo.get_by_id(tenant_id, UUID(str(event["from_snapshot_id"])))
    if url is None or url.get("linked_sku") is None or to_snapshot is None:
        return None
    evidence = evidence_ids_for_snapshot(tenant_id, UUID(str(to_snapshot["id"])))
    if not evidence:
        return None
    price_changed = event["delta_paise"] != 0
    ftype = "PRICE_CHANGE" if price_changed else "AVAILABILITY_CHANGE"
    finding_id, created = ci_finding_repo.upsert(
        tenant_id,
        product_id=url["linked_sku"],
        competitor_url_id=UUID(str(url["id"])),
        finding_type=ftype,
        dedup_key=f"price-event:{event_id}",
        evidence_refs=evidence,
        confidence="DERIVED",
        freshness=freshness_of(to_snapshot["captured_at"], now=now).value,
        seller_confirmation="CONFIRMED",  # only a confirmed snapshot ever produces an event (C37)
        payload={
            "label": url.get("label"),
            "marketplace": url["marketplace"],
            "deltaPaise": event["delta_paise"],
            "deltaPct": str(event["delta_pct"]),
            "direction": event["direction"],
            "availabilityChange": event.get("availability_change"),
            "fromPricePaise": from_snapshot["listed_price_paise"] if from_snapshot else None,
            "toPricePaise": to_snapshot["listed_price_paise"],
            "evidenceDate": _iso(to_snapshot["captured_at"]),
        },
        now=now,
    )
    _created(tenant_id, finding_id, created, ftype, now)
    return finding_id


def record_review_finding(tenant_id: UUID, competitor_url_id: UUID, *, now: datetime | None = None) -> UUID | None:
    """The newest review insight for a competitor, as a finding with its sample size (N of M, C45)."""
    now = now or datetime.now(timezone.utc)
    url = competitor_url_repo.get_any_by_id(tenant_id, competitor_url_id)
    if url is None or url.get("linked_sku") is None:
        return None
    insight = competitor_review_insight_repo.latest_for_url(tenant_id, url["url"])
    if insight is None or insight["insight_state"] == "UNAVAILABLE":
        return None
    from competitor_intelligence.repositories import ci_tenant_config_repo  # noqa: PLC0415

    if int(insight["reviews_considered"] or 0) < ci_tenant_config_repo.get_review_min_sample(tenant_id):
        return None  # too few reviews read to call anything a recurring theme: the insight is kept and shown with its count, but no finding is raised (spec Q22, C45)
    evidence = [UUID(str(r["id"])) for r in competitor_evidence_repo.list_for_competitor(tenant_id, competitor_url_id, limit=5)]
    if not evidence:
        return None
    finding_id, created = ci_finding_repo.upsert(
        tenant_id,
        product_id=url["linked_sku"],
        competitor_url_id=competitor_url_id,
        finding_type="REVIEW_THEME",
        dedup_key=f"review-insight:{insight['id']}",
        evidence_refs=evidence,
        confidence=str(insight["confidence"]),
        freshness=freshness_of(insight["derived_at"], now=now).value if insight["derived_at"] else Freshness.UNAVAILABLE.value,
        payload={
            "label": url.get("label"),
            "complaintThemes": insight["complaint_themes"],
            "positiveThemes": insight["positive_themes"],
            "insightState": insight["insight_state"],
            "evidenceDate": _iso(insight["derived_at"]),
        },
        sample_size=insight["reviews_considered"],
        sample_total=None,  # a screenshot's sample is the whole of what was read: no population claim (C45)
        now=now,
    )
    _created(tenant_id, finding_id, created, "REVIEW_THEME", now)
    return finding_id


def record_freshness_finding(tenant_id: UUID, competitor_url_id: UUID, *, now: datetime | None = None, min_age_days: int = 0) -> UUID | None:
    """A competitor whose newest screenshot is stale or past the ceiling: a reminder finding that cites that screenshot.
    No evidence at all means there is nothing to remind about yet, so no finding (the monitoring report says so)."""
    now = now or datetime.now(timezone.utc)
    url = competitor_url_repo.get_any_by_id(tenant_id, competitor_url_id)
    if url is None or url.get("linked_sku") is None or url["status"] != "ACTIVE":
        return None
    latest = competitor_evidence_repo.list_for_competitor(tenant_id, competitor_url_id, limit=1)
    if not latest:
        return None
    uploaded_at = latest[0]["uploaded_at"]
    freshness = freshness_of(uploaded_at, now=now)
    if freshness is Freshness.FRESH or (now - uploaded_at).days < min_age_days:
        return None
    finding_id, created = ci_finding_repo.upsert(
        tenant_id,
        product_id=url["linked_sku"],
        competitor_url_id=competitor_url_id,
        finding_type="FRESHNESS",
        dedup_key=f"freshness:{competitor_url_id}:{uploaded_at.date().isoformat()}",
        evidence_refs=[UUID(str(latest[0]["id"]))],
        confidence="DERIVED",
        freshness=freshness.value,
        payload={"label": url.get("label"), "marketplace": url["marketplace"], "evidenceDate": _iso(uploaded_at), "requestedAction": "send a fresh screenshot"},
        now=now,
    )
    _created(tenant_id, finding_id, created, "FRESHNESS", now)
    return finding_id
