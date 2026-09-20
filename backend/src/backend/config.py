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
