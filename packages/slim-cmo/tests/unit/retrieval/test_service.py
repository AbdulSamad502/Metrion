"""7e: Market Signal Retrieval (CMO side) with fake providers, a fake slot counter and the real in-process cache."""

from __future__ import annotations

import dataclasses
import inspect
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from market_signals.cache import InProcessQueryCache
from market_signals.tavily_client import TavilySearchResult, TavilyUnavailable
from market_signals.youtube_client import YoutubeUnavailable, YoutubeVideo

from slim_cmo.retrieval.service import (
    CEILING_REASON, QueryOutcome, RetrievalService, SectionStatus,
)
from slim_cmo.trends.queries import EgressViolation, Provider, build_plan
from slim_cmo.trends.sources import SourceType
from slim_cmo.types import Marketplace as M
from slim_cmo.types import TrendSection as S

from ..factories import trend_config
from ..trends.test_queries import LAUNCH

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
TERMS = ("steel water bottle", "yoga mat")
CFG = trend_config(**LAUNCH)


class FakeTavily:
    def __init__(self, fail_on=None, exc=TavilyUnavailable("down"), empty=False):
        self.calls, self.fail_on, self.exc, self.empty = [], fail_on or (lambda q: False), exc, empty

    def search(self, query, *, include_images=False, max_results=10, topic=None, days=None, country=None):
        self.calls.append({"query": query, "include_images": include_images, "max_results": max_results, "topic": topic, "days": days, "country": country})
        if self.fail_on(query):
            raise self.exc
        if self.empty:
            return []
        return [
            TavilySearchResult(f"https://news{n}.example.in/{abs(hash(query)) % 999}", f"Title {n}", f"content {n}", 0.5, "Thu, 01 Oct 2026 07:00:00 GMT" if n == 0 else None, NOW)
            for n in range(2)
        ]


class FakeYoutube:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def search_videos(self, query, *, max_results=10, region_code=None, order=None, published_after=None):
        self.calls.append({"query": query, "max_results": max_results, "region_code": region_code, "order": order, "published_after": published_after})
        if self.fail:
            raise YoutubeUnavailable("quota")
        return [
            YoutubeVideo("vid1", "Dated video", "Chan", 1200, 3, "th", NOW - timedelta(days=3), (), NOW, channel_id="UCabc"),
            YoutubeVideo("vid2", "Undated video", "Chan2", None, None, "th", NOW, (), NOW, channel_id=None),  # client fell back to retrieved_at
        ]


class FakeSlots:
    def __init__(self, ceiling_after=None, boom=False):
        self.taken, self.ceiling_after, self.boom = [], ceiling_after, boom

    def take_slot(self, provider, ceiling):
        if self.boom:
            raise RuntimeError("db down")
        self.taken.append((provider, ceiling))
        return self.ceiling_after is None or len(self.taken) <= self.ceiling_after


def build(tavily=None, youtube=None, slots=None, cache=None, throttled=None):
    @contextmanager
    def throttle(source):
        if throttled is not None:
            throttled.append(source)
        yield

    return RetrievalService(
        tavily=tavily or FakeTavily(), youtube=youtube or FakeYoutube(), cache=cache if cache is not None else InProcessQueryCache(),
        slots=slots or FakeSlots(), clock=lambda: NOW, throttle=throttle,
    )


def plan(terms=TERMS, **kw):
    return build_plan(config=CFG, sections=tuple(S), confirmed_terms=terms, marketplaces=(M.AMAZON, M.FLIPKART, M.MEESHO))


def run(svc, p=None, terms=TERMS, config=CFG):
    return svc.run(p or plan(), config=config, confirmed_terms=terms)


# ------------------------------------------------------------------------------ happy path and accounting
def test_full_report_makes_seven_tavily_and_three_youtube_calls_with_the_cmo_options_and_takes_ten_slots():
    t, y, s = FakeTavily(), FakeYoutube(), FakeSlots()
    r = run(build(t, y, s))
    assert len(t.calls) == 7 and len(y.calls) == 3
    assert all(c["topic"] == "news" and c["days"] == 30 and c["country"] == "india" and c["max_results"] == 5 and c["include_images"] is False for c in t.calls)
    assert all(c["region_code"] == "IN" and c["max_results"] == 5 and c["order"] is None for c in y.calls)
    assert all(c["published_after"] == NOW - timedelta(days=30) for c in y.calls)
    assert s.taken == [(p.provider.value, 20) for p in plan().queries]
    assert r.accounting["provider_calls"] == {"TAVILY": 7, "YOUTUBE": 3} and r.accounting["cache_hits"] == 0 and r.accounting["planned"] == 10
    assert all(sec.status is SectionStatus.COMPLETE for sec in r.sections) and len(r.sections) == 5


