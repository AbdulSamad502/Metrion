"""line_component repository — data-foundation.md §1.4."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

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


def _component_params(
    tenant_id: UUID, parent_key: str, parent_id: UUID, component: ComponentValue
) -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "tenant_id": str(tenant_id),
        parent_key: str(parent_id),
        "component_kind": component.component_kind,
        "component_code": component.component_code,
        "source_side": component.source_side,
        "amount": component.amount_paise,
        "tax_amount": component.tax_amount_paise,
        "rate_pct": component.rate_pct,
        "source_column": component.source_column,
        "is_verified": component.is_verified,
        "note": component.note,
    }


def insert_components_on(
    conn: Connection,
    tenant_id: UUID,
    *,
    parent_key: str,
    items: Iterable[tuple[UUID, Sequence[ComponentValue]]],
) -> int:
    """Bulk-inserts components for many parent lines on an ALREADY-OPEN `tenant_scope()`
    connection (so the caller controls the transaction) — one executemany round trip per
    table instead of one INSERT round trip per component. `parent_key` is "sales_line_id" or
    "settlement_line_id" (the other FK column is left NULL, same as the single-row writers)."""
    if parent_key not in ("sales_line_id", "settlement_line_id"):
        raise ValueError(f"unsupported parent_key {parent_key!r}")
    params = [_component_params(tenant_id, parent_key, pid, c) for pid, comps in items for c in comps]
    if params:
        conn.execute(_INSERT_SQL if parent_key == "sales_line_id" else _INSERT_SETTLEMENT_SQL, params)
    return len(params)


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


_INSERT_SETTLEMENT_SQL = text(
    """
    INSERT INTO line_component
        (id, tenant_id, settlement_line_id, component_kind, component_code, source_side, amount,
         tax_amount, rate_pct, source_column, is_verified, note)
    VALUES
        (:id, :tenant_id, :settlement_line_id, :component_kind, :component_code, :source_side, :amount,
         :tax_amount, :rate_pct, :source_column, :is_verified, :note)
    """
)


def insert_settlement_components(
    tenant_id: UUID, *, settlement_line_id: UUID, components: tuple[ComponentValue, ...]
) -> list[UUID]:
    """Same shape as `insert_components`, for the settlement side — `sales_line_id` left NULL."""
    ids: list[UUID] = []
    with tenant_scope(tenant_id) as conn:
        for component in components:
            new_id = uuid4()
            ids.append(new_id)
            conn.execute(
                _INSERT_SETTLEMENT_SQL,
                {
                    "id": str(new_id),
                    "tenant_id": str(tenant_id),
                    "settlement_line_id": str(settlement_line_id),
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


_BY_PARENT_SQL = {
    "sales_line_id": text(
        """
        SELECT sales_line_id AS parent_id, component_kind, component_code, source_side, amount, tax_amount, rate_pct
        FROM line_component WHERE tenant_id = :tenant_id AND sales_line_id = ANY(CAST(:ids AS uuid[]))
        ORDER BY component_kind, component_code
        """
    ),
    "settlement_line_id": text(
        """
        SELECT settlement_line_id AS parent_id, component_kind, component_code, source_side, amount, tax_amount, rate_pct
        FROM line_component WHERE tenant_id = :tenant_id AND settlement_line_id = ANY(CAST(:ids AS uuid[]))
        ORDER BY component_kind, component_code
        """
    ),
}


def components_for_lines(tenant_id: UUID, *, parent_key: str, parent_ids: Sequence[UUID]) -> dict[str, list[dict[str, object]]]:
    """The persisted components (fees, taxes, discounts) of the given lines, keyed by line id.
    `parent_key` is "sales_line_id" or "settlement_line_id"."""
    if parent_key not in _BY_PARENT_SQL:
        raise ValueError(f"unsupported parent_key {parent_key!r}")
    out: dict[str, list[dict[str, object]]] = {}
    if not parent_ids:
        return out
    with tenant_scope(tenant_id) as conn:
        for row in conn.execute(
            _BY_PARENT_SQL[parent_key], {"tenant_id": str(tenant_id), "ids": [str(i) for i in parent_ids]}
        ).mappings():
            out.setdefault(str(row["parent_id"]), []).append(dict(row))
    return out
