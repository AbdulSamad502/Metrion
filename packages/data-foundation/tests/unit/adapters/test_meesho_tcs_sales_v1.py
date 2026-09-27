"""meesho.tcs_sales.v1 — data-foundation.md §2.3. Real 17-column header list copied verbatim
from the real `tcs_sales.xlsx` export inspected directly (not retyped from memory)."""

from __future__ import annotations

from data_foundation.adapters.meesho_tcs_sales_v1 import adapter as meesho_tcs_sales_adapter
from data_foundation.types import FileSample, RawFile

REAL_COLUMNS = (
    "identifier",
    "sup_name",
    "gstin",
    "sub_order_num",
    "order_date",
    "hsn_code",
    "quantity",
    "gst_rate",
    "total_taxable_sale_value",
    "tax_amount",
    "total_invoice_value",
    "taxable_shipping",
    "end_customer_state_new",
    "enrollment_no",
    "financial_year",
    "month_number",
    "supplier_id",
)


def test_detect_matched_against_real_header_row():
    sample = FileSample(columns=REAL_COLUMNS)
    result = meesho_tcs_sales_adapter.detect(sample)
    assert result.matched is True
    assert result.missing_columns == ()


def test_detect_reports_missing_columns_diff():
    sample = FileSample(columns=("identifier", "sup_name"))
    result = meesho_tcs_sales_adapter.detect(sample)
    assert result.matched is False
    assert set(result.missing_columns) == {"sub_order_num", "gst_rate", "total_taxable_sale_value"}


def test_parse_sub_order_num_maps_to_line_ref():
    raw = RawFile(columns=REAL_COLUMNS, rows=[{"sub_order_num": "SUB123"}])
    row = list(meesho_tcs_sales_adapter.parse(raw))[0]
    assert row.canonical_fields["line_ref"] == "SUB123"


def test_parse_gst_rate_kept_as_source_decimal_string():
    raw = RawFile(columns=REAL_COLUMNS, rows=[{"gst_rate": "18.00"}])
    row = list(meesho_tcs_sales_adapter.parse(raw))[0]
    assert row.canonical_fields["gst_rate"] == "18.00"


def test_parse_total_taxable_sale_value_converts_to_paise():
    raw = RawFile(columns=REAL_COLUMNS, rows=[{"total_taxable_sale_value": "372.06"}])
    row = list(meesho_tcs_sales_adapter.parse(raw))[0]
    assert row.canonical_fields["taxable_amount"] == 37_206


def test_old_guessed_header_no_longer_recognized():
    # The earlier, unverified pass mapped "Sub Order No" — confirmed wrong against the real
    # export, which uses "sub_order_num" instead. That old header must now be unknown.
    raw = RawFile(columns=("Sub Order No",), rows=[{"Sub Order No": "SUB1"}])
    row = list(meesho_tcs_sales_adapter.parse(raw))[0]
    assert row.unknown_columns == ("Sub Order No",)
