"""Listing-insight derivation as wired into submit_research_session — verifies it only
fires when listing-copy evidence was actually submitted, and persists via the real repo
against a live Postgres."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from competitor_intelligence.direct_path.research_run import submit_research_session
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import competitor_listing_insight_repo, competitor_url_repo
from competitor_intelligence.types import Marketplace

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def _make_url(tenant_id: uuid.UUID, url: str = "https://amazon.in/dp/fixture-listing-insight"):
    added_by = uuid.uuid4()
    url_id = competitor_url_repo.create_url(tenant_id, marketplace=Marketplace.AMAZON, url=url, added_by=added_by)
    return url_id, added_by


def test_price_only_submission_creates_no_listing_insight_row(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    fake_extractor.responses["img-1"] = ExtractionResult(
        fields=(ExtractedField("listed_price_paise", 100000), ExtractedField("availability", "IN_STOCK"))
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
        now=datetime.now(timezone.utc),
    )

    assert competitor_listing_insight_repo.get_by_snapshot(tenant_id, result.snapshot_id) is None


def test_title_submission_creates_a_listing_insight_row(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    fake_extractor.responses["img-1"] = ExtractionResult(
        fields=(
            ExtractedField("listed_price_paise", 100000),
            ExtractedField("availability", "IN_STOCK"),
            ExtractedField("title", "Waterproof Bluetooth Speaker"),
            ExtractedField("bullets", ["Waterproof", "10hr battery"]),
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
        now=datetime.now(timezone.utc),
    )

    insight = competitor_listing_insight_repo.get_by_snapshot(tenant_id, result.snapshot_id)
    assert insight is not None
    assert insight["insight_state"] == "COMPLETE"
    assert insight["bullet_count"] == 2
    assert insight["image_count"] is None
    assert "waterproof" in insight["keyword_themes"]


def test_differentiation_opportunities_uses_other_same_category_competitors(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_a, requested_by = _make_url(tenant_id, "https://amazon.in/dp/listing-insight-a")
    url_b, _ = _make_url(tenant_id, "https://amazon.in/dp/listing-insight-b")

    fake_extractor.responses["img-a"] = ExtractionResult(
        fields=(
            ExtractedField("listed_price_paise", 100000),
            ExtractedField("availability", "IN_STOCK"),
            ExtractedField("title", "Bluetooth Waterproof Speaker"),
            ExtractedField("observed_category", "Speakers"),
        )
    )
    submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_a,
        image_refs=["img-a"],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=fake_extractor,
        now=datetime.now(timezone.utc),
    )

    fake_extractor.responses["img-b"] = ExtractionResult(
        fields=(
            ExtractedField("listed_price_paise", 90000),
            ExtractedField("availability", "IN_STOCK"),
            ExtractedField("title", "Basic Portable Speaker"),
            ExtractedField("observed_category", "Speakers"),
        )
    )
    result_b = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_b,
        image_refs=["img-b"],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=fake_extractor,
        now=datetime.now(timezone.utc),
    )

    insight_b = competitor_listing_insight_repo.get_by_snapshot(tenant_id, result_b.snapshot_id)
    assert insight_b is not None
    assert "waterproof" in insight_b["differentiation_opportunities"] or "bluetooth" in insight_b["differentiation_opportunities"]
