"""Duplicate classification matrix (cfo-data-intelligence.md §6.3, TD9b, AC-D6b). Pure; no database.

Covers the classification classes, the report family, and strong identity defined separately for Amazon, Flipkart and Meesho."""

from __future__ import annotations

from datetime import date

import pytest

from data_foundation.ingestion.duplicates import (
    MARKETPLACE_IDENTITY,
    SALES,
    SETTLEMENT,
    DupClass,
    DuplicateTracker,
    ExistingEntry,
    existing_sales_entry,
    existing_settlement_entry,
    raw_row_hash,
    report_family,
)
from data_foundation.types import ParsedRow
from data_foundation.validation.severity import Severity

FAM = {"MEESHO": "meesho.orders", "AMAZON": "amazon.mtr.b2c", "FLIPKART": "flipkart.sales.report"}
SFAM = {"MEESHO": "meesho.payments", "AMAZON": "amazon.settlement", "FLIPKART": "flipkart.payments"}


def row(n: int, raw: dict[str, str], **fields: object) -> ParsedRow:
    return ParsedRow(source_row_number=n, source_row_json=raw, canonical_fields=dict(fields), components=(), unknown_columns=(), unmapped_enum_fields=())


def sales(n: int, order: str, line: str | None = None, *, sku: str | None = None, item: str | None = None, price: str = "100", invoice: str | None = None) -> ParsedRow:
    raw = {"Order": order, "Line": line or "", "SKU": sku or "", "Item": item or "", "Price": price}
    f: dict[str, object] = {"order_ref": order}
    for k, v in (("line_ref", line), ("sku", sku), ("marketplace_item_id", item), ("invoice_ref", invoice)):
        if v:
            f[k] = v
    return row(n, raw, **f)


def settlement(n: int, order: str, amount: int, *, sid: str | None = None, when: date | None = None, extra: str = "", **more: object) -> ParsedRow:
    raw = {"Order": order, "Amount": str(amount), "SID": sid or "", "When": str(when or ""), "Extra": extra}
    f: dict[str, object] = {"order_ref": order, "gross_settlement_amount": amount, **more}
    if sid:
        f["settlement_id"] = sid
    if when:
        f["settlement_date"] = when
    return row(n, raw, **f)


def classes(decisions) -> list[DupClass]:  # type: ignore[no-untyped-def]
    return [d.klass for d in decisions]


def sales_tracker(mp: str = "MEESHO") -> DuplicateTracker:
    return DuplicateTracker(SALES, mp, FAM[mp])


def settle_tracker(mp: str = "FLIPKART") -> DuplicateTracker:
    return DuplicateTracker(SETTLEMENT, mp, SFAM[mp])


def entry_for(r: ParsedRow, *, side: str = SALES, mp: str = "MEESHO", family: str | None = None) -> ExistingEntry:
    make = existing_sales_entry if side == SALES else existing_settlement_entry
    e = make(mp, family or (FAM[mp] if side == SALES else SFAM[mp]), r.canonical_fields, r.source_row_json)
    assert e is not None
    return e


# ================================================================================ classification
def test_distinct_lines_are_all_new() -> None:
    assert classes(sales_tracker().classify([sales(1, "O1", "L1"), sales(2, "O1", "L2"), sales(3, "O2", "L1")], [])) == [DupClass.NEW] * 3


def test_exact_repeat_in_file_is_skipped_with_a_warning_naming_the_first_row() -> None:
    out = sales_tracker().classify([sales(1, "O1", "L1"), sales(2, "O1", "L1")], [])
    assert classes(out) == [DupClass.NEW, DupClass.EXACT_DUPLICATE_IN_FILE]
    assert out[1].finding is not None and out[1].finding.severity is Severity.WARNING and "row 1" in out[1].finding.message
    assert out[1].klass.skipped_as_duplicate and not out[1].klass.held and not out[1].klass.posts


