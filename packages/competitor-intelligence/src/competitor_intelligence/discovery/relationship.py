"""Competitive relationship — competitor-intelligence-agent.md §6.27.1 (C43, D17).

*Identity* (`identity_resolution.py`) answers "is this the same sellable product as mine?".
*Relationship* answers "how does this product compete with mine?". They are separate: a
different brand's 1 L steel bottle is `NOT_A_MATCH` on identity and, correctly, a
`DIRECT_COMPETITOR` on relationship. Collapsing them is what made the original gate reject every
cross-brand competitor.

Everything here is a deterministic function of values already computed — the identity result and
the §6.14 relevance axes. No LLM, no network, no new judgement. `UNKNOWN` is a first-class,
never-promoted outcome (C25): a class is named only when the evidence for it is in hand.

**Provisional derivation (spec §6.27.1, refined at CP2).** At discovery a search lead has no
structured category and no use-case judgement, so the category and use-case axes are `UNKNOWN`.
Waiting for those would leave every lead `UNKNOWN`. So when category is unknown, the *product*
axis alone may name `DIRECT_COMPETITOR` / `FUNCTIONAL_ALTERNATIVE` — flagged
`is_provisional=True` — and `UNRELATED` is reserved for the evidence-backed case (category and
product both `KNOWN` zero). A provisional class is a label on a lead, never a fact about the
competitor, and is revised when evidence supplies the missing axes (V18 validates accuracy).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from competitor_intelligence.discovery.identity_resolution import IdentityMatch, IdentityMatchBasis
from competitor_intelligence.discovery.relevance_scoring import (
    AxisResult,
    AxisState,
    ProductSimilarityTier,
)


class RelationshipClass(str, Enum):
    SAME_PRODUCT = "SAME_PRODUCT"
    VARIANT = "VARIANT"
    DIRECT_COMPETITOR = "DIRECT_COMPETITOR"
    FUNCTIONAL_ALTERNATIVE = "FUNCTIONAL_ALTERNATIVE"
    UNRELATED = "UNRELATED"
    UNKNOWN = "UNKNOWN"


# Deterministic product-similarity from title tokens (brand excluded by identity resolution).
# Deliberately never returns DIFFERENT: low overlap between two titles is not evidence that two
# products are different (synonyms: "bottle" / "flask"), so it stays unknown (C25).
SAME_LINE_MIN_OVERLAP = 0.5
SAME_TYPE_MIN_OVERLAP = 0.15


def product_tier_from_tokens(basis: IdentityMatchBasis) -> ProductSimilarityTier | None:
    seller = basis.seller_model_tokens
    candidate = basis.candidate_model_tokens
    if not seller or not candidate:
        return None
    union = seller | candidate
    overlap = len(seller & candidate) / len(union)
    if overlap >= SAME_LINE_MIN_OVERLAP:
        return ProductSimilarityTier.SAME_LINE
    if overlap >= SAME_TYPE_MIN_OVERLAP:
        return ProductSimilarityTier.SAME_TYPE_DIFFERENT_LINE
    return None


@dataclass(frozen=True, slots=True)
class Relationship:
    relationship_class: RelationshipClass
    is_provisional: bool
    basis: dict[str, object]

    @property
    def recommendable(self) -> bool:
        """Whether this relationship may put a candidate into the Recommended tier. `UNKNOWN`
        and `UNRELATED` never fill a list (C25, C43) — they stay visible in the other tiers."""
        return self.relationship_class in (
            RelationshipClass.SAME_PRODUCT,
            RelationshipClass.VARIANT,
            RelationshipClass.DIRECT_COMPETITOR,
            RelationshipClass.FUNCTIONAL_ALTERNATIVE,
        )


def classify_relationship(
    identity_match: IdentityMatch,
    *,
    category: AxisResult,
    product: AxisResult,
    use_case: AxisResult,
) -> Relationship:
    basis: dict[str, object] = {
        "identity_match": identity_match.value,
        "category": [category.score, category.state.value],
        "product": [product.score, product.state.value],
        "use_case": [use_case.score, use_case.state.value],
    }

    if identity_match is IdentityMatch.EXACT_MATCH:
        return Relationship(RelationshipClass.SAME_PRODUCT, False, basis)
    if identity_match is IdentityMatch.LIKELY_VARIANT:
        return Relationship(RelationshipClass.VARIANT, False, basis)
    if identity_match is IdentityMatch.UNCERTAIN:
        return Relationship(RelationshipClass.UNKNOWN, True, basis)

    # NOT_A_MATCH: a different product. How does it compete?
    category_known = category.state is AxisState.KNOWN
    product_known = product.state is AxisState.KNOWN
    use_case_known = use_case.state is AxisState.KNOWN

    if category_known and product_known and category.score == 0 and product.score == 0:
        return Relationship(RelationshipClass.UNRELATED, False, basis)

    if not product_known:
        return Relationship(RelationshipClass.UNKNOWN, True, basis)

    if category_known:
        if category.score >= 1 and product.score == 2:
            return Relationship(RelationshipClass.DIRECT_COMPETITOR, False, basis)
        if (category.score >= 1 and product.score == 1) or (product.score == 1 and use_case_known and use_case.score >= 1):
            return Relationship(RelationshipClass.FUNCTIONAL_ALTERNATIVE, False, basis)
        return Relationship(RelationshipClass.UNKNOWN, False, basis)

    # Category unknown: the product axis alone decides, provisionally.
    if product.score == 2:
        return Relationship(RelationshipClass.DIRECT_COMPETITOR, True, basis)
    if product.score == 1:
        return Relationship(RelationshipClass.FUNCTIONAL_ALTERNATIVE, True, basis)
    return Relationship(RelationshipClass.UNKNOWN, True, basis)
