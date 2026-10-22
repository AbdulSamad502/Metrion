"""Pure rules of the expense ledger (docs/specs/cfo-expense-ledger.md §6): normalisation, entry identity, duplicate / overlap holds.

No I/O and no clock. The identity is the database's duplicate guard (unique per tenant among non-void rows), so it must be a stable function of
the *meaning* of an entry, not of how a file spelled it: whitespace and letter case are normalised; the amount is the signed integer paise as given.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from enum import Enum

from calc_engine.formulas.expense_accounting import ExpenseHold

# OQ-L2 (initial list, to be confirmed by the owner): categories that are normally deducted by the marketplace itself. An expense in the seller's
# own books with such a category may already be inside a settlement, so it is held until the seller confirms it is not (cost-ownership matrix, §4.3).
OVERLAP_LIKE_TOKENS: frozenset[str] = frozenset({"commission", "fixed fee", "collection fee", "closing fee", "shipping fee", "tcs", "tds"})

MARKETPLACES: frozenset[str] = frozenset({"AMAZON", "FLIPKART", "MEESHO"})


class LedgerRuleError(ValueError):
    """An entry or request the ledger refuses; the message is safe to show the seller."""


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.split())
    return collapsed or None


def normalize_category(value: str | None) -> str:
    c = normalize_text(value)
    if c is None:
        raise LedgerRuleError("an expense needs a category; it is never defaulted")
    return c


@dataclass(frozen=True, slots=True)
class NewEntry:
    entry_date: date
    amount_paise: int
    category: str
    paid_date: date | None = None
    gst_amount_paise: int | None = None
    gst_treatment: str | None = None
    vendor: str | None = None
    description: str | None = None
    payment_ref: str | None = None
    marketplace: str | None = None
    source: str = "MANUAL"
    ingestion_run_id: str | None = None
    source_row_number: int | None = None


def validate_new_entry(e: NewEntry) -> NewEntry:
    """Normalises text fields and rejects what the database would also reject, with a seller-safe message."""
    if isinstance(e.amount_paise, bool) or not isinstance(e.amount_paise, int):
        raise LedgerRuleError("the amount must be a whole number of paise")
    if e.amount_paise == 0:
        raise LedgerRuleError("an expense of zero is not recorded")
    if e.gst_amount_paise is not None and (isinstance(e.gst_amount_paise, bool) or not isinstance(e.gst_amount_paise, int)):
        raise LedgerRuleError("the GST amount must be a whole number of paise")
    if e.gst_treatment not in (None, "INCLUDED_IN_COST", "CREDITABLE"):
        raise LedgerRuleError("GST treatment must be INCLUDED_IN_COST or CREDITABLE")
    if e.gst_treatment is not None and e.gst_amount_paise is None:
        raise LedgerRuleError("a GST treatment needs a GST amount")
    if e.paid_date is not None and e.paid_date < e.entry_date:
        raise LedgerRuleError("an expense cannot be paid before it was incurred")
    market = None if e.marketplace is None else e.marketplace.strip().upper()
    if market is not None and market not in MARKETPLACES:
        raise LedgerRuleError(f"unknown marketplace {e.marketplace!r}")
    if e.source not in ("FILE", "MANUAL"):
        raise LedgerRuleError("source must be FILE or MANUAL")
    return NewEntry(
        entry_date=e.entry_date, amount_paise=e.amount_paise, category=normalize_category(e.category), paid_date=e.paid_date,
        gst_amount_paise=e.gst_amount_paise, gst_treatment=e.gst_treatment, vendor=normalize_text(e.vendor), description=normalize_text(e.description),
        payment_ref=normalize_text(e.payment_ref), marketplace=market, source=e.source, ingestion_run_id=e.ingestion_run_id,
        source_row_number=e.source_row_number,
    )


def _fold(value: str | None) -> str | None:
    return None if value is None else value.casefold()


def entry_identity(e: NewEntry) -> str:
    """SHA-256 over the meaning of the entry (D1): date, signed amount, category, vendor, payment reference, description. Text is normalised and
    case-folded; the marketplace, GST fields and provenance are deliberately not part of identity (the same payment re-uploaded is the same payment)."""
    payload = [e.entry_date.isoformat(), e.amount_paise, _fold(normalize_text(e.category)), _fold(e.vendor), _fold(e.payment_ref), _fold(e.description)]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def possible_duplicate_key(e: NewEntry) -> tuple[str, int, str | None]:
    """Same day, same signed amount, same vendor — a different identity (other text) is exactly the ambiguous case the seller must resolve (D1)."""
    return (e.entry_date.isoformat(), e.amount_paise, _fold(e.vendor))


def is_overlap_like(category: str) -> bool:
    folded = category.casefold()
    return any(tok in folded for tok in OVERLAP_LIKE_TOKENS)


class Disposition(str, Enum):
    STORE = "STORE"
    SKIP_EXACT_DUPLICATE = "SKIP_EXACT_DUPLICATE"


@dataclass(frozen=True, slots=True)
class Decision:
    disposition: Disposition
    hold: ExpenseHold
    identity: str


def decide(e: NewEntry, known_identities: Collection[str], known_duplicate_keys: Collection[tuple[str, int, str | None]]) -> Decision:
    """The single write-path rule (spec §6.1): exact repeat -> skipped (counted by the caller); same date/amount/vendor with another identity ->
    POSSIBLE_DUPLICATE; a marketplace-deduction-like category -> MAY_OVERLAP_UNCONFIRMED; otherwise stored clean. A possible duplicate wins over
    an overlap hold (it is the stronger doubt); both exclude the entry from every total until the seller resolves it."""
    ident = entry_identity(e)
    if ident in known_identities:
        return Decision(Disposition.SKIP_EXACT_DUPLICATE, ExpenseHold.NONE, ident)
    if possible_duplicate_key(e) in known_duplicate_keys:
        return Decision(Disposition.STORE, ExpenseHold.POSSIBLE_DUPLICATE, ident)
    if is_overlap_like(e.category):
        return Decision(Disposition.STORE, ExpenseHold.MAY_OVERLAP_UNCONFIRMED, ident)
    return Decision(Disposition.STORE, ExpenseHold.NONE, ident)
