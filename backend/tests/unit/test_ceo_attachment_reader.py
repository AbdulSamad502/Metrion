"""Spec 6.34: the file reader. The type comes from the CONTENT, never the name; unsupported or hostile content is refused; extraction is bounded and untrusted."""

from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook
from PIL import Image

from backend.services import ceo_attachments as att
from tests.unit.pdf_fixture import make_pdf

PDF = make_pdf("Profit was 99999 last month")


def image(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format=fmt)
    return buf.getvalue()


def sheet(rows: int = 3) -> bytes:
    wb = Workbook()
    ws = wb.active
    for i in range(rows):
        ws.append([f"sku-{i}", i * 10, "=1+1"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize("data,expected", [(image("PNG"), "PNG"), (image("JPEG"), "JPEG"), (image("WEBP"), "WEBP"), (PDF, "PDF"), (sheet(), "XLSX"), (b"sku,qty\na,1\nb,2\n", "CSV")])
def test_the_type_is_detected_from_the_content(data, expected):
    assert att.detect_type(data) == expected
    assert att.check(data, max_bytes=10_000_000) == expected


@pytest.mark.parametrize("data", [b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64, b"\x7fELF\x02\x01\x01" + b"\x00" * 64, b"<html><script>alert(1)</script></html>", b"\x00\x01\x02binary\xff\xfe",
                                  b"PK\x03\x04not really a zip", b""])
def test_unsupported_or_hostile_content_is_refused_whatever_it_is_named(data):
    with pytest.raises(att.Unsupported):
        att.check(data, max_bytes=10_000_000)


def test_a_zip_that_is_not_a_spreadsheet_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("evil.txt", "x")
    with pytest.raises(att.Unsupported):
        att.detect_type(buf.getvalue())


def test_a_corrupt_image_and_an_oversized_file_are_refused():
    with pytest.raises(att.Unsupported):
        att.check(b"\x89PNG\r\n\x1a\n" + b"garbage", max_bytes=10_000_000)
    with pytest.raises(ValueError, match="too large"):
        att.check(b"a,b\n" * 100, max_bytes=10)


def test_pdf_text_is_extracted_and_returned_as_data():
    ex = att.extract(PDF, "PDF", max_pages=5)
    assert ex.status == "OK" and "Profit was 99999" in (ex.text or "")


def test_csv_and_xlsx_cells_are_read_and_formulas_are_never_evaluated():
    csv_ex = att.extract(b"sku,qty\na,1\nb,2\n", "CSV", max_pages=1)
    assert csv_ex.status == "OK" and "a\t1" in (csv_ex.text or "")
    x = att.extract(sheet(), "XLSX", max_pages=1)
    assert x.status == "OK" and "sku-1\t10" in (x.text or "")
    assert "=1+1" not in (x.text or "")  # a formula's text is not echoed as a value, and it is never evaluated


def test_long_files_are_cut_and_the_cut_is_named():
    big_csv = ("a,b\n" + "x,y\n" * (att.MAX_SHEET_ROWS + 50)).encode()
    ex = att.extract(big_csv, "CSV", max_pages=1)
    assert ex.status == "OK" and ex.note and "rows were read" in ex.note
    assert len((ex.text or "").splitlines()) == att.MAX_SHEET_ROWS


def test_an_image_is_kept_but_honestly_not_read():
    ex = att.extract(image("PNG"), "PNG", max_pages=1)
    assert ex.status == "NOT_READ" and ex.text is None and "not available yet" in (ex.note or "")


def test_a_broken_pdf_never_raises():
    ex = att.extract(b"%PDF-1.4 broken", "PDF", max_pages=1)
    assert ex.status in ("FAILED", "NOT_READ") and ex.text is None
