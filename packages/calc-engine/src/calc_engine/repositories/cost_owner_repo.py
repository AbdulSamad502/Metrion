"""Cost-ownership choices (cost-ownership matrix, V-DUP-2; docs/specs/cfo-expense-ledger.md D5, cfo-phase3-scope.md AD4).

For a cost component (advertising, packaging, storage, logistics, other) and a marketplace (or the whole account, "ALL") over a period, more than one source can
speak: the Expense Tracker's pool, the expense ledger, and — for advertising only — an uploaded report. Exactly one may count. The seller's choice is recorded here,
append-only; a later choice for the same key supersedes the earlier. Without a choice the caller treats the situation as an unresolved conflict.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import text

from calc_engine.repositories import read_model_version_repo
from calc_engine.repositories.tenant_context import tenant_scope

COMPONENTS = ("ADVERTISING", "PACKAGING", "STORAGE", "LOGISTICS", "OTHER")
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO", "ALL")
OWNERS_FOR = {"ADVERTISING": ("REPORT", "POOL", "LEDGER"), "PACKAGING": ("POOL", "LEDGER"), "STORAGE": ("POOL", "LEDGER"), "LOGISTICS": ("POOL", "LEDGER"), "OTHER": ("POOL", "LEDGER")}


class CostOwnerError(ValueError):
    """A request the cost-ownership rules refuse; the message is safe to show the seller."""


def choose_owner(tenant_id: UUID, component: str, marketplace: str, start: date, end: date, owner: str, chosen_by: UUID) -> UUID:
    if component not in COMPONENTS:
        raise CostOwnerError(f"unknown cost {component!r}; choose one of {', '.join(c.lower() for c in COMPONENTS)}")
    if marketplace not in MARKETPLACES:
        raise CostOwnerError(f"unknown marketplace {marketplace!r}")
    if owner not in OWNERS_FOR[component]:
        raise CostOwnerError(f"the owner of {component.lower()} costs must be one of {', '.join(OWNERS_FOR[component])}")
    if end < start:
        raise CostOwnerError("the period ends before it starts")
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        prev = conn.execute(text(
            "SELECT c.id FROM cost_owner_choice c WHERE c.tenant_id = :t AND c.component = :c AND c.marketplace = :m AND c.period_start = :s AND c.period_end = :e "
            "AND NOT EXISTS (SELECT 1 FROM cost_owner_choice n WHERE n.tenant_id = c.tenant_id AND n.supersedes_id = c.id) LIMIT 1"),
            {"t": str(tenant_id), "c": component, "m": marketplace, "s": start, "e": end}).one_or_none()
        conn.execute(text(
            "INSERT INTO cost_owner_choice (id, tenant_id, component, marketplace, period_start, period_end, owner, chosen_by, supersedes_id) "
            "VALUES (:id, :t, :c, :m, :s, :e, :o, :by, :sup)"),
            {"id": str(new_id), "t": str(tenant_id), "c": component, "m": marketplace, "s": start, "e": end, "o": owner, "by": str(chosen_by), "sup": None if prev is None else str(prev[0])})
        read_model_version_repo.bump_on(conn, tenant_id)
    return new_id


def owner_for(tenant_id: UUID, component: str, marketplace: str, start: date, end: date) -> str | None:
    """The seller's live choice whose period contains the whole asked period, or None. A choice for the marketplace wins over one for the whole account."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(
            "SELECT c.marketplace, c.owner FROM cost_owner_choice c WHERE c.tenant_id = :t AND c.component = :c AND c.marketplace IN (:m, 'ALL') "
            "AND c.period_start <= :s AND c.period_end >= :e "
            "AND NOT EXISTS (SELECT 1 FROM cost_owner_choice n WHERE n.tenant_id = c.tenant_id AND n.supersedes_id = c.id) ORDER BY c.chosen_at DESC"),
            {"t": str(tenant_id), "c": component, "m": marketplace, "s": start, "e": end}).all()
    for mp, owner in rows:
        if mp == marketplace:
            return str(owner)
    return str(rows[0][1]) if rows else None
