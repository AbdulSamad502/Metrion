"""fee_resolution.py / resolve_fee_or_unavailable — deterministic-engine.md §5.14."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from calc_engine.formulas.fee_resolution import FeeReference, resolve_fee_or_unavailable
from calc_engine.types import Unavailable


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "rate_pct": None,
        "rate_low_pct": None,
        "rate_high_pct": None,
        "source": "Amazon Seller Central fee schedule",
        "confidence": "VERIFIED",
        "version": 1,
    }
    base.update(overrides)
    return base


def test_none_row_returns_unavailable():
    result = resolve_fee_or_unavailable(None)
    assert result == Unavailable(
        reason="no fee_reference row covers this (marketplace, category, fee_type)",
        missing_inputs=("fee_reference",),
    )


def test_point_rate_row_populates_rate_pct_only():
    row = _row(rate_pct=Decimal("18.5000"))
    result = resolve_fee_or_unavailable(row)
    assert result == FeeReference(
        rate_pct=Fraction(37, 2),
        rate_low_pct=None,
        rate_high_pct=None,
        source="Amazon Seller Central fee schedule",
        confidence="VERIFIED",
        version=1,
    )


def test_range_only_row_populates_low_and_high_never_a_midpoint():
    row = _row(rate_low_pct=Decimal("5.0000"), rate_high_pct=Decimal("15.0000"))
    result = resolve_fee_or_unavailable(row)
    assert isinstance(result, FeeReference)
    assert result.rate_pct is None  # never collapsed to a midpoint/derived point value
    assert result.rate_low_pct == Fraction(5, 1)
    assert result.rate_high_pct == Fraction(15, 1)
    # Guardrail: the midpoint of low/high (10) must not have been invented anywhere on the
    # result — rate_pct stays None, and low/high are exactly what the row stored, not a
    # collapsed single value.
    midpoint = Fraction(10, 1)
    assert result.rate_pct != midpoint
    assert result.rate_pct is None


def test_all_three_none_raises_value_error_as_malformed():
    row = _row()
    with pytest.raises(ValueError):
        resolve_fee_or_unavailable(row)


def test_decimal_to_fraction_conversion_is_exact():
    row = _row(rate_pct=Decimal("18.5000"))
    result = resolve_fee_or_unavailable(row)
    assert isinstance(result, FeeReference)
    assert result.rate_pct == Fraction(37, 2)
    assert result.rate_pct == Fraction(185, 10)
    assert float(result.rate_pct) == 18.5


def test_decimal_to_fraction_conversion_exact_for_non_terminating_looking_value():
    row = _row(rate_pct=Decimal("2.3400"))
    result = resolve_fee_or_unavailable(row)
    assert isinstance(result, FeeReference)
    assert result.rate_pct == Fraction(234, 100)
    assert result.rate_pct == Fraction(117, 50)
