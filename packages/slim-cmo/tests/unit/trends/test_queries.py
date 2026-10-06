"""7e: fixed templates, the outbound-query plan, the exact preview, and the egress guard (spec §6.8.3 rule 5, C15, AC30)."""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from slim_cmo.trends import queries as Q
from slim_cmo.trends.queries import EgressViolation, OutboundQuery, Provider, build_plan, validate_egress
from slim_cmo.trends.screening import screen_term
from slim_cmo.types import Marketplace as M
from slim_cmo.types import TrendSection as S

from ..factories import trend_config

LAUNCH = dict(
    max_queries_per_report=10,
    section_query_budgets={"NICHE": 2, "MARKET_NEWS": 2, "REPORTED_TACTICS": 2, "NEW_PRODUCTS_BUZZ": 2, "ADJACENT": 2},
    section_priority=["NICHE", "MARKET_NEWS", "REPORTED_TACTICS", "NEW_PRODUCTS_BUZZ", "ADJACENT"],
    max_results_per_query=5, news_window_days=30, provider_call_timeout_seconds=15, provider_cache_ttl_hours=24,
    provider_daily_search_ceiling=20, max_term_chars=40,
)
ALL = tuple(S)
TERMS = ("steel water bottle", "yoga mat")


def cfg(**kw):
    return trend_config(**{**LAUNCH, **kw})


def plan(terms=TERMS, sections=ALL, marketplaces=(M.AMAZON, M.FLIPKART, M.MEESHO), **kw):
    return build_plan(config=cfg(**kw), sections=sections, confirmed_terms=terms, marketplaces=marketplaces)


# ------------------------------------------------------------------------------ the launch plan
def test_launch_plan_is_ten_queries_two_per_section_in_the_configured_priority_order():
    p = plan()
    assert len(p.queries) == 10
    assert [q.section for q in p.queries] == [s for s in (S.NICHE, S.MARKET_NEWS, S.REPORTED_TACTICS, S.NEW_PRODUCTS_BUZZ, S.ADJACENT) for _ in (0, 1)]
    assert p.by_provider() == {"TAVILY": 7, "YOUTUBE": 3}  # niche 1+1, news 2, tactics 2, buzz 0+2, adjacent 2 -> T:1+2+2+2, Y:1+2
    assert p.unavailable == {} and p.skipped == ()


def test_the_provider_allocation_is_exactly_the_approved_one():
    got = {s: [Q.TEMPLATES[t].provider.value for t in ids] for s, ids in Q.SECTION_SLOTS.items()}
    assert got == {
        S.NICHE: ["TAVILY", "YOUTUBE"], S.MARKET_NEWS: ["TAVILY", "TAVILY"], S.REPORTED_TACTICS: ["TAVILY", "TAVILY"],
        S.NEW_PRODUCTS_BUZZ: ["YOUTUBE", "YOUTUBE"], S.ADJACENT: ["TAVILY", "TAVILY"],
    }


def test_exact_preview_shows_precisely_what_will_be_sent():
    p = plan(terms=("steel water bottle",), sections=(S.NICHE, S.MARKET_NEWS))
    assert p.preview() == [
        {"queryId": "NICHE:0", "section": "NICHE", "provider": "TAVILY", "templateId": "NICHE_NEWS_V1", "query": "steel water bottle India e-commerce news",
         "params": {"topic": "news", "days": 30, "country": "india", "max_results": 5}},
        {"queryId": "NICHE:1", "section": "NICHE", "provider": "YOUTUBE", "templateId": "NICHE_VIDEO_V1", "query": "steel water bottle India",
         "params": {"region_code": "IN", "published_within_days": 30, "max_results": 5}},
        {"queryId": "MARKET_NEWS:0", "section": "MARKET_NEWS", "provider": "TAVILY", "templateId": "MARKET_NEWS_POLICY_V1",
         "query": "Amazon India Flipkart Meesho seller policy and fee changes", "params": {"topic": "news", "days": 30, "country": "india", "max_results": 5}},
        {"queryId": "MARKET_NEWS:1", "section": "MARKET_NEWS", "provider": "TAVILY", "templateId": "MARKET_NEWS_PROGRAM_V1",
         "query": "Amazon India Flipkart Meesho seller programs and seasonal sales", "params": {"topic": "news", "days": 30, "country": "india", "max_results": 5}},
    ]


