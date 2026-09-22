"""ci_candidate — competitor-intelligence-agent.md §5.4, §6.13.

`tier`, `identity_match`, `seller_decision` and `evidence_status` are four independent
fields (§5.4's "must stay distinguishable" table) — this module never merges them into a
single status column, and every write function below touches exactly the columns its name
says it touches.

Every function takes `tenant_id` first and receives its connection only via `tenant_scope()`
(auth.md §7.3), matching every other repository in this package.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.discovery.identity_resolution import IdentityMatchBasis, IdentityResolution
from competitor_intelligence.repositories.tenant_context import tenant_scope


def _basis_to_json(basis: IdentityMatchBasis) -> str:
    return json.dumps(
        {
            "candidate_brand": basis.candidate_brand,
            "seller_brand": basis.seller_brand,
            "candidate_model_tokens": sorted(basis.candidate_model_tokens),
            "seller_model_tokens": sorted(basis.seller_model_tokens),
            "candidate_pack_size": basis.candidate_pack_size,
            "seller_pack_size": basis.seller_pack_size,
            "candidate_is_bundle": basis.candidate_is_bundle,
            "seller_is_bundle": basis.seller_is_bundle,
            "notes": basis.notes,
        }
    )


def create_candidate(
    tenant_id: UUID,
    *,
    discovery_run_id: UUID,
    candidate_url: str,
    origin: str = "DISCOVERED",
    search_result_id: UUID | None = None,
    marketplace: str | None = None,
    tier: str = "RAW",
) -> UUID:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_candidate
                    (tenant_id, discovery_run_id, search_result_id, origin, candidate_url, marketplace, tier)
                VALUES
                    (:tenant_id, :discovery_run_id, :search_result_id, :origin, :candidate_url, :marketplace, :tier)
                ON CONFLICT (tenant_id, discovery_run_id, candidate_url) DO UPDATE
                    SET marketplace = EXCLUDED.marketplace
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "discovery_run_id": str(discovery_run_id),
                "search_result_id": str(search_result_id) if search_result_id else None,
                "origin": origin,
                "candidate_url": candidate_url,
                "marketplace": marketplace,
                "tier": tier,
            },
        ).one()
        return row[0]


def set_identity_resolution(tenant_id: UUID, candidate_id: UUID, resolution: IdentityResolution, *, tier: str) -> None:
    """Records §6.13.1's result: `identity_match` plus its required `identity_match_basis`
    (§5.4: "required whenever identity_match is set"), and moves the candidate to `tier`
    (`ANALYZED` for anything that has been through identity resolution)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE ci_candidate
                SET identity_match = :identity_match,
                    identity_match_basis = CAST(:basis AS jsonb),
                    tier = :tier
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "id": str(candidate_id),
                "identity_match": resolution.identity_match.value,
                "basis": _basis_to_json(resolution.basis),
                "tier": tier,
            },
        )


def set_tier(tenant_id: UUID, candidate_id: UUID, tier: str) -> None:
    """`RAW | ANALYZED | RECOMMENDED` — RECOMMENDED is a subset of ANALYZED's population,
    kept as its own value deliberately (§5.4)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE ci_candidate SET tier = :tier WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(candidate_id), "tier": tier},
        )


def set_seller_decision(tenant_id: UUID, candidate_id: UUID, *, decision: str, decided_by: UUID) -> None:
    """`seller_decision` is a HUMAN action, never system-written (§6.13.3) — this is the
    only write path for it, and it is never invoked from `resolve_identity`/`gate`."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                UPDATE ci_candidate
                SET seller_decision = :decision, seller_decided_by = :decided_by, seller_decided_at = now()
                WHERE tenant_id = :tenant_id AND id = :id
                """
            ),
            {"tenant_id": str(tenant_id), "id": str(candidate_id), "decision": decision, "decided_by": str(decided_by)},
        )


def set_competitor_url_id(tenant_id: UUID, candidate_id: UUID, competitor_url_id: UUID) -> None:
    """Sec 6.15 rule 6 — set once a candidate is accepted and promoted into a tracked
    `competitor_url`. Never set any other way; `accept_candidate` (discovery_run.py) is the
    only caller."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE ci_candidate SET competitor_url_id = :competitor_url_id WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(candidate_id), "competitor_url_id": str(competitor_url_id)},
        )


def set_origin(tenant_id: UUID, candidate_id: UUID, origin: str) -> None:
    """`DISCOVERED | MANUAL_URL | PROMOTED_BY_SELLER` (Sec 5.4). Used by the "Promote to
    analysis" seller action (Sec 6.15 rule 4) to mark a formerly-unanalyzed raw candidate as
    `PROMOTED_BY_SELLER` once the seller pulls it into analysis by hand."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE ci_candidate SET origin = :origin WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(candidate_id), "origin": origin},
        )


def set_evidence_status(tenant_id: UUID, candidate_id: UUID, evidence_status: str) -> None:
    """`AWAITING_EVIDENCE | EVIDENCE_BACKED` — a third, independent axis from relevance and
    identity match (C23/C25, §5.4)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("UPDATE ci_candidate SET evidence_status = :status WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(candidate_id), "status": evidence_status},
        )


def get_candidate(tenant_id: UUID, candidate_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM ci_candidate WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(candidate_id)},
        ).mappings().first()
        return dict(row) if row is not None else None


def get_by_competitor_url_id(tenant_id: UUID, competitor_url_id: UUID) -> dict[str, Any] | None:
    """Checkpoint 6 — the price-band/comparison eligibility check (competitor-intelligence-
    agent.md §6.16.3: "currently tracked EXACT_MATCH-or-LIKELY_VARIANT competitors") needs a
    tracked competitor_url's original identity_match, if it has one. Returns `None` for a
    competitor_url added through the manual-URL path with no discovery candidate behind it —
    the caller treats that as "no adverse identity-match signal on record", never as UNCERTAIN
    or NOT_A_MATCH (a manual add is itself the seller's identity confirmation, C21)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM ci_candidate WHERE tenant_id = :tenant_id AND competitor_url_id = :competitor_url_id"),
            {"tenant_id": str(tenant_id), "competitor_url_id": str(competitor_url_id)},
        ).mappings().first()
        return dict(row) if row is not None else None


def list_candidates_for_run(tenant_id: UUID, discovery_run_id: UUID, *, tier: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM ci_candidate WHERE tenant_id = :tenant_id AND discovery_run_id = :discovery_run_id"
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "discovery_run_id": str(discovery_run_id)}
    if tier is not None:
        query += " AND tier = :tier"
        params["tier"] = tier
    query += " ORDER BY created_at ASC"
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(query), params).mappings().all()
        return [dict(r) for r in rows]
