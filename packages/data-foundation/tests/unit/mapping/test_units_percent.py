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
from data_foundation.mapping.units import (
    format_percent_points,
    parse_fraction_as_percent_points,
    parse_percent_points,
    percent_unit_is_ambiguous,
)
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



# ===================================================================== UNIT-AWARE VALIDATION (decision R2, 2026-10-21)
# A rate column whose values are all 1 or less could be percentage points (0.18 = 0.18%) or fractions (0.18 = 18%).
# Metrion never decides: the seller must choose, and the conversion exists only as an explicit choice.

@pytest.mark.parametrize("raw,expected", [("0.18", "18"), ("0.0525", "5.25"), ("1", "100"), ("0", "0"), ("0.000001", "0.0001"), ("0.05", "5"), ("1.0", "100"), (" 0.5 ", "50")])
def test_fractions_convert_exactly_only_when_the_seller_chose_that_unit(raw: str, expected: str) -> None:
    got = parse_fraction_as_percent_points(raw)
    assert got is not None and format_percent_points(got) == expected and got == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "abc", "1.01", "2", "18", "18%", "0.18%", "-0.1", "0.1234567", ".5", "1,5", "NaN", "1e-1"])
def test_anything_that_is_not_a_fraction_of_one_is_invalid_for_the_fraction_unit(raw: str) -> None:
    assert parse_fraction_as_percent_points(raw) is None


def test_the_two_units_disagree_on_purpose_and_neither_is_applied_silently() -> None:
    assert parse_percent_points("0.18") == Decimal("0.18")  # points: stays 0.18
    assert parse_fraction_as_percent_points("0.18") == Decimal(18)  # fraction: 18, only if the seller said so
    assert parse_percent_points("0.18") != parse_fraction_as_percent_points("0.18")


@pytest.mark.parametrize("max_value,sign,ambiguous", [
    (Decimal("0.18"), False, True), (Decimal("1"), False, True), (Decimal("0.0001"), False, True),
    (Decimal("0"), False, False),  # all zeros: 0 is 0 in either unit
    (Decimal("1.01"), False, False), (Decimal("5"), False, False), (Decimal("18"), False, False),  # something above 1 can only be points
    (Decimal("0.18"), True, False),  # a % sign says points
    (None, False, False),  # nothing parsed
])
def test_ambiguity_rule(max_value: Decimal | None, sign: bool, ambiguous: bool) -> None:
    assert percent_unit_is_ambiguous(max_value=max_value, has_percent_sign=sign) is ambiguous


