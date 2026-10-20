"""ci_finding — the persisted, dashboard-addressable form of a CI finding (spec §5.7, C45, C46).

Every row has a stable tenant-scoped `id` (the `finding_id` the dashboard's Ask CEO passes and the CEO
re-reads), at least one `evidence_refs` entry (a finding without evidence is invalid — also a CHECK in the
migration), and a `dedup_key` so the same observation is one finding however many times it is derived.
`payload` is display-safe derived facts only — never review text, snippets or image content."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope

FINDING_TYPES = frozenset(
    {"PRICE_CHANGE", "AVAILABILITY_CHANGE", "REVIEW_THEME", "LISTING_GAP", "DIFFERENTIATION", "MARKET_POSITION", "FRESHNESS", "DISCOVERY_CANDIDATE"}
)


class FindingWithoutEvidence(ValueError):
    """A finding must resolve to at least one evidence record (C45, AC53)."""


def upsert(
    tenant_id: UUID,
    *,
    product_id: str,
    competitor_url_id: UUID | None,
    finding_type: str,
    dedup_key: str,
    evidence_refs: Sequence[UUID],
    confidence: str,
    freshness: str,
    payload: dict[str, Any],
    seller_confirmation: str = "NOT_REQUIRED",
    sample_size: int | None = None,
    sample_total: int | None = None,
    engine_result_ref: UUID | None = None,
    now: datetime | None = None,
) -> tuple[UUID, bool]:
    """Returns `(finding_id, created)`. A repeat of the same `dedup_key` refreshes freshness and payload and
    keeps the id, so a dashboard link or an Ask CEO issued earlier still resolves."""
    if finding_type not in FINDING_TYPES:
        raise ValueError(f"unknown finding_type {finding_type!r}")
    if not evidence_refs:
        raise FindingWithoutEvidence(f"{finding_type} finding {dedup_key!r} has no evidence_refs")
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO ci_finding (tenant_id, product_id, competitor_url_id, finding_type, dedup_key, evidence_refs,
                                        sample_size, sample_total, confidence, freshness, seller_confirmation,
                                        engine_result_ref, payload, created_at)
                VALUES (:tenant_id, :product_id, :url, :ft, :dedup, CAST(:refs AS uuid[]), :ss, :st, :conf, :fresh,
                        :sc, :engine, CAST(:payload AS jsonb), :now)
                ON CONFLICT (tenant_id, dedup_key) DO UPDATE
                  SET freshness = EXCLUDED.freshness, payload = EXCLUDED.payload,
                      seller_confirmation = EXCLUDED.seller_confirmation, confidence = EXCLUDED.confidence
                RETURNING id, (xmax = 0) AS created
                """
            ),
            {
                "tenant_id": str(tenant_id), "product_id": product_id, "url": str(competitor_url_id) if competitor_url_id else None,
                "ft": finding_type, "dedup": dedup_key, "refs": [str(r) for r in evidence_refs], "ss": sample_size, "st": sample_total,
                "conf": confidence, "fresh": freshness, "sc": seller_confirmation, "engine": str(engine_result_ref) if engine_result_ref else None,
                "payload": json.dumps(payload), "now": now or datetime.now(timezone.utc),
            },
        ).one()
        return row[0], bool(row[1])


def get(tenant_id: UUID, finding_id: UUID) -> dict[str, Any] | None:
    """Tenant-scoped: another tenant's finding id is simply absent (RLS), never a distinguishable 'forbidden'."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM ci_finding WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": str(tenant_id), "id": str(finding_id)},
        ).mappings().first()
        return dict(row) if row else None


def list_for_product(tenant_id: UUID, product_id: str, *, limit: int = 30) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM ci_finding WHERE tenant_id = :tenant_id AND product_id = :product_id AND superseded_by IS NULL "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"tenant_id": str(tenant_id), "product_id": product_id, "limit": limit},
        ).mappings()
        return [dict(r) for r in rows]
