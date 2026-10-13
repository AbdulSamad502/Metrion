"""Reading a spreadsheet the seller attached to a CEO conversation as TABLES, and answering questions about it with code (never with a model).

What this is: a bounded, defensive parser (CSV, XLSX) that keeps sheet names, the header row, file row numbers, blank cells and column types, plus a fixed set of
deterministic analyses (describe, totals, fee categories, returns, duplicates, data-quality checks, cross-file comparison). Every figure is computed here from the
file's own cells with `Decimal` and carries where it came from (file, sheet, column, rows). No language model sees a cell or does any arithmetic.

What this is NOT: an import. Nothing here touches the financial ledger, the engine, or any table; the figures are labelled "from your attached file", are never an
engine result and are never verified. Persistent records and formal reconciliation stay with Profit & Finance.

Cell values are untrusted data. Nothing is evaluated (an XLSX is read for cached values only, never calculated; a CSV cell that starts with = + - @ is just text), no
link is followed, and text from a cell is only ever echoed back inside quotes as a value, never as an instruction.

The limits below are technical guards against a pathological file (like `ceo_attachments.EXTRACT_TIMEOUT_SECONDS`), not business settings; when one is hit it is said.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

MAX_SHEETS = 10
MAX_ROWS = 50_000  # data rows read per sheet
MAX_COLS = 100
MAX_CELL_CHARS = 200
MAX_LISTED = 5  # rows named as examples


class UnreadableTable(ValueError):
    """The file could not be read as a table (the message is safe to show)."""


# ------------------------------------------------------------------------------------------------ model
@dataclass(slots=True)
class Column:
    name: str
    kind: str  # number | date | text | empty
    values: list[Any]  # Decimal | date | str | None per data row (None = a blank cell, never zero)
    bad_rows: list[int]  # file row numbers whose cell did not fit the column's kind (e.g. text in a number column)
    amount_like: bool
    had_currency_symbol: bool = False

    @property
    def non_blank(self) -> int:
        return sum(1 for v in self.values if v is not None)


@dataclass(slots=True)
class Sheet:
    name: str
    header_row: int | None  # the file row number of the header; None when the sheet has no header row (columns are then named "Column N")
    columns: list[Column]
    row_numbers: list[int]  # file row number of each data row
    ragged_rows: list[int] = field(default_factory=list)  # rows whose cell count differs from the header's
    truncated_rows: bool = False
    truncated_cols: bool = False
    skipped_empty_rows: int = 0
    formulas_without_value: int = 0  # XLSX cells that hold a formula with no stored result: read as blank, never calculated

    @property
    def n_rows(self) -> int:
        return len(self.row_numbers)

    @property
    def span(self) -> str:
        return f"rows {self.row_numbers[0]}-{self.row_numbers[-1]}" if self.row_numbers else "no data rows"


@dataclass(slots=True)
class Workbook:
    filename: str
    kind: str  # CSV | XLSX
    sheets: list[Sheet]
    sheets_truncated: bool = False
    dates_day_first: bool = False  # a slash date such as 03/04/2026 was read day first


# ------------------------------------------------------------------------------------------------ cell parsing
_AMOUNT_WORDS = re.compile(
    r"amount|price|total|fee|charge|commission|settle|refund|tax|gst|tcs|tds|discount|value|payout|revenue|sales|shipping|cost|mrp|incentive|penalty|deduction|adjust|reimburs|cashback|"
    r"royalty|closing|collection|net|gross|igst|cgst|sgst", re.IGNORECASE)
_ID_WORDS = re.compile(r"(?:^|[^a-z])(?:id|ids|no|number|num|ref|reference|awb|sku|utr|asin|fsn|hsn|pincode|pin|gstin|invoice|order|suborder|sub order|transaction|settlement|shipment|tracking)(?:[^a-z]|$)", re.IGNORECASE)
_DATE_HEADER = re.compile(r"date|time|period|day|month|settled|placed|shipped|delivered|returned", re.IGNORECASE)
# Numeric columns that are never money even when their header also contains a money word ("GST Filing Year", "Ship To Postal Code", "Igst Rate"): they are not summed or
# ranked as amounts. Detected from the header only; the cells are still read, and the column is listed with its plain type.
_NOT_MONEY_WORDS = re.compile(r"year|postal|post ?code|zip|pin ?code|\bcode\b|\brate\b|percent|pct|%|month|quarter|\bfy\b", re.IGNORECASE)
_QTY_WORDS = re.compile(r"quantity|qty|units|count|weight", re.IGNORECASE)
_CURRENCY = re.compile(r"₹|\brs\.?|\binr\b", re.IGNORECASE)
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%b %d, %Y")
_SLASH_DAY_FIRST = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{4}")


def _clean(v: Any) -> Any:
    """A raw cell as a value or None (blank). Strings are trimmed and bounded; nothing is evaluated."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s[:MAX_CELL_CHARS] if s else None
    return v


