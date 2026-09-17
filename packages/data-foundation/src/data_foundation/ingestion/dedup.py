"""content_sha256 + natural-key dedup — data-foundation.md §3.1 rule 3, §6 rule 4.

"Same file + same adapter version = same result. Re-uploading a duplicate (matching
content_sha256) is detected and reported, not re-ingested" (§3.1) — enforced at the schema
level too (report_file's `unique (tenant_id, content_sha256)`), but checked here first so the
caller can report a clean "already uploaded" message instead of a raw constraint violation.

"Overlapping uploads are expected. Deduplicate on natural key + content hash; never
double-count" (§6 rule 4) — the natural key is `(marketplace, order_ref, line_ref,
invoice_ref)` per sales_line's own comment (§1.3): whichever of those three a source actually
supplies.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from data_foundation.types import ParsedRow

NaturalKey = tuple[str, str | None, str | None, str | None]


def is_duplicate_file(content_sha256: str, existing_hashes: Iterable[str]) -> bool:
    return content_sha256 in set(existing_hashes)


def natural_key(marketplace: str, row: ParsedRow) -> NaturalKey | None:
    """None when the row supplies none of the three natural-key fields at all — such a row
    can't be deduplicated by key (only by content_sha256 at the file level), never treated as
    an automatic match against every other keyless row."""
    order_ref = row.canonical_fields.get("order_ref")
    line_ref = row.canonical_fields.get("line_ref")
    invoice_ref = row.canonical_fields.get("invoice_ref")
    assert order_ref is None or isinstance(order_ref, str)
    assert line_ref is None or isinstance(line_ref, str)
    assert invoice_ref is None or isinstance(invoice_ref, str)
    if order_ref is None and line_ref is None and invoice_ref is None:
        return None
    return (marketplace, order_ref, line_ref, invoice_ref)


def find_natural_key_duplicates(
    marketplace: str, rows: Sequence[ParsedRow], existing_keys: Iterable[NaturalKey]
) -> list[int]:
    """Returns the `source_row_number`s of rows whose natural key already exists (e.g. from an
    earlier, overlapping-period upload) — these are candidates the caller must not
    double-count, not necessarily rows to reject outright (a corrected re-upload of the same
    order is expected, per §3.1 rule 4's superseding-run model)."""
    existing = set(existing_keys)
    duplicates: list[int] = []
    for row in rows:
        key = natural_key(marketplace, row)
        if key is not None and key in existing:
            duplicates.append(row.source_row_number)
    return duplicates
