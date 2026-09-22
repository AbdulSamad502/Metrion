"""Checkpoint 6 — Market/Competitive Landscape, against a real Postgres:
`landscape/price_band.py`'s eligibility selection (competitor-intelligence-agent.md
§6.16.3) and `landscape/comparison.py`'s four-bucket comparison (§6.19). Reuses the real
`submit_research_session` write path (same convention as test_step5_features.py) rather than
hand-inserting snapshot rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from competitor_intelligence.direct_path.research_run import submit_research_session
from competitor_intelligence.discovery.identity_resolution import (
    IdentityMatch,
    IdentityMatchBasis,
    IdentityResolution,
)
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.landscape.comparison import ComparisonState, compute_comparison
from competitor_intelligence.landscape.price_band import eligible_competitor_prices
from competitor_intelligence.listing_insight.derive import ListingInsightDraft
from competitor_intelligence.repositories import (
    ci_candidate_repo,
    competitor_listing_insight_repo,
    competitor_review_insight_repo,
    competitor_url_repo,
)
from competitor_intelligence.review_insight.aggregate import ReviewInsightDraft
from competitor_intelligence.seller_product.types import FieldSource, SellerProduct
from competitor_intelligence.types import Confidence, DerivationMethod, InsightState, Marketplace, Unavailable

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")

PRODUCT_ID = "SKU-LANDSCAPE-1"


def _make_url(tenant_id: uuid.UUID, url: str, *, linked_sku: str | None = PRODUCT_ID):
    added_by = uuid.uuid4()
    url_id = competitor_url_repo.create_url(
        tenant_id, marketplace=Marketplace.AMAZON, url=url, added_by=added_by, linked_sku=linked_sku
    )
    return url_id, added_by


def _research(tenant_id, url_id, requested_by, extractor, *, price: int, when: datetime, **extra_fields):
    image_ref = f"img-{url_id}-{when.isoformat()}"
    fields = [ExtractedField("listed_price_paise", price), ExtractedField("availability", "IN_STOCK")]
    for key, value in extra_fields.items():
        fields.append(ExtractedField(key, value))
    extractor.responses[image_ref] = ExtractionResult(fields=tuple(fields))
    return submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=[image_ref],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=extractor,
        now=when,
    )


def _identity_basis() -> IdentityMatchBasis:
    return IdentityMatchBasis(
        candidate_brand="Acme", seller_brand="Acme",
        candidate_model_tokens=frozenset({"mouse"}), seller_model_tokens=frozenset({"mouse"}),
        candidate_pack_size=None, seller_pack_size=None, candidate_is_bundle=False, seller_is_bundle=False,
    )


def _seller_product(**overrides) -> SellerProduct:
    defaults = dict(
        product_id=PRODUCT_ID, title="Acme Mouse", category="Computer Accessories", price_paise=90_000,
        attributes=(("brand", "Acme"),), keywords=("wireless", "ergonomic"), fulfillment_type="SELLER_FULFILLED",
        review_count=None, rating=None, last_updated=datetime.now(timezone.utc),
        field_source={"category": FieldSource.SELLER_ENTERED, "keywords": FieldSource.SELLER_ENTERED},
    )
    defaults.update(overrides)
    return SellerProduct(**defaults)


class TestPriceBandEligibility:
    def test_three_tracked_competitors_are_all_eligible(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        for i, price in enumerate([85_000, 90_000, 95_000]):
            url_id, requested_by = _make_url(tenant_a, f"https://amazon.in/dp/lb-{i}")
            _research(tenant_a, url_id, requested_by, fake_extractor, price=price, when=now)

        prices = eligible_competitor_prices(tenant_a, PRODUCT_ID)
        assert sorted(p.value_paise for p in prices) == [85_000, 90_000, 95_000]

    def test_uncertain_identity_match_is_excluded(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        good_url, requested_by = _make_url(tenant_a, "https://amazon.in/dp/lb-good")
        _research(tenant_a, good_url, requested_by, fake_extractor, price=90_000, when=now)

        uncertain_url, _ = _make_url(tenant_a, "https://amazon.in/dp/lb-uncertain")
        _research(tenant_a, uncertain_url, requested_by, fake_extractor, price=999_999, when=now)
        ci_candidate_repo.set_identity_resolution(
            tenant_a,
            ci_candidate_repo.create_candidate(tenant_a, discovery_run_id=uuid.uuid4(), candidate_url="https://amazon.in/dp/lb-uncertain"),
            IdentityResolution(identity_match=IdentityMatch.UNCERTAIN, basis=_identity_basis()),
            tier="ANALYZED",
        )
        # Link that candidate's competitor_url_id to the real tracked URL — accept_candidate
        # normally does this at accept time; this test constructs the linkage directly since
        # it's exercising eligibility filtering, not the full discovery accept flow (already
        # covered by Checkpoint 5's own tests).
        candidates = ci_candidate_repo.list_candidates_for_run(tenant_a, uuid.uuid4())  # no-op, just for readability
        # Find the candidate we just created by URL to link it.
        from sqlalchemy import text as _text
        from competitor_intelligence.repositories.tenant_context import tenant_scope as _tenant_scope

        with _tenant_scope(tenant_a) as conn:
            candidate_id = conn.execute(
                _text("SELECT id FROM ci_candidate WHERE tenant_id = :t AND candidate_url = :u"),
                {"t": str(tenant_a), "u": "https://amazon.in/dp/lb-uncertain"},
            ).scalar_one()
        ci_candidate_repo.set_competitor_url_id(tenant_a, candidate_id, uncertain_url)

        prices = eligible_competitor_prices(tenant_a, PRODUCT_ID)
        assert [p.value_paise for p in prices] == [90_000]

    def test_manually_added_competitor_with_no_candidate_record_is_eligible(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/lb-manual")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=77_000, when=now)

        prices = eligible_competitor_prices(tenant_a, PRODUCT_ID)
        assert [p.value_paise for p in prices] == [77_000]

    def test_no_usable_snapshot_yet_is_excluded_not_fabricated(self, two_tenants) -> None:
        tenant_a, _ = two_tenants
        _make_url(tenant_a, "https://amazon.in/dp/lb-no-evidence")
        assert eligible_competitor_prices(tenant_a, PRODUCT_ID) == []

    def test_scoped_to_the_right_product_only(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/lb-other-sku", linked_sku="SKU-OTHER")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=50_000, when=now)
        assert eligible_competitor_prices(tenant_a, PRODUCT_ID) == []
        assert len(eligible_competitor_prices(tenant_a, "SKU-OTHER")) == 1


class TestComparison:
    def test_no_evidence_is_unavailable(self, two_tenants) -> None:
        tenant_a, _ = two_tenants
        url_id, _ = _make_url(tenant_a, "https://amazon.in/dp/cmp-no-evidence")
        result = compute_comparison(tenant_a, competitor_url_id=url_id, seller_product=_seller_product())
        assert isinstance(result, Unavailable)
        assert "AWAITING_EVIDENCE" in result.reason

    def test_listing_gap_and_strength_are_real_set_differences(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/cmp-1")
        result = _research(tenant_a, url_id, requested_by, fake_extractor, price=90_000, when=now)

        draft = ListingInsightDraft(
            keyword_themes={"silent click": 1, "wireless": 1},
            title_length=20, title_structure={}, feature_categories={},
            benefit_term_patterns={}, differentiation_opportunities=[], bullet_count=3, image_count=None,
            confidence=Confidence.DERIVED, derivation_method=DerivationMethod.LOCAL_HEURISTIC,
            insight_state=InsightState.COMPLETE, degraded_reason=None,
        )
        competitor_listing_insight_repo.insert_insight(
            tenant_a, snapshot_id=result.snapshot_id, source_url=url_id and "https://amazon.in/dp/cmp-1", fetched_at=now, draft=draft
        )

        comparison = compute_comparison(tenant_a, competitor_url_id=url_id, seller_product=_seller_product())
        assert not isinstance(comparison, Unavailable)
        gap_texts = " ".join(e.detail for e in comparison.listing_gaps)
        assert "silent click" in gap_texts  # competitor has it, seller keywords don't
        strength_texts = " ".join(e.detail for e in comparison.product_strengths)
        assert "ergonomic" in strength_texts  # seller has it, competitor listing doesn't

    def test_weaknesses_bucket_is_honestly_unknown_never_fabricated(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/cmp-2")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=90_000, when=now)

        comparison = compute_comparison(tenant_a, competitor_url_id=url_id, seller_product=_seller_product())
        assert not isinstance(comparison, Unavailable)
        assert all(e.state == ComparisonState.UNKNOWN for e in comparison.product_weaknesses)

    def test_differentiation_uses_conservative_claim_only(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/cmp-3")
        result = _research(tenant_a, url_id, requested_by, fake_extractor, price=90_000, when=now)

        review_draft = ReviewInsightDraft(
            sentiment_split={"POSITIVE": "3/5", "NEGATIVE": "2/5", "NEUTRAL": "0/5"},
            positive_themes={}, complaint_themes={"battery life": 2},
            rating_distribution=None, reviews_considered=5, confidence=Confidence.DERIVED,
            derivation_method=DerivationMethod.LOCAL_MODEL, insight_state=InsightState.COMPLETE, degraded_reason=None,
        )
        competitor_review_insight_repo.insert_insight(
            tenant_a, snapshot_id=result.snapshot_id, source_url="https://amazon.in/dp/cmp-3", fetched_at=now, draft=review_draft
        )

        comparison = compute_comparison(tenant_a, competitor_url_id=url_id, seller_product=_seller_product())
        assert not isinstance(comparison, Unavailable)
        entry = next(e for e in comparison.differentiation_opportunities if "battery life" in e.detail)
        assert "does not indicate this problem" in entry.detail
        assert "your product does not have this problem" not in entry.detail.lower()

    def test_likely_variant_caveat_travels_onto_every_entry(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/cmp-4")
        result = _research(tenant_a, url_id, requested_by, fake_extractor, price=90_000, when=now)

        draft = ListingInsightDraft(
            keyword_themes={"silent click": 1}, title_length=10, title_structure={}, feature_categories={},
            benefit_term_patterns={}, differentiation_opportunities=[], bullet_count=1, image_count=None,
            confidence=Confidence.DERIVED, derivation_method=DerivationMethod.LOCAL_HEURISTIC,
            insight_state=InsightState.COMPLETE, degraded_reason=None,
        )
        competitor_listing_insight_repo.insert_insight(
            tenant_a, snapshot_id=result.snapshot_id, source_url="https://amazon.in/dp/cmp-4", fetched_at=now, draft=draft
        )

        candidate_id = ci_candidate_repo.create_candidate(tenant_a, discovery_run_id=uuid.uuid4(), candidate_url="https://amazon.in/dp/cmp-4")
        ci_candidate_repo.set_identity_resolution(
            tenant_a, candidate_id,
            IdentityResolution(identity_match=IdentityMatch.LIKELY_VARIANT, basis=_identity_basis(), caveat="may be a 2-pack"),
            tier="ANALYZED",
        )
        ci_candidate_repo.set_competitor_url_id(tenant_a, candidate_id, url_id)

        comparison = compute_comparison(tenant_a, competitor_url_id=url_id, seller_product=_seller_product())
        assert not isinstance(comparison, Unavailable)
        assert all(e.caveat is not None for e in comparison.listing_gaps if e.state == ComparisonState.KNOWN)
