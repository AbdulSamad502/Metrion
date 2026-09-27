"""meesho.tcs_sales_return.v1 — data-foundation.md §2.3. Real 18-column header list copied
verbatim from the real `tcs_sales_return.xlsx` export inspected directly (not retyped from
memory)."""

from __future__ import annotations

from data_foundation.adapters.meesho_tcs_sales_return_v1 import adapter as meesho_return_adapter
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
    "cancel_return_date",
    "financial_year",
    "month_number",
    "supplier_id",
)


def test_detect_matched_against_real_18_column_header_row():
    sample = FileSample(columns=REAL_COLUMNS)
    result = meesho_return_adapter.detect(sample)
    assert result.matched is True
    assert result.missing_columns == ()


def test_detect_reports_missing_columns_diff():
    sample = FileSample(columns=("identifier", "sup_name"))
    result = meesho_return_adapter.detect(sample)
    assert result.matched is False
    assert set(result.missing_columns) == {"sub_order_num", "total_taxable_sale_value", "cancel_return_date"}


def test_parse_sub_order_num_maps_to_line_ref():
    raw = RawFile(columns=REAL_COLUMNS, rows=[{"sub_order_num": "SUB456"}])
    row = list(meesho_return_adapter.parse(raw))[0]
    assert row.canonical_fields["line_ref"] == "SUB456"


def test_parse_cancel_return_date_uses_corrected_date_formats_key():
    assert meesho_return_adapter.date_formats == {"cancel_return_date": "%d-%b-%y"}
    raw = RawFile(columns=REAL_COLUMNS, rows=[{"cancel_return_date": "05-Jan-24"}])
    row = list(meesho_return_adapter.parse(raw))[0]
    assert row.canonical_fields["cancel_return_date"] == "05-Jan-24"


def test_old_guessed_headers_no_longer_recognized():
    # Earlier, unverified pass mapped "Sub Order No" and "cancel_return" — both confirmed
    # wrong against the real export ("sub_order_num" / "cancel_return_date" instead).
    raw = RawFile(
        columns=("Sub Order No", "cancel_return"),
        rows=[{"Sub Order No": "SUB1", "cancel_return": "05-Jan-24"}],
    )
    row = list(meesho_return_adapter.parse(raw))[0]
    assert set(row.unknown_columns) == {"Sub Order No", "cancel_return"}


def test_parse_total_taxable_sale_value_positive_on_real_sample_not_asserted_universal():
    # Verified: the one real return row inspected showed +238.14 (positive), correcting the
    # earlier docstring claim that this field is always negative on the return file.
    raw = RawFile(columns=REAL_COLUMNS, rows=[{"total_taxable_sale_value": "238.14"}])
    row = list(meesho_return_adapter.parse(raw))[0]
    assert row.canonical_fields["taxable_amount"] == 23_814