def test_marketplace_names_follow_the_sellers_selection_in_canonical_order():
    p = plan(sections=(S.MARKET_NEWS,), marketplaces=(M.MEESHO, M.AMAZON))
    assert p.queries[0].text == "Amazon India Meesho seller policy and fee changes"
    assert plan(sections=(S.MARKET_NEWS,), marketplaces=()).queries[0].text.startswith("Amazon India Flipkart Meesho")


# ------------------------------------------------------------------------------ terms
def test_one_confirmed_term_per_query_in_sorted_order_across_term_needing_sections():
    p = plan(terms=("yoga mat", "steel water bottle"))
    used = [(q.query_id, q.term) for q in p.queries if q.term]
    assert used == [("NICHE:0", "steel water bottle"), ("NICHE:1", "yoga mat"), ("ADJACENT:0", "steel water bottle"), ("ADJACENT:1", "yoga mat")]
    assert p.unresearched_terms == ()


def test_terms_beyond_the_available_queries_are_disclosed_as_unresearched():
    terms = tuple(f"term {c}" for c in "abcdef")
    p = plan(terms=terms)
    assert [q.term for q in p.queries if q.term] == ["term a", "term b", "term c", "term d"]
    assert p.unresearched_terms == ("term e", "term f")


def test_a_single_term_is_reused_across_the_slots_that_need_one():
    p = plan(terms=("only term",))
    assert {q.term for q in p.queries if q.term} == {"only term"} and p.unresearched_terms == ()


def test_no_confirmed_terms_makes_niche_and_adjacent_unavailable_but_the_broader_sections_still_plan_E19():
    p = plan(terms=())
    assert p.unavailable == {S.NICHE: Q.NO_NICHE_REASON, S.ADJACENT: Q.NO_NICHE_REASON}
    assert {q.section for q in p.queries} == {S.MARKET_NEWS, S.REPORTED_TACTICS, S.NEW_PRODUCTS_BUZZ}
    assert all(q.term is None for q in p.queries)


def test_term_free_sections_never_contain_a_term():
    for q in plan().queries:
        if q.section in (S.MARKET_NEWS, S.REPORTED_TACTICS, S.NEW_PRODUCTS_BUZZ):
            assert q.term is None and not any(t in q.text for t in TERMS)


@pytest.mark.parametrize("bad", ["me@example.com", "9876543210", "https://x.test", "27AAPFU0939F1ZV", "12345", "x" * 41, "", "  "])
def test_an_unsafe_term_that_somehow_reaches_the_planner_is_dropped_never_sent(bad):
    p = plan(terms=(bad, "safe term"))
    assert all(q.term in (None, "safe term") for q in p.queries)
    assert not any(bad.strip() and bad in q.text for q in p.queries)


def test_duplicate_and_case_variant_terms_collapse():
    p = plan(terms=("Yoga Mat", "yoga  mat", "YOGA MAT"))
    assert {q.term for q in p.queries if q.term} == {"yoga mat"}


# ------------------------------------------------------------------------------ budgets
def test_section_budgets_truncate_a_sections_slots_never_extend_them():
    p = plan(section_query_budgets={"NICHE": 1, "MARKET_NEWS": 2, "REPORTED_TACTICS": 0 + 1, "NEW_PRODUCTS_BUZZ": 2, "ADJACENT": 2}, max_queries_per_report=10)
    assert [q.query_id for q in p.queries if q.section is S.NICHE] == ["NICHE:0"]
    assert [(s.section, s.template_id, s.reason) for s in p.skipped] == [
        (S.NICHE, "NICHE_VIDEO_V1", "SECTION_BUDGET_EXHAUSTED"), (S.REPORTED_TACTICS, "TACTICS_RANKING_V1", "SECTION_BUDGET_EXHAUSTED"),
    ]
    bigger = plan(section_query_budgets={"NICHE": 5, "MARKET_NEWS": 5, "REPORTED_TACTICS": 5, "NEW_PRODUCTS_BUZZ": 5, "ADJACENT": 5}, max_queries_per_report=25)
    assert len(bigger.queries) == 10  # a larger budget does not invent queries


