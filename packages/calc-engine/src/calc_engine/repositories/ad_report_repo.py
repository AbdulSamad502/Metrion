"""Advertising data access (docs/specs/cfo-phase3-scope.md 3b): report coverage and spend, 'no advertising' declarations, cost-owner choices.

Append-only: SELECT and INSERT only. Declarations and choices are superseded by later rows, never edited. Coverage is derived from what a report
*declares by its dates* and from explicit seller declarations — never from the mere absence of rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from calc_engine.formulas.ad_spend import AdCoverage, AdCoverageSource
from calc_engine.repositories import cost_owner_repo, read_model_version_repo
from calc_engine.repositories.tenant_context import tenant_scope

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
OWNERS = ("REPORT", "POOL", "LEDGER")


class AdRuleError(ValueError):
    """A request the advertising rules refuse; the message is safe to show the seller."""


@dataclass(frozen=True, slots=True)
class AdSpend:
    spend_paise: int
    attributed_sales_paise: int | None  # None when no line in scope carries it (never zero)
    line_count: int
    lines_with_sales: int


def report_coverage(tenant_id: UUID, marketplace: str | None = None) -> list[AdCoverage]:
    """One interval per (ingestion run, marketplace): the first to the last report date that run carried."""
    sql = ("SELECT marketplace, min(report_date), max(report_date) FROM ad_report_line WHERE tenant_id = :t"
           + (" AND marketplace = :m" if marketplace else "") + " GROUP BY ingestion_run_id, marketplace")
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(sql), {"t": str(tenant_id), **({"m": marketplace} if marketplace else {})}).all()
    return [AdCoverage(mp, lo, hi, AdCoverageSource.REPORT) for mp, lo, hi in rows]


def declared_no_ads(tenant_id: UUID, marketplace: str | None = None) -> list[AdCoverage]:
    sql = ("SELECT d.marketplace, d.period_start, d.period_end FROM ad_period_declaration d WHERE d.tenant_id = :t"
           + (" AND d.marketplace = :m" if marketplace else "")
           + " AND NOT EXISTS (SELECT 1 FROM ad_period_declaration n WHERE n.tenant_id = d.tenant_id AND n.supersedes_id = d.id)")
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(sql), {"t": str(tenant_id), **({"m": marketplace} if marketplace else {})}).all()
    return [AdCoverage(mp, lo, hi, AdCoverageSource.DECLARATION_NO_ADS) for mp, lo, hi in rows]


def spend_in_period(tenant_id: UUID, marketplace: str, start: date, end: date) -> AdSpend | None:
    """Σ spend (signed paise) over the report lines of a marketplace dated in the period; None when there are no lines."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text(
            "SELECT count(*), coalesce(sum(spend), 0), sum(attributed_sales), count(attributed_sales) FROM ad_report_line "
            "WHERE tenant_id = :t AND marketplace = :m AND report_date BETWEEN :s AND :e"),
            {"t": str(tenant_id), "m": marketplace, "s": start, "e": end}).one()
    n, spend, sales, with_sales = int(row[0]), int(row[1]), row[2], int(row[3])
    if n == 0:
        return None
    return AdSpend(spend, None if sales is None else int(sales), n, with_sales)


def declare_no_ads(tenant_id: UUID, marketplace: str, start: date, end: date, declared_by: UUID) -> UUID:
    if marketplace not in MARKETPLACES:
        raise AdRuleError(f"unknown marketplace {marketplace!r}")
    if end < start:
        raise AdRuleError("the period ends before it starts")
    if spend_in_period(tenant_id, marketplace, start, end) is not None:
        raise AdRuleError("advertising report lines already exist in this period; a 'no advertising' declaration would contradict them")
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(text("INSERT INTO ad_period_declaration (id, tenant_id, marketplace, period_start, period_end, declaration, declared_by) "
                          "VALUES (:id, :t, :m, :s, :e, 'NO_ADS', :by)"),
                     {"id": str(new_id), "t": str(tenant_id), "m": marketplace, "s": start, "e": end, "by": str(declared_by)})
        read_model_version_repo.bump_on(conn, tenant_id)
    return new_id


def choose_owner(tenant_id: UUID, marketplace: str, start: date, end: date, owner: str, chosen_by: UUID) -> UUID:
    """Which source counts for advertising in a marketplace and period when more than one exists (REPORT, POOL or LEDGER)."""
    try:
        return cost_owner_repo.choose_owner(tenant_id, "ADVERTISING", marketplace, start, end, owner, chosen_by)
    except cost_owner_repo.CostOwnerError as exc:
        raise AdRuleError(str(exc)) from None


def owner_for(tenant_id: UUID, marketplace: str, start: date, end: date) -> str | None:
    return cost_owner_repo.owner_for(tenant_id, "ADVERTISING", marketplace, start, end)
