"""pi_tenant_config — one row per tenant; the migration gives no default row, so a tenant
with no row yet must get the spec's stated defaults from application code, same convention
as CI's `ci_tenant_config_repo`. Now also holds the per-source cache TTL knobs
(`tavily_cache_ttl_hours`/`youtube_cache_ttl_hours`) that `sources/cache.py`'s callers read
before calling `QueryCache.put(...)` — the cache itself never reads config directly.

**Checkpoint 2 — real implementation.** Every function takes `tenant_id` first and receives
its connection only via `tenant_scope()` (auth.md §7.3), matching every other repository in
this package.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope

# product-intelligence-agent.md §5's own column defaults, used only when no row exists yet.
DEFAULT_CANDIDATE_RETENTION_DAYS = 90
DEFAULT_SUPPLIER_LEAD_RETENTION_DAYS = 90
DEFAULT_TAVILY_CACHE_TTL_HOURS = 24
DEFAULT_YOUTUBE_CACHE_TTL_HOURS = 24


def get_config(tenant_id: UUID) -> dict[str, object]:
    """Every `pi_tenant_config` column, defaulted per-field when no row exists yet."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT candidate_retention_days, supplier_lead_retention_days, "
                "tavily_cache_ttl_hours, youtube_cache_ttl_hours, updated_by, updated_at "
                "FROM pi_tenant_config WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": str(tenant_id)},
        ).mappings().first()
    if row is None:
        return {
            "candidateRetentionDays": DEFAULT_CANDIDATE_RETENTION_DAYS,
            "supplierLeadRetentionDays": DEFAULT_SUPPLIER_LEAD_RETENTION_DAYS,
            "tavilyCacheTtlHours": DEFAULT_TAVILY_CACHE_TTL_HOURS,
            "youtubeCacheTtlHours": DEFAULT_YOUTUBE_CACHE_TTL_HOURS,
            "updatedBy": None,
            "updatedAt": None,
        }
    return {
        "candidateRetentionDays": row["candidate_retention_days"],
        "supplierLeadRetentionDays": row["supplier_lead_retention_days"],
        "tavilyCacheTtlHours": row["tavily_cache_ttl_hours"],
        "youtubeCacheTtlHours": row["youtube_cache_ttl_hours"],
        "updatedBy": row["updated_by"],
        "updatedAt": row["updated_at"],
    }


def get_candidate_retention_days(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT candidate_retention_days FROM pi_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return row[0] if row is not None else DEFAULT_CANDIDATE_RETENTION_DAYS


def get_supplier_lead_retention_days(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT supplier_lead_retention_days FROM pi_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return row[0] if row is not None else DEFAULT_SUPPLIER_LEAD_RETENTION_DAYS


def get_tavily_cache_ttl_hours(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT tavily_cache_ttl_hours FROM pi_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return row[0] if row is not None else DEFAULT_TAVILY_CACHE_TTL_HOURS


def get_youtube_cache_ttl_hours(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT youtube_cache_ttl_hours FROM pi_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        return row[0] if row is not None else DEFAULT_YOUTUBE_CACHE_TTL_HOURS


def upsert_config(
    tenant_id: UUID,
    *,
    updated_by: UUID,
    candidate_retention_days: int | None = None,
    supplier_lead_retention_days: int | None = None,
    tavily_cache_ttl_hours: int | None = None,
    youtube_cache_ttl_hours: int | None = None,
) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO pi_tenant_config
                    (tenant_id, candidate_retention_days, supplier_lead_retention_days,
                     tavily_cache_ttl_hours, youtube_cache_ttl_hours, updated_by, updated_at)
                VALUES
                    (:tenant_id, COALESCE(:candidate_retention_days, :default_candidate_retention_days),
                     COALESCE(:supplier_lead_retention_days, :default_supplier_lead_retention_days),
                     COALESCE(:tavily_cache_ttl_hours, :default_tavily_cache_ttl_hours),
                     COALESCE(:youtube_cache_ttl_hours, :default_youtube_cache_ttl_hours),
                     :updated_by, now())
                ON CONFLICT (tenant_id) DO UPDATE SET
                    candidate_retention_days = COALESCE(:candidate_retention_days, pi_tenant_config.candidate_retention_days),
                    supplier_lead_retention_days = COALESCE(:supplier_lead_retention_days, pi_tenant_config.supplier_lead_retention_days),
                    tavily_cache_ttl_hours = COALESCE(:tavily_cache_ttl_hours, pi_tenant_config.tavily_cache_ttl_hours),
                    youtube_cache_ttl_hours = COALESCE(:youtube_cache_ttl_hours, pi_tenant_config.youtube_cache_ttl_hours),
                    updated_by = :updated_by,
                    updated_at = now()
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "updated_by": str(updated_by),
                "candidate_retention_days": candidate_retention_days,
                "supplier_lead_retention_days": supplier_lead_retention_days,
                "tavily_cache_ttl_hours": tavily_cache_ttl_hours,
                "youtube_cache_ttl_hours": youtube_cache_ttl_hours,
                "default_candidate_retention_days": DEFAULT_CANDIDATE_RETENTION_DAYS,
                "default_supplier_lead_retention_days": DEFAULT_SUPPLIER_LEAD_RETENTION_DAYS,
                "default_tavily_cache_ttl_hours": DEFAULT_TAVILY_CACHE_TTL_HOURS,
                "default_youtube_cache_ttl_hours": DEFAULT_YOUTUBE_CACHE_TTL_HOURS,
            },
        )
