"""Expense CSV import (kickoff S5a): the fixed template, row-level errors for malformed and partially invalid files, text-to-paise parsing, and duplicate detection."""

from __future__ import annotations

from datetime import date

import pytest

from backend.services import expense_import as imp

H = ",".join(imp.TEMPLATE_COLUMNS)


def csv_of(*lines: str, header: str = H) -> bytes:
    return ("\r\n".join([header, *lines]) + "\r\n").encode()


GOOD = "2026-09-10,Acme Realty,September rent,operating_overhead,1200.50,INV-1,"


@pytest.mark.parametrize("text,paise", [("0", 0), ("1200", 120_000), ("1200.5", 120_050), ("1200.50", 120_050), ("0.05", 5), ("99999999999.99", 9_999_999_999_999)])
def test_rupees_become_integer_paise(text, paise) -> None:
    assert imp.rupees_to_paise(text) == paise


@pytest.mark.parametrize("text", ["", "-5", "+5", "1,200", "1e3", "1200.505", "1200.", ".5", "₹100", "Rs 100", "12 00", "abc", "100000000000", "1.5.5", "٣"])
def test_anything_else_is_refused(text) -> None:
    assert imp.rupees_to_paise(text) is None


def test_the_template_is_the_header_only() -> None:
    assert imp.template_csv().strip() == H


def test_a_valid_file_parses_to_rows_with_integer_paise() -> None:
    r = imp.parse_csv(csv_of(GOOD))
    assert r.file_errors == [] and len(r.rows) == 1
    row = r.rows[0]
    assert (row.date, row.vendor, row.category, row.amount_paise, row.source_id, row.channel, row.errors) == (date(2026, 9, 10), "Acme Realty", "operating_overhead", 120_050, "INV-1", None, [])
    assert len(r.sha256) == 64


def test_the_columns_may_come_in_any_order_and_a_bom_is_tolerated() -> None:
    cols = ["amount_rupees", "category", "date", "vendor", "description", "channel", "source_id"]
    data = ("﻿" + ",".join(cols) + "\r\n10,software,2026-09-01,Acme,,,\r\n").encode("utf-8")
    r = imp.parse_csv(data)
    assert r.file_errors == [] and r.rows[0].amount_paise == 1_000 and r.rows[0].category == "software"


@pytest.mark.parametrize(
    "data,fragment",
    [
        (b"", "empty"),
        (b"\r\n\r\n", "empty"),
        (csv_of(GOOD, header="date,vendor,amount"), "header"),
        (csv_of(GOOD, header=H + ",extra"), "header"),
        (csv_of(GOOD, header="date,date,description,category,amount_rupees,source_id,channel"), "header"),
        (b"\xff\xfe\x00bad", "UTF-8"),
        (b"date,vendor\x00,x\r\n", "CSV"),
    ],
)
def test_a_malformed_file_is_refused_whole_with_a_reason(data, fragment) -> None:
    r = imp.parse_csv(data)
    assert r.rows == [] and any(fragment in e for e in r.file_errors)


def test_a_file_over_the_size_or_row_limit_is_refused_whole() -> None:
    big = imp.parse_csv(b"a" * (imp.MAX_BYTES + 1))
    assert big.rows == [] and "larger" in big.file_errors[0]
    many = imp.parse_csv(chr(10).join([H] + [GOOD] * (imp.MAX_ROWS + 1)).encode())
    assert many.rows == [] and "more than" in many.file_errors[0]


def test_a_row_with_the_wrong_number_of_columns_is_a_row_error_not_a_crash() -> None:
    r = imp.parse_csv(csv_of(GOOD, "2026-09-10,only,three", GOOD.replace("INV-1", "INV-2")))
    assert [bool(x.errors) for x in r.rows] == [False, True, False]
    assert "columns" in r.rows[1].errors[0]