def test_the_report_cap_stops_lower_priority_sections_first():
    p = plan(section_priority=["ADJACENT", "NICHE", "MARKET_NEWS", "REPORTED_TACTICS", "NEW_PRODUCTS_BUZZ"])
    assert [q.section for q in p.queries][:2] == [S.ADJACENT, S.ADJACENT]  # priority drives order


def test_only_requested_sections_are_planned():
    p = plan(sections=(S.NEW_PRODUCTS_BUZZ,))
    assert {q.section for q in p.queries} == {S.NEW_PRODUCTS_BUZZ} and len(p.queries) == 2


def test_provider_options_come_from_configuration_only():
    p = plan(terms=("t one",), sections=(S.NICHE,), max_results_per_query=3, news_window_days=7)
    assert dict(p.queries[0].params) == {"topic": "news", "days": 7, "country": "india", "max_results": 3}
    assert dict(p.queries[1].params) == {"region_code": "IN", "published_within_days": 7, "max_results": 3}


# ------------------------------------------------------------------------------ privacy: the structural guarantee
SECRETS = ["AquaKeep Steel Bottle SKU-0042 Rs 499", "customer Ravi Kumar 9876543210", "my cost price is 120", "internal note: supplier Acme", "27AAPFU0939F1ZV"]


def test_nothing_but_template_text_marketplaces_and_confirmed_terms_appears_in_any_query():
    p = plan(terms=("steel water bottle",))
    allowed_words = set()
    for t in Q.TEMPLATES.values():
        allowed_words |= set(t.text.replace("{term}", "").replace("{marketplaces}", "").lower().split())
    for name in Q.MARKETPLACE_NAMES.values():
        allowed_words |= set(name.lower().split())
    allowed_words |= {"steel", "water", "bottle"}
    for q in p.queries:
        assert set(q.text.lower().split()) <= allowed_words, q.text
        for secret in SECRETS:
            assert secret.lower() not in q.text.lower()


def test_the_planner_has_no_parameter_through_which_catalog_data_or_notes_could_enter():
    import inspect

    assert list(inspect.signature(build_plan).parameters) == ["config", "sections", "confirmed_terms", "marketplaces"]
    assert [f.name for f in dataclasses.fields(OutboundQuery)] == ["query_id", "section", "provider", "template_id", "text", "term", "marketplaces", "params"]


def test_every_template_is_static_safe_text_with_only_the_two_placeholders():
    for t in Q.TEMPLATES.values():
        bare = t.text.replace("{term}", "x").replace("{marketplaces}", "y")
        assert "{" not in bare and "}" not in bare
        assert not any(ch.isdigit() for ch in t.text)  # no figures, years or ids in fixed text
        assert screen_term(bare, max_chars=400).ok
        assert t.id.endswith("_V1") and t.id in Q.SECTION_SLOTS[next(s for s, ids in Q.SECTION_SLOTS.items() if t.id in ids)]


# ------------------------------------------------------------------------------ the egress guard
def ok(p, terms=TERMS, **kw):
    validate_egress(p.queries, confirmed_terms=terms, config=cfg(**kw))


def tamper(q, **kw):
    return dataclasses.replace(q, **kw)


def test_a_freshly_built_plan_passes_the_guard():
    ok(plan())


def test_an_unconfirmed_suggested_or_rejected_term_is_refused():
    p = plan(terms=("steel water bottle", "yoga mat"))
    with pytest.raises(EgressViolation, match="not a confirmed niche term"):
        ok(p, terms=("steel water bottle",))  # 'yoga mat' was never confirmed (or was later rejected)


def test_extra_words_or_data_appended_to_a_query_are_refused():
    p = plan()
    for extra in (" Rs 499", " ravi@example.com", " SKU-0042", " 9876543210", "!"):
        q = tamper(p.queries[0], text=p.queries[0].text + extra)
        with pytest.raises(EgressViolation, match="not exactly the rendered template"):
            validate_egress([q], confirmed_terms=TERMS, config=cfg())


def test_a_hand_built_free_text_query_is_refused():
    q = OutboundQuery("X:0", S.NICHE, Provider.TAVILY, "NICHE_NEWS_V1", "the seller's whole sales report", "steel water bottle", (), dict(plan().queries[0].params))
    with pytest.raises(EgressViolation):
        validate_egress([q], confirmed_terms=TERMS, config=cfg())


