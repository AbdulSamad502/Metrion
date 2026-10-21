"""Duplicate classification before financial posting (cfo-data-intelligence.md §6.3, owner requirement 4).

Every row is classified by two measurements — an *identity* (who the row claims to be) and a *raw-row
hash* (what the row says) — against rows already seen in this file and rows already ingested:

    NEW                        post
    EXACT_DUPLICATE_CROSS_FILE overlapping upload: skip, counted and disclosed
    EXACT_DUPLICATE_IN_FILE    identity-strong repeat of an identical row: skip, WARNING V-DUP-001
    CONFLICT_CROSS_FILE        same identity, different content as earlier data: HOLD, ERROR V-DUP-003
    CONFLICT_IN_FILE           same identity, different content earlier in this file: HOLD, ERROR V-DUP-003
    AMBIGUOUS_REPEAT           identical repeat that cannot be told from a double export: HOLD, ERROR V-DUP-002

Legitimate repeats are preserved by construction: the settlement identity includes the settlement id, date
and amount, so partial settlements and adjustments of one order are different identities; the sales identity
adds `(sku, marketplace_item_id)` when there is no `line_ref`, so two items of one order are different
identities. Where the available columns cannot distinguish two entries, the second is held with a plain
explanation — never posted twice, never silently dropped.

Pure: no database, no clock. The caller supplies the existing rows' identity fields and stored raw row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from data_foundation.types import ParsedRow
from data_foundation.validation.severity import Finding, Severity

SALES = "SALES"
SETTLEMENT = "SETTLEMENT"

V_DUP_IN_FILE = "V-DUP-001"
V_DUP_AMBIGUOUS = "V-DUP-002"
V_DUP_CONFLICT = "V-DUP-003"


class DupClass(str, Enum):
    NEW = "NEW"
    EXACT_DUPLICATE_CROSS_FILE = "EXACT_DUPLICATE_CROSS_FILE"
    EXACT_DUPLICATE_IN_FILE = "EXACT_DUPLICATE_IN_FILE"
    CONFLICT_CROSS_FILE = "CONFLICT_CROSS_FILE"
    CONFLICT_IN_FILE = "CONFLICT_IN_FILE"
    AMBIGUOUS_REPEAT = "AMBIGUOUS_REPEAT"

    @property
    def posts(self) -> bool:
        return self is DupClass.NEW

    @property
    def held(self) -> bool:
        return self in (DupClass.CONFLICT_CROSS_FILE, DupClass.CONFLICT_IN_FILE, DupClass.AMBIGUOUS_REPEAT)

    @property
    def skipped_as_duplicate(self) -> bool:
        return self in (DupClass.EXACT_DUPLICATE_CROSS_FILE, DupClass.EXACT_DUPLICATE_IN_FILE)


@dataclass(frozen=True, slots=True)
class DupDecision:
    source_row_number: int
    klass: DupClass
    finding: Finding | None = None
    first_seen_row: int | None = None  # the earlier row of this file that this one repeats/conflicts with


@dataclass(frozen=True, slots=True)
class ExistingEntry:
    """What the database remembers about an already-ingested row: its identity digest and raw-row hash."""

    identity: bytes
    raw_hash: bytes


def _norm(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _digest(parts: Sequence[str]) -> bytes:
    return hashlib.blake2b("\x1f".join(parts).encode("utf-8"), digest_size=16).digest()


def raw_row_hash(source_row_json: Mapping[str, str]) -> bytes:
    """Order-independent digest of a row's source columns (values stripped)."""
    canon = json.dumps({str(k): _norm(v) for k, v in source_row_json.items()}, sort_keys=True, separators=(",", ":"))
    return _digest([canon])


@dataclass(frozen=True, slots=True)
class Identity:
    digest: bytes
    strong: bool  # True when the row carries enough to tell it apart from a different row of the same order
    none: bool = False  # True when the row carries no identity fields at all


def sales_identity(marketplace: str, f: Mapping[str, object]) -> Identity:
    order_ref, line_ref, invoice_ref = _norm(f.get("order_ref")), _norm(f.get("line_ref")), _norm(f.get("invoice_ref"))
    sku, item_id = _norm(f.get("sku")), _norm(f.get("marketplace_item_id"))
    if not (order_ref or line_ref or invoice_ref):
        return Identity(digest=b"", strong=False, none=True)
    parts = [SALES, marketplace, order_ref, line_ref, invoice_ref]
    if not line_ref:
        parts += [sku, item_id]
    strong = bool(line_ref or sku or item_id)
    return Identity(digest=_digest(parts), strong=strong)


def settlement_identity(marketplace: str, f: Mapping[str, object]) -> Identity:
    order_ref, line_ref = _norm(f.get("order_ref")), _norm(f.get("line_ref"))
    sid, sdate, amount = _norm(f.get("settlement_id")), _norm(f.get("settlement_date")), _norm(f.get("gross_settlement_amount"))
    if not (order_ref or line_ref or sid):
        return Identity(digest=b"", strong=False, none=True)
    # A settlement identity is never "strong": identical settlement rows cannot be told from a double export.
    return Identity(digest=_digest([SETTLEMENT, marketplace, order_ref, line_ref, sid, sdate, amount]), strong=False)


