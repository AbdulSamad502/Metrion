"""Mapping validator tests (cfo-data-intelligence.md §6.4, §12 TD3–TD7, TD11). Proposals are plain data
standing in for (mocked) model output — including adversarial output. No LLM, no database."""

from __future__ import annotations

import json
from datetime import date
from fractions import Fraction
from typing import Any

import pytest

from data_foundation.mapping.masking import is_pii_column, mask_cell, mask_sample
from data_foundation.mapping.profile import file_fingerprint, parse_decimal, profile_columns
from data_foundation.mapping.proposal import ProposalParseError, parse_proposal
from data_foundation.mapping.validator import MappingLimits, validate_mapping

LIMITS = MappingLimits(
    min_parse_rate=Fraction(98, 100), tax_consistency_rate=Fraction(98, 100), tax_tolerance_paise=1,
    key_unique_rate=Fraction(98, 100), mixed_sign_low=Fraction(2, 100), max_date_span_years=5, unit_fraction_share=Fraction(2, 100),
)
AS_OF = date(2026, 10, 21)
COLUMNS = ["Order ID", "Qty", "Item Price", "Taxable Value", "CGST", "SGST", "Invoice Date", "Return Status"]


def make_rows(n: int = 60, *, price_inclusive: bool = True) -> list[list[str]]:
    rows = []
    for i in range(n):
        taxable = 100 + (i % 7) * 10            # rupees
        cgst = sgst = Fraction(taxable * 9, 100)
        gross = taxable + cgst + sgst if price_inclusive else taxable
        day = 1 + (i % 28)                       # days up to 28 -> DD/MM certain
        rows.append([f"OD{1000 + i}", "1", f"{float(gross):.2f}", f"{taxable:.2f}", f"{float(cgst):.2f}", f"{float(sgst):.2f}",
                     f"{day:02d}/10/2026", "DELIVERED" if i % 5 else "RETURNED"])
    return rows


def field(index: int, canonical: str, transform: str = "IDENTITY", *, component: str | None = None, tax: str | None = None, sign: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"source_column": COLUMNS[index], "index": index, "canonical_field": canonical, "transform": transform}
    if component:
        d["component_code"] = component
    if tax:
        d["tax_inclusion"] = tax
    if sign:
        d["sign_convention"] = sign
    return d


def good_proposal() -> dict[str, Any]:
    return {"fields": [
        field(0, "order_ref"), field(1, "quantity"),
        field(2, "gross_item_amount", "RUPEES_TO_PAISE", tax="INCLUSIVE", sign="AS_IS"),
        field(3, "taxable_amount", "RUPEES_TO_PAISE", tax="EXCLUSIVE", sign="AS_IS"),
        field(4, "component_amount", "RUPEES_TO_PAISE", component="CGST", sign="AS_IS"),
        field(5, "component_amount", "RUPEES_TO_PAISE", component="SGST", sign="AS_IS"),
        field(6, "invoice_date", "DATE_DMY"), field(7, "return_status"),
    ], "unmapped_columns": []}


def run(proposal: dict[str, Any], rows: list[list[str]] | None = None, kind: str = "SALES", columns: list[str] | None = None) -> Any:
    rows = rows if rows is not None else make_rows()
    cols = columns or COLUMNS
    return validate_mapping(parse_proposal(proposal), report_kind=kind, columns=cols, rows=rows,
                            profiles=profile_columns(cols, rows), limits=LIMITS, as_of=AS_OF)


# --------------------------------------------------------------------------- the good path
def test_correct_proposal_has_no_errors_but_still_needs_the_seller_to_confirm() -> None:
    v = run(good_proposal())
    assert not v.has_errors, [(f.source_column, f.errors) for f in v.fields if f.errors] + list(v.global_issues)
    assert not v.missing_required
    assert not v.auto_acceptable  # unrecognised header names + status domain + tax — never auto
    by_col = {f.source_column: f for f in v.fields}
    assert by_col["Item Price"].detected_tax_inclusion == "INCLUSIVE"
    assert by_col["Return Status"].enum_values == ("DELIVERED", "RETURNED")
    assert by_col["Return Status"].needs_confirmation


