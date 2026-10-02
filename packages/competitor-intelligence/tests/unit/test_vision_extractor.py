"""OllamaVisionExtractor — the real vision-extraction implementation, exercised with a fake
ImageStore and a fake OllamaClient so no test reaches a filesystem or a real model. Focused
on: only spec-backed fields are ever emitted, unit conversion (rupees -> paise) happens in
code not the model, and every failure mode degrades to ExtractionFailed rather than
fabricating a value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from competitor_intelligence.evidence.extraction import ExtractionFailed, ExtractionResult
from competitor_intelligence.evidence.image_store import ImageNotFound
from competitor_intelligence.evidence.ollama_client import OllamaUnavailable
from competitor_intelligence.evidence.vision_extractor import OllamaVisionExtractor


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
    calls: list[str] = field(default_factory=list)

    def generate(self, *, model: str, prompt: str, image_bytes: bytes) -> str:
        self.calls.append(model)
        key = image_bytes.decode()
        if key not in self.responses:
            raise OllamaUnavailable("no fixture registered")
        return self.responses[key]


def _extractor(images: dict[str, bytes], responses: dict[str, str]) -> tuple[OllamaVisionExtractor, _FakeOllama]:
    store = _FakeImageStore(images=images)
    ollama = _FakeOllama(responses=responses)
    return OllamaVisionExtractor(image_store=store, ollama=ollama, model="llava"), ollama


def _by_name(result: ExtractionResult) -> dict[str, object]:
    return {f.field_name: f.value for f in result.fields}


def test_extracts_price_and_availability_converting_rupees_to_paise() -> None:
    model_json = json.dumps({"listed_price": "999.00", "availability": "In stock"})
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})

    result = extractor.extract("img-1")

    assert isinstance(result, ExtractionResult)
    fields = _by_name(result)
    assert fields["listed_price_paise"] == 99900
    assert fields["availability"] == "IN_STOCK"


def test_extracts_title_bullets_and_rating() -> None:
    model_json = json.dumps(
        {"title": "Wireless Mouse", "bullets": ["2.4GHz", "Ergonomic"], "rating": "4.3", "rating_count": "1,234"}
    )
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})

    result = extractor.extract("img-1")

    fields = _by_name(result)
    assert fields["title"] == "Wireless Mouse"
    assert fields["bullets"] == ["2.4GHz", "Ergonomic"]
    assert fields["rating"] == "4.3"
    assert fields["rating_count"] == 1234


def test_never_emits_variant_key_field() -> None:
    """V7: variant-key derivation is an open production-validation blocker — this extractor
    must never guess at it, even if a model hallucinates one into its JSON."""
    model_json = json.dumps({"title": "X", "variant_key": "red-large"})
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})

    result = extractor.extract("img-1")

    assert "variant_key" not in _by_name(result)


def test_out_of_stock_text_variants_normalize_correctly() -> None:
    for text, expected in [
        ("Currently unavailable", "OUT_OF_STOCK"),
        ("Sold Out", "OUT_OF_STOCK"),
        ("In Stock", "IN_STOCK"),
        ("Add to Cart", "IN_STOCK"),
        ("Ships in 3 days", "UNKNOWN"),
    ]:
        model_json = json.dumps({"availability": text})
        extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})
        fields = _by_name(extractor.extract("img-1"))
        assert fields["availability"] == expected


def test_image_not_found_is_extraction_failed_not_an_exception() -> None:
    extractor, _ = _extractor({}, {})
    result = extractor.extract("missing-ref")
    assert isinstance(result, ExtractionFailed)


def test_ollama_unavailable_is_extraction_failed() -> None:
    extractor, _ = _extractor({"img-1": b"img-1"}, {})  # no response registered -> raises
    result = extractor.extract("img-1")
    assert isinstance(result, ExtractionFailed)


def test_unparseable_model_response_is_extraction_failed_never_fabricated() -> None:
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": "not json at all, sorry!"})
    result = extractor.extract("img-1")
    assert isinstance(result, ExtractionFailed)


def test_empty_json_object_is_extraction_failed() -> None:
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": "{}"})
    result = extractor.extract("img-1")
    assert isinstance(result, ExtractionFailed)


def test_invalid_price_string_is_omitted_not_fabricated() -> None:
    model_json = json.dumps({"title": "X", "listed_price": "call for price"})
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})
    fields = _by_name(extractor.extract("img-1"))
    assert "listed_price_paise" not in fields
    assert fields["title"] == "X"


@pytest.mark.parametrize("bad_price", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity"])
def test_non_finite_price_is_omitted_not_a_crash(bad_price: object) -> None:
    # json.dumps emits bare NaN/Infinity (which json.loads accepts), and Decimal("NaN") /
    # Decimal("Infinity") parse fine — but int() on them raises ValueError/OverflowError, which
    # extract() does not catch. An unreadable price must be omitted (never zero, never a crash).
    model_json = json.dumps({"title": "X", "listed_price": bad_price})
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})
    result = extractor.extract("img-1")
    assert isinstance(result, ExtractionResult)
    fields = _by_name(result)
    assert "listed_price_paise" not in fields
    assert fields["title"] == "X"


@pytest.mark.parametrize("bad_rating", [float("nan"), "NaN", "Infinity"])
def test_non_finite_rating_is_omitted_not_a_crash(bad_rating: object) -> None:
    # Decimal("NaN") < 0 raises InvalidOperation outside the parser's try block.
    model_json = json.dumps({"title": "X", "rating": bad_rating})
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})
    result = extractor.extract("img-1")
    assert isinstance(result, ExtractionResult)
    fields = _by_name(result)
    assert "rating" not in fields
    assert fields["title"] == "X"


def test_rating_out_of_range_is_omitted() -> None:
    model_json = json.dumps({"title": "X", "rating": "9.9"})
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})
    fields = _by_name(extractor.extract("img-1"))
    assert "rating" not in fields


def test_model_response_with_surrounding_prose_still_parses_json() -> None:
    model_json = "Sure, here is the JSON:\n" + json.dumps({"title": "X"}) + "\nHope that helps!"
    extractor, _ = _extractor({"img-1": b"img-1"}, {"img-1": model_json})
    fields = _by_name(extractor.extract("img-1"))
    assert fields["title"] == "X"
