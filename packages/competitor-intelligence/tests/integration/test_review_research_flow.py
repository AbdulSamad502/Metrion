"""submit_review_research() against a real Postgres — mirrors test_research_run_flow.py's
rigor for the review-evidence path. Uses a fake ReviewVisionExtractor; no real model, no
real network."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from competitor_intelligence.direct_path.research_run import submit_research_session
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import competitor_url_repo
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.review_insight.extraction import (
    ReviewExtractionFailed,
    ReviewExtractionResult,
    ReviewObservation,
)
from competitor_intelligence.review_insight.submit import submit_review_research
from competitor_intelligence.types import Marketplace, RunStatus

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


@dataclass
class _FakeReviewExtractor:
    responses: dict[str, ReviewExtractionResult | ReviewExtractionFailed] = field(default_factory=dict)

    def extract(self, image_ref: str):
        return self.responses.get(image_ref, ReviewExtractionFailed(reason="no fixture"))


def _make_url(tenant_id: uuid.UUID):
    added_by = uuid.uuid4()
    url_id = competitor_url_repo.create_url(
        tenant_id, marketplace=Marketplace.AMAZON, url="https://amazon.in/dp/fixture-reviews", added_by=added_by
    )
    return url_id, added_by


def test_review_research_persists_insight_and_agent_run(two_tenants):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    extractor = _FakeReviewExtractor(
        responses={
            "review-img-1": ReviewExtractionResult(
                reviews=(ReviewObservation("POSITIVE", ("battery",)), ReviewObservation("NEGATIVE", ("delivery",)))
            )
        }
    )

    result = submit_review_research(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["review-img-1"],
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=extractor,
    )

    assert result.status == RunStatus.COMPLETE
    assert result.review_insight_id is not None
    assert result.insight_state == "COMPLETE"

    with tenant_scope(tenant_id) as conn:
        run = conn.execute(
            text("SELECT agent_id, trigger_ref, status FROM agent_run WHERE id = :id"),
            {"id": str(result.agent_run_id)},
        ).mappings().one()
    assert run["agent_id"] == "CI"
    assert run["trigger_ref"] == "ci.review_research"
    assert run["status"] == "COMPLETE"

    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT reviews_considered, insight_state FROM competitor_review_insight WHERE id = :id"),
            {"id": str(result.review_insight_id)},
        ).mappings().one()
    assert row["reviews_considered"] == 2
    assert row["insight_state"] == "COMPLETE"


def test_zero_legible_reviews_is_unavailable_and_partial_run(two_tenants):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    extractor = _FakeReviewExtractor(responses={"review-img-1": ReviewExtractionResult(reviews=())})

    result = submit_review_research(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["review-img-1"],
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=extractor,
    )

    assert result.status == RunStatus.PARTIAL
    assert result.insight_state == "UNAVAILABLE"


def test_review_insight_can_link_to_an_existing_snapshot_and_use_its_fallback(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)

    fake_extractor.responses["listing-img"] = ExtractionResult(
        fields=(
            ExtractedField("listed_price_paise", 50000),
            ExtractedField("availability", "IN_STOCK"),
            ExtractedField("rating", "4.5"),
            ExtractedField("rating_count", 200),
        )
    )
    listing_result = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["listing-img"],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=fake_extractor,
        now=datetime.now(timezone.utc),
    )

    review_extractor = _FakeReviewExtractor(responses={"review-img-1": ReviewExtractionFailed(reason="model down")})
    result = submit_review_research(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["review-img-1"],
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=review_extractor,
        snapshot_id=listing_result.snapshot_id,
    )

    assert result.insight_state == "DEGRADED"  # E16: falls back to the linked snapshot's rating/rating_count

    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT snapshot_id FROM competitor_review_insight WHERE id = :id"),
            {"id": str(result.review_insight_id)},
        ).mappings().one()
    assert row["snapshot_id"] == listing_result.snapshot_id


def test_permission_denied_fails_before_any_extraction(two_tenants):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    extractor = _FakeReviewExtractor()

    result = submit_review_research(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=["review-img-1"],
        permission_check="DENIED",
        entitlement_check="PASS",
        extractor=extractor,
    )

    assert result.status == RunStatus.FAILED
    assert result.review_insight_id is None
