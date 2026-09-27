"""meesho.payments.v1 — data-foundation.md §2.3/§5.6/§1.4. Mirrors test_base.py's style for
the other adapters, dedicated to this one since it introduces the first settlement-side
adapter and the first scalar-field (gross_settlement_amount) mapping."""

from __future__ import annotations

from data_foundation.adapters.meesho_payments_v1 import adapter as meesho_payments_adapter
from data_foundation.types import FileSample, RawFile


def test_detect_matched_when_all_confirmed_columns_present():
    sample = FileSample(
        columns=(
            "Sub Order No",
            "Fixed Fee (Incl. GST)",
            "Final Settlement Amount",
            "Total Sale Amount (Incl. Shipping & GST)",
        )
    )
    result = meesho_payments_adapter.detect(sample)
    assert result.matched is True
    assert result.missing_columns == ()


def test_detect_reports_missing_columns_diff():
    sample = FileSample(columns=("Sub Order No",))
    result = meesho_payments_adapter.detect(sample)
    assert result.matched is False
    assert set(result.missing_columns) == {
        "Fixed Fee (Incl. GST)",
        "Final Settlement Amount",
        "Total Sale Amount (Incl. Shipping & GST)",
    }


def test_source_side_is_settlement():
    assert meesho_payments_adapter.source_side == "SETTLEMENT"


def test_parse_sub_order_no_maps_to_line_ref():
    raw = RawFile(columns=("Sub Order No",), rows=[{"Sub Order No": "SUB123"}])
    row = list(meesho_payments_adapter.parse(raw))[0]
    assert row.canonical_fields["line_ref"] == "SUB123"


def test_parse_fixed_fee_maps_to_fixed_fee_component():
    raw = RawFile(columns=("Fixed Fee (Incl. GST)",), rows=[{"Fixed Fee (Incl. GST)": "17.70"}])
    row = list(meesho_payments_adapter.parse(raw))[0]
    assert len(row.components) == 1
    component = row.components[0]
    assert component.component_code == "FIXED_FEE"
    assert component.component_kind == "FEE"
    assert component.source_side == "SETTLEMENT"
    assert component.amount_paise == 1_770


def test_parse_final_settlement_amount_converts_to_gross_settlement_amount_paise():
    raw = RawFile(columns=("Final Settlement Amount",), rows=[{"Final Settlement Amount": "372.06"}])
    row = list(meesho_payments_adapter.parse(raw))[0]
    assert row.canonical_fields["gross_settlement_amount"] == 37_206
    assert row.components == ()  # scalar field, never a line_component


def test_parse_total_sale_amount_converts_to_scalar_paise():
    raw = RawFile(
        columns=("Total Sale Amount (Incl. Shipping & GST)",),
        rows=[{"Total Sale Amount (Incl. Shipping & GST)": "195.00"}],
    )
    row = list(meesho_payments_adapter.parse(raw))[0]
    assert row.canonical_fields["total_sale_amount"] == 19_500
    assert row.components == ()  # scalar field, never a line_component


def test_parse_negative_final_settlement_amount():
    raw = RawFile(columns=("Final Settlement Amount",), rows=[{"Final Settlement Amount": "-50.00"}])
    row = list(meesho_payments_adapter.parse(raw))[0]
    assert row.canonical_fields["gross_settlement_amount"] == -5_000


def test_intentionally_unmapped_columns_land_in_unknown_columns():
    raw = RawFile(
        columns=(
            "Warehousing fee (incl GST)",
            "Return premium (incl GST)",
            "Meesho Commission Percentage",
            "Final Settlement Amount",
        ),
        rows=[
            {
                "Warehousing fee (incl GST)": "5.00",
                "Return premium (incl GST)": "2.00",
                "Meesho Commission Percentage": "10",
                "Final Settlement Amount": "100.00",
            }
        ],
    )
    row = list(meesho_payments_adapter.parse(raw))[0]
    assert set(row.unknown_columns) == {
        "Warehousing fee (incl GST)",
        "Return premium (incl GST)",
        "Meesho Commission Percentage",
    }
    # verbatim, never dropped, per §3.1 rule 5 / §2.2 rule 3
    assert row.source_row_json["Warehousing fee (incl GST)"] == "5.00"
    assert row.source_row_json["Return premium (incl GST)"] == "2.00"
    assert row.source_row_json["Meesho Commission Percentage"] == "10"


