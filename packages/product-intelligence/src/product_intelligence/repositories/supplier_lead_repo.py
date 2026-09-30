"""supplier_lead — `product-intelligence-agent.md` §6.6. Discovery only, never ranked here
or anywhere in PI (C4) — CFO ranks, from seller-supplied quotes only.

**Checkpoint 2 — real implementation.** Every function takes `tenant_id` first and receives
its connection only via `tenant_scope()` (auth.md §7.3), matching every other repository in
this package.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope


def insert_lead(
    tenant_id: UUID,
    *,
    run_id: UUID,
    candidate_id: UUID | None,
    supplier_name: str,
    source: str,
    contact: dict[str, Any] | None,
    locality: str | None,
    distance_km: Decimal | None,
    category_match: str | None,
    source_url: str | None,
    fetched_at: datetime,
) -> UUID:
    """`source` is `GOOGLE_PLACES` | `TAVILY` | `INDIAMART_LOOKUP` — IndiaMART is not
    implemented in this build (plan's Context; deferred pending a commercial partnership),
    so no caller in Checkpoint 2 passes that value yet.

    `candidate_id` is nullable — `pi_supplier_lookup.py` always passes the candidate this
    lead was found for, but the column stays optional for any future category-wide lookup
    that isn't tied to one candidate."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO supplier_lead
                    (tenant_id, run_id, candidate_id, supplier_name, source, contact, locality,
                     distance_km, category_match, source_url, fetched_at)
                VALUES
                    (:tenant_id, :run_id, :candidate_id, :supplier_name, :source,
                     CAST(:contact AS jsonb), :locality, :distance_km, :category_match,
                     :source_url, :fetched_at)
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "run_id": str(run_id),
                "candidate_id": str(candidate_id) if candidate_id is not None else None,
                "supplier_name": supplier_name,
                "source": source,
                "contact": json.dumps(contact) if contact is not None else None,
                "locality": locality,
                "distance_km": distance_km,
                "category_match": category_match,
                "source_url": source_url,
                "fetched_at": fetched_at,
            },
        ).one()
        return row[0]


def list_leads_for_run(tenant_id: UUID, run_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM supplier_lead WHERE tenant_id = :tenant_id AND run_id = :run_id "
                "ORDER BY fetched_at DESC"
            ),
            {"tenant_id": str(tenant_id), "run_id": str(run_id)},
        ).mappings().all()
        return [dict(r) for r in rows]


def list_leads_for_candidate(tenant_id: UUID, candidate_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM supplier_lead WHERE tenant_id = :tenant_id "
                "AND candidate_id = :candidate_id ORDER BY fetched_at DESC"
            ),
            {"tenant_id": str(tenant_id), "candidate_id": str(candidate_id)},
        ).mappings().all()
        return [dict(r) for r in rows]