def test_same_line_different_values_in_file_holds_the_later_row() -> None:
    out = sales_tracker().classify([sales(1, "O1", "L1", price="100"), sales(2, "O1", "L1", price="120")], [])
    assert classes(out) == [DupClass.NEW, DupClass.CONFLICT_IN_FILE]
    assert out[1].finding is not None and out[1].finding.rule_id == "V-DUP-003" and out[1].finding.severity is Severity.ERROR and out[1].klass.held


def test_cross_file_overlap_exact_vs_conflict() -> None:
    earlier = sales(1, "O1", "L1", price="100")
    out = sales_tracker().classify([sales(1, "O1", "L1", price="100"), sales(2, "O1", "L1", price="150"), sales(3, "O9", "L1")], [entry_for(earlier)])
    assert classes(out) == [DupClass.EXACT_DUPLICATE_CROSS_FILE, DupClass.CONFLICT_IN_FILE, DupClass.NEW]
    lone = sales_tracker().classify([sales(1, "O1", "L1", price="150")], [entry_for(earlier)])
    assert classes(lone) == [DupClass.CONFLICT_CROSS_FILE] and "needs your confirmation" in lone[0].finding.message  # type: ignore[union-attr]


def test_rows_with_no_identity_fields_post_but_identical_repeats_are_held() -> None:
    a, b, c = row(1, {"x": "1"}, quantity=1), row(2, {"x": "1"}, quantity=1), row(3, {"x": "2"}, quantity=1)
    assert classes(sales_tracker().classify([a, b, c], [])) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT, DupClass.NEW]


def test_tracker_state_carries_across_chunks() -> None:
    t = sales_tracker()
    t.classify([sales(1, "O1", "L1")], [])
    out = t.classify([sales(2, "O1", "L1")], [])
    assert classes(out) == [DupClass.EXACT_DUPLICATE_IN_FILE] and out[0].first_seen_row == 1


# ======================================================== strong identity, defined per marketplace
@pytest.mark.parametrize("mp,line_meaning", [("MEESHO", "Sub Order No"), ("AMAZON", "Shipment Item ID"), ("FLIPKART", "Line Item ID")])
def test_each_marketplace_has_a_documented_unique_line_id(mp: str, line_meaning: str) -> None:
    rule = MARKETPLACE_IDENTITY[mp]
    assert rule.sales_line_field == "line_ref" and rule.sales_line_meaning == line_meaning and rule.settlement_fields


@pytest.mark.parametrize("mp", ["MEESHO", "AMAZON", "FLIPKART"])
def test_with_the_marketplaces_line_id_an_identical_repeat_is_a_safe_skip(mp: str) -> None:
    out = sales_tracker(mp).classify([sales(1, "O1", "LINE-A", item="P1"), sales(2, "O1", "LINE-A", item="P1")], [])
    assert classes(out) == [DupClass.NEW, DupClass.EXACT_DUPLICATE_IN_FILE]


@pytest.mark.parametrize("mp", ["MEESHO", "AMAZON", "FLIPKART"])
def test_a_product_id_is_never_a_line_id_identical_repeats_without_a_line_id_are_held(mp: str) -> None:
    # Same ASIN/FSN/SKU, no line id: the same product can legitimately sit on two lines of one order, so a repeat cannot be skipped.
    out = sales_tracker(mp).classify([sales(1, "O1", item="P1", sku="S1"), sales(2, "O1", item="P1", sku="S1")], [])
    assert classes(out) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT]
    assert out[1].finding is not None and out[1].finding.rule_id == "V-DUP-002"
    assert MARKETPLACE_IDENTITY[mp].sales_line_meaning in out[1].finding.message  # the explanation names this marketplace's own id


@pytest.mark.parametrize("mp", ["MEESHO", "AMAZON", "FLIPKART"])
def test_same_product_on_two_different_lines_of_one_order_are_both_posted(mp: str) -> None:
    out = sales_tracker(mp).classify([sales(1, "O1", "LINE-A", item="SAME-ASIN"), sales(2, "O1", "LINE-B", item="SAME-ASIN")], [])
    assert classes(out) == [DupClass.NEW, DupClass.NEW]


