"""Single Clerk SDK client instance, lazily constructed from CLERK_SECRET_KEY. Shared by
JWT verification, webhook reconciliation calls, and the onboarding endpoint's organization
creation."""

from __future__ import annotations

from functools import lru_cache

from clerk_backend_api import Clerk

from backend.config import clerk_secret_key


@lru_cache
def get_clerk_client() -> Clerk:
    return Clerk(bearer_auth=clerk_secret_key())
