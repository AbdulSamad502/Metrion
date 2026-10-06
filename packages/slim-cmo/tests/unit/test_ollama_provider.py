"""OllamaLlmProvider against a mock transport - no network, no model."""

from __future__ import annotations

import json

import httpx
import pytest

from slim_cmo.generation.provider import LlmUnavailable
from slim_cmo.providers.ollama import OllamaLlmProvider


def provider(handler, **kw):
    return OllamaLlmProvider(host="http://ollama.test", timeout_seconds=5, transport=httpx.MockTransport(handler), **kw)


def test_posts_text_only_and_returns_the_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": '  {"titles": []}  '})

    out = provider(handler).complete(model="m", prompt="hello")
    assert out == '{"titles": []}'
    assert seen["url"] == "http://ollama.test/api/generate"
    assert seen["body"] == {"model": "m", "prompt": "hello", "stream": False}  # no image/option fields


@pytest.mark.parametrize("think", [False, True])
def test_think_flag_is_sent_only_when_set(think):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "x"})

    provider(handler, think=think).complete(model="m", prompt="p")
    assert seen["body"]["think"] is think


def test_think_blocks_are_stripped_but_an_unclosed_one_is_left_alone():
    ok = provider(lambda r: httpx.Response(200, json={"response": "<think>plan\nmore</think>\n{\"a\": 1}"}))
    assert ok.complete(model="m", prompt="p") == '{"a": 1}'
    cut = provider(lambda r: httpx.Response(200, json={"response": "<think>never closed {"}))
    assert cut.complete(model="m", prompt="p").startswith("<think>")


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(500, json={}),
    lambda r: httpx.Response(200, json={"nope": 1}),
    lambda r: httpx.Response(200, json=["list"]),
    lambda r: httpx.Response(200, content=b"not json"),
    lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("slow")),
])
def test_every_failure_is_llm_unavailable_never_fabricated_text(handler):
    with pytest.raises(LlmUnavailable):
        provider(handler).complete(model="m", prompt="p")


@pytest.mark.parametrize("kw", [{"host": " ", "timeout_seconds": 5}, {"host": "h", "timeout_seconds": 0},
                                {"host": "h", "timeout_seconds": True}, {"host": "h", "timeout_seconds": 2.5}])
def test_host_and_timeout_are_required_and_validated_never_defaulted(kw):
    with pytest.raises(ValueError):
        OllamaLlmProvider(**kw)
    with pytest.raises(TypeError):
        OllamaLlmProvider()  # type: ignore[call-arg]
