"""Reading a file the seller attaches to a CEO conversation — spec §6.34.

Two jobs, both defensive: (1) decide what the file REALLY is from its content (the name and the declared type are never trusted), refusing anything outside the
supported set; (2) pull out bounded text for the CEO to quote. Nothing here executes content, follows a link, or interprets what a file says: extracted text is
UNTRUSTED data (R9). A reader that fails or times out yields a plain note and the file is still stored. Limits (bytes, files, pages) are configuration with no default.
"""

from __future__ import annotations

import csv
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass

SUPPORTED = ("PNG", "JPEG", "WEBP", "PDF", "CSV", "XLSX")
EXTRACT_TIMEOUT_SECONDS = 20  # a technical guard against a hostile or pathological file, not a business setting
MAX_EXTRACTED_CHARS = 20_000  # how much text is kept; the rest is named as cut off
MAX_SHEET_ROWS, MAX_SHEET_COLS = 200, 20
MAX_IMAGE_PIXELS = 50_000_000


class Unsupported(ValueError):
    """The content is not one of the supported types (or does not decode as one)."""


@dataclass(frozen=True, slots=True)
class Extraction:
    status: str  # OK | NOT_READ | FAILED
    note: str | None
    text: str | None


def detect_type(data: bytes) -> str:
    """The type from the content itself. A CSV has no signature, so it must decode as clean text with a consistent delimiter; anything else is refused."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data.startswith(b"%PDF-"):
        return "PDF"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names):
                    return "XLSX"
        except zipfile.BadZipFile:
            pass
        raise Unsupported("That archive is not a spreadsheet.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Unsupported("That file is not a supported type.") from None
    if "\x00" in text or not text.strip() or "," not in text and ";" not in text and "\t" not in text:
        raise Unsupported("That file is not a supported type.")
    return "CSV"


def _image_ok(data: bytes) -> str | None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > MAX_IMAGE_PIXELS:
                return "That image is too large (too many pixels)."
            im.verify()
    except Exception:  # noqa: BLE001 - a corrupt image is refused, never opened further
        return "That image could not be opened."
    return None


def check(data: bytes, *, max_bytes: int) -> str:
    """The detected type, or raise `Unsupported` / `ValueError("too large")`. The caller maps these to 415 / 413."""
    if len(data) == 0:
        raise Unsupported("That file is empty.")
    if len(data) > max_bytes:
        raise ValueError("too large")
    kind = detect_type(data)
    if kind in ("PNG", "JPEG", "WEBP"):
        problem = _image_ok(data)
        if problem:
            raise Unsupported(problem)
    return kind


def _cap(text: str) -> tuple[str, str | None]:
    return (text[:MAX_EXTRACTED_CHARS], f"Only the first {MAX_EXTRACTED_CHARS:,} characters were kept.") if len(text) > MAX_EXTRACTED_CHARS else (text, None)


def _pdf(data: bytes, max_pages: int) -> Extraction:
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        return Extraction("NOT_READ", "This PDF is password protected, so I could not read it.", None)
    pages = reader.pages[:max_pages]
    text = "\n".join((p.extract_text() or "") for p in pages).strip()
    cut = f"Only the first {max_pages} of {len(reader.pages)} pages were read." if len(reader.pages) > max_pages else None
    if not text:
        return Extraction("NOT_READ", "No text could be read from this PDF (it may be a scan of a page).", None)
    body, more = _cap(text)
    return Extraction("OK", " ".join(n for n in (cut, more) if n) or None, body)


def _csv(data: bytes) -> Extraction:
    text = data.decode("utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i >= MAX_SHEET_ROWS:
            break
        rows.append("\t".join(c.strip() for c in row[:MAX_SHEET_COLS]))
    body, more = _cap("\n".join(rows))
    total = text.count("\n") + 1
    cut = f"Only the first {MAX_SHEET_ROWS} rows were read." if total > MAX_SHEET_ROWS else None
    return Extraction("OK", " ".join(n for n in (cut, more) if n) or None, body)


def _xlsx(data: bytes) -> Extraction:
    from openpyxl import load_workbook  # type: ignore[import-untyped]

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)  # cell values only: formulas are never evaluated
    ws = wb.worksheets[0]
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i >= MAX_SHEET_ROWS:
            break
        rows.append("\t".join("" if c is None else str(c) for c in row[:MAX_SHEET_COLS]))
    body, more = _cap("\n".join(rows).strip())
    if not body:
        return Extraction("NOT_READ", "The first sheet of this workbook is empty.", None)
    note = f"Only the first sheet and its first {MAX_SHEET_ROWS} rows were read." if len(wb.worksheets) > 1 or ws.max_row and ws.max_row > MAX_SHEET_ROWS else None
    return Extraction("OK", " ".join(n for n in (note, more) if n) or None, body)


def extract(data: bytes, kind: str, *, max_pages: int) -> Extraction:
    """Bounded text for the CEO to quote. Never raises: a failure is `FAILED` with a plain note."""
    if kind in ("PNG", "JPEG", "WEBP"):
        return Extraction("NOT_READ", "Images are saved with your conversation. Reading what is in an image is not available yet.", None)

    def work() -> Extraction:
        return _pdf(data, max_pages) if kind == "PDF" else _csv(data) if kind == "CSV" else _xlsx(data)

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ceo-extract")
    try:
        return pool.submit(work).result(timeout=EXTRACT_TIMEOUT_SECONDS)
    except FutureTimeout:
        return Extraction("FAILED", "Reading this file took too long, so I stopped.", None)
    except Exception:  # noqa: BLE001
        return Extraction("FAILED", "I could not read this file.", None)
    finally:
        pool.shutdown(wait=False)
