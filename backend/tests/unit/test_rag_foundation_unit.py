"""R1 unit tests (rag-knowledge.md section 5.9, 6.1, 8.4, 9): the embedding provider contract, the collection grid, the permission key and the config defaults. No database."""

from __future__ import annotations

import math

import httpx
import pytest

from backend import config
from backend.auth import permissions
from backend.rag import grid
from backend.rag.embedding import (
    KNOWN_MODELS, EmbeddingUnavailable, HashEmbeddingProvider, OllamaEmbeddingProvider, UnknownEmbeddingModel, build_provider, model_dim, validate_vectors,
)


def _response(status: int, payload) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "http://x/api/embed"))


def _vecs(n: int, dim: int) -> list[list[float]]:
    return [[0.01 * (i + 1)] * dim for i in range(n)]


# ---- registry / validation ------------------------------------------------------------------------------------------------------------------------------------------
def test_registry_pairs_are_the_two_candidates():
    assert dict(KNOWN_MODELS) == {"nomic-embed-text": 768, "bge-m3": 1024}
    assert model_dim("bge-m3") == 1024
    with pytest.raises(UnknownEmbeddingModel):
        model_dim("text-embedding-3-large")  # no hosted model is registered


@pytest.mark.parametrize(
    "vectors, count",
    [
        ([[0.1] * 767], 1),  # short
        ([[0.1] * 769], 1),  # long: never truncated
        ([[0.1] * 768, [0.1] * 768], 1),  # too many
        ([], 1),  # none
        ([[float("nan")] + [0.1] * 767], 1),
        ([[float("inf")] + [0.1] * 767], 1),
        ([["a"] * 768], 1),
        ([[True] * 768], 1),
        ("not-a-list", 1),
    ],
)
def test_validate_vectors_refuses_anything_not_exactly_right(vectors, count):
    with pytest.raises(EmbeddingUnavailable):
        validate_vectors(vectors, count=count, dim=768, model="nomic-embed-text")


def test_validate_vectors_accepts_exact_input():
    out = validate_vectors(_vecs(2, 768), count=2, dim=768, model="nomic-embed-text")
    assert len(out) == 2 and all(len(v) == 768 for v in out)


# ---- Ollama provider ------------------------------------------------------------------------------------------------------------------------------------------------
def test_ollama_provider_batches_one_request_and_returns_exact_dimension(monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append((url, json, timeout))
        return _response(200, {"embeddings": _vecs(len(json["input"]), 1024)})

    monkeypatch.setattr(httpx, "post", post)
    provider = OllamaEmbeddingProvider(model_name="bge-m3", host="http://ollama:11434/", timeout_seconds=2.5)
    vectors = provider.embed_many(["a", "b", "c"])
    assert len(calls) == 1 and calls[0][0] == "http://ollama:11434/api/embed" and calls[0][2] == 2.5
    assert calls[0][1] == {"model": "bge-m3", "input": ["a", "b", "c"]}
    assert len(vectors) == 3 and all(len(v) == 1024 for v in vectors)
    assert provider.model_dim == 1024


def test_ollama_provider_wrong_dimension_is_unavailable_not_repaired(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: _response(200, {"embeddings": _vecs(1, 768)}))
    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbeddingProvider(model_name="bge-m3", host="http://h").embed("x")  # a 768-dim answer for a 1024-dim model


def test_ollama_provider_retries_once_on_timeout_then_gives_up(monkeypatch):
    attempts = []

    def post(url, json, timeout):
        attempts.append(1)
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbeddingProvider(model_name="nomic-embed-text", host="http://h").embed("x")
    assert len(attempts) == 2  # one try + one bounded retry


def test_ollama_provider_recovers_when_the_retry_succeeds(monkeypatch):
    state = {"n": 0}

    def post(url, json, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("down")
        return _response(200, {"embeddings": _vecs(1, 768)})

    monkeypatch.setattr(httpx, "post", post)
    assert len(OllamaEmbeddingProvider(model_name="nomic-embed-text", host="http://h").embed("x")) == 768


def test_ollama_provider_does_not_retry_a_client_error(monkeypatch):
    attempts = []

    def post(url, json, timeout):
        attempts.append(1)
        return _response(404, {"error": "model not found"})

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbeddingProvider(model_name="nomic-embed-text", host="http://h").embed("x")
    assert len(attempts) == 1


def test_ollama_provider_5xx_retries_and_malformed_body_is_unavailable(monkeypatch):
    attempts = []

    def post(url, json, timeout):
        attempts.append(1)
        return _response(503, {"error": "busy"})

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbeddingProvider(model_name="nomic-embed-text", host="http://h").embed("x")
    assert len(attempts) == 2

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: httpx.Response(200, content=b"<html>proxy error</html>", request=httpx.Request("POST", "http://h")))
    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbeddingProvider(model_name="nomic-embed-text", host="http://h").embed("x")
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: _response(200, ["not", "an", "object"]))
    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbeddingProvider(model_name="nomic-embed-text", host="http://h").embed("x")


