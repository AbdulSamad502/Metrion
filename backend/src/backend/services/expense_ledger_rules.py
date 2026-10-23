"""Pure rules for the expense ledger — no I/O, no money arithmetic (kickoff S3b; Round 9; expense-tracker.md §6, §7).

The limits marked PROPOSED are conservative proposals for owner review (R9-5, `docs/planning/expense-tracker/15-build-notes.md`), derived from existing code where
it exists: the amount ceiling is the 11-rupee-digit limit already used by `frontend/lib/pnlText.ts` and the Profit Calculator API; the text caps and page sizes
have no equivalent in the legacy expense route and are PROPOSED.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- categories (R9-4, Option A: a default cost class per category, overridable on the record; "Direct product costs" is omitted: COGS stays cogs_per_unit) ---


@dataclass(frozen=True, slots=True)
class Category:
    label: str
    cost_class: str  # ADVERTISING | STORAGE | OVERHEAD | DIRECT (the engine feed vocabulary)
    treatment: str = "incremental"  # default treatment only; a category never decides deductibility or settlement overlap on its own


CATEGORIES: dict[str, Category] = {
    "packaging": Category("Packaging", "DIRECT"),
    "inward_freight": Category("Inward freight", "DIRECT"),
    "advertising": Category("Advertising", "ADVERTISING"),
    "storage": Category("Storage / warehousing", "STORAGE"),
    "operating_overhead": Category("Operating overhead (rent, utilities)", "OVERHEAD"),
    "software": Category("Software", "OVERHEAD"),
    "personnel": Category("Personnel", "OVERHEAD"),
    "financial_charges": Category("Financial charges", "OVERHEAD"),
    "taxes": Category("Taxes", "OVERHEAD", "informational"),  # not subtracted until CA review (P9, G5)
    "other": Category("Other", "OVERHEAD"),
}
COST_CLASSES = frozenset({"ADVERTISING", "STORAGE", "OVERHEAD", "DIRECT"})
TREATMENTS = frozenset({"incremental", "already_in_settlement", "informational"})
REVIEW_STATES = ("draft", "pending_review", "confirmed", "voided")
PAYMENT_STATUSES = ("unpaid", "partially_paid", "paid", "unknown")
# Channel tags (spec §6.3): marketplaces, plus manually tagged ("not synced") channels. NULL / absent = business-wide.
CHANNEL_TAGS = frozenset({"AMAZON", "FLIPKART", "MEESHO", "OWN_WEBSITE", "WHATSAPP", "INDIAMART", "OTHER"})

# --- bounds (PROPOSED for owner review) ---------------------------------------------------------------------------------------------------------------
AMOUNT_MAX_PAISE = 9_999_999_999_999  # 11 rupee digits: derived from the ceiling already in frontend/lib/pnlText.ts
VENDOR_MAX = 120
DESCRIPTION_MAX = 500
REASON_MAX = 500
SKU_MAX = 120
SOURCE_REFERENCE_MAX = 200
IDEMPOTENCY_KEY_MAX = 120
ASSIGNMENT_SKUS_MAX = 20  # PROPOSED: the most SKUs one expense may be assigned to
PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 200


def amount_error(value: object) -> str | None:
    """Integer paise only (as `parse_expense_pool_adjustment` requires); magnitude within the ceiling; zero is an entered zero."""
    if isinstance(value, bool) or not isinstance(value, int):
        return "Amount must be a whole number of paise."
    if abs(value) > AMOUNT_MAX_PAISE:
        return f"Amount is above the limit of {AMOUNT_MAX_PAISE} paise."
    return None


def cost_amount_error(value: int) -> str | None:
    return "A cost is entered as zero or a positive amount; record a refund or credit note as a refund." if value < 0 else None


def refund_amount_error(value: int) -> str | None:
    return "A refund or credit note is a negative amount." if value >= 0 else None


# --- vendor (Q22): refuse a currency symbol or an amount-like number; allow short numerals ------------------------------------------------------------------
_CURRENCY = re.compile(r"(?:₹|\$|€|£)|\b(?:rs|inr|usd|eur|gbp)\b\.?", re.I)
_GROUPED_OR_DECIMAL = re.compile(r"\d[\d,]*\.\d+|\d{1,3}(?:,\d{2,3})+")
_LONG_DIGITS = re.compile(r"\d{5,}")


def vendor_error(vendor: str) -> str | None:
    """The vendor is a name, not an amount: refuse a currency symbol or code, a grouped or decimal number such as 1,200.50, or a run of five or more digits.
    Short numerals (3M, 7 Eleven, Studio 54, 1999) are allowed."""
    if len(vendor) > VENDOR_MAX:
        return f"Vendor is too long (at most {VENDOR_MAX} characters)."
    if _CURRENCY.search(vendor) or _GROUPED_OR_DECIMAL.search(vendor) or _LONG_DIGITS.search(vendor):
        return "The vendor looks like an amount. Enter the vendor's name only; amounts go in the amount field."
    return None


# --- review-state transitions --------------------------------------------------------------------------------------------------------------------
_EDITABLE = ("draft", "pending_review", "confirmed")


def review_transition_allowed(current: str, new: str) -> bool:
    """Among draft, pending_review and confirmed any move is allowed; `voided` is terminal, and a void goes through the void action (which needs a reason)."""
    return current in _EDITABLE and new in _EDITABLE
