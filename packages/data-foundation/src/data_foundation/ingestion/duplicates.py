"""Duplicate classification before financial posting (cfo-data-intelligence.md §6.3, owner requirements 4 and 2026-10-21 decision).

Every row is classified by two measurements — an *identity* (who the row claims to be) and a *raw-row hash* (what the
row says) — against rows already seen in this file and rows already ingested **from the same report family**:

    NEW                        post
    EXACT_DUPLICATE_CROSS_FILE overlapping upload: skip, counted and disclosed
    EXACT_DUPLICATE_IN_FILE    identity-strong repeat of an identical row: skip, WARNING V-DUP-001
    CONFLICT_CROSS_FILE        same identity, different content as earlier data: HOLD, ERROR V-DUP-003
    CONFLICT_IN_FILE           same identity, different content earlier in this file: HOLD, ERROR V-DUP-003
    AMBIGUOUS_REPEAT           identical repeat that cannot be told from a double export: HOLD, ERROR V-DUP-002

**Report family.** A Meesho orders report and a Meesho TCS report both carry rows for the same sub-order; they are
different facts about it, not duplicates of each other. Identity therefore includes the report family (the adapter
id without its version suffix, or the confirmed mapping's file shape), so only a re-upload of the *same kind* of
report can overlap.

**Strong identity is defined per marketplace** (`MARKETPLACE_IDENTITY`), from what each marketplace's reports really
carry. A product id (SKU, ASIN, FSN) is never a line identity: the same product can appear on several lines of one
order. Where a row lacks the marketplace's line id, an identical repeat is held as ambiguous, never skipped.

**Legitimate financial events that share an order or shipment id** are different events and must not collide: a sale and its
credit note, a shipment and its refund, partial refunds, a replacement shipment, several shipments of one order. The identity
therefore also carries the **event discriminators** the row has: `document_type` (invoice / credit note ...) and
`transaction_type` (shipment / refund / adjustment ...) for sales rows, and `document_type` for settlement rows. When a report
does not carry them (today's verified adapters map neither) the rows are told apart by what they do carry (line id, amounts,
dates, descriptions); where that is not enough, two rows of one line with different content are a CONFLICT and an identical
repeat is AMBIGUOUS — held and explained, never merged and never silently both posted.

**Held rows are unresolved**: they are not posted, so they are excluded from every authoritative financial figure,
until the seller resolves them (resolution flow: spec OQ7/OQ10).

Pure: no database, no clock. The caller supplies the existing rows' identity fields and stored raw row.
"""

from __future__ import annotations

import hashlib
import json
import re
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


@dataclass(frozen=True, slots=True)
class MarketplaceIdentity:
    """What makes a row *this* row for one marketplace, from the columns its adapters really map."""

    sales_line_field: str  # canonical field holding the marketplace's unique line id — the only strong sales identity
    sales_line_meaning: str  # the marketplace's own name for it (documentation, and shown in explanations)
    settlement_fields: tuple[str, ...]  # canonical fields that together identify one settlement row; never strong


MARKETPLACE_IDENTITY: dict[str, MarketplaceIdentity] = {
    # Meesho orders/TCS: `Sub Order No` is the verified unique sub-order key (data-foundation.md §5.1). The Payments export
    # carries only the sub-order and the final amount — no settlement id or date — so its identity is just those two.
    "MEESHO": MarketplaceIdentity("line_ref", "Sub Order No", ("line_ref", "gross_settlement_amount")),
    # Amazon MTR: `Shipment Item ID` is the unique shipped-item id (ASIN is the product, not the line). Settlement V2 rows are
    # melted (one row per amount-type/description pair), so the identity includes the melted triple, the item codes and the id.
    "AMAZON": MarketplaceIdentity(
        "line_ref", "Shipment Item ID",
        ("order_ref", "order_item_code", "merchant_order_item_id", "shipment_id", "settlement_id", "settlement_amount_type",
         "settlement_amount_description", "settlement_amount_value"),
    ),
    # Flipkart sales report: `Line Item ID` is the unique line id (FSN is the product). Payments rows are identified by order, date, amount.
    "FLIPKART": MarketplaceIdentity("line_ref", "Line Item ID", ("order_ref", "settlement_id", "settlement_date", "gross_settlement_amount")),
}


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


_VERSION_SUFFIX = re.compile(r"\.v\d+$")


def report_family(adapter_id: str, mapping_fingerprint: str | None = None) -> str:
    """The kind of report a row came from. A verified adapter's family is its id without the version suffix (so a v2 of the same
    report still overlaps its v1); a seller-confirmed mapping's family is the file shape it was confirmed for."""
    if adapter_id.startswith("mapped."):
        if not mapping_fingerprint:
            raise ValueError("a mapped adapter's report family needs the mapping's file fingerprint")
        return f"mapped:{mapping_fingerprint}"
    return _VERSION_SUFFIX.sub("", adapter_id)


