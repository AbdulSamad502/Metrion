"""Expense CSV import: the fixed template, row-level validation and duplicate detection (kickoff S5a; expense-tracker.md import rules, X10, Q22, Q29).

Pure functions over the uploaded bytes and a list of existing ledger rows; no database, no clock. A preview writes nothing; a commit writes only through the ledger
repository as `pending_review` records that the seller confirms (confirmation needs `financials.adjust`, like every ledger write). The raw CSV is never stored: only the
parsed fields of accepted rows, a short reference to the file (the start of its SHA-256) and the row number, which is also what makes a re-upload of the same file safe.

The one conversion here is text to integer paise for the rupee column (whole-and-fraction digit handling, no float); no amount is ever added, compared for size or rounded.
Amounts are costs (zero or positive); a refund or credit note is entered through the refund action, not imported.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

from backend.services import expense_ledger_rules as rules

TEMPLATE_COLUMNS: tuple[str, ...] = ("date", "vendor", "description", "category", "amount_rupees", "source_id", "channel")
MAX_BYTES = 1_000_000  # PROPOSED (R9-5)
MAX_ROWS = 2_000  # PROPOSED (R9-5)
SOURCE_ID_MAX = 80

OK = "OK"
ERROR = "ERROR"
DUPLICATE = "DUPLICATE"  # the same source id is already in the ledger: skipped, and reported
PROBABLE_MATCH = "PROBABLE_MATCH"  # same date, vendor, amount and description as an existing record: imported for review, flagged, never dropped

_AMOUNT = re.compile(r"^([0-9]{1,11})(?:\.([0-9]{1,2}))?$")


@dataclass(slots=True)
class ParsedRow:
    number: int  # 1-based data row (the header is row 0)
    date: date | None = None
    vendor: str | None = None
    description: str | None = None
    category: str | None = None
    amount_paise: int | None = None
    source_id: str | None = None
    channel: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def reference(self) -> str:
        """What the ledger keeps as `source_reference`: the seller's own id when there is one, else this file's short hash and the row number (set by the caller)."""
        return f"import:{self.source_id}" if self.source_id else ""


@dataclass(slots=True)
class ParseResult:
    sha256: str
    rows: list[ParsedRow]
    file_errors: list[str]


@dataclass(slots=True)
class Classified:
    row: ParsedRow
    status: str
    matches: list[str] = field(default_factory=list)  # ids of the existing records it matches
    note: str | None = None


def rupees_to_paise(text: str) -> int | None:
    """`1200`, `1200.5`, `1200.50` -> paise as an integer; anything else (sign, grouping, exponent, more than two decimals, currency) -> None. No float."""
    m = _AMOUNT.match(text.strip())
    if m is None:
        return None
    whole, frac = m.group(1), (m.group(2) or "").ljust(2, "0")
    return int(whole) * 100 + int(frac)


def normalise(text: str | None) -> str:
    """Case-folded alphanumerics with single spaces: 'ACME  Realty, Pvt.' and 'acme realty pvt' compare equal."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (text or "").lower()).split())


def template_csv() -> str:
    return ",".join(TEMPLATE_COLUMNS) + "\r\n"


def parse_csv(data: bytes) -> ParseResult:
    sha = hashlib.sha256(data).hexdigest()
    if len(data) > MAX_BYTES:
        return ParseResult(sha, [], [f"The file is larger than {MAX_BYTES // 1000} KB."])
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ParseResult(sha, [], ["The file is not UTF-8 text. Save it as CSV (UTF-8) and try again."])
    if "\x00" in text:
        return ParseResult(sha, [], ["The file does not look like a CSV."])
    try:
        records = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        return ParseResult(sha, [], [f"The file is not valid CSV: {exc}"])
    records = [r for r in records if any(cell.strip() for cell in r)]  # blank lines are skipped
    if not records:
        return ParseResult(sha, [], ["The file is empty."])
    header = [h.strip().lower() for h in records[0]]
    if sorted(header) != sorted(TEMPLATE_COLUMNS) or len(set(header)) != len(header):
        return ParseResult(sha, [], [f"The header must be exactly these columns (any order): {', '.join(TEMPLATE_COLUMNS)}."])
    body = records[1:]
    if len(body) > MAX_ROWS:
        return ParseResult(sha, [], [f"The file has more than {MAX_ROWS} rows."])
    rows: list[ParsedRow] = []
    for n, cells in enumerate(body, start=1):
        row = ParsedRow(n)
        if len(cells) != len(header):
            row.errors.append(f"Expected {len(header)} columns but found {len(cells)}.")
            rows.append(row)
            continue
        cell = {name: value.strip() for name, value in zip(header, cells)}
        _fill(row, cell)
        rows.append(row)
    return ParseResult(sha, rows, [])