def parse_number(s: str) -> tuple[Decimal | None, bool]:
    """(value, had_currency_symbol). Handles 1,23,456.78, (123.45) as negative, a trailing minus, ₹ / Rs. / INR. Anything else is not a number (a leading zero or an overlong
    digit string is an identifier, not an amount)."""
    t = s.strip()
    symbol = bool(_CURRENCY.search(t))
    t = _CURRENCY.sub("", t).strip()
    negative = False
    if t.startswith("(") and t.endswith(")"):
        negative, t = True, t[1:-1].strip()
    if t.startswith("-"):
        negative, t = True, t[1:].strip()
    elif t.endswith("-"):
        negative, t = True, t[:-1].strip()
    t = t.replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None, symbol
    if (len(t.split(".")[0]) > 1 and t.startswith("0") and "." not in t) or len(t.replace(".", "")) > 15:
        return None, symbol  # an identifier such as 00123 or a 16-digit order number, not an amount
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None, symbol
    return (-d if negative else d), symbol


def parse_date(s: str) -> tuple[date | None, bool]:
    """(date, was_slash_day_first)."""
    t = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date(), bool(_SLASH_DAY_FIRST.match(t)) and fmt.startswith("%d")
        except ValueError:
            continue
    return None, False


def _classify_cell(v: Any, id_like: bool) -> tuple[str, Any, bool, bool]:
    """(kind, value, currency_symbol, day_first) for one non-blank cell."""
    if isinstance(v, bool):
        return "text", str(v), False, False
    if isinstance(v, datetime):
        return "date", v.date(), False, False
    if isinstance(v, date):
        return "date", v, False, False
    if isinstance(v, (int, float, Decimal)):
        if id_like:
            return "text", (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)), False, False
        return "number", Decimal(str(v)), False, False  # via the shortest decimal text, never float arithmetic
    s = str(v)
    if id_like:
        return "text", s, False, False
    d, day_first = parse_date(s)
    if d is not None:
        return "date", d, False, day_first
    n, sym = parse_number(s)
    if n is not None:
        return "number", n, sym, False
    return "text", s, False, False