def test_item_price_synonym_is_never_auto_trusted() -> None:
    f = {f.source_column: f for f in run(good_proposal()).fields}["Item Price"]
    assert not f.auto_acceptable and not f.exact_register_match


def test_a_header_a_verified_adapter_already_knows_is_recognised_exactly() -> None:
    cols = ["Meesho Order Number"]
    rows = [[f"{10**15 + i}"] for i in range(30)]
    v = validate_mapping(parse_proposal({"fields": [{"source_column": cols[0], "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"}]}),
                         report_kind="SALES", columns=cols, rows=rows, profiles=profile_columns(cols, rows), limits=LIMITS, as_of=AS_OF)
    assert v.fields[0].exact_register_match and v.fields[0].auto_acceptable
    assert not v.auto_acceptable  # required fields (quantity, amount, date) are still missing
    assert ("quantity",) in v.missing_required


# ---------------------------------------------------------------------- adversarial proposals
def test_tax_inclusive_price_declared_exclusive_is_an_error() -> None:
    p = good_proposal()
    p["fields"][2]["tax_inclusion"] = "EXCLUSIVE"
    v = run(p)
    assert "M-TAX" in v.rules() and v.has_errors


def test_tax_inclusion_unmeasurable_requires_confirmation_not_assumption() -> None:
    cols = ["Order ID", "Qty", "Item Price", "Invoice Date"]
    rows = [[f"OD{i}", "1", "118.00", "05/10/2026"] for i in range(40)]
    p = {"fields": [
        {"source_column": "Order ID", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
        {"source_column": "Qty", "index": 1, "canonical_field": "quantity", "transform": "IDENTITY"},
        {"source_column": "Item Price", "index": 2, "canonical_field": "gross_item_amount", "transform": "RUPEES_TO_PAISE", "tax_inclusion": "INCLUSIVE", "sign_convention": "AS_IS"},
        {"source_column": "Invoice Date", "index": 3, "canonical_field": "invoice_date", "transform": "DATE_DMY"}]}
    v = validate_mapping(parse_proposal(p), report_kind="SALES", columns=cols, rows=rows, profiles=profile_columns(cols, rows), limits=LIMITS, as_of=AS_OF)
    price = v.fields[2]
    assert not price.errors and price.detected_tax_inclusion == "UNKNOWN"
    assert any("GST" in r or "tax" in r for r in price.confirm_reasons)


def test_fee_column_with_swapped_mixed_signs_is_an_error() -> None:
    rows = make_rows()
    for i, r in enumerate(rows):
        r[4] = f"-{r[4]}" if i % 2 else r[4]
    v = run(good_proposal(), rows)
    assert "M-SGN" in v.rules() and v.has_errors


def test_rupees_declared_as_paise_is_an_error() -> None:
    p = good_proposal()
    p["fields"][2]["transform"] = "PAISE_IDENTITY"
    assert "M-UNT" in run(p).rules()


def test_three_decimal_places_cannot_become_whole_paise() -> None:
    rows = make_rows()
    rows[0][2] = "118.005"
    assert "M-UNT" in run(good_proposal(), rows).rules()


def test_all_whole_numbers_money_asks_rupees_or_paise() -> None:
    cols = ["Order ID", "Amount"]
    rows = [[f"OD{i}", str(1000 + i)] for i in range(40)]
    p = {"fields": [{"source_column": "Order ID", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
                    {"source_column": "Amount", "index": 1, "canonical_field": "gross_item_amount", "transform": "RUPEES_TO_PAISE", "sign_convention": "AS_IS"}]}
    v = validate_mapping(parse_proposal(p), report_kind="SALES", columns=cols, rows=rows, profiles=profile_columns(cols, rows), limits=LIMITS, as_of=AS_OF)
    assert any("rupees or in paise" in r for r in v.fields[1].confirm_reasons)


def test_invented_field_and_component_are_rejected() -> None:
    p = good_proposal()
    p["fields"][1]["canonical_field"] = "units_sold_magic"
    p["fields"][4]["component_code"] = "SUPER_FEE"
    v = run(p)
    assert "M-VOC" in v.rules() and v.has_errors


def test_field_from_the_wrong_report_kind_is_rejected() -> None:
    assert "M-VOC" in run(good_proposal(), kind="SETTLEMENT").rules()


def test_component_code_on_a_plain_field_is_rejected() -> None:
    p = good_proposal()
    p["fields"][0]["component_code"] = "CGST"
    assert "M-VOC" in run(p).rules()


def test_two_columns_to_one_target_and_one_column_twice() -> None:
    p = good_proposal()
    p["fields"][3]["canonical_field"] = "gross_item_amount"  # taxable also claims gross_item_amount
    assert "M-ONE" in run(p).rules()
    p = good_proposal()
    p["fields"].append(field(2, "total_invoice_amount", "RUPEES_TO_PAISE", sign="AS_IS"))  # same column, second target
    assert "M-ONE" in run(p).rules()


def test_two_different_tax_components_are_not_a_duplicate() -> None:
    assert "M-ONE" not in run(good_proposal()).rules()  # CGST + SGST both component_amount, different codes


def test_source_column_must_match_its_position() -> None:
    p = good_proposal()
    p["fields"][1]["source_column"] = "Quantity Sold"  # not the column at index 1
    assert "M-VOC" in run(p).rules()


def test_date_order_contradictions() -> None:
    p = good_proposal()
    p["fields"][6]["transform"] = "DATE_MDY"  # values like 25/10/2026 can only be day-first
    assert "M-DTE" in run(p).rules()


def test_ambiguous_date_order_requires_confirmation() -> None:
    rows = make_rows()
    for r in rows:
        r[6] = "03/04/2026"  # could be either
    f = {f.source_column: f for f in run(good_proposal(), rows).fields}["Invoice Date"]
    assert any("DD/MM" in r for r in f.confirm_reasons) and not f.errors


def test_foreign_currency_values_are_rejected() -> None:
    rows = make_rows()
    rows[3][2] = "$118.00"
    assert "M-CUR" in run(good_proposal(), rows).rules()


def test_non_numeric_money_column_fails_type_validation() -> None:
    rows = make_rows()
    for r in rows[:10]:
        r[3] = "N/A"
    assert "M-TYP" in run(good_proposal(), rows).rules()


def test_empty_column_is_an_error() -> None:
    rows = make_rows()
    for r in rows:
        r[1] = ""
    assert "M-TYP" in run(good_proposal(), rows).rules()


def test_missing_required_fields_are_listed_not_assumed() -> None:
    p = good_proposal()
    p["fields"] = [f for f in p["fields"] if f["canonical_field"] not in ("quantity", "invoice_date")]
    v = run(p)
    assert ("quantity",) in v.missing_required
    assert ("invoice_date", "dispatch_date", "order_date") in v.missing_required


def test_grain_duplicate_order_ids_are_flagged() -> None:
    rows = make_rows()
    for r in rows:
        r[0] = "OD1"  # one order id repeated: an order-level or aggregated report, not line-level
    assert "M-GRN" in run(good_proposal(), rows).rules()


def test_no_identity_column_cannot_establish_grain() -> None:
    p = good_proposal()
    p["fields"] = [f for f in p["fields"] if f["canonical_field"] != "order_ref"]
    assert "M-GRN" in run(p).rules()


def test_unaddressed_columns_are_surfaced() -> None:
    p = good_proposal()
    p["fields"] = p["fields"][:-1]  # leaves "Return Status" neither mapped nor set aside
    v = run(p)
    assert any("Return Status" in w.message for w in v.global_warnings)
    p["unmapped_columns"] = ["Return Status"]
    assert not any("Return Status" in w.message for w in run(p).global_warnings)


def test_future_dates_warn() -> None:
    rows = make_rows()
    rows[0][6] = "05/12/2027"
    v = run(good_proposal(), rows)
    assert "M-PER" in v.rules() and not v.has_errors


# ----------------------------------------------------------------------- proposal parsing
@pytest.mark.parametrize("raw", [
    "not json", "[]", '{"fields": "x"}', '{"fields": [], "surprise": 1}',
    '{"fields": [{"source_column": "a", "index": -1, "canonical_field": "sku", "transform": "IDENTITY"}]}',
    '{"fields": [{"source_column": "a", "index": 0, "canonical_field": "sku"}]}',
    '{"fields": [{"source_column": "a", "index": 0, "canonical_field": "sku", "transform": "IDENTITY", "sql": "1"}]}',
    '{"fields": [{"source_column": "a", "index": true, "canonical_field": "sku", "transform": "IDENTITY"}]}',
])
def test_malformed_model_output_is_a_parse_error_not_a_guess(raw: str) -> None:
    with pytest.raises(ProposalParseError):
        parse_proposal(raw)


def test_proposal_accepts_json_string_and_object() -> None:
    p = good_proposal()
    assert parse_proposal(json.dumps(p)) == parse_proposal(p)


# ----------------------------------------------------------------------------- masking
def test_pii_columns_are_masked_wholesale_and_business_columns_are_kept() -> None:
    assert is_pii_column("Customer Name") and is_pii_column("Buyer Phone") and is_pii_column("Shipping Address")
    assert is_pii_column("GSTIN") and is_pii_column("Bank Account Number")
    for ok in ("SKU", "Item Price", "Order ID", "Product Name", "Seller Name", "Company"):
        assert not is_pii_column(ok), ok


def test_masking_patterns_inside_ordinary_columns() -> None:
    assert mask_cell("Notes", "mail ravi@example.com now") == "mail <EMAIL> now"
    assert mask_cell("Notes", "call 9876543210") == "call <PHONE>"
    assert mask_cell("Notes", "+91 98765 43210".replace(" ", "")) == "<PHONE>"
    assert mask_cell("Notes", "07AWOPM5761A1ZG") == "<GSTIN>"
    assert mask_cell("Notes", "AWOPM5761A") == "<PAN>"
    assert mask_cell("Notes", "ravi@okhdfc") == "<UPI>"
    assert mask_cell("Item Price", "1,18,000.00") == "1,18,000.00"  # amounts survive
    assert mask_cell("Order ID", "OD1000234") == "OD1000234"


def test_sample_masking_is_index_based_for_duplicate_headers() -> None:
    cols = ["Fixed Fee", "Customer Name", "Fixed Fee"]
    out = mask_sample(cols, [["10.00", "Ravi Kumar", "5.00"]])
    assert out == [["10.00", "<PII>", "5.00"]]


def test_masked_sample_leaks_no_personal_tokens() -> None:
    cols = ["Order ID", "Customer Name", "Phone", "Email", "GSTIN", "Notes"]
    rows = [["OD1", "Ravi Kumar", "9876543210", "ravi@example.com", "07AWOPM5761A1ZG", "paid via ravi@okhdfc 9123456780"]]
    blob = json.dumps(mask_sample(cols, rows))
    for secret in ("Ravi", "9876543210", "9123456780", "ravi@", "07AWOPM5761A1ZG"):
        assert secret not in blob, secret


# ------------------------------------------------------------- parsing and fingerprint
@pytest.mark.parametrize("raw,expected", [
    ("1,23,456.50", "123456.50"), ("₹ 1,18,000", "118000"), ("Rs. 99.5", "99.5"), ("(1,234.00)", "-1234.00"),
    ("-45", "-45"), ("12abc", None), ("", None), ("1.2.3", None),
])
def test_parse_decimal(raw: str, expected: str | None) -> None:
    from decimal import Decimal

    got = parse_decimal(raw)
    assert (got is None) if expected is None else (got == Decimal(expected))


def test_fingerprint_is_order_independent_and_sheet_sensitive() -> None:
    a = file_fingerprint(["Order ID", "Qty", "Item Price"], "Sheet1")
    assert a == file_fingerprint(["item price", "ORDER ID", "qty"], "sheet1")
    assert a != file_fingerprint(["Order ID", "Qty", "Item Price", "Extra"], "Sheet1")
    assert a != file_fingerprint(["Order ID", "Qty", "Item Price"], "Orders")


def test_a_proposer_is_handed_masked_profiles_never_raw_cells() -> None:
    """Regression: a column profile keeps its distinct values (so a status column can be confirmed). Those raw values must be
    masked, and dropped entirely for a personal-data column, before any proposer can see them."""
    from data_foundation.mapping.service import _masked_profiles

    cols = ["Customer Name", "Status", "Notes"]
    rows = [["Ravi Kumar", "DELIVERED", "mail ravi@example.com"], ["Asha Rao", "RETURNED", "ok"]]
    masked = _masked_profiles(profile_columns(cols, rows))
    by_name = {p.name: p for p in masked}
    assert by_name["Customer Name"].enum_values == ()  # a personal-data column keeps no values at all
    assert by_name["Status"].enum_values == ("DELIVERED", "RETURNED")  # business values survive
    assert all("ravi" not in v.lower() and "asha" not in v.lower() for p in masked for v in p.enum_values)
    assert by_name["Notes"].enum_values == ("<EMAIL>".join(["mail ", ""]).rstrip(), "ok") or "<EMAIL>" in by_name["Notes"].enum_values[0]



def test_grain_check_treats_a_sale_and_its_credit_note_as_different_events() -> None:
    cols = ["Order ID", "Line ID", "Doc Type", "Qty", "Price", "Invoice Date"]
    rows = []
    for i in range(40):
        rows.append([f"O{i}", f"L{i}", "INVOICE", "1", f"{100 + i}.00", "05/10/2026"])
        if i % 3 == 0:
            rows.append([f"O{i}", f"L{i}", "CREDIT_NOTE", "1", f"-{100 + i}.00", "09/10/2026"])

    def fields(with_doc_type: bool) -> dict[str, Any]:
        f = [{"source_column": "Order ID", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
             {"source_column": "Line ID", "index": 1, "canonical_field": "line_ref", "transform": "IDENTITY"},
             {"source_column": "Qty", "index": 3, "canonical_field": "quantity", "transform": "IDENTITY"},
             {"source_column": "Price", "index": 4, "canonical_field": "gross_item_amount", "transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE", "sign_convention": "AS_IS"},
             {"source_column": "Invoice Date", "index": 5, "canonical_field": "invoice_date", "transform": "DATE_DMY"}]
        if with_doc_type:
            f.append({"source_column": "Doc Type", "index": 2, "canonical_field": "document_type", "transform": "IDENTITY"})
        return {"fields": f, "unmapped_columns": [] if with_doc_type else ["Doc Type"]}

    def run_grain(with_doc_type: bool) -> Any:
        return validate_mapping(parse_proposal(fields(with_doc_type)), report_kind="SALES", columns=cols, rows=rows, profiles=profile_columns(cols, rows),
                                limits=LIMITS, as_of=AS_OF)

    assert "M-GRN" not in run_grain(True).rules()  # the document type distinguishes the credit notes: one row per line event
    assert "M-GRN" in run_grain(False).rules()  # without it the same lines repeat: this really does look order-level or aggregated


def test_day_month_name_two_digit_year_dates_read_as_day_first() -> None:
    from datetime import date

    from data_foundation.mapping.profile import parse_date_with

    assert parse_date_with("15-Sep-25", "DATE_DMY") == date(2025, 9, 15)
    assert parse_date_with("05 Jan 26", "DATE_DMY") == date(2026, 1, 5)
    assert parse_date_with("15-Sep-2025", "DATE_DMY") == date(2025, 9, 15)
    assert parse_date_with("15-Sep-25", "DATE_ISO") is None  # a month name is never an ISO date
