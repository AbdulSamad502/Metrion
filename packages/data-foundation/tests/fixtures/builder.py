"""Synthetic row builders for tests — every number here is copied verbatim from
data-foundation.md's own text (its §4.2 rule table's "observed in reference data" column),
never invented. See each test's docstring for the exact spec citation."""

from __future__ import annotations

from typing import Mapping

from data_foundation.types import FileSample, RawFile


def make_file(columns: tuple[str, ...], rows: list[Mapping[str, str]]) -> tuple[FileSample, RawFile]:
    return FileSample(columns=columns), RawFile(columns=columns, rows=rows)
