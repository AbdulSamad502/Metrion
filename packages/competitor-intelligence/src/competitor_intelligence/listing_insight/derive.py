"""`competitor_listing_insight` derivation (§6.6). Runs entirely over the seller-submitted
`title`/`description`/`bullets` text already persisted on `competitor_snapshot` under C16's
carve-out — it never triggers a new evidence submission or a model call of its own. This is
plain deterministic string analysis (`derivation_method = LOCAL_HEURISTIC`), not a
classify-then-aggregate model pipeline like `review_insight/` — MN8 doesn't apply here
because no model is involved at all.

`image_count` is deliberately never populated: nothing in the current evidence model
captures how many images a competitor's listing has (a seller's screenshot shows a page,
not an image manifest), so fabricating a count from what's visible in one screenshot would
be a guess, not an observation. It stays `None` always, by design — an honest gap, not an
oversight.

`feature_categories`/`benefit_term_patterns` are CI's OWN listing-content buckets (a handful
of generic English terms, e.g. "warranty," "waterproof") — unrelated to, and not a
substitute for, the still-unresolved marketplace-category-taxonomy question (Q8), which is
about mapping `observed_category` strings to the fee-reference store's taxonomy for margin
estimation, a different problem this module makes no attempt to solve.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from competitor_intelligence.types import Confidence, DerivationMethod, InsightState

_STOPWORDS = frozenset(
    "a an the and or for with of to in on is are be this that from your you it its as at by "
    "pack set new best top pcs piece pieces".split()
)

# CI's own listing-content buckets — a fixed, small, generic vocabulary. Not a marketplace
# taxonomy (Q8 remains unresolved and is not addressed here).
_FEATURE_CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "material": ("cotton", "plastic", "metal", "steel", "leather", "silicone", "wood", "glass", "fabric"),
    "size": ("small", "medium", "large", "xl", "xxl", "compact", "mini", "size"),
    "color": ("black", "white", "red", "blue", "green", "grey", "gray", "silver", "gold", "multicolor"),
    "power": ("battery", "rechargeable", "wireless", "bluetooth", "usb", "charging", "watt", "mah"),
    "durability": ("waterproof", "shockproof", "durable", "sturdy", "rugged", "heavy-duty"),
}

_BENEFIT_TERMS = (
    "free",
    "warranty",
    "guarantee",
    "guaranteed",
    "fast",
    "premium",
    "waterproof",
    "durable",
    "lightweight",
    "easy",
    "portable",
    "genuine",
)


@dataclass(frozen=True, slots=True)
class ListingInsightDraft:
    keyword_themes: dict[str, int]
    title_length: int | None
    title_structure: dict[str, object]
    feature_categories: dict[str, int]
    benefit_term_patterns: dict[str, int]
    differentiation_opportunities: list[str]
    bullet_count: int | None
    image_count: None
    confidence: Confidence
    derivation_method: DerivationMethod
    insight_state: InsightState
    degraded_reason: str | None


def _tokenize(*texts: str | None) -> list[str]:
    joined = " ".join(t for t in texts if t)
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", joined.lower())
    return [w for w in words if w not in _STOPWORDS]


def _title_structure(title: str | None) -> dict[str, object]:
    if not title:
        return {}
    words = title.split()
    return {
        "word_count": len(words),
        "char_count": len(title),
        "has_numbers": bool(re.search(r"\d", title)),
        "has_brand_prefix": bool(words) and words[0].isupper() is False and words[0][:1].isupper(),
    }


def _feature_categories(tokens: Sequence[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    token_set = set(tokens)
    for category, terms in _FEATURE_CATEGORY_TERMS.items():
        hits = sum(1 for t in terms if t in token_set)
        if hits:
            counts[category] = hits
    return dict(counts)


def _benefit_term_patterns(tokens: Sequence[str]) -> dict[str, int]:
    counter = Counter(tokens)
    return {term: counter[term] for term in _BENEFIT_TERMS if counter[term] > 0}


def derive_listing_insight(
    *,
    title: str | None,
    description: str | None,
    bullets: Sequence[str] | None,
    other_competitor_theme_sets: Sequence[frozenset[str]] = (),
) -> ListingInsightDraft:
    """`other_competitor_theme_sets` — each element is another tracked competitor's (same
    tenant, same `observed_category`) most recent keyword-theme set, supplied by the caller
    (`competitor_listing_insight_repo`) — this function does no querying of its own, keeping
    it a pure function like the rest of this package's derivation code."""
    if title is None and description is None and not bullets:
        return ListingInsightDraft(
            keyword_themes={},
            title_length=None,
            title_structure={},
            feature_categories={},
            benefit_term_patterns={},
            differentiation_opportunities=[],
            bullet_count=None,
            image_count=None,
            confidence=Confidence.UNAVAILABLE,
            derivation_method=DerivationMethod.STRUCTURED_ONLY,
            insight_state=InsightState.UNAVAILABLE,
            degraded_reason="no title, description or bullets recorded on this snapshot",
        )

    bullets_text = " ".join(bullets) if bullets else None
    tokens = _tokenize(title, description, bullets_text)
    keyword_themes = dict(Counter(tokens).most_common(10))

    this_listing_themes = frozenset(keyword_themes)
    common_across_others = Counter[str]()
    for other in other_competitor_theme_sets:
        common_across_others.update(other)
    differentiation_opportunities = sorted(
        theme for theme, count in common_across_others.items() if count >= 1 and theme not in this_listing_themes
    )[:10]

    insight_state = InsightState.COMPLETE if title else InsightState.DEGRADED
    degraded_reason = None if title else "no title recorded — analysis limited to description/bullets"

    return ListingInsightDraft(
        keyword_themes=keyword_themes,
        title_length=len(title) if title else None,
        title_structure=_title_structure(title),
        feature_categories=_feature_categories(tokens),
        benefit_term_patterns=_benefit_term_patterns(tokens),
        differentiation_opportunities=differentiation_opportunities,
        bullet_count=len(bullets) if bullets is not None else None,
        image_count=None,
        confidence=Confidence.DERIVED,
        derivation_method=DerivationMethod.LOCAL_HEURISTIC,
        insight_state=insight_state,
        degraded_reason=degraded_reason,
    )
