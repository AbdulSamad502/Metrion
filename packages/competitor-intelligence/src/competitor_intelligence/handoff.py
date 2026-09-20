"""CI's side of the CEO/CFO/CMO handoff interface (§6.6 ownership boundary with CMO, §6.9
WhatsApp handoff, C11/AC10). The star topology (agent-orchestration-patterns) forbids
agent-to-agent calls — CI never calls CFO/CMO/CEO directly. What CI CAN do is expose a
stable, queryable shape of its own facts so that whichever agent the CEO routes a
conversational turn to can consume them without re-deriving anything CI already knows.

This module defines that shape and builds it from CI's own already-persisted data. It does
not call calc-engine's price-positioning functions (those need a seller-supplied current
price, which CI never assumes — see `docs/specs/competitor-intelligence-agent.md` §5.2's
still-deferred CompetitorObservationSet for that boundary). A caller that has a seller price
in hand should call `calc_engine.api.compute_metric.compute_price_positioning` itself,
passing `CompetitorPrice(value_paise=..., confidence=Confidence.DERIVED, source_ref=...)`
built from this payload's `listed_price_paise`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from competitor_intelligence.delta.compute import is_stale
from competitor_intelligence.repositories import competitor_snapshot_repo, competitor_url_repo
from competitor_intelligence.types import Unavailable


@dataclass(frozen=True, slots=True)
class CiHandoffSnapshot:
    """One competitor's latest known facts, in the shape a CFO/CMO/CEO consumer needs —
    every field here is either a raw observed fact or an explicit staleness/availability
    flag. No narration, no recommendation: that is the consuming agent's job, not CI's."""

    competitor_url_id: UUID
    marketplace: str
    label: str | None
    tags: tuple[str, ...]
    snapshot_id: UUID
    captured_at: datetime
    is_stale: bool
    capture_status: str
    confidence: str
    listed_price_paise: int | None
    availability: str | None
    source_url: str


def build_ci_handoff_snapshot(
    tenant_id: UUID, competitor_url_id: UUID, *, now: datetime | None = None
) -> CiHandoffSnapshot | Unavailable:
    now = now or datetime.now(timezone.utc)

    urls = competitor_url_repo.get_by_ids(tenant_id, [competitor_url_id])
    if not urls:
        return Unavailable(reason="competitor_url not found, not ACTIVE, or not owned by this tenant")
    url_row = urls[0]

    snapshots = competitor_snapshot_repo.list_snapshots(tenant_id, competitor_url_id, limit=1)
    if not snapshots:
        return Unavailable(reason="no research has been submitted for this competitor yet")
    snapshot = snapshots[0]

    return CiHandoffSnapshot(
        competitor_url_id=competitor_url_id,
        marketplace=url_row["marketplace"],
        label=url_row.get("label"),
        tags=tuple(url_row.get("tags") or ()),
        snapshot_id=snapshot["id"],
        captured_at=snapshot["captured_at"],
        is_stale=is_stale(snapshot["captured_at"], now=now),
        capture_status=snapshot["capture_status"],
        confidence=snapshot["confidence"],
        listed_price_paise=snapshot["listed_price_paise"],
        availability=snapshot["availability"],
        source_url=snapshot["source_url"],
    )


def handoff_snapshot_to_dict(payload: CiHandoffSnapshot) -> dict[str, Any]:
    """The wire shape for the API layer — kept in this module (not the router) so the
    contract lives with the dataclass it serializes, and any future CFO/CMO consumer can
    import it directly instead of re-deriving field names from an endpoint."""
    return {
        "competitorUrlId": str(payload.competitor_url_id),
        "marketplace": payload.marketplace,
        "label": payload.label,
        "tags": list(payload.tags),
        "snapshotId": str(payload.snapshot_id),
        "capturedAt": payload.captured_at.isoformat(),
        "isStale": payload.is_stale,
        "captureStatus": payload.capture_status,
        "confidence": payload.confidence,
        "listedPricePaise": payload.listed_price_paise,
        "availability": payload.availability,
        "sourceUrl": payload.source_url,
    }
