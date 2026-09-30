"""discovery/product_extraction.py — extraction-only local Ollama pass. All HTTP calls are
mocked; no live network call in this unit test. Verifies the extraction contract: empty list
on no mention (a normal outcome, never an error), a plain list of strings on a real mention,
`ProductExtractionUnavailable` on failure, and that the output never contains a number of any
kind (CLAUDE.md's hard rule — models classify/extract, never compute)."""

from __future__ import annotations

import httpx
import pytest

from product_intelligence.discovery.product_extraction import (
    OllamaProductExtractionClient,
    ProductExtractionUnavailable,
    UnimplementedProductExtractionClient,
    extract_product_mentions,
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


def test_extract_products_returns_list_of_strings_when_products_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"response": '{"products": ["Nike Pegasus 41", "Asics Novablast 4"]}'}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(body))

    client = OllamaProductExtractionClient(host="http://localhost:11434", model="qwen3:8b")
    result = client.extract_products("some roundup article content", category_text="running shoes")

    assert result == ["Nike Pegasus 41", "Asics Novablast 4"]
    for entry in result:
        assert isinstance(entry, str)


def test_extract_products_returns_empty_list_when_nothing_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal, expected outcome (module docstring) — e.g. a Reddit discussion thread with
    no specific product mentioned. Never an error, never worked around."""
    body = {"response": '{"products": []}'}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(body))

    client = OllamaProductExtractionClient(host="http://localhost:11434", model="qwen3:8b")
    result = client.extract_products(
        "people were just discussing whether running is good for you in general, no specific "
        "shoe or brand was mentioned anywhere in this thread",
        category_text="running shoes",
    )

    assert result == []


def test_extract_product_mentions_never_invents_a_product_not_in_the_fake_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies the wrapper never adds anything beyond what the (fake) model actually
    returned — no fabrication anywhere in this module's own code path."""
    body = {"response": '{"products": []}'}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(body))

    client = OllamaProductExtractionClient(host="http://localhost:11434", model="qwen3:8b")
    result = extract_product_mentions(
        "generic discussion with no product literally named", category_text="running shoes", client=client
    )

    assert result == []


def test_extract_products_output_never_contains_a_number_score_or_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard rule (CLAUDE.md): the model classifies/extracts, it never computes or scores.
    Verifies the parsed output is a plain list of strings only — no numeric entries, no dict
    entries carrying a score/rank field could ever survive `_parse_products`."""
    body = {
        "response": '{"products": ["Nike Pegasus 41", 42, {"name": "Asics Novablast 4", "rank": 1}, null]}'
    }
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(body))

    client = OllamaProductExtractionClient(host="http://localhost:11434", model="qwen3:8b")
    result = client.extract_products("text", category_text="running shoes")

    assert result == ["Nike Pegasus 41"]
    for entry in result:
        assert isinstance(entry, str)
        assert not isinstance(entry, (int, float))


def test_extract_products_raises_unavailable_on_unreachable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise)
    client = OllamaProductExtractionClient(host="http://localhost:11434", model="qwen3:8b")

    with pytest.raises(ProductExtractionUnavailable, match="Ollama request failed"):
        client.extract_products("some text", category_text="running shoes")


def test_extract_products_raises_unavailable_on_unparseable_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse({"response": "not json at all"}))
    client = OllamaProductExtractionClient(host="http://localhost:11434", model="qwen3:8b")

    with pytest.raises(ProductExtractionUnavailable, match="parseable"):
        client.extract_products("some text", category_text="running shoes")


def test_extract_products_returns_empty_list_for_blank_text_without_calling_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(*a, **kw):
        raise AssertionError("must not call Ollama for blank text")

    monkeypatch.setattr(httpx, "post", _fail)
    client = OllamaProductExtractionClient(host="http://localhost:11434", model="qwen3:8b")

    assert client.extract_products("   ", category_text="running shoes") == []


def test_extract_product_mentions_returns_empty_list_for_blank_text_without_calling_client() -> None:
    class _FailingClient:
        def extract_products(self, text: str, *, category_text: str) -> list[str]:
            raise AssertionError("must not call client for blank text")

    assert extract_product_mentions("", category_text="running shoes", client=_FailingClient()) == []  # type: ignore[arg-type]


def test_unimplemented_client_raises_not_a_silent_fabrication() -> None:
    client = UnimplementedProductExtractionClient()
    with pytest.raises(NotImplementedError):
        client.extract_products("text", category_text="running shoes")
