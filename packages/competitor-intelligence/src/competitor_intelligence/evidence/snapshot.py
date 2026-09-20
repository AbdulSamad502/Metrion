"""SnapshotDraft — the evidence-model shape of §5's `competitor_snapshot`, pre-persistence.

Replaces the SnapshotDraft that used to live in the now-removed `capture/service.py` (the
retired scraping-orchestration module). `delta/compute.py` depends on this module instead —
its own logic is unchanged, only the import source moved, since a price/availability delta is
computed identically regardless of how the two snapshots' fields were populated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from competitor_intelligence.evidence.merge import (
    MergedField,
    combine_snapshot_confidence,
    compute_capture_status,
)
from competitor_intelligence.types import Availability, CaptureStatus, Confidence, Paise


@dataclass(frozen=True, slots=True)
class SnapshotDraft:
    """Every field `competitor_snapshot` needs except the ids assigned at persistence time
    (id, tenant_id, competitor_url_id, ci_capture_run_id). `title`/`description`/`bullets`
    are new under C16's carve-out — seller-submitted evidence, never scraped."""

    captured_at: datetime
    capture_status: CaptureStatus
    source_url: str
    confidence: Confidence
    research_session_id: UUID
    title: str | None = None
    description: str | None = None
    bullets: tuple[str, ...] | None = None
    seller_name: str | None = None
    observed_category: str | None = None
    category_confidence: Confidence | None = None
    listed_price_paise: Paise | None = None
    mrp_paise: Paise | None = None
    visible_discount_paise: Paise | None = None
    rating: Decimal | None = None
    rating_count: int | None = None
    availability: Availability | None = None
    variant_key: str | None = None


def build_snapshot_draft(
    *,
    fields: tuple[MergedField, ...],
    source_url: str,
    captured_at: datetime,
    research_session_id: UUID,
) -> SnapshotDraft:
    """Rolls up merged/manually-corrected fields (evidence/merge.py) into a SnapshotDraft.
    A field absent from `fields` entirely (no screenshot reported it, no manual entry either)
    simply stays at its dataclass default of None — never fabricated."""
    by_name = {f.field_name: f.value for f in fields if not f.conflict}
    availability = by_name.get("availability")

    return SnapshotDraft(
        captured_at=captured_at,
        capture_status=compute_capture_status(fields),
        source_url=source_url,
        confidence=combine_snapshot_confidence(fields),
        research_session_id=research_session_id,
        title=by_name.get("title"),
        description=by_name.get("description"),
        bullets=tuple(by_name["bullets"]) if by_name.get("bullets") else None,
        seller_name=by_name.get("seller_name"),
        observed_category=by_name.get("observed_category"),
        category_confidence=_field_confidence(fields, "observed_category"),
        listed_price_paise=by_name.get("listed_price_paise"),
        mrp_paise=by_name.get("mrp_paise"),
        visible_discount_paise=by_name.get("visible_discount_paise"),
        rating=Decimal(str(by_name["rating"])) if by_name.get("rating") is not None else None,
        rating_count=by_name.get("rating_count"),
        availability=Availability(availability) if availability else None,
        variant_key=by_name.get("variant_key"),
    )


def _field_confidence(fields: tuple[MergedField, ...], field_name: str) -> Confidence | None:
    for f in fields:
        if f.field_name == field_name:
            return f.confidence
    return None