def _fill(row: ParsedRow, cell: Mapping[str, str]) -> None:
    try:
        row.date = date.fromisoformat(cell["date"]) if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", cell["date"]) else None
    except ValueError:
        row.date = None
    if row.date is None:
        row.errors.append("Date must be a real date written YYYY-MM-DD.")
    row.vendor = cell["vendor"] or None
    if row.vendor:
        if len(row.vendor) > rules.VENDOR_MAX:
            row.errors.append(f"Vendor is too long (at most {rules.VENDOR_MAX} characters).")
        elif (message := rules.vendor_error(row.vendor)) is not None:
            row.errors.append(message)
    row.description = cell["description"] or None
    if row.description and len(row.description) > rules.DESCRIPTION_MAX:
        row.errors.append(f"Description is too long (at most {rules.DESCRIPTION_MAX} characters).")
    row.category = cell["category"].lower() or None
    if row.category not in rules.CATEGORIES:
        row.errors.append("Category must be one of: " + ", ".join(sorted(rules.CATEGORIES)) + ".")
    paise = rupees_to_paise(cell["amount_rupees"])
    if paise is None:
        row.errors.append("Amount must be rupees such as 1200 or 1200.50 (no sign, commas or currency symbol).")
    elif (message := rules.amount_error(paise)) is not None:
        row.errors.append(message)
    else:
        row.amount_paise = paise
    row.source_id = cell["source_id"] or None
    if row.source_id and (len(row.source_id) > SOURCE_ID_MAX or not re.fullmatch(r"[A-Za-z0-9._/#:-]+", row.source_id)):
        row.errors.append(f"Source id may use letters, digits and . _ / # : - only, up to {SOURCE_ID_MAX} characters.")
    row.channel = cell["channel"].upper() or None
    if row.channel is not None and row.channel not in rules.CHANNEL_TAGS:
        row.errors.append("Channel must be one of: " + ", ".join(sorted(rules.CHANNEL_TAGS)) + " (or empty for the whole business).")


def _match_key(day: date | None, vendor: str | None, amount: int | None, description: str | None) -> tuple[Any, ...]:
    return (day, normalise(vendor), amount, normalise(description))


def classify(rows: Sequence[ParsedRow], existing: Sequence[Mapping[str, Any]]) -> list[Classified]:
    """`existing` = the tenant's non-voided ledger rows that could match (id, effective_date, vendor, description, amount_paise, source_reference).
    A row is: ERROR; DUPLICATE when its source id is already in the ledger or earlier in this file (skipped, reported); PROBABLE_MATCH when its date, normalised vendor,
    amount and normalised description equal an existing record's or an earlier row's (kept, flagged for review); else OK. Nothing is ever dropped without being listed."""
    by_ref: dict[str, list[str]] = {}
    by_key: dict[tuple[Any, ...], list[str]] = {}
    for e in existing:
        if e.get("source_reference"):
            by_ref.setdefault(str(e["source_reference"]).split(":probable")[0], []).append(str(e["id"]))  # a flagged probable match still owns its source id
        by_key.setdefault(_match_key(e["effective_date"], e.get("vendor"), e["amount_paise"], e.get("description")), []).append(str(e["id"]))
    seen_refs: dict[str, int] = {}
    seen_keys: dict[tuple[Any, ...], int] = {}
    out: list[Classified] = []
    for row in rows:
        if row.errors:
            out.append(Classified(row, ERROR))
            continue
        ref = row.reference
        key = _match_key(row.date, row.vendor, row.amount_paise, row.description)
        if ref and ref in by_ref:
            out.append(Classified(row, DUPLICATE, by_ref[ref], "This source id is already in the ledger."))
        elif ref and ref in seen_refs:
            out.append(Classified(row, DUPLICATE, [], f"The same source id appears on row {seen_refs[ref]} of this file."))
        else:
            matches = list(by_key.get(key, []))
            note = "Same date, vendor, amount and description as an existing entry." if matches else None
            if key in seen_keys:
                note = note or f"Same date, vendor, amount and description as row {seen_keys[key]} of this file."
            out.append(Classified(row, PROBABLE_MATCH if note else OK, matches, note))
            if ref:
                seen_refs[ref] = row.number
        seen_keys.setdefault(key, row.number)
    return out
