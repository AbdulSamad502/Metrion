"""Inclusive/exclusive price normalisation — deterministic-engine.md §8.1.

if basis = EXCLUSIVE:  taxable = listed
if basis = INCLUSIVE:  taxable = listed × 100 / (100 + effective_rate)

Requires a known effective rate. Where the rate is unknown, normalisation fails and the line
is flagged — it never guesses a rate. Basis is declared per marketplace and per field in
adapter configuration, never inferred (A1, resolved) — this function trusts whatever basis the
caller supplies; it does not itself decide which basis applies to which source field.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Paise, Unavailable

Basis = Literal["INCLUSIVE", "EXCLUSIVE"]


def normalize_to_exclusive(listed: Paise, basis: Basis, effective_rate: Fraction | None) -> Paise | Unavailable:
    if basis == "EXCLUSIVE":
        return listed
    if basis == "INCLUSIVE":
        if effective_rate is None:
            return Unavailable(
                reason="INCLUSIVE basis declared but effective_rate is unknown — normalisation never guesses a rate (§8.1)",
                missing_inputs=("effective_rate",),
            )
        taxable = Fraction(listed.value) * 100 / (Fraction(100) + effective_rate)
        return round_half_up_paise(taxable)
    raise ValueError(f"unknown GST basis {basis!r}")
