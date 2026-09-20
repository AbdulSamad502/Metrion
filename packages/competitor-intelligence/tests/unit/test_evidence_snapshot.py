"""evidence/snapshot.py — build_snapshot_draft() rolls up merged fields into a SnapshotDraft."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.evidence.merge import apply_manual_entries, merge_extractions
from competitor_intelligence.evidence.snapshot import build_snapshot_draft
from competitor_intelligence.types import Availability, CaptureStatus, Confidence

NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)


def test_build_snapshot_draft_rolls_up_resolved_fields() -> None:
    fields = merge_extractions(
        [
            (
                uuid4(),
                ExtractionResult(
                    fields=(
                        ExtractedField("listed_price_paise", 100000),
                        ExtractedField("availability", "IN_STOCK"),
                        ExtractedField("rating", "4.3"),
                        ExtractedField("title", "Running Shoes — Model X"),
                    )
                ),
            )
        ]
    )
    session_id = uuid4()

    draft = build_snapshot_draft(
        fields=fields, source_url="https://amazon.in/dp/x", captured_at=NOW, research_session_id=session_id
    )

    assert draft.capture_status == CaptureStatus.COMPLETE
    assert draft.listed_price_paise == 100000
    assert draft.availability == Availability.IN_STOCK
    assert draft.rating == Decimal("4.3")
    assert draft.title == "Running Shoes — Model X"
    assert draft.research_session_id == session_id
    assert draft.confidence == Confidence.VISION_EXTRACTED


def test_build_snapshot_draft_conflicted_field_stays_none() -> None:
    e1, e2 = uuid4(), uuid4()
    fields = merge_extractions(
        [
            (e1, ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))),
            (e2, ExtractionResult(fields=(ExtractedField("listed_price_paise", 95000),))),
        ]
    )

    draft = build_snapshot_draft(
        fields=fields, source_url="https://amazon.in/dp/x", captured_at=NOW, research_session_id=uuid4()
    )

    assert draft.listed_price_paise is None
    assert draft.capture_status == CaptureStatus.PENDING_MANUAL_ENTRY


def test_build_snapshot_draft_after_manual_correction_is_complete() -> None:
    e1, e2 = uuid4(), uuid4()
    fields = merge_extractions(
        [
            (e1, ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))),
            (e2, ExtractionResult(fields=(ExtractedField("listed_price_paise", 95000),))),
        ]
    )
    fields = apply_manual_entries(fields, {"listed_price_paise": 97500, "availability": "IN_STOCK"})

    draft = build_snapshot_draft(
        fields=fields, source_url="https://amazon.in/dp/x", captured_at=NOW, research_session_id=uuid4()
    )

    assert draft.listed_price_paise == 97500
    assert draft.availability == Availability.IN_STOCK
    assert draft.capture_status == CaptureStatus.COMPLETE
    assert draft.confidence == Confidence.SELLER_ENTERED


def test_build_snapshot_draft_missing_field_stays_none_not_fabricated() -> None:
    fields = merge_extractions(
        [(uuid4(), ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),)))]
    )

    draft = build_snapshot_draft(
        fields=fields, source_url="https://amazon.in/dp/x", captured_at=NOW, research_session_id=uuid4()
    )

    assert draft.availability is None
    assert draft.rating is None
    assert draft.title is None
