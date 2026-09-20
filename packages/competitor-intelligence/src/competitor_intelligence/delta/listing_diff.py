"""Listing-change detection — compares seller-submitted-evidence listing fields (title,
description, bullets, observed_category) between two snapshots. Distinct from
`compute.py`'s price/availability delta: this is a content diff, not an arithmetic
comparison, and it never enters Brain 1 (there is no money here).

Deliberately computed on read rather than persisted as its own event table — Step 5 is
scoped to reuse existing plumbing (competitor_snapshot_field rows already hold both
snapshots' values), not add new architectural surface. Whether a listing change deserves
its own persisted alert stream is a decision for a future pass; for now it is comparable
history/diff data only, the same status as the diff itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from competitor_intelligence.types import Unavailable

LISTING_FIELDS: tuple[str, ...] = ("title", "description", "bullets", "observed_category")


@dataclass(frozen=True, slots=True)
class ListingFieldChange:
    field_name: str
    prior_value: Any
    current_value: Any


@dataclass(frozen=True, slots=True)
class ListingDiff:
    changed_fields: tuple[ListingFieldChange, ...]


def compute_listing_diff(
    prior_fields: Mapping[str, Any], current_fields: Mapping[str, Any]
) -> ListingDiff | Unavailable:
    """`prior_fields`/`current_fields` are field_name -> value maps, as produced by
    `competitor_snapshot_field_repo.get_fields` (or any equivalent). A field is "changed"
    when it is present with a non-null value on at least one side and the two values
    differ — a field absent/null on both sides is not a change (never fabricate a
    listing change from missing data)."""
    if not prior_fields and not current_fields:
        return Unavailable(reason="no listing fields recorded on either snapshot")

    changed: list[ListingFieldChange] = []
    for field_name in LISTING_FIELDS:
        prior_value = prior_fields.get(field_name)
        current_value = current_fields.get(field_name)
        if prior_value is None and current_value is None:
            continue
        if prior_value != current_value:
            changed.append(
                ListingFieldChange(field_name=field_name, prior_value=prior_value, current_value=current_value)
            )
    return ListingDiff(changed_fields=tuple(changed))
