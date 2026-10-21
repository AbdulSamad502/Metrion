"""Deterministic mapping validator (cfo-data-intelligence.md §6.4: M-VOC … M-REQ).

Given a *proposal* (from a model, mocked in tests, or typed by the seller) and measurements of the file
(column profiles, a bounded sample), decide per field whether the mapping is (a) an error, (b) acceptable
only after the seller confirms it, or (c) auto-acceptable. Auto-accept is deliberately narrow: every rule
must pass AND the source header must exactly match a header a verified adapter already knows. A plausible
synonym ("Item Price", "Sale Amount") never auto-accepts — tax inclusion, sign, unit and enum domains are
always the seller's call unless measured and consistent.

Pure: no I/O, no clock (`as_of` is a parameter), no model. Money comparisons use exact `Decimal`/int paise.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from data_foundation.component_registry import COMPONENT_KIND_BY_CODE
from data_foundation.mapping import vocab as V
from data_foundation.mapping.profile import ColumnProfile, parse_decimal
from data_foundation.mapping.proposal import FieldProposal, MappingProposal
from data_foundation.mapping.units import percent_unit_is_ambiguous

_TAX_CODES = frozenset({"CGST", "SGST", "IGST", "UTGST", "CESS"})
_GROSS_LIKE = ("total_invoice_amount", "gross_item_amount")
_ENUM_NEEDS_TABLE = frozenset({"return_status", "document_type", "transaction_type", "payment_method", "supply_type"})
_INR_VALUES = frozenset({"inr", "rs", "rs.", "₹", "rupee", "rupees"})


@dataclass(frozen=True, slots=True)
class MappingLimits:
    """Configuration, supplied by the caller — no defaults in code (CLAUDE.md: thresholds are config)."""

    min_parse_rate: Fraction  # M-TYP: share of non-null values that must parse under the proposed transform
    tax_consistency_rate: Fraction  # M-TAX: share of rows that must satisfy the tax identity to infer inclusion
    tax_tolerance_paise: int  # M-TAX: rounding tolerance in paise
    key_unique_rate: Fraction  # M-GRN: share of rows that must be distinct on the identity key
    mixed_sign_low: Fraction  # M-SGN: negative share above this and below (1 - this) is "mixed"
    max_date_span_years: int  # M-PER
    unit_fraction_share: Fraction  # M-UNT: non-zero-fraction share above this means "rupees"


@dataclass(frozen=True, slots=True)
class Issue:
    rule: str
    message: str


@dataclass(frozen=True, slots=True)
class FieldVerdict:
    index: int
    source_column: str
    errors: tuple[Issue, ...] = ()
    warnings: tuple[Issue, ...] = ()
    confirm_reasons: tuple[str, ...] = ()  # why the seller must confirm; empty => auto-acceptable
    detected_tax_inclusion: str | None = None
    enum_values: tuple[str, ...] = ()  # shown to the seller when a status domain needs confirming
    exact_register_match: bool = False

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.confirm_reasons)

    @property
    def auto_acceptable(self) -> bool:
        return not self.errors and not self.confirm_reasons and self.exact_register_match


@dataclass(frozen=True, slots=True)
class MappingVerdict:
    fields: tuple[FieldVerdict, ...]
    global_issues: tuple[Issue, ...] = ()
    global_warnings: tuple[Issue, ...] = ()
    missing_required: tuple[tuple[str, ...], ...] = ()  # each tuple is an any-of group nothing satisfied

    @property
    def has_errors(self) -> bool:
        return bool(self.global_issues) or any(f.errors for f in self.fields)

    @property
    def auto_acceptable(self) -> bool:
        return not self.has_errors and not self.missing_required and all(f.auto_acceptable for f in self.fields)

    def rules(self) -> frozenset[str]:
        s = {i.rule for i in self.global_issues} | {i.rule for i in self.global_warnings}
        for f in self.fields:
            s |= {i.rule for i in f.errors} | {i.rule for i in f.warnings}
        return frozenset(s)


def _to_paise(raw: str, transform: str) -> int | None:
    d = parse_decimal(raw)
    if d is None:
        return None
    if transform == "RUPEES_TO_PAISE":
        d = d * 100
    if d != d.to_integral_value():
        return None
    return int(d)


def _check_field(
    f: FieldProposal, profile: ColumnProfile | None, report_kind: str, columns: Sequence[str], limits: MappingLimits, as_of: date
) -> FieldVerdict:
    errors: list[Issue] = []
    warns: list[Issue] = []
    confirm: list[str] = []
    spec = V.CANONICAL_FIELDS.get(f.canonical_field)

    # ---- M-VOC ---------------------------------------------------------------------------------
    if spec is None:
        errors.append(Issue("M-VOC", f"'{f.canonical_field}' is not a canonical field (invented names are never accepted)"))
    elif report_kind not in spec.kinds:
        errors.append(Issue("M-VOC", f"'{f.canonical_field}' does not belong to a {report_kind} report"))
    if f.canonical_field == V.COMPONENT_FIELD:
        if f.component_code is None or f.component_code not in V.COMPONENT_CODES:
            errors.append(Issue("M-VOC", f"component_code {f.component_code!r} is not in the component registry"))
    elif f.component_code is not None:
        errors.append(Issue("M-VOC", "component_code is only valid on a component_amount field"))
    if f.transform not in V.TRANSFORMS:
        errors.append(Issue("M-VOC", f"transform {f.transform!r} is not permitted"))
    if f.index >= len(columns) or columns[f.index] != f.source_column:
        errors.append(Issue("M-VOC", f"source column {f.source_column!r} does not match the file's column at position {f.index}"))
    if f.tax_inclusion is not None and f.tax_inclusion not in V.TAX_INCLUSION_VALUES:
        errors.append(Issue("M-VOC", f"tax_inclusion {f.tax_inclusion!r} is not permitted"))
    if f.sign_convention is not None and f.sign_convention not in V.SIGN_CONVENTIONS:
        errors.append(Issue("M-VOC", f"sign_convention {f.sign_convention!r} is not permitted"))

    vt = spec.value_type if spec else "text"
    is_money = vt == "money"
    if spec is not None and f.transform in V.TRANSFORMS:
        if is_money and f.transform not in V.MONEY_TRANSFORMS:
            errors.append(Issue("M-VOC", f"a money field needs a money transform, not {f.transform}"))
        if vt == "date" and f.transform not in V.DATE_TRANSFORMS:
            errors.append(Issue("M-VOC", f"a date field needs a date transform, not {f.transform}"))
        if vt == "percent" and f.transform not in V.PERCENT_TRANSFORMS:
            errors.append(Issue("M-VOC", "a percentage field needs PERCENT or FRACTION_TO_PERCENT"))
        if vt in ("text", "int", "enum") and f.transform != "IDENTITY":
            errors.append(Issue("M-VOC", f"a {vt} field takes the IDENTITY transform"))
    if not is_money and (f.tax_inclusion is not None or f.sign_convention is not None):
        errors.append(Issue("M-VOC", "tax_inclusion and sign_convention apply to money fields only"))

    exact = V.is_exact_register_match(f.source_column, f.canonical_field, f.component_code)
    if not exact:
        confirm.append("the column name is not one a verified report format already uses — please confirm what it holds")

    if profile is None:
        errors.append(Issue("M-TYP", "no profile was measured for this column"))
        return FieldVerdict(f.index, f.source_column, tuple(errors), tuple(warns), tuple(confirm), exact_register_match=exact)

    # ---- M-TYP ---------------------------------------------------------------------------------
    if profile.non_null == 0:
        errors.append(Issue("M-TYP", "the column has no values in the sampled rows"))
    elif spec is not None and not any(e.rule == "M-VOC" for e in errors):
        if vt == "percent" and f.transform == "FRACTION_TO_PERCENT":
            rate, what = profile.fraction_parse_rate, "fractions between 0 and 1 (at most 6 decimals)"
        elif vt == "percent":
            rate, what = profile.percent_parse_rate, "percentages between 0 and 100 (at most 4 decimals)"
        elif is_money:
            rate, what = profile.numeric_parse_rate, "numbers"
        elif vt == "int":
            rate, what = profile.integer_parse_rate, "whole numbers"
        elif vt == "date":
            rate, what = profile.date_parse_rate.get(f.transform, Fraction(0)), f"dates in {f.transform}"
        else:
            rate, what = Fraction(1), ""
        if rate < limits.min_parse_rate:
            errors.append(Issue("M-TYP", f"only {rate.numerator}/{rate.denominator} of values read as {what}; at least {limits.min_parse_rate.numerator}/{limits.min_parse_rate.denominator} is required"))

    if is_money:
        # ---- M-CUR -----------------------------------------------------------------------------
        if profile.foreign_currency_share > 0:
            errors.append(Issue("M-CUR", "values carry a non-INR currency marker; only INR is supported"))
        # ---- M-UNT -----------------------------------------------------------------------------
        if f.transform == "PAISE_IDENTITY" and profile.fractional_share > limits.unit_fraction_share:
            errors.append(Issue("M-UNT", "values have decimals but were declared as paise — this looks like rupees"))
        if f.transform == "RUPEES_TO_PAISE" and profile.max_decimal_places > 2:
            errors.append(Issue("M-UNT", "values have more than two decimal places and cannot convert to whole paise exactly"))
        if f.transform in V.MONEY_TRANSFORMS and profile.fractional_share == 0 and profile.non_null:
            confirm.append("every value is a whole number — please confirm whether the amounts are in rupees or in paise")
        # ---- M-SGN -----------------------------------------------------------------------------
        mixed = limits.mixed_sign_low < profile.negative_share < (1 - limits.mixed_sign_low)
        comp_kind = COMPONENT_KIND_BY_CODE.get(f.component_code or "")
        if mixed:
            if comp_kind in ("FEE", "TAX", "DISCOUNT", "LEVY", "CHARGE") and f.canonical_field == V.COMPONENT_FIELD:
                errors.append(Issue("M-SGN", f"a {comp_kind.lower()} column mixes positive and negative values"))
            elif f.canonical_field in V.MIXED_SIGN_OK:
                warns.append(Issue("M-SGN", "the column mixes positive and negative values (credits/reversals?)"))
            else:
                errors.append(Issue("M-SGN", "the column mixes positive and negative values"))
        if f.sign_convention is None:
            confirm.append("the sign convention (are deductions negative?) was not stated — please confirm")
        elif profile.negative_share >= 1 - limits.mixed_sign_low and f.sign_convention == "AS_IS" and f.canonical_field == V.COMPONENT_FIELD:
            confirm.append("every value is negative — please confirm these are deductions stored as negatives")

    if vt == "percent" and not any(e.rule == "M-VOC" for e in errors) and profile.non_null:
        # ---- M-PCT: the unit of a rate is never guessed (decision R2, 2026-10-21) ------------------------------------------
        ambiguous = percent_unit_is_ambiguous(max_value=profile.percent_max, has_percent_sign=profile.percent_has_sign)
        if f.transform == "PERCENT" and ambiguous:
            confirm.append("every value is 1 or less, so these could be percentage points (0.18 means 0.18%) or fractions (0.18 means 18%); "
                           "Metrion will not guess - please choose the unit explicitly")
        if f.transform == "FRACTION_TO_PERCENT":
            if profile.percent_has_sign or (profile.percent_max is not None and profile.percent_max > 1):
                errors.append(Issue("M-PCT", "some values are above 1 or carry a % sign, so they are percentages, not fractions of 1"))
            confirm.append("you chose to read these values as fractions of 1 (0.18 becomes 18%) - please confirm")

    if vt == "date":
        # ---- M-DTE (ambiguity) and M-PER ---------------------------------------------------------
        if f.transform == "DATE_DMY" and profile.date_mdy_certain:
            errors.append(Issue("M-DTE", "some values can only be month-first (MM/DD) but the proposal says day-first"))
        if f.transform == "DATE_MDY" and profile.date_dmy_certain:
            errors.append(Issue("M-DTE", "some values can only be day-first (DD/MM) but the proposal says month-first"))
        if profile.date_dmy_certain and profile.date_mdy_certain:
            errors.append(Issue("M-DTE", "the column mixes day-first and month-first dates"))
        if f.transform in ("DATE_DMY", "DATE_MDY") and not (profile.date_dmy_certain or profile.date_mdy_certain):
            confirm.append("the date order (DD/MM vs MM/DD) cannot be told from the values — please confirm")
        if profile.date_max is not None and profile.date_max > as_of:
            warns.append(Issue("M-PER", f"dates run past the as-of date ({profile.date_max.isoformat()})"))
        if profile.date_min is not None and profile.date_max is not None:
            span_years = (profile.date_max - profile.date_min).days // 365
            if span_years > limits.max_date_span_years:
                warns.append(Issue("M-PER", f"dates span {span_years} years, which is unusual for one report"))

    if f.canonical_field == "currency" and profile.enum_values:
        bad = [v for v in profile.enum_values if v.strip().lower() not in _INR_VALUES]
        if bad:
            errors.append(Issue("M-CUR", f"currency column contains non-INR values {bad[:3]}"))

    # ---- M-STA (status domains are always the seller's table) --------------------------------------
    enum_values: tuple[str, ...] = ()
    if f.canonical_field in _ENUM_NEEDS_TABLE:
        enum_values = profile.enum_values
        confirm.append("please confirm what each status value means (a status table is never inferred)")

    return FieldVerdict(
        index=f.index, source_column=f.source_column, errors=tuple(errors), warnings=tuple(warns),
        confirm_reasons=tuple(confirm), enum_values=enum_values, exact_register_match=exact,
    )


def _detect_tax_inclusion(
    proposal: MappingProposal, rows: Sequence[Sequence[str]], limits: MappingLimits
) -> dict[int, str]:
    """M-TAX: for each gross-like column, test the identities against the file's own tax columns.
    Returns column index -> INCLUSIVE | EXCLUSIVE | UNKNOWN. UNKNOWN when it cannot be measured."""
    by_field: dict[str, FieldProposal] = {f.canonical_field: f for f in proposal.fields if f.canonical_field != V.COMPONENT_FIELD}
    taxable = by_field.get("taxable_amount")
    tax_cols = [f for f in proposal.fields if f.canonical_field == V.COMPONENT_FIELD and f.component_code in _TAX_CODES]
    result: dict[int, str] = {}
    for name in _GROSS_LIKE:
        g = by_field.get(name)
        if g is None:
            continue
        if taxable is None or not tax_cols:
            result[g.index] = "UNKNOWN"
            continue
        incl = excl = total = 0
        for r in rows:
            gv = _to_paise(r[g.index], g.transform) if g.index < len(r) else None
            tv = _to_paise(r[taxable.index], taxable.transform) if taxable.index < len(r) else None
            tax_parts = [_to_paise(r[t.index], t.transform) if t.index < len(r) else None for t in tax_cols]
            if gv is None or tv is None or any(p is None for p in tax_parts):
                continue
            total += 1
            tax_sum = sum(p for p in tax_parts if p is not None)
            if abs(tv + tax_sum - gv) <= limits.tax_tolerance_paise:
                incl += 1
            if abs(tv - gv) <= limits.tax_tolerance_paise:
                excl += 1
        if total == 0:
            result[g.index] = "UNKNOWN"
        elif Fraction(incl, total) >= limits.tax_consistency_rate and incl >= excl:
            result[g.index] = "INCLUSIVE"
        elif Fraction(excl, total) >= limits.tax_consistency_rate:
            result[g.index] = "EXCLUSIVE"
        else:
            result[g.index] = "UNKNOWN"
    return result


def validate_mapping(
    proposal: MappingProposal,
    *,
    report_kind: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    profiles: Sequence[ColumnProfile],
    limits: MappingLimits,
    as_of: date,
) -> MappingVerdict:
    by_index = {p.index: p for p in profiles}
    verdicts: list[FieldVerdict] = []
    g_issues: list[Issue] = []
    g_warns: list[Issue] = []

    if report_kind not in V.REPORT_KINDS:
        return MappingVerdict(fields=(), global_issues=(Issue("M-VOC", f"unknown report kind {report_kind!r}"),))

    # ---- M-ONE ----------------------------------------------------------------------------------
    seen_idx: set[int] = set()
    seen_target: dict[tuple[str, str | None], int] = {}
    for f in proposal.fields:
        if f.index in seen_idx:
            g_issues.append(Issue("M-ONE", f"column position {f.index} is mapped more than once"))
        seen_idx.add(f.index)
        key = (f.canonical_field, f.component_code if f.canonical_field == V.COMPONENT_FIELD else None)
        if key in seen_target:
            what = f"{f.canonical_field}/{f.component_code}" if f.component_code else f.canonical_field
            g_issues.append(Issue("M-ONE", f"two columns map to the same target {what}"))
        seen_target[key] = f.index

    detected = _detect_tax_inclusion(proposal, rows, limits)

    for f in proposal.fields:
        v = _check_field(f, by_index.get(f.index), report_kind, columns, limits, as_of)
        spec = V.CANONICAL_FIELDS.get(f.canonical_field)
        errors, confirm = list(v.errors), list(v.confirm_reasons)
        det = detected.get(f.index)
        if spec is not None and spec.value_type == "money" and f.canonical_field in ("taxable_amount", *_GROSS_LIKE):
            declared = f.tax_inclusion
            if f.canonical_field == "taxable_amount":
                pass  # exclusive by definition
            elif det in ("INCLUSIVE", "EXCLUSIVE"):
                if declared in ("INCLUSIVE", "EXCLUSIVE") and declared != det:
                    errors.append(Issue("M-TAX", f"proposal says {declared.lower()} but the file's own tax columns show the amount is {det.lower()}"))
                elif declared not in ("INCLUSIVE", "EXCLUSIVE"):
                    confirm.append(f"measured as tax-{det.lower()}; please confirm")
            else:
                confirm.append("tax inclusion cannot be measured from this file — please confirm whether the amount includes GST")
        elif spec is not None and spec.value_type == "money" and f.canonical_field == V.COMPONENT_FIELD and f.component_code in _TAX_CODES:
            pass
        verdicts.append(FieldVerdict(
            index=v.index, source_column=v.source_column, errors=tuple(errors), warnings=v.warnings,
            confirm_reasons=tuple(dict.fromkeys(confirm)), detected_tax_inclusion=det, enum_values=v.enum_values,
            exact_register_match=v.exact_register_match,
        ))

    # ---- M-GRN (sales: one row per order line) --------------------------------------------------
    if report_kind == "SALES":
        key_cols = [f.index for f in proposal.fields if V.CANONICAL_FIELDS.get(f.canonical_field) and V.CANONICAL_FIELDS[f.canonical_field].is_key]
        if not key_cols:
            g_issues.append(Issue("M-GRN", "no identity column (order/line/invoice reference) is mapped, so the row grain cannot be established"))
        elif rows:
            keys = [tuple((r[i] if i < len(r) else "") for i in key_cols) for r in rows]
            share = Fraction(len(set(keys)), len(keys))
            if share < limits.key_unique_rate:
                g_issues.append(Issue("M-GRN", f"rows are not unique on their identity columns ({len(set(keys))} distinct of {len(keys)}); this may be an order-level or aggregated report, not one row per order line"))

    # ---- M-REQ ------------------------------------------------------------------------------------
    mapped = {f.canonical_field for f in proposal.fields}
    missing = tuple(grp for grp in V.REQUIRED_GROUPS.get(report_kind, ()) if not any(m in mapped for m in grp))

    # Columns the proposal neither mapped nor explicitly set aside are surfaced, never silently dropped.
    addressed = {f.index for f in proposal.fields} | {i for i, c in enumerate(columns) if c in set(proposal.unmapped_columns)}
    for i, c in enumerate(columns):
        if i not in addressed:
            g_warns.append(Issue("M-VOC", f"column {c!r} was neither mapped nor set aside"))

    return MappingVerdict(
        fields=tuple(verdicts), global_issues=tuple(g_issues), global_warnings=tuple(g_warns), missing_required=missing
    )
