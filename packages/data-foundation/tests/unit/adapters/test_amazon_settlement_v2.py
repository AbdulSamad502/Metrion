"""amazon.settlement.v2 — mirrors test_flipkart_payments_v1.py's structure/rigor. Every
assertion here exercises `is_verified=False` bindings built from data-foundation.md §5.1.2's
secondary-sourced identity/join-key research and §5.1.4's melted-amount-triple capture-not-
classify decision; nothing here claims real-export validation.

The example melted-triple values used below (`amount-type="ItemFees"`,
`amount-description="Commission"`, `amount="-45.00"`) are the spec's own illustrative example
(§5.1.4) — not claimed as a real observed Amazon value."""

from __future__ import annotations

from data_foundation.adapters.amazon_settlement_v2 import adapter as amazon_settlement_adapter
from data_foundation.types import FileSample, RawFile


def test_detect_matched_when_all_confirmed_columns_present():
    sample = FileSample(
        columns=(
            "order-id",
            "settlement-id",
            "shipment-id",
            "sku",
            "marketplace-name",
            "merchant-order-id",
            "order-item-code",
            "merchant-order-item-id",
            "amount-type",
            "amount-description",
            "amount",
        )
    )
    result = amazon_settlement_adapter.detect(sample)
    assert result.matched is True
    assert result.missing_columns == ()


def test_detect_reports_missing_columns_diff():
    sample = FileSample(columns=("order-id",))
    result = amazon_settlement_adapter.detect(sample)
    assert result.matched is False
    assert set(result.missing_columns) == {
        "settlement-id",
        "shipment-id",
        "sku",
        "marketplace-name",
        "merchant-order-id",
        "order-item-code",
        "merchant-order-item-id",
        "amount-type",
        "amount-description",
        "amount",
    }


def test_source_side_is_settlement():
    assert amazon_settlement_adapter.source_side == "SETTLEMENT"


def test_parse_order_id_maps_to_order_ref():
    raw = RawFile(columns=("order-id",), rows=[{"order-id": "406-1234567-8901234"}])
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.canonical_fields["order_ref"] == "406-1234567-8901234"


def test_parse_settlement_id_maps_to_settlement_id_field():
    raw = RawFile(columns=("settlement-id",), rows=[{"settlement-id": "22120012345"}])
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.canonical_fields["settlement_id"] == "22120012345"


def test_shipment_sku_marketplace_name_merchant_order_id_captured_as_plain_fields():
    raw = RawFile(
        columns=("shipment-id", "sku", "marketplace-name", "merchant-order-id"),
        rows=[
            {
                "shipment-id": "SHIP123",
                "sku": "SKU-ABC-1",
                "marketplace-name": "Amazon.in",
                "merchant-order-id": "MORD-1",
            }
        ],
    )
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.canonical_fields["shipment_id"] == "SHIP123"
    assert row.canonical_fields["sku"] == "SKU-ABC-1"
    assert row.canonical_fields["marketplace_name"] == "Amazon.in"
    assert row.canonical_fields["merchant_order_id"] == "MORD-1"
    assert row.components == ()


def test_order_item_code_and_merchant_order_item_id_both_captured_neither_is_line_ref():
    raw = RawFile(
        columns=("order-item-code", "merchant-order-item-id"),
        rows=[{"order-item-code": "OIC-1", "merchant-order-item-id": "MOII-1"}],
    )
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.canonical_fields["order_item_code"] == "OIC-1"
    assert row.canonical_fields["merchant_order_item_id"] == "MOII-1"
    assert "line_ref" not in row.canonical_fields


def test_melted_triple_captured_verbatim_and_produces_no_component():
    raw = RawFile(
        columns=("amount-type", "amount-description", "amount"),
        rows=[
            {
                "amount-type": "ItemFees",
                "amount-description": "Commission",
                "amount": "-45.00",
            }
        ],
    )
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.canonical_fields["settlement_amount_type"] == "ItemFees"
    assert row.canonical_fields["settlement_amount_description"] == "Commission"
    assert row.canonical_fields["settlement_amount_value"] == -4_500
    assert row.components == ()
    assert row.unmapped_enum_fields == ()


