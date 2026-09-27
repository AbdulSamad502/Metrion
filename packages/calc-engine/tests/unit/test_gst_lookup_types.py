"""L3 ("`source_url` and `retrieved_at` are mandatory. A result without both is discarded.")
proven structurally: `GstLookupResult` cannot be *constructed* without either field — not a
runtime validation error caught after the fact, a `TypeError` from the dataclass's own
generated `__init__` before any field is ever assigned.

Also covers L5 (every result carries the standing disclaimer by construction) and the
status-vocabulary guard in `__post_init__`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from calc_engine.gst_lookup.types import (
    GST_LOOKUP_DISCLAIMER,
    GstLookupNoMatch,
    GstLookupQuery,
    GstLookupResult,
)

_NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


def _base_kwargs() -> dict[str, object]:
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "query_text": "Cotton T-shirt",
        "source_url": "https://busy.in/gst-rates/stationery/",
        "retrieved_at": _NOW,
    }


def test_construction_succeeds_with_both_mandatory_fields() -> None:
    result = GstLookupResult(**_base_kwargs())
    assert result.source_url == "https://busy.in/gst-rates/stationery/"
    assert result.retrieved_at == _NOW


def test_l3_missing_source_url_is_structurally_impossible() -> None:
    kwargs = _base_kwargs()
    del kwargs["source_url"]
    with pytest.raises(TypeError):
        GstLookupResult(**kwargs)  # type: ignore[arg-type]


def test_l3_missing_retrieved_at_is_structurally_impossible() -> None:
    kwargs = _base_kwargs()
    del kwargs["retrieved_at"]
    with pytest.raises(TypeError):
        GstLookupResult(**kwargs)  # type: ignore[arg-type]


def test_l3_empty_source_url_rejected_at_construction_time() -> None:
    """Belt-and-suspenders: even a syntactically-present-but-empty `source_url` (which the
    dataclass's field typing alone cannot rule out — `""` is a valid `str`) is rejected by
    `__post_init__`, so an empty string can never masquerade as "provided" (L3's own
    "discarded" language)."""
    kwargs = _base_kwargs()
    kwargs["source_url"] = ""
    with pytest.raises(ValueError):
        GstLookupResult(**kwargs)


def test_l5_disclaimer_present_by_default() -> None:
    result = GstLookupResult(**_base_kwargs())
    assert result.disclaimer == GST_LOOKUP_DISCLAIMER
    assert "official GST guidance or a qualified tax professional" in result.disclaimer


def test_invalid_status_rejected() -> None:
    kwargs = _base_kwargs()
    kwargs["status"] = "NOT_A_REAL_STATUS"
    with pytest.raises(ValueError):
        GstLookupResult(**kwargs)


def test_gst_lookup_query_defaults_to_no_hsn_or_category() -> None:
    query = GstLookupQuery(product_title="Cotton T-shirt")
    assert query.sku is None
    assert query.hsn is None
    assert query.category is None


def test_gst_lookup_no_match_is_a_distinct_type_not_a_result() -> None:
    outcome = GstLookupNoMatch(query_text="Some obscure item")
    assert isinstance(outcome, GstLookupNoMatch)
    assert not isinstance(outcome, GstLookupResult)
    assert outcome.reason == "NO_RELIABLE_SOURCE_FOUND"