def _dedupe_headers(names: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for n in names:
        seen[n] += 1
        out.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return out


def _build_sheet(name: str, grid: list[tuple[int, list[Any]]], *, skipped_empty: int, truncated_rows: bool, truncated_cols: bool, formulas: int, wb_flags: dict[str, bool]) -> Sheet:
    if not grid:
        return Sheet(name, None, [], [], skipped_empty_rows=skipped_empty, truncated_rows=truncated_rows, truncated_cols=truncated_cols, formulas_without_value=formulas)
    first_no, first = grid[0]
    # a header row is one whose filled cells are not all numbers or dates (a sheet that starts with data has no header)
    filled = [c for c in first if c is not None]
    looks_like_data = bool(filled) and all(_classify_cell(c, False)[0] in ("number", "date") for c in filled)
    width = max(len(first), 1)
    if looks_like_data:
        header_row, names, body = None, [f"Column {i + 1}" for i in range(width)], grid
        width = max((len(r) for _, r in grid), default=width)
        names = [f"Column {i + 1}" for i in range(width)]
    else:
        header_row = first_no
        names = [str(c)[:MAX_CELL_CHARS] if c is not None else f"Column {i + 1}" for i, c in enumerate(first)]
        body = grid[1:]
    names = _dedupe_headers(names)
    ragged: list[int] = []
    rows: list[list[Any]] = []
    row_numbers: list[int] = []
    for no, r in body:
        if len(r) != len(names):
            ragged.append(no)
        rows.append((r + [None] * len(names))[: len(names)])
        row_numbers.append(no)
    columns: list[Column] = []
    for ci, cname in enumerate(names):
        id_like = bool(_ID_WORDS.search(cname)) and not _AMOUNT_WORDS.search(cname) and not _DATE_HEADER.search(cname) and not _QTY_WORDS.search(cname)
        kinds: list[str] = []
        parsed: list[Any] = []
        symbol = False
        for r in rows:
            v = r[ci]
            if v is None:
                kinds.append("blank")
                parsed.append(None)
                continue
            k, val, sym, dfirst = _classify_cell(v, id_like)
            symbol = symbol or sym
            wb_flags["day_first"] = wb_flags.get("day_first", False) or dfirst
            kinds.append(k)
            parsed.append(val)
        counts = Counter(k for k in kinds if k != "blank")
        total = sum(counts.values())
        if total == 0:
            kind = "empty"
        else:
            top, n = counts.most_common(1)[0]
            kind = top if n * 10 >= total * 9 else "text"  # 90% of the filled cells must agree, otherwise the column is text
        values: list[Any] = []
        bad: list[int] = []
        for no, k, val, r in zip(row_numbers, kinds, parsed, rows):
            if k == "blank":
                values.append(None)
            elif kind == "text":
                values.append(str(r[ci]) if not isinstance(val, str) else val)
            elif k == kind:
                values.append(val)
            else:
                values.append(None)  # a cell that does not fit the column is not counted; its row is named
                bad.append(no)
        amount_like = kind == "number" and (bool(_AMOUNT_WORDS.search(cname)) or symbol) and not id_like and not _NOT_MONEY_WORDS.search(cname)
        columns.append(Column(cname, kind, values, bad, amount_like, symbol))
    return Sheet(name, header_row, columns, row_numbers, ragged_rows=ragged, truncated_rows=truncated_rows, truncated_cols=truncated_cols,
                 skipped_empty_rows=skipped_empty, formulas_without_value=formulas)


def read_csv(data: bytes, filename: str) -> Workbook:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            raise UnreadableTable("That file is not readable text.") from None
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    grid: list[tuple[int, list[Any]]] = []
    empty = 0
    truncated_rows = truncated_cols = False
    try:
        for no, row in enumerate(csv.reader(io.StringIO(text), dialect), start=1):
            cells = [_clean(c) for c in row]
            if all(c is None for c in cells):
                empty += 1
                continue
            if len(cells) > MAX_COLS:
                cells, truncated_cols = cells[:MAX_COLS], True
            if len(grid) > MAX_ROWS:  # one header plus MAX_ROWS data rows
                truncated_rows = True
                break
            grid.append((no, cells))
    except csv.Error as exc:
        raise UnreadableTable(f"That CSV is malformed ({str(exc)[:80]}).") from None
    flags: dict[str, bool] = {}
    sheet = _build_sheet("(CSV)", grid, skipped_empty=empty, truncated_rows=truncated_rows, truncated_cols=truncated_cols, formulas=0, wb_flags=flags)
    return Workbook(filename, "CSV", [sheet], dates_day_first=flags.get("day_first", False))


def read_xlsx(data: bytes, filename: str) -> Workbook:
    from openpyxl import load_workbook  # type: ignore[import-untyped]

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)  # cached values only: a formula is never evaluated
    except Exception:  # noqa: BLE001 - a corrupt workbook is "unreadable", never a stack trace
        raise UnreadableTable("That workbook could not be opened.") from None
    sheets: list[Sheet] = []
    flags: dict[str, bool] = {}
    names = wb.sheetnames
    for ws in [wb[n] for n in names[:MAX_SHEETS]]:
        grid: list[tuple[int, list[Any]]] = []
        empty = formulas = 0
        truncated_rows = truncated_cols = False
        for no, row in enumerate(ws.iter_rows(values_only=True), start=1):
            cells = [_clean(c) for c in row]
            while cells and cells[-1] is None:
                cells.pop()  # trailing blanks are the sheet's used-range padding, not data
            if not cells:
                empty += 1
                continue
            if len(cells) > MAX_COLS:
                cells, truncated_cols = cells[:MAX_COLS], True
            if len(grid) > MAX_ROWS:
                truncated_rows = True
                break
            grid.append((no, cells))
        sheets.append(_build_sheet(ws.title, grid, skipped_empty=empty, truncated_rows=truncated_rows, truncated_cols=truncated_cols, formulas=formulas, wb_flags=flags))
    try:
        wb.close()
    except Exception:  # noqa: BLE001
        pass
    return Workbook(filename, "XLSX", sheets, sheets_truncated=len(names) > MAX_SHEETS, dates_day_first=flags.get("day_first", False))


