"""competitor-intelligence-agent.md §6.13.1-§6.13.2 — identity resolution and gating."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from competitor_intelligence.discovery.identity_resolution import (
    CaveatedValue,
    GatingOutcome,
    IdentityMatch,
    IdentityResolution,
    attach_identity_caveat,
    enters_relevance_scoring,
    gate,
    resolve_identity,
)
from competitor_intelligence.discovery.search_provider import SearchResult
from competitor_intelligence.seller_product.types import FieldSource, SellerProduct

_NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def _seller_product(title: str = "XYZ Wireless Mouse Pro", **overrides) -> SellerProduct:
    defaults = dict(
        product_id="SKU-1",
        title=title,
        category="Computer Accessories",
        price_paise=99900,
        attributes=None,
        keywords=("wireless mouse", "ergonomic"),
        fulfillment_type="SELLER_FULFILLED",
        review_count=None,
        rating=None,
        last_updated=None,
        field_source={"title": FieldSource.CANONICAL_DERIVED},
    )
    defaults.update(overrides)
    return SellerProduct(**defaults)


def _candidate(title: str | None, snippet: str | None = None, url: str = "https://amazon.in/dp/x") -> SearchResult:
    return SearchResult(rank=1, url=url, title=title, snippet=snippet, source="MOCK", retrieved_at=_NOW)


# --------------------------------------------------------------------------------------
# Four tiers, concrete examples
# --------------------------------------------------------------------------------------


def test_exact_match_same_brand_same_model_no_variant_signal() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro")
    candidate = _candidate("XYZ Wireless Mouse Pro - Black")

    resolution = resolve_identity(candidate, seller)

    assert resolution.identity_match is IdentityMatch.EXACT_MATCH
    assert resolution.caveat is None
    assert resolution.basis.candidate_brand == "XYZ"
    assert resolution.basis.seller_brand == "XYZ"


def test_likely_variant_same_brand_same_line_different_pack_size() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro", attributes=(("brand", "XYZ"), ("pack_size", "1")))
    candidate = _candidate("XYZ Wireless Mouse Pro - Pack of 2")

    resolution = resolve_identity(candidate, seller)

    assert resolution.identity_match is IdentityMatch.LIKELY_VARIANT
    assert resolution.caveat is not None
    assert "2-pack" in resolution.caveat
    assert resolution.basis.candidate_pack_size == 2
    assert resolution.basis.seller_pack_size == 1


def test_likely_variant_bundle_mismatch() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro", attributes=(("brand", "XYZ"), ("bundle", "false")))
    candidate = _candidate("XYZ Wireless Mouse Pro Combo Kit with Mousepad")

    resolution = resolve_identity(candidate, seller)

    assert resolution.identity_match is IdentityMatch.LIKELY_VARIANT
    assert resolution.caveat is not None
    assert "bundle" in resolution.caveat.lower()


def test_uncertain_when_model_tokens_do_not_overlap_confidently() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro")
    candidate = _candidate("XYZ Bluetooth Keyboard Deluxe")

    resolution = resolve_identity(candidate, seller)

    assert resolution.identity_match is IdentityMatch.UNCERTAIN
    assert resolution.caveat is None


def test_uncertain_when_candidate_has_no_usable_text() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro")
    candidate = _candidate(title=None, snippet=None)

    resolution = resolve_identity(candidate, seller)

    assert resolution.identity_match is IdentityMatch.UNCERTAIN
    assert resolution.caveat is None


def test_not_a_match_different_brand() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro")
    candidate = _candidate("ABC Wireless Mouse Pro")

    resolution = resolve_identity(candidate, seller)

    assert resolution.identity_match is IdentityMatch.NOT_A_MATCH
    assert resolution.caveat is None
    assert resolution.basis.notes == "different brand"


def test_basis_is_always_present_regardless_of_tier() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro")
    for candidate_title in ("XYZ Wireless Mouse Pro", "ABC Wireless Mouse Pro", "XYZ Bluetooth Keyboard Deluxe", None):
        resolution = resolve_identity(_candidate(candidate_title), seller)
        assert resolution.basis is not None


# --------------------------------------------------------------------------------------
# IdentityResolution invariants (never silently assumed to be exact / caveat presence)
# --------------------------------------------------------------------------------------


def test_identity_resolution_rejects_likely_variant_without_caveat() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro")
    resolution = resolve_identity(_candidate("XYZ Wireless Mouse Pro"), seller)
    basis = resolution.basis
    with pytest.raises(ValueError, match="must carry a visible caveat"):
        IdentityResolution(identity_match=IdentityMatch.LIKELY_VARIANT, basis=basis, caveat=None)


def test_identity_resolution_rejects_caveat_on_non_variant_tiers() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro")
    resolution = resolve_identity(_candidate("XYZ Wireless Mouse Pro"), seller)
    basis = resolution.basis
    with pytest.raises(ValueError, match="only a LIKELY_VARIANT"):
        IdentityResolution(identity_match=IdentityMatch.EXACT_MATCH, basis=basis, caveat="spurious")


# --------------------------------------------------------------------------------------
# §6.13.2 gating table
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identity_match,expected_outcome,expected_enters",
    [
        (IdentityMatch.EXACT_MATCH, GatingOutcome.PROCEEDS, True),
        (IdentityMatch.LIKELY_VARIANT, GatingOutcome.PROCEEDS_WITH_CAVEAT, True),
        (IdentityMatch.UNCERTAIN, GatingOutcome.BLOCKED_FOR_REVIEW, False),
        (IdentityMatch.NOT_A_MATCH, GatingOutcome.PROCEEDS_AS_OTHER_PRODUCT, True),  # C43: a different product is a candidate competitor
    ],
)
def test_gating_table_matches_spec_exactly(identity_match, expected_outcome, expected_enters) -> None:
    assert gate(identity_match) is expected_outcome
    assert enters_relevance_scoring(identity_match) is expected_enters


# --------------------------------------------------------------------------------------
# Caveat propagation onto a downstream comparison-shaped object (§6.13.2, not just a badge)
# --------------------------------------------------------------------------------------


def test_likely_variant_caveat_propagates_onto_a_downstream_comparison_field() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro", attributes=(("brand", "XYZ"), ("pack_size", "1")))
    candidate = _candidate("XYZ Wireless Mouse Pro - Pack of 2")
    resolution = resolve_identity(candidate, seller)
    assert resolution.identity_match is IdentityMatch.LIKELY_VARIANT

    price_comparison = attach_identity_caveat(-500, resolution)  # e.g. a price-difference-in-paise figure

    assert isinstance(price_comparison, CaveatedValue)
    assert price_comparison.value == -500
    assert price_comparison.identity_match is IdentityMatch.LIKELY_VARIANT
    assert price_comparison.caveat == resolution.caveat
    assert price_comparison.caveat is not None


def test_exact_match_comparison_field_carries_no_caveat() -> None:
    seller = _seller_product("XYZ Wireless Mouse Pro")
    candidate = _candidate("XYZ Wireless Mouse Pro")
    resolution = resolve_identity(candidate, seller)
    assert resolution.identity_match is IdentityMatch.EXACT_MATCH

    comparison = attach_identity_caveat(1200, resolution)

    assert comparison.caveat is None


def test_caveated_value_rejects_a_likely_variant_without_a_caveat_string() -> None:
    with pytest.raises(ValueError, match="must carry its caveat"):
        CaveatedValue(value=1, identity_match=IdentityMatch.LIKELY_VARIANT, caveat=None)


def test_caveated_value_rejects_a_caveat_on_a_non_variant_match() -> None:
    with pytest.raises(ValueError, match="only a LIKELY_VARIANT"):
        CaveatedValue(value=1, identity_match=IdentityMatch.EXACT_MATCH, caveat="spurious")