def test_the_accounting_note_does_not_claim_to_cover_product_intelligence():
    note = run(build()).accounting["note"]
    assert "CMO searches only" in note and "Product Intelligence" in note


def test_every_provider_call_runs_inside_the_shared_throttle_for_that_provider():
    seen: list[str] = []
    run(build(throttled=seen))
    assert sorted(seen) == ["tavily"] * 7 + ["youtube"] * 3


def test_items_are_parsed_with_dates_channel_ids_and_unknown_dates_stay_unknown():
    r = run(build())
    niche = r.section(S.NICHE)
    web = [i for i in niche.items if i.source_type is SourceType.WEB]
    vid = [i for i in niche.items if i.source_type is SourceType.VIDEO]
    assert web[0].published_at == datetime(2026, 10, 1, 7, tzinfo=UTC) and web[0].published_raw == "Thu, 01 Oct 2026 07:00:00 GMT"
    assert web[1].published_at is None and web[1].published_raw is None
    assert vid[0].published_at == NOW - timedelta(days=3) and vid[0].channel_id == "UCabc" and vid[0].view_count == 1200
    assert vid[1].published_at is None  # the client's retrieval-date fallback is NOT a publication date
    assert vid[0].url == "https://www.youtube.com/watch?v=vid1"
    si = vid[0].to_source_item()
    assert si.channel_id == "UCabc" and si.source_type is SourceType.VIDEO


# ------------------------------------------------------------------------------ caching
def test_a_second_run_is_served_entirely_from_cache_with_no_calls_and_no_slots():
    cache, t, y, s = InProcessQueryCache(), FakeTavily(), FakeYoutube(), FakeSlots()
    first = run(build(t, y, s, cache))
    s.taken.clear()
    t.calls.clear(), y.calls.clear()
    again = run(build(t, y, s, cache))
    assert t.calls == [] and y.calls == [] and s.taken == []
    assert again.accounting["cache_hits"] == 10 and all(q.outcome is QueryOutcome.CACHE_HIT for q in again.queries)
    assert [(i.url, i.published_at, i.channel_id) for sec in again.sections for i in sec.items] == [(i.url, i.published_at, i.channel_id) for sec in first.sections for i in sec.items]


def test_the_cache_still_hits_just_before_the_ttl_and_misses_exactly_at_it():
    cache, t = InProcessQueryCache(), FakeTavily()
    run(build(t, cache=cache))
    for delta, expected_calls in ((timedelta(hours=23, minutes=59), 0), (timedelta(hours=24), 7)):
        t.calls.clear()
        run(RetrievalService(tavily=t, youtube=FakeYoutube(), cache=InProcessQueryCache() if False else cache, slots=FakeSlots(), clock=lambda d=delta: NOW + d, throttle=lambda s: _null()))
        assert len(t.calls) == expected_calls


def test_the_cache_expires_after_the_configured_ttl():
    cache, t = InProcessQueryCache(), FakeTavily()
    run(build(t, cache=cache))
    later = RetrievalService(tavily=t, youtube=FakeYoutube(), cache=cache, slots=FakeSlots(), clock=lambda: NOW + timedelta(hours=24), throttle=lambda s: _null())
    t.calls.clear()
    run(later)
    assert len(t.calls) == 7  # exactly 24h later the entries are gone


@contextmanager
def _null():
    yield


def test_cache_keys_include_the_exact_provider_options_so_different_options_never_share_an_entry():
    cache, t = InProcessQueryCache(), FakeTavily()
    run(build(t, cache=cache))
    t.calls.clear()
    other = trend_config(**{**LAUNCH, "max_results_per_query": 4})
    svc = build(t, cache=cache)
    svc.run(build_plan(config=other, sections=tuple(S), confirmed_terms=TERMS, marketplaces=tuple(M)), config=other, confirmed_terms=TERMS)
    assert len(t.calls) == 7  # nothing from the 5-results run was reused for the 4-results run


def test_cmo_cache_entries_live_in_their_own_namespace_and_never_collide_with_product_intelligence():
    cache = InProcessQueryCache()
    p = plan()
    q = p.queries[0]
    cache.put("tavily", f"search::{q.text}", {"results": ["PI ENTRY"], "images": []}, ttl_hours=24, now=NOW)  # what PI would hold
    svc = build(FakeTavily(), cache=cache)
    cache.put("tavily", svc._cache_key(q), "POISONED-BY-ANOTHER-NAMESPACE", ttl_hours=24, now=NOW)  # even under CMO's exact key, PI's source name
    cache.put("youtube", svc._cache_key(p.queries[1]), "POISONED", ttl_hours=24, now=NOW)
    t = FakeTavily()
    run(build(t, cache=cache), p)
    assert len(t.calls) == 7  # the PI entry was never mistaken for a CMO result
    assert cache.get("tavily", f"search::{q.text}", now=NOW) == {"results": ["PI ENTRY"], "images": []}  # and was not overwritten


