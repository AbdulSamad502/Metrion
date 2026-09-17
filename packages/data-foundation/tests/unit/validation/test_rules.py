"""One test per V-* rule (§4.2), each using the spec's own quoted "observed in reference
data" example wherever one is given. No invented Amazon/Flipkart/Meesho values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from data_foundation.types import ComponentValue, ParsedRow
from data_foundation.validation.rules import (
    v_col_001_unknown_columns,
    v_cur_001_currency_is_inr,
    v_date_002_date_ordering,
    v_enum_001_unmapped_enum_values,
    v_fee_001_rate_amount_reconciliation,
    v_fee_002_duplicate_fee_candidates,
    v_id_001_required_identifiers,
    v_per_001_report_period_consistent,
    v_qty_001_positive_quantity,
    v_setl_001_settlement_references_resolvable_line,
    v_sum_001_components_sum_to_total,
    v_tax_001_interstate_tax_head,
    v_tax_002_cgst_sgst_parity,
    v_tax_003_gst_rate_plausibility,
)
from data_foundation.validation.severity import Severity


def _row(canonical_fields=None, components=(), unknown_columns=(), unmapped_enum_fields=()) -> ParsedRow:
    return ParsedRow(
        source_row_number=1,
        source_row_json={},
        canonical_fields=canonical_fields or {},
        components=components,
        unknown_columns=unknown_columns,
        unmapped_enum_fields=unmapped_enum_fields,
    )


def test_v_tax_001_interstate_charging_cgst_sgst_is_error():
    # spec: "6 of 40 Amazon rows marked Interstate while charging CGST+SGST"
    row = _row(
        canonical_fields={"supply_type": "INTERSTATE"},
        components=(
            ComponentValue("TAX", "CGST", "INVOICE", 900, None, None, "CGST Amount", False, None),
            ComponentValue("TAX", "SGST", "INVOICE", 900, None, None, "SGST Amount", False, None),
        ),
    )
    findings = v_tax_001_interstate_tax_head(row)
    assert len(findings) == 1 and findings[0].severity == Severity.ERROR


def test_v_tax_001_intrastate_charging_igst_is_error():
    row = _row(
        canonical_fields={"supply_type": "INTRASTATE"},
        components=(ComponentValue("TAX", "IGST", "INVOICE", 900, None, None, "IGST Amount", False, None),),
    )
    assert len(v_tax_001_interstate_tax_head(row)) == 1


def test_v_tax_001_consistent_case_passes():
    row = _row(
        canonical_fields={"supply_type": "INTERSTATE"},
        components=(ComponentValue("TAX", "IGST", "INVOICE", 900, None, None, "IGST Amount", False, None),),
    )
    assert v_tax_001_interstate_tax_head(row) == []


def test_v_tax_002_cgst_sgst_rate_mismatch_is_error():
    row = _row(
        components=(
            ComponentValue("TAX", "CGST", "INVOICE", 900, None, "9", "CGST Amount", False, None),
            ComponentValue("TAX", "SGST", "INVOICE", 800, None, "8", "SGST Amount", False, None),
        )
    )
    assert len(v_tax_002_cgst_sgst_parity(row)) == 1


def test_v_tax_003_amazon_row1_9_percent_on_hsn_8517():
    # spec: "Amazon row 1: 9% total on HSN 8517"
    row = _row(canonical_fields={"gst_rate": "9"})
    findings = v_tax_003_gst_rate_plausibility(row, plausible_rates_pct=frozenset({Decimal("18"), Decimal("5")}))
    assert len(findings) == 1 and findings[0].severity == Severity.WARNING  # never ERROR


def test_v_tax_003_matched_rate_no_warning():
    row = _row(canonical_fields={"gst_rate": "18"})
    assert v_tax_003_gst_rate_plausibility(row, plausible_rates_pct=frozenset({Decimal("18")})) == []


def test_v_fee_001_amazon_row1_rate_amount_mismatch():
    # spec: "Amazon row 1: Marketplace Fee % = 10, Amount = ₹50 on a ₹37,206 item"
    row = _row(
        canonical_fields={"taxable_amount": 3_720_600},  # ₹37,206
        components=(ComponentValue("FEE", "MARKETPLACE_FEE_GENERIC", "INVOICE", 5_000, None, "10", "Marketplace Fee Amount", False, None),),
    )
    findings = v_fee_001_rate_amount_reconciliation(row)
    assert len(findings) == 1 and findings[0].severity == Severity.ERROR


def test_v_fee_002_amazon_row1_platform_fee_equals_marketplace_fee():
    # spec: "Amazon row 1: Platform Fee = Marketplace Fee Amount = ₹50. Double-count risk."
    row = _row(
        components=(
            ComponentValue("FEE", "PLATFORM_FEE", "INVOICE", 5_000, None, None, "Platform Fee", False, None),
            ComponentValue("FEE", "MARKETPLACE_FEE_GENERIC", "INVOICE", 5_000, None, None, "Marketplace Fee Amount", False, None),
        )
    )
    findings = v_fee_002_duplicate_fee_candidates(row)
    assert len(findings) == 1 and findings[0].severity == Severity.WARNING


def test_v_fee_002_distinct_amounts_not_flagged():
    row = _row(
        components=(
            ComponentValue("FEE", "PLATFORM_FEE", "INVOICE", 5_000, None, None, "Platform Fee", False, None),
            ComponentValue("FEE", "MARKETPLACE_FEE_GENERIC", "INVOICE", 7_000, None, None, "Marketplace Fee Amount", False, None),
        )
    )
    assert v_fee_002_duplicate_fee_candidates(row) == []


def test_v_sum_001_amazon_shipping_charge_excluded_from_total():
    # spec: "Amazon Shipping Charge ₹50 excluded from Total Invoice Value"
    row = _row(
        canonical_fields={"gross_item_amount": 100_000, "total_invoice_amount": 100_000},
        components=(ComponentValue("CHARGE", "SHIPPING_CHARGE", "INVOICE", 5_000, None, None, "Shipping Charge", False, None),),
    )
    assert len(v_sum_001_components_sum_to_total(row)) == 1


def test_v_sum_001_reconciled_case_passes():
    row = _row(
        canonical_fields={"gross_item_amount": 100_000, "total_invoice_amount": 105_000},
        components=(ComponentValue("CHARGE", "SHIPPING_CHARGE", "INVOICE", 5_000, None, None, "Shipping Charge", False, None),),
    )
    assert v_sum_001_components_sum_to_total(row) == []


def test_v_date_002_out_of_order_is_warning():
    findings = v_date_002_date_ordering(_row(), order_date=date(2026, 9, 10), dispatch_date=date(2026, 9, 5), invoice_date=None)
    assert len(findings) == 1 and findings[0].severity == Severity.WARNING


def test_v_date_002_in_order_passes():
    findings = v_date_002_date_ordering(_row(), order_date=date(2026, 9, 1), dispatch_date=date(2026, 9, 2), invoice_date=date(2026, 9, 3))
    assert findings == []


def test_v_id_001_missing_required_identifier():
    row = _row(canonical_fields={"order_ref": None})
    assert len(v_id_001_required_identifiers(row, required_fields=("order_ref",))) == 1


def test_v_id_001_present_passes():
    row = _row(canonical_fields={"order_ref": "OD123"})
    assert v_id_001_required_identifiers(row, required_fields=("order_ref",)) == []


def test_v_enum_001_meesho_return_status_delivered():
    # spec: "Meesho Return Status contains Delivered; Amazon uses Not Returned/Returned"
    row = _row(unmapped_enum_fields=(("return_status", "Delivered"),))
    findings = v_enum_001_unmapped_enum_values(row)
    assert len(findings) == 1 and findings[0].severity == Severity.WARNING


def test_v_col_001_meesho_sss_column():
    # spec: "Meesho column 28 is literally named sss"
    row = _row(unknown_columns=("sss",))
    findings = v_col_001_unknown_columns(row)
    assert len(findings) == 1 and findings[0].severity == Severity.WARNING


def test_v_cur_001_non_inr_is_error():
    row = _row(canonical_fields={"currency": "USD"})
    assert len(v_cur_001_currency_is_inr(row)) == 1


def test_v_cur_001_inr_passes():
    row = _row(canonical_fields={"currency": "INR"})
    assert v_cur_001_currency_is_inr(row) == []


def test_v_cur_001_missing_currency_defaults_to_inr_no_error():
    row = _row(canonical_fields={})
    assert v_cur_001_currency_is_inr(row) == []


def test_v_qty_001_zero_quantity_non_credit_note_is_error():
    row = _row(canonical_fields={"quantity": 0, "document_type": "INVOICE"})
    assert len(v_qty_001_positive_quantity(row)) == 1


def test_v_qty_001_zero_quantity_credit_note_passes():
    row = _row(canonical_fields={"quantity": 0, "document_type": "CREDIT_NOTE"})
    assert v_qty_001_positive_quantity(row) == []


def test_v_qty_001_null_quantity_never_flagged():
    # quantity is nullable (Category C amendment) — absent is a missing input, not a violation
    row = _row(canonical_fields={"quantity": None, "document_type": "INVOICE"})
    assert v_qty_001_positive_quantity(row) == []


def test_v_setl_001_trivially_satisfied_this_pass():
    assert v_setl_001_settlement_references_resolvable_line() == []


def test_v_per_001_amazon_sep_2025_file_is_consistent():
    # spec's own example: "Amazon file named sep_2025 covers 16 Aug-15 Sep, GST Filing Month = 8"
    # — the point of this example is that the FILENAME ("sep") is misleading, not that the
    # declared fields are inconsistent; declared_filing_month=8 matches period_start's month.
    findings = v_per_001_report_period_consistent(
        period_start=date(2025, 8, 16), period_end=date(2025, 9, 15), declared_filing_month=8, declared_filing_year=2025
    )
    assert findings == []


def test_v_per_001_genuinely_inconsistent_filing_month_is_error():
    findings = v_per_001_report_period_consistent(
        period_start=date(2025, 8, 16), period_end=date(2025, 9, 15), declared_filing_month=5, declared_filing_year=2025
    )
    assert len(findings) == 1 and findings[0].severity == Severity.ERROR


def test_v_per_001_period_start_after_end_is_error():
    findings = v_per_001_report_period_consistent(
        period_start=date(2025, 9, 15), period_end=date(2025, 8, 16), declared_filing_month=None, declared_filing_year=None
    )
    assert len(findings) == 1
