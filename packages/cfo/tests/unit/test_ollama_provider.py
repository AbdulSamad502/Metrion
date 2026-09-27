"""`OllamaLlmProvider.complete` — real HTTP call, stubbed at `httpx.post` (the same
monkeypatch-the-HTTP-boundary approach this codebase already uses at the client edge; no
live Ollama needed for this unit test). CFO end-to-end evaluation, 2026-09-27: qwen3:8b (a
"thinking" model) was found to leak a full `<think>...</think>` reasoning block before its
actual answer — this test proves `complete()` strips it before returning, per `narrate.py`'s
own contract that Brain 3's narration is prose, not the model's internal reasoning."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cfo.reasoning.ollama_provider import OllamaLlmProvider, OllamaUnavailable


@dataclass
class _FakeResponse:
    _json: dict[str, object]
    status_code: int = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, object]:
        return self._json


def test_complete_strips_a_think_block_before_the_real_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "<think>let me reason about this figure</think>\nThe Contribution Profit is ₹3,500.00."
    monkeypatch.setattr(
        "cfo.reasoning.ollama_provider.httpx.post",
        lambda *a, **k: _FakeResponse({"response": raw}),
    )
    result = OllamaLlmProvider().complete(model="qwen3:8b", prompt="irrelevant")
    assert result == "The Contribution Profit is ₹3,500.00."
    assert "<think>" not in result


def test_complete_passes_through_unchanged_when_there_is_no_think_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cfo.reasoning.ollama_provider.httpx.post",
        lambda *a, **k: _FakeResponse({"response": "The Contribution Profit is ₹3,500.00."}),
    )
    result = OllamaLlmProvider().complete(model="qwen3:8b", prompt="irrelevant")
    assert result == "The Contribution Profit is ₹3,500.00."


def test_complete_strips_a_multiline_think_block(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "<think>\nline one\nline two\n</think>\n\nFinal answer here."
    monkeypatch.setattr(
        "cfo.reasoning.ollama_provider.httpx.post",
        lambda *a, **k: _FakeResponse({"response": raw}),
    )
    result = OllamaLlmProvider().complete(model="qwen3:8b", prompt="irrelevant")
    assert result == "Final answer here."


def test_complete_raises_ollama_unavailable_when_response_field_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cfo.reasoning.ollama_provider.httpx.post",
        lambda *a, **k: _FakeResponse({}),
    )
    with pytest.raises(OllamaUnavailable):
        OllamaLlmProvider().complete(model="qwen3:8b", prompt="irrelevant")
