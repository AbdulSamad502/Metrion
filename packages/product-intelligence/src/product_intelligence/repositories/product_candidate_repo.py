"""product_candidate — PI build plan §2 (revised opportunity-idea shape). Persists Stage 1
(`discovery/ranking.py`) output only — `score_explanation`/`opportunity_label`/
`web_price_signal` travel with every row, never computed here.

**Checkpoint 2 — real implementation.** Every function takes `tenant_id` first and receives
its connection only via `tenant_scope()` (auth.md §7.3), matching every other repository in
this package. `opportunity_label` is never accepted as a parameter — it is fixed at
`'CANDIDATE_OPPORTUNITY'` by the migration's own CHECK constraint (§0a), and this module's
INSERT never references it either, relying on the column default.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope


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
    it is cast to `numeric(6,2)` at the DB boundary, never a Python `float`."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO product_candidate
                    (tenant_id, run_id, candidate_title, title_length, title_structure,
                     keyword_themes, observed_category, category_confidence, image_url,
                     image_source_url, demand_signal, engagement_signal, web_price_signal,
                     source_diversity, proxy_score, proxy_state, proxy_basis, score_explanation,
                     candidate_marketplaces, source_urls, capture_status, confidence)
                VALUES
                    (:tenant_id, :run_id, :candidate_title, :title_length,
                     CAST(:title_structure AS jsonb), CAST(:keyword_themes AS jsonb),
                     :observed_category, :category_confidence, :image_url, :image_source_url,
                     CAST(:demand_signal AS jsonb), CAST(:engagement_signal AS jsonb),
                     CAST(:web_price_signal AS jsonb), :source_diversity,
                     CAST(:proxy_score AS numeric(6,2)), :proxy_state, CAST(:proxy_basis AS jsonb),
                     CAST(:score_explanation AS jsonb), CAST(:candidate_marketplaces AS text[]),
                     CAST(:source_urls AS jsonb), :capture_status, :confidence)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "run_id": str(run_id),
                "candidate_title": candidate_title,
                "title_length": title_length,
                "title_structure": json.dumps(title_structure) if title_structure is not None else None,
                "keyword_themes": json.dumps(keyword_themes) if keyword_themes is not None else None,
                "observed_category": observed_category,
                "category_confidence": category_confidence,
                "image_url": image_url,
                "image_source_url": image_source_url,
                "demand_signal": json.dumps(demand_signal) if demand_signal is not None else None,
                "engagement_signal": json.dumps(engagement_signal) if engagement_signal is not None else None,
                "web_price_signal": json.dumps(web_price_signal) if web_price_signal is not None else None,
                "source_diversity": source_diversity,
                "proxy_score": proxy_score,
                "proxy_state": proxy_state,
                "proxy_basis": json.dumps(proxy_basis),
                "score_explanation": json.dumps(score_explanation),
                "candidate_marketplaces": candidate_marketplaces,
                "source_urls": json.dumps(source_urls),
                "capture_status": capture_status,
                "confidence": confidence,
            },
        ).one()
        return row[0]


def update_feasibility(
    tenant_id: UUID,
    candidate_id: UUID,
    *,
    feasibility_status: str,
    feasibility_estimate_ref: UUID | None,
    feasibility_low_paise: int | None,
    feasibility_high_paise: int | None,
    feasibility_cogs_basis: str | None,
    feasibility_assumptions: list[str] | None,
    feasibility_unavailable_reason: str | None,
) -> None:
    """Writes back the snapshot `discovery/feasibility.py` computed (or the honest
    UNAVAILABLE outcome when it couldn't be computed) — a separate post-synthesis update,
    same shape as review-insight/embedding being computed after the initial `insert_candidate`
    row exists, never squeezed into the original INSERT (feasibility depends on the already-
    persisted candidate's id as its own `observation_ref` anchor)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE product_candidate
                SET feasibility_status = :feasibility_status,
                    feasibility_estimate_ref = :feasibility_estimate_ref,
                    feasibility_low_paise = :feasibility_low_paise,
                    feasibility_high_paise = :feasibility_high_paise,
                    feasibility_cogs_basis = :feasibility_cogs_basis,
                    feasibility_assumptions = CAST(:feasibility_assumptions AS jsonb),
                    feasibility_unavailable_reason = :feasibility_unavailable_reason
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(candidate_id),
                "feasibility_status": feasibility_status,
                "feasibility_estimate_ref": str(feasibility_estimate_ref) if feasibility_estimate_ref else None,
                "feasibility_low_paise": feasibility_low_paise,
                "feasibility_high_paise": feasibility_high_paise,
                "feasibility_cogs_basis": feasibility_cogs_basis,
                "feasibility_assumptions": json.dumps(feasibility_assumptions) if feasibility_assumptions is not None else None,
                "feasibility_unavailable_reason": feasibility_unavailable_reason,
            },
        )


