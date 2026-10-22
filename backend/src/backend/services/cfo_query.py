"""Composition root for the CFO query planner (cfo-query-planner.md §6.1): wires the configured model, the Postgres/Brain 1 backend and the
evidence cache to `cfo.planner.pipeline.run_financial_query`. The CEO reaches this only through the registered `cfo.query` action; there is no
route that accepts a plan.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from fractions import Fraction
from typing import Any
from uuid import UUID

from cfo.planner.cache_store import EvidenceCache, InMemoryEvidenceCache, RedisEvidenceCache
from cfo.planner.executor import ExecutorConfig
from cfo.planner.pipeline import LlmPlannerProvider, PlannerAnswer, PlannerProvider, PlannerRefusal, run_financial_query
from cfo.planner.plan import PeriodRef
from cfo.planner.validator import ValidatorLimits
from cfo.reasoning.ollama_provider import OllamaLlmProvider

from backend.config import cfo_planner_model, cfo_planner_settings, ollama_host
from backend.services.cfo_planner_backend import PlannerComponentCodes, PostgresPlannerBackend

# Every input the planner can ever need coverage for; a threshold exists for each so a metric is never "CONFIG_MISSING" by accident.
_COVERAGE_INPUTS = (
    "sales_lines", "cogs_per_unit", "cancellation_state", "return_status", "rto_status", "rto_outcome", "fee_components", "settlement_lines", "settlement_history",
    "reconciliation_exceptions", "contribution_profit", "expense_entries", "expense_class", "ad_source",
)

_process_cache: EvidenceCache | None = None


def _cache(ttl_seconds: int) -> EvidenceCache:
    """Redis when `REDIS_URL` is set and the client library is installed; otherwise a process-local cache (correct, because every key carries the
    tenant's data_version, but only effective within one worker)."""
    global _process_cache
    if _process_cache is None:
        url = (os.environ.get("REDIS_URL") or "").strip()
        client: Any = None
        if url:
            try:
                import redis  # type: ignore[import-not-found,import-untyped,unused-ignore]

                client = redis.Redis.from_url(url, decode_responses=True)
            except Exception:
                client = None
        _process_cache = RedisEvidenceCache(client, ttl_seconds) if client is not None else InMemoryEvidenceCache()
    return _process_cache


def planner_limits(settings: dict[str, object]) -> ValidatorLimits:
    cov = settings["min_coverage"]
    assert isinstance(cov, Fraction)
    return ValidatorLimits(
        max_rows_scanned=int(settings["max_rows_scanned"]),  # type: ignore[call-overload]
        max_groups=int(settings["max_groups"]), max_limit=int(settings["max_limit"]),  # type: ignore[call-overload]
        min_coverage={k: cov for k in _COVERAGE_INPUTS},
        low_explainability_share=settings["low_explainability_share"],  # type: ignore[arg-type]
    )


def answer_financial_query(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    question: str,
    periods: Sequence[PeriodRef],
    provider: PlannerProvider | None = None,
    cache: EvidenceCache | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> PlannerAnswer | PlannerRefusal:
    model = cfo_planner_model()
    if provider is None:
        if model is None:
            return PlannerRefusal("PLANNER_OFF", "Open financial questions are not switched on for this workspace yet.")
        provider = LlmPlannerProvider(OllamaLlmProvider(host=ollama_host()), model)
    s = cfo_planner_settings()
    backend = PostgresPlannerBackend(
        requested_by=requested_by,
        codes=PlannerComponentCodes(s["fee_codes"], s["forward_logistics_codes"], s["reverse_logistics_codes"], s["non_refunded_fee_codes"]),  # type: ignore[arg-type]
        statement_timeout_ms=int(s["statement_timeout_ms"]),  # type: ignore[call-overload]
        min_coverage=s["min_coverage"],  # type: ignore[arg-type]
        cash_min_samples=int(s["cash_min_samples"]),  # type: ignore[call-overload]
    )
    return run_financial_query(
        question, periods, tenant_id=tenant_id, provider=provider, backend=backend,
        cache=cache if cache is not None else _cache(int(s["cache_ttl_seconds"])),  # type: ignore[call-overload]
        limits=planner_limits(s),
        config=ExecutorConfig(statement_timeout_ms=int(s["statement_timeout_ms"]), oracle_sample_size=int(s["oracle_sample_size"]),  # type: ignore[call-overload]
                              max_ranking_groups=int(s["max_ranking_groups"])),  # type: ignore[call-overload]
        on_stage=on_stage,
    )
