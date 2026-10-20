"""§6.12.1 — locked discovery budget defaults, as configuration, never hardcoded."""

from __future__ import annotations

from competitor_intelligence.discovery.budget import DiscoveryBudget


def test_defaults_match_locked_spec_values() -> None:
    budget = DiscoveryBudget()

    assert budget.max_discovery_queries_per_run == 20
    assert budget.max_raw_candidates == 50
    assert budget.max_analyzed_candidates == 20
    assert budget.max_recommended_candidates == 15
    assert budget.max_followup_searches_per_candidate == 3
    assert budget.discovery_run_timeout_seconds == 120
    assert budget.search_cache_ttl_hours == 24


def test_every_knob_is_overridable() -> None:
    budget = DiscoveryBudget(
        max_discovery_queries_per_run=1,
        max_raw_candidates=2,
        max_analyzed_candidates=3,
        max_recommended_candidates=4,
        max_followup_searches_per_candidate=5,
        discovery_run_timeout_seconds=6,
        search_cache_ttl_hours=7,
    )

    assert budget.max_discovery_queries_per_run == 1
    assert budget.max_raw_candidates == 2
    assert budget.max_analyzed_candidates == 3
    assert budget.max_recommended_candidates == 4
    assert budget.max_followup_searches_per_candidate == 5
    assert budget.discovery_run_timeout_seconds == 6
    assert budget.search_cache_ttl_hours == 7
