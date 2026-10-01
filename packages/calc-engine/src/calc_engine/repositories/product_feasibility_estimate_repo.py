"""product_feasibility_estimate repository — deterministic-engine.md §5.13.2, §9.1.

Persists the `ProductFeasibilityEstimate` objects `api/estimate_product_feasibility.py`
already builds in memory. Mirrors `metric_result_repo.py`'s role exactly: that function is
"pure and DB-free" by design (its own docstring), so persistence is the caller's job — this
module is the thin mapping from `ProductFeasibilityEstimate` to the `product_feasibility_estimate`
row shape, through `tenant_context.tenant_scope()`. No calculation and no interpretation
happens here.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from calc_engine.api.estimate_product_feasibility import ProductFeasibilityEstimate
from calc_engine.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO product_feasibility_estimate
        (id, tenant_id, low_paise, high_paise, confidence, basis, assumptions, cogs_basis,
         fee_reference_version, observation_ref, formula_version, config_version, computed_at)
    VALUES
        (:id, :tenant_id, :low_paise, :high_paise, :confidence, :basis, CAST(:assumptions AS jsonb),
         :cogs_basis, :fee_reference_version, CAST(:observation_ref AS jsonb), :formula_version,
         :config_version, :computed_at)
    """
)

_GET_SQL = text(
    """
    SELECT id, tenant_id, low_paise, high_paise, confidence, basis, assumptions, cogs_basis,
           fee_reference_version, observation_ref, formula_version, config_version, computed_at
    FROM product_feasibility_estimate
    WHERE id = :id
    """
)


def save(tenant_id: UUID, estimate: ProductFeasibilityEstimate) -> UUID:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(estimate.id),
                "tenant_id": str(tenant_id),
                "low_paise": estimate.low_paise.value,
                "high_paise": estimate.high_paise.value,
                "confidence": estimate.confidence.value,
                "basis": estimate.basis,
                "assumptions": json.dumps(list(estimate.assumptions)),
                "cogs_basis": estimate.cogs_basis,
                "fee_reference_version": estimate.fee_reference_version,
                "observation_ref": json.dumps(estimate.observation_ref),
                "formula_version": estimate.formula_version,
                "config_version": estimate.config_version,
                "computed_at": estimate.computed_at,
            },
        )
    return estimate.id


def get(tenant_id: UUID, estimate_id: UUID) -> dict[str, object] | None:
    """Returns None both when the row doesn't exist and when it belongs to another tenant —
    same RLS-driven indistinguishability as `metric_result_repo.get`."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_GET_SQL, {"id": str(estimate_id)}).first()
        return dict(row._mapping) if row is not None else None
