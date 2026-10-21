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

# A row can be either a plain dict (existing behavior — every current adapter/test uses this;
# a dict literal cannot hold duplicate keys, so no duplicate-header case is possible this way)
# OR an ordered list of (header, value) tuples (new — the only way to represent a real export
# with two columns literally sharing the same header string, since a dict can't). Additive:
# nothing that constructs a RawFile with a dict today needs to change.
RowData = Mapping[str, str] | Sequence[tuple[str, str]]


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
    shape-only, no inference of what a string "should" mean beyond the declared column_map).

    Each row is a `RowData`: either a plain `dict[str, str]` (the common case — every adapter
    built so far uses this, and it is unchanged from before) or an ordered `Sequence[tuple[str,
    str]]` of (header, value) pairs. The tuple-list form exists solely to represent a real
    export where the same header string appears more than once at different column positions
    with different meanings (a plain dict cannot hold two entries for the same key, so it
    cannot represent that file shape at all) — see `adapters/base.py`'s occurrence-indexed
    `column_map` lookup for how a duplicate header is disambiguated."""

    columns: tuple[str, ...]
    rows: Sequence[RowData]


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
    source_row_json: dict[str, str]  # "verbatim" in the common case only — see source_row_pairs
    canonical_fields: dict[str, object]  # sales_line-shaped: order_ref, quantity, dates, ...
    components: tuple[ComponentValue, ...]
    unknown_columns: tuple[str, ...]  # present in the row, absent from column_map (-> V-COL-001)
    unmapped_enum_fields: tuple[tuple[str, str], ...]  # (canonical_field, raw_value) -> V-ENUM-001
    # Full-fidelity ordered copy of the row, additive alongside source_row_json (never replacing
    # it — existing callers/tests keep working unchanged). A real Meesho export
    # (meesho.payments.v1's "Order Payments" tab) was found to carry the SAME header twice
    # ("Fixed Fee (Incl. GST)" at two column positions with different meaning) — a Python dict
    # (source_row_json's type) cannot hold two entries under one key, so building it via
    # `dict(pairs)` silently keeps only the last-seen value, losing the other. `source_row_pairs`
    # is the ordered (header, value) list `_parse_row` actually iterated, before any
    # dict-collapsing — it is duplicate-safe by construction. No DDL/schema change is required
    # to persist it losslessly: the `jsonb` columns on `sales_line`/`settlement_line`
    # (data-foundation.md §1.3/§5.6) accept a JSON *array* of pairs exactly as readily as a JSON
    # object, so a future settlement-side persistence path can `json.dumps(source_row_pairs)`
    # into the same column type sales_line already uses for the dict form. Every adapter today
    # populates this field; only meesho.payments.v1 currently produces rows where it actually
    # differs in content from `source_row_json`.
    source_row_pairs: tuple[tuple[str, str], ...] = ()
    # (column header, raw value) pairs whose value could not be read under the mapping that produced this row
    # (a malformed number, an unreadable date). Only mapped (non-verified-adapter) sources populate it; a row with
    # any entry is quarantined by V-MAP-001 rather than crashing the run or posting a guessed value.
    parse_errors: tuple[tuple[str, str], ...] = ()


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
