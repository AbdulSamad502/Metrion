"""line_component repository — data-foundation.md §1.4."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope
from data_foundation.types import ComponentValue

_INSERT_SQL = text(
    """
    INSERT INTO line_component
        (id, tenant_id, sales_line_id, component_kind, component_code, source_side, amount,
         tax_amount, rate_pct, source_column, is_verified, note)
    VALUES
        (:id, :tenant_id, :sales_line_id, :component_kind, :component_code, :source_side, :amount,
         :tax_amount, :rate_pct, :source_column, :is_verified, :note)
    """
)


def insert_components(tenant_id: UUID, *, sales_line_id: UUID, components: tuple[ComponentValue, ...]) -> list[UUID]:
    ids: list[UUID] = []
    with tenant_scope(tenant_id) as conn:
        for component in components:
            new_id = uuid4()
            ids.append(new_id)
            conn.execute(
                _INSERT_SQL,
                {
                    "id": str(new_id),
                    "tenant_id": str(tenant_id),
                    "sales_line_id": str(sales_line_id),
                    "component_kind": component.component_kind,
                    "component_code": component.component_code,
                    "source_side": component.source_side,
                    "amount": component.amount_paise,
                    "tax_amount": component.tax_amount_paise,
                    "rate_pct": component.rate_pct,
                    "source_column": component.source_column,
                    "is_verified": component.is_verified,
                    "note": component.note,
                },
            )
    return ids
