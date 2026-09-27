"""leak_finding — cfo-agent.md §5. Every function takes tenant_id first and receives its
connection only via tenant_scope(); no function in this module opens its own connection.

CP1 scaffolding only (`twinkly-mapping-canyon.md`): plain insert/list against the table this
migration owns. No classification, ranking, or leak-category mapping logic lives here — that
composition (§6.3/§6.4, `rank_findings`) belongs to CP2's `src/cfo/leak/classification.py` and
`backend/services/cfo_actions.py`. `amount_paise` is always a value the caller already copied
from the reconciliation exception (AC4) — this module never computes it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from cfo.repositories.tenant_context import tenant_scope


def insert(
    tenant_id: UUID,
    *,
    reconciliation_exception_id: UUID,
    engine_result_ref: UUID,
    marketplace: str,
    leak_category: str,
    severity: str,
    amount_paise: int,
    affected_line_count: int,
    first_observed_at: datetime,
    age_days: int,
    status: str,
    confidence: str,
    formula_version: str,
    sku: str | None = None,
    claim_window_days: int | None = None,
    window_status: str | None = None,
    explanation: str | None = None,
    recommended_action: str | None = None,
) -> UUID:
    """Writes one leak_finding row exactly as given — no derivation, no recomputation."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO leak_finding (
                  tenant_id, reconciliation_exception_id, engine_result_ref, marketplace,
                  leak_category, severity, amount_paise, affected_line_count, sku,
                  first_observed_at, age_days, claim_window_days, window_status,
                  explanation, recommended_action, status, confidence, formula_version
                )
                VALUES (
                  :tenant_id, :reconciliation_exception_id, :engine_result_ref, :marketplace,
                  :leak_category, :severity, :amount_paise, :affected_line_count, :sku,
                  :first_observed_at, :age_days, :claim_window_days, :window_status,
                  :explanation, :recommended_action, :status, :confidence, :formula_version
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "reconciliation_exception_id": str(reconciliation_exception_id),
                "engine_result_ref": str(engine_result_ref),
                "marketplace": marketplace,
                "leak_category": leak_category,
                "severity": severity,
                "amount_paise": amount_paise,
                "affected_line_count": affected_line_count,
                "sku": sku,
                "first_observed_at": first_observed_at,
                "age_days": age_days,
                "claim_window_days": claim_window_days,
                "window_status": window_status,
                "explanation": explanation,
                "recommended_action": recommended_action,
                "status": status,
                "confidence": confidence,
                "formula_version": formula_version,
            },
        ).one()
        return row[0]


def list_for_tenant(tenant_id: UUID) -> list[dict[str, Any]]:
    """All leak_finding rows visible to this tenant, most recently observed first."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT * FROM leak_finding WHERE tenant_id = :tenant_id ORDER BY first_observed_at DESC"),
            {"tenant_id": str(tenant_id)},
        ).mappings()
        return [dict(r) for r in rows]
