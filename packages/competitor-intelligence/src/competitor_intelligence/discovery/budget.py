"""Discovery query/cost budgets — competitor-intelligence-agent.md §6.12.1.

Per §5.4, these are `ci_tenant_config` columns — **tenant-level Postgres configuration**,
not process-wide env-var config (`backend/src/backend/config.py`'s pattern does not apply
here: these knobs are per-tenant, not per-deployment). `DiscoveryBudget` is the plain,
DB-free value object every budget-aware function in this subpackage takes; reading it from
`ci_tenant_config` (with the spec's own defaults when no row exists yet) is
`repositories/ci_tenant_config_repo.py::get_discovery_budget`'s job, mirroring the existing
`get_price_threshold_pct`/`get_config` pattern in that module.

None of the seven values below are hardcoded into pipeline logic — every call site takes a
`DiscoveryBudget` instance and reads its fields, so a per-tenant override never requires a
code change.
"""

from __future__ import annotations

from dataclasses import dataclass

# §6.12.1 locked defaults — used only when a tenant has no `ci_tenant_config` row yet
# (same no-row-yet convention as `ci_tenant_config_repo`'s other DEFAULT_* constants).
DEFAULT_MAX_DISCOVERY_QUERIES_PER_RUN = 20
DEFAULT_MAX_RAW_CANDIDATES = 50
DEFAULT_MAX_ANALYZED_CANDIDATES = 20
DEFAULT_MAX_RECOMMENDED_CANDIDATES = 15  # the seller is shown the top 15 matches and picks up to their free slots (owner decision 2026-10-20)
DEFAULT_MAX_FOLLOWUP_SEARCHES_PER_CANDIDATE = 3
DEFAULT_DISCOVERY_RUN_TIMEOUT_SECONDS = 120
DEFAULT_SEARCH_CACHE_TTL_HOURS = 24
DEFAULT_DISCOVERY_ENABLED = True


@dataclass(frozen=True, slots=True)
class DiscoveryBudget:
    max_discovery_queries_per_run: int = DEFAULT_MAX_DISCOVERY_QUERIES_PER_RUN
    max_raw_candidates: int = DEFAULT_MAX_RAW_CANDIDATES
    max_analyzed_candidates: int = DEFAULT_MAX_ANALYZED_CANDIDATES
    max_recommended_candidates: int = DEFAULT_MAX_RECOMMENDED_CANDIDATES
    max_followup_searches_per_candidate: int = DEFAULT_MAX_FOLLOWUP_SEARCHES_PER_CANDIDATE
    discovery_run_timeout_seconds: int = DEFAULT_DISCOVERY_RUN_TIMEOUT_SECONDS
    search_cache_ttl_hours: int = DEFAULT_SEARCH_CACHE_TTL_HOURS


class BudgetLimit(str):
    """Names a §6.12.1 limit — used as `ci_discovery_run.partial_reason` (a later
    checkpoint) so a `PARTIAL` run always names the exact limit hit, never a silently
    truncated result presented as complete (§6.12.1, AC19)."""


LIMIT_MAX_DISCOVERY_QUERIES_PER_RUN = BudgetLimit("max_discovery_queries_per_run")
LIMIT_MAX_RAW_CANDIDATES = BudgetLimit("max_raw_candidates")
