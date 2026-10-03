"""constraints.resolve_constraint: C13 / AC5 / AC24 / E5 / E16 / E17.

The module never supplies a value of its own, never falls back silently, and treats missing
configuration as a block - these tests pin each of those, with the boundaries exact."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from slim_cmo.constraints import (
    ConstraintUnavailable,
    ResolvedConstraint,
    UnavailableReason,
    resolve_constraint,
)
from slim_cmo.types import ConstraintRowKind, CountRule, Marketplace, OutputType

from .factories import NOW, constraint

AMZ, FK, MS = Marketplace.AMAZON, Marketplace.FLIPKART, Marketplace.MEESHO
V, T = ConstraintRowKind.VERIFIED, ConstraintRowKind.TEST_FIXTURE


def resolve(rows, *, mp=AMZ, category=None, output=OutputType.TITLE_SET, max_age=30, now=NOW, **kw):
    return resolve_constraint(rows, marketplace=mp, category=category, output_type=output, now=now, max_age_days=max_age, **kw)


def reason(result) -> UnavailableReason:
    assert isinstance(result, ConstraintUnavailable), result
    return result.reason


class TestConfigurationFirst:
    @pytest.mark.parametrize("bad", [None, 0, -5, True, 3.0, "30"])
    def test_staleness_policy_must_be_a_positive_integer_else_config_missing(self, bad):
        out = resolve([constraint()], max_age=bad)
        assert reason(out) is UnavailableReason.CONFIG_MISSING
        assert out.missing == ("format_constraint_max_age_days",)

    def test_a_fresh_valid_row_does_not_rescue_missing_config(self):
        assert reason(resolve([constraint(verified_at=NOW)], max_age=None)) is UnavailableReason.CONFIG_MISSING

    def test_naive_clock_is_a_programming_error(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            resolve([constraint()], now=datetime(2026, 10, 3, 12, 0))


class TestRowVisibility:
    def test_no_rows_at_all(self):
        assert reason(resolve([])) is UnavailableReason.NO_ROW

    def test_rows_for_other_marketplaces_are_invisible(self):
        assert reason(resolve([constraint(FK), constraint(MS)], mp=AMZ)) is UnavailableReason.NO_ROW

    def test_test_fixtures_are_invisible_to_the_production_path(self):
        """E17: only a TEST_FIXTURE exists -> treated as missing, never used."""
        out = resolve([constraint(row_kind=T)])
        assert reason(out) is UnavailableReason.NO_VERIFIED_ROW

    def test_production_default_accepts_verified_only(self):
        verified = constraint(row_kind=V, version=1)
        fixture = constraint(row_kind=T, version=99)  # a higher version must not win
        out = resolve([fixture, verified])
        assert isinstance(out, ResolvedConstraint) and out.row is verified

    def test_tests_can_explicitly_accept_fixtures(self):
        fixture = constraint(row_kind=T)
        out = resolve([fixture], accepted_row_kinds=frozenset({T}))
        assert isinstance(out, ResolvedConstraint) and out.row is fixture

    def test_verified_beats_fixture_at_equal_version_when_both_accepted(self):
        verified, fixture = constraint(row_kind=V, version=4), constraint(row_kind=T, version=4)
        out = resolve([fixture, verified], accepted_row_kinds=frozenset({V, T}))
        assert out.row is verified  # type: ignore[union-attr]


class TestCategoryAndVersion:
    def test_category_specific_row_beats_marketplace_default(self):
        default = constraint(version=9)
        specific = constraint(category="Drinkware", version=1)
        out = resolve([default, specific], category="drinkware")
        assert out.row is specific  # type: ignore[union-attr]

    def test_category_match_ignores_case_and_spacing(self):
        specific = constraint(category="Home  &  Kitchen")
        assert resolve([specific], category="  home & kitchen ").row is specific  # type: ignore[union-attr]

    def test_no_category_requested_ignores_category_rows(self):
        default, specific = constraint(), constraint(category="Drinkware", version=50)
        assert resolve([default, specific], category=None).row is default  # type: ignore[union-attr]

    def test_unmatched_category_falls_back_to_the_default(self):
        default, other = constraint(), constraint(category="Toys")
        assert resolve([default, other], category="Drinkware").row is default  # type: ignore[union-attr]

    def test_only_other_category_rows_and_no_default_is_no_row(self):
        assert reason(resolve([constraint(category="Toys")], category="Drinkware")) is UnavailableReason.NO_ROW
        assert reason(resolve([constraint(category="Toys")], category=None)) is UnavailableReason.NO_ROW

    def test_highest_version_wins_within_the_group(self):
        v1, v2, v3 = constraint(version=1), constraint(version=3), constraint(version=2)
        assert resolve([v1, v2, v3]).row is v2  # type: ignore[union-attr]

    def test_a_stale_specific_row_blocks_rather_than_falling_back_to_a_fresh_default(self):
        """The more specific rule is the one that applies to the product; a fresh generic rule
        must not quietly stand in for a stale specific one."""
        stale_specific = constraint(category="Drinkware", verified_at=NOW - timedelta(days=90))
        fresh_default = constraint(verified_at=NOW)
        assert reason(resolve([stale_specific, fresh_default], category="Drinkware")) is UnavailableReason.STALE

    def test_a_newer_version_with_an_older_verified_at_still_wins(self):
        """Version is the ordering; verified_at is only the staleness check."""
        old_date_new_version = constraint(version=5, verified_at=NOW - timedelta(days=20))
        new_date_old_version = constraint(version=4, verified_at=NOW)
        assert resolve([new_date_old_version, old_date_new_version]).row is old_date_new_version  # type: ignore[union-attr]


class TestStaleness:
    def test_age_exactly_at_the_limit_is_still_valid(self):
        row = constraint(verified_at=NOW - timedelta(days=30))
        assert isinstance(resolve([row], max_age=30), ResolvedConstraint)

    def test_one_second_past_the_limit_is_stale(self):
        row = constraint(verified_at=NOW - timedelta(days=30, seconds=1))
        assert reason(resolve([row], max_age=30)) is UnavailableReason.STALE

    def test_age_zero_is_valid(self):
        assert isinstance(resolve([constraint(verified_at=NOW)]), ResolvedConstraint)

    def test_future_dated_row_is_blocked(self):
        row = constraint(verified_at=NOW + timedelta(seconds=1))
        assert reason(resolve([row])) is UnavailableReason.FUTURE_VERIFIED_AT

    def test_naive_verified_at_is_an_invalid_row(self):
        row = constraint(verified_at=datetime(2026, 10, 2, 12, 0))
        assert reason(resolve([row])) is UnavailableReason.INVALID_ROW

    def test_comparison_is_timezone_correct(self):
        ist = timezone(timedelta(hours=5, minutes=30))
        # 2026-09-03 17:30 IST == 2026-09-03 12:00 UTC == exactly 30 days before NOW
        row = constraint(verified_at=datetime(2026, 9, 3, 17, 30, tzinfo=ist))
        assert isinstance(resolve([row], max_age=30), ResolvedConstraint)
        assert reason(resolve([row], max_age=29)) is UnavailableReason.STALE

    def test_staleness_uses_the_chosen_row_not_an_older_one(self):
        newest_but_stale = constraint(version=2, verified_at=NOW - timedelta(days=60))
        older_but_fresh = constraint(version=1, verified_at=NOW)
        assert reason(resolve([older_but_fresh, newest_but_stale])) is UnavailableReason.STALE


class TestRequiredAndUnverifiedLimits:
    def test_title_set_needs_the_option_count(self):
        out = resolve([constraint(title_option_count=None)], output=OutputType.TITLE_SET)
        assert reason(out) is UnavailableReason.MISSING_REQUIRED_LIMIT and out.missing == ("title_option_count",)

    def test_unstated_title_length_is_unverified_not_blocking(self):
        out = resolve([constraint(title_max_chars=None)], output=OutputType.TITLE_SET)
        assert isinstance(out, ResolvedConstraint) and out.unverified_limits == ("title_max_chars",)

    def test_copy_and_bullets_need_the_bullet_count(self):
        for output in (OutputType.LISTING_COPY, OutputType.BULLETS):
            out = resolve([constraint(bullet_count=None)], output=output)
            assert reason(out) is UnavailableReason.MISSING_REQUIRED_LIMIT and out.missing == ("bullet_count",)

    def test_listing_copy_reports_every_unstated_validating_limit(self):
        row = constraint(bullet_max_chars=None, description_max_chars=None, keywords_max_count=None, keywords_max_chars=None)
        out = resolve([row], output=OutputType.LISTING_COPY)
        assert isinstance(out, ResolvedConstraint)
        assert set(out.unverified_limits) == {"bullet_max_chars", "description_max_chars", "keywords_max_count", "keywords_max_chars"}

    def test_fully_stated_row_reports_nothing_unverified(self):
        assert resolve([constraint()], output=OutputType.LISTING_COPY).unverified_limits == ()  # type: ignore[union-attr]

    def test_description_and_keywords_need_no_hard_limit(self):
        row = constraint(description_max_chars=None, keywords_max_count=None, keywords_max_chars=None)
        assert isinstance(resolve([row], output=OutputType.DESCRIPTION), ResolvedConstraint)
        assert isinstance(resolve([row], output=OutputType.KEYWORDS), ResolvedConstraint)

    def test_backend_terms_need_the_byte_cap_and_are_amazon_only(self):
        assert reason(resolve([constraint(AMZ, backend_terms_max_bytes=None)], output=OutputType.BACKEND_TERMS)) is UnavailableReason.MISSING_REQUIRED_LIMIT
        assert isinstance(resolve([constraint(AMZ)], output=OutputType.BACKEND_TERMS), ResolvedConstraint)
        assert reason(resolve([constraint(FK)], mp=FK, output=OutputType.BACKEND_TERMS)) is UnavailableReason.UNSUPPORTED_COMBINATION

    @pytest.mark.parametrize("output", [OutputType.HASHTAGS, OutputType.CATALOG_ANSWER, OutputType.TREND_REPORT])
    def test_artefacts_not_bound_to_a_constraint_refuse_to_resolve_one(self, output):
        with pytest.raises(ValueError, match="not bound"):
            resolve([constraint()], output=output)


class TestCountingRuleMustBeVerified:
    """The UTF-16 count in the code is a conservative FALLBACK, not a verified marketplace rule:
    until a row states how the marketplace counts characters, production generation is blocked."""

    @pytest.mark.parametrize("output", [OutputType.TITLE_SET, OutputType.LISTING_COPY, OutputType.DESCRIPTION, OutputType.BULLETS, OutputType.KEYWORDS])
    def test_an_unverified_counting_rule_blocks_every_character_limited_artefact(self, output):
        out = resolve([constraint(count_rule=None)], output=output)
        assert reason(out) is UnavailableReason.COUNTING_RULE_UNVERIFIED and out.missing == ("count_rule",)

    def test_backend_terms_are_exempt_because_their_cap_is_bytes(self):
        assert isinstance(resolve([constraint(AMZ, count_rule=None)], output=OutputType.BACKEND_TERMS), ResolvedConstraint)

    @pytest.mark.parametrize("rule", list(CountRule))
    def test_either_supported_rule_resolves(self, rule):
        out = resolve([constraint(count_rule=rule)])
        assert isinstance(out, ResolvedConstraint) and out.row.count_rule is rule

    def test_a_stale_row_is_reported_stale_before_its_counting_rule_is_examined(self):
        out = resolve([constraint(count_rule=None, verified_at=NOW - timedelta(days=90))])
        assert reason(out) is UnavailableReason.STALE

    def test_the_rule_is_checked_on_the_chosen_row_not_an_older_one(self):
        unverified_newest = constraint(version=2, count_rule=None)
        verified_older = constraint(version=1, count_rule=CountRule.UTF16_CODE_UNITS)
        assert reason(resolve([verified_older, unverified_newest])) is UnavailableReason.COUNTING_RULE_UNVERIFIED


class TestCitationAndHashtags:
    def test_cite_carries_what_a_seller_needs_to_judge_currency(self):
        row = constraint(version=7)
        cite = row.cite()
        assert cite["version"] == 7 and cite["source_url"].startswith("https://") and cite["verified_at"].startswith("2026-10-02")
        assert cite["format_constraint_ref"] == str(row.id)

    @pytest.mark.parametrize("flag,allowed", [(None, False), (False, False), (True, True)])
    def test_only_an_explicit_true_permits_hashtags_in_a_listing(self, flag, allowed):
        assert constraint(hashtags_supported=flag).hashtags_in_listing_allowed is allowed


class TestDeterminism:
    def test_row_order_never_changes_the_answer(self):
        rows = [constraint(version=v) for v in (3, 1, 2, 5, 4)]
        a = resolve(rows).row
        b = resolve(list(reversed(rows))).row
        assert a is b and a.version == 5  # type: ignore[union-attr]

    def test_resolution_is_pure(self):
        rows = [constraint()]
        assert resolve(rows).row is resolve(rows).row  # type: ignore[union-attr]