def _norm(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _event(v: object) -> str:
    """An event discriminator (document or transaction type), case/separator-insensitive: 'Credit Note' == 'CREDIT_NOTE'."""
    return re.sub(r"[\s_\-]+", "_", _norm(v).upper())


def _digest(parts: Sequence[str]) -> bytes:
    return hashlib.blake2b("\x1f".join(parts).encode("utf-8"), digest_size=16).digest()


def raw_row_hash(source_row_json: Mapping[str, str]) -> bytes:
    """Order-independent digest of a row's source columns (values stripped)."""
    canon = json.dumps({str(k): _norm(v) for k, v in source_row_json.items()}, sort_keys=True, separators=(",", ":"))
    return _digest([canon])


@dataclass(frozen=True, slots=True)
class Identity:
    digest: bytes
    strong: bool  # True only when the row carries the marketplace's own unique line id
    none: bool = False  # True when the row carries no identity fields at all


def _rules(marketplace: str) -> MarketplaceIdentity:
    rule = MARKETPLACE_IDENTITY.get(marketplace)
    if rule is None:
        # An unknown marketplace (not Amazon/Flipkart/Meesho) gets the conservative default: nothing is strong.
        return MarketplaceIdentity("line_ref", "line id", ())
    return rule


def sales_identity(marketplace: str, family: str, f: Mapping[str, object]) -> Identity:
    rule = _rules(marketplace)
    order_ref, invoice_ref = _norm(f.get("order_ref")), _norm(f.get("invoice_ref"))
    line = _norm(f.get(rule.sales_line_field))
    if not (order_ref or line or invoice_ref):
        return Identity(digest=b"", strong=False, none=True)
    parts = [SALES, family, marketplace, order_ref, line, invoice_ref, _event(f.get("document_type")), _event(f.get("transaction_type"))]
    if not line:
        # No line id: two product lines of one order must still not collapse into one, so the product ids join the digest, but the
        # row is not strong (a product id is not a line id).
        parts += [_norm(f.get("marketplace_item_id")), _norm(f.get("sku"))]
    return Identity(digest=_digest(parts), strong=bool(line))


def settlement_identity(marketplace: str, family: str, f: Mapping[str, object]) -> Identity:
    rule = _rules(marketplace)
    values = [_norm(f.get(name)) for name in rule.settlement_fields]
    if not any(_norm(f.get(n)) for n in ("order_ref", "line_ref", "settlement_id")):
        return Identity(digest=b"", strong=False, none=True)
    # A settlement identity is never "strong": identical settlement rows cannot be told from a double export.
    return Identity(digest=_digest([SETTLEMENT, family, marketplace, *rule.settlement_fields, *values, _event(f.get("document_type"))]), strong=False)


def existing_sales_entry(marketplace: str, family: str, row: Mapping[str, object], source_row_json: Mapping[str, str]) -> ExistingEntry | None:
    ident = sales_identity(marketplace, family, row)
    return None if ident.none else ExistingEntry(ident.digest, raw_row_hash(source_row_json))


def existing_settlement_entry(marketplace: str, family: str, row: Mapping[str, object], source_row_json: Mapping[str, str]) -> ExistingEntry | None:
    ident = settlement_identity(marketplace, family, row)
    return None if ident.none else ExistingEntry(ident.digest, raw_row_hash(source_row_json))


class DuplicateTracker:
    """Per-file classifier. Feed it chunks in order; it remembers one digest pair per distinct identity (about 130 bytes each: the
    memory cost that grows with the number of distinct rows — see cfo-data-intelligence.md AC-D1 and OQ6)."""

    def __init__(self, side: str, marketplace: str, family: str) -> None:
        if side not in (SALES, SETTLEMENT):
            raise ValueError(f"unknown side {side!r}")
        self._side = side
        self._marketplace = marketplace
        self._family = family
        self._seen: dict[bytes, tuple[bytes, int]] = {}  # identity -> (raw hash, first row number)
        self._seen_identityless: dict[bytes, int] = {}  # raw hash -> first row number (rows with no identity fields)

    def _identity(self, fields: Mapping[str, object]) -> Identity:
        fn = sales_identity if self._side == SALES else settlement_identity
        return fn(self._marketplace, self._family, fields)

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
                # No identity at all: it cannot be matched to earlier data (the file-level content hash is the only guard across
                # files), but an identical repeat inside this file is indistinguishable from a double export.
                first = self._seen_identityless.get(rh)
                if first is not None:
                    out.append(DupDecision(n, DupClass.AMBIGUOUS_REPEAT, _ambiguous(n, first, self._marketplace), first))
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
                        out.append(DupDecision(n, DupClass.AMBIGUOUS_REPEAT, _ambiguous(n, first, self._marketplace), first))
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


def _ambiguous(n: int, first: int, marketplace: str) -> Finding:
    rule = _rules(marketplace)
    return Finding(V_DUP_AMBIGUOUS, Severity.ERROR,
                   f"Row {n} is identical to row {first} and nothing in the file tells them apart (this report has no usable {rule.sales_line_meaning} "
                   f"for the row), so it cannot be known whether this is a double export or two genuine identical entries. Row {n} was held and not "
                   f"posted. If both are real, add a distinguishing reference (for example a settlement id or line id) and upload again.", n)


def _conflict_in_file(n: int, first: int) -> Finding:
    return Finding(V_DUP_CONFLICT, Severity.ERROR,
                   f"Row {n} has the same order line as row {first} but different values, so it is unclear which is current. "
                   f"The first was kept; row {n} was held and not posted.", n)


def _conflict_cross(n: int) -> Finding:
    return Finding(V_DUP_CONFLICT, Severity.ERROR,
                   f"Row {n} has the same order line as a row you uploaded earlier but different values (a correction, a status change or a "
                   f"different report version). It was held and not posted; replacing the earlier row needs your confirmation.", n)
