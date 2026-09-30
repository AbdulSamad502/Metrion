"""review_insight/text_extraction.py — classification-only Ollama pass. All HTTP calls are
mocked; no live network call in this unit test."""

from __future__ import annotations

import httpx
import pytest

from product_intelligence.review_insight.text_extraction import (
    OllamaTextInsightExtractor,
    TextExtractionFailed,
    TextExtractionResult,
    UnimplementedTextInsightExtractor,
)


class _FakeResponse:
    def __init__(self, json_body: dict, status_code: int = 200) -> None:
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._json_body


def test_extract_returns_observations_for_valid_model_response(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {
        "response": '{"items": [{"sentiment": "POSITIVE", "themes": ["battery life"]}, '
        '{"sentiment": "NEGATIVE", "themes": ["build quality"]}]}'
    }
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(body))

    extractor = OllamaTextInsightExtractor(host="http://localhost:11434", model="llama3")
    result = extractor.extract(["great earbuds!", "case broke after a week"], insight_source_type="YOUTUBE_COMMENTARY")

    assert isinstance(result, TextExtractionResult)
    assert result.insight_source_type == "YOUTUBE_COMMENTARY"
    assert len(result.observations) == 2
    assert result.observations[0].sentiment == "POSITIVE"
    assert result.observations[0].themes == ("battery life",)


def test_extract_fails_on_unreachable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise)
    extractor = OllamaTextInsightExtractor(host="http://localhost:11434", model="llama3")
    result = extractor.extract(["some text"], insight_source_type="WEB_EDITORIAL")

    assert isinstance(result, TextExtractionFailed)
    assert "Ollama request failed" in result.reason


def test_extract_fails_on_unparseable_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse({"response": "not json at all"}))
    extractor = OllamaTextInsightExtractor(host="http://localhost:11434", model="llama3")
    result = extractor.extract(["some text"], insight_source_type="WEB_EDITORIAL")

    assert isinstance(result, TextExtractionFailed)
    assert "parseable" in result.reason


def test_extract_fails_when_no_texts_to_classify() -> None:
    extractor = OllamaTextInsightExtractor(host="http://localhost:11434", model="llama3")
    result = extractor.extract([], insight_source_type="WEB_EDITORIAL")
    assert isinstance(result, TextExtractionFailed)
    assert result.reason == "no texts to classify"


def test_extract_rejects_invalid_insight_source_type() -> None:
    extractor = OllamaTextInsightExtractor(host="http://localhost:11434", model="llama3")
    with pytest.raises(ValueError):
        extractor.extract(["text"], insight_source_type="MARKETPLACE_REVIEW")


def test_unimplemented_extractor_raises_not_a_silent_fabrication() -> None:
    extractor = UnimplementedTextInsightExtractor()
    with pytest.raises(NotImplementedError):
        extractor.extract(["text"], insight_source_type="WEB_EDITORIAL")


def test_extract_result_never_contains_the_raw_input_text(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_text = "this exact sentence must never be reproduced by the model wrapper"
    body = {"response": '{"items": [{"sentiment": "NEUTRAL", "themes": []}]}'}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(body))

    extractor = OllamaTextInsightExtractor(host="http://localhost:11434", model="llama3")
    result = extractor.extract([raw_text], insight_source_type="WEB_EDITORIAL")

    assert isinstance(result, TextExtractionResult)
    assert raw_text not in repr(result)
