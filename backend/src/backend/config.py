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
