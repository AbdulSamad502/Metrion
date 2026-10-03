"""`seller_fact` reads and appends (spec §5, §6.1). Append-only for the application role.

`load_facts` returns facts for ONE exact, non-null sku, oldest -> newest (decision 2); there is
deliberately no way to load a tenant's sku-less facts here. A TARGET_PRICE row is returned with
`value=None` (its value lives in `value_paise`, which is not selected at all).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Connection, text

from slim_cmo.generation.facts import FactInput
from slim_cmo.service.models import NewFact
from slim_cmo.types import SellerFactType

_LOAD = text(
    """
    SELECT id, fact_type, attribute_name, fact_value, provided_at
    FROM seller_fact
    WHERE tenant_id = :tenant_id AND sku = :sku
    ORDER BY provided_at, id
    """
)
_INSERT = text(
    """
    INSERT INTO seller_fact (tenant_id, sku, attribute_name, fact_type, fact_value, value_paise, image_analysis_id, provided_by)
    VALUES (:tenant_id, :sku, :attribute_name, :fact_type, :fact_value, :value_paise, :image_analysis_id, :provided_by)
    RETURNING id, provided_at
    """
)


def load_facts(conn: Connection, tenant_id: UUID, sku: str) -> list[FactInput]:
    return [
        FactInput(SellerFactType(r.fact_type), r.fact_value, r.attribute_name, r.provided_at, str(r.id))
        for r in conn.execute(_LOAD, {"tenant_id": tenant_id, "sku": sku})
    ]


def insert_facts(conn: Connection, tenant_id: UUID, user_id: UUID, facts: Sequence[NewFact]) -> list[FactInput]:
    out: list[FactInput] = []
    for f in facts:
        r = conn.execute(
            _INSERT,
            {
                "tenant_id": tenant_id, "sku": f.sku, "attribute_name": f.attribute_name,
                "fact_type": f.fact_type.value, "fact_value": f.fact_value, "value_paise": f.value_paise,
                "image_analysis_id": f.image_analysis_id, "provided_by": user_id,
            },
        ).one()
        out.append(FactInput(f.fact_type, f.fact_value, f.attribute_name, r.provided_at, str(r.id)))
    return out