def _gst_verdict(values: list[str], transform: str = "PERCENT"):  # type: ignore[no-untyped-def]
    cols = ["Order", "GST Rate"]
    rows = [[f"O{i}", v] for i, v in enumerate(values)]
    proposal = parse_proposal({"fields": [{"source_column": "Order", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
                                          {"source_column": "GST Rate", "index": 1, "canonical_field": "gst_rate", "transform": transform}], "unmapped_columns": []})
    return validate_mapping(proposal, report_kind="SALES", columns=cols, rows=rows, profiles=profile_columns(cols, rows), limits=_LIM, as_of=date(2026, 10, 21))


def _gst_field(verdict):  # type: ignore[no-untyped-def]
    return next(f for f in verdict.fields if f.source_column == "GST Rate")


def test_a_column_of_values_at_or_below_one_is_ambiguous_and_must_be_confirmed_never_auto_accepted() -> None:
    v = _gst_verdict(["0.18", "0.05", "0.12", "0.28", "0.18"] * 10)
    f = _gst_field(v)
    assert not f.errors and f.needs_confirmation and not f.auto_acceptable
    assert any("percentage points" in r and "fractions" in r and "will not guess" in r for r in f.confirm_reasons)


def test_a_recognised_header_still_cannot_auto_accept_an_ambiguous_rate_column() -> None:
    """A header a verified adapter already uses (taken from the real register, not invented) must not override the unit question."""
    from data_foundation.mapping.vocab import is_exact_register_match, synonym_register

    header = next(h for h, (canon, comp) in synonym_register().items() if canon == "gst_rate" and comp is None)  # the adapter's own gst_rate header
    cols = ["Order", header]
    rows = [[f"O{i}", v] for i, v in enumerate(["0.18", "0.05", "0.12", "0.28"] * 6)]
    proposal = parse_proposal({"fields": [{"source_column": "Order", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
                                          {"source_column": header, "index": 1, "canonical_field": "gst_rate", "transform": "PERCENT"}], "unmapped_columns": []})
    v = validate_mapping(proposal, report_kind="SALES", columns=cols, rows=rows, profiles=profile_columns(cols, rows), limits=_LIM, as_of=date(2026, 10, 21))
    f = next(x for x in v.fields if x.source_column == header)
    assert is_exact_register_match(header, "gst_rate", None) and f.exact_register_match  # it IS a recognised header...
    assert f.needs_confirmation and not f.auto_acceptable  # ...and still cannot be auto-accepted while the unit is ambiguous
    assert any("will not guess" in r for r in f.confirm_reasons)


@pytest.mark.parametrize("values", [
    ["18", "5", "12", "28", "0"] * 4,                 # clearly points
    ["18%", "5%", "12%"] * 5,                         # a % sign says points
    ["0.18", "5", "12", "0.05"] * 5,                  # mixed: something above 1 can only be points
    ["0", "0", "0.00"] * 7,                           # all zero
])
def test_unambiguous_columns_raise_no_unit_question(values: list[str]) -> None:
    f = _gst_field(_gst_verdict(values))
    assert not any("unit" in r or "fractions" in r for r in f.confirm_reasons) and not f.errors


def test_choosing_the_fraction_unit_is_valid_for_fractions_but_always_needs_confirmation() -> None:
    f = _gst_field(_gst_verdict(["0.18", "0.05", "0.12"] * 10, transform="FRACTION_TO_PERCENT"))
    assert not f.errors and f.needs_confirmation and not f.auto_acceptable
    assert any("fractions of 1" in r for r in f.confirm_reasons)


@pytest.mark.parametrize("values", [["18", "5", "12"] * 5, ["0.18", "18%"] * 5, ["0.18", "1.5"] * 5])
def test_the_fraction_unit_is_refused_when_values_are_not_fractions(values: list[str]) -> None:
    v = _gst_verdict(values, transform="FRACTION_TO_PERCENT")
    assert "M-PCT" in v.rules() and v.has_errors


def test_the_mapped_adapter_applies_exactly_the_unit_the_seller_chose() -> None:
    def adapter(transform: str) -> MappedAdapter:
        return MappedAdapter(adapter_id="mapped.t", marketplace="MEESHO", report_category="TAX", format_version="v1", columns=("Order", "GST"),
                             fields=(MappedField(0, "Order", "order_ref", None, "IDENTITY", None, None), MappedField(1, "GST", "gst_rate", None, transform, None, None)))

    rows = [{"Order": "O1", "GST": "0.18"}, {"Order": "O2", "GST": "0.0525"}, {"Order": "O3", "GST": "1.5"}, {"Order": "O4", "GST": "18%"}]
    raw = RawFile(columns=("Order", "GST"), rows=rows)
    points = list(adapter("PERCENT").parse(raw))
    fractions = list(adapter("FRACTION_TO_PERCENT").parse(raw))
    assert [p.canonical_fields.get("gst_rate") for p in points] == ["0.18", "0.0525", "1.5", "18"]  # never converted
    assert [p.canonical_fields.get("gst_rate") for p in fractions] == ["18", "5.25", None, None]  # converted only on the fraction path
    assert [bool(p.parse_errors) for p in fractions] == [False, False, True, True]  # 1.5 and 18% are not fractions: quarantined, not converted


@given(st.decimals(min_value=0, max_value=1, places=6, allow_nan=False, allow_infinity=False))
def test_property_every_six_place_fraction_converts_exactly_and_satisfies_the_four_place_rule(d: Decimal) -> None:
    got = parse_fraction_as_percent_points(format(d, "f"))
    assert got is not None and got == d * 100  # exact
    assert parse_percent_points(format_percent_points(got)) == got  # the result is itself a valid percentage (<= 4 decimals, 0..100)


@given(st.decimals(min_value=Decimal("1.000001"), max_value=1000, places=6, allow_nan=False, allow_infinity=False))
def test_property_a_value_above_one_is_never_a_fraction(d: Decimal) -> None:
    assert parse_fraction_as_percent_points(format(d, "f")) is None
