"""BaseAdapter — the shared detect()/parse() mechanics every adapter configures rather than
reimplements, per data-foundation.md §2.1 ("Adapters share an interface, never an
implementation") and §2.2's five contract rules.

**Column coverage is deliberately partial.** `data-foundation.md` states literal column
header names for only a subset of fields per marketplace: the §1.4 component_code registry
(fee/discount/tax/levy columns), the Amazon settlement seed-pairs table, and one comment in
§1.3 giving order_ref/line_ref/marketplace_item_id alternatives per marketplace. It never
states a literal header for `quantity`, `gross_item_amount`, `sku`, or any date column, for
any of the six adapters built here. Guessing one (e.g. assuming the header is literally
"Quantity") would be inventing a marketplace fact this project's rules prohibit. Every
`column_map` below therefore maps ONLY columns data-foundation.md actually quotes — every
other column present in a real file is structurally unknown to this adapter and correctly
raises `V-COL-001` (§2.2 rule 3: "Unknown columns are preserved, never dropped"), which is
the spec's own designed-for behavior for an incomplete mapping, not a bug. Filling in the
missing headers is data-foundation.md §9's validation procedure (against a real export), not
something to invent here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterator, Mapping

from data_foundation.component_registry import COMPONENT_KIND_BY_CODE
from data_foundation.types import ColumnBinding, ComponentValue, DetectionResult, FileSample, ParsedRow, RawFile


class MoneyParseError(ValueError):
    """A money column's raw value isn't a well-formed decimal string. Distinct from a missing
    value (blank -> None, not an error) — §2.2 rule 2 requires parse() to be shape-only, and a
    non-numeric string in a declared money column is a shape failure, not a judgment call."""


# sales_line's own money-scalar fields (data-foundation.md §1.3) — a ColumnBinding whose
# canonical_field is one of these gets the same declared rupees->paise unit conversion a
# component amount gets, since these are scalars on the row itself, not per-component amounts.
_MONEY_SCALAR_FIELDS = frozenset({"gross_item_amount", "taxable_amount", "total_invoice_amount"})


def rupees_to_paise(raw_value: str) -> int:
    """Rupees-string -> signed paise-int. This is a declared unit conversion of one stated
    value (multiply by 100, round to the nearest paise) — not the "arithmetic" §2.2 rule 2
    prohibits, which is about deriving/summing/inferring a value from others. Decimal only;
    a float never touches a money value in this package, matching calc-engine's own rule."""
    try:
        rupees = Decimal(raw_value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise MoneyParseError(f"{raw_value!r} is not a valid decimal money value") from exc
    return int((rupees * 100).to_integral_value())


@dataclass(frozen=True, slots=True)
class BaseAdapter:
    adapter_id: str
    marketplace: str
    report_category: str
    format_version: str
    date_formats: Mapping[str, str]
    column_map: Mapping[str, ColumnBinding]
    enum_maps: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    source_side: str = "INVOICE"  # every adapter built this pass is sales-side (settlement deferred)

    def detect(self, sample: FileSample) -> DetectionResult:
        """§2.2 rule 1: a confidence score + the missing-column diff. Declared, explicit
        column-presence check only — no heuristics about which marketplace a file "looks like"
        (§2.1)."""
        expected = set(self.column_map)
        present = set(sample.columns)
        missing = tuple(sorted(expected - present))
        return DetectionResult(
            matched=not missing,
            matched_columns=len(expected & present),
            expected_columns=len(expected),
            missing_columns=missing,
        )

    def parse(self, f: RawFile) -> Iterator[ParsedRow]:
        """§2.2 rule 2: pure and streaming, shape only. No validation, no arithmetic beyond
        the declared rupees->paise unit conversion, no inference."""
        for row_number, row in enumerate(f.rows, start=1):
            yield self._parse_row(row_number, row)

    def _parse_row(self, row_number: int, row: Mapping[str, str]) -> ParsedRow:
        canonical_fields: dict[str, object] = {}
        components: list[ComponentValue] = []
        unknown_columns: list[str] = []
        unmapped_enum_fields: list[tuple[str, str]] = []

        for column_name, raw_value in row.items():
            binding = self.column_map.get(column_name)
            if binding is None:
                unknown_columns.append(column_name)  # §2.2 rule 3: preserved, never dropped
                continue

            if binding.component_code is not None:
                components.append(
                    ComponentValue(
                        component_kind=COMPONENT_KIND_BY_CODE[binding.component_code],
                        component_code=binding.component_code,
                        source_side=self.source_side,
                        amount_paise=rupees_to_paise(raw_value) if raw_value.strip() else 0,
                        tax_amount_paise=None,  # no adapter here has a confirmed "tax on this fee" column
                        rate_pct=None,  # no adapter here has a confirmed rate column paired to this amount
                        source_column=column_name,
                        is_verified=binding.is_verified,
                        note=binding.note,
                    )
                )
                continue

            if binding.canonical_field in _MONEY_SCALAR_FIELDS:
                canonical_fields[binding.canonical_field] = (
                    rupees_to_paise(raw_value) if raw_value.strip() else None
                )
                continue

            enum_map = self.enum_maps.get(binding.canonical_field)
            if enum_map is not None:
                if raw_value not in enum_map:
                    # §2.2 rule 4: "It does not guess" — record the gap, don't invent a mapping
                    unmapped_enum_fields.append((binding.canonical_field, raw_value))
                    canonical_fields[binding.canonical_field] = None
                else:
                    canonical_fields[binding.canonical_field] = enum_map[raw_value]
            else:
                canonical_fields[binding.canonical_field] = raw_value or None

        return ParsedRow(
            source_row_number=row_number,
            source_row_json=dict(row),
            canonical_fields=canonical_fields,
            components=tuple(components),
            unknown_columns=tuple(unknown_columns),
            unmapped_enum_fields=tuple(unmapped_enum_fields),
        )