def existing_sales_entry(marketplace: str, row: Mapping[str, object], source_row_json: Mapping[str, str]) -> ExistingEntry | None:
    ident = sales_identity(marketplace, row)
    return None if ident.none else ExistingEntry(ident.digest, raw_row_hash(source_row_json))


def existing_settlement_entry(marketplace: str, row: Mapping[str, object], source_row_json: Mapping[str, str]) -> ExistingEntry | None:
    ident = settlement_identity(marketplace, row)
    return None if ident.none else ExistingEntry(ident.digest, raw_row_hash(source_row_json))


class DuplicateTracker:
    """Per-file classifier. Feed it chunks in order; it remembers one digest pair per distinct identity
    (about 130 bytes each — see cfo-data-intelligence.md OQ6 for the very-large-file stance)."""

    def __init__(self, side: str, marketplace: str) -> None:
        if side not in (SALES, SETTLEMENT):
            raise ValueError(f"unknown side {side!r}")
        self._side = side
        self._marketplace = marketplace
        self._seen: dict[bytes, tuple[bytes, int]] = {}  # identity -> (raw hash, first row number)
        self._seen_identityless: dict[bytes, int] = {}  # raw hash -> first row number (rows with no identity fields)

    def _identity(self, fields: Mapping[str, object]) -> Identity:
        return sales_identity(self._marketplace, fields) if self._side == SALES else settlement_identity(self._marketplace, fields)

    def classify(self, rows: Sequence[ParsedRow], existing: Iterable[ExistingEntry]) -> list[DupDecision]:
        prior: dict[bytes, set[bytes]] = {}
        for e in existing:
            prior.setdefault(e.identity, set()).add(e.raw_hash)

        out: list[DupDecision] = []
        for row in rows:
            n = row.source_row_number
            rh = raw_row_hash(row.source_row_json)
            ident = self._identity(row.canonical_fields)

            if ident.none:
                # No identity at all: it cannot be matched to earlier data (the file-level content hash is the only
                # guard across files), but an identical repeat inside this file is indistinguishable from a double export.
                first = self._seen_identityless.get(rh)
                if first is not None:
                    out.append(DupDecision(n, DupClass.AMBIGUOUS_REPEAT, _ambiguous(n, first), first))
                else:
                    self._seen_identityless[rh] = n
                    out.append(DupDecision(n, DupClass.NEW))
                continue

            seen = self._seen.get(ident.digest)
            if seen is not None:
                seen_hash, first = seen
                if seen_hash == rh:
                    if ident.strong:
                        out.append(DupDecision(n, DupClass.EXACT_DUPLICATE_IN_FILE, _in_file(n, first), first))
                    else:
                        out.append(DupDecision(n, DupClass.AMBIGUOUS_REPEAT, _ambiguous(n, first), first))
                else:
                    out.append(DupDecision(n, DupClass.CONFLICT_IN_FILE, _conflict_in_file(n, first), first))
                continue

            self._seen[ident.digest] = (rh, n)
            hashes = prior.get(ident.digest)
            if hashes is None:
                out.append(DupDecision(n, DupClass.NEW))
            elif rh in hashes:
                out.append(DupDecision(n, DupClass.EXACT_DUPLICATE_CROSS_FILE))
            else:
                out.append(DupDecision(n, DupClass.CONFLICT_CROSS_FILE, _conflict_cross(n)))
        return out


def _in_file(n: int, first: int) -> Finding:
    return Finding(V_DUP_IN_FILE, Severity.WARNING,
                   f"Row {n} repeats row {first} exactly (same order line, same values). It was counted once and the repeat was skipped.", n)


def _ambiguous(n: int, first: int) -> Finding:
    return Finding(V_DUP_AMBIGUOUS, Severity.ERROR,
                   f"Row {n} is identical to row {first} and nothing in the file tells them apart, so it cannot be known whether this is a "
                   f"double export or two genuine identical entries. Row {n} was held and not posted. If both are real, add a distinguishing "
                   f"reference (for example a settlement id or line id) and upload again.", n)


def _conflict_in_file(n: int, first: int) -> Finding:
    return Finding(V_DUP_CONFLICT, Severity.ERROR,
                   f"Row {n} has the same order line as row {first} but different values, so it is unclear which is current. "
                   f"The first was kept; row {n} was held and not posted.", n)


def _conflict_cross(n: int) -> Finding:
    return Finding(V_DUP_CONFLICT, Severity.ERROR,
                   f"Row {n} has the same order line as a row you uploaded earlier but different values (a correction, a status change or a "
                   f"different report version). It was held and not posted; replacing the earlier row needs your confirmation.", n)
