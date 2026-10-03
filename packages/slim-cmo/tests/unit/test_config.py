"""config: fail-closed loaders. Every problem is named at once; nothing is ever defaulted."""

from __future__ import annotations

import copy

import pytest

from slim_cmo import config as cfg
from slim_cmo.config import ConfigMissing, GenerationConfig, TrendConfig

from .factories import VALID_TREND_VALUES, trend_values


class TestGenerationConfig:
    def test_valid(self):
        out = cfg.load_generation_config({"format_constraint_max_age_days": 30, "internal_retry_bound": 2})
        assert out == GenerationConfig(30, 2)

    def test_zero_retries_is_an_explicit_legitimate_choice(self):
        out = cfg.load_generation_config({"format_constraint_max_age_days": 1, "internal_retry_bound": 0})
        assert isinstance(out, GenerationConfig) and out.internal_retry_bound == 0

    def test_empty_names_every_missing_key_at_once(self):
        out = cfg.load_generation_config({})
        assert isinstance(out, ConfigMissing)
        assert out.code == "CONFIG_MISSING"
        assert set(out.missing) == {"format_constraint_max_age_days", "internal_retry_bound"}

    def test_explicit_null_counts_as_missing(self):
        out = cfg.load_generation_config({"format_constraint_max_age_days": None, "internal_retry_bound": 1})
        assert isinstance(out, ConfigMissing) and out.missing == ("format_constraint_max_age_days",)

    @pytest.mark.parametrize("bad", [0, -1, True, False, 1.0, 2.5, "30", [], {}])
    def test_max_age_must_be_a_positive_integer(self, bad):
        out = cfg.load_generation_config({"format_constraint_max_age_days": bad, "internal_retry_bound": 1})
        assert isinstance(out, ConfigMissing)
        assert [k for k, _ in out.invalid] == ["format_constraint_max_age_days"]

    @pytest.mark.parametrize("bad", [-1, True, 1.0, "1"])
    def test_retry_bound_must_be_a_non_negative_integer(self, bad):
        out = cfg.load_generation_config({"format_constraint_max_age_days": 5, "internal_retry_bound": bad})
        assert isinstance(out, ConfigMissing) and [k for k, _ in out.invalid] == ["internal_retry_bound"]


