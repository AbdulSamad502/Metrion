"""Review/listing derived-insight generation (C5/C6/C14/C16, local-only — raw review text is
never sent to a hosted LLM provider).

Like `capture/parser.py`, the derivation logic itself is NOT implemented in this pass — for a
different reason than the price-snapshot parser, but just as deliberate:

1. Acquiring review data at all requires fetching a marketplace's reviews page/tab, which is
   a structurally separate target from the single listing-page fetch `capture/service.py`
   handles. No selectors or acquisition strategy for that page are specified anywhere in the
   spec.
2. Turning raw review text into sentiment/themes requires a local model, and the spec's own
   §12 open questions flag "local derivation model quality on 4GB VRAM" as unresolved (🔴,
   genuinely undefined — not something this pass can guess a model choice for).

Building either half now would mean inventing an acquisition strategy and a model choice
neither confirmed anywhere — exactly what "no invented values... no invented marketplace
rules" forbids. What IS implemented: the `ReviewInsightDraft`/`ListingInsightDraft` shapes
(so a future derivation engine has a concrete contract to fill) and the persistence
repositories for `competitor_review_insight`/`competitor_listing_insight` (ordinary DB code,
independent of how derivation eventually happens) — see `repositories/insight_repo.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from competitor_intelligence.types import Confidence, DerivationMethod, InsightState


@dataclass(frozen=True, slots=True)
class ReviewInsightDraft:
    sentiment_split: dict[str, Any] | None
    rating_distribution: dict[str, Any] | None
    complaint_themes: list[dict[str, Any]] | None
    positive_themes: list[dict[str, Any]] | None
    summarised_patterns: dict[str, Any] | None
    reviews_considered: int | None
    confidence: Confidence
    derivation_method: DerivationMethod
    insight_state: InsightState
    degraded_reason: str | None
    source_url: str
    fetched_at: datetime
    derived_at: datetime


@dataclass(frozen=True, slots=True)
class ListingInsightDraft:
    keyword_themes: list[dict[str, Any]] | None
    title_length: int | None
    title_structure: dict[str, Any] | None
    feature_categories: list[dict[str, Any]] | None
    benefit_term_patterns: list[dict[str, Any]] | None
    differentiation_opportunities: list[dict[str, Any]] | None
    bullet_count: int | None
    image_count: int | None
    confidence: Confidence
    derivation_method: DerivationMethod
    insight_state: InsightState
    source_url: str
    fetched_at: datetime
    derived_at: datetime


class DerivationEngine(Protocol):
    def derive_review_insight(self, *, source_url: str, now: datetime) -> ReviewInsightDraft: ...
    def derive_listing_insight(self, *, source_url: str, now: datetime) -> ListingInsightDraft: ...


class UnimplementedDerivationEngine:
    """See module docstring. Raises rather than fabricating sentiment/themes."""

    def derive_review_insight(self, *, source_url: str, now: datetime) -> ReviewInsightDraft:
        raise NotImplementedError(
            "No review-insight derivation implemented yet — needs a review-page acquisition "
            "strategy and a resolved local-model choice (spec §12, flagged unresolved)."
        )

    def derive_listing_insight(self, *, source_url: str, now: datetime) -> ListingInsightDraft:
        raise NotImplementedError(
            "No listing-insight derivation implemented yet — needs the same unresolved "
            "acquisition/model decisions as derive_review_insight."
        )
