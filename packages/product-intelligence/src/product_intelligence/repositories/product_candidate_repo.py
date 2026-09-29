"""product_candidate — PI build plan §2 (revised opportunity-idea shape). Persists Stage 1
(`discovery/ranking.py`) output only — `score_explanation`/`opportunity_label`/
`web_price_signal` travel with every row, never computed here.

**Checkpoint 1 scaffolding only** — every function below is a `NotImplementedError` stub.
Every function takes `tenant_id` first, per CI's convention.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


def insert_candidate(
    tenant_id: UUID,
    *,
    run_id: UUID,
    candidate_title: str,
    title_length: int | None,
    title_structure: dict[str, Any] | None,
    keyword_themes: dict[str, Any] | None,
    observed_category: str | None,
    category_confidence: str | None,
    image_url: str | None,
    image_source_url: str | None,
    demand_signal: dict[str, Any] | None,
    engagement_signal: dict[str, Any] | None,
    web_price_signal: dict[str, Any] | None,
    source_diversity: int,
    proxy_score: str | None,
    proxy_state: str,
    proxy_basis: dict[str, Any],
    score_explanation: dict[str, Any],
    candidate_marketplaces: list[str] | None,
    source_urls: list[dict[str, Any]],
    capture_status: str,
    confidence: str,
) -> UUID:
    """`opportunity_label` is never accepted as a parameter — it is fixed at
    `'CANDIDATE_OPPORTUNITY'` by the migration's own CHECK constraint (§0a), never a caller
    choice. `proxy_score` is a `Fraction`/`Paise`-free numeric string per the no-float rule;
    the real implementation converts it to `numeric(6,2)` at the DB boundary, never a Python
    `float`."""
    raise NotImplementedError("product_candidate_repo.insert_candidate: Checkpoint 2")


def get_candidate(tenant_id: UUID, candidate_id: UUID) -> dict[str, Any] | None:
    raise NotImplementedError("product_candidate_repo.get_candidate: Checkpoint 2")


def list_candidates_for_run(tenant_id: UUID, run_id: UUID) -> list[dict[str, Any]]:
    raise NotImplementedError("product_candidate_repo.list_candidates_for_run: Checkpoint 2")


def list_prior_candidates_for_brief(tenant_id: UUID, niche_brief_id: UUID) -> list[dict[str, Any]]:
    """Reads candidates from earlier runs against the same `niche_brief_id`, within
    `pi_tenant_config.candidate_retention_days` — feeds the optional review-velocity
    refinement (`product-intelligence-agent.md` §6.3), never triggers a new fetch."""
    raise NotImplementedError("product_candidate_repo.list_prior_candidates_for_brief: Checkpoint 2")
