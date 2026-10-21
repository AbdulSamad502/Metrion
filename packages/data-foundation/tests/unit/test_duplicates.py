"""Duplicate classification matrix (cfo-data-intelligence.md §6.3, TD9b, AC-D6b). Pure; no database."""

from __future__ import annotations

from datetime import date

import pytest

from data_foundation.ingestion.duplicates import (
    DupClass,
    DuplicateTracker,
    ExistingEntry,
    SALES,
    SETTLEMENT,
    existing_sales_entry,
    existing_settlement_entry,
    raw_row_hash,
)
from data_foundation.types import ParsedRow
from data_foundation.validation.severity import Severity


def row(n: int, raw: dict[str, str], **fields: object) -> ParsedRow:
    return ParsedRow(source_row_number=n, source_row_json=raw, canonical_fields=dict(fields), components=(), unknown_columns=(), unmapped_enum_fields=())


def sales(n: int, order: str, line: str | None = None, *, sku: str | None = None, price: str = "100", invoice: str | None = None) -> ParsedRow:
    raw = {"Order": order, "Line": line or "", "SKU": sku or "", "Price": price}
    f: dict[str, object] = {"order_ref": order}
    if line:
        f["line_ref"] = line
    if sku:
        f["sku"] = sku
    if invoice:
        f["invoice_ref"] = invoice
    return row(n, raw, **f)


def settlement(n: int, order: str, amount: int, *, sid: str | None = None, when: date | None = None, extra: str = "") -> ParsedRow:
    raw = {"Order": order, "Amount": str(amount), "SID": sid or "", "When": str(when or ""), "Extra": extra}
    f: dict[str, object] = {"order_ref": order, "gross_settlement_amount": amount}
    if sid:
        f["settlement_id"] = sid
    if when:
        f["settlement_date"] = when
    return row(n, raw, **f)


def classes(decisions) -> list[DupClass]:  # type: ignore[no-untyped-def]
    return [d.klass for d in decisions]


def entry_for(r: ParsedRow, side: str = SALES, marketplace: str = "MEESHO") -> ExistingEntry:
    make = existing_sales_entry if side == SALES else existing_settlement_entry
    e = make(marketplace, r.canonical_fields, r.source_row_json)
    assert e is not None
    return e


# ------------------------------------------------------------------------------------------ sales
def test_distinct_lines_are_all_new() -> None:
    t = DuplicateTracker(SALES, "MEESHO")
    assert classes(t.classify([sales(1, "O1", "L1"), sales(2, "O1", "L2"), sales(3, "O2", "L1")], [])) == [DupClass.NEW] * 3


def test_two_items_of_one_order_without_line_ref_are_not_duplicates() -> None:
    t = DuplicateTracker(SALES, "AMAZON")
    out = t.classify([sales(1, "O1", sku="SKU-A", invoice="INV1"), sales(2, "O1", sku="SKU-B", invoice="INV1")], [])
    assert classes(out) == [DupClass.NEW, DupClass.NEW]


def test_exact_repeat_in_file_is_skipped_with_a_warning_naming_the_first_row() -> None:
    t = DuplicateTracker(SALES, "MEESHO")
    out = t.classify([sales(1, "O1", "L1"), sales(2, "O1", "L1")], [])
    assert classes(out) == [DupClass.NEW, DupClass.EXACT_DUPLICATE_IN_FILE]
    assert out[1].finding is not None and out[1].finding.severity is Severity.WARNING and "row 1" in out[1].finding.message
    assert out[1].klass.skipped_as_duplicate and not out[1].klass.held


def test_same_line_different_values_in_file_holds_the_later_row() -> None:
    out = DuplicateTracker(SALES, "MEESHO").classify([sales(1, "O1", "L1", price="100"), sales(2, "O1", "L1", price="120")], [])
    assert classes(out) == [DupClass.NEW, DupClass.CONFLICT_IN_FILE]
    assert out[1].finding is not None and out[1].finding.rule_id == "V-DUP-003" and out[1].finding.severity is Severity.ERROR
    assert out[1].klass.held


def test_cross_file_overlap_exact_vs_conflict() -> None:
    earlier = sales(1, "O1", "L1", price="100")
    t = DuplicateTracker(SALES, "MEESHO")
    out = t.classify([sales(1, "O1", "L1", price="100"), sales(2, "O1", "L1", price="150"), sales(3, "O9", "L1")], [entry_for(earlier)])
    # first row: identical to earlier data (overlap); the in-file second row then conflicts with that first row.
    assert classes(out) == [DupClass.EXACT_DUPLICATE_CROSS_FILE, DupClass.CONFLICT_IN_FILE, DupClass.NEW]


def test_cross_file_conflict_alone_is_held() -> None:
    earlier = sales(1, "O1", "L1", price="100")
    out = DuplicateTracker(SALES, "MEESHO").classify([sales(1, "O1", "L1", price="150")], [entry_for(earlier)])
    assert classes(out) == [DupClass.CONFLICT_CROSS_FILE]
    assert "needs your confirmation" in out[0].finding.message  # type: ignore[union-attr]


def test_identity_weak_identical_repeat_is_ambiguous_not_a_safe_skip() -> None:
    out = DuplicateTracker(SALES, "AMAZON").classify([sales(1, "O1", invoice="INV1"), sales(2, "O1", invoice="INV1")], [])
    assert classes(out) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT]
    assert out[1].finding is not None and out[1].finding.rule_id == "V-DUP-002" and out[1].klass.held