@pytest.mark.parametrize(
    "line,fragment",
    [
        ("10/09/2026,Acme,,software,100,,", "Date"),
        ("2026-02-30,Acme,,software,100,,", "Date"),
        ("2026-09-10,Acme,,not_a_category,100,,", "Category"),
        ("2026-09-10,Acme,,software,-100,,", "Amount"),
        ("2026-09-10,Acme,,software,1,200,,", "columns"),
        ('2026-09-10,Acme,,software,"1,200",,', "Amount"),
        ("2026-09-10,Acme,,software,12.345,,", "Amount"),
        ("2026-09-10,Rent Rs 1,200.50,,software,100,,", "columns"),
        ('2026-09-10,"Rent 1,200.50",,software,100,,', "vendor"),
        ("2026-09-10,Acme,,software,100,bad id!,", "Source id"),
        ("2026-09-10,Acme,,software,100,,mars", "Channel"),
        ("2026-09-10,Acme,,software,100000000000,,", "Amount"),
    ],
)
def test_each_invalid_row_names_what_is_wrong(line, fragment) -> None:
    row = imp.parse_csv(csv_of(line)).rows[0]
    assert row.errors and any(fragment in e for e in row.errors), row.errors


def test_a_partially_invalid_file_keeps_the_good_rows_and_lists_every_bad_one() -> None:
    rows = imp.parse_csv(csv_of(GOOD, "bad,Acme,,software,100,,", GOOD.replace("INV-1", "INV-3").replace("1200.50", "5"), "2026-09-10,Acme,,nope,1,,")).rows
    out = imp.classify(rows, [])
    assert [c.status for c in out] == [imp.OK, imp.ERROR, imp.OK, imp.ERROR] and [c.row.number for c in out] == [1, 2, 3, 4]


def existing(**kw):
    base = dict(id="e1", effective_date=date(2026, 9, 10), vendor="ACME  Realty", description="september rent", amount_paise=120_050, source_reference="manual")
    base.update(kw)
    return base


def test_the_same_source_id_in_the_ledger_is_a_duplicate_and_is_listed() -> None:
    rows = imp.parse_csv(csv_of(GOOD)).rows
    out = imp.classify(rows, [existing(id="e9", source_reference="import:INV-1", description="other")])
    assert out[0].status == imp.DUPLICATE and out[0].matches == ["e9"]


def test_the_same_source_id_twice_in_one_file_flags_the_second() -> None:
    rows = imp.parse_csv(csv_of(GOOD, GOOD.replace("September rent", "different"))).rows
    out = imp.classify(rows, [])
    assert [c.status for c in out] == [imp.OK, imp.DUPLICATE] and "row 1" in (out[1].note or "")


def test_date_normalised_vendor_amount_and_description_make_a_probable_match_that_is_kept() -> None:
    rows = imp.parse_csv(csv_of("2026-09-10,acme realty,September  Rent!,operating_overhead,1200.50,,")).rows
    out = imp.classify(rows, [existing()])
    assert out[0].status == imp.PROBABLE_MATCH and out[0].matches == ["e1"]  # flagged for review, not dropped


@pytest.mark.parametrize("field,value", [("effective_date", date(2026, 9, 11)), ("vendor", "Other Co"), ("amount_paise", 120_051), ("description", "october rent")])
def test_one_differing_field_is_not_a_match(field, value) -> None:
    rows = imp.parse_csv(csv_of("2026-09-10,Acme Realty,September rent,operating_overhead,1200.50,,")).rows
    assert imp.classify(rows, [existing(**{field: value})])[0].status == imp.OK


def test_two_identical_rows_without_source_ids_in_one_file_are_probable_matches_not_dropped() -> None:
    line = "2026-09-10,Acme,coffee,other,50,,"
    out = imp.classify(imp.parse_csv(csv_of(line, line)).rows, [])
    assert [c.status for c in out] == [imp.OK, imp.PROBABLE_MATCH]


def test_normalise_ignores_case_punctuation_and_spacing() -> None:
    assert imp.normalise("  ACME,  Realty (Pvt.) Ltd ") == imp.normalise("acme realty pvt ltd") == "acme realty pvt ltd"
    assert imp.normalise(None) == ""


def test_the_parser_never_stores_or_returns_the_raw_text() -> None:
    r = imp.parse_csv(csv_of(GOOD))
    assert not hasattr(r, "text") and not hasattr(r, "raw") and "Acme Realty" not in repr(r.sha256)
