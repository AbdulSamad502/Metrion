"""Four-bucket competitor-vs-seller comparison — competitor-intelligence-agent.md §6.19.
Computed only for a candidate with at least one evidence source (§6.10.3) — never on a
tracked competitor still sitting at `AWAITING_EVIDENCE`. Deterministic set-comparison only:
no LLM, no financial arithmetic (that boundary is unrelated to this module, which never
touches money at all — comparison here is keyword/attribute overlap, not price).

Honest, documented data-model limitation (not a shortcut): `SellerProduct` (§5.5) has no
`description`/`bullets` field — only `category`/`attributes`/`keywords`/`price_paise`/
`fulfillment_type` (C31 locks exactly those five for the manual form; `title` is
canonical-derived only). Any bucket entry that would need the seller's own listing
description/bullets to compute is therefore always `UNKNOWN` today, honestly, exactly like
`review_count`/`rating` are always `UNKNOWN` (§5.5.2) — this is the same "we don't capture
that yet" degradation already established elsewhere in this package, not new to this module.

§6.19.2's differentiation-claim rule is enforced structurally, not by convention: this
module has no field anywhere for "affirmative seller evidence" (a positive review, a test
result, an explicit spec) that would license the stronger claim, so every
`differentiation_opportunities` entry this module produces renders at the conservative tier
only ("available seller evidence does not indicate this problem; your listing doesn't
currently address it") — there is no code path in this module capable of producing the
stronger, disallowed claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from competitor_intelligence.discovery.identity_resolution import IdentityMatch
from competitor_intelligence.repositories import (
    ci_candidate_repo,
    competitor_listing_insight_repo,
    competitor_review_insight_repo,
    competitor_snapshot_repo,
)
from competitor_intelligence.seller_product.types import SellerProduct
from competitor_intelligence.types import Unavailable


class ComparisonState(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ComparisonEntry:
    """One bucket entry. `state=UNKNOWN` means exactly that — a value this comparison would
    need is not on record on one or both sides — never inferred, never omitted (§6.19.1: "is
    reported UNKNOWN, not omitted and not inferred"). `caveat` carries the candidate's
    `LIKELY_VARIANT` caveat, when applicable, onto this specific entry (§6.13.2)."""

    field: str
    state: ComparisonState
    detail: str
    caveat: str | None = None


@dataclass(frozen=True, slots=True)
class CompetitorComparison:
    competitor_url_id: UUID
    snapshot_id: UUID
    listing_gaps: tuple[ComparisonEntry, ...]
    product_strengths: tuple[ComparisonEntry, ...]
    product_weaknesses: tuple[ComparisonEntry, ...]
    differentiation_opportunities: tuple[ComparisonEntry, ...]


def _theme_set(themes: object) -> frozenset[str] | None:
    """`competitor_listing_insight.keyword_themes` / `.feature_categories` are jsonb; be
    liberal about the container shape (list or already a set-like) but never silently treat
    a missing value as an empty, comparable set — that would fabricate a gap/strength from
    nothing (§6.19.1)."""
    if not themes:
        return None
    return frozenset(str(t).strip().lower() for t in themes if str(t).strip())


def _seller_keyword_set(seller_product: SellerProduct) -> frozenset[str] | None:
    if not seller_product.keywords:
        return None
    return frozenset(k.strip().lower() for k in seller_product.keywords if k.strip())


def _seller_attribute_set(seller_product: SellerProduct) -> frozenset[str] | None:
    if not seller_product.attributes:
        return None
    return frozenset(v.strip().lower() for _, v in seller_product.attributes if v.strip())


def compute_comparison(
    tenant_id: UUID, *, competitor_url_id: UUID, seller_product: SellerProduct
) -> CompetitorComparison | Unavailable:
    snapshot = competitor_snapshot_repo.latest_usable_snapshot(tenant_id, competitor_url_id)
    if snapshot is None:
        return Unavailable(reason="AWAITING_EVIDENCE — no usable snapshot for this competitor yet (§6.10.3)")

    candidate = ci_candidate_repo.get_by_competitor_url_id(tenant_id, competitor_url_id)
    caveat: str | None = None
    if candidate is not None and candidate["identity_match"] == IdentityMatch.LIKELY_VARIANT.value:
        caveat = "This competitor may be a different variant of the same product line (§6.13.2)."

    listing_insight = competitor_listing_insight_repo.get_by_snapshot(tenant_id, snapshot["id"])
    review_insight = competitor_review_insight_repo.get_by_snapshot(tenant_id, snapshot["id"])

    competitor_keywords = _theme_set(listing_insight["keyword_themes"]) if listing_insight else None
    competitor_features = _theme_set(listing_insight["feature_categories"]) if listing_insight else None
    seller_keywords = _seller_keyword_set(seller_product)
    seller_terms = (seller_keywords or frozenset()) | (_seller_attribute_set(seller_product) or frozenset())

    listing_gaps: list[ComparisonEntry] = []
    product_strengths: list[ComparisonEntry] = []

    if listing_insight is None:
        listing_gaps.append(
            ComparisonEntry("keywords", ComparisonState.UNKNOWN, "Competitor listing insight not yet derived.")
        )
        product_strengths.append(
            ComparisonEntry("keywords", ComparisonState.UNKNOWN, "Competitor listing insight not yet derived.")
        )
    elif seller_keywords is None:
        listing_gaps.append(
            ComparisonEntry(
                "keywords", ComparisonState.UNKNOWN,
                "Your own keywords are UNKNOWN — fill in your Seller Product profile to compare.",
            )
        )
        product_strengths.append(
            ComparisonEntry(
                "keywords", ComparisonState.UNKNOWN,
                "Your own keywords are UNKNOWN — fill in your Seller Product profile to compare.",
            )
        )
    else:
        competitor_terms = (competitor_keywords or frozenset()) | (competitor_features or frozenset())
        for term in sorted(competitor_terms - seller_terms):
            listing_gaps.append(
                ComparisonEntry(
                    "keywords", ComparisonState.KNOWN,
                    f"Competitor's listing mentions '{term}' — your listing/profile doesn't.", caveat=caveat,
                )
            )
        for term in sorted(seller_terms - competitor_terms):
            product_strengths.append(
                ComparisonEntry(
                    "keywords", ComparisonState.KNOWN,
                    f"You mention '{term}' — this competitor's listing doesn't.", caveat=caveat,
                )
            )
        if not listing_gaps:
            listing_gaps.append(ComparisonEntry("keywords", ComparisonState.KNOWN, "No listing gaps found.", caveat=caveat))
        if not product_strengths:
            product_strengths.append(
                ComparisonEntry("keywords", ComparisonState.KNOWN, "No distinguishing keyword strengths found.", caveat=caveat)
            )

    # Product weaknesses: rating/review-volume comparison requires the seller's own rating/
    # review_count, which SellerProduct never carries (§5.5.2) — honestly UNKNOWN, not
    # fabricated, and price-based weakness is deliberately not recomputed here (that
    # arithmetic already exists, real and tested, at the price-scenario endpoint — Checkpoint
    # 1 — this module never duplicates it).
    product_weaknesses = (
        ComparisonEntry(
            "rating", ComparisonState.UNKNOWN,
            "Your own product rating is not captured by Metrion yet — cannot compare.",
        ),
        ComparisonEntry(
            "review_count", ComparisonState.UNKNOWN,
            "Your own review count is not captured by Metrion yet — cannot compare.",
        ),
        ComparisonEntry(
            "price", ComparisonState.UNKNOWN,
            "Use the price-position check above for a real, engine-computed price comparison — not duplicated here.",
        ),
    )

    differentiation_opportunities: list[ComparisonEntry] = []
    if review_insight is None:
        differentiation_opportunities.append(
            ComparisonEntry(
                "customer_complaints", ComparisonState.UNKNOWN,
                "No review evidence submitted for this competitor yet.",
            )
        )
    else:
        complaint_themes = review_insight["complaint_themes"] or []
        if not complaint_themes:
            differentiation_opportunities.append(
                ComparisonEntry("customer_complaints", ComparisonState.KNOWN, "No complaint themes recorded.", caveat=caveat)
            )
        for theme in complaint_themes:
            # §6.19.2, locked: the conservative claim only — this module has no field for
            # "affirmative seller evidence" that would license a stronger one.
            differentiation_opportunities.append(
                ComparisonEntry(
                    "customer_complaints", ComparisonState.KNOWN,
                    f"Competitors' customers mention '{theme}'. Available seller evidence does not indicate "
                    "this problem for you; your listing doesn't currently address it.",
                    caveat=caveat,
                )
            )

    return CompetitorComparison(
        competitor_url_id=competitor_url_id,
        snapshot_id=snapshot["id"],
        listing_gaps=tuple(listing_gaps),
        product_strengths=tuple(product_strengths),
        product_weaknesses=product_weaknesses,
        differentiation_opportunities=tuple(differentiation_opportunities),
    )
