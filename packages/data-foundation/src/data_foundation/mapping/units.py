"""Exact definitions of the value transforms a confirmed mapping may apply that are not plain money or dates
(cfo-data-intelligence.md §6.4a). One function per transform, so the adapter that applies it and the validator that
checks it can never disagree.

PERCENT — `parse_percent_points`
  Meaning    a percentage in percentage points: the text "18" or "18%" means 18 percentage points (an 18% rate). It is NOT
             converted to a fraction: every rule that consumes a rate (V-TAX-003, the GST slab references) compares in
             percentage points, as the verified adapters store it.
  Accepts    optional surrounding spaces; digits with an optional decimal part; an optional single trailing "%".
             No leading "+". Examples: "18", "18%", " 18.0 % ", "2.5", "0.25", "0".
  Range      0 <= value <= 100, inclusive. A negative value or a value above 100 is invalid, never clamped.
  Precision  at most 4 decimal places (the width of `line_component.rate_pct numeric(7,4)`). More than 4 is invalid:
             rejected, never rounded.
  Rounding   none. The exact decimal, normalised to its shortest form ("18.00" -> "18", "0.00" -> "0").
  Invalid    "", "abc", "NaN", "inf", "1e1", "1,8", "18%%", "-1", "100.01", "18.12345": returns None and the row is
             quarantined by V-MAP-001 naming the value (never defaulted to 0). A blank cell is "not given".

FRACTION_TO_PERCENT — `parse_fraction_as_percent_points` (a seller-chosen conversion, never a default)
  Meaning    the seller states the values are fractions of 1: "0.18" means 18 percentage points. Result = value x 100, exactly.
  Accepts    a decimal 0 <= value <= 1 with at most 6 decimal places and no "%" sign: "0.18", "0.0525", "1", "0".
  Rounding   none: at most 6 input decimals give at most 4 output decimals, so the product is exact and satisfies the
             4-decimal rule. More than 6 decimals is invalid.
  Invalid    anything else, including a value above 1 or a "%" sign (those are percentages, not fractions): the row is
             quarantined by V-MAP-001, and a mapping that asks for this transform on such a column is refused (M-PCT).

AMBIGUITY — `percent_unit_is_ambiguous` (decision R2, 2026-10-21: never silently convert an ambiguous value)
  A column whose non-blank values are ALL within (0, 1] and none carries a "%" could be percentage points (0.18 = 0.18%) or
  fractions (0.18 = 18%). Metrion never decides: the validator (M-PCT) requires the seller to choose the unit explicitly,
  and auto-accept is impossible even for a recognised header. PERCENT never converts "0.18" to 18 on its own, and
  FRACTION_TO_PERCENT is applied only when the seller chose it. A column with any value above 1 or any "%" sign is
  unambiguously percentage points; an all-zero column is not ambiguous (0 is 0 in either unit).
"""

from __future__ import annotations

import re
from decimal import Decimal

_PERCENT = re.compile(r"^\s*(\d+(?:\.\d{1,4})?)\s*%?\s*$")
_MAX_PERCENT = Decimal(100)
_FRACTION = re.compile(r"^\s*(0(?:\.\d{1,6})?|1(?:\.0{1,6})?)\s*$")
_HUNDRED = Decimal(100)


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


def parse_fraction_as_percent_points(raw: str) -> Decimal | None:
    """A fraction of 1 read as percentage points (value x 100, exact), or None when `raw` is not a valid fraction. Only ever applied
    when the seller explicitly chose FRACTION_TO_PERCENT; see the module docstring."""
    m = _FRACTION.match(raw)
    if m is None:
        return None
    value = Decimal(m.group(1)) * _HUNDRED
    return value.normalize() if value != 0 else Decimal(0)


def percent_unit_is_ambiguous(*, max_value: Decimal | None, has_percent_sign: bool) -> bool:
    """True when a column's values cannot tell percentage points from fractions: every value is within (0, 1] and none has a "%" sign.
    `max_value` is the largest value that parsed as a percentage (None when none did). An all-zero column is not ambiguous."""
    return max_value is not None and Decimal(0) < max_value <= Decimal(1) and not has_percent_sign
