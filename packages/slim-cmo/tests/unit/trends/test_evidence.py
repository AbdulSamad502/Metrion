"""trends.evidence: independence, syndication collapse, recency and corroboration (C14, AC28).

Thresholds in these tests are (fresh 7d, recent 30d, moderate >=2, strong >=4) - TEST values.
Every boundary is exercised on both sides, and the "several mentions from one source are one
source" rule is attacked from several directions."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo.trends import evidence as ev
from slim_cmo.trends.evidence import Corroboration as C
from slim_cmo.trends.evidence import RecencyClass as R
from slim_cmo.trends.sources import SourceType

from .helpers import NOW, T, days, item


class TestThresholds:
    def test_valid(self):
        assert T.fresh_window_days == 7

    @pytest.mark.parametrize(
        "kw",
        [
            dict(fresh_window_days=0), dict(recent_window_days=0), dict(fresh_window_days=31, recent_window_days=30),
            dict(moderate_min_independent_sources=1), dict(strong_min_independent_sources=2),
            dict(fresh_window_days=True), dict(recent_window_days=3.5),
        ],
    )
    def test_invalid_scales_are_refused(self, kw):
        base = dict(fresh_window_days=7, recent_window_days=30, moderate_min_independent_sources=2, strong_min_independent_sources=4)
        with pytest.raises(ValueError):
            ev.Thresholds(**{**base, **kw})

    def test_equal_windows_are_permitted(self):
        ev.Thresholds(10, 10, 2, 3)


class TestRecencyBoundaries:
    def cls(self, age):
        return ev.classify_recency(NOW - age, NOW, T)

    def test_inclusive_fresh_boundary(self):
        assert self.cls(days(7)).recency is R.FRESH
        assert self.cls(days(7, seconds=1)).recency is R.RECENT

    def test_inclusive_recent_boundary(self):
        assert self.cls(days(30)).recency is R.RECENT
        assert self.cls(days(30, seconds=1)).recency is R.OLDER

    def test_just_published_is_fresh(self):
        assert self.cls(timedelta(0)).recency is R.FRESH

    def test_far_past_is_older(self):
        assert self.cls(days(3650)).recency is R.OLDER

    def test_no_date_is_unknown_and_retrieval_date_is_never_substituted(self):
        out = ev.classify_recency(None, NOW, T)
        assert (out.recency, out.future_date) == (R.DATE_UNKNOWN, False)

    def test_a_publication_date_after_retrieval_is_unknown_and_flagged_never_fresh(self):
        out = ev.classify_recency(NOW + timedelta(seconds=1), NOW, T)
        assert (out.recency, out.future_date) == (R.DATE_UNKNOWN, True)

    def test_naive_datetimes_are_programming_errors(self):
        with pytest.raises(ValueError):
            ev.classify_recency(datetime(2026, 10, 1), NOW, T)
        with pytest.raises(ValueError):
            ev.classify_recency(NOW, datetime(2026, 10, 3), T)

    def test_timezone_aware_comparison(self):
        ist = timezone_ist()
        published = datetime(2026, 9, 26, 17, 30, tzinfo=ist)  # == 2026-09-26 12:00 UTC == exactly 7 days before NOW
        assert ev.classify_recency(published, NOW, T).recency is R.FRESH

    @given(st.integers(0, 4000), st.integers(0, 86399))
    @settings(max_examples=300, deadline=None)
    def test_class_is_monotonic_in_age(self, d, secs):
        order = [R.FRESH, R.RECENT, R.OLDER]
        a = ev.classify_recency(NOW - timedelta(days=d, seconds=secs), NOW, T).recency
        b = ev.classify_recency(NOW - timedelta(days=d + 1, seconds=secs), NOW, T).recency
        assert order.index(a) <= order.index(b)


def timezone_ist():
    from datetime import timezone

    return timezone(timedelta(hours=5, minutes=30))


class TestCorroborationLevel:
    @pytest.mark.parametrize("recency", list(R))
    def test_one_source_is_always_single_source(self, recency):
        assert ev.corroboration_level(1, recency, T) is C.SINGLE_SOURCE

    @pytest.mark.parametrize(
        "n,recency,expected",
        [
            (2, R.FRESH, C.MODERATE), (3, R.FRESH, C.MODERATE), (4, R.FRESH, C.STRONG), (9, R.FRESH, C.STRONG),
            (2, R.RECENT, C.MODERATE), (4, R.RECENT, C.STRONG),
            # OLDER: one level down, floored at WEAK for 2+ sources
            (2, R.OLDER, C.WEAK), (3, R.OLDER, C.WEAK), (4, R.OLDER, C.MODERATE), (9, R.OLDER, C.MODERATE),
            # all undated: capped at WEAK
            (2, R.DATE_UNKNOWN, C.WEAK), (4, R.DATE_UNKNOWN, C.WEAK), (50, R.DATE_UNKNOWN, C.WEAK),
        ],
    )
    def test_table(self, n, recency, expected):
        assert ev.corroboration_level(n, recency, T) is expected

    def test_weak_band_exists_when_the_thresholds_leave_room(self):
        wide = ev.Thresholds(7, 30, 3, 5)
        assert ev.corroboration_level(2, R.FRESH, wide) is C.WEAK
        assert ev.corroboration_level(3, R.FRESH, wide) is C.MODERATE
        assert ev.corroboration_level(5, R.FRESH, wide) is C.STRONG

    def test_a_downgrade_never_produces_single_source_for_multiple_sources(self):
        for n in range(2, 12):
            assert ev.corroboration_level(n, R.OLDER, T) is not C.SINGLE_SOURCE

    @pytest.mark.parametrize("n", [0, -1, True, 2.0, None, "3"])
    def test_zero_or_invalid_counts_are_errors(self, n):
        with pytest.raises(ValueError):
            ev.corroboration_level(n, R.FRESH, T)  # type: ignore[arg-type]

    @given(st.integers(2, 40), st.sampled_from(list(R)))
    @settings(max_examples=300, deadline=None)
    def test_more_sources_never_lowers_corroboration(self, n, recency):
        rank = {C.SINGLE_SOURCE: 0, C.WEAK: 1, C.MODERATE: 2, C.STRONG: 3}
        assert rank[ev.corroboration_level(n + 1, recency, T)] >= rank[ev.corroboration_level(n, recency, T)]

    @given(st.integers(1, 40))
    @settings(max_examples=100, deadline=None)
    def test_fresher_evidence_never_lowers_corroboration(self, n):
        rank = {C.SINGLE_SOURCE: 0, C.WEAK: 1, C.MODERATE: 2, C.STRONG: 3}
        levels = [rank[ev.corroboration_level(n, r, T)] for r in (R.FRESH, R.RECENT, R.OLDER, R.DATE_UNKNOWN)]
        assert levels == sorted(levels, reverse=True)  # FRESH >= RECENT >= OLDER >= DATE_UNKNOWN


class TestCollapseSyndicated:
    def test_same_story_on_different_domains_is_one_item_earliest_wins(self):
        a = item("https://one.com/s", title="Platform Fee Update", age=days(3))
        b = item("https://two.com/s", title="platform fee update!", age=days(2))
        c = item("https://three.com/s", title="Platform  Fee  Update", age=days(5))  # earliest published
        reps, folded = ev.collapse_syndicated([a, b, c])
        assert [r.url for r in reps] == ["https://three.com/s"]
        assert folded == {"https://one.com/s": "https://three.com/s", "https://two.com/s": "https://three.com/s"}

    def test_a_dated_copy_beats_an_undated_one(self):
        dated, undated = item("https://b.com/x", title="T Story", age=days(20)), item("https://a.com/x", title="T Story")
        assert ev.collapse_syndicated([undated, dated])[0][0].url == "https://b.com/x"

    def test_all_undated_picks_deterministically_by_url(self):
        a, b = item("https://b.com/x", title="Same"), item("https://a.com/x", title="Same")
        assert ev.collapse_syndicated([a, b])[0][0].url == "https://a.com/x"
        assert ev.collapse_syndicated([b, a])[0][0].url == "https://a.com/x"

    def test_different_titles_are_not_collapsed(self):
        reps, folded = ev.collapse_syndicated([item("https://a.com/1", title="Alpha news"), item("https://b.com/1", title="Beta news")])
        assert len(reps) == 2 and folded == {}

    def test_untitled_items_are_never_collapsed(self):
        reps, _ = ev.collapse_syndicated([item("https://a.com/1"), item("https://b.com/1"), item("https://c.com/1", title="  !!  ")])
        assert len(reps) == 3

    def test_the_same_url_twice_is_one_item_not_a_syndicated_copy_of_itself(self):
        reps, folded = ev.collapse_syndicated([item("https://a.com/1", title="X Y"), item("https://a.com/1", title="X Y")])
        assert len(reps) == 1 and folded == {}

    def test_input_order_is_irrelevant(self):
        items = [item(f"https://d{i}.com/s", title="One Story", age=days(i)) for i in range(6)]
        expected = ev.collapse_syndicated(items)
        for seed in range(5):
            shuffled = items[:]
            random.Random(seed).shuffle(shuffled)
            assert ev.collapse_syndicated(shuffled) == expected


class TestEvaluateEvidence:
    def test_ten_articles_on_one_domain_are_one_independent_source(self):
        items = [item(f"https://blog.example.com/p{i}", title=f"Post {i}", age=days(1)) for i in range(10)]
        e = ev.evaluate_evidence(items, T)
        assert (e.mention_count, e.independent_source_count) == (10, 1)
        assert e.corroboration is C.SINGLE_SOURCE  # mention_count never feeds strength

    def test_repeats_do_not_raise_strength(self):
        base = [item("https://a.com/1", title="A1", age=days(1)), item("https://b.com/1", title="B1", age=days(1))]
        spam = base + [item(f"https://a.com/x{i}", title=f"A spam {i}", age=days(1)) for i in range(20)]
        assert ev.evaluate_evidence(spam, T).corroboration is ev.evaluate_evidence(base, T).corroboration is C.MODERATE
        assert ev.evaluate_evidence(spam, T).independent_source_count == 2

    def test_syndicated_wire_story_across_three_domains_plus_one_original_is_two_sources(self):
        """T30: ten articles from one domain + a syndicated copy on two other domains."""
        wire = [item(f"https://{d}.com/wire", title="Fee Change Announced", age=days(2 + i)) for i, d in enumerate(("x", "y", "z"))]
        own = [item(f"https://home.com/a{i}", title=f"Home piece {i}", age=days(1)) for i in range(10)]
        e = ev.evaluate_evidence(wire + own, T)
        assert e.mention_count == 13
        assert e.collapsed_duplicates == 2
        assert e.independent_source_count == 2  # one for the wire story, one for home.com
        assert e.corroboration is C.MODERATE

    def test_independent_domains_each_count(self):
        items = [item(f"https://site{i}.com/p", title=f"Story {i}", age=days(1)) for i in range(4)]
        e = ev.evaluate_evidence(items, T)
        assert e.independent_source_count == 4 and e.corroboration is C.STRONG

    def test_subdomains_of_one_site_do_not_count_separately(self):
        items = [item(f"https://{sub}.example.com/p", title=f"T {sub}", age=days(1)) for sub in ("www", "blog", "news", "m")]
        assert ev.evaluate_evidence(items, T).independent_source_count == 1

    def test_videos_count_by_channel(self):
        items = [item(f"https://youtu.be/{i}", kind=SourceType.VIDEO, channel_id="UC1", title=f"V{i}", age=days(1)) for i in range(5)]
        items.append(item("https://youtu.be/z", kind=SourceType.VIDEO, channel_id="UC2", title="Vz", age=days(1)))
        assert ev.evaluate_evidence(items, T).independent_source_count == 2

    def test_uncitable_items_are_dropped_and_counted(self):
        items = [item("https://a.com/1", title="A", age=days(1)), item("not a url", title="B"), item("ftp://x.com", title="C")]
        e = ev.evaluate_evidence(items, T)
        assert (e.mention_count, e.uncitable_dropped, e.independent_source_count) == (1, 2, 1)

    def test_no_citable_evidence_has_no_corroboration_and_is_stale(self):
        e = ev.evaluate_evidence([item("junk")], T)
        assert e.corroboration is None and e.is_stale and not e.has_citable_evidence and e.independent_source_count == 0
        assert ev.evaluate_evidence([], T).corroboration is None

    def test_all_undated_is_date_unknown_capped_weak_and_stale(self):
        items = [item(f"https://s{i}.com/p", title=f"S{i}") for i in range(5)]
        e = ev.evaluate_evidence(items, T)
        assert e.recency is R.DATE_UNKNOWN and e.corroboration is C.WEAK and e.is_stale
        assert e.freshest_published_at is None and e.oldest_published_at is None

    def test_one_dated_fresh_source_among_undated_gives_fresh_not_capped(self):
        items = [item("https://a.com/1", title="A", age=days(2))] + [item(f"https://s{i}.com/p", title=f"S{i}") for i in range(3)]
        e = ev.evaluate_evidence(items, T)
        assert e.recency is R.FRESH and not e.is_stale and e.corroboration is C.STRONG

    def test_older_evidence_is_stale_and_downgraded(self):
        items = [item(f"https://s{i}.com/p", title=f"S{i}", age=days(90)) for i in range(4)]
        e = ev.evaluate_evidence(items, T)
        assert e.recency is R.OLDER and e.is_stale and e.corroboration is C.MODERATE  # STRONG -> MODERATE

    def test_freshest_and_oldest_dates_come_from_representatives(self):
        items = [item("https://a.com/1", title="A", age=days(2)), item("https://b.com/1", title="B", age=days(20)), item("https://c.com/1", title="C", age=days(90))]
        e = ev.evaluate_evidence(items, T)
        assert e.freshest_published_at == NOW - days(2) and e.oldest_published_at == NOW - days(90)
        assert e.recency is R.FRESH

    def test_a_collapsed_copy_does_not_lend_its_recency_to_the_story(self):
        """The republished copy is newer, but the story is as old as its earliest publication."""
        original = item("https://a.com/s", title="Old Story", age=days(60))
        republished = item("https://b.com/s", title="OLD STORY", age=days(1))
        e = ev.evaluate_evidence([original, republished], T)
        assert e.independent_source_count == 1 and e.recency is R.OLDER and e.freshest_published_at == NOW - days(60)

    def test_future_dates_are_flagged_per_item_and_never_fresh(self):
        e = ev.evaluate_evidence([item("https://a.com/1", title="A", published=NOW + days(2))], T)
        assert e.recency is R.DATE_UNKNOWN and e.items[0].future_date and e.is_stale

    def test_per_item_trail_records_what_collapsed_into_what(self):
        a, b = item("https://a.com/s", title="Same", age=days(5)), item("https://b.com/s", title="Same", age=days(3))
        e = ev.evaluate_evidence([a, b], T)
        by_url = {i.url: i for i in e.items}
        assert by_url["https://b.com/s"].collapsed_into == "https://a.com/s" and by_url["https://a.com/s"].collapsed_into is None
        assert by_url["https://a.com/s"].independence_key == "web:a.com"

    def test_naive_item_dates_are_programming_errors(self):
        with pytest.raises(ValueError):
            ev.evaluate_evidence([item("https://a.com/1", title="A", published=datetime(2026, 10, 1))], T)

    def test_independence_keys_are_sorted_and_unique(self):
        items = [item(f"https://{d}.com/p", title=f"T{d}", age=days(1)) for d in "cab"]
        assert ev.evaluate_evidence(items, T).independence_keys == ("web:a.com", "web:b.com", "web:c.com")

    @given(
        st.lists(
            st.tuples(st.sampled_from(["a", "b", "c", "d"]), st.sampled_from(["x", "y", "z", ""]), st.one_of(st.none(), st.integers(0, 120))),
            max_size=14,
        ),
        st.randoms(use_true_random=False),
    )
    @settings(max_examples=200, deadline=None)
    def test_invariants_and_order_independence(self, specs, rng):
        items = [
            item(f"https://{dom}.com/{i}", title=(f"story {t}" if t else None), age=(days(a) if a is not None else None))
            for i, (dom, t, a) in enumerate(specs)
        ]
        e = ev.evaluate_evidence(items, T)
        assert e.independent_source_count <= len({s[0] for s in specs}) if specs else e.independent_source_count == 0
        assert e.independent_source_count <= e.mention_count == len(items)
        assert e.collapsed_duplicates + len(e.representatives) <= e.mention_count
        shuffled = items[:]
        rng.shuffle(shuffled)
        again = ev.evaluate_evidence(shuffled, T)
        assert (again.independent_source_count, again.recency, again.corroboration, again.independence_keys) == (
            e.independent_source_count, e.recency, e.corroboration, e.independence_keys)
