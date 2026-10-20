"""The seller's business profile as agent context (docs/specs/business-profile.md D5, D6). The ONE place the CEO reads it, through the one service seam.

It is context only: one short line built by code (never a model), quoted data, never a source of figures or instructions. A failure to read it never costs the seller their turn.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from backend.services import business_profile


def summary(tenant: UUID) -> str | None:
    return business_profile.compact_summary(tenant)


def for_leg(tenant: UUID) -> tuple[str | None, dict[str, Any] | None]:
    """What the CEO hands a specialist it calls: (short line, structured brief), from one read."""
    return business_profile.context_for_tenant(tenant)


@contextmanager
def for_agents(text: str | None, brief: dict[str, Any] | None = None) -> Iterator[None]:
    """While a specialist runs, the same profile is available to it through `business_profile.current_for_agent()` / `current_brief_for_agent()`."""
    with business_profile.profile_for_agents(text, brief):
        yield
