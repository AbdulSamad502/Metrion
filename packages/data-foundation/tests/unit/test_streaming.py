"""Streaming CSV/XLSX reader tests (cfo-data-intelligence.md §12 TD1, TD2, TD10, TD14; AC-D1, AC-D2, AC-D10)."""

from __future__ import annotations

import tracemalloc
import zipfile
from datetime import datetime
from fractions import Fraction
from pathlib import Path

import pytest

from data_foundation.ingestion.file_reader import read_csv_file
from data_foundation.ingestion.streaming import (
    StreamError,
    StreamLimits,
    check_xlsx_archive,
    list_xlsx_sheets,
    open_csv,
    open_report,
    open_xlsx,
)

LIM = StreamLimits(
    chunk_rows=1000, max_rows=500_000, header_scan_rows=30, min_header_fill=Fraction(6, 10),
    max_uncompressed_bytes=50 * 1024 * 1024, max_zip_ratio=200, max_zip_members=200, max_sheets=20,
)


def write(path: Path, text: str, enc: str = "utf-8") -> Path:
    path.write_bytes(text.encode(enc))
    return path


def all_rows(stream) -> list:  # type: ignore[no-untyped-def]
    out: list = []
    for chunk in stream.chunks():
        out.extend(chunk.rows)
    return out


# ------------------------------------------------------------------------------------------ CSV
def test_csv_matches_the_old_reader_row_for_row(tmp_path: Path) -> None:
    body = "Order ID,Qty,Item Price\n" + "\n".join(f"OD{i},1,{100 + i}.00" for i in range(2500)) + "\n"
    p = write(tmp_path / "a.csv", body)
    _, old = read_csv_file(p.read_bytes())
    s = open_csv(p, LIM)
    assert s.header.columns == old.columns
    assert all_rows(s) == list(old.rows)  # golden: identical to the legacy path (AC-D2)


def test_chunks_are_bounded(tmp_path: Path) -> None:
    p = write(tmp_path / "a.csv", "A,B\n" + "\n".join(f"{i},x" for i in range(2500)) + "\n")
    sizes = [len(c.rows) for c in open_csv(p, LIM).chunks()]
    assert sizes == [1000, 1000, 500] and max(sizes) <= LIM.chunk_rows


def test_bom_header_not_on_first_row_blank_and_ragged_rows(tmp_path: Path) -> None:
    text = "﻿Marketplace Report,,\nGenerated 21 Oct,,\nOrder ID,Qty,Amount\nOD1,1,10\n\nOD2,2\nOD3,3,30,EXTRA\n"
    s = open_csv(write(tmp_path / "b.csv", text), LIM)
    assert s.header.columns == ("Order ID", "Qty", "Amount") and s.header.header_row_index == 2
    rows = all_rows(s)
    assert rows == [{"Order ID": "OD1", "Qty": "1", "Amount": "10"}, {"Order ID": "OD2", "Qty": "2", "Amount": ""},
                    {"Order ID": "OD3", "Qty": "3", "Amount": "30"}]
    assert s.stats.blank_rows_skipped == 1 and s.stats.ragged_rows == 2 and s.stats.rows_read == 3


def test_duplicate_headers_become_ordered_pairs(tmp_path: Path) -> None:
    s = open_csv(write(tmp_path / "d.csv", "Fixed Fee (Incl. GST),Order,Fixed Fee (Incl. GST)\n5,OD1,7\n"), LIM)
    assert s.header.has_duplicate_headers
    (row,) = all_rows(s)
    assert row == (("Fixed Fee (Incl. GST)", "5"), ("Order", "OD1"), ("Fixed Fee (Incl. GST)", "7"))


def test_cp1252_files_are_decoded(tmp_path: Path) -> None:
    s = open_csv(write(tmp_path / "c.csv", "Item,Price\nCaf\xe9 Kurti,10\n", enc="cp1252"), LIM)
    assert s.header.encoding == "cp1252"
    assert all_rows(s)[0]["Item"] == "Café Kurti"


def test_empty_header_only_and_headerless_files(tmp_path: Path) -> None:
    with pytest.raises(StreamError) as e:
        open_csv(write(tmp_path / "e.csv", ""), LIM)
    assert e.value.code == "empty_file"
    s = open_csv(write(tmp_path / "h.csv", "A,B,C\n"), LIM)
    assert all_rows(s) == [] and s.stats.rows_read == 0  # header-only: valid, zero rows (TD14)
    with pytest.raises(StreamError) as e2:
        open_csv(write(tmp_path / "n.csv", "1,2,3\n4,5,6\n7,8,9\n"), LIM)
    assert e2.value.code == "no_header"


