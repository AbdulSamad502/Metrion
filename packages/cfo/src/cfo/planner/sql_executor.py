"""The set-based (SQL) fast path and its per-line reference (cfo-query-planner.md §6.3, §9, D5).

**Two paths, one truth.** A metric is allowed on the SQL path only when this module also holds its per-line reference — built from the
same rows through the real `calc_engine` formula — and the oracle suite proves the two equal to the paisa. Today that is `GROSS_SALES`
and `SETTLEMENT_RECEIPTS`; every other metric runs through the engine's own composition (see `executor.py`), not through SQL.

**No SQL is composed from plan values.** Every statement is assembled from a closed set of fixed fragments, selected by dictionary
lookup on catalog-validated identifiers; every plan *value* (dates, marketplaces, SKUs, limits) is a bound parameter. Reads go through
`tenant_scope()` (RLS, `SET LOCAL` context, fail-closed) with a statement timeout set inside the transaction.

No money arithmetic lives here: SQL sums integers (paise) and the reference sums through `calc_engine`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from calc_engine.dates import resolve_document_date
from calc_engine.formulas.gross_sales import GrossSales, gross_sales
from calc_engine.formulas.settlement_receipts import SettlementLineInput, SettlementReceipts, settlement_receipts
from calc_engine.types import CanonicalLine, Confidence, Paise, Unavailable
from cfo.repositories.tenant_context import tenant_scope

SQL_METRICS: frozenset[str] = frozenset({"GROSS_SALES", "SETTLEMENT_RECEIPTS"})
SQL_DIMENSIONS: dict[str, frozenset[str]] = {
    "GROSS_SALES": frozenset({"marketplace", "sku", "period"}),
    "SETTLEMENT_RECEIPTS": frozenset({"marketplace", "period"}),
}
GRANULARITIES: frozenset[str] = frozenset({"day", "week", "month"})
UNSPECIFIED_SKU = "(unspecified)"

_SALES_DATE = "coalesce(invoice_date, dispatch_date, order_date)"  # must stay in agreement with calc_engine.dates.resolve_document_date
_SETTLEMENT_DATE = "settlement_date"
_BUCKET = {  # fixed expressions; "{d}" is replaced by one of the two fixed date expressions above, never by a plan value
    "day": "({d})",
    "week": "date_trunc('week', {d})::date",
    "month": "date_trunc('month', {d})::date",
}
_DIM_SQL = {"marketplace": "marketplace", "sku": "sku"}


@dataclass(frozen=True, slots=True)
class Scope:
    period_start: date
    period_end: date
    marketplaces: tuple[str, ...] | None = None
    skus: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Grouping:
    dimensions: tuple[str, ...] = ()  # subset of SQL_DIMENSIONS[metric], in the order requested
    granularity: str | None = None  # required iff "period" is a dimension


@dataclass(frozen=True, slots=True)
class SetRow:
    keys: tuple[tuple[str, str], ...]
    value_paise: int | None  # None = nothing measurable in this group (never zero)
    line_count: int
    excluded: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class SetResult:
    metric_id: str
    rows: tuple[SetRow, ...]
    consolidated: SetRow
    truncated: bool
    groups_total: int


class UnsupportedQuery(ValueError):
    pass


def _check(metric_id: str, group: Grouping) -> None:
    if metric_id not in SQL_METRICS:
        raise UnsupportedQuery(f"{metric_id} has no set-based path")
    bad = [d for d in group.dimensions if d not in SQL_DIMENSIONS[metric_id]]
    if bad:
        raise UnsupportedQuery(f"{metric_id} cannot be grouped by {bad}")
    if ("period" in group.dimensions) != (group.granularity is not None):
        raise UnsupportedQuery("a period granularity is required exactly when grouping by period")
    if group.granularity is not None and group.granularity not in GRANULARITIES:
        raise UnsupportedQuery(f"unknown granularity {group.granularity!r}")
    if len(set(group.dimensions)) != len(group.dimensions):
        raise UnsupportedQuery("duplicate group-by dimension")


def _date_expr(metric_id: str) -> str:
    return _SALES_DATE if metric_id == "GROSS_SALES" else _SETTLEMENT_DATE


def build_sql(metric_id: str, group: Grouping, *, filter_marketplaces: bool, filter_skus: bool, limited: bool) -> str:
    """The one statement shape for (metric, grouping, filters). Pure function of catalog-validated identifiers."""
    _check(metric_id, group)
    d = _date_expr(metric_id)
    select_dims: list[str] = []
    group_dims: list[str] = []
    for dim in group.dimensions:
        if dim == "period":
            assert group.granularity is not None
            expr = _BUCKET[group.granularity].format(d=d)
            select_dims.append(f"{expr} AS g_period")
            group_dims.append("g_period")
        else:
            select_dims.append(f"{_DIM_SQL[dim]} AS g_{dim}")
            group_dims.append(_DIM_SQL[dim])

    wheres = ["tenant_id = :tenant_id", f"{d} BETWEEN :period_start AND :period_end"]
    if metric_id == "SETTLEMENT_RECEIPTS" and "period" not in group.dimensions:
        # undated settlement lines cannot be assigned to a period; they are counted when the grouping does not split by period
        wheres = ["tenant_id = :tenant_id", f"({d} BETWEEN :period_start AND :period_end OR {d} IS NULL)"]
    if filter_marketplaces:
        wheres.append("marketplace = ANY(:marketplaces)")
    if filter_skus:
        wheres.append("sku = ANY(:skus)")

    if metric_id == "GROSS_SALES":
        valid = "quantity IS NOT NULL AND gross_item_amount IS NOT NULL"
        value = f"SUM(gross_item_amount) FILTER (WHERE {valid})"
        count = f"COUNT(*) FILTER (WHERE {valid})"
        blocked = f"COUNT(*) FILTER (WHERE NOT ({valid}))"
        undated = "0"
        table = "sales_line"
    else:
        in_period = f"{d} BETWEEN :period_start AND :period_end"
        value = f"SUM(gross_settlement_amount) FILTER (WHERE {in_period} AND gross_settlement_amount IS NOT NULL)"
        count = f"COUNT(*) FILTER (WHERE {in_period} AND gross_settlement_amount IS NOT NULL)"
        blocked = f"COUNT(*) FILTER (WHERE {in_period} AND gross_settlement_amount IS NULL)"
        undated = f"COUNT(*) FILTER (WHERE {d} IS NULL)"
        table = "settlement_line"

    cols = ", ".join([*select_dims, f"{value} AS value", f"{count} AS line_count", f"{blocked} AS blocked", f"{undated} AS undated"])
    sql = f"SELECT {cols} FROM {table} WHERE {' AND '.join(wheres)}"
    if group_dims:
        sql += " GROUP BY " + ", ".join(group_dims)
        order = ", ".join(f'{g} COLLATE "C"' if g in _DIM_SQL.values() else g for g in group_dims)
        sql += f" ORDER BY value DESC NULLS LAST, {order}"
        if limited:
            sql += " LIMIT :limit"
    return sql


def _key_value(dim: str, raw: object) -> str:
    if dim == "sku" and raw is None:
        return UNSPECIFIED_SKU
    if isinstance(raw, date):
        return raw.isoformat()
    return str(raw)


def _row(metric_id: str, dims: Sequence[str], m: Mapping[str, object]) -> SetRow:
    keys = tuple((d, _key_value(d, m[f"g_{d}"])) for d in dims)
    excl: list[tuple[str, int]] = []
    if metric_id == "GROSS_SALES":
        if int(m["blocked"]) > 0:  # type: ignore[call-overload]
            excl.append(("NO_QUANTITY_OR_GROSS_AMOUNT", int(m["blocked"])))  # type: ignore[call-overload]
    else:
        if int(m["blocked"]) > 0:  # type: ignore[call-overload]
            excl.append(("NO_SETTLED_AMOUNT", int(m["blocked"])))  # type: ignore[call-overload]
        if int(m["undated"]) > 0:  # type: ignore[call-overload]
            excl.append(("NO_SETTLEMENT_DATE", int(m["undated"])))  # type: ignore[call-overload]
    v = m["value"]
    return SetRow(keys=keys, value_paise=None if v is None else int(v), line_count=int(m["line_count"]), excluded=tuple(excl))  # type: ignore[call-overload]


def _params(scope: Scope, limit: int | None) -> dict[str, object]:
    p: dict[str, object] = {"period_start": scope.period_start, "period_end": scope.period_end}
    if scope.marketplaces is not None:
        p["marketplaces"] = list(scope.marketplaces)
    if scope.skus is not None:
        p["skus"] = list(scope.skus)
    if limit is not None:
        p["limit"] = limit
    return p


def run_set_metric(
    conn: Connection, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, *, limit: int, statement_timeout_ms: int
) -> SetResult:
    """Runs the grouped statement and the ungrouped (consolidated) one on an open tenant-scoped connection. The grouped rows are
    fetched with `limit + 1` so truncation is detected without a second count."""
    if limit < 1 or statement_timeout_ms < 1:
        raise ValueError("limit and statement_timeout_ms must be positive (they are configuration, never defaulted)")
    _check(metric_id, group)
    conn.execute(text("SELECT set_config('statement_timeout', :ms, true)"), {"ms": str(statement_timeout_ms)})
    base = {"tenant_id": str(tenant_id)}
    fm, fs = scope.marketplaces is not None, scope.skus is not None

    rows: tuple[SetRow, ...] = ()
    truncated = False
    if group.dimensions:
        sql = build_sql(metric_id, group, filter_marketplaces=fm, filter_skus=fs, limited=True)
        got = [dict(r._mapping) for r in conn.execute(text(sql), {**base, **_params(scope, limit + 1)})]
        truncated = len(got) > limit
        rows = tuple(_row(metric_id, group.dimensions, r) for r in got[:limit])
    total_sql = build_sql(metric_id, Grouping(), filter_marketplaces=fm, filter_skus=fs, limited=False)
    cons = _row(metric_id, (), dict(conn.execute(text(total_sql), {**base, **_params(scope, None)}).one()._mapping))
    return SetResult(metric_id=metric_id, rows=rows, consolidated=cons, truncated=truncated, groups_total=len(rows) + (1 if truncated else 0))


def execute_set_metric(tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping, *, limit: int, statement_timeout_ms: int) -> SetResult:
    with tenant_scope(tenant_id) as conn:
        return run_set_metric(conn, tenant_id, metric_id, scope, group, limit=limit, statement_timeout_ms=statement_timeout_ms)


# ======================================================================== the per-line reference (oracle)
def _trunc(d: date, granularity: str) -> date:
    if granularity == "day":
        return d
    if granularity == "week":
        return d - timedelta(days=d.weekday())  # ISO week, Monday: matches date_trunc('week')
    return d.replace(day=1)


def _sales_rows(conn: Connection, tenant_id: UUID, scope: Scope) -> list[dict[str, object]]:
    """Deliberately independent of the SQL path's date expression: it fetches every row with ANY of its three dates in the period
    (a line's document date is always one of them) and resolves the document date in Python through the engine's own
    `resolve_document_date`, so a wrong precedence in the SQL cannot be mirrored here."""
    in_p = "BETWEEN :period_start AND :period_end"
    sql = (
        "SELECT id, marketplace, sku, quantity, gross_item_amount, invoice_date, dispatch_date, order_date FROM sales_line "
        f"WHERE tenant_id = :tenant_id AND (invoice_date {in_p} OR dispatch_date {in_p} OR order_date {in_p})"
        + (" AND marketplace = ANY(:marketplaces)" if scope.marketplaces is not None else "")
        + (" AND sku = ANY(:skus)" if scope.skus is not None else "")
    )
    out: list[dict[str, object]] = []
    for r in conn.execute(text(sql), {"tenant_id": str(tenant_id), **_params(scope, None)}):
        m = dict(r._mapping)
        m["doc_date"] = resolve_document_date(m["invoice_date"], m["dispatch_date"], m["order_date"])
        if scope.period_start <= m["doc_date"] <= scope.period_end:
            out.append(m)
    return out


def _settlement_rows(conn: Connection, tenant_id: UUID, scope: Scope) -> list[dict[str, object]]:
    sql = (
        "SELECT id, marketplace, gross_settlement_amount, settlement_date FROM settlement_line WHERE tenant_id = :tenant_id"
        " AND (settlement_date BETWEEN :period_start AND :period_end OR settlement_date IS NULL)"
        + (" AND marketplace = ANY(:marketplaces)" if scope.marketplaces is not None else "")
    )
    return [dict(r._mapping) for r in conn.execute(text(sql), {"tenant_id": str(tenant_id), **_params(scope, None)})]


def _canonical(r: Mapping[str, object]) -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=r["id"],  # type: ignore[arg-type]
        marketplace=str(r["marketplace"]), document_type="INVOICE", quantity=int(r["quantity"]),  # type: ignore[call-overload]
        invoice_date=r["invoice_date"], dispatch_date=r["dispatch_date"], order_date=r["order_date"],  # type: ignore[arg-type]
        gross_item_amount=Paise(int(r["gross_item_amount"])),  # type: ignore[call-overload]
        components=(), confidence=Confidence.PROVISIONAL,
    )


def _key_for(dims: Sequence[str], granularity: str | None, r: Mapping[str, object], date_key: str) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for dim in dims:
        if dim == "period":
            assert granularity is not None
            out.append((dim, _trunc(r[date_key], granularity).isoformat()))  # type: ignore[arg-type]
        else:
            out.append((dim, _key_value(dim, r[dim])))
    return tuple(out)


def _gross_row(keys: tuple[tuple[str, str], ...], rows: Sequence[Mapping[str, object]]) -> SetRow:
    valid = [r for r in rows if r["quantity"] is not None and r["gross_item_amount"] is not None]
    blocked = len(rows) - len(valid)
    res: GrossSales | Unavailable = gross_sales([_canonical(r) for r in valid], blocked_line_count=blocked)
    excl = (("NO_QUANTITY_OR_GROSS_AMOUNT", blocked),) if blocked else ()
    if isinstance(res, Unavailable):
        return SetRow(keys, None, 0, excl)
    return SetRow(keys, res.value.value, res.line_count, excl)


def _settlement_row(keys: tuple[tuple[str, str], ...], rows: Sequence[Mapping[str, object]], scope: Scope) -> SetRow:
    inputs = [
        SettlementLineInput(line_id=str(r["id"]), marketplace=str(r["marketplace"]), settlement_date=r["settlement_date"],  # type: ignore[arg-type]
                            amount_paise=None if r["gross_settlement_amount"] is None else int(r["gross_settlement_amount"]))  # type: ignore[call-overload]
        for r in rows
    ]
    res: SettlementReceipts | Unavailable = settlement_receipts(inputs, scope.period_start, scope.period_end) if inputs else Unavailable("none", ())
    if isinstance(res, Unavailable):
        in_period_no_amount = sum(1 for i in inputs if i.settlement_date is not None and i.amount_paise is None)
        undated = sum(1 for i in inputs if i.settlement_date is None)
        excl = tuple(e for e in (("NO_SETTLED_AMOUNT", in_period_no_amount), ("NO_SETTLEMENT_DATE", undated)) if e[1])
        return SetRow(keys, None, 0, excl)
    excl = tuple(e for e in (("NO_SETTLED_AMOUNT", res.excluded_no_amount), ("NO_SETTLEMENT_DATE", res.excluded_undated)) if e[1])
    return SetRow(keys, res.value_paise, res.line_count, excl)


def reference_set_metric(conn: Connection, tenant_id: UUID, metric_id: str, scope: Scope, group: Grouping) -> tuple[Mapping[tuple[tuple[str, str], ...], SetRow], SetRow]:
    """The per-line reference: the same rows, grouped in Python, aggregated through the real `calc_engine` formula. Returns
    (rows by key — every group, untruncated, consolidated). The oracle suite and the production spot-check (V-DET-3) compare to it."""
    _check(metric_id, group)
    if metric_id == "GROSS_SALES":
        rows = _sales_rows(conn, tenant_id, scope)
        groups: dict[tuple[tuple[str, str], ...], list[dict[str, object]]] = {}
        for r in rows:
            groups.setdefault(_key_for(group.dimensions, group.granularity, r, "doc_date"), []).append(r)
        by_key = {k: _gross_row(k, v) for k, v in groups.items()}
        return by_key, _gross_row((), rows)

    srows = _settlement_rows(conn, tenant_id, scope)
    by_period = "period" in group.dimensions
    sgroups: dict[tuple[tuple[str, str], ...], list[dict[str, object]]] = {}
    for r in srows:
        if by_period and r["settlement_date"] is None:
            continue  # an undated line cannot be placed in a bucket
        sgroups.setdefault(_key_for(group.dimensions, group.granularity, r, "settlement_date"), []).append(r)
    by_key_s = {k: _settlement_row(k, v, scope) for k, v in sgroups.items()}
    return by_key_s, _settlement_row((), srows, scope)


def new_ref() -> str:
    return str(uuid4())
