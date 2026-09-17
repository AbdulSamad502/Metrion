"""content_sha256 + natural-key dedup — data-foundation.md §3.1 rule 3, §6 rule 4."""

from __future__ import annotations

from data_foundation.ingestion.dedup import find_natural_key_duplicates, is_duplicate_file, natural_key
from data_foundation.types import ParsedRow


def _row(order_ref=None, line_ref=None, invoice_ref=None, row_number=1) -> ParsedRow:
    return ParsedRow(
        source_row_number=row_number,
        source_row_json={},
        canonical_fields={"order_ref": order_ref, "line_ref": line_ref, "invoice_ref": invoice_ref},
        components=(),
        unknown_columns=(),
        unmapped_enum_fields=(),
    )


def test_is_duplicate_file_detects_matching_hash():
    assert is_duplicate_file("abc123", ["def456", "abc123"]) is True


def test_is_duplicate_file_no_match():
    assert is_duplicate_file("abc123", ["def456"]) is False


def test_natural_key_none_when_no_key_fields_present():
    assert natural_key("MEESHO", _row()) is None


def test_natural_key_built_from_available_fields():
    key = natural_key("MEESHO", _row(order_ref="ORD1", line_ref="SUB1"))
    assert key == ("MEESHO", "ORD1", "SUB1", None)


def test_find_natural_key_duplicates_flags_overlapping_rows():
    rows = [_row(order_ref="ORD1", line_ref="SUB1", row_number=1), _row(order_ref="ORD2", line_ref="SUB2", row_number=2)]
    existing = [("MEESHO", "ORD1", "SUB1", None)]
    assert find_natural_key_duplicates("MEESHO", rows, existing) == [1]


def test_find_natural_key_duplicates_keyless_row_never_matches():
    rows = [_row(row_number=1)]
    existing = [("MEESHO", None, None, None)]
    assert find_natural_key_duplicates("MEESHO", rows, existing) == []
