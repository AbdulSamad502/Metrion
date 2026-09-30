"""Environment configuration. No secret ever has a default — a missing value fails at
startup, not at first use, so a misconfigured deployment can't silently run unauthenticated
or unscoped."""

from __future__ import annotations

import os
from functools import lru_cache


class MissingConfig(RuntimeError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is not set. See .env.example.")


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfig(name)
    return value


@lru_cache
def clerk_secret_key() -> str:
    return _required("CLERK_SECRET_KEY")


@lru_cache
def clerk_webhook_secret() -> str:
    return _required("CLERK_WEBHOOK_SECRET")


@lru_cache
def clerk_jwt_key() -> str:
    """The instance's PEM public key (Dashboard -> API Keys -> JWKS, or `clerk api /jwks`)
    for networkless JWT verification. Without this, `authenticate_request()` performs a
    live JWKS network fetch on every call with no bounded timeout — observed to hang
    indefinitely in this environment. `\\n`-escaped in .env; unescaped here."""
    return _required("CLERK_JWT_KEY").replace("\\n", "\n")


@lru_cache
def frontend_origin() -> str:
    return os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")


@lru_cache
def cfo_report_storage_dir() -> str:
    """Local-disk storage for seller-uploaded marketplace report files (cfo-agent.md §6.16) —
    same functional-only, real-object-storage-is-later posture as `ci_evidence_storage_dir`."""
    return os.environ.get("CFO_REPORT_DIR", "./data/cfo-reports")


@lru_cache
def ci_evidence_storage_dir() -> str:
    """Local-disk storage for seller-uploaded evidence screenshots (Step 4, functional-only
    — not a secret, so a default is fine here unlike everything else in this file). Real
    object storage (S3-equivalent) is a later concern; this just needs to work for now."""
    return os.environ.get("CI_EVIDENCE_DIR", "./data/ci-evidence")


@lru_cache
def ollama_host() -> str:
    """C15 (local-only derivation): always a local address, never a hosted provider — not a
    secret, so a default is fine. `OLLAMA_HOST` overrides for a non-default local port."""
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")


@lru_cache
def ci_vision_model() -> str:
    """The Ollama model used for listing-screenshot field extraction (`evidence/
    vision_extractor.py`). No model choice is locked by the spec (§1a item 4 / Q7 remains
    open) — this is a configurable default, not a spec decision, so an operator can swap
    models without a code change."""
    return os.environ.get("CI_VISION_MODEL", "llava")


@lru_cache
def ci_review_vision_model() -> str:
    """The Ollama model used for reviews-tab screenshot classification (`review_insight/
    ollama_extractor.py`). Defaults to the same model as listing extraction — both are
    vision-classification tasks; an operator may point them at different models via env."""
    return os.environ.get("CI_REVIEW_VISION_MODEL", ci_vision_model())


@lru_cache
def tavily_api_key() -> str:
    """`product_intelligence.sources.tavily_client.HttpTavilyClient` — not `_required()`: PI's
    unit/integration tests run entirely against fakes (Phase 1), so an empty key here must not
    block app startup; only a real `pi.discover`/`pi.supplier_lookup` call against this key
    fails, honestly, at that call site."""
    return os.environ.get("TAVILY_API_KEY", "")


@lru_cache
def youtube_api_key() -> str:
    """`product_intelligence.sources.youtube_client.HttpYoutubeClient` — same "optional at
    startup, real calls fail honestly" posture as `tavily_api_key()`."""
    return os.environ.get("YOUTUBE_API_KEY", "")


@lru_cache
def google_places_api_key() -> str:
    """`product_intelligence.supplier.google_places_client.HttpPlacesClient` — same posture as
    `tavily_api_key()`."""
    return os.environ.get("GOOGLE_PLACES_API_KEY", "")


@lru_cache
def pi_text_insight_model() -> str:
    """The Ollama model used for PI's review-commentary text classification
    (`review_insight/text_extraction.py`'s `OllamaTextInsightExtractor`) — configurable
    default, not a spec decision, same reasoning as `ci_vision_model()`."""
    return os.environ.get("PI_TEXT_INSIGHT_MODEL", "qwen3:8b")


@lru_cache
def pi_product_extraction_model() -> str:
    """The Ollama model used for PI's discovery-time product-name extraction
    (`discovery/product_extraction.py`'s `OllamaProductExtractionClient`) — a separate
    extraction task from `pi_text_insight_model()`'s review-commentary sentiment
    classification (different prompt, different output contract), so it gets its own
    configurable default rather than silently reusing that one — same `PI_*_MODEL` env-var
    convention, same default model family."""
    return os.environ.get("PI_PRODUCT_EXTRACTION_MODEL", "qwen3:8b")


@lru_cache
def pi_embedding_model() -> str:
    """The Ollama model used for PI's derived-attribute embeddings (`embedding/embed.py`'s
    `OllamaEmbeddingClient`). Do not repoint at a different-dimension model without also
    updating `embed.py`'s `MODEL_DIM`/the `product_embedding.embedding` column type."""
    return os.environ.get("PI_EMBEDDING_MODEL", "nomic-embed-text")


@lru_cache
def cfo_narration_model() -> str:
    """The Ollama model used for CFO's Brain-3 narration (`cfo.reasoning.narrate.
    narrate_figures`, via `cfo.reasoning.ollama_provider.OllamaLlmProvider`) — text-only,
    unrelated to `ci_vision_model()`'s vision-classification models above. No model choice is
    locked by cfo-agent.md; this is a configurable default, not a spec decision, so an
    operator can swap models without a code change (mirrors `ci_vision_model()`'s own
    precedent exactly)."""
    return os.environ.get("CFO_NARRATION_MODEL", "qwen3:8b")
