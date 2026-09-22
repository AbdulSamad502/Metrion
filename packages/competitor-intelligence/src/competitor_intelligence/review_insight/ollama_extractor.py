"""The real review-screenshot extractor — replaces `UnimplementedReviewVisionExtractor` at
the composition root. Reuses `evidence.image_store`/`evidence.ollama_client` (the same
local-only seam listing extraction uses) rather than a second implementation of either.

Model output boundary (MN8, §6.5): the prompt below asks for classification only — a
sentiment label and short theme tags per review, plus the rating-distribution bar if
visible. It never asks the model to compute a proportion, a percentage or a count across
reviews; `review_insight/aggregate.py` does that in plain code from the labels this module
returns.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from competitor_intelligence.evidence.image_store import ImageNotFound, ImageStore
from competitor_intelligence.evidence.ollama_client import OllamaClient, OllamaUnavailable
from competitor_intelligence.review_insight.extraction import (
    SENTIMENTS,
    ReviewExtractionFailed,
    ReviewExtractionResult,
    ReviewObservation,
)

_PROMPT = """You are reading a single screenshot of a product reviews page from an Indian \
e-commerce marketplace. For EACH individual customer review visible in this screenshot \
(ignore the product listing itself, only look at reviews), classify it — do not quote or \
reproduce the review's text.

Respond with ONLY a single JSON object (no other text):

{
  "reviews": [
    {"sentiment": "POSITIVE" | "NEGATIVE" | "NEUTRAL", "themes": ["short-theme-tag", ...]}
  ],
  "rating_distribution": {"5": <count>, "4": <count>, "3": <count>, "2": <count>, "1": <count>}
}

Only include "rating_distribution" if the page shows a star-rating breakdown bar/chart — \
omit it entirely if not visible. Theme tags must be short (1-3 words), lowercase, generic \
categories like "battery life", "build quality", "delivery", "price" — never a direct quote \
from any review. If no reviews are legible in this screenshot, return {"reviews": []}."""


def _extract_json_object(text: str) -> dict[str, object] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_reviews(raw: object) -> tuple[ReviewObservation, ...]:
    if not isinstance(raw, list):
        return ()
    observations: list[ReviewObservation] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        sentiment = str(entry.get("sentiment", "")).strip().upper()
        if sentiment not in SENTIMENTS:
            continue
        themes_raw = entry.get("themes", [])
        themes = tuple(
            t.strip().lower() for t in themes_raw if isinstance(t, str) and t.strip()
        ) if isinstance(themes_raw, list) else ()
        observations.append(ReviewObservation(sentiment=sentiment, themes=themes))
    return tuple(observations)


def _parse_rating_distribution(raw: object) -> dict[str, int] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    result: dict[str, int] = {}
    for star in ("1", "2", "3", "4", "5"):
        value = raw.get(star)
        if value is None:
            continue
        try:
            result[star] = int(re.sub(r"[^\d]", "", str(value)) or "0")
        except ValueError:
            continue
    return result or None


@dataclass(frozen=True, slots=True)
class OllamaReviewVisionExtractor:
    image_store: ImageStore
    ollama: OllamaClient
    model: str

    def extract(self, image_ref: str) -> ReviewExtractionResult | ReviewExtractionFailed:
        try:
            image_bytes = self.image_store.read(image_ref)
        except ImageNotFound as exc:
            return ReviewExtractionFailed(reason=str(exc))

        try:
            raw = self.ollama.generate(model=self.model, prompt=_PROMPT, image_bytes=image_bytes)
        except OllamaUnavailable as exc:
            return ReviewExtractionFailed(reason=str(exc))

        parsed = _extract_json_object(raw)
        if parsed is None:
            return ReviewExtractionFailed(reason="model response did not contain a parseable JSON object")

        reviews = _parse_reviews(parsed.get("reviews"))
        rating_distribution = _parse_rating_distribution(parsed.get("rating_distribution"))
        if not reviews and rating_distribution is None:
            return ReviewExtractionFailed(reason="model reported no reviews and no rating distribution")
        return ReviewExtractionResult(reviews=reviews, rating_distribution=rating_distribution)
