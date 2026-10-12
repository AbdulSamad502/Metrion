"""The PI structural worst-case bounds are maxima ONLY under stated assumptions and only for a bounded candidate_cap (verification finding, 2026-10-10)."""

from __future__ import annotations

import pytest

from product_intelligence import timing
from product_intelligence.discovery.discovery_run import DEFAULT_CANDIDATE_CAP, MAX_CANDIDATE_CAP, _select_candidates_with_cap


def test_the_documented_figures_for_the_default_cap():
    assert DEFAULT_CANDIDATE_CAP == 30
    assert timing.discover_worst_case_seconds() == 1850  # a bound for cap 30 under the module's assumptions: NOT a maximum for arbitrary caps
    assert timing.supplier_lookup_worst_case_seconds() == 30


def test_the_bound_grows_with_the_cap_and_is_refused_where_it_cannot_be_established():
    assert timing.discover_worst_case_seconds(1) < timing.discover_worst_case_seconds(30) < timing.discover_worst_case_seconds(100)
    for bad in (0, -1, -100):
        with pytest.raises(ValueError, match="does not bound the work"):
            timing.discover_worst_case_seconds(bad)


def test_a_non_positive_cap_keeps_nothing():
    rows = [{"source_diversity": i, "engagement_signal": {"status": "AVAILABLE"} if i % 2 == 0 else {}} for i in range(40)]
    for cap in (0, -1, -100):
        assert _select_candidates_with_cap(rows, candidate_cap=cap) == []
    assert len(_select_candidates_with_cap(rows, candidate_cap=1)) == 1


def test_the_bound_exists_and_is_finite_for_every_accepted_cap():
    assert MAX_CANDIDATE_CAP == 100
    values = [timing.discover_worst_case_seconds(c) for c in range(1, MAX_CANDIDATE_CAP + 1)]
    assert all(isinstance(v, int) and v > 0 for v in values) and values == sorted(values)
