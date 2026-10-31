"""Reading a seller's marketplace performance report (CMO 3.0 M8). Pure: no I/O, no model, no floats. The caller turns a CSV/XLSX file into a list of rows of cell values; this validates them.

Only what the report actually carries is kept. A blank, "-", "N/A" or "NA" cell is MISSING (None), never zero. A rate column (CTR, conversion rate) is not stored: a rate cannot be added up across days
or SKUs, so it is recomputed from the counts when the counts are present. Column names are matched against a short, documented list (docs/CMO-3.0/CMO_M8_PERFORMANCE.md); nothing is guessed from a
column that merely looks similar (for example "page views" is not "impressions")."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
METRICS = ("impressions", "clicks", "orders", "units", "sales")
MAX_ROWS = 50_000
MAX_SHOWN = 30
SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("date", "report date", "day"),
    "sku": ("sku", "seller sku", "merchant sku", "report sku"),
    "marketplace": ("marketplace",),
    "impressions": ("impressions",),
    "clicks": ("clicks",),
    "orders": ("orders", "order count", "total orders", "orders placed"),
    "units": ("units", "units sold", "units ordered", "quantity sold"),
    "sales": ("sales", "revenue", "sales amount", "ordered product sales", "gross sales"),
}
RATE_COLUMNS = ("ctr", "click through rate", "click-through rate", "conversion rate", "conversion", "cvr")
MISSING = frozenset({"", "-", "--", "n/a", "na", "nan", "null", "none"})
_DMY = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DMON = re.compile(r"^(\d{1,2})[ -]([A-Za-z]{3})[a-z]*[ ,-]*(\d{4})$")


def _fold(h: Any) -> str:
    return " ".join(str(h or "").replace("_", " ").casefold().split())


def _missing(v: Any) -> bool:
    return v is None or str(v).strip().casefold() in MISSING


def parse_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    try:
        if (m := _ISO.match(s)):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if (m := _DMY.match(s)):
            return date(int(m[3]), int(m[2]), int(m[1]))  # day first (India); an impossible day/month is an error, not a swap
        if (m := _DMON.match(s)) and m[2].casefold() in _MONTHS:
            return date(int(m[3]), _MONTHS[m[2].casefold()], int(m[1]))
    except ValueError:
        return None
    return None


def parse_count(v: Any) -> int | None:
    """A whole, non-negative number. Raises ValueError for anything else (a fraction, text, a negative)."""
    if isinstance(v, bool):
        raise ValueError("not a number")
    if isinstance(v, int):
        n = Decimal(v)
    else:
        s = str(v).strip().replace(",", "").replace(" ", "")
        try:
            n = Decimal(s)
        except InvalidOperation:
            raise ValueError("not a number") from None
    if not n.is_finite() or n != n.to_integral_value() or n < 0:
        raise ValueError("must be a whole number, zero or more")
    return int(n)


def parse_paise(v: Any) -> int | None:
    """A rupee amount with at most two decimals -> integer paise. Raises ValueError otherwise."""
    if isinstance(v, bool):
        raise ValueError("not an amount")
    s = str(v).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").replace("INR", "").replace(" ", "")
    try:
        n = Decimal(s)
    except InvalidOperation:
        raise ValueError("not an amount") from None
    p = n * 100
    if not n.is_finite() or p != p.to_integral_value() or n < 0:
        raise ValueError("must be a rupee amount of zero or more with at most two decimals")
    return int(p)


def _row_error(errors: list[dict[str, Any]], row: int, msg: str) -> None:
    errors.append({"row": row, "message": msg})


def validate(table: Sequence[Sequence[Any]], marketplace: str, today: date) -> dict[str, Any]:
    """The checked report. `ok` is False when anything must be fixed in the file; nothing is partly accepted."""
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    mp = str(marketplace or "").upper()
    base: dict[str, Any] = {"ok": False, "marketplace": mp, "errors": errors, "warnings": warnings, "lines": [], "metrics": [], "ignoredColumns": [], "period": None, "rowCount": 0, "errorCount": 0}
    if mp not in MARKETPLACES:
        _row_error(errors, 0, "Choose Amazon, Flipkart or Meesho.")
        return _done(base)
    rows = [list(r) for r in table]
    while rows and all(_missing(c) for c in rows[0]):
        rows.pop(0)
    if not rows:
        _row_error(errors, 0, "The file is empty.")
        return _done(base)
    header = [_fold(c) for c in rows[0]]
    cols: dict[str, int] = {}
    for key, names in SYNONYMS.items():
        hits = [i for i, h in enumerate(header) if h in names]
        if len(hits) > 1:
            _row_error(errors, 1, f"Two columns look like “{key}”: {', '.join(repr(str(rows[0][i])) for i in hits)}. Keep one.")
        elif hits:
            cols[key] = hits[0]
    for need, human in (("date", "a date column (Date)"), ("sku", "a SKU column (SKU)")):
        if need not in cols:
            _row_error(errors, 1, f"The file needs {human}.")
    metrics = [m for m in METRICS if m in cols]
    if not metrics:
        _row_error(errors, 1, "The file has none of the supported metric columns: " + ", ".join(m.title() for m in METRICS) + ".")
    known = {i for i in cols.values()}
    base["ignoredColumns"] = [str(rows[0][i]) for i, h in enumerate(header) if i not in known and h]
    rates = [str(rows[0][i]) for i, h in enumerate(header) if h in RATE_COLUMNS]
    if rates:
        warnings.append("Not stored: " + ", ".join(rates) + ". A rate cannot be added up across days, so CTR and conversion rate are worked out from your clicks, impressions and orders when the report has them.")
    if errors:
        return _done(base)
    body = rows[1:]
    if len(body) > MAX_ROWS:
        _row_error(errors, 0, f"The file has more than {MAX_ROWS:,} rows. Split it by period and import the parts.")
        return _done(base)
    seen: dict[tuple[str, date], tuple[int, tuple[Any, ...]]] = {}
    lines: list[dict[str, Any]] = []
    dup_same = 0
    for n, raw in enumerate(body, start=2):
        if all(_missing(c) for c in raw):
            continue
        cell = lambda k: raw[cols[k]] if k in cols and cols[k] < len(raw) else None  # noqa: E731
        bad = len(errors)
        d = parse_date(cell("date"))
        if d is None:
            _row_error(errors, n, f"Row {n}: the date “{cell('date')}” is not a valid date. Use YYYY-MM-DD or DD/MM/YYYY.")
        elif d > today:
            _row_error(errors, n, f"Row {n}: the date {d.isoformat()} is in the future.")
        sku = "" if _missing(cell("sku")) else str(cell("sku")).strip()
        if not sku:
            _row_error(errors, n, f"Row {n}: the SKU is blank.")
        if "marketplace" in cols and not _missing(cell("marketplace")) and str(cell("marketplace")).strip().upper() != mp:
            _row_error(errors, n, f"Row {n}: the row says marketplace “{cell('marketplace')}” but you are importing a {mp.title()} report.")
        vals: dict[str, int | None] = {}
        for m in metrics:
            v = cell(m)
            if _missing(v):
                vals[m] = None
                continue
            try:
                vals[m] = parse_paise(v) if m == "sales" else parse_count(v)
            except ValueError as e:
                _row_error(errors, n, f"Row {n}: {m} “{v}” {e}.")
        if len(errors) > bad or d is None:
            continue
        if vals.get("clicks") is not None and vals.get("impressions") is not None and vals["clicks"] > vals["impressions"]:  # type: ignore[operator]
            _row_error(errors, n, f"Row {n}: clicks ({vals['clicks']}) are more than impressions ({vals['impressions']}).")
            continue
        if all(vals.get(m) is None for m in metrics):
            warnings.append(f"Row {n} has no values for any metric and was skipped.")
            continue
        if vals.get("orders") is not None and vals.get("clicks") is not None and vals["orders"] > vals["clicks"]:  # type: ignore[operator]
            warnings.append(f"Row {n}: orders ({vals['orders']}) are more than clicks ({vals['clicks']}); the conversion rate will be shown as reported by these counts.")
        key = (sku, d)
        sig = tuple(vals.get(m) for m in metrics)
        if key in seen:
            first, was = seen[key]
            if was == sig:
                dup_same += 1
            else:
                _row_error(errors, n, f"Row {n}: {sku} on {d.isoformat()} is repeated with different numbers (first seen on row {first}).")
            continue
        seen[key] = (n, sig)
        lines.append({"row": n, "sku": sku, "date": d, **{m: vals.get(m) for m in METRICS}})
    if dup_same:
        warnings.append(f"{dup_same} repeated row(s) with identical numbers were counted once.")
    if not lines and not errors:
        _row_error(errors, 0, "No usable rows were found.")
    base["lines"] = lines
    base["metrics"] = metrics
    base["rowCount"] = len(lines)
    if lines:
        base["period"] = (min(x["date"] for x in lines), max(x["date"] for x in lines))
    return _done(base)


def _done(r: dict[str, Any]) -> dict[str, Any]:
    r["errorCount"] = len(r["errors"])
    r["errors"] = r["errors"][:MAX_SHOWN]
    r["ok"] = r["errorCount"] == 0
    return r