def test_melted_triple_amount_type_has_no_enum_map_and_never_raises_v_enum_001():
    """§5.1.4: amount-type has no enum_maps entry at all — the enum_map-is-None fallthrough in
    _parse_row captures the raw value verbatim and never appends to unmapped_enum_fields, which
    is reserved for a *declared-but-incomplete* enumeration, not an undeclared one."""
    assert "settlement_amount_type" not in amazon_settlement_adapter.enum_maps
    assert "settlement_amount_description" not in amazon_settlement_adapter.enum_maps
    raw = RawFile(
        columns=("amount-type",),
        rows=[{"amount-type": "SomeNeverSeenBeforeValue"}],
    )
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.canonical_fields["settlement_amount_type"] == "SomeNeverSeenBeforeValue"
    assert row.unmapped_enum_fields == ()


def test_parse_negative_amount_value_signed_paise():
    raw = RawFile(columns=("amount",), rows=[{"amount": "-45.00"}])
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.canonical_fields["settlement_amount_value"] == -4_500


def test_parse_positive_amount_value_signed_paise():
    raw = RawFile(columns=("amount",), rows=[{"amount": "120.50"}])
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.canonical_fields["settlement_amount_value"] == 12_050


def test_gross_settlement_amount_never_populated():
    """§5.1.4: gross_settlement_amount is a real, deliberate gap for this adapter — a per-
    order-item settlement total would require summing amount values across rows, which parse()
    (single-row, streaming, shape-only) is not permitted to do. No column in this adapter binds
    to gross_settlement_amount."""
    bound_fields = {binding.canonical_field for binding in amazon_settlement_adapter.column_map.values()}
    assert "gross_settlement_amount" not in bound_fields

    raw = RawFile(
        columns=("order-id", "settlement-id", "amount-type", "amount-description", "amount"),
        rows=[
            {
                "order-id": "406-1234567-8901234",
                "settlement-id": "22120012345",
                "amount-type": "ItemFees",
                "amount-description": "Commission",
                "amount": "-45.00",
            }
        ],
    )
    for row in amazon_settlement_adapter.parse(raw):
        assert row.canonical_fields.get("gross_settlement_amount") is None


def test_posted_date_and_other_unbound_columns_fall_through_to_unknown_columns():
    raw = RawFile(
        columns=("order-id", "posted-date", "posted-date-time", "quantity-purchased"),
        rows=[
            {
                "order-id": "406-1234567-8901234",
                "posted-date": "2025-08-26T10:00:00Z",
                "posted-date-time": "2025-08-26T10:00:00Z",
                "quantity-purchased": "2",
            }
        ],
    )
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert set(row.unknown_columns) == {"posted-date", "posted-date-time", "quantity-purchased"}
    assert row.canonical_fields["order_ref"] == "406-1234567-8901234"


def test_parse_unknown_column_preserved_and_flagged():
    raw = RawFile(columns=("order-id", "Mystery Column"), rows=[{"order-id": "O1", "Mystery Column": "??"}])
    row = list(amazon_settlement_adapter.parse(raw))[0]
    assert row.unknown_columns == ("Mystery Column",)
    assert row.source_row_json == {"order-id": "O1", "Mystery Column": "??"}


def test_date_formats_has_no_posted_date_entry():
    assert "settlement_date" not in amazon_settlement_adapter.date_formats
    assert amazon_settlement_adapter.date_formats == {}


def test_every_binding_is_unverified():
    """Blanket check per this pass's own hard rule: no real Amazon settlement V2 export has
    ever been inspected, so every single ColumnBinding in this adapter must carry
    is_verified=False, without exception."""
    assert all(binding.is_verified is False for binding in amazon_settlement_adapter.column_map.values())


def test_melted_triple_bindings_have_no_component_code():
    """§5.1.4, the critical rule: component_code stays None for all three melted-triple
    bindings — no ComponentValue is ever produced from amount-type/amount-description/amount."""
    for header in ("amount-type", "amount-description", "amount"):
        assert amazon_settlement_adapter.column_map[header].component_code is None
