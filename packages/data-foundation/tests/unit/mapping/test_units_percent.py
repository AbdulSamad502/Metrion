"""PERCENT transform — exact formula, valid inputs, precision, rounding (never) and tests (decision R2, 2026-10-21).
The definition lives in `data_foundation/mapping/units.py`; these tests are its executable form."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, strategies as st

from data_foundation.adapters.mapped import MappedAdapter, MappedField
from data_foundation.mapping.profile import profile_columns
from data_foundation.mapping.proposal import parse_proposal
from data_foundation.mapping.units import format_percent_points, parse_percent_points
from data_foundation.mapping.validator import MappingLimits, validate_mapping
from data_foundation.types import RawFile


@pytest.mark.parametrize("raw,expected", [
    ("18", "18"), ("18%", "18"), (" 18.0 % ", "18"), ("18.00", "18"), ("2.5", "2.5"), ("0.25", "0.25"), ("0", "0"), ("0.00", "0"),
    ("28", "28"), ("100", "100"), ("100.0000", "100"), ("0.0001", "0.0001"), ("12.5%", "12.5"), ("05", "5"),
])
def test_valid_percentages_are_read_exactly_in_percentage_points(raw: str, expected: str) -> None:
    got = parse_percent_points(raw)
    assert got is not None and format_percent_points(got) == expected and got == Decimal(expected)


@pytest.mark.parametrize("raw", [
    "", " ", "abc", "NaN", "inf", "-1", "-0.5", "100.01", "101", "1000", "18.12345", "1e1", "1,8", "18%%", "%18", "+18", "18 %%", "1 8", "18 percent", "0x12",
])
def test_everything_else_is_invalid_never_clamped_never_rounded(raw: str) -> None:
    assert parse_percent_points(raw) is None


def test_a_fraction_is_not_silently_turned_into_a_percentage() -> None:
    """0.18 means 0.18 percentage points. Guessing it is "18%" would silently turn an 18% rate into 0.18%, so no heuristic exists."""
    assert parse_percent_points("0.18") == Decimal("0.18") != Decimal(18)


def test_more_than_four_decimals_is_rejected_not_rounded() -> None:
    assert parse_percent_points("18.1234") == Decimal("18.1234")
    assert parse_percent_points("18.12345") is None
    assert parse_percent_points("0.00001") is None  # would round to 0; rejected instead


@given(st.decimals(min_value=0, max_value=100, places=4, allow_nan=False, allow_infinity=False))
def test_property_every_valid_four_place_percentage_round_trips_exactly(d: Decimal) -> None:
    text_form = format(d, "f")
    got = parse_percent_points(text_form)
    assert got == d  # exact, no rounding anywhere
    assert parse_percent_points(text_form + "%") == d
    assert Decimal(format_percent_points(got)) == d  # canonical text re-parses to the same number


@given(st.decimals(min_value=Decimal("100.0001"), max_value=10_000, places=4, allow_nan=False, allow_infinity=False))
def test_property_above_one_hundred_is_always_invalid(d: Decimal) -> None:
    assert parse_percent_points(format(d, "f")) is None


# ---------------------------------------------------------------------------- through the mapped adapter
def _adapter() -> MappedAdapter:
    return MappedAdapter(
        adapter_id="mapped.t", marketplace="MEESHO", report_category="TAX", format_version="v1", columns=("Order", "GST"),
        fields=(MappedField(0, "Order", "order_ref", None, "IDENTITY", None, None), MappedField(1, "GST", "gst_rate", None, "PERCENT", None, None)),
    )


def test_the_mapped_adapter_stores_percentage_points_and_quarantines_the_unreadable() -> None:
    rows = [{"Order": "O1", "GST": "18%"}, {"Order": "O2", "GST": "5"}, {"Order": "O3", "GST": "0.18"}, {"Order": "O4", "GST": "abc"},
            {"Order": "O5", "GST": "150"}, {"Order": "O6", "GST": ""}]
    parsed = list(_adapter().parse(RawFile(columns=("Order", "GST"), rows=rows)))
    assert [p.canonical_fields.get("gst_rate") for p in parsed] == ["18", "5", "0.18", None, None, None]
    assert [bool(p.parse_errors) for p in parsed] == [False, False, False, True, True, False]  # blank is "not given", not an error and not 0
    assert parsed[3].parse_errors == (("GST", "abc"),) and parsed[4].parse_errors == (("GST", "150"),)


_LIM = MappingLimits(min_parse_rate=Fraction(98, 100), tax_consistency_rate=Fraction(98, 100), tax_tolerance_paise=1, key_unique_rate=Fraction(98, 100),
                     mixed_sign_low=Fraction(2, 100), max_date_span_years=5, unit_fraction_share=Fraction(2, 100))


def _verdict(values: list[str]):  # type: ignore[no-untyped-def]
    cols = ["Order", "GST"]
    rows = [[f"O{i}", v] for i, v in enumerate(values)]
    proposal = parse_proposal({"fields": [{"source_column": "Order", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
                                          {"source_column": "GST", "index": 1, "canonical_field": "gst_rate", "transform": "PERCENT"}], "unmapped_columns": []})
    return validate_mapping(proposal, report_kind="SALES", columns=cols, rows=rows, profiles=profile_columns(cols, rows), limits=_LIM, as_of=date(2026, 10, 21))


def test_the_validator_accepts_percent_text_with_a_percent_sign_and_rejects_non_percentages() -> None:
    assert "M-TYP" not in _verdict(["18%", "5%", "12", "28", "0"] * 20).rules()
    bad = _verdict(["18%", "five", "N/A", "150", "-3"] * 20)
    assert "M-TYP" in bad.rules()


def test_a_percent_transform_on_a_non_percentage_field_is_still_a_vocabulary_error() -> None:
    cols, rows = ["Order", "Qty"], [["O1", "2"], ["O2", "3"]]
    proposal = parse_proposal({"fields": [{"source_column": "Order", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
                                          {"source_column": "Qty", "index": 1, "canonical_field": "quantity", "transform": "PERCENT"}], "unmapped_columns": []})
    v = validate_mapping(proposal, report_kind="SALES", columns=cols, rows=rows, profiles=profile_columns(cols, rows), limits=_LIM, as_of=date(2026, 10, 21))
    assert "M-VOC" in v.rules()