def read_table(data: bytes, kind: str, filename: str) -> Workbook:
    if kind == "CSV":
        return read_csv(data, filename)
    if kind == "XLSX":
        return read_xlsx(data, filename)
    raise UnreadableTable("Only CSV and XLSX files are read as tables.")


def summary(wb: Workbook) -> dict[str, Any]:
    """What the upload response shows the seller: the sheets and their sizes, and anything cut off. No cell values."""
    return {
        "sheets": [{"name": s.name, "rows": s.n_rows, "columns": len(s.columns), "headerRow": s.header_row, "truncated": s.truncated_rows or s.truncated_cols} for s in wb.sheets],
        "sheetsTruncated": wb.sheets_truncated,
    }


# ------------------------------------------------------------------------------------------------ formatting (code only)
def money(d: Decimal) -> str:
    return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def percent(part: Decimal, whole: Decimal) -> str:
    if whole == 0:
        return "n/a"
    return f"{(part * 100 / whole).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def _q(s: str) -> str:
    """A cell or header echoed back: quoted, bounded, on one line. It is data; it never reaches a model."""
    return "'" + " ".join(s.split())[:60] + "'"


def _rows(nums: list[int]) -> str:
    return ", ".join(str(n) for n in nums[:MAX_LISTED]) + (f" and {len(nums) - MAX_LISTED} more" if len(nums) > MAX_LISTED else "")


# ------------------------------------------------------------------------------------------------ analyses
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_FILENAME_MONTH = re.compile(r"(?<![a-z])(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\W_]*(20\d{2})(?!\d)", re.IGNORECASE)


def filename_month_hint(filename: str) -> tuple[date, date] | None:
    """(first day, last day) of a month-and-year written in the file name ("amazon_mtr_sep_2025.csv"), or None. A hint to check the dates against, never a period."""
    m = _FILENAME_MONTH.search(filename)
    if not m:
        return None
    month, year = _MONTHS[m.group(1).lower()], int(m.group(2))
    first = date(year, month, 1)
    return first, (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))


def describe(wb: Workbook) -> list[str]:
    out = [f"File {_q(wb.filename)} ({wb.kind}): {len(wb.sheets)} sheet{'s' if len(wb.sheets) != 1 else ''}."]
    if wb.sheets_truncated:
        out.append(f"Only the first {MAX_SHEETS} sheets were read; the rest were not.")
    for s in wb.sheets:
        label = "" if wb.kind == "CSV" else f"Sheet {_q(s.name)}: "
        head = f"header on row {s.header_row}" if s.header_row else "no header row, so the columns are named Column 1, Column 2..."
        out.append(f"{label}{s.n_rows} data rows ({s.span}), {len(s.columns)} columns, {head}.")
        out.append("Columns: " + "; ".join(f"{_q(c.name)} ({'amount' if c.amount_like else c.kind})" for c in s.columns[:25]) + (f"; and {len(s.columns) - 25} more" if len(s.columns) > 25 else "") + ".")
        if s.truncated_rows:
            out.append(f"This sheet has more than {MAX_ROWS:,} data rows: only the first {MAX_ROWS:,} were read, so every total below is for those rows only.")
        if s.truncated_cols:
            out.append(f"This sheet has more than {MAX_COLS} columns: only the first {MAX_COLS} were read.")
        if s.ragged_rows:
            out.append(f"{len(s.ragged_rows)} row{'s have' if len(s.ragged_rows) != 1 else ' has'} a different number of cells from the header (row {_rows(s.ragged_rows)}); missing cells are treated as blank and extra cells were ignored.")
        if s.skipped_empty_rows:
            out.append(f"{s.skipped_empty_rows} completely empty row{'s were' if s.skipped_empty_rows != 1 else ' was'} skipped.")
    if wb.dates_day_first:
        out.append("Dates written like 03/04/2026 are ambiguous (3 April or 4 March) and the file does not say which; I read them day first (3 April). Confirm this before relying on any period below.")
    p = _period(wb)
    if p is not None:
        out.append(f"Reporting period suggested by the dates in {_q(p[0])}: {p[1].isoformat()} to {p[2].isoformat()}" + (" (reading slash dates day first)." if wb.dates_day_first else "."))
        hint = filename_month_hint(wb.filename)
        if hint is not None and not (p[1] <= hint[1] and hint[0] <= p[2]):
            out.append(f"The file name suggests {hint[0].strftime('%B %Y')}, but its dates do not fall in that month, so the reporting period is unverified: check the file and the date format before using any total as that month's figure.")
    else:
        out.append("No date column was found, so the reporting period cannot be established from the file.")
    return out


