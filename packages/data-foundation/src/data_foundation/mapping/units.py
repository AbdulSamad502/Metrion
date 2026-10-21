"""Exact definitions of the value transforms a confirmed mapping may apply that are not plain money or dates
(cfo-data-intelligence.md §6.4a). One function per transform, so the adapter that applies it and the validator that
checks it can never disagree.

PERCENT — `parse_percent_points`
  Meaning   a percentage expressed in percentage points: the text "18" or "18%" means 18 percentage points (an 18% rate).
            It is NOT converted to a fraction: 18 stays 18, because every rule that consumes a rate (V-TAX-003, the GST slab
            references) compares in percentage points, as the verified adapters store it.
  Accepts   an optional leading/trailing space; an optional single trailing "%"; digits with an optional decimal part
            (a leading "+" is not accepted). Examples: "18", "18%", " 18.0 % ", "2.5", "0.25", "0".
  Range     0 <= value <= 100 (inclusive). A negative value or a value above 100 is invalid, not clamped.
  Precision at most 4 decimal places (the width of `line_component.rate_pct numeric(7,4)`). More than 4 is invalid —
            the value is rejected, never rounded.
  Rounding  none. The result is the exact decimal, normalised to its shortest form ("18.00" -> "18", "0.00" -> "0").
  Never     a heuristic: "0.18" is 0.18 percentage points, not 18%. A column of fractions must be mapped by the seller as
            something else or fixed at the source; guessing would silently turn an 18% rate into 0.18%.
  Invalid   anything else — "", "abc", "NaN", "inf", "1e1", "1,8", "18%%", "-1", "100.01", "18.12345" — returns None, and the
            row is quarantined by V-MAP-001 naming the value (never defaulted to 0).
"""

from __future__ import annotations

import re
from decimal import Decimal

_PERCENT = re.compile(r"^\s*(\d+(?:\.\d{1,4})?)\s*%?\s*$")
_MAX_PERCENT = Decimal(100)


def parse_percent_points(raw: str) -> Decimal | None:
    """The exact percentage points in `raw`, or None when `raw` is not a valid percentage (see the module docstring)."""
    m = _PERCENT.match(raw)
    if m is None:
        return None
    value = Decimal(m.group(1))
    if value > _MAX_PERCENT:
        return None
    return value.normalize() if value != 0 else Decimal(0)


def format_percent_points(value: Decimal) -> str:
    """Canonical text of a parsed percentage: no exponent, no trailing zeros ("18", "2.5", "0")."""
    return format(value, "f")
