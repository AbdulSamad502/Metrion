"""Declared date parsing — data-foundation.md §2.4. Dates are declared per adapter, never
auto-detected or retried under a different pattern: "Any date that fails its declared pattern
is a hard ERROR. It is never retried under a different pattern" (§2.4) — this exists
specifically because Amazon's `%m/%d/%Y` and Flipkart's `%d-%m-%Y` are silently ambiguous for
day <= 12, and guessing would risk exactly that silent corruption.
"""

from __future__ import annotations

from datetime import date, datetime

# §2.4's table, verbatim — the only three formats this spec confirms.
AMAZON_DATE_FORMAT = "%m/%d/%Y"
FLIPKART_DATE_FORMAT = "%d-%m-%Y"
MEESHO_DATE_FORMAT = "%d-%b-%y"


class DateParseError(ValueError):
    """Raised when a date string fails its declared format — a hard ERROR (V-DATE-001), never
    silently retried under a different pattern."""


def parse_declared_date(value: str, *, pattern: str) -> date:
    try:
        return datetime.strptime(value, pattern).date()
    except ValueError as exc:
        raise DateParseError(f"{value!r} does not match declared pattern {pattern!r}") from exc
