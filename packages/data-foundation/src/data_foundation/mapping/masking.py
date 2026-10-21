"""Deterministic PII masking applied before any sample reaches a model or a log (cfo-data-intelligence.md D7, I3).

Two layers: (1) a column whose *name* says it holds personal data is masked wholesale; (2) in every other
column, values matching personal-data patterns (email, phone, GSTIN, PAN, UPI id) are replaced by a typed
token. Numbers and dates in ordinary columns are kept — a model cannot tell a tax-inclusive price from an
exclusive one without them. Masking is a pure function: same input, same output.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_PII_NAME_WORDS = (
    "name", "address", "addr", "phone", "mobile", "contact", "email", "e mail", "customer", "buyer", "consignee",
    "recipient", "pincode", "pin code", "postal", "gstin", "gst no", "gst number", "pan", "aadhaar", "aadhar",
    "bank", "account no", "account number", "ifsc", "upi", "vpa", "beneficiary", "landmark", "city", "state of",
)
# Words that look PII-ish but are business fields we must keep readable.
_PII_NAME_EXEMPT = ("sku", "item name", "product name", "listing name", "seller name", "campaign name", "category name", "state code")

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_UPI = re.compile(r"\b[\w.\-]{2,}@[a-z]{2,}\b", re.IGNORECASE)
_GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?[6-9]\d{9}(?!\d)")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def is_pii_column(name: str) -> bool:
    n = _norm(name)
    if any(x in n for x in _PII_NAME_EXEMPT):
        return False
    # whole-word match so "company" does not trip "pan"
    return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", n) for w in _PII_NAME_WORDS)


def mask_cell(column_name: str, value: str) -> str:
    if value is None or value == "":
        return value
    if is_pii_column(column_name):
        return "<PII>"
    out = _EMAIL.sub("<EMAIL>", value)
    out = _GSTIN.sub("<GSTIN>", out)
    out = _PAN.sub("<PAN>", out)
    out = _UPI.sub("<UPI>", out)
    out = _PHONE.sub("<PHONE>", out)
    return out


def mask_sample(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> list[list[str]]:
    """Mask a sample (rows of cell strings aligned to `columns`). Index-based, so duplicate headers are safe."""
    return [[mask_cell(columns[i] if i < len(columns) else "", cell) for i, cell in enumerate(row)] for row in rows]
