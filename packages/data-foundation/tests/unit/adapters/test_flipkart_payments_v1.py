"""flipkart.payments.v1 — mirrors test_meesho_payments_v1.py's structure/rigor. Every assertion
here exercises `is_verified=False` bindings built entirely from data-foundation.md §5.1.3's
secondary-sourced research; nothing here claims real-export validation.

**Duplicate-header assumption.** Unlike meesho.payments.v1's real, verified "Fixed Fee
(Incl. GST)" duplicate, none of §5.1.3's sources (ReconPe, gonukkad.com) mention any duplicate
or repeated header on the real Flipkart settlement file — the dense-header quote and the
fee-line prose are both given as a plain, non-repeating list. This adapter's column_map
therefore uses only bare-string keys (§2.1.3's occurrence-0-only lookup), and every test below
uses plain-dict RawFile rows, consistent with that assumption. This is stated explicitly, not
silently assumed, per this pass's own instructions."""

from __future__ import annotations

from data_foundation.adapters.flipkart_payments_v1 import adapter as flipkart_payments_adapter
from data_foundation.types import FileSample, RawFile


def test_detect_matched_when_all_confirmed_columns_present():
    sample = FileSample(
        columns=(
            "Order ID",
            "Bank Settlement Value",
            "Payment Date",
            "Commission Fee",
            "Fixed Fee",
            "Collection Fee",
            "Shipping Fee",
            "Non-Order Charges",
        )
    )
    result = flipkart_payments_adapter.detect(sample)
    assert result.matched is True
    assert result.missing_columns == ()


def test_detect_reports_missing_columns_diff():
    sample = FileSample(columns=("Order ID",))
    result = flipkart_payments_adapter.detect(sample)
    assert result.matched is False
    assert set(result.missing_columns) == {
        "Bank Settlement Value",
        "Payment Date",
        "Commission Fee",
        "Fixed Fee",
        "Collection Fee",
        "Shipping Fee",
        "Non-Order Charges",
    }


def test_source_side_is_settlement():
    assert flipkart_payments_adapter.source_side == "SETTLEMENT"