def totals(wb: Workbook, limit: int = 12) -> list[str]:
    out: list[str] = []
    for s in wb.sheets:
        amounts = [c for c in s.columns if c.amount_like]
        if not amounts:
            continue
        ranked = sorted(amounts, key=lambda c: abs(sum((v for v in c.values if v is not None), Decimal(0))), reverse=True)[:limit]
        label = f"{_q(wb.filename)}" + ("" if wb.kind == "CSV" else f", sheet {_q(s.name)}")
        out.append(f"Totals of the amount columns in {label} (summed by code from the cells; blank cells are not counted as zero):")
        for c in ranked:
            vals = [v for v in c.values if v is not None]
            blanks = len(c.values) - len(vals) - len(c.bad_rows)
            note = f"{len(vals)} values summed" + (f", {blanks} blank" if blanks else "") + (f", {len(c.bad_rows)} not a number (row {_rows(c.bad_rows)})" if c.bad_rows else "")
            out.append(f"- {_q(c.name)}: {money(sum(vals, Decimal(0)))} ({note}; {s.span}).")
    if not out:
        out.append("No column in these files looks like an amount, so I have no totals to give.")
    return out


_FEE_HEADER = re.compile(r"fee|charge|commission|tcs|tds|gst|tax|shipping|penalty|deduction|closing|royalty|collection|adjust|cost|reverse", re.IGNORECASE)
_CATEGORY_HEADER = re.compile(r"type|category|description|particular|head|charge|fee|reason|status", re.IGNORECASE)


def fee_categories(wb: Workbook, limit: int = 10) -> list[str]:
    out: list[str] = []
    for s in wb.sheets:
        label = f"{_q(wb.filename)}" + ("" if wb.kind == "CSV" else f", sheet {_q(s.name)}")
        fee_cols = [c for c in s.columns if c.amount_like and _FEE_HEADER.search(c.name)]
        if fee_cols:
            sums = {c.name: sum((v for v in c.values if v is not None), Decimal(0)) for c in fee_cols}
            whole = sum((abs(v) for v in sums.values()), Decimal(0))
            out.append(f"Fee and charge columns in {label}, largest first (by size, ignoring sign; the share is of all these columns together):")
            for name, v in sorted(sums.items(), key=lambda kv: abs(kv[1]), reverse=True)[:limit]:
                out.append(f"- {_q(name)}: {money(v)} ({percent(abs(v), whole)}).")
            continue
        cats = [c for c in s.columns if c.kind == "text" and _CATEGORY_HEADER.search(c.name) and 1 < len({v for v in c.values if v is not None}) <= 40]
        amts = [c for c in s.columns if c.amount_like]
        if cats and amts:
            cat, amt = cats[0], next((a for a in amts if re.search(r"amount|total|value", a.name, re.IGNORECASE)), amts[0])
            groups: dict[str, Decimal] = defaultdict(Decimal)
            counted = 0
            for cv, av in zip(cat.values, amt.values):
                if cv is not None and av is not None:
                    groups[cv] += av
                    counted += 1
            whole = sum((abs(v) for v in groups.values()), Decimal(0))
            out.append(f"{label}: amounts in {_q(amt.name)} grouped by {_q(cat.name)}, largest first ({counted} rows with both values; rows missing either are left out):")
            for name, v in sorted(groups.items(), key=lambda kv: abs(kv[1]), reverse=True)[:limit]:
                out.append(f"- {_q(name)}: {money(v)} ({percent(abs(v), whole)}).")
            continue
        out.append(f"{label}: no column looks like a fee or charge, so I cannot list fee categories from it. Its columns are: " + ", ".join(_q(c.name) for c in s.columns[:15]) + ".")
    return out


