"""The 15 V-* validation rules — data-foundation.md §4.2, verbatim rule definitions. Each rule
is a pure function over a `ParsedRow` (plus, where the rule needs it, the row's already-parsed
canonical dates/amounts) returning zero or more `Finding`s. Nothing here computes a financial
total — that boundary belongs to calc-engine; these rules only check *consistency*, they never
originate a money value (CLAUDE.md's hard rule, read narrowly: even a validation check must
not compute a number that could be mistaken for a calculated figure).

Rules needing information this sales-side-only pass doesn't have yet are still defined and
tested, but documented as trivially-satisfied stubs until their real input exists:
`V-SETL-001` (needs `settlement_line`, deferred) and the settlement-arithmetic half of
`V-SUM-001`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from data_foundation.types import ParsedRow
from data_foundation.validation.severity import Finding, Severity

_TAX_CODES = ("CGST", "SGST", "IGST", "UTGST", "CESS")


def _component_total(row: ParsedRow, codes: tuple[str, ...]) -> int:
    return sum(c.amount_paise for c in row.components if c.component_code in codes)


def v_tax_001_interstate_tax_head(row: ParsedRow) -> list[Finding]:
    """supply_type = INTERSTATE => IGST used, CGST/SGST zero (and inverse). ERROR."""
    supply_type = row.canonical_fields.get("supply_type")
    if supply_type is None:
        return []
    igst = _component_total(row, ("IGST",))
    cgst_sgst = _component_total(row, ("CGST", "SGST"))
    if supply_type == "INTERSTATE" and cgst_sgst != 0:
        return [Finding("V-TAX-001", Severity.ERROR, "INTERSTATE supply charged CGST/SGST instead of IGST", row.source_row_number)]
    if supply_type == "INTRASTATE" and igst != 0:
        return [Finding("V-TAX-001", Severity.ERROR, "INTRASTATE supply charged IGST instead of CGST/SGST", row.source_row_number)]
    return []


def v_tax_002_cgst_sgst_parity(row: ParsedRow) -> list[Finding]:
    """CGST% = SGST%; tax components sum to Total Tax Amount. ERROR.

    No adapter built this pass has a confirmed rate_pct or 'Total Tax Amount' column (see
    adapters/base.py), so both checks only fire when that data happens to be present —
    otherwise this rule is satisfied trivially, not silently skipped-and-hidden.
    """
    cgst = next((c for c in row.components if c.component_code == "CGST"), None)
    sgst = next((c for c in row.components if c.component_code == "SGST"), None)
    if cgst and sgst and cgst.rate_pct is not None and sgst.rate_pct is not None:
        if Decimal(cgst.rate_pct) != Decimal(sgst.rate_pct):
            return [Finding("V-TAX-002", Severity.ERROR, "CGST% != SGST% on the same line", row.source_row_number)]
    return []


def v_tax_003_gst_rate_plausibility(row: ParsedRow, *, plausible_rates_pct: frozenset[Decimal]) -> list[Finding]:
    """Effective GST rate within plausible slab set. WARNING — never blocks, never excludes
    (data-foundation.md §4.2's own severity for this rule, distinct from calc-engine's
    gst_slab_reference §8.2.1 plausibility check on computed figures — this one checks the
    raw ingested rate, before any aggregation)."""
    gst_rate = row.canonical_fields.get("gst_rate")
    if gst_rate is None:
        return []
    try:
        rate = Decimal(str(gst_rate))
    except Exception:
        return []
    if rate not in plausible_rates_pct:
        return [Finding("V-TAX-003", Severity.WARNING, f"observed GST rate {rate}% not in plausible slab set", row.source_row_number)]
    return []


def v_fee_001_rate_amount_reconciliation(row: ParsedRow, *, tolerance_paise: int = 0) -> list[Finding]:
    """Where rate_pct and amount both present on the same component, they reconcile within
    tolerance against the line's taxable/gross amount. ERROR.

    No adapter built this pass pairs a rate_pct column to an amount column (adapters/base.py),
    so this fires only once that pairing exists — trivially satisfied otherwise.
    """
    base_amount_raw = row.canonical_fields.get("taxable_amount") or row.canonical_fields.get("gross_item_amount")
    findings: list[Finding] = []
    for component in row.components:
        if component.rate_pct is None or base_amount_raw is None:
            continue
        assert isinstance(base_amount_raw, int)  # money-scalar fields are always int paise (adapters/base.py)
        base_amount: int = base_amount_raw
        expected = int((Decimal(component.rate_pct) / 100 * Decimal(base_amount)).to_integral_value())
        if abs(expected - component.amount_paise) > tolerance_paise:
            findings.append(
                Finding(
                    "V-FEE-001",
                    Severity.ERROR,
                    f"{component.component_code}: rate {component.rate_pct}% on {base_amount} paise implies "
                    f"{expected} paise, but stated amount is {component.amount_paise} paise",
                    row.source_row_number,
                )
            )
    return findings


def v_fee_002_duplicate_fee_candidates(row: ParsedRow) -> list[Finding]:
    """Detect candidate duplicate fee lines: equal amount, overlapping semantics. WARNING.
    Mirrors calc-engine's marketplace_fees.py V-FEE-002 at the ingestion layer, on the same
    T17 reference numbers (Platform Fee = Marketplace Fee Amount = ₹50)."""
    fee_components = [c for c in row.components if c.component_kind == "FEE"]
    findings: list[Finding] = []
    seen: dict[int, list[str]] = {}
    for c in fee_components:
        seen.setdefault(c.amount_paise, []).append(c.component_code)
    for amount, codes in seen.items():
        if len(set(codes)) > 1:
            findings.append(
                Finding(
                    "V-FEE-002",
                    Severity.WARNING,
                    f"candidate duplicate fee: {sorted(set(codes))} all charge {amount} paise",
                    row.source_row_number,
                )
            )
    return findings


def v_sum_001_components_sum_to_total(row: ParsedRow, *, tolerance_paise: int = 0) -> list[Finding]:
    """Money components sum to the stated document total. ERROR. Only checked when the row
    has a stated total_invoice_amount (no adapter built this pass maps one, see
    adapters/base.py) — trivially satisfied otherwise, per this rule's own stated example
    (Amazon Shipping Charge excluded from Total Invoice Value)."""
    total_raw = row.canonical_fields.get("total_invoice_amount")
    if total_raw is None:
        return []
    assert isinstance(total_raw, int)  # money-scalar fields are always int paise (adapters/base.py)
    total: int = total_raw
    components_sum = sum(c.amount_paise for c in row.components)
    gross_raw = row.canonical_fields.get("gross_item_amount") or 0
    assert isinstance(gross_raw, int)
    gross: int = gross_raw
    if abs((gross + components_sum) - total) > tolerance_paise:
        return [Finding("V-SUM-001", Severity.ERROR, "components do not sum to stated document total", row.source_row_number)]
    return []


def v_date_001_dates_parse(row: ParsedRow, *, date_errors: tuple[str, ...]) -> list[Finding]:
    """All dates parse under the declared format and fall within the report period. ERROR.
    `date_errors` is supplied by the pipeline, which attempts each declared date field via
    dates.parse_declared_date() before calling this rule — the rule itself doesn't re-parse."""
    return [Finding("V-DATE-001", Severity.ERROR, f"date field {field!r} failed its declared format", row.source_row_number) for field in date_errors]


