"""Published supplier unit price (docs/specs/ceo-pi-research-flow.md C5a, D6).

A supplier's own page text sometimes states a unit price ("₹450 per piece", "Rs. 1,299/pc"). This module finds such a statement, deterministically, and returns it as a
**published figure with its source and capture time**. It is never a quote: it is not saved as a `supplier.quote`, never reaches Brain 1 or the CFO, and is always shown
labelled "published by the supplier, not a quote" (the seller's own confirmed quote is the only price the CFO uses). Absence is the common case and is normal.

Deliberately narrow so it under-reports rather than invents: an amount counts only when it is directly followed by a per-unit word (per piece / pc / unit / set / pair /
each, or a slash form). A bare "₹450" (which might be a total, a shipping fee or a range of unrelated items) is ignored. Several different amounts on one page are returned
as a low-high range with the sample count, never averaged. Pure parsing: text in, integer paise out (rupee text converted with `Decimal`, never `float`).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_PATTERN = re.compile(
    r"(?:₹|Rs\.?|INR)\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(?:(?:/\s*|per\s+|a\s+)(pieces?|pcs?|units?|sets?|pairs?)\b|each\b)",
    re.IGNORECASE,
)
_MAX_PAISE = 10_000_000_00  # ₹10 crore per unit: anything above is not a unit price


def _to_paise(raw: str) -> int | None:
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    paise = int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return paise if 0 < paise <= _MAX_PAISE else None


def extract_published_unit_price(text: str, *, source_url: str | None, captured_at: datetime) -> dict[str, Any] | None:
    """`{"low_paise", "high_paise", "sample_count", "unit", "basis", "source_url", "captured_at", "disclaimer"}` or None when the text states no per-unit price."""
    amounts: list[int] = []
    unit = "unit"
    for match in _PATTERN.finditer(text or ""):
        paise = _to_paise(match.group(1))
        if paise is None:
            continue
        amounts.append(paise)
        word = (match.group(2) or "").lower()
        if word:
            unit = "piece" if word.startswith(("piece", "pc")) else word.rstrip("s")
    if not amounts:
        return None
    return {
        "low_paise": min(amounts), "high_paise": max(amounts), "sample_count": len(amounts), "unit": unit, "basis": "SUPPLIER_PAGE_TEXT",
        "source_url": source_url, "captured_at": captured_at.isoformat(),
        "disclaimer": "Published by the supplier on its page; not a quote and not checked by Metrion. Ask the supplier for a quote and tell the CEO to get cost, margin and units.",
    }
