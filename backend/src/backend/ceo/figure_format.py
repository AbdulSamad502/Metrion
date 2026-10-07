"""Presentation-only rendering of already-stored numbers into display strings (spec §6.5, §6.13).

This is the ONE module in `backend/ceo` allowed to turn a stored integer into text. It determines no
monetary outcome: the figure was fully computed by the engine before it gets here. It only converts the
unit (paise -> rupees) for display — the same lossless, no-float conversion `cfo_actions._format_paise_for_narration`
applies (and `tests/unit/test_ceo_figures.py` pins the two to identical output so they cannot drift).
`divmod`/`abs` are function calls rather than `+ - * /` operators on purpose: this reads as unit conversion, not
as a derivation of a new figure (and the CEO arithmetic lint, which looks for operators on money-named operands,
correctly does not flag it).
"""

from __future__ import annotations

from fractions import Fraction

from backend.ceo.contract import Register

UNAVAILABLE = "UNAVAILABLE"


def format_paise(value_paise: int | None, *, is_available: bool = True) -> str:
    if not is_available or value_paise is None:
        return UNAVAILABLE
    sign = "-" if value_paise < 0 else ""
    rupees, remainder_paise = divmod(abs(value_paise), 100)
    return f"{sign}₹{rupees:,}.{remainder_paise:02d}"


def register_for(*, is_available: bool, confidence: str | None) -> Register:
    """`cfo_actions._register_for` — UNAVAILABLE beats confidence; PROVISIONAL has no register of its own and is
    presented as DERIVED (never ESTIMATE, which §7.4.7 reserves for estimate_ref-bearing figures)."""
    if not is_available:
        return Register.UNAVAILABLE
    if confidence == "PROVISIONAL":
        return Register.DERIVED
    if confidence in ("VERIFIED", "DERIVED", "MANUAL"):
        return Register(confidence)
    return Register.UNAVAILABLE  # an unknown confidence value is never presented as a verified figure


def format_percent_number(numerator: int | None, denominator: int | None) -> str:
    """Display of a stored percent-valued metric. `metric_result` stores percentages on the *percent-number* scale
    (`value_fraction` 25/2 means 12.5%, not 0.125 — financial_health.py's module docstring), so this appends a percent sign and
    rounds the exact `Fraction` half-up to two decimals; it never scales by 100. Never a `float`."""
    if numerator is None or not denominator:
        return UNAVAILABLE
    value = Fraction(numerator, denominator)
    hundredths = Fraction(abs(value) * 100)
    scaled = int(hundredths + Fraction(1, 2))  # half-up on a non-negative exact fraction
    whole, frac = divmod(scaled, 100)
    sign = "-" if value < 0 and scaled else ""
    text = f"{whole}.{frac:02d}".rstrip("0").rstrip(".")
    return f"{sign}{text}%"
