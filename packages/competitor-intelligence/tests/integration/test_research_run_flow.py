"""End-to-end ci.research_now (submit_research_session / submit_manual_correction) against a
real Postgres, using the FakeVisionExtractor from tests/conftest.py — no real vision model,
no real network access, matching the same "never touch a real marketplace" discipline the
scraping-era tests observed. Covers: single-screenshot success, multi-screenshot merge
(agreement and conflict), manual correction after a conflict, price-change detection, and
agent_run/RLS correctness.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from competitor_intelligence.direct_path.research_run import (
    submit_manual_correction,
    submit_research_session,
)
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import competitor_snapshot_field_repo, competitor_url_repo
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import CaptureStatus, Marketplace, RunStatus

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def _make_url(tenant_id: uuid.UUID, url: str = "https://amazon.in/dp/fixture-evidence"):
    added_by = uuid.uuid4()
    url_id = competitor_url_repo.create_url(tenant_id, marketplace=Marketplace.AMAZON, url=url, added_by=added_by)
    return url_id, added_by


def test_single_screenshot_complete_snapshot(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    now = datetime.now(timezone.utc)

    fake_extractor.responses["img-1"] = ExtractionResult(
        fields=(
            ExtractedField("listed_price_paise", 100000),
            ExtractedField("availability", "IN_STOCK"),
            ExtractedField("title", "Running Shoes"),
        )
    )

    result = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["img-1"],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=fake_extractor,
        now=now,
    )

    assert result.status == RunStatus.COMPLETE
    assert result.capture_status == CaptureStatus.COMPLETE
    assert result.price_event_id is None  # baseline only (E5)

    with tenant_scope(tenant_id) as conn:
        snap = conn.execute(
            text("SELECT capture_status, listed_price_paise, title, confidence FROM competitor_snapshot WHERE id = :id"),
            {"id": str(result.snapshot_id)},
        ).mappings().one()
    assert snap["capture_status"] == "COMPLETE"
    assert snap["listed_price_paise"] == 100000
    assert snap["title"] == "Running Shoes"
    assert snap["confidence"] == "VISION_EXTRACTED"

    with tenant_scope(tenant_id) as conn:
        run = conn.execute(
            text("SELECT agent_id, trigger_type, parent_run_id, status FROM agent_run WHERE id = :id"),
            {"id": str(result.agent_run_id)},
        ).mappings().one()
    assert run["agent_id"] == "CI"
    assert run["parent_run_id"] is None
    assert run["status"] == "COMPLETE"


def test_multi_screenshot_agreement_merges_cleanly(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    now = datetime.now(timezone.utc)

    for ref in ("img-a", "img-b"):
        fake_extractor.responses[ref] = ExtractionResult(
            fields=(
                ExtractedField("listed_price_paise", 100000),
                ExtractedField("availability", "IN_STOCK"),
            )
        )

    result = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["img-a", "img-b"],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=fake_extractor,
        now=now,
    )

    assert result.capture_status == CaptureStatus.COMPLETE
    fields = competitor_snapshot_field_repo.get_fields(tenant_id, result.snapshot_id)
    price_field = next(f for f in fields if f["field_name"] == "listed_price_paise")
    assert price_field["conflict"] is False


def test_multi_screenshot_conflict_then_manual_resolution(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    now = datetime.now(timezone.utc)

    fake_extractor.responses["img-a"] = ExtractionResult(
        fields=(ExtractedField("listed_price_paise", 100000), ExtractedField("availability", "IN_STOCK"))
    )
    fake_extractor.responses["img-b"] = ExtractionResult(
        fields=(ExtractedField("listed_price_paise", 95000), ExtractedField("availability", "IN_STOCK"))
    )

    result = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["img-a", "img-b"],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=fake_extractor,
        now=now,
    )

    # price conflicted -> not resolved -> capture_status can only be PARTIAL (availability
    # agreed) since price is one of the two REQUIRED_FIELDS and is unresolved.
    assert result.capture_status == CaptureStatus.PARTIAL
    with tenant_scope(tenant_id) as conn:
        snap = conn.execute(
            text("SELECT listed_price_paise FROM competitor_snapshot WHERE id = :id"),
            {"id": str(result.snapshot_id)},
        ).mappings().one()
    assert snap["listed_price_paise"] is None

    fields = competitor_snapshot_field_repo.get_fields(tenant_id, result.snapshot_id)
    price_field = next(f for f in fields if f["field_name"] == "listed_price_paise")
    assert price_field["conflict"] is True
    assert set(price_field["conflict_values"]) == {100000, 95000}

    # Manual resolution (§5.3 rule 4 / T10b)
    correction = submit_manual_correction(
        tenant_id, result.snapshot_id, manual_fields={"listed_price_paise": 97500}
    )
    assert correction.capture_status == CaptureStatus.COMPLETE
    with tenant_scope(tenant_id) as conn:
        snap = conn.execute(
            text("SELECT listed_price_paise, capture_status, confidence FROM competitor_snapshot WHERE id = :id"),
            {"id": str(result.snapshot_id)},
        ).mappings().one()
    assert snap["listed_price_paise"] == 97500
    assert snap["capture_status"] == "COMPLETE"
    # Weakest-wins rollup (evidence/merge.py combine_snapshot_confidence): availability was
    # never corrected and is still VISION_EXTRACTED, so the snapshot-level confidence stays
    # there even though price is now SELLER_ENTERED — only per-field confidence (checked
    # below) reflects the correction directly.
    assert snap["confidence"] == "VISION_EXTRACTED"

    fields = competitor_snapshot_field_repo.get_fields(tenant_id, result.snapshot_id)
    corrected_price_field = next(f for f in fields if f["field_name"] == "listed_price_paise")
    assert corrected_price_field["source"] == "SELLER_ENTERED"
    assert corrected_price_field["confidence"] == "SELLER_ENTERED"


def test_second_session_above_threshold_creates_price_event(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    t0 = datetime.now(timezone.utc)

    fake_extractor.responses["img-1"] = ExtractionResult(
        fields=(ExtractedField("listed_price_paise", 100000), ExtractedField("availability", "IN_STOCK"))
    )
    first = submit_research_session(
        tenant_id, requested_by=requested_by, competitor_url_id=url_id, image_refs=["img-1"],
        manual_fields=None, permission_check="PASS", entitlement_check="PASS", extractor=fake_extractor, now=t0,
    )
    assert first.price_event_id is None

    t1 = t0 + timedelta(hours=6)
    fake_extractor.responses["img-2"] = ExtractionResult(
        fields=(ExtractedField("listed_price_paise", 80000), ExtractedField("availability", "IN_STOCK"))
    )
    second = submit_research_session(
        tenant_id, requested_by=requested_by, competitor_url_id=url_id, image_refs=["img-2"],
        manual_fields=None, permission_check="PASS", entitlement_check="PASS", extractor=fake_extractor, now=t1,
    )

    assert second.price_event_id is not None
    with tenant_scope(tenant_id) as conn:
        event = conn.execute(
            text("SELECT delta_pct, direction, threshold_breached, to_snapshot_id FROM competitor_price_event WHERE id = :id"),
            {"id": str(second.price_event_id)},
        ).mappings().one()
    assert event["direction"] == "DECREASE"
    assert event["threshold_breached"] is True
    assert event["to_snapshot_id"] == second.snapshot_id


def test_denied_permission_fails_without_writing_a_snapshot(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)

    result = submit_research_session(
        tenant_id, requested_by=requested_by, competitor_url_id=url_id, image_refs=["img-1"],
        manual_fields=None, permission_check="DENIED", entitlement_check="PASS",
        extractor=fake_extractor, now=datetime.now(timezone.utc),
    )

    assert result.status == RunStatus.FAILED
    assert result.snapshot_id is None
    assert fake_extractor.calls == []


def test_extraction_failure_on_every_screenshot_is_pending_manual_entry(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    now = datetime.now(timezone.utc)
    # no fixture registered for "img-bad" -> FakeVisionExtractor returns ExtractionFailed

    result = submit_research_session(
        tenant_id, requested_by=requested_by, competitor_url_id=url_id, image_refs=["img-bad"],
        manual_fields=None, permission_check="PASS", entitlement_check="PASS",
        extractor=fake_extractor, now=now,
    )

    assert result.capture_status == CaptureStatus.PENDING_MANUAL_ENTRY
    assert result.status == RunStatus.PARTIAL  # the run itself succeeded — seller has follow-up to do


def test_manual_fields_at_submission_time_fill_extraction_gaps(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    now = datetime.now(timezone.utc)

    fake_extractor.responses["img-1"] = ExtractionResult(fields=(ExtractedField("listed_price_paise", 100000),))

    result = submit_research_session(
        tenant_id, requested_by=requested_by, competitor_url_id=url_id, image_refs=["img-1"],
        manual_fields={"availability": "IN_STOCK"}, permission_check="PASS", entitlement_check="PASS",
        extractor=fake_extractor, now=now,
    )

    assert result.capture_status == CaptureStatus.COMPLETE
    with tenant_scope(tenant_id) as conn:
        snap = conn.execute(
            text("SELECT availability FROM competitor_snapshot WHERE id = :id"), {"id": str(result.snapshot_id)}
        ).mappings().one()
    assert snap["availability"] == "IN_STOCK"