_RETURN_WORD = re.compile(r"return|refund|cancel|rto|replac|reversal", re.IGNORECASE)


def returns(wb: Workbook) -> list[str]:
    out: list[str] = []
    for s in wb.sheets:
        label = f"{_q(wb.filename)}" + ("" if wb.kind == "CSV" else f", sheet {_q(s.name)}")
        found = False
        for c in s.columns:
            if c.kind == "text":
                dist = Counter(v for v in c.values if v is not None)
                hits = {k: n for k, n in dist.items() if _RETURN_WORD.search(k)}
                if hits and len(dist) <= 40:
                    found = True
                    filled = sum(dist.values())
                    out.append(f"{label}, column {_q(c.name)}: " + "; ".join(f"{_q(k)} on {n} of {filled} filled rows ({percent(Decimal(n), Decimal(filled))})" for k, n in sorted(hits.items(), key=lambda kv: -kv[1])[:6]) + ".")
            elif c.amount_like and _RETURN_WORD.search(c.name):
                found = True
                vals = [v for v in c.values if v is not None]
                out.append(f"{label}, column {_q(c.name)}: total {money(sum(vals, Decimal(0)))} over {len(vals)} rows with a value ({s.span}).")
        if not found:
            out.append(f"{label}: no column or status value mentions a return, refund or cancellation, so I cannot summarise returns from it.")
    return out


_KEY_HEADER = re.compile(r"order|sub ?order|transaction|settlement|invoice|awb|shipment|reference|ref\b|utr|id\b", re.IGNORECASE)


def duplicates(wb: Workbook) -> list[str]:
    out: list[str] = []
    for s in wb.sheets:
        label = f"{_q(wb.filename)}" + ("" if wb.kind == "CSV" else f", sheet {_q(s.name)}")
        rows_t = list(zip(*[c.values for c in s.columns])) if s.columns else []
        seen: dict[tuple[Any, ...], int] = {}
        exact: list[int] = []
        for no, tup in zip(s.row_numbers, rows_t):
            if all(v is None for v in tup):
                continue
            if tup in seen:
                exact.append(no)
            else:
                seen[tup] = no
        out.append(f"{label}: " + (f"{len(exact)} row{'s are' if len(exact) != 1 else ' is'} an exact copy of an earlier row (row {_rows(exact)})." if exact else "no row is an exact copy of another."))
        for c in s.columns:
            if c.kind == "text" and _KEY_HEADER.search(c.name):
                dist = Counter(v for v in c.values if v is not None)
                dup = {k: n for k, n in dist.items() if n > 1}
                if dup:
                    rows_of = {k: [no for no, v in zip(s.row_numbers, c.values) if v == k] for k in list(dup)[:MAX_LISTED]}
                    ex = "; ".join(f"{_q(k)} on rows {_rows(r)}" for k, r in rows_of.items())
                    out.append(f"- {_q(c.name)}: {len(dup)} value{'s appear' if len(dup) != 1 else ' appears'} more than once ({sum(dup.values()) - len(dup)} extra rows), for example {ex}. Repeats can be legitimate (an order with several items or fee lines); check before treating them as errors.")
    return out