def test_two_different_products_of_one_order_without_a_line_id_are_not_merged() -> None:
    out = sales_tracker("AMAZON").classify([sales(1, "O1", item="P1", invoice="INV1"), sales(2, "O1", item="P2", invoice="INV1")], [])
    assert classes(out) == [DupClass.NEW, DupClass.NEW]


def test_an_unknown_marketplace_gets_the_conservative_default_nothing_is_strong() -> None:
    out = DuplicateTracker(SALES, "SNAPDEAL", "x").classify([sales(1, "O1", "L1"), sales(2, "O1", "L1")], [])
    assert classes(out) == [DupClass.NEW, DupClass.EXACT_DUPLICATE_IN_FILE]  # a line id still counts, but...
    out2 = DuplicateTracker(SETTLEMENT, "SNAPDEAL", "x").classify([settlement(1, "O1", 5), settlement(2, "O1", 5)], [])
    assert classes(out2) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT]  # ...a settlement row never is strong


# ========================================================== settlement identity, per marketplace
def test_flipkart_partial_settlements_and_adjustments_of_one_order_are_all_posted() -> None:
    out = settle_tracker("FLIPKART").classify(
        [settlement(1, "O1", 40_000, sid="S1", when=date(2026, 10, 1)), settlement(2, "O1", 35_000, sid="S2", when=date(2026, 10, 8)),
         settlement(3, "O1", -5_000, sid="S3", when=date(2026, 10, 15), extra="reversal")], [])
    assert classes(out) == [DupClass.NEW] * 3


def test_flipkart_same_order_same_day_different_adjustment_amounts_are_distinct() -> None:
    out = settle_tracker("FLIPKART").classify(
        [settlement(1, "O1", -1_000, sid="S1", when=date(2026, 10, 1)), settlement(2, "O1", -2_500, sid="S1", when=date(2026, 10, 1))], [])
    assert classes(out) == [DupClass.NEW, DupClass.NEW]


def test_flipkart_identical_settlement_rows_are_ambiguous_and_held() -> None:
    a = settlement(1, "O1", -1_000, sid="S1", when=date(2026, 10, 1))
    b = settlement(2, "O1", -1_000, sid="S1", when=date(2026, 10, 1))
    out = settle_tracker("FLIPKART").classify([a, b], [])
    assert classes(out) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT] and "add a distinguishing reference" in out[1].finding.message  # type: ignore[union-attr]


def test_flipkart_same_identity_different_content_is_a_conflict() -> None:
    a = settlement(1, "O1", -1_000, sid="S1", when=date(2026, 10, 1), extra="fee 10")
    b = settlement(2, "O1", -1_000, sid="S1", when=date(2026, 10, 1), extra="fee 12")
    assert classes(settle_tracker("FLIPKART").classify([a, b], [])) == [DupClass.NEW, DupClass.CONFLICT_IN_FILE]


def test_reuploaded_settlement_report_is_overlap_not_new_money() -> None:
    first = settlement(1, "O1", 40_000, sid="S1", when=date(2026, 10, 1))
    again = settlement(7, "O1", 40_000, sid="S1", when=date(2026, 10, 1))
    out = settle_tracker("FLIPKART").classify([again], [entry_for(first, side=SETTLEMENT, mp="FLIPKART")])
    assert classes(out) == [DupClass.EXACT_DUPLICATE_CROSS_FILE]


def test_meesho_payments_rows_carry_only_line_ref_and_amount_so_an_identical_repeat_is_held() -> None:
    a = row(1, {"Sub Order No": "L1", "Final Settlement Amount": "250.00"}, line_ref="L1", gross_settlement_amount=25_000)
    b = row(2, {"Sub Order No": "L1", "Final Settlement Amount": "250.00"}, line_ref="L1", gross_settlement_amount=25_000)
    c = row(3, {"Sub Order No": "L1", "Final Settlement Amount": "180.00"}, line_ref="L1", gross_settlement_amount=18_000)
    assert classes(settle_tracker("MEESHO").classify([a, b, c], [])) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT, DupClass.NEW]


