"""pi_tenant_config — one row per tenant; the migration gives no default row, so a tenant
with no row yet must get the spec's stated defaults from application code, same convention
as CI's `ci_tenant_config_repo`. Now also holds the per-source cache TTL knobs
(`tavily_cache_ttl_hours`/`youtube_cache_ttl_hours`) that `sources/cache.py`'s callers read
before calling `QueryCache.put(...)` — the cache itself never reads config directly.

**Checkpoint 1 scaffolding only** — every function below is a `NotImplementedError` stub.
Every function takes `tenant_id` first, per CI's convention.
"""

from __future__ import annotations

from uuid import UUID

# product-intelligence-agent.md §5's own column defaults, used only when no row exists yet.
DEFAULT_CANDIDATE_RETENTION_DAYS = 90
DEFAULT_SUPPLIER_LEAD_RETENTION_DAYS = 90
DEFAULT_TAVILY_CACHE_TTL_HOURS = 24
DEFAULT_YOUTUBE_CACHE_TTL_HOURS = 24


def get_config(tenant_id: UUID) -> dict[str, object]:
    """Every `pi_tenant_config` column, defaulted per-field when no row exists yet."""
    raise NotImplementedError("pi_tenant_config_repo.get_config: Checkpoint 2")


def get_candidate_retention_days(tenant_id: UUID) -> int:
    raise NotImplementedError("pi_tenant_config_repo.get_candidate_retention_days: Checkpoint 2")


def get_supplier_lead_retention_days(tenant_id: UUID) -> int:
    raise NotImplementedError("pi_tenant_config_repo.get_supplier_lead_retention_days: Checkpoint 2")


def get_tavily_cache_ttl_hours(tenant_id: UUID) -> int:
    raise NotImplementedError("pi_tenant_config_repo.get_tavily_cache_ttl_hours: Checkpoint 2")


def get_youtube_cache_ttl_hours(tenant_id: UUID) -> int:
    raise NotImplementedError("pi_tenant_config_repo.get_youtube_cache_ttl_hours: Checkpoint 2")


def upsert_config(
    tenant_id: UUID,
    *,
    updated_by: UUID,
    candidate_retention_days: int | None = None,
    supplier_lead_retention_days: int | None = None,
    tavily_cache_ttl_hours: int | None = None,
    youtube_cache_ttl_hours: int | None = None,
) -> None:
    raise NotImplementedError("pi_tenant_config_repo.upsert_config: Checkpoint 2")
