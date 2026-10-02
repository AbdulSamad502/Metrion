"""BaseAdapter mechanics — data-foundation.md §2.2's five contract rules."""

from __future__ import annotations

import pytest

from data_foundation.adapters.base import BaseAdapter, MoneyParseError, rupees_to_paise
from data_foundation.adapters.flipkart_sales_report_v1 import adapter as flipkart_adapter
from data_foundation.adapters.meesho_orders_v1 import adapter as meesho_orders_adapter
from data_foundation.adapters.meesho_tcs_sales_return_v1 import adapter as meesho_return_adapter
from data_foundation.types import ColumnBinding, FileSample, RawFile


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_rupees_to_paise_rejects_non_finite_as_money_parse_error(raw):
    # Decimal("NaN")/Decimal("Infinity") parse successfully, so without an explicit check
    # int() raised a bare ValueError / OverflowError (the latter not even a ValueError) instead
    # of the MoneyParseError this function documents.
    with pytest.raises(MoneyParseError):
        rupees_to_paise(raw)


def test_rupees_to_paise_positive():
    assert rupees_to_paise("372.06") == 37_206


def test_rupees_to_paise_negative():
    assert rupees_to_paise("-100.50") == -10_050


def test_rupees_to_paise_whole_number():
    assert rupees_to_paise("50") == 5_000


def test_rupees_to_paise_invalid_raises():
    with pytest.raises(MoneyParseError):
        rupees_to_paise("not-a-number")


def test_detect_matched_when_all_confirmed_columns_present():
    sample = FileSample(columns=("Meesho Order Number", "Sub Order No", "Reason for Credit Entry", "Return Status"))
    result = meesho_orders_adapter.detect(sample)
    assert result.matched is True
    assert result.missing_columns == ()


def test_detect_reports_missing_columns_diff():
    sample = FileSample(columns=("Meesho Order Number",))
    result = meesho_orders_adapter.detect(sample)
    assert result.matched is False
    assert set(result.missing_columns) == {"Sub Order No", "Reason for Credit Entry", "Return Status"}


def test_parse_unknown_column_preserved_and_flagged():
    raw = RawFile(columns=("Sub Order No", "sss"), rows=[{"Sub Order No": "SUB1", "sss": "mystery"}])
    parsed = list(meesho_orders_adapter.parse(raw))
    assert len(parsed) == 1
    row = parsed[0]
    assert row.unknown_columns == ("sss",)
    assert row.source_row_json == {"Sub Order No": "SUB1", "sss": "mystery"}  # verbatim, never dropped


def test_parse_unmapped_enum_value_does_not_guess():
    raw = RawFile(columns=("Return Status",), rows=[{"Return Status": "Delivered"}])
    row = list(meesho_orders_adapter.parse(raw))[0]
    assert row.unmapped_enum_fields == (("return_status", "Delivered"),)
    assert row.canonical_fields["return_status"] is None  # never guessed


def test_flipkart_tds_amount_column_maps_to_tcs_not_tds():
    # §1.4: "the column says TDS, the money is TCS" — a real bug class if mapped literally.
    raw = RawFile(columns=("TDS Amount",), rows=[{"TDS Amount": "10.00"}])
    row = list(flipkart_adapter.parse(raw))[0]
    assert len(row.components) == 1
    assert row.components[0].component_code == "TCS"


def test_flipkart_dead_pre_gst_columns_ignored_not_unknown():
    raw = RawFile(columns=("CST Rate", "VAT Amount"), rows=[{"CST Rate": "0", "VAT Amount": "0"}])
    row = list(flipkart_adapter.parse(raw))[0]
    assert row.unknown_columns == ()  # recognized-but-discarded, not flagged as unknown
    assert row.components == ()


def test_flipkart_discount_bearer_split_maps_to_distinct_codes():
    raw = RawFile(columns=("Seller Share", "Bank Offer Share"), rows=[{"Seller Share": "50.00", "Bank Offer Share": "20.00"}])
    row = list(flipkart_adapter.parse(raw))[0]
    codes = {c.component_code: c.amount_paise for c in row.components}
    assert codes == {"SELLER_DISCOUNT": 5_000, "PLATFORM_DISCOUNT": 2_000}


def test_meesho_return_negative_taxable_amount():
    # Unit test of rupees_to_paise's handling of a negative numeric string, not an assertion
    # that real Meesho return data is always negative (see meesho_tcs_sales_return_v1.py's
    # docstring — the one real sample inspected was positive).
    raw = RawFile(columns=("total_taxable_sale_value",), rows=[{"total_taxable_sale_value": "-372.06"}])
    row = list(meesho_return_adapter.parse(raw))[0]
    assert row.canonical_fields["taxable_amount"] == -37_206


def test_column_map_ambiguous_bare_and_tuple_key_raises_at_construction():
    # data-foundation.md architecture decision: a bare string key "X" and an explicit tuple key
    # ("X", 0) both target occurrence 0 of header "X" — having both is ambiguous and must fail
    # fast at adapter-definition/import time, not per-row at parse time.
    with pytest.raises(ValueError, match="X"):
        BaseAdapter(
            adapter_id="test.ambiguous.v1",
            marketplace="MEESHO",
            report_category="TEST",
            format_version="v1",
            date_formats={},
            column_map={
                "X": ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
                ("X", 0): ColumnBinding(canonical_field="line_ref", component_code=None, is_verified=False),
            },
        )
