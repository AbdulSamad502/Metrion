"""Raw CSV bytes -> FileSample/RawFile (§2.2's pure input shapes). CSV only this pass — XLSX
via openpyxl is a same-shaped follow-up, not attempted here to keep this increment reviewable.
"""

from __future__ import annotations

import csv
import io

from data_foundation.types import FileSample, RawFile


def read_csv_file(content: bytes) -> tuple[FileSample, RawFile]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    columns = tuple(reader.fieldnames or ())
    rows = [dict(row) for row in reader]
    return FileSample(columns=columns), RawFile(columns=columns, rows=rows)
