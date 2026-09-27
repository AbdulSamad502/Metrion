"""formulas/return_rate.py — anomaly-detection.md §6.1 `RETURN_RATE_PCT`'s pure formula."""

from __future__ import annotations

from datetime import date
from fractions import Fraction
from uuid import uuid4

from calc_engine.formulas.return_rate import return_rate_pct
from calc_engine.types import CanonicalLine, Confidence, Paise, Unavailable

_AS_OF = date(2026, 9, 25)


def _line(*, quantity: int, returned_qty: int = 0, rto_qty: int = 0, confidence: Confidence = Confidence.VERIFIED) -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=uuid4(),
        marketplace="MEESHO",
        document_type="INVOICE",
        quantity=quantity,
        invoice_date=_AS_OF,
        dispatch_date=_AS_OF,
        order_date=_AS_OF,
        gross_item_amount=Paise(1_000_00),
        components=(),
        confidence=confidence,
        returned_qty=returned_qty,
        rto_qty=rto_qty,
    )


def test_happy_path_combines_returned_and_rto_quantities():
    lines = [
        _line(quantity=10, returned_qty=2, rto_qty=1),
        _line(quantity=10, returned_qty=0, rto_qty=0),
    ]
    result = return_rate_pct(lines)
    # total_quantity = 20, total_returned_all_outcomes = 2 + 1 = 3
    assert result == Fraction(3, 20) * 100


def test_pure_return_only_no_rto():
    lines = [_line(quantity=10, returned_qty=2, rto_qty=0)]
    result = return_rate_pct(lines)
    assert result == Fraction(2, 10) * 100


def test_pure_rto_only_no_plain_return():
    lines = [_line(quantity=10, returned_qty=0, rto_qty=4)]
    result = return_rate_pct(lines)
    assert result == Fraction(4, 10) * 100


def test_empty_series_is_unavailable_never_zero_or_undefined():
    result = return_rate_pct([])
    assert isinstance(result, Unavailable)
    assert "quantity" in result.missing_inputs


def test_all_zero_quantity_lines_is_unavailable_never_division_by_zero():
    lines = [_line(quantity=0, returned_qty=0, rto_qty=0)]
    result = return_rate_pct(lines)
    assert isinstance(result, Unavailable)


def test_zero_returns_yields_zero_pct_not_unavailable():
    lines = [_line(quantity=10, returned_qty=0, rto_qty=0)]
    result = return_rate_pct(lines)
    assert result == Fraction(0)


def test_never_a_float():
    lines = [_line(quantity=3, returned_qty=1, rto_qty=0)]
    result = return_rate_pct(lines)
    assert isinstance(result, Fraction)
