from __future__ import annotations

import httpx
import pytest

from competitor_intelligence.evidence.ollama_client import HttpOllamaClient, OllamaUnavailable


class _FakeResp:
    def __init__(self, data: dict[str, object], status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]

    def json(self) -> dict[str, object]:
        return self._data


def _capture_post(monkeypatch, response_data: dict[str, object]) -> dict[str, object]:
    seen: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> _FakeResp:
        seen.update(url=url, json=json, timeout=timeout)
        return _FakeResp(response_data)

    monkeypatch.setattr(httpx, "post", fake_post)
    return seen


def test_http_ollama_client_defaults_think_to_false(monkeypatch) -> None:
    seen = _capture_post(monkeypatch, {"response": '{"listed_price": "99.00"}'})
    client = HttpOllamaClient(host="http://localhost:11434")
    out = client.generate(model="qwen3.5:4b", prompt="read", image_bytes=b"raw-bytes")
    assert out == '{"listed_price": "99.00"}'
    assert seen["json"]["think"] is False
    assert "keep_alive" not in seen["json"]
    assert seen["timeout"] == 60.0


def test_http_ollama_client_configurable_think_and_keep_alive(monkeypatch) -> None:
    seen = _capture_post(monkeypatch, {"response": "{}"})
    client = HttpOllamaClient(host="http://localhost:11434", timeout_seconds=120.0, keep_alive="10m", think=True)
    client.generate(model="custom-model", prompt="read", image_bytes=b"raw-bytes")
    assert seen["json"]["think"] is True
    assert seen["json"]["keep_alive"] == "10m"
    assert seen["timeout"] == 120.0

    seen.clear()
    client_omit_think = HttpOllamaClient(host="http://localhost:11434", think=None)
    client_omit_think.generate(model="custom-model", prompt="read", image_bytes=b"raw-bytes")
    assert "think" not in seen["json"]


def test_http_ollama_client_strips_think_tags(monkeypatch) -> None:
    _capture_post(monkeypatch, {"response": "<think>\nThinking about price...\n</think>\n{\"listed_price\": \"99.00\"}"})
    client = HttpOllamaClient(host="http://localhost:11434")
    out = client.generate(model="qwen3.5:4b", prompt="read", image_bytes=b"raw-bytes")
    assert out == '{"listed_price": "99.00"}'


def test_http_ollama_client_raises_unavailable_on_failure(monkeypatch) -> None:
    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> _FakeResp:
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    client = HttpOllamaClient(host="http://localhost:11434")
    with pytest.raises(OllamaUnavailable, match="Ollama request failed"):
        client.generate(model="m", prompt="p", image_bytes=b"x")