def test_row_cap_is_enforced(tmp_path: Path) -> None:
    lim = StreamLimits(chunk_rows=LIM.chunk_rows, max_rows=10, header_scan_rows=LIM.header_scan_rows, min_header_fill=LIM.min_header_fill,
                       max_uncompressed_bytes=LIM.max_uncompressed_bytes, max_zip_ratio=LIM.max_zip_ratio,
                       max_zip_members=LIM.max_zip_members, max_sheets=LIM.max_sheets)
    p = write(tmp_path / "big.csv", "A\n" + "\n".join(str(i) for i in range(50)) + "\n")
    with pytest.raises(StreamError) as e:
        all_rows(open_csv(p, lim))
    assert e.value.code == "too_large"


def test_memory_is_bounded_by_the_chunk_not_the_file(tmp_path: Path) -> None:
    """AC-D1: stream 100k rows while retaining nothing; peak traced memory stays far below the old ~31x path."""
    p = tmp_path / "large.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write("Order ID,SKU,Qty,Item Price,Taxable Value,Status\n")
        for i in range(100_000):
            fh.write(f"OD{i:09d},SKU-{i % 500},1,{100 + i % 900}.00,{85 + i % 900}.00,DELIVERED\n")
    size = p.stat().st_size
    tracemalloc.start()
    n = 0
    for chunk in open_csv(p, LIM).chunks():
        n += len(chunk.rows)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert n == 100_000
    assert peak < size, f"peak {peak} bytes should be below the file size {size}; old path was ~31x the file"


# ----------------------------------------------------------------------------------------- XLSX
def make_xlsx(path: Path, *, sheets: dict[str, list[list[object]]], hidden: tuple[str, ...] = ()) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
        if name in hidden:
            ws.sheet_state = "hidden"
    wb.save(path)
    return path


def test_xlsx_streams_with_value_conversion(tmp_path: Path) -> None:
    rows = [["Order ID", "Qty", "Item Price", "Invoice Date", "Paid"],
            ["OD1", 1, 118.5, datetime(2026, 10, 5), True],
            ["OD2", 2, 1e-05, datetime(2026, 10, 6, 14, 30), False]]
    s = open_xlsx(make_xlsx(tmp_path / "a.xlsx", sheets={"Orders": rows}), LIM)
    assert s.header.sheet_name == "Orders" and s.header.columns == ("Order ID", "Qty", "Item Price", "Invoice Date", "Paid")
    r1, r2 = all_rows(s)
    assert r1 == {"Order ID": "OD1", "Qty": "1", "Item Price": "118.5", "Invoice Date": "2026-10-05", "Paid": "TRUE"}
    assert r2["Item Price"] == "0.00001" and r2["Invoice Date"] == "2026-10-06 14:30:00"  # no scientific notation


def test_xlsx_with_a_wrong_declared_dimension_still_yields_every_column(tmp_path: Path) -> None:
    # The Meesho GST workbooks declare a sheet dimension of A1 although the sheet holds many columns; without ignoring it only column A is read.
    rows = [["sub_order_num", "gst_rate", "total_taxable_sale_value"], ["O-1_1", "18.00", "100.5"], ["O-2_1", "5.00", "40"]]
    src = make_xlsx(tmp_path / "ok.xlsx", sheets={"3609938": rows})
    bad = tmp_path / "bad.xlsx"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                import re

                data = re.sub(rb'<dimension ref="[^"]*"\s*/>', b'<dimension ref="A1"/>', data)
                assert b'<dimension ref="A1"/>' in data
            zout.writestr(item, data)
    s = open_xlsx(bad, LIM)
    assert s.header.columns == ("sub_order_num", "gst_rate", "total_taxable_sale_value")
    assert [r["total_taxable_sale_value"] for r in all_rows(s)] == ["100.5", "40"]