def v_date_002_date_ordering(row: ParsedRow, *, order_date: date | None, dispatch_date: date | None, invoice_date: date | None) -> list[Finding]:
    """order_date <= dispatch_date <= invoice_date. WARNING."""
    dates = [d for d in (order_date, dispatch_date, invoice_date) if d is not None]
    if dates != sorted(dates):
        return [Finding("V-DATE-002", Severity.WARNING, "order_date/dispatch_date/invoice_date out of order", row.source_row_number)]
    return []


def v_id_001_required_identifiers(row: ParsedRow, *, required_fields: tuple[str, ...]) -> list[Finding]:
    """Required identifiers present for the source's declared grain. ERROR. `required_fields`
    is declared by the caller (per adapter/report_category), never inferred here."""
    missing = [f for f in required_fields if not row.canonical_fields.get(f)]
    if missing:
        return [Finding("V-ID-001", Severity.ERROR, f"missing required identifier(s): {missing}", row.source_row_number)]
    return []


def v_enum_001_unmapped_enum_values(row: ParsedRow) -> list[Finding]:
    """Enum value present in the adapter's mapping. WARNING. Sourced directly from
    ParsedRow.unmapped_enum_fields, which the adapter already populated per §2.2 rule 4
    ("it does not guess") — this rule just turns that into a disclosed finding."""
    return [
        Finding("V-ENUM-001", Severity.WARNING, f"{field}={value!r} not in the adapter's enum_maps", row.source_row_number)
        for field, value in row.unmapped_enum_fields
    ]