def quality(wb: Workbook) -> list[str]:
    out: list[str] = []
    for s in wb.sheets:
        label = f"{_q(wb.filename)}" + ("" if wb.kind == "CSV" else f", sheet {_q(s.name)}")
        issues = 0
        for c in s.columns:
            if c.bad_rows:
                issues += 1
                out.append(f"- {label}, column {_q(c.name)}: {len(c.bad_rows)} cell{'s do' if len(c.bad_rows) != 1 else ' does'} not look like a {c.kind} (row {_rows(c.bad_rows)}); {'they were' if len(c.bad_rows) != 1 else 'it was'} left out of its figures.")
            if c.amount_like:
                blanks = len(c.values) - c.non_blank - len(c.bad_rows)
                neg = [no for no, v in zip(s.row_numbers, c.values) if v is not None and v < 0]
                if blanks:
                    issues += 1
                    out.append(f"- {label}, column {_q(c.name)}: {blanks} blank cell{'s' if blanks != 1 else ''}; blank is not zero, so they are not in its total.")
                if neg:
                    issues += 1
                    out.append(f"- {label}, column {_q(c.name)}: {len(neg)} negative value{'s' if len(neg) != 1 else ''} (row {_rows(neg)}). Refunds, fees and reversals are often negative; this is a row to check, not proof of a loss.")
        if s.ragged_rows:
            issues += 1
            out.append(f"- {label}: {len(s.ragged_rows)} row{'s' if len(s.ragged_rows) != 1 else ''} with the wrong number of cells (row {_rows(s.ragged_rows)}).")
        if s.formulas_without_value:
            issues += 1
            out.append(f"- {label}: {s.formulas_without_value} formula cell{'s' if s.formulas_without_value != 1 else ''} with no stored result were read as blank (formulas are never calculated here).")
        if not issues:
            out.append(f"- {label}: nothing odd found by these checks (blank or non-numeric amounts, negatives, short or long rows). That does not prove the data is right.")
    out.extend(duplicates(wb))
    return out


# ------------------------------------------------------------------------------------------------ cross-file
def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _period(wb: Workbook) -> tuple[str, date, date] | None:
    for s in wb.sheets:
        for c in s.columns:
            if c.kind == "date" and _DATE_HEADER.search(c.name):
                ds = [v for v in c.values if v is not None]
                if ds:
                    return c.name, min(ds), max(ds)
    return None


def compare(wbs: list[Workbook]) -> list[str]:
    out: list[str] = []
    if len(wbs) < 2:
        return ["A comparison needs two files attached; I only have one."]
    a, b = wbs[0], wbs[1]
    pa, pb = _period(a), _period(b)
    for w, p in ((a, pa), (b, pb)):
        out.append(f"{_q(w.filename)}: " + (f"dates in {_q(p[0])} run from {p[1].isoformat()} to {p[2].isoformat()}." if p else "no date column found, so its reporting period cannot be established from the file."))
    if pa is None or pb is None:
        same_period: bool | None = None
        out.append("Because the periods cannot both be established, I show each file's own figures side by side and do not compute any difference between them.")
    elif (pa[1], pa[2]) == (pb[1], pb[2]):
        same_period = True
        out.append("The two files cover the same date range in these columns. That is not the same as covering the same orders: an order report and a settlement report date the same order differently.")
    elif pa[2] < pb[1] or pb[2] < pa[1]:
        same_period = False
        out.append("The two files cover different, non-overlapping periods, so their totals are not comparable and I do not compute a difference.")
    else:
        same_period = False
        out.append("The two files overlap only partly in time, so their totals are not comparable and I do not compute a difference.")
    cols_a = {_norm(c.name): (c, s) for s in a.sheets for c in s.columns if c.amount_like}
    cols_b = {_norm(c.name): (c, s) for s in b.sheets for c in s.columns if c.amount_like}
    common = [k for k in cols_a if k in cols_b]
    for k in common[:10]:
        ca, _ = cols_a[k]
        cb, _ = cols_b[k]
        ta = sum((v for v in ca.values if v is not None), Decimal(0))
        tb = sum((v for v in cb.values if v is not None), Decimal(0))
        line = f"- {_q(ca.name)}: {money(ta)} in the first file, {money(tb)} in the second"
        if same_period:
            line += f"; difference {money(ta - tb)} (first minus second), for the totals of this column only."
        else:
            line += "; no difference computed."
        out.append(line)
    if not common:
        out.append("The two files share no amount column with the same name, so there is nothing to compare column by column.")
    keys_a = {_norm(c.name): c for s in a.sheets for c in s.columns if c.kind == "text" and _KEY_HEADER.search(c.name)}
    keys_b = {_norm(c.name): c for s in b.sheets for c in s.columns if c.kind == "text" and _KEY_HEADER.search(c.name)}
    for k in [k for k in keys_a if k in keys_b][:3]:
        sa = {v for v in keys_a[k].values if v is not None}
        sb = {v for v in keys_b[k].values if v is not None}
        both = sa & sb
        out.append(f"- Identifier {_q(keys_a[k].name)}: {len(both)} appear in both files, {len(sa - sb)} only in the first, {len(sb - sa)} only in the second. These counts are exact matches of the cell text.")
        if sa and sb and len(both) * 2 > min(len(sa), len(sb)):
            same_cols = {_norm(c.name) for s in a.sheets for c in s.columns} == {_norm(c.name) for s in b.sheets for c in s.columns}
            if same_cols:
                out.append("These two files have the same columns and share most identifiers: adding them together would count the same records twice.")
    return out


