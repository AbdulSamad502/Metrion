"""compute_listing_diff() — content diff between two snapshots' listing fields. Never
fabricates a change from missing data (both-sides-null is not a change)."""

from __future__ import annotations

from competitor_intelligence.delta.listing_diff import compute_listing_diff
from competitor_intelligence.types import Unavailable


def test_no_fields_on_either_side_is_unavailable() -> None:
    result = compute_listing_diff({}, {})
    assert isinstance(result, Unavailable)


def test_identical_title_is_not_a_change() -> None:
    result = compute_listing_diff({"title": "Wireless Mouse"}, {"title": "Wireless Mouse"})
    assert not isinstance(result, Unavailable)
    assert result.changed_fields == ()


def test_changed_title_is_reported() -> None:
    result = compute_listing_diff({"title": "Wireless Mouse"}, {"title": "Wireless Mouse Pro"})
    assert not isinstance(result, Unavailable)
    assert len(result.changed_fields) == 1
    change = result.changed_fields[0]
    assert change.field_name == "title"
    assert change.prior_value == "Wireless Mouse"
    assert change.current_value == "Wireless Mouse Pro"


def test_field_appearing_where_previously_absent_counts_as_change() -> None:
    result = compute_listing_diff({}, {"description": "New description"})
    assert not isinstance(result, Unavailable)
    assert result.changed_fields[0].field_name == "description"
    assert result.changed_fields[0].prior_value is None


def test_both_sides_missing_a_field_is_not_a_change() -> None:
    result = compute_listing_diff({"title": "X"}, {"title": "X"})
    assert not isinstance(result, Unavailable)
    assert not any(c.field_name == "observed_category" for c in result.changed_fields)


def test_multiple_changed_fields_all_reported() -> None:
    prior = {"title": "A", "bullets": ["one"], "observed_category": "Electronics"}
    current = {"title": "B", "bullets": ["one", "two"], "observed_category": "Electronics"}

    result = compute_listing_diff(prior, current)

    assert not isinstance(result, Unavailable)
    changed_names = {c.field_name for c in result.changed_fields}
    assert changed_names == {"title", "bullets"}
