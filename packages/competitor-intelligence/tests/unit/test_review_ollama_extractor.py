"""OllamaReviewVisionExtractor — fake ImageStore/OllamaClient only, same discipline as
test_vision_extractor.py."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from competitor_intelligence.evidence.image_store import ImageNotFound
from competitor_intelligence.evidence.ollama_client import OllamaUnavailable
from competitor_intelligence.review_insight.extraction import ReviewExtractionFailed, ReviewExtractionResult
from competitor_intelligence.review_insight.ollama_extractor import OllamaReviewVisionExtractor


@dataclass
class _FakeImageStore:
    images: dict[str, bytes] = field(default_factory=dict)

    def read(self, image_ref: str) -> bytes:
        if image_ref not in self.images:
            raise ImageNotFound(image_ref)
        return self.images[image_ref]


@dataclass
class _FakeOllama:
    responses: dict[str, str] = field(default_factory=dict)

    def generate(self, *, model: str, prompt: str, image_bytes: bytes) -> str:
        key = image_bytes.decode()
        if key not in self.responses:
            raise OllamaUnavailable("no fixture registered")
        return self.responses[key]


def _extractor(images: dict[str, bytes], responses: dict[str, str]) -> OllamaReviewVisionExtractor:
    return OllamaReviewVisionExtractor(image_store=_FakeImageStore(images), ollama=_FakeOllama(responses), model="llava")


def test_parses_reviews_and_rating_distribution() -> None:
    model_json = json.dumps(
        {
            "reviews": [
                {"sentiment": "POSITIVE", "themes": ["battery life"]},
                {"sentiment": "NEGATIVE", "themes": ["delivery"]},
            ],
            "rating_distribution": {"5": 10, "4": 2, "3": 1, "2": 0, "1": 1},
        }
    )
    extractor = _extractor({"img-1": b"img-1"}, {"img-1": model_json})

    result = extractor.extract("img-1")

    assert isinstance(result, ReviewExtractionResult)
    assert len(result.reviews) == 2
    assert result.reviews[0].sentiment == "POSITIVE"
    assert result.rating_distribution == {"5": 10, "4": 2, "3": 1, "2": 0, "1": 1}


def test_no_reviews_and_no_distribution_is_extraction_failed() -> None:
    extractor = _extractor({"img-1": b"img-1"}, {"img-1": json.dumps({"reviews": []})})
    result = extractor.extract("img-1")
    assert isinstance(result, ReviewExtractionFailed)


def test_invalid_sentiment_value_is_dropped_not_fabricated() -> None:
    model_json = json.dumps({"reviews": [{"sentiment": "MIXED", "themes": []}, {"sentiment": "POSITIVE", "themes": []}]})
    extractor = _extractor({"img-1": b"img-1"}, {"img-1": model_json})
    result = extractor.extract("img-1")
    assert isinstance(result, ReviewExtractionResult)
    assert len(result.reviews) == 1
    assert result.reviews[0].sentiment == "POSITIVE"


def test_image_not_found_is_extraction_failed() -> None:
    extractor = _extractor({}, {})
    result = extractor.extract("missing")
    assert isinstance(result, ReviewExtractionFailed)


def test_ollama_unavailable_is_extraction_failed() -> None:
    extractor = _extractor({"img-1": b"img-1"}, {})
    result = extractor.extract("img-1")
    assert isinstance(result, ReviewExtractionFailed)