def test_amazon_melted_settlement_rows_of_one_item_are_distinct_by_amount_description() -> None:
    def melted(n: int, desc: str, amount: int) -> ParsedRow:
        return row(n, {"d": desc, "a": str(amount)}, order_ref="O1", order_item_code="I1", settlement_id="S9", settlement_amount_type="ItemFees",
                   settlement_amount_description=desc, settlement_amount_value=amount)

    out = settle_tracker("AMAZON").classify([melted(1, "Commission", -1500), melted(2, "FBA fee", -2000), melted(3, "Principal", 10000)], [])
    assert classes(out) == [DupClass.NEW] * 3
    repeat = settle_tracker("AMAZON").classify([melted(1, "Commission", -1500), melted(2, "Commission", -1500)], [])
    assert classes(repeat) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT]  # an identical melted row twice cannot be told from a double export


# ============================================================================== report family
def test_report_family_strips_the_version_so_a_new_version_of_the_same_report_still_overlaps() -> None:
    assert report_family("meesho.orders.v1") == report_family("meesho.orders.v2") == "meesho.orders"
    assert report_family("amazon.settlement.v2") == "amazon.settlement"


def test_report_family_of_a_mapped_adapter_is_the_confirmed_file_shape() -> None:
    assert report_family("mapped.abc", "fp1") == "mapped:fp1" == report_family("mapped.other-version", "fp1")
    with pytest.raises(ValueError):
        report_family("mapped.abc")  # never guess a family without the mapping's fingerprint


def test_a_different_kind_of_report_about_the_same_line_is_not_a_duplicate() -> None:
    """Meesho orders and Meesho TCS both carry rows for one Sub Order No. They are different facts, not duplicates of each other."""
    orders_row = sales(1, "O1", "SUB-1", price="100")
    tcs_row = row(1, {"Sub Order No": "SUB-1", "TCS Taxable Sales": "84.75"}, line_ref="SUB-1", taxable_amount=8475)
    existing = entry_for(orders_row, family="meesho.orders")
    out = DuplicateTracker(SALES, "MEESHO", "meesho.tcs.sales").classify([tcs_row], [existing])
    assert classes(out) == [DupClass.NEW]
    corrected = sales(1, "O1", "SUB-1", price="999")  # same report family, same line, different content
    same_family = DuplicateTracker(SALES, "MEESHO", "meesho.orders").classify([corrected], [existing])
    assert classes(same_family) == [DupClass.CONFLICT_CROSS_FILE]  # inside one family the same line with different content IS a conflict
    # ...and the very same row presented under another family is simply a different report's row
    assert classes(DuplicateTracker(SALES, "MEESHO", "meesho.tcs.sales").classify([corrected], [existing])) == [DupClass.NEW]


# ================================================================================== hashing
def test_raw_hash_is_order_independent_and_value_sensitive() -> None:
    assert raw_row_hash({"a": "1", "b": " 2 "}) == raw_row_hash({"b": "2", "a": "1"})
    assert raw_row_hash({"a": "1"}) != raw_row_hash({"a": "2"})
    assert len(raw_row_hash({})) == 16


def test_identity_digests_match_between_incoming_and_stored_forms() -> None:
    inc = settlement(1, "O1", 40_000, sid="S1", when=date(2026, 10, 1))
    stored = existing_settlement_entry("FLIPKART", SFAM["FLIPKART"], {"order_ref": "O1", "line_ref": None, "settlement_id": "S1",
                                                                      "settlement_date": date(2026, 10, 1), "gross_settlement_amount": 40_000}, inc.source_row_json)
    assert stored is not None
    assert classes(settle_tracker("FLIPKART").classify([inc], [stored])) == [DupClass.EXACT_DUPLICATE_CROSS_FILE]


def test_unknown_side_rejected() -> None:
    with pytest.raises(ValueError):
        DuplicateTracker("INVENTORY", "MEESHO", "x")