class TestTrendConfig:
    def test_valid_roundtrips_and_snapshots(self):
        out = cfg.load_trend_config(trend_values())
        assert isinstance(out, TrendConfig)
        snap = out.snapshot()
        assert snap["fresh_window_days"] == 7 and snap["section_priority"][0] == "NICHE"
        assert snap["official_marketplace_domains"] == [] and snap["tactic_risk_pattern_set_ref"] is None

    def test_every_required_key_is_individually_required(self):
        for key in cfg.TREND_REQUIRED_KEYS:
            values = trend_values()
            del values[key]
            out = cfg.load_trend_config(values)
            assert isinstance(out, ConfigMissing), f"{key} should be required"
            assert key in out.missing

    def test_empty_config_lists_all_required_keys_not_just_the_first(self):
        out = cfg.load_trend_config({})
        assert isinstance(out, ConfigMissing)
        assert set(out.missing) == set(cfg.TREND_REQUIRED_KEYS)

    def test_the_optional_keys_are_the_only_ones_that_may_be_absent(self):
        assert set(cfg.TREND_OPTIONAL_KEYS) == {
            "tactic_risk_pattern_set_ref", "official_marketplace_domains", "niche_stopwords_extra", "niche_stopwords_exclude",
        }
        out = cfg.load_trend_config(trend_values())
        assert isinstance(out, TrendConfig)
        assert out.tactic_risk_pattern_set_ref is None  # fail-safe: no pattern set => UNASSESSED downstream
        assert out.official_marketplace_domains == frozenset()  # fail-safe: nothing is ever labelled official

    @pytest.mark.parametrize("key", [k for k in cfg.TREND_REQUIRED_KEYS if k not in ("section_query_budgets", "section_priority")])
    @pytest.mark.parametrize("bad", [True, 1.5, "3", 0, -2])
    def test_integer_keys_reject_bools_floats_strings_and_non_positives(self, key, bad):
        out = cfg.load_trend_config(trend_values(**{key: bad}))
        assert isinstance(out, ConfigMissing)
        assert key in [k for k, _ in out.invalid] or key in out.missing

    def test_moderate_threshold_must_be_at_least_two(self):
        out = cfg.load_trend_config(trend_values(moderate_min_independent_sources=1))
        assert isinstance(out, ConfigMissing) and "moderate_min_independent_sources" in [k for k, _ in out.invalid]

    def test_strong_must_exceed_moderate(self):
        out = cfg.load_trend_config(trend_values(moderate_min_independent_sources=4, strong_min_independent_sources=4))
        assert isinstance(out, ConfigMissing)
        assert "strong_min_independent_sources" in [k for k, _ in out.invalid]

    def test_fresh_window_cannot_exceed_recent_window(self):
        out = cfg.load_trend_config(trend_values(fresh_window_days=31, recent_window_days=30))
        assert isinstance(out, ConfigMissing) and "fresh_window_days" in [k for k, _ in out.invalid]
        equal = cfg.load_trend_config(trend_values(fresh_window_days=30, recent_window_days=30))
        assert isinstance(equal, TrendConfig)

    def test_section_budgets_must_sum_to_at_most_the_report_cap(self):
        budgets = {"NICHE": 10, "MARKET_NEWS": 10, "REPORTED_TACTICS": 10, "NEW_PRODUCTS_BUZZ": 10, "ADJACENT": 10}
        out = cfg.load_trend_config(trend_values(section_query_budgets=budgets, max_queries_per_report=49))
        assert isinstance(out, ConfigMissing) and "section_query_budgets" in [k for k, _ in out.invalid]
        ok = cfg.load_trend_config(trend_values(section_query_budgets=budgets, max_queries_per_report=50))
        assert isinstance(ok, TrendConfig)

    def test_every_section_needs_an_explicit_budget(self):
        budgets = {"NICHE": 3, "MARKET_NEWS": 3}
        out = cfg.load_trend_config(trend_values(section_query_budgets=budgets))
        assert isinstance(out, ConfigMissing)

    def test_zero_budget_for_a_section_is_allowed_but_negative_is_not(self):
        base = dict(VALID_TREND_VALUES["section_query_budgets"])
        assert isinstance(cfg.load_trend_config(trend_values(section_query_budgets={**base, "ADJACENT": 0})), TrendConfig)
        assert isinstance(cfg.load_trend_config(trend_values(section_query_budgets={**base, "ADJACENT": -1})), ConfigMissing)

    @pytest.mark.parametrize("not_a_mapping", [[1, 2, 3], "NICHE=3", 7, ["NICHE"]])
    def test_budgets_must_be_an_object(self, not_a_mapping):
        out = cfg.load_trend_config(trend_values(section_query_budgets=not_a_mapping))
        assert isinstance(out, ConfigMissing) and "section_query_budgets" in [k for k, _ in out.invalid]

    def test_unknown_section_in_budgets_is_rejected(self):
        base = dict(VALID_TREND_VALUES["section_query_budgets"])
        out = cfg.load_trend_config(trend_values(section_query_budgets={**base, "GOSSIP": 1}))
        assert isinstance(out, ConfigMissing)

    @pytest.mark.parametrize(
        "priority",
        [
            ["NICHE"],
            ["NICHE", "NICHE", "MARKET_NEWS", "ADJACENT", "REPORTED_TACTICS"],
            ["NICHE", "MARKET_NEWS", "NEW_PRODUCTS_BUZZ", "REPORTED_TACTICS", "GOSSIP"],
            "NICHE",
            [1, 2, 3, 4, 5],
        ],
    )
    def test_priority_must_be_a_complete_permutation(self, priority):
        assert isinstance(cfg.load_trend_config(trend_values(section_priority=priority)), ConfigMissing)

    def test_official_domains_are_normalised_and_validated(self):
        ok = cfg.load_trend_config(trend_values(official_marketplace_domains=[" Amazon.IN ", "flipkart.com."]))
        assert isinstance(ok, TrendConfig) and ok.official_marketplace_domains == frozenset({"amazon.in", "flipkart.com"})
        for bad in (["https://amazon.in"], ["amazon"], ["a b.com"], [""], "amazon.in", [5]):
            assert isinstance(cfg.load_trend_config(trend_values(official_marketplace_domains=bad)), ConfigMissing), bad

    def test_pattern_set_ref_must_be_a_non_empty_string_when_given(self):
        assert isinstance(cfg.load_trend_config(trend_values(tactic_risk_pattern_set_ref="risk-v1")), TrendConfig)
        for bad in ("", "   ", 5, ["x"]):
            assert isinstance(cfg.load_trend_config(trend_values(tactic_risk_pattern_set_ref=bad)), ConfigMissing), bad

    def test_all_problems_are_reported_in_one_pass(self):
        values = trend_values(fresh_window_days=0, moderate_min_independent_sources=1, max_term_chars="x")
        del values["max_queries_per_report"]
        out = cfg.load_trend_config(values)
        assert isinstance(out, ConfigMissing)
        keys = set(out.missing) | {k for k, _ in out.invalid}
        assert {"max_queries_per_report", "fresh_window_days", "moderate_min_independent_sources", "max_term_chars"} <= keys
        assert "max_queries_per_report" in out.describe()

    def test_input_mapping_is_never_mutated(self):
        values = trend_values()
        before = copy.deepcopy(values)
        cfg.load_trend_config(values)
        assert values == before

    def test_loaded_budget_mapping_is_a_copy(self):
        values = trend_values()
        out = cfg.load_trend_config(values)
        assert isinstance(out, TrendConfig)
        values["section_query_budgets"]["NICHE"] = 999
        assert out.section_query_budgets["NICHE"] == 5