def test_term_bearing_cache_entries_are_per_tenant_and_term_free_ones_are_shared():
    """A query carrying a seller's niche term is keyed by tenant scope, so one seller can never learn (through a cache hit) that another
    researched the same term; term-free queries are identical for everyone and are shared. Scope is the only owner marker in a key."""
    cache = InProcessQueryCache()
    p = plan()
    svc = build(cache=cache)
    svc.run(p, config=CFG, confirmed_terms=TERMS, cache_scope="tenant-A")
    keys = [k for (_s, k) in cache._store]  # noqa: SLF001 - white-box: the keys ARE the privacy surface
    assert len(keys) == 10
    planned = {q.text.lower(): q for q in p.queries}
    for k in keys:
        template_id, text, options, owner = k.split("|")
        q = planned[text]
        assert template_id.upper().endswith("_V1") and "@" not in k
        assert owner == ("tenant-a" if q.term else "")  # normalised key: owner only on term-bearing queries
    t2, y2 = FakeTavily(), FakeYoutube()
    build(t2, y2, cache=cache).run(p, config=CFG, confirmed_terms=TERMS, cache_scope="tenant-B")
    called = {c["query"] for c in t2.calls} | {c["query"] for c in y2.calls}
    assert called == {q.text for q in p.queries if q.term}  # tenant B re-asked only the term-bearing ones; the shared ones were cache hits


def test_an_empty_provider_answer_is_cached_as_a_real_empty_result():
    cache, t = InProcessQueryCache(), FakeTavily(empty=True)
    run(build(t, cache=cache))
    t.calls.clear()
    r = run(build(t, cache=cache))
    assert t.calls == [] and r.section(S.MARKET_NEWS).status is SectionStatus.COMPLETE and r.section(S.MARKET_NEWS).items == ()


# ------------------------------------------------------------------------------ daily ceiling
def test_when_the_daily_ceiling_is_reached_remaining_queries_are_refused_without_calls_and_sections_degrade():
    t, y, s = FakeTavily(), FakeYoutube(), FakeSlots(ceiling_after=4)
    r = run(build(t, y, s))
    assert len(t.calls) + len(y.calls) == 4 and len(s.taken) == 5  # the 5th request was refused; later ones never reached the database
    assert r.accounting["refused_daily_ceiling"] == 6 and r.accounting["provider_calls"] == {"TAVILY": 3, "YOUTUBE": 1}
    niche, news, tactics = r.section(S.NICHE), r.section(S.MARKET_NEWS), r.section(S.REPORTED_TACTICS)
    assert niche.status is SectionStatus.COMPLETE and news.status is SectionStatus.COMPLETE
    assert tactics.status is SectionStatus.UNAVAILABLE and tactics.reason == CEILING_REASON
    assert r.section(S.ADJACENT).status is SectionStatus.UNAVAILABLE


def test_cache_hits_are_still_served_after_the_ceiling_is_reached():
    cache, t, y = InProcessQueryCache(), FakeTavily(), FakeYoutube()
    run(build(t, y, FakeSlots(), cache))
    r = run(build(t, y, FakeSlots(ceiling_after=0), cache))
    assert r.accounting["cache_hits"] == 10 and r.accounting["refused_daily_ceiling"] == 0


def test_the_ceiling_value_passed_to_the_counter_is_the_configured_one():
    s = FakeSlots()
    run(build(slots=s), config=trend_config(**{**LAUNCH, "provider_daily_search_ceiling": 7}), p=build_plan(config=trend_config(**{**LAUNCH, "provider_daily_search_ceiling": 7}), sections=tuple(S), confirmed_terms=TERMS, marketplaces=tuple(M)))
    assert {c for _, c in s.taken} == {7}


def test_a_counter_failure_fails_closed_no_provider_call_is_made():
    t, y = FakeTavily(), FakeYoutube()
    r = run(build(t, y, FakeSlots(boom=True)))
    assert t.calls == [] and y.calls == []
    assert r.accounting["counter_errors"] == 10 and all(sec.status is SectionStatus.UNAVAILABLE for sec in r.sections)


# ------------------------------------------------------------------------------ partial failures
def test_one_failing_query_degrades_only_its_section_and_the_slot_stays_counted():
    t = FakeTavily(fail_on=lambda q: q.endswith("India e-commerce news") and q.startswith("steel"))
    s = FakeSlots()
    r = run(build(t, FakeYoutube(), s))
    niche = r.section(S.NICHE)
    assert niche.status is SectionStatus.PARTIAL and "Tavily was unavailable" in niche.reason and len(niche.items) == 2  # the YouTube half survived
    assert r.section(S.MARKET_NEWS).status is SectionStatus.COMPLETE
    assert len(s.taken) == 10 and r.accounting["failed"] == 1 and r.accounting["provider_calls"]["TAVILY"] == 7