def test_xlsx_header_offset_multi_sheet_selection_and_hidden_sheets(tmp_path: Path) -> None:
    p = make_xlsx(tmp_path / "m.xlsx", sheets={
        "Summary": [["Total", 5]],
        "Orders": [["Seller Report"], [], ["Order ID", "Qty"], ["OD1", 1], ["OD2", 2]],
        "Secret": [["Order ID", "Qty"], ["X", 9]],
    }, hidden=("Secret",))
    sheets = dict(list_xlsx_sheets(p, LIM))
    assert "Secret" not in sheets and sheets["Orders"] is True and sheets["Summary"] is False
    s = open_xlsx(p, LIM, sheet_name="Orders")
    assert s.header.header_row_index == 2 and len(all_rows(s)) == 2
    with pytest.raises(StreamError) as e:
        open_xlsx(p, LIM, sheet_name="Secret")
    assert e.value.code == "no_sheet"
    with pytest.raises(StreamError) as e2:
        open_xlsx(p, LIM, sheet_name="Summary")
    assert e2.value.code == "no_header"


def test_xlsx_formula_without_cached_value_reads_as_blank_never_a_guess(tmp_path: Path) -> None:
    s = open_xlsx(make_xlsx(tmp_path / "f.xlsx", sheets={"S": [["A", "B"], [1, "=A2*2"]]}), LIM)
    (row,) = all_rows(s)
    assert row["B"] == ""  # downstream this is a missing input -> UNAVAILABLE, not 0


def test_zip_bomb_is_rejected_before_any_parser_opens_it(tmp_path: Path) -> None:
    p = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/worksheets/sheet1.xml", b"\0" * (40 * 1024 * 1024))  # ~40 MB of zeros compresses to ~40 KB
    with pytest.raises(StreamError) as e:
        check_xlsx_archive(p, LIM)
    assert e.value.code == "unsafe_archive" and "zip bomb" in e.value.detail
    with pytest.raises(StreamError):
        open_xlsx(p, LIM)


def test_oversized_and_part_heavy_archives_and_non_xlsx(tmp_path: Path) -> None:
    tight = StreamLimits(chunk_rows=10, max_rows=10, header_scan_rows=5, min_header_fill=Fraction(6, 10),
                         max_uncompressed_bytes=1000, max_zip_ratio=10_000, max_zip_members=3, max_sheets=2)
    p = make_xlsx(tmp_path / "ok.xlsx", sheets={"S": [["A"], ["1"]]})
    with pytest.raises(StreamError) as e:
        check_xlsx_archive(p, tight)
    assert e.value.code == "unsafe_archive"
    junk = write(tmp_path / "junk.xlsx", "not a zip")
    with pytest.raises(StreamError) as e2:
        check_xlsx_archive(junk, LIM)
    assert e2.value.code == "not_xlsx"
    plain_zip = tmp_path / "plain.xlsx"
    with zipfile.ZipFile(plain_zip, "w") as zf:
        zf.writestr("hello.txt", "x")
    with pytest.raises(StreamError) as e3:
        check_xlsx_archive(plain_zip, LIM)
    assert e3.value.code == "not_xlsx"


def test_too_many_sheets_rejected(tmp_path: Path) -> None:
    lim = StreamLimits(chunk_rows=10, max_rows=10, header_scan_rows=5, min_header_fill=Fraction(6, 10),
                       max_uncompressed_bytes=50 * 1024 * 1024, max_zip_ratio=200, max_zip_members=200, max_sheets=2)
    p = make_xlsx(tmp_path / "many.xlsx", sheets={f"S{i}": [["A"], ["1"]] for i in range(4)})
    with pytest.raises(StreamError) as e:
        open_xlsx(p, lim)
    assert e.value.code == "unsafe_archive"


# ---------------------------------------------------------------------------------- dispatcher
@pytest.mark.parametrize("name", ["report.xlsm", "report.xls", "report.xlsb", "report.pdf", "report"])
def test_unsupported_types_are_refused_with_a_reason(tmp_path: Path, name: str) -> None:
    p = write(tmp_path / name, "x")
    with pytest.raises(StreamError) as e:
        open_report(p, LIM)
    assert e.value.code == "unsupported_type"


def test_dispatch_by_extension(tmp_path: Path) -> None:
    assert open_report(write(tmp_path / "a.csv", "A,B\n1,2\n"), LIM).header.columns == ("A", "B")
    assert open_report(make_xlsx(tmp_path / "a.xlsx", sheets={"S": [["A", "B"], [1, 2]]}), LIM).header.sheet_name == "S"
