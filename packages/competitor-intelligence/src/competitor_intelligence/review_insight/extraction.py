"""Review-screenshot vision extraction — §6.5. A distinct extraction shape from
`evidence/extraction.py`'s listing-field extraction: a reviews-tab screenshot doesn't carry
structured fields like price/availability, it carries a set of individual reviews (each with
a sentiment/theme) plus, sometimes, the marketplace's own aggregate rating-distribution bar.

Per MN8 ("models classify, code computes"), this extractor's job stops at classification —
labelling what's visible with a sentiment class and theme tags per review. Turning those
labels into proportions, weighted themes, etc. is `aggregate.py`'s job, in plain
deterministic code, never here and never inside a prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

SENTIMENTS = ("POSITIVE", "NEGATIVE", "NEUTRAL")


@dataclass(frozen=True, slots=True)
class ReviewObservation:
    """One review visible in the screenshot, as the model classified it — never a
    reproduction of its text (C15/AC5b: no review-text corpus, no embeddings, nothing
    beyond a sentiment label and theme tags ever leaves this module)."""

    sentiment: str  # one of SENTIMENTS
    themes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewExtractionResult:
    reviews: tuple[ReviewObservation, ...]
    # The visible rating-distribution bar (e.g. {"5": 120, "4": 30, ...}), only when legible
    # in this screenshot — None when the screenshot doesn't show it at all (E12b).
    rating_distribution: Mapping[str, int] | None = None


@dataclass(frozen=True, slots=True)
class ReviewExtractionFailed:
    reason: str


class ReviewVisionExtractor(Protocol):
    def extract(self, image_ref: str) -> ReviewExtractionResult | ReviewExtractionFailed: ...


class UnimplementedReviewVisionExtractor:
    """Same honest-stub pattern as `evidence.extraction.UnimplementedVisionExtractor` — kept
    as the safe default for any composition root not yet configured with a real extractor,
    and for tests to inject a fake in its place."""

    def extract(self, image_ref: str) -> ReviewExtractionResult | ReviewExtractionFailed:
        raise NotImplementedError(
            "No review-screenshot vision extractor wired — inject a fake ReviewVisionExtractor "
            "for tests, or configure OllamaReviewVisionExtractor at the composition root."
        )