def test_a_provider_that_is_down_makes_its_sections_unavailable_and_the_others_carry_on():
    r = run(build(FakeTavily(), FakeYoutube(fail=True)))
    assert r.section(S.NEW_PRODUCTS_BUZZ).status is SectionStatus.UNAVAILABLE
    assert r.section(S.MARKET_NEWS).status is SectionStatus.COMPLETE and r.section(S.NICHE).status is SectionStatus.PARTIAL


def test_failures_are_not_cached_so_the_next_run_retries():
    cache = InProcessQueryCache()
    run(build(FakeTavily(fail_on=lambda q: True), FakeYoutube(), cache=cache))
    t = FakeTavily()
    run(build(t, FakeYoutube(), cache=cache))
    assert len(t.calls) == 7


def test_an_unexpected_exception_is_contained_to_that_query():
    t = FakeTavily(fail_on=lambda q: "policy" in q, exc=KeyError("boom"))
    r = run(build(t))
    assert r.accounting["failed"] == 1 and r.section(S.MARKET_NEWS).status is SectionStatus.PARTIAL
    assert "KeyError" in r.section(S.MARKET_NEWS).reason and "boom" not in r.section(S.MARKET_NEWS).reason  # no raw detail leaks


# ------------------------------------------------------------------------------ privacy at the choke point
def test_a_plan_with_an_unconfirmed_term_is_refused_before_any_call_or_slot():
    t, y, s = FakeTavily(), FakeYoutube(), FakeSlots()
    with pytest.raises(EgressViolation):
        build(t, y, s).run(plan(), config=CFG, confirmed_terms=("steel water bottle",))  # 'yoga mat' not confirmed
    assert t.calls == [] and y.calls == [] and s.taken == []


def test_a_tampered_query_is_refused_before_any_call_or_slot():
    p = plan()
    bad = dataclasses.replace(p.queries[0], text=p.queries[0].text + " Rs 499 sku-42")
    tampered = dataclasses.replace(p, queries=(bad, *p.queries[1:]))
    t, s = FakeTavily(), FakeSlots()
    with pytest.raises(EgressViolation):
        build(t, slots=s).run(tampered, config=CFG, confirmed_terms=TERMS)
    assert t.calls == [] and s.taken == []


def test_a_plan_whose_queries_change_between_the_whole_plan_check_and_the_call_is_still_refused():
    """The guard runs again immediately before each provider call: a plan that yields clean queries once and a tampered
    one afterwards (a mutated or lazily-built sequence) must not get through."""
    p = plan()
    bad = dataclasses.replace(p.queries[0], text=p.queries[0].text + " Rs 499")

    class Shifty:
        def __init__(self):
            self.n = 0

        def __iter__(self):
            self.n += 1
            return iter(p.queries if self.n == 1 else (bad, *p.queries[1:]))

        def __len__(self):
            return len(p.queries)

    shifty = dataclasses.replace(p, queries=Shifty())  # type: ignore[arg-type]
    t, s = FakeTavily(), FakeSlots()
    with pytest.raises(EgressViolation):
        build(t, slots=s).run(shifty, config=CFG, confirmed_terms=TERMS)
    assert t.calls == [] and s.taken == []


def test_the_service_has_no_tenant_or_catalog_parameter_so_none_can_leak_into_a_request():
    params = set(inspect.signature(RetrievalService.run).parameters)
    assert params == {"self", "plan", "config", "confirmed_terms", "cache_scope"}  # cache_scope is an opaque cache-partition label, never part of a query
    assert not {"tenant_id", "titles", "notes", "catalog"} & set(inspect.signature(RetrievalService.__init__).parameters)


def test_every_string_that_reaches_a_provider_is_a_planned_query_text():
    t, y = FakeTavily(), FakeYoutube()
    run(build(t, y))
    sent = {c["query"] for c in t.calls} | {c["query"] for c in y.calls}
    assert sent == {q.text for q in plan().queries}


def test_no_confirmed_terms_still_researches_the_broader_sections_and_marks_the_rest_unavailable():
    t, y = FakeTavily(), FakeYoutube()
    p = plan(terms=())
    r = build(t, y).run(p, config=CFG, confirmed_terms=())
    assert r.section(S.NICHE).status is SectionStatus.UNAVAILABLE and "niche" in r.section(S.NICHE).reason.lower()
    assert r.section(S.MARKET_NEWS).status is SectionStatus.COMPLETE
    assert len(t.calls) + len(y.calls) == 6 and r.unresearched_terms == ()


def test_unresearched_terms_are_disclosed_in_the_result():
    terms = tuple(f"term {c}" for c in "abcdef")
    r = build().run(plan(terms=terms), config=CFG, confirmed_terms=terms)
    assert r.unresearched_terms == ("term e", "term f")