# ------------------------------------------------------------------------------------------------ the question -> the analyses (a closed menu, no model)
_ASK_WORDS = re.compile(
    r"\b(?:attached|attachment|file|files|report|reports|spreadsheet|sheet|sheets|csv|xlsx|excel|settlement|settlements|orders?|sales|returns?|refunds?|fees?|charges?|commission|duplicate|duplicates|summari[sz]e|summary|total|totals|"
    r"largest|biggest|compare|comparison|reconcile|suspicious|inconsisten\w*|leaks?|mismatch\w*|what(?:'s| is) in|read)\b", re.IGNORECASE)
DEFAULT_MESSAGE = "Please read what I attached."


def is_analysis_request(text: str) -> bool:
    t = text.strip()
    return not t or t == DEFAULT_MESSAGE or bool(_ASK_WORDS.search(t))


HEADER = ("Here is what I can establish from the file you attached in this conversation. I calculated every figure below with code from the file's own cells; none of it comes from your saved financial "
          "records, and nothing was imported, saved or changed.")
FOOTER = ("These figures are from your attached file only. Metrion has not verified them against your saved records, and they are not saved anywhere. For persistent financial records and formal marketplace "
          "reconciliation, use Profit & Finance.")


def analyse(wbs: list[Workbook], question: str) -> str:
    t = question.lower()
    lines: list[str] = [HEADER, ""]
    for w in wbs:
        lines += describe(w) + [""]
    asked_something = False
    if re.search(r"fee|charge|commission|largest|biggest|cost|deduction", t):
        asked_something = True
        lines.append("Fee categories:")
        for w in wbs:
            lines += fee_categories(w)
        lines.append("")
    if re.search(r"return|refund|cancel|rto", t):
        asked_something = True
        lines.append("Returns and refunds:")
        for w in wbs:
            lines += returns(w)
        lines.append("")
    if re.search(r"duplicate|double|twice|repeated", t):
        asked_something = True
        lines.append("Duplicates:")
        for w in wbs:
            lines += duplicates(w)
        lines.append("")
    if re.search(r"suspicious|inconsisten|wrong|error|anomal|mismatch|leak|odd|problem|check", t):
        asked_something = True
        lines.append("Rows and columns worth checking:")
        for w in wbs:
            lines += quality(w)
        lines.append("")
    if len(wbs) > 1 and re.search(r"compar|reconcil|versus|\bvs\b|match|settlement|differ", t):
        asked_something = True
        lines.append("Comparing the two files:")
        lines += compare(wbs)
        lines.append("")
    if not asked_something or re.search(r"summar|total|sales|revenue|what(?:'s| is) in|read|overview", t) or not t.strip():
        for w in wbs:
            lines += totals(w) + [""]
    if re.search(r"profit|margin|cogs|cost price|net earn", t):
        lines.append("Profit and margin need your product costs and every fee, which these files alone do not establish; I have not estimated them. Save your costs and import the reports in Profit & Finance for a verified profit figure.")
        lines.append("")
    lines.append(FOOTER)
    return "\n".join(lines).strip()
