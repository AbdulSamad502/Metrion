"""embedding/embed.py — derived-attribute-only text composition, embedding write path
(repo monkeypatched, no live Postgres), near-duplicate lookup exclusion."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from product_intelligence.embedding.embed import (
    MODEL_DIM,
    MODEL_NAME,
    EmbeddingUnavailable,
    OllamaEmbeddingClient,
    derived_attribute_text,
    embed_candidate,
    find_near_duplicate_candidates,
)
from product_intelligence.repositories import product_embedding_repo


class _FakeResponse:
    def __init__(self, *, json_body=None, json_error: Exception | None = None, status_code: int = 200) -> None:
        self._json_body = json_body
        self._json_error = json_error
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)  # type: ignore[arg-type]

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_body


def test_ollama_embedding_client_raises_embedding_unavailable_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug-hunt regression (2026-10-01): unlike every other HTTP client in this package,
    `OllamaEmbeddingClient.embed()` had no guard around `response.json()` at all — a
    malformed/non-JSON Ollama response raised `json.JSONDecodeError` uncaught, which wasn't
    `EmbeddingUnavailable`, so the per-candidate handler in `pi_discover.py` didn't catch it
    and the whole discovery run aborted."""
    monkeypatch.setattr(
        httpx, "post", lambda *a, **kw: _FakeResponse(json_error=ValueError("Expecting value: line 1 column 1"))
    )
    client = OllamaEmbeddingClient(host="http://localhost:11434")

    with pytest.raises(EmbeddingUnavailable):
        client.embed("some text")


def test_ollama_embedding_client_raises_embedding_unavailable_when_body_is_not_an_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(json_body=["not", "an", "object"]))
    client = OllamaEmbeddingClient(host="http://localhost:11434")

    with pytest.raises(EmbeddingUnavailable):
        client.embed("some text")

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
_TENANT_ID = uuid4()
_CANDIDATE_ID = uuid4()


class _FakeEmbeddingClient:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    def embed(self, text: str) -> list[float]:
        return self._vector


def test_derived_attribute_text_never_includes_candidate_title() -> None:
    text = derived_attribute_text(
        title_length=42,
        title_structure={"word_count": 5},
        keyword_themes={"top_keywords": ["earbuds", "wireless"]},
    )
    assert "candidate_title" not in text
    assert "title_length:42" in text
    assert "earbuds" in text and "wireless" in text


def test_derived_attribute_text_deterministic_for_same_inputs() -> None:
    kwargs = dict(
        title_length=10, title_structure={"b": 2, "a": 1}, keyword_themes={"top_keywords": ["z", "a"]}
    )
    assert derived_attribute_text(**kwargs) == derived_attribute_text(**kwargs)


def test_derived_attribute_text_fallback_when_nothing_available() -> None:
    text = derived_attribute_text(title_length=None, title_structure=None, keyword_themes=None)
    assert text == "no derived attributes available"


def test_embed_candidate_persists_via_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _fake_upsert(tenant_id, **kwargs):
        captured.update(kwargs)
        return uuid4()

    monkeypatch.setattr(product_embedding_repo, "upsert_embedding", _fake_upsert)

    client = _FakeEmbeddingClient([0.1] * MODEL_DIM)
    embed_candidate(
        _TENANT_ID,
        _CANDIDATE_ID,
        title_length=5,
        title_structure={},
        keyword_themes={},
        client=client,
        now=_NOW,
    )

    assert captured["subject_type"] == "CANDIDATE"
    assert captured["model_name"] == MODEL_NAME
    assert captured["model_dim"] == MODEL_DIM
    assert len(captured["embedding"]) == MODEL_DIM


def test_embed_candidate_raises_on_dimension_mismatch_never_pads_or_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(product_embedding_repo, "upsert_embedding", lambda tenant_id, **kw: uuid4())
    client = _FakeEmbeddingClient([0.1] * (MODEL_DIM - 1))

    with pytest.raises(EmbeddingUnavailable):
        embed_candidate(
            _TENANT_ID, _CANDIDATE_ID, title_length=5, title_structure={}, keyword_themes={}, client=client, now=_NOW
        )


def test_find_near_duplicate_candidates_excludes_self(monkeypatch: pytest.MonkeyPatch) -> None:
    # `find_nearest`'s real (SQLAlchemy/psycopg) return shape carries `subject_id` as a UUID
    # object, matching the uuid column type — the fake below must match that, not a str, or
    # this test would pass for the wrong reason (str != UUID always True).
    other_id = uuid4()
    monkeypatch.setattr(
        product_embedding_repo,
        "find_nearest",
        lambda tenant_id, **kw: [
            {"subject_id": _CANDIDATE_ID, "distance": 0.0},
            {"subject_id": other_id, "distance": 0.1},
        ],
    )

    neighbours = find_near_duplicate_candidates(_TENANT_ID, _CANDIDATE_ID, embedding=[0.1] * MODEL_DIM, limit=5)

    assert all(n["subject_id"] != _CANDIDATE_ID for n in neighbours)
    assert len(neighbours) == 1
