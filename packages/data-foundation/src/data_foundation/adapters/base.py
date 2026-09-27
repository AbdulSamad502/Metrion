"""BaseAdapter — the shared detect()/parse() mechanics every adapter configures rather than
reimplements, per data-foundation.md §2.1 ("Adapters share an interface, never an
implementation") and §2.2's five contract rules.

**Column coverage is deliberately partial.** `data-foundation.md` states literal column
header names for only a subset of fields per marketplace: the §1.4 component_code registry
(fee/discount/tax/levy columns), the Amazon settlement seed-pairs table, and one comment in
§1.3 giving order_ref/line_ref/marketplace_item_id alternatives per marketplace. It never
states a literal header for `quantity`, `gross_item_amount`, `sku`, or any date column, for
any of the adapters built so far. Guessing one (e.g. assuming the header is literally
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
from data_foundation.types import ColumnBinding, ComponentValue, DetectionResult, FileSample, ParsedRow, RawFile, RowData


class MoneyParseError(ValueError):
    """A money column's raw value isn't a well-formed decimal string. Distinct from a missing
    value (blank -> None, not an error) — §2.2 rule 2 requires parse() to be shape-only, and a
    non-numeric string in a declared money column is a shape failure, not a judgment call."""


# sales_line's own money-scalar fields (data-foundation.md §1.3), plus settlement_line's own
# scalar money field (§5.6, "gross_settlement_amount") — a ColumnBinding whose canonical_field
# is one of these gets the same declared rupees->paise unit conversion a component amount
# gets, since these are scalars on the row itself, not per-component amounts. Purely additive:
# no sales-side adapter ever produces a canonical_field named "gross_settlement_amount", so
# adding it here changes nothing for any existing adapter.
#
# "total_sale_amount" (added this pass, architect-pass finding on data-foundation.md §5.4):
# the Payments workbook's real "Total Sale Amount (Incl. Shipping & GST)" column (letter B in
# the 18-term Final Settlement Amount formula) — the fee-base amount a future rate-card-based
# variance model (resolve_fee_reference, not an invoice-side line_component, since no real
# invoice-side fee document exists for Meesho — see the architect finding) would apply a
# fee_reference rate to. `settlement_line`'s current migration (§5.6) has NO column for this
# value yet — it is captured here in ParsedRow.canonical_fields/source_row_pairs, with nowhere
# to persist to a real DB column until that's added. That is a real, separate follow-up
# (a schema question, not invented here) — not blocking capturing the value at parse time.
#
# "settlement_amount_value" (added this pass, data-foundation.md §5.1.4): amazon.settlement.v2's
# melted-triple `amount` column — the same "captured now, schema question resolved later"
# posture as total_sale_amount above. Amazon's real amount values are signed (e.g. a negative
# fee); Decimal parses a leading "-" natively, so rupees_to_paise needs no special-casing for
# this field. Purely additive: no other adapter ever produces this canonical_field.
_MONEY_SCALAR_FIELDS = frozenset(
    {
        "gross_item_amount",
        "taxable_amount",
        "total_invoice_amount",
        "gross_settlement_amount",
        "total_sale_amount",
        "settlement_amount_value",
    }
)


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
    # A bare string key means "occurrence 0 of this header" — every existing adapter's
    # column_map uses only bare strings and has zero duplicate headers, so this is unchanged
    # for them. A (header, occurrence_index) tuple key explicitly targets the Nth occurrence
    # (0-indexed) of a repeated header — how a future adapter disambiguates a real file with
    # the same header string appearing more than once (e.g. meesho.payments.v1's two columns
    # both literally named "Fixed Fee (Incl. GST)").
    column_map: Mapping[str | tuple[str, int], ColumnBinding]
    enum_maps: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    source_side: str = "INVOICE"  # default for sales-side adapters; meesho.payments.v1 overrides to "SETTLEMENT"

    def __post_init__(self) -> None:
        """Ambiguity validation at construction time, not per-row at parse time. A bare string
        key `"X"` and an explicit tuple key `("X", 0)` both target the same thing — occurrence
        0 of header "X" — so having both in the same column_map is an ambiguous binding for
        that occurrence, never a legitimate configuration. Fails fast at adapter-definition/
        import time."""
        bare_headers = {key for key in self.column_map if isinstance(key, str)}
        for key in self.column_map:
            if isinstance(key, tuple) and key[1] == 0 and key[0] in bare_headers:
                raise ValueError(
                    f"ambiguous column_map binding for header {key[0]!r}: both the bare-string "
                    f"key {key[0]!r} and the explicit tuple key {key!r} target occurrence 0 of "
                    "the same header — use only one"
                )

    def detect(self, sample: FileSample) -> DetectionResult:
        """§2.2 rule 1: a confidence score + the missing-column diff. Declared, explicit
        column-presence check only — no heuristics about which marketplace a file "looks like"
        (§2.1).

        `FileSample.columns` is a header-presence set, not occurrence-aware (a header either
        appears in the file's header row or it doesn't) — so `expected` is derived from the
        distinct header names in `column_map`, unwrapping any `(header, occurrence_index)`
        tuple key to its header. For every adapter whose column_map uses only bare-string keys
        (i.e. every adapter except meesho.payments.v1's duplicate-header binding), this is
        identical to `set(self.column_map)` as before — unchanged."""
        expected = {key[0] if isinstance(key, tuple) else key for key in self.column_map}
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

    def _parse_row(self, row_number: int, row: RowData) -> ParsedRow:
        canonical_fields: dict[str, object] = {}
        components: list[ComponentValue] = []
        unknown_columns: list[str] = []
        unmapped_enum_fields: list[tuple[str, str]] = []

        # Normalize into an ordered list of (header, value) pairs regardless of which RowData
        # form was given — a plain dict (the common case, zero duplicates possible) or an
        # already-ordered list of pairs (the only form that can carry duplicate headers).
        pairs: list[tuple[str, str]] = list(row.items()) if isinstance(row, Mapping) else list(row)

        occurrence_counts: dict[str, int] = {}
        for column_name, raw_value in pairs:
            idx = occurrence_counts.get(column_name, 0)
            occurrence_counts[column_name] = idx + 1

            binding = self.column_map.get((column_name, idx))
            if binding is None and idx == 0:
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
            source_row_json=dict(pairs),  # lossy on a true duplicate header — see source_row_pairs
            canonical_fields=canonical_fields,
            components=tuple(components),
            unknown_columns=tuple(unknown_columns),
            unmapped_enum_fields=tuple(unmapped_enum_fields),
            source_row_pairs=tuple(pairs),  # duplicate-safe, full-fidelity ordered copy
        )