def test_rows_with_no_identity_fields_post_but_identical_repeats_are_held() -> None:
    a = row(1, {"x": "1"}, quantity=1)
    b = row(2, {"x": "1"}, quantity=1)
    c = row(3, {"x": "2"}, quantity=1)
    assert classes(DuplicateTracker(SALES, "MEESHO").classify([a, b, c], [])) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT, DupClass.NEW]


def test_tracker_state_carries_across_chunks() -> None:
    t = DuplicateTracker(SALES, "MEESHO")
    t.classify([sales(1, "O1", "L1")], [])
    out = t.classify([sales(2, "O1", "L1")], [])  # same identity, next chunk
    assert classes(out) == [DupClass.EXACT_DUPLICATE_IN_FILE] and out[0].first_seen_row == 1


# -------------------------------------------------------------------------------------- settlement
def test_three_partial_settlements_of_one_order_are_all_posted() -> None:
    out = DuplicateTracker(SETTLEMENT, "FLIPKART").classify(
        [settlement(1, "O1", 40_000, sid="S1", when=date(2026, 10, 1)),
         settlement(2, "O1", 35_000, sid="S2", when=date(2026, 10, 8)),
         settlement(3, "O1", -5_000, sid="S3", when=date(2026, 10, 15), extra="reversal")], [])
    assert classes(out) == [DupClass.NEW] * 3


def test_same_order_same_day_different_adjustment_amounts_are_distinct() -> None:
    out = DuplicateTracker(SETTLEMENT, "FLIPKART").classify(
        [settlement(1, "O1", -1_000, sid="S1", when=date(2026, 10, 1)), settlement(2, "O1", -2_500, sid="S1", when=date(2026, 10, 1))], [])
    assert classes(out) == [DupClass.NEW, DupClass.NEW]


def test_identical_settlement_rows_in_one_file_are_ambiguous_and_held() -> None:
    a, b = settlement(1, "O1", -1_000, sid="S1", when=date(2026, 10, 1)), settlement(2, "O1", -1_000, sid="S1", when=date(2026, 10, 1))
    out = DuplicateTracker(SETTLEMENT, "FLIPKART").classify([a, b], [])
    assert classes(out) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT]
    assert "add a distinguishing reference" in out[1].finding.message  # type: ignore[union-attr]


def test_same_settlement_identity_with_different_content_is_a_conflict() -> None:
    a = settlement(1, "O1", -1_000, sid="S1", when=date(2026, 10, 1), extra="fee 10")
    b = settlement(2, "O1", -1_000, sid="S1", when=date(2026, 10, 1), extra="fee 12")
    assert classes(DuplicateTracker(SETTLEMENT, "FLIPKART").classify([a, b], [])) == [DupClass.NEW, DupClass.CONFLICT_IN_FILE]


def test_reuploaded_settlement_report_is_cross_file_overlap_not_new_money() -> None:
    first = settlement(1, "O1", 40_000, sid="S1", when=date(2026, 10, 1))
    again = settlement(7, "O1", 40_000, sid="S1", when=date(2026, 10, 1))
    out = DuplicateTracker(SETTLEMENT, "FLIPKART").classify([again], [entry_for(first, SETTLEMENT, "FLIPKART")])
    assert classes(out) == [DupClass.EXACT_DUPLICATE_CROSS_FILE]


def test_meesho_style_settlement_with_only_line_ref_and_amount() -> None:
    # Real Meesho payments rows carry only line_ref + amount: weak identity, so an identical repeat is held, never doubled.
    a = row(1, {"Sub Order No": "L1", "Final Settlement Amount": "250.00"}, line_ref="L1", gross_settlement_amount=25_000)
    b = row(2, {"Sub Order No": "L1", "Final Settlement Amount": "250.00"}, line_ref="L1", gross_settlement_amount=25_000)
    c = row(3, {"Sub Order No": "L1", "Final Settlement Amount": "180.00"}, line_ref="L1", gross_settlement_amount=18_000)
    assert classes(DuplicateTracker(SETTLEMENT, "MEESHO").classify([a, b, c], [])) == [DupClass.NEW, DupClass.AMBIGUOUS_REPEAT, DupClass.NEW]


# ------------------------------------------------------------------------------------------ hashing
def test_raw_hash_is_order_independent_and_value_sensitive() -> None:
    assert raw_row_hash({"a": "1", "b": " 2 "}) == raw_row_hash({"b": "2", "a": "1"})
    assert raw_row_hash({"a": "1"}) != raw_row_hash({"a": "2"})
    assert len(raw_row_hash({})) == 16


def test_identity_digests_match_between_incoming_and_stored_forms() -> None:
    inc = settlement(1, "O1", 40_000, sid="S1", when=date(2026, 10, 1))
    stored = existing_settlement_entry("FLIPKART", {"order_ref": "O1", "line_ref": None, "settlement_id": "S1",
                                                    "settlement_date": date(2026, 10, 1), "gross_settlement_amount": 40_000}, inc.source_row_json)
    assert stored is not None
    out = DuplicateTracker(SETTLEMENT, "FLIPKART").classify([inc], [stored])
    assert classes(out) == [DupClass.EXACT_DUPLICATE_CROSS_FILE]


def test_unknown_side_rejected() -> None:
    with pytest.raises(ValueError):
        DuplicateTracker("INVENTORY", "MEESHO")
