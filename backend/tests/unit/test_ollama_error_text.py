"""Ollama failures reach sellers (PI `partialReason`, CI `PENDING_MANUAL_ENTRY` reason, CFO narration notes) and logs. They must say what happened in words: a missing model is
stated as "not installed" (issue 9: the vision workflow stays explicitly unavailable until its model is installed), and no URL or raw OS text (`[WinError 10061]`) is shown."""

from __future__ import annotations

import importlib
import inspect

import httpx
import pytest

HELPERS = (
    "backend.llm.ollama_errors",
    "cfo.reasoning.ollama_errors",
    "competitor_intelligence.evidence.ollama_errors",
    "product_intelligence.ollama_errors",
)


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://localhost:11434/api/generate")
    try:
        httpx.Response(code, request=request).raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError


def test_the_four_copies_are_identical():
    sources = {m: inspect.getsource(importlib.import_module(m)) for m in HELPERS}
    assert len(set(sources.values())) == 1


@pytest.mark.parametrize("module", HELPERS)
def test_descriptions(module):
    describe = importlib.import_module(module).describe_ollama_error
    assert describe(_status_error(404), "llava") == "the model 'llava' is not installed on the local model server"
    assert "HTTP 500" in describe(_status_error(500), "llava")
    assert "in time" in describe(httpx.ReadTimeout("t"), "llava")
    assert "could not be reached" in describe(httpx.ConnectError("[WinError 10061] No connection could be made"), "llava")
    for text in (describe(_status_error(404), "m"), describe(httpx.ConnectError("[WinError 10061] x"), "m")):
        assert "WinError" not in text and "localhost" not in text and "http" not in text.lower()
    assert describe(RuntimeError("secret"), "m") == "unexpected RuntimeError"


def test_the_vision_client_reports_a_missing_model_plainly(monkeypatch):
    from competitor_intelligence.evidence import ollama_client

    def post(*a, **k):
        resp = httpx.Response(404, request=httpx.Request("POST", "http://localhost:11434/api/generate"))
        resp.raise_for_status()

    monkeypatch.setattr(ollama_client.httpx, "post", post)
    with pytest.raises(ollama_client.OllamaUnavailable) as caught:
        ollama_client.HttpOllamaClient(host="http://localhost:11434", timeout_seconds=5).generate(model="qwen2.5vl-manual", prompt="p", image_bytes=b"x")
    assert str(caught.value) == "Ollama request failed: the model 'qwen2.5vl-manual' is not installed on the local model server"


def test_an_unreachable_server_never_shows_raw_os_text(monkeypatch):
    from cfo.reasoning import ollama_provider

    def post(*a, **k):
        raise httpx.ConnectError("[WinError 10061] No connection could be made because the target machine actively refused it")

    monkeypatch.setattr(ollama_provider.httpx, "post", post)
    with pytest.raises(ollama_provider.OllamaUnavailable) as caught:
        ollama_provider.OllamaLlmProvider(host="http://localhost:11434", timeout_seconds=5).complete(model="qwen3:8b", prompt="p")
    assert "WinError" not in str(caught.value) and "could not be reached" in str(caught.value)