def test_empty_batch_makes_no_request(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no request for an empty batch"))
    assert OllamaEmbeddingProvider(model_name="nomic-embed-text", host="http://h").embed_many([]) == []


def test_unregistered_model_cannot_build_a_provider():
    with pytest.raises(UnknownEmbeddingModel):
        build_provider("some-hosted-model", "http://h", timeout_seconds=1)


# ---- deterministic test double --------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("model", ["nomic-embed-text", "bge-m3"])
def test_hash_provider_is_deterministic_unit_length_and_the_right_dimension(model):
    p = HashEmbeddingProvider(model_name=model)
    a, b, c = p.embed("supplier quote"), p.embed("supplier quote"), p.embed("brand guide")
    assert a == b and a != c
    assert len(a) == KNOWN_MODELS[model]
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)
    assert p.embed_many(["x", "y"]) == [p.embed("x"), p.embed("y")]


# ---- collection grid (AC14) -----------------------------------------------------------------------------------------------------------------------------------------
def test_grid_matches_spec_6_1():
    assert grid.GRID["CEO"] == {"SELLER_DOCUMENT", "APPROVED_FINDING", "APPROVED_MEMORY"}
    assert grid.GRID["CMO"] == {"SELLER_DOCUMENT", "APPROVED_MEMORY"}
    assert grid.GRID["CI"] == {"APPROVED_FINDING"}  # CI: derived findings only, never documents or anything raw
    assert "GLOBAL_REFERENCE" not in grid.GRID["CEO"] and "GLOBAL_REFERENCE" in grid.GRID["CFO"]
    assert set(grid.GRID) == set(grid.AGENTS)


def test_grid_refuses_anything_outside_a_row_and_never_narrows_silently():
    assert grid.permitted("CEO", ["SELLER_DOCUMENT", "APPROVED_FINDING"]) == ("SELLER_DOCUMENT", "APPROVED_FINDING")
    with pytest.raises(grid.CollectionNotPermitted):
        grid.permitted("CI", ["SELLER_DOCUMENT"])
    with pytest.raises(grid.CollectionNotPermitted):
        grid.permitted("CEO", ["SELLER_DOCUMENT", "GLOBAL_REFERENCE"])  # partly permitted is refused, not trimmed
    with pytest.raises(grid.CollectionNotPermitted):
        grid.permitted("NOT_AN_AGENT", ["SELLER_DOCUMENT"])
    with pytest.raises(grid.CollectionNotPermitted):
        grid.permitted("CEO", [])


# ---- permission key (owner decision Q7) ------------------------------------------------------------------------------------------------------------------------------
def test_knowledge_manage_is_owner_implicit_and_partner_deny_by_default():
    key = permissions.KNOWLEDGE_MANAGE
    assert key == "knowledge.manage" and key in permissions.ALL_KEYS
    assert permissions.has_permission(role=permissions.OWNER_ROLE, permissions={}, key=key)
    assert not permissions.has_permission(role=permissions.PARTNER_ROLE, permissions={}, key=key)
    assert not permissions.has_permission(role=permissions.PARTNER_ROLE, permissions={"files.upload": True, "team.manage": True}, key=key)  # nothing implies it
    assert permissions.has_permission(role=permissions.PARTNER_ROLE, permissions={key: True}, key=key)


# ---- configuration (owner decisions Q5, Q7) -------------------------------------------------------------------------------------------------------------------------
def test_rag_config_defaults_and_overrides(monkeypatch):
    for fn in (config.rag_embedding_model, config.rag_ollama_host, config.rag_embed_timeout_seconds, config.rag_max_document_bytes, config.rag_max_documents_per_tenant):
        fn.cache_clear()
    for name in ("RAG_EMBEDDING_MODEL", "RAG_OLLAMA_HOST", "RAG_EMBED_TIMEOUT_SECONDS", "RAG_MAX_DOCUMENT_BYTES", "RAG_MAX_DOCUMENTS_PER_TENANT", "OLLAMA_HOST"):
        monkeypatch.delenv(name, raising=False)
    config.ollama_host.cache_clear()
    assert config.rag_embedding_model() == "nomic-embed-text"
    assert config.rag_ollama_host() == "http://localhost:11434"
    assert config.rag_embed_timeout_seconds() == 3.0
    assert config.rag_max_document_bytes() == 10 * 1024 * 1024
    assert config.rag_max_documents_per_tenant() == 50
    monkeypatch.setenv("RAG_MAX_DOCUMENTS_PER_TENANT", "7")
    config.rag_max_documents_per_tenant.cache_clear()
    assert config.rag_max_documents_per_tenant() == 7
    for fn in (config.rag_embedding_model, config.rag_ollama_host, config.rag_embed_timeout_seconds, config.rag_max_document_bytes, config.rag_max_documents_per_tenant, config.ollama_host):
        fn.cache_clear()
