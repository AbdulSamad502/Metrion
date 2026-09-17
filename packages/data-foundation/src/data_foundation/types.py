"""Adapter contract types — data-foundation.md §2.2, verbatim where the spec gives an exact
shape (`ColumnBinding`, the `MarketplaceAdapter` Protocol). `FileSample`/`RawFile`/
`DetectionResult`/`ParsedRow` are named by the Protocol but never given field-level shape in
the spec — the shapes below are this package's own design, built to satisfy the Protocol's
stated contract rules (§2.2) exactly, not to add behavior the spec doesn't call for.

Scope boundary: `RawFile` takes already-tabular rows (a sequence of column-name -> raw-string
dicts). Decoding actual .xlsx/.csv bytes into that shape is a separate, ordinary file-I/O
concern this package does not implement — nothing in data-foundation.md's adapter contract
requires it, and no spec anywhere describes an upload transport. `report_file.storage_uri`
implies *something* reads bytes from object storage eventually, but that plumbing is out of
scope here; `detect()`/`parse()` operate on rows already shaped this way.

`Confidence`/`Paise` are imported from calc_engine, not redefined — both packages must agree
on the same four-level ranking and the same signed-paise contract (deterministic-engine.md
§7.1's confidence model is data-foundation.md's own, cross-referenced, not a separate one).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Mapping, Protocol, Sequence

from calc_engine.types import Confidence  # noqa: F401  (re-exported for convenience)


@dataclass(frozen=True, slots=True)
class ColumnBinding:
    """§2.2, verbatim shape."""

    canonical_field: str
    component_code: str | None
    is_verified: bool  # False for every binding in v1 (§2.3: no adapter validated against a real export)
    note: str | None = None


@dataclass(frozen=True, slots=True)
class FileSample:
    """What `detect()` inspects (§2.2 rule 1: "returns a confidence score and the set of
    expected-but-missing columns. It never mutates.") — header row only, no data rows needed
    for a column-presence check."""

    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawFile:
    """What `parse()` consumes — already-tabular rows. `rows` yields raw string values keyed
    by original column header; `parse()` never receives pre-converted types (§2.2 rule 2: pure,
    shape-only, no inference of what a string "should" mean beyond the declared column_map)."""

    columns: tuple[str, ...]
    rows: Sequence[Mapping[str, str]]


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """§2.2 rule 1. `matched_columns`/`expected_columns` are counts, not a money value — a
    plain Fraction keeps this package float-free throughout, consistent with calc-engine's own
    rule, even though CLAUDE.md's float ban is scoped to money arithmetic specifically."""

    matched: bool
    matched_columns: int
    expected_columns: int
    missing_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComponentValue:
    """One money-bearing column identified on a row, mapped onto `line_component`'s shape
    (data-foundation.md §1.4) — `amount_paise`/`tax_amount_paise` are already paise-integer by
    the time `parse()` emits this (see `dates.py`-adjacent note in each adapter on why the
    rupees-string -> paise-int conversion is a declared unit conversion, not the "arithmetic"
    §2.2 rule 2 prohibits — no summing, no derivation, no inference happens here)."""

    component_kind: str  # DISCOUNT | FEE | CHARGE | TAX | LEVY
    component_code: str
    source_side: str  # INVOICE | SETTLEMENT
    amount_paise: int
    tax_amount_paise: int | None
    rate_pct: str | None  # kept as the source's own decimal string; never float
    source_column: str
    is_verified: bool
    note: str | None


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """Output of `parse()` — shape only, per §2.2 rule 2. Nothing here has been validated
    (that's `validation/rules.py`'s job) or assigned a final confidence (that's the pipeline's
    job, after validation runs) — a `ParsedRow` is the direct, mechanical result of applying
    one adapter's `column_map`/`enum_maps`/`date_formats` to one raw row."""

    source_row_number: int
    source_row_json: dict[str, str]  # verbatim original row, every original column preserved
    canonical_fields: dict[str, object]  # sales_line-shaped: order_ref, quantity, dates, ...
    components: tuple[ComponentValue, ...]
    unknown_columns: tuple[str, ...]  # present in the row, absent from column_map (-> V-COL-001)
    unmapped_enum_fields: tuple[tuple[str, str], ...]  # (canonical_field, raw_value) -> V-ENUM-001


class MarketplaceAdapter(Protocol):
    """§2.2, verbatim in substance. Declared as read-only `@property` members (rather than
    plain attribute annotations) so a frozen dataclass — every adapter in `adapters/*.py` is
    one — satisfies this Protocol structurally; a plain annotation would require a settable
    attribute, which a frozen dataclass deliberately never offers (§2.2 rule 5: "Adapters are
    versioned and immutable once released")."""

    @property
    def adapter_id(self) -> str: ...

    @property
    def marketplace(self) -> str: ...

    @property
    def report_category(self) -> str: ...

    @property
    def format_version(self) -> str: ...

    @property
    def date_formats(self) -> Mapping[str, str]: ...

    @property
    def column_map(self) -> Mapping[str, ColumnBinding]: ...

    @property
    def enum_maps(self) -> Mapping[str, Mapping[str, str]]: ...

    def detect(self, sample: FileSample) -> DetectionResult: ...

    def parse(self, f: RawFile) -> Iterator[ParsedRow]: ...