def test_parse_order_id_maps_to_order_ref():
    raw = RawFile(columns=("Order ID",), rows=[{"Order ID": "OD1234567890"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert row.canonical_fields["order_ref"] == "OD1234567890"


def test_parse_bank_settlement_value_converts_to_gross_settlement_amount_paise():
    raw = RawFile(columns=("Bank Settlement Value",), rows=[{"Bank Settlement Value": "845.50"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert row.canonical_fields["gross_settlement_amount"] == 84_550
    assert row.components == ()  # scalar field, never a line_component


def test_parse_negative_bank_settlement_value():
    raw = RawFile(columns=("Bank Settlement Value",), rows=[{"Bank Settlement Value": "-120.00"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert row.canonical_fields["gross_settlement_amount"] == -12_000


def test_parse_payment_date_maps_to_settlement_date_canonical_field():
    raw = RawFile(columns=("Payment Date",), rows=[{"Payment Date": "26-08-2025"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    # parse() is shape-only (§2.2 rule 2) — the declared date_formats value is metadata for a
    # later parsing step, not applied inside parse() itself, matching every other adapter's
    # existing behavior (meesho.tcs_sales_return.v1's cancel_return_date is handled the same way).
    assert row.canonical_fields["settlement_date"] == "26-08-2025"
    assert flipkart_payments_adapter.date_formats["settlement_date"] == "%d-%m-%Y"


def test_parse_commission_fee_maps_to_commission_component():
    raw = RawFile(columns=("Commission Fee",), rows=[{"Commission Fee": "45.00"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert len(row.components) == 1
    component = row.components[0]
    assert component.component_code == "COMMISSION"
    assert component.component_kind == "FEE"
    assert component.source_side == "SETTLEMENT"
    assert component.amount_paise == 4_500
    assert component.is_verified is False


def test_parse_fixed_fee_maps_to_fixed_fee_component():
    raw = RawFile(columns=("Fixed Fee",), rows=[{"Fixed Fee": "20.00"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert row.components[0].component_code == "FIXED_FEE"
    assert row.components[0].component_kind == "FEE"
    assert row.components[0].amount_paise == 2_000


def test_parse_collection_fee_maps_to_collection_fee_component():
    raw = RawFile(columns=("Collection Fee",), rows=[{"Collection Fee": "10.50"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert row.components[0].component_code == "COLLECTION_FEE"
    assert row.components[0].component_kind == "FEE"
    assert row.components[0].amount_paise == 1_050


def test_parse_shipping_fee_maps_to_shipping_charge_component():
    raw = RawFile(columns=("Shipping Fee",), rows=[{"Shipping Fee": "60.00"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert row.components[0].component_code == "SHIPPING_CHARGE"
    assert row.components[0].component_kind == "CHARGE"
    assert row.components[0].amount_paise == 6_000


def test_parse_non_order_charges_maps_to_non_order_fee_component():
    raw = RawFile(columns=("Non-Order Charges",), rows=[{"Non-Order Charges": "99.99"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert row.components[0].component_code == "NON_ORDER_FEE"
    assert row.components[0].component_kind == "FEE"
    assert row.components[0].amount_paise == 9_999


def test_line_item_id_and_settlement_id_and_neft_columns_are_unknown():
    """None of these are bound (see the adapter's module docstring): Line Item ID and
    Settlement ID because no source names a confirmed header/join role for them beyond
    Order ID, NEFT ID / Neft Type because settlement_line has no field for a bank reference."""
    raw = RawFile(
        columns=("Order ID", "Line Item ID", "Settlement ID", "NEFT ID", "Neft Type"),
        rows=[
            {
                "Order ID": "OD1",
                "Line Item ID": "LI1",
                "Settlement ID": "ST1",
                "NEFT ID": "N123",
                "Neft Type": "NEFT",
            }
        ],
    )
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert set(row.unknown_columns) == {"Line Item ID", "Settlement ID", "NEFT ID", "Neft Type"}
    assert row.canonical_fields["order_ref"] == "OD1"


def test_parse_unknown_column_preserved_and_flagged():
    raw = RawFile(columns=("Order ID", "Mystery Column"), rows=[{"Order ID": "OD1", "Mystery Column": "??"}])
    row = list(flipkart_payments_adapter.parse(raw))[0]
    assert row.unknown_columns == ("Mystery Column",)
    assert row.source_row_json == {"Order ID": "OD1", "Mystery Column": "??"}


def test_return_shipping_fee_spf_credit_subvention_rebate_have_registry_codes_but_no_binding():
    """component_registry.py gained RETURN_SHIPPING_FEE / SPF_CREDIT / SUBVENTION_REBATE this
    pass (real §5.1.3 concepts, no confirmed literal header) — they must exist in the registry
    for a future adapter revision to use, but this adapter's column_map never binds a header to
    any of them (guessing one would violate the never-guess rule)."""
    from data_foundation.component_registry import COMPONENT_KIND_BY_CODE

    assert COMPONENT_KIND_BY_CODE["RETURN_SHIPPING_FEE"] == "FEE"
    assert COMPONENT_KIND_BY_CODE["SPF_CREDIT"] == "CHARGE"
    assert COMPONENT_KIND_BY_CODE["SUBVENTION_REBATE"] == "CHARGE"

    bound_codes = {binding.component_code for binding in flipkart_payments_adapter.column_map.values()}
    assert "RETURN_SHIPPING_FEE" not in bound_codes
    assert "SPF_CREDIT" not in bound_codes
    assert "SUBVENTION_REBATE" not in bound_codes


def test_every_binding_is_unverified():
    """Blanket check per this pass's own hard rule: no real Flipkart settlement export has ever
    been inspected, so every single ColumnBinding in this adapter must carry is_verified=False,
    without exception."""
    assert all(binding.is_verified is False for binding in flipkart_payments_adapter.column_map.values())
