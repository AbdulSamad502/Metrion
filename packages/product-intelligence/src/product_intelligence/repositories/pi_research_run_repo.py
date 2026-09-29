"""pi_research_run — `product-intelligence-agent.md` §5, §6.8. Created only from an
already-`READY` `niche_brief_id` (§6.1 rule 4); the `QUEUED -> RUNNING -> PARTIAL|COMPLETE|
FAILED` state machine itself is Checkpoint 2's job — this module only persists whatever
status a caller sets, same scope boundary as CI's `ci_discovery_run_repo`.

**Checkpoint 1 scaffolding only** — every function below is a `NotImplementedError` stub.
Every function takes `tenant_id` first, per CI's convention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID


def create_run(
    tenant_id: UUID,
    *,
    niche_brief_id: UUID,
    depth: str,
    trigger: str,
    candidate_cap: int,
    status: str = "QUEUED",
) -> UUID:
    """Inserts a `pi_research_run` row. Returns the new row's id. `depth` is `SHALLOW` |
    `COMPLETE`; `trigger` is `DIRECT_UI` | `CEO_REQUEST`."""
    raise NotImplementedError("pi_research_run_repo.create_run: Checkpoint 2")


def get_run(tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
    raise NotImplementedError("pi_research_run_repo.get_run: Checkpoint 2")


def list_runs_for_brief(tenant_id: UUID, niche_brief_id: UUID) -> list[dict[str, Any]]:
    raise NotImplementedError("pi_research_run_repo.list_runs_for_brief: Checkpoint 2")


def has_active_run(tenant_id: UUID, niche_brief_id: UUID) -> bool:
    """True when a `QUEUED`/`RUNNING` run already references `niche_brief_id` — used by
    `niche_brief_repo.mark_draft`'s caller to enforce §6.1 rule 2's edit-lock."""
    raise NotImplementedError("pi_research_run_repo.has_active_run: Checkpoint 2")


def update_status(tenant_id: UUID, run_id: UUID, *, status: str, started_at: datetime | None = None) -> None:
    raise NotImplementedError("pi_research_run_repo.update_status: Checkpoint 2")


def finish_run(tenant_id: UUID, run_id: UUID, *, status: str, finished_at: datetime) -> None:
    raise NotImplementedError("pi_research_run_repo.finish_run: Checkpoint 2")
