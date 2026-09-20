"""evidence/merge.py — competitor-intelligence-agent.md §5.3. The hard rule under test:
disagreement across screenshots is never silently resolved."""

from __future__ import annotations

from uuid import uuid4

from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.evidence.merge import (
    apply_manual_entries,
    combine_snapshot_confidence,
    compute_capture_status,
    merge_extractions,
)
from competitor_intelligence.types import CaptureStatus, Confidence


def test_single_screenshot_field_is_vision_extracted() -> None:
    evidence_id = uuid4()
    result = ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))

    merged = merge_extractions([(evidence_id, result)])

    assert len(merged) == 1
    assert merged[0].value == 100000
    assert merged[0].source == Confidence.VISION_EXTRACTED
    assert merged[0].confidence == Confidence.VISION_EXTRACTED
    assert merged[0].evidence_id == evidence_id
    assert merged[0].conflict is False


def test_agreeing_screenshots_merge_without_conflict() -> None:
    e1, e2 = uuid4(), uuid4()
    r1 = ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))
    r2 = ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))

    merged = merge_extractions([(e1, r1), (e2, r2)])

    assert len(merged) == 1
    assert merged[0].conflict is False
    assert merged[0].value == 100000


def test_disagreeing_screenshots_never_pick_one() -> None:
    """§5.3 rule 3 — the hard rule."""
    e1, e2 = uuid4(), uuid4()
    r1 = ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))
    r2 = ExtractionResult(fields=(ExtractedField("listed_price_paise", 95000),))

    merged = merge_extractions([(e1, r1), (e2, r2)])

    assert len(merged) == 1
    field = merged[0]
    assert field.conflict is True
    assert field.value is None
    assert field.source is None
    assert field.confidence == Confidence.UNAVAILABLE
    assert set(field.conflict_values) == {100000, 95000}


def test_manual_entry_supersedes_vision_extracted() -> None:
    evidence_id = uuid4()
    result = ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))
    merged = merge_extractions([(evidence_id, result)])

    corrected = apply_manual_entries(merged, {"listed_price_paise": 99999})

    field = next(f for f in corrected if f.field_name == "listed_price_paise")
    assert field.value == 99999
    assert field.source == Confidence.SELLER_ENTERED
    assert field.confidence == Confidence.SELLER_ENTERED


def test_manual_entry_resolves_a_conflict() -> None:
    e1, e2 = uuid4(), uuid4()
    r1 = ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))
    r2 = ExtractionResult(fields=(ExtractedField("listed_price_paise", 95000),))
    merged = merge_extractions([(e1, r1), (e2, r2)])
    assert merged[0].conflict is True

    resolved = apply_manual_entries(merged, {"listed_price_paise": 97500})

    field = next(f for f in resolved if f.field_name == "listed_price_paise")
    assert field.conflict is False
    assert field.value == 97500
    assert field.source == Confidence.SELLER_ENTERED


def test_capture_status_complete_when_both_required_fields_resolved() -> None:
    fields = merge_extractions(
        [
            (
                uuid4(),
                ExtractionResult(
                    fields=(
                        ExtractedField("listed_price_paise", 100000),
                        ExtractedField("availability", "IN_STOCK"),
                    )
                ),
            )
        ]
    )
    assert compute_capture_status(fields) == CaptureStatus.COMPLETE


def test_capture_status_partial_when_only_one_required_field_resolved() -> None:
    fields = merge_extractions(
        [(uuid4(), ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),)))]
    )
    assert compute_capture_status(fields) == CaptureStatus.PARTIAL


def test_capture_status_pending_manual_entry_when_extraction_finds_nothing() -> None:
    assert compute_capture_status(()) == CaptureStatus.PENDING_MANUAL_ENTRY


def test_capture_status_pending_when_only_required_field_is_conflicted() -> None:
    e1, e2 = uuid4(), uuid4()
    fields = merge_extractions(
        [
            (e1, ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))),
            (e2, ExtractionResult(fields=(ExtractedField("listed_price_paise", 95000),))),
        ]
    )
    assert compute_capture_status(fields) == CaptureStatus.PENDING_MANUAL_ENTRY


def test_snapshot_confidence_rollup_is_weakest_of_the_required_fields() -> None:
    """Weakest-wins (same precedent as calc-engine's combine_confidence): one required field
    still VISION_EXTRACTED caps the rollup even though the other was manually confirmed."""
    fields = merge_extractions(
        [
            (
                uuid4(),
                ExtractionResult(
                    fields=(
                        ExtractedField("listed_price_paise", 100000),
                        ExtractedField("availability", "IN_STOCK"),
                    )
                ),
            )
        ]
    )
    fields = apply_manual_entries(fields, {"availability": "IN_STOCK"})
    assert combine_snapshot_confidence(fields) == Confidence.VISION_EXTRACTED


def test_snapshot_confidence_rollup_is_seller_entered_when_all_required_confirmed() -> None:
    fields = merge_extractions(
        [
            (
                uuid4(),
                ExtractionResult(
                    fields=(
                        ExtractedField("listed_price_paise", 100000),
                        ExtractedField("availability", "IN_STOCK"),
                    )
                ),
            )
        ]
    )
    fields = apply_manual_entries(fields, {"listed_price_paise": 99999, "availability": "IN_STOCK"})
    assert combine_snapshot_confidence(fields) == Confidence.SELLER_ENTERED


def test_snapshot_confidence_rollup_is_unavailable_when_no_required_field_present() -> None:
    assert combine_snapshot_confidence(()) == Confidence.UNAVAILABLE


def test_optional_field_failure_does_not_affect_capture_status() -> None:
    """A snapshot can be COMPLETE even if an optional field (rating) failed extraction —
    only REQUIRED_FIELDS (price, availability) gate capture_status."""
    fields = merge_extractions(
        [
            (
                uuid4(),
                ExtractionResult(
                    fields=(
                        ExtractedField("listed_price_paise", 100000),
                        ExtractedField("availability", "IN_STOCK"),
                    )
                ),
            )
        ]
    )
    assert compute_capture_status(fields) == CaptureStatus.COMPLETE