def update_image(tenant_id: UUID, candidate_id: UUID, *, image_url: str | None, image_source_url: str | None) -> None:
    """Sets (or clears) a candidate's image. Used only for the final five (`discovery/top5_images.py`); discovery itself persists no image."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE product_candidate SET image_url = :url, image_source_url = :source WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(candidate_id), "url": image_url, "source": image_source_url},
        )


def get_candidate(tenant_id: UUID, candidate_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM product_candidate WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(candidate_id)},
        ).mappings().first()
        return dict(row) if row is not None else None


def list_candidates_for_run(tenant_id: UUID, run_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM product_candidate WHERE tenant_id = :tenant_id AND run_id = :run_id "
                "ORDER BY proxy_score DESC NULLS LAST"
            ),
            {"tenant_id": str(tenant_id), "run_id": str(run_id)},
        ).mappings().all()
        return [dict(r) for r in rows]


def list_candidates_by_ids(tenant_id: UUID, candidate_ids: list[UUID]) -> list[dict[str, Any]]:
    """Stage 4's shortlist lookup — returns rows for exactly the given ids, tenant-scoped;
    silently skips any id not owned by this tenant (RLS + the explicit `WHERE tenant_id`
    below both exclude it, never an error, matching `get_candidate`'s own "None if not
    found/not owned" precedent one level up)."""
    if not candidate_ids:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM product_candidate WHERE tenant_id = :tenant_id "
                "AND id = ANY(CAST(:candidate_ids AS uuid[]))"
            ),
            {"tenant_id": str(tenant_id), "candidate_ids": [str(c) for c in candidate_ids]},
        ).mappings().all()
        return [dict(r) for r in rows]


def list_prior_candidates_for_brief(tenant_id: UUID, niche_brief_id: UUID) -> list[dict[str, Any]]:
    """Reads candidates from earlier runs against the same `niche_brief_id`, within
    `pi_tenant_config.candidate_retention_days` — feeds the optional review-velocity
    refinement (`product-intelligence-agent.md` §6.3), never triggers a new fetch."""
    with tenant_scope(tenant_id) as conn:
        retention_row = conn.execute(
            text("SELECT candidate_retention_days FROM pi_tenant_config WHERE tenant_id = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        ).first()
        retention_days = retention_row[0] if retention_row is not None else 90

        rows = conn.execute(
            text(
                """
                SELECT pc.*
                FROM product_candidate pc
                JOIN pi_research_run pr ON pr.id = pc.run_id AND pr.tenant_id = pc.tenant_id
                WHERE pc.tenant_id = :tenant_id
                  AND pr.niche_brief_id = :niche_brief_id
                  AND pr.started_at >= now() - make_interval(days => :retention_days)
                ORDER BY pr.started_at DESC
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "niche_brief_id": str(niche_brief_id),
                "retention_days": retention_days,
            },
        ).mappings().all()
        return [dict(r) for r in rows]