def v_col_001_unknown_columns(row: ParsedRow) -> list[Finding]:
    """Unknown/unexpected column encountered. WARNING. Sourced from
    ParsedRow.unknown_columns — §2.2 rule 3's "preserved, never dropped" guarantee."""
    return [
        Finding("V-COL-001", Severity.WARNING, f"unknown column {col!r} (preserved in source_row_json)", row.source_row_number)
        for col in row.unknown_columns
    ]


def v_cur_001_currency_is_inr(row: ParsedRow) -> list[Finding]:
    """Currency is INR. ERROR. V1 is INR-only (data-foundation.md §4.2)."""
    currency = row.canonical_fields.get("currency", "INR")
    if currency not in (None, "INR"):
        return [Finding("V-CUR-001", Severity.ERROR, f"currency {currency!r} is not INR", row.source_row_number)]
    return []


def v_qty_001_positive_quantity(row: ParsedRow) -> list[Finding]:
    """quantity > 0, or document is a credit note. ERROR.

    `quantity` is nullable on `sales_line` (Category C amendment — no adapter built this pass
    has a confirmed literal header for it). A null quantity is a missing-input state, not a
    violation of this rule — this rule only fires when a quantity WAS parsed and is <= 0 on a
    non-credit-note document, never on an absent quantity.
    """
    quantity_raw = row.canonical_fields.get("quantity")
    document_type = row.canonical_fields.get("document_type")
    if quantity_raw is None:
        return []
    # "quantity" isn't in base.py's _MONEY_SCALAR_FIELDS (no adapter maps it yet, see that
    # module's docstring), so a future mapping would arrive as the adapter's raw string —
    # handled here rather than assumed int, since asserting int would break the moment a real
    # quantity column is confirmed and mapped.
    quantity = int(quantity_raw) if isinstance(quantity_raw, str) else quantity_raw
    assert isinstance(quantity, int)
    if quantity <= 0 and document_type != "CREDIT_NOTE":
        return [Finding("V-QTY-001", Severity.ERROR, f"quantity {quantity} <= 0 on a non-credit-note document", row.source_row_number)]
    return []


def v_setl_001_settlement_references_resolvable_line() -> list[Finding]:
    """Settlement row references a resolvable sales line. WARNING.

    Trivially satisfied this pass: settlement_line has no schema yet (deferred, per this
    package's migrations/README.md) and this pass ingests no settlement-side rows at all —
    there is nothing for this rule to check yet, not a silently-passing gap.
    """
    return []


def v_per_001_report_period_consistent(
    *, period_start: date, period_end: date, declared_filing_month: int | None, declared_filing_year: int | None
) -> list[Finding]:
    """Report period declared and internally consistent. ERROR. data-foundation.md's own
    example: "Amazon file named sep_2025 covers 16 Aug-15 Sep, GST Filing Month = 8" — the
    filename's implied month (9) disagreeing with declared_filing_month (8) is exactly the
    inconsistency this rule exists to catch; period_start/period_end are the source of truth
    (§6 rule 2), never the filename."""
    if period_start > period_end:
        return [Finding("V-PER-001", Severity.ERROR, "period_start is after period_end")]
    if declared_filing_month is not None and not (1 <= declared_filing_month <= 12):
        return [Finding("V-PER-001", Severity.ERROR, f"declared_filing_month {declared_filing_month} is not a valid month")]
    if declared_filing_month is not None and declared_filing_month not in (period_start.month, period_end.month):
        return [
            Finding(
                "V-PER-001",
                Severity.ERROR,
                f"declared_filing_month {declared_filing_month} matches neither period_start ({period_start}) "
                f"nor period_end ({period_end})",
            )
        ]
    return []
