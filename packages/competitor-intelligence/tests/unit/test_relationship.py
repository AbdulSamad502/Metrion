"""§6.27.1 / C43 / D17 — relationship class, derived deterministically; UNKNOWN never promoted."""

from __future__ import annotations

import pytest

from competitor_intelligence.discovery.identity_resolution import IdentityMatch, IdentityMatchBasis
from competitor_intelligence.discovery.relationship import (
    Relationship,
    RelationshipClass,
    classify_relationship,
    product_tier_from_tokens,
)
from competitor_intelligence.discovery.relevance_scoring import AxisResult, AxisState, ProductSimilarityTier

UNKNOWN = AxisResult(0, AxisState.UNKNOWN, "unknown")


def known(score: int) -> AxisResult:
    return AxisResult(score, AxisState.KNOWN, "known")


def _basis(seller: set[str], candidate: set[str]) -> IdentityMatchBasis:
    return IdentityMatchBasis(
        candidate_brand="Globex",
        seller_brand="Acme",
        candidate_model_tokens=frozenset(candidate),
        seller_model_tokens=frozenset(seller),
        candidate_pack_size=None,
        seller_pack_size=None,
        candidate_is_bundle=False,
        seller_is_bundle=False,
    )


def test_identity_classes_map_directly() -> None:
    assert classify_relationship(IdentityMatch.EXACT_MATCH, category=UNKNOWN, product=UNKNOWN, use_case=UNKNOWN).relationship_class is RelationshipClass.SAME_PRODUCT
    assert classify_relationship(IdentityMatch.LIKELY_VARIANT, category=UNKNOWN, product=UNKNOWN, use_case=UNKNOWN).relationship_class is RelationshipClass.VARIANT


def test_uncertain_identity_is_unknown_not_guessed() -> None:
    r = classify_relationship(IdentityMatch.UNCERTAIN, category=known(2), product=known(2), use_case=known(2))
    assert r.relationship_class is RelationshipClass.UNKNOWN and not r.recommendable


def test_known_category_and_same_line_product_is_a_direct_competitor_not_provisional() -> None:
    r = classify_relationship(IdentityMatch.NOT_A_MATCH, category=known(2), product=known(2), use_case=UNKNOWN)
    assert (r.relationship_class, r.is_provisional) == (RelationshipClass.DIRECT_COMPETITOR, False)


def test_same_type_different_line_is_a_functional_alternative() -> None:
    r = classify_relationship(IdentityMatch.NOT_A_MATCH, category=known(1), product=known(1), use_case=UNKNOWN)
    assert r.relationship_class is RelationshipClass.FUNCTIONAL_ALTERNATIVE


def test_unrelated_needs_category_and_product_both_known_zero() -> None:
    r = classify_relationship(IdentityMatch.NOT_A_MATCH, category=known(0), product=known(0), use_case=UNKNOWN)
    assert r.relationship_class is RelationshipClass.UNRELATED and not r.recommendable
    # A known-zero product with an UNKNOWN category is not enough to call something unrelated.
    r2 = classify_relationship(IdentityMatch.NOT_A_MATCH, category=UNKNOWN, product=known(0), use_case=UNKNOWN)
    assert r2.relationship_class is RelationshipClass.UNKNOWN


def test_unknown_category_lets_the_product_axis_decide_but_only_provisionally() -> None:
    top = classify_relationship(IdentityMatch.NOT_A_MATCH, category=UNKNOWN, product=known(2), use_case=UNKNOWN)
    assert (top.relationship_class, top.is_provisional) == (RelationshipClass.DIRECT_COMPETITOR, True)
    mid = classify_relationship(IdentityMatch.NOT_A_MATCH, category=UNKNOWN, product=known(1), use_case=UNKNOWN)
    assert (mid.relationship_class, mid.is_provisional) == (RelationshipClass.FUNCTIONAL_ALTERNATIVE, True)


def test_unknown_product_axis_is_never_promoted() -> None:
    r = classify_relationship(IdentityMatch.NOT_A_MATCH, category=known(2), product=UNKNOWN, use_case=known(2))
    assert r.relationship_class is RelationshipClass.UNKNOWN and not r.recommendable


def test_basis_records_what_drove_the_class() -> None:
    r: Relationship = classify_relationship(IdentityMatch.NOT_A_MATCH, category=UNKNOWN, product=known(2), use_case=UNKNOWN)
    assert r.basis["identity_match"] == "NOT_A_MATCH" and r.basis["product"] == [2, "KNOWN"]


@pytest.mark.parametrize(
    "seller,candidate,expected",
    [
        ({"wireless", "mouse", "pro"}, {"wireless", "mouse", "x200"}, ProductSimilarityTier.SAME_LINE),
        ({"wireless", "mouse", "pro"}, {"mouse", "gaming", "rgb"}, ProductSimilarityTier.SAME_TYPE_DIFFERENT_LINE),
        ({"wireless", "mouse"}, {"garden", "hose"}, None),  # no overlap is unknown, never "different"
        (set(), {"mouse"}, None),
        ({"mouse"}, set(), None),
    ],
)
def test_token_overlap_tiers_never_return_different(seller, candidate, expected) -> None:
    assert product_tier_from_tokens(_basis(seller, candidate)) is expected
