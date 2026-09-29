"""niche_brief — `product-intelligence-agent.md` §5, §6.1. DRAFT/READY/ARCHIVED lifecycle;
authoring is never a direct execution path (§6.1 rule 1) — this repository only persists
what a plain CRUD form or a CEO conversation already composed.

**Checkpoint 1 scaffolding only** — every function below is a `NotImplementedError` stub
naming its expected shape. Real queries (mirroring
`competitor_intelligence.repositories.ci_discovery_run_repo`'s `tenant_scope()`-per-call
pattern) land in Checkpoint 2. Every function takes `tenant_id` first, per CI's convention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID


def create_draft(
    tenant_id: UUID,
    *,
    created_by: UUID,
    category_text: str | None = None,
    budget_paise: int | None = None,
    target_price_min_paise: int | None = None,
    target_price_max_paise: int | None = None,
    marketplaces: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> UUID:
    """Inserts a `DRAFT` `niche_brief` row. Returns the new row's id."""
    raise NotImplementedError("niche_brief_repo.create_draft: Checkpoint 2")


def get_brief(tenant_id: UUID, brief_id: UUID) -> dict[str, Any] | None:
    raise NotImplementedError("niche_brief_repo.get_brief: Checkpoint 2")


def list_briefs(tenant_id: UUID, *, status: str | None = None) -> list[dict[str, Any]]:
    raise NotImplementedError("niche_brief_repo.list_briefs: Checkpoint 2")


def update_draft(
    tenant_id: UUID,
    brief_id: UUID,
    *,
    category_text: str | None = None,
    budget_paise: int | None = None,
    target_price_min_paise: int | None = None,
    target_price_max_paise: int | None = None,
    marketplaces: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> None:
    """§6.1 rule 2: only a `DRAFT` (or a `READY` brief with no `QUEUED`/`RUNNING` run against
    it, which is moved back to `DRAFT` first) may be edited."""
    raise NotImplementedError("niche_brief_repo.update_draft: Checkpoint 2")


def mark_ready(tenant_id: UUID, brief_id: UUID, *, readied_at: datetime) -> None:
    """§6.1 rule 2: only when budget, category and at least one marketplace are present —
    the caller enforces that precondition, this function only performs the transition."""
    raise NotImplementedError("niche_brief_repo.mark_ready: Checkpoint 2")


def mark_draft(tenant_id: UUID, brief_id: UUID) -> None:
    """§6.1 rule 2: a `READY` brief may be edited back to `DRAFT` at any time before a run
    starts against it; blocked while a `pi_research_run` referencing it is `QUEUED`/`RUNNING`
    — that check is the caller's (`pi_research_run_repo`), not this function's."""
    raise NotImplementedError("niche_brief_repo.mark_draft: Checkpoint 2")


def archive(tenant_id: UUID, brief_id: UUID) -> None:
    raise NotImplementedError("niche_brief_repo.archive: Checkpoint 2")
