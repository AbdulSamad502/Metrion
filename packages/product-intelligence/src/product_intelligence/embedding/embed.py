"""Derived-attribute-only embeddings — PI build plan §2/D5/E12/C13. Embeds
`title_length`/`title_structure`/`keyword_themes` — **never raw `candidate_title` text** —
via `nomic-embed-text` through the local Ollama instance (`OLLAMA_HOST`, same convention as
`review_insight/text_extraction.py`). Used for near-duplicate candidate grouping (E12):
`candidate_synthesis.py`'s own grouping is a cheap keyword-overlap first pass at synthesis
time; this module's pgvector cosine-distance lookup is the second, more precise pass, run
after every candidate in a run already has an embedding.

`model_name`/`model_dim` travel with every embedding row (already enforced by
`product_embedding_repo.upsert_embedding`'s own contract) so a future model swap is a
detectable, scriptable re-index (E14), never silent corruption.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from product_intelligence.repositories import product_embedding_repo

MODEL_NAME = "nomic-embed-text"
MODEL_DIM = 768


class EmbeddingUnavailable(Exception):
    """The local Ollama model server could not be reached, timed out, returned a non-2xx
    response, or produced an embedding of the wrong dimension — never a reason to fabricate
    or silently truncate/pad a vector."""


class EmbeddingClient(Protocol):
    def embed(self, text: str) -> list[float]: ...


class OllamaEmbeddingClient:
    def __init__(self, *, host: str, model: str = MODEL_NAME, timeout_seconds: float = 30.0) -> None:
        self._host = host
        self._model = model
        self._timeout_seconds = timeout_seconds

    def embed(self, text: str) -> list[float]:
        import httpx

        try:
            response = httpx.post(
                f"{self._host}/api/embeddings",
                json={"model": self._model, "prompt": text},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(f"Ollama embeddings request failed: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            # Bug-hunt pass (2026-10-01): unlike every other HTTP client in this package
            # (tavily_client.py, youtube_client.py, google_places_client.py all guard
            # response.json()), this call had no guard at all — a malformed/non-JSON Ollama
            # response (truncated stream, a proxy's HTML error page) raised json.JSONDecodeError
            # uncaught, which isn't EmbeddingUnavailable, so pi_discover.py's per-candidate
            # handler didn't catch it and the whole run aborted with pi_research_run stuck at
            # RUNNING forever (before the top-level safety net existed there too).
            raise EmbeddingUnavailable(f"Ollama embeddings response was not valid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise EmbeddingUnavailable("Ollama embeddings response was not a JSON object")
        embedding = body.get("embedding")
        if not isinstance(embedding, list) or not all(isinstance(v, (int, float)) for v in embedding):
            raise EmbeddingUnavailable("Ollama embeddings response had no numeric 'embedding' list")
        return [float(v) for v in embedding]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embeds many texts in ONE `/api/embed` request. Measured on a CPU host: ~2.5 s fixed
        overhead per request, so 30 per-candidate requests cost 17.7 s even across 5 worker
        threads, vs 3.9 s for one batched request. Vectors are the same direction as the legacy
        `/api/embeddings` endpoint's (cosine similarity 1.000000) but L2-normalised; the only
        consumer is pgvector's cosine `<=>`, which is magnitude-invariant. Raises
        `EmbeddingUnavailable` on any failure or on a wrong count/shape — never partial results."""
        import httpx

        if not texts:
            return []
        try:
            response = httpx.post(
                f"{self._host}/api/embed",
                json={"model": self._model, "input": texts},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(f"Ollama batch embeddings request failed: {exc}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise EmbeddingUnavailable(f"Ollama batch embeddings response was not valid JSON: {exc}") from exc
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        if (
            not isinstance(vectors, list)
            or len(vectors) != len(texts)
            or not all(isinstance(v, list) and all(isinstance(x, (int, float)) for x in v) for v in vectors)
        ):
            raise EmbeddingUnavailable("Ollama batch embeddings response did not contain one numeric vector per input")
        return [[float(x) for x in v] for v in vectors]


def derived_attribute_text(
    *, title_length: int | None, title_structure: dict[str, Any] | None, keyword_themes: dict[str, Any] | None
) -> str:
    """The only text ever handed to the embedding model — composed entirely from derived
    attributes (D5), never a copy of `candidate_title`. Deterministic ordering so the same
    inputs always produce the same prompt text, which matters for embedding stability."""
    parts: list[str] = []
    if title_length is not None:
        parts.append(f"title_length:{title_length}")
    if title_structure:
        for key in sorted(title_structure):
            parts.append(f"title_structure.{key}:{title_structure[key]}")
    if keyword_themes:
        top_keywords = keyword_themes.get("top_keywords") if isinstance(keyword_themes, dict) else None
        if isinstance(top_keywords, list):
            parts.append("keywords:" + ",".join(str(k) for k in sorted(top_keywords)))
    return " ".join(parts) if parts else "no derived attributes available"


def embed_candidate(
    tenant_id: UUID,
    candidate_id: UUID,
    *,
    title_length: int | None,
    title_structure: dict[str, Any] | None,
    keyword_themes: dict[str, Any] | None,
    client: EmbeddingClient,
    now: datetime | None = None,
) -> UUID:
    """Embeds one candidate's derived attributes and persists it as `subject_type=CANDIDATE`.
    Raises `EmbeddingUnavailable` (never silently skips) if the model produces a vector whose
    length doesn't match `MODEL_DIM` — a caller may catch this and degrade the run rather than
    write a corrupt row."""
    text = derived_attribute_text(
        title_length=title_length, title_structure=title_structure, keyword_themes=keyword_themes
    )
    return store_candidate_embedding(tenant_id, candidate_id, client.embed(text), now=now)


def store_candidate_embedding(
    tenant_id: UUID, candidate_id: UUID, vector: list[float], *, now: datetime | None = None
) -> UUID:
    """Validates a candidate's vector's dimension and persists it — shared by the per-candidate
    path (`embed_candidate`) and the batched path, so both enforce the same contract."""
    now = now or datetime.now(timezone.utc)
    if len(vector) != MODEL_DIM:
        raise EmbeddingUnavailable(
            f"embedding model returned {len(vector)}-dim vector, expected {MODEL_DIM} for {MODEL_NAME}"
        )
    return product_embedding_repo.upsert_embedding(
        tenant_id,
        subject_type="CANDIDATE",
        subject_id=candidate_id,
        embedding=vector,
        model_name=MODEL_NAME,
        model_dim=MODEL_DIM,
        created_at=now,
    )


def find_near_duplicate_candidates(
    tenant_id: UUID, candidate_id: UUID, *, embedding: list[float], limit: int = 5
) -> list[dict[str, Any]]:
    """pgvector cosine-distance lookup (E12) — never compares across `model_name` values
    (E14), matching `product_embedding_repo.find_nearest`'s own documented contract."""
    neighbours = product_embedding_repo.find_nearest(
        tenant_id, subject_type="CANDIDATE", embedding=embedding, model_name=MODEL_NAME, limit=limit + 1
    )
    return [n for n in neighbours if n.get("subject_id") != candidate_id][:limit]
