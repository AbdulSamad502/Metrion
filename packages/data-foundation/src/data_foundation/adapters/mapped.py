"""An adapter built from a *seller-confirmed* column mapping (cfo-data-intelligence.md §6.4, §6.5).

For a file no verified adapter recognises, a confirmed mapping (proposed, validated and confirmed — never
auto-trusted) is turned into an object that satisfies the same `MarketplaceAdapter` protocol, so the rows
flow through exactly the same validation, duplicate classification and persistence as a known format.

What it guarantees, and what it refuses:

* Every row is `PROVISIONAL` (the pipeline's rule for any non-verified binding); every component is
  `is_verified=False`; the mapping id and version travel as the `adapter_id` / `format_version` of the
  ingestion run, so any number traces back to the exact mapping a seller confirmed.
* Values are normalised by the confirmed transform (rupees to paise, paise as-is, DD/MM or MM/DD or ISO
  dates, sign). A value that cannot be read becomes a `parse_errors` entry — the row is quarantined by
  V-MAP-001 with the column and value named; it is never crashed on and never defaulted.
* **Refused: GST-inclusive money for mapped sources.** The engine's tax normalisation (§8.1) has no path
  for a mapped, GST-inclusive gross amount yet, and posting it as tax-exclusive would silently overstate
  revenue. Such a mapping raises `MappedAdapterUnsupported` and the job fails with a clear message.
* Only SALES and SETTLEMENT mappings produce rows here; expense and advertising files have their own
  ingestion paths.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterator

from data_foundation.adapters.base import rupees_to_paise
from data_foundation.component_registry import COMPONENT_KIND_BY_CODE
from data_foundation.mapping import vocab as V
from data_foundation.mapping.profile import parse_date_with, parse_decimal
from data_foundation.types import ColumnBinding, ComponentValue, DetectionResult, FileSample, ParsedRow, RawFile

_RESOLVED = frozenset({"AUTO_ACCEPTED_BY_RULES", "SELLER_CONFIRMED", "SELLER_OVERRIDDEN"})
_GROSS_LIKE = frozenset({"gross_item_amount", "total_invoice_amount"})


class MappedAdapterUnsupported(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class MappedField:
    index: int
    header: str
    canonical_field: str
    component_code: str | None
    transform: str
    sign_convention: str | None
    tax_inclusion: str | None


_BAD = object()  # sentinel: the cell is present but cannot be read


def _money(raw: str, transform: str, sign: str | None) -> Any:
    if not raw.strip():
        return None
    d = parse_decimal(raw)
    if d is None:
        return _BAD
    if transform == "RUPEES_TO_PAISE":
        d = d * 100
    if d != d.to_integral_value():
        return _BAD
    paise = int(d)
    return -paise if sign == "NEGATE" else paise


@dataclass(frozen=True, slots=True)
class MappedAdapter:
    adapter_id: str
    marketplace: str
    report_category: str
    format_version: str
    columns: tuple[str, ...]
    fields: tuple[MappedField, ...]
    ignored_indexes: frozenset[int] = frozenset()
    source_side: str = "INVOICE"
    date_formats: Mapping[str, str] = field(default_factory=dict)
    enum_maps: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    @property
    def column_map(self) -> Mapping[str, ColumnBinding]:
        out: dict[str, ColumnBinding] = {}
        for f in self.fields:
            out.setdefault(f.header, ColumnBinding(canonical_field=f.canonical_field, component_code=f.component_code,
                                                   is_verified=False, note=f"seller-confirmed mapping {self.adapter_id}"))
        return out

    def detect(self, sample: FileSample) -> DetectionResult:
        """The file must have exactly the shape the mapping was confirmed for: the same headers at the same positions."""
        expected = {f.header for f in self.fields}
        missing = tuple(sorted(expected - set(sample.columns)))
        same_shape = tuple(sample.columns) == self.columns
        return DetectionResult(matched=same_shape and not missing, matched_columns=len(expected & set(sample.columns)),
                               expected_columns=len(expected), missing_columns=missing)

    def parse(self, f: RawFile) -> Iterator[ParsedRow]:
        for n, row in enumerate(f.rows, start=1):
            yield self._parse_row(n, row)

    def _parse_row(self, n: int, row: Any) -> ParsedRow:
        pairs: list[tuple[str, str]] = list(row.items()) if isinstance(row, Mapping) else list(row)
        canonical: dict[str, object] = {}
        components: list[ComponentValue] = []
        errors: list[tuple[str, str]] = []
        for fld in self.fields:
            raw = pairs[fld.index][1] if fld.index < len(pairs) else ""
            raw = raw if raw is not None else ""
            spec = V.CANONICAL_FIELDS[fld.canonical_field]
            vt = spec.value_type

            if fld.canonical_field == V.COMPONENT_FIELD:
                amount = _money(raw, fld.transform, fld.sign_convention)
                if amount is _BAD:
                    errors.append((fld.header, raw))
                    continue
                assert fld.component_code is not None
                components.append(ComponentValue(
                    component_kind=COMPONENT_KIND_BY_CODE[fld.component_code], component_code=fld.component_code,
                    source_side=self.source_side, amount_paise=int(amount) if amount is not None else 0,  # blank fee column = no fee (same as verified adapters)
                    tax_amount_paise=None, rate_pct=None, source_column=fld.header, is_verified=False,
                    note=f"mapped {self.adapter_id}; sign={fld.sign_convention or 'AS_IS'}",
                ))
            elif vt == "money":
                value = _money(raw, fld.transform, fld.sign_convention)
                if value is _BAD:
                    errors.append((fld.header, raw))
                else:
                    canonical[fld.canonical_field] = value
            elif vt == "int":
                if not raw.strip():
                    canonical[fld.canonical_field] = None
                else:
                    d = parse_decimal(raw)
                    if d is None or d != d.to_integral_value():
                        errors.append((fld.header, raw))
                    else:
                        canonical[fld.canonical_field] = int(d)
            elif vt == "date":
                if not raw.strip():
                    canonical[fld.canonical_field] = None
                else:
                    parsed = parse_date_with(raw, fld.transform)
                    if parsed is None:
                        errors.append((fld.header, raw))
                    else:
                        canonical[fld.canonical_field] = parsed
            elif vt == "percent":
                if not raw.strip():
                    canonical[fld.canonical_field] = None
                else:
                    d = parse_decimal(raw.replace("%", ""))
                    if d is None:
                        errors.append((fld.header, raw))
                    else:
                        canonical[fld.canonical_field] = format(d.normalize(), "f")  # percentage points, as verified adapters store it
            else:  # text / enum
                value_s = raw.strip()
                if fld.canonical_field == "currency" and value_s.lower() in {"inr", "rs", "rs.", "₹", "rupee", "rupees"}:
                    value_s = "INR"
                canonical[fld.canonical_field] = value_s or None

        unknown = tuple(h for i, (h, _) in enumerate(pairs) if i not in {f.index for f in self.fields} and i not in self.ignored_indexes)
        return ParsedRow(
            source_row_number=n, source_row_json=dict(pairs), canonical_fields=canonical, components=tuple(components),
            unknown_columns=unknown, unmapped_enum_fields=(), source_row_pairs=tuple(pairs), parse_errors=tuple(errors),
        )


def adapter_from_mapping(mapping: Mapping[str, Any], columns: Sequence[str], marketplace: str) -> MappedAdapter:
    """Build the adapter for a CONFIRMED mapping (the dict `column_mapping_repo.get_mapping` returns).

    Raises `MappedAdapterUnsupported` for anything that cannot be posted honestly, so the caller fails the job with
    a plain reason instead of posting a number that is silently wrong."""
    if mapping["status"] != "CONFIRMED":
        raise MappedAdapterUnsupported("MAPPING_NOT_CONFIRMED", "this column mapping has not been confirmed by the seller")
    kind = mapping["report_kind"]
    if kind not in ("SALES", "SETTLEMENT"):
        raise MappedAdapterUnsupported("MAPPED_KIND_UNSUPPORTED", f"{kind} files are not ingested through the order/settlement path")
    fields: list[MappedField] = []
    for f in mapping["fields"]:
        if f["decision"] not in _RESOLVED:
            raise MappedAdapterUnsupported("MAPPING_UNRESOLVED", f"column {f['source_column']!r} has no confirmed decision")
        idx = int(f["source_column_index"])
        if idx >= len(columns) or columns[idx] != f["source_column"]:
            raise MappedAdapterUnsupported("MAPPING_SHAPE_CHANGED", f"column {f['source_column']!r} is no longer at position {idx}")
        if f["canonical_field"] in _GROSS_LIKE and f.get("tax_inclusion") != "EXCLUSIVE":
            raise MappedAdapterUnsupported(
                "TAX_INCLUSIVE_UNSUPPORTED_FOR_MAPPED",
                f"column {f['source_column']!r} includes GST (or its GST treatment is unknown). Metrion cannot yet extract GST from a mapped file, and "
                "posting it as tax-exclusive would overstate revenue. Upload a report that has a tax-exclusive amount, or contact support.",
            )
        fields.append(MappedField(idx, f["source_column"], f["canonical_field"], f.get("component_code"), f["transform"],
                                  f.get("sign_convention"), f.get("tax_inclusion")))
    mapped_idx = {f.index for f in fields}
    category = "SETTLEMENT" if kind == "SETTLEMENT" else "TAX"
    return MappedAdapter(
        adapter_id=f"mapped.{mapping['id']}", marketplace=marketplace, report_category=category,
        format_version=f"v{mapping['version']}", columns=tuple(columns), fields=tuple(sorted(fields, key=lambda x: x.index)),
        ignored_indexes=frozenset(i for i in range(len(columns)) if i not in mapped_idx),
        source_side="SETTLEMENT" if kind == "SETTLEMENT" else "INVOICE",
    )
