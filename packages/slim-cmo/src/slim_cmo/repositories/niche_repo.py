"""Niche-term persistence and the two read-only catalog reads (spec §6.8.3, C15). One `tenant_scope` per call.

`read_catalog_titles` returns DISTINCT `item_title` strings and nothing else: the SELECT list contains no amount,
quantity, order reference, customer or settlement column, and no file bytes. Frequency is used only to ORDER the
rows (best-selling first, so the read cap keeps the most representative titles); it is never returned.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from slim_cmo.repositories import config_repo
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.niche import PlanFn, SELLER_FACT_TYPES, StoredTerm
from slim_cmo.types import NicheTermOrigin, NicheTermStatus

_TITLES = text(
    """
    SELECT item_title
    FROM sales_line
    WHERE tenant_id = :tenant_id AND item_title IS NOT NULL AND btrim(item_title) <> ''
    GROUP BY item_title
    ORDER BY count(*) DESC, item_title
    LIMIT :cap
    """
)
_FACT_TERMS = text(
    """
    SELECT DISTINCT fact_value
    FROM seller_fact
    WHERE tenant_id = :tenant_id AND fact_type IN ('CATEGORY', 'NICHE')
      AND fact_value IS NOT NULL AND btrim(fact_value) <> ''
    ORDER BY fact_value
    LIMIT :cap
    """
)
_LIST = text(
    """
    SELECT id, term, origin, origin_note, status
    FROM cmo_niche_term
    WHERE tenant_id = :tenant_id
    ORDER BY created_at, term
    """
)
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('cmo_niche_term:' || :tenant_id, 0))")
_INSERT = text(
    """
    INSERT INTO cmo_niche_term (tenant_id, term, origin, origin_note, status, confirmed_by, confirmed_at)
    VALUES (:tenant_id, :term, :origin, :origin_note, :status,
            CASE WHEN :status = 'CONFIRMED' THEN CAST(:user_id AS uuid) END,
            CASE WHEN :status = 'CONFIRMED' THEN now() END)
    """
)
_SET_STATUS = text(
    """
    UPDATE cmo_niche_term
    SET status = :status,
        confirmed_by = CASE WHEN :status = 'CONFIRMED' THEN CAST(:user_id AS uuid) END,
        confirmed_at = CASE WHEN :status = 'CONFIRMED' THEN now() END
    WHERE tenant_id = :tenant_id AND id = :term_id
    """
)


def _rows(conn: Connection, tenant_id: UUID) -> list[StoredTerm]:
    return [
        StoredTerm(r.id, r.term, NicheTermOrigin(r.origin), r.origin_note, NicheTermStatus(r.status))
        for r in conn.execute(_LIST, {"tenant_id": tenant_id})
    ]


class PostgresNicheStore:
    def load_config(self, tenant_id: UUID, keys: Sequence[str], as_of: date) -> Mapping[str, Any]:
        with tenant_scope(tenant_id) as conn:
            return config_repo.load_config_values(conn, tenant_id, keys, as_of)

    def read_catalog_titles(self, tenant_id: UUID, cap: int) -> list[str]:
        with tenant_scope(tenant_id) as conn:
            return [r.item_title for r in conn.execute(_TITLES, {"tenant_id": tenant_id, "cap": cap})]

    def read_seller_fact_terms(self, tenant_id: UUID, cap: int) -> list[str]:
        assert SELLER_FACT_TYPES == ("CATEGORY", "NICHE")  # the SQL literal above must match the contract
        with tenant_scope(tenant_id) as conn:
            return [r.fact_value for r in conn.execute(_FACT_TERMS, {"tenant_id": tenant_id, "cap": cap})]

    def list_terms(self, tenant_id: UUID) -> list[StoredTerm]:
        with tenant_scope(tenant_id) as conn:
            return _rows(conn, tenant_id)

    def apply_plan(self, tenant_id: UUID, user_id: UUID, plan_fn: PlanFn) -> list[StoredTerm]:
        with tenant_scope(tenant_id) as conn:
            conn.execute(_LOCK, {"tenant_id": str(tenant_id)})  # serialises concurrent niche changes for this tenant
            plan = plan_fn(_rows(conn, tenant_id))  # an exception here rolls the whole transaction back
            for c in plan.changes:
                conn.execute(_SET_STATUS, {"tenant_id": tenant_id, "term_id": c.term_id, "status": c.status.value, "user_id": str(user_id)})
            for i in plan.inserts:
                conn.execute(
                    _INSERT,
                    {"tenant_id": tenant_id, "term": i.term, "origin": i.origin.value, "origin_note": i.origin_note,
                     "status": i.status.value, "user_id": str(user_id)},
                )
            return _rows(conn, tenant_id)