def test_an_unknown_template_a_wrong_section_or_a_wrong_provider_is_refused():
    q = plan().queries[0]
    for bad, match in ((tamper(q, template_id="MADE_UP"), "unknown template"), (tamper(q, section=S.MARKET_NEWS), "not allowed for section"),
                       (tamper(q, provider=Provider.YOUTUBE), "provider does not match")):
        with pytest.raises(EgressViolation, match=match):
            validate_egress([bad], confirmed_terms=TERMS, config=cfg())


def test_a_term_on_a_term_free_template_or_marketplaces_on_a_marketplace_free_one_is_refused():
    news = next(q for q in plan().queries if q.section is S.MARKET_NEWS)
    niche = next(q for q in plan().queries if q.section is S.NICHE)
    with pytest.raises(EgressViolation, match="takes no term"):
        validate_egress([tamper(news, term="yoga mat")], confirmed_terms=TERMS, config=cfg())
    with pytest.raises(EgressViolation, match="takes no marketplace"):
        validate_egress([tamper(niche, marketplaces=(M.AMAZON,))], confirmed_terms=TERMS, config=cfg())


def test_marketplaces_must_be_enum_members_in_canonical_order():
    news = next(q for q in plan().queries if q.section is S.MARKET_NEWS)
    for bad in ((), ("Amazon India",), (M.MEESHO, M.AMAZON)):
        with pytest.raises(EgressViolation):
            validate_egress([tamper(news, marketplaces=bad)], confirmed_terms=TERMS, config=cfg())


def test_provider_options_other_than_the_permitted_set_are_refused():
    q = plan().queries[0]
    for params in ({**q.params, "include_raw_content": True}, {**q.params, "country": "us"}, {k: v for k, v in q.params.items() if k != "days"}, {**q.params, "max_results": 50}):
        with pytest.raises(EgressViolation, match="provider options"):
            validate_egress([tamper(q, params=params)], confirmed_terms=TERMS, config=cfg())


def test_a_term_that_fails_the_outbound_screen_is_refused_even_if_listed_as_confirmed():
    q = tamper(plan().queries[0], term="call 9876543210", text="call 9876543210 India e-commerce news")
    with pytest.raises(EgressViolation, match="outbound screen"):
        validate_egress([q], confirmed_terms=("call 9876543210",), config=cfg())


def test_budgets_are_enforced_by_the_guard_too():
    p = plan()
    with pytest.raises(EgressViolation, match="exceed its budget"):
        ok(p, section_query_budgets={"NICHE": 1, "MARKET_NEWS": 2, "REPORTED_TACTICS": 2, "NEW_PRODUCTS_BUZZ": 2, "ADJACENT": 2})
    with pytest.raises(EgressViolation, match="report budget"):
        ok(p, max_queries_per_report=9, section_query_budgets={"NICHE": 1, "MARKET_NEWS": 2, "REPORTED_TACTICS": 2, "NEW_PRODUCTS_BUZZ": 2, "ADJACENT": 2})


def test_duplicate_queries_are_refused():
    q = plan().queries[0]
    with pytest.raises(EgressViolation, match="duplicate"):
        validate_egress([q, q], confirmed_terms=TERMS, config=cfg())


def test_the_guard_reports_every_problem_at_once():
    q = plan().queries[0]
    with pytest.raises(EgressViolation) as err:
        validate_egress([tamper(q, text=q.text + "x", params={})], confirmed_terms=TERMS, config=cfg())
    assert len(err.value.reasons) >= 2


def test_changing_the_config_after_planning_invalidates_the_options_in_the_plan():
    p = plan()
    with pytest.raises(EgressViolation, match="provider options"):
        ok(p, max_results_per_query=4)


@pytest.mark.parametrize("ms", [c for r in (1, 2, 3) for c in itertools.combinations(M, r)])
def test_every_marketplace_combination_renders_and_validates(ms):
    p = plan(sections=(S.MARKET_NEWS, S.REPORTED_TACTICS), marketplaces=ms)
    ok(p)
    assert all(Q.MARKETPLACE_NAMES[m] in p.queries[0].text for m in ms)
