"""One bounded pass over a file to gather what mapping needs (cfo-data-intelligence.md §6.4, D7).

Reads the stream once, keeps only: the first `profile_rows` rows (for column profiles and the tax/grain checks),
a deterministic reservoir sample of `sample_rows` rows drawn across the *whole* file (so a model sees the file's
middle and end, not just its top), and the row count. The sample is masked before it leaves this module. Memory is
bounded by `profile_rows + sample_rows`, never by file size.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from data_foundation.ingestion.streaming import RowStream
from data_foundation.mapping.masking import mask_sample
from data_foundation.mapping.profile import ColumnProfile, file_fingerprint, profile_columns


@dataclass(frozen=True, slots=True)
class ProfileInput:
    columns: tuple[str, ...]
    header_row_index: int
    sheet_name: str | None
    fingerprint: str
    profile_rows: tuple[tuple[str, ...], ...]  # unmasked, first rows — validator-internal, never sent to a model
    masked_sample: tuple[tuple[str, ...], ...]  # the only rows a model may see
    profiles: tuple[ColumnProfile, ...]
    total_rows: int


def _cells(row: object, width: int) -> tuple[str, ...]:
    values = [v for _, v in row] if not isinstance(row, Mapping) else list(row.values())  # type: ignore[union-attr]
    values = [("" if v is None else str(v)) for v in values]
    return tuple((values + [""] * width)[:width])


def collect_profile_input(stream: RowStream, *, profile_rows: int, sample_rows: int, seed: int) -> ProfileInput:
    cols = stream.header.columns
    width = len(cols)
    rng = random.Random(seed)
    first: list[tuple[str, ...]] = []
    reservoir: list[tuple[str, ...]] = []
    seen = 0
    for chunk in stream.chunks():
        for raw in chunk.rows:
            cells = _cells(raw, width)
            if len(first) < profile_rows:
                first.append(cells)
            seen += 1
            if len(reservoir) < sample_rows:
                reservoir.append(cells)
            else:
                j = rng.randrange(seen)
                if j < sample_rows:
                    reservoir[j] = cells
    profiles = profile_columns(cols, first)
    return ProfileInput(
        columns=cols, header_row_index=stream.header.header_row_index, sheet_name=stream.header.sheet_name,
        fingerprint=file_fingerprint(cols, stream.header.sheet_name), profile_rows=tuple(first),
        masked_sample=tuple(tuple(r) for r in mask_sample(cols, reservoir)), profiles=profiles, total_rows=seen,
    )