def test_parse_unknown_column_preserved_and_flagged():
    raw = RawFile(columns=("Sub Order No", "sss"), rows=[{"Sub Order No": "SUB1", "sss": "mystery"}])
    row = list(meesho_payments_adapter.parse(raw))[0]
    assert row.unknown_columns == ("sss",)
    assert row.source_row_json == {"Sub Order No": "SUB1", "sss": "mystery"}


def test_parse_duplicate_fixed_fee_header_only_first_occurrence_bound():
    # Real "Order Payments" export: "Fixed Fee (Incl. GST)" appears twice at different column
    # positions with different meanings — only occurrence 0 (index 17) is part of the real
    # settlement formula. A dict can't represent this row shape (duplicate keys collapse), so
    # this uses the tuple-list RawFile row form (data_foundation.types.RowData) instead.
    raw = RawFile(
        columns=("Sub Order No", "Fixed Fee (Incl. GST)", "Fixed Fee (Incl. GST)"),
        rows=[
            [
                ("Sub Order No", "SUB999"),
                ("Fixed Fee (Incl. GST)", "17.70"),
                ("Fixed Fee (Incl. GST)", "5.00"),
            ]
        ],
    )
    row = list(meesho_payments_adapter.parse(raw))[0]

    assert len(row.components) == 1
    assert row.components[0].component_code == "FIXED_FEE"
    assert row.components[0].amount_paise == 1_770  # from occurrence 0's value (17.70), not occurrence 1's

    assert row.unknown_columns == ("Fixed Fee (Incl. GST)",)  # occurrence 1, unbound, correctly flagged

    # source_row_json (a dict) collapses the duplicate header — last value wins, one is lost.
    # This is a known, documented limitation (types.py's ParsedRow docstring), not a silent
    # regression: source_row_pairs (below) is the field that actually preserves both.
    assert row.source_row_json["Fixed Fee (Incl. GST)"] == "5.00"  # occurrence 1 overwrote occurrence 0

    # source_row_pairs is duplicate-safe: both occurrences survive, in original order, with
    # their original values — the full-fidelity audit copy source_row_json cannot provide here.
    fixed_fee_pairs = [(k, v) for k, v in row.source_row_pairs if k == "Fixed Fee (Incl. GST)"]
    assert fixed_fee_pairs == [("Fixed Fee (Incl. GST)", "17.70"), ("Fixed Fee (Incl. GST)", "5.00")]
    assert row.source_row_pairs == (
        ("Sub Order No", "SUB999"),
        ("Fixed Fee (Incl. GST)", "17.70"),
        ("Fixed Fee (Incl. GST)", "5.00"),
    )


def test_parse_real_meesho_row_source_row_pairs_preserves_both_duplicate_values():
    """Regression test using the ACTUAL real-export values this session extracted directly
    from a real seller's Payments workbook (row 1, "Order Payments" tab,
    meesho_PREVIOUS_PAYMENT_2026-01-01_2026-01-31) — not a synthetic approximation. Both real
    "Fixed Fee (Incl. GST)" cells on that row happened to be 0.00, which is exactly why this
    test also checks column identity/order, not just non-zero values: a bug that dropped one
    occurrence but kept the other would be invisible if both values were equal, so the
    assertion is on the pair COUNT and the surviving `unknown_columns` entry, matching what
    real-data validation (this session) confirmed against the live adapter."""
    raw = RawFile(
        columns=("Sub Order No", "Fixed Fee (Incl. GST)", "Fixed Fee (Incl. GST)", "Final Settlement Amount"),
        rows=[
            [
                ("Sub Order No", "239871537625475904_1"),
                ("Fixed Fee (Incl. GST)", "0.0"),
                ("Fixed Fee (Incl. GST)", "0.0"),
                ("Final Settlement Amount", "125.12"),
            ]
        ],
    )
    row = list(meesho_payments_adapter.parse(raw))[0]

    assert row.canonical_fields["line_ref"] == "239871537625475904_1"
    assert row.canonical_fields["gross_settlement_amount"] == 12_512  # matches the real settled row exactly
    assert len(row.components) == 1  # occurrence 0 only, never double-counted
    assert row.unknown_columns == ("Fixed Fee (Incl. GST)",)  # occurrence 1, correctly unbound

    # The real gap this test guards: source_row_json has 3 keys (one Fixed Fee entry collapsed
    # away), source_row_pairs has all 4 real columns, in order, none lost.
    assert len(row.source_row_json) == 3
    assert len(row.source_row_pairs) == 4
