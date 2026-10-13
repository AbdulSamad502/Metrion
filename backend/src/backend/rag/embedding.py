"""`EmbeddingProvider`: text in, vectors out (rag-knowledge.md §1, §8.4). A pure function of text; no vector is ever shown to the seller and none is a figure source.

Backend-owned on purpose: a port of the batched Ollama client in `product_intelligence.embedding.embed` (not an import of it), because that module is PI's derived-attribute-only
pipeline (PI C13) and PI must not gain a RAG dependency, nor RAG a PI one. Differences from the PI client: the model is a registered (name, dimension) pair, every vector is validated
(count, dimension, finite) before it is returned, there is one bounded retry, and a failure is always `EmbeddingUnavailable` - never a partial result, a truncated vector or a padded one.

Self-hosted only (owner decision Q5): the host is a local/self-managed Ollama; no hosted provider is registered.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

# The registered (model -> dimension) pairs. The database CHECK `rag_embedding_model_check` and the per-model partial HNSW indexes mirror this table exactly; adding a model is a
# migration (registry entry + index) plus an entry here, never a config-only change (readiness review 2.13).
KNOWN_MODELS: Mapping[str, int] = {"nomic-embed-text": 768, "bge-m3": 1024}


class EmbeddingUnavailable(Exception):
    """The embedding model could not be reached, timed out, answered non-2xx / malformed, or produced a vector of the wrong count, dimension or with a non-finite value."""


class UnknownEmbeddingModel(ValueError):
    pass


def model_dim(model_name: str) -> int:
    try:
        return KNOWN_MODELS[model_name]
    except KeyError:
        raise UnknownEmbeddingModel(f"{model_name!r} is not a registered embedding model (known: {sorted(KNOWN_MODELS)})") from None


class EmbeddingProvider(Protocol):
    model_name: str
    model_dim: int

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


def validate_vectors(vectors: Any, *, count: int, dim: int, model: str) -> list[list[float]]:
    """Exactly `count` finite vectors of exactly `dim` numbers, else `EmbeddingUnavailable`. Never truncates, pads or repairs."""
    if not isinstance(vectors, list) or len(vectors) != count:
        raise EmbeddingUnavailable(f"{model}: expected {count} vectors, got {len(vectors) if isinstance(vectors, list) else type(vectors).__name__}")
    out: list[list[float]] = []
    for vec in vectors:
        if not isinstance(vec, list) or len(vec) != dim or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in vec):
            raise EmbeddingUnavailable(f"{model}: a vector was not {dim} numbers")
        floats = [float(x) for x in vec]
        if not all(math.isfinite(x) for x in floats):
            raise EmbeddingUnavailable(f"{model}: a vector held a non-finite value")
        out.append(floats)
    return out


@dataclass(slots=True)
class OllamaEmbeddingProvider:
    """Batched `/api/embed` against a self-hosted Ollama. One bounded retry (connect/timeout/5xx only); the timeout is per request."""

    model_name: str
    host: str
    timeout_seconds: float = 3.0
    retries: int = 1
    model_dim: int = 0

    def __post_init__(self) -> None:
        self.model_dim = model_dim(self.model_name)
        self.host = self.host.rstrip("/")

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        import httpx

        if not texts:
            return []
        last: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                response = httpx.post(f"{self.host}/api/embed", json={"model": self.model_name, "input": list(texts)}, timeout=self.timeout_seconds)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError("server error", request=response.request, response=response)
                response.raise_for_status()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    break  # a client error will not improve on retry
                continue
            try:
                body = response.json()
            except ValueError as exc:
                raise EmbeddingUnavailable(f"{self.model_name}: response was not valid JSON") from exc
            vectors = body.get("embeddings") if isinstance(body, dict) else None
            return validate_vectors(vectors, count=len(texts), dim=self.model_dim, model=self.model_name)
        raise EmbeddingUnavailable(f"{self.model_name}: embedding request failed: {type(last).__name__}") from last


@dataclass(slots=True)
class HashEmbeddingProvider:
    """DETERMINISTIC TEST DOUBLE, NOT A SEMANTIC MODEL: a stable pseudo-vector derived from a SHA-256 of the text, unit length, of the registered dimension. Identical text gives an
    identical vector and different text a different one, so storage / isolation / index mechanics are testable offline; it says nothing about retrieval quality and must never
    be used to report one."""

    model_name: str = "nomic-embed-text"
    model_dim: int = 0

    def __post_init__(self) -> None:
        self.model_dim = model_dim(self.model_name)

    def embed(self, text: str) -> list[float]:
        raw: list[float] = []
        counter = 0
        while len(raw) < self.model_dim:
            digest = hashlib.sha256(f"{self.model_name}\x00{counter}\x00{text}".encode()).digest()
            raw.extend(v / 2**31 - 1.0 for v in struct.unpack("<8i", digest))
            counter += 1
        raw = raw[: self.model_dim]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def build_provider(model_name: str, host: str, *, timeout_seconds: float) -> EmbeddingProvider:
    """The configured provider. Only Ollama (self-hosted) exists; there is deliberately no hosted branch."""
    return OllamaEmbeddingProvider(model_name=model_name, host=host, timeout_seconds=timeout_seconds)
