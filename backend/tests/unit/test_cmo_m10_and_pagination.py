"""Written with the M10 / version-pagination work (see the docs for whether these have been run). Pure unit tests: stubs stand in for the database."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.ceo import cmo_market_chat as chat
from backend.services import cmo_market, cmo_perf_view

TODAY = date(2026, 11, 1)
TENANT = uuid.uuid4()


# ------------------------------------------------------------------------------------------------ M10: routing
@pytest.mark.parametrize(("text", "kind"), [
    ("Find opportunities for my products", "OPPORTUNITIES"), ("Show latest marketplace news", "NEWS"), ("What has changed on Amazon?", "CHANGED"),
    ("Which opportunities should I focus on?", "FOCUS"), ("How does this news affect my products?", "AFFECTS"), ("What should I do about this update?", "ACTION"),
])
def test_the_six_requests_are_recognised(text, kind):
    assert chat.classify(text) == kind


@pytest.mark.parametrize("text", ["latest news in ecommerce", "Amazon news", "Flipkart news today", "market news", "any updates?", "amazon update my listing", "show my listing", "hello", "x" * 400])
def test_the_existing_market_research_phrases_and_other_requests_are_left_alone(text):
    assert chat.classify(text) is None


# ------------------------------------------------------------------------------------------------ M10: the service
def _report():
    f = {"finding_id": "f1", "theme": "Amazon India updates return policy for steel bottles", "summary": "s", "news_kind": "POLICY", "independent_source_count": 1, "corroboration": "SINGLE_SOURCE",
         "sources": [{"url": "https://sell.amazon.in/a", "title": "t", "published_at": "2026-10-20T00:00:00", "retrieved_at": "2026-10-30T00:00:00", "source_class": "OFFICIAL_MARKETPLACE"}]}
    g = {**f, "finding_id": "f2", "theme": "Flipkart fee change for hoses", "sources": [{**f["sources"][0], "url": "https://seller.flipkart.com/b", "title": "Fee change"}]}
    return [{"id": "r1", "generatedAt": "2026-10-30T10:00:00+00:00", "sections": {"MARKET_NEWS": {"findings": [f, g]}}}]


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(cmo_market, "products", lambda t: [{"sku": "aqua", "name": "AquaNest steel bottle", "facts": ["steel"], "marketplaces": ["AMAZON"]}])
    monkeypatch.setattr(cmo_market.cmo_market_repo, "recent_reports", lambda t, n: _report())


def test_overview_filters_by_marketplace_and_counts_what_names_none(stubbed):
    all_ = cmo_market.overview(TENANT, today=TODAY)
    assert all_["state"] == "OK" and len(all_["news"]) == 2 and all_["aiCredits"] == 0 and all_["notes"]
    amazon = cmo_market.overview(TENANT, marketplace="AMAZON", today=TODAY)
    assert [n["marketplaces"] for n in amazon["news"]] == [["AMAZON"]]


def test_an_unknown_product_or_marketplace_is_refused(stubbed):
    with pytest.raises(cmo_market.MarketRefused) as e:
        cmo_market.overview(TENANT, sku="nope", today=TODAY)
    assert e.value.status == 404
    with pytest.raises(cmo_market.MarketRefused):
        cmo_market.overview(TENANT, marketplace="EBAY", today=TODAY)


def test_with_no_saved_report_the_service_says_so(monkeypatch):
    monkeypatch.setattr(cmo_market, "products", lambda t: [])
    monkeypatch.setattr(cmo_market.cmo_market_repo, "recent_reports", lambda t, n: [])
    o = cmo_market.overview(TENANT, today=TODAY)
    assert o["state"] == "NO_REPORT" and o["news"] == [] and o["opportunities"] == []


# ------------------------------------------------------------------------------------------------ M10: chat answers
class FakeSvc:
    MarketRefused = cmo_market.MarketRefused

    def __init__(self, ov):
        self.ov = ov

    def overview(self, tenant, *, marketplace=None, sku=None):
        return self.ov


def _ov(state="OK", news=None, opps=None):
    return {"state": state, "message": "old" if state == "STALE_REPORTS" else None, "latestReportAt": "2026-10-30", "reportCount": 1, "newsWithoutMarketplace": 0, "notes": ["n"], "news": news or [], "opportunities": opps or []}


def test_chat_with_no_report_returns_the_no_report_card_and_invents_nothing():
    text, card = chat._answer(TENANT, "NEWS", "Show latest marketplace news", None, None, FakeSvc({**_ov("NO_REPORT"), "message": "You have no saved market-trend report yet."}))
    assert card["view"] == "NO_REPORT" and card["news"] == [] and card["aiCredits"] == 0 and "no saved" in text


def test_chat_changed_on_a_marketplace_asks_one_question_when_none_is_named():
    text, card = chat._answer(TENANT, "CHANGED", "what changed", None, None, FakeSvc(_ov()))
    assert card["view"] == "CLARIFY" and [o["marketplace"] for o in card["options"]] == ["AMAZON", "FLIPKART", "MEESHO"]


def test_chat_news_and_affects_use_the_stored_item():
    item = {"id": "r1:f1", "headline": "Return policy", "publishedAt": "2026-10-20", "freshness": "FRESH", "sourceNote": "official", "impact": "A policy update.", "marketplaces": ["AMAZON"],
            "relevance": {"level": "HIGH", "reason": "It mentions steel.", "affects": [{"sku": "aqua"}]}}
    svc = FakeSvc(_ov(news=[item]))
    text, card = chat._answer(TENANT, "NEWS", "Show latest marketplace news", None, None, svc)
    assert card["view"] == "NEWS" and card["news"][0]["id"] == "r1:f1" and "Return policy" in text
    text, card = chat._answer(TENANT, "AFFECTS", "How does this news affect my products?", card, None, svc)
    assert card["view"] == "AFFECTS" and card["focusId"] == "r1:f1" and "may affect 1" in text
    text, card = chat._answer(TENANT, "ACTION", "What should I do about this update?", card, None, svc)
    assert card["view"] == "ACTION" and "A policy update." in text


def test_chat_focus_names_why_it_is_first_and_that_demand_is_unavailable():
    opp = {"title": "Steel bottle gifting", "relevance": {"level": "HIGH"}, "evidenceStrength": "MODERATE", "observed": {"freshness": "FRESH"}, "rankedBecause": "Ranked by those three, with no score or forecast."}
    text, card = chat._answer(TENANT, "FOCUS", "Which opportunities should I focus on?", None, None, FakeSvc(_ov(opps=[opp])))
    assert card["view"] == "FOCUS" and "Steel bottle gifting" in text and "UNAVAILABLE" in text


# ------------------------------------------------------------------------------------------------ version pagination (no page cap; stable order; only the requested page is analysed)
def _versions(n):
    return [{"id": f"v{i}", "number": i, "createdAt": f"2026-01-{(i % 28) + 1:02d}", "sourceText": "x", "changedSection": None} for i in range(1, n + 1)]


@pytest.fixture
def many(monkeypatch):
    monkeypatch.setattr(cmo_perf_view, "_products", lambda t: {("s", "AMAZON"): {"name": "S", "versions": _versions(130)}})
    monkeypatch.setattr(cmo_perf_view, "window_days", lambda t: (None, None))
    monkeypatch.setattr(cmo_perf_view, "_links", lambda t: {})
    monkeypatch.setattr(cmo_perf_view.repo, "golives", lambda t, s, m: [])


def test_a_page_of_versions_comes_with_the_total_and_whether_more_exist(many):
    p = cmo_perf_view.versions(TENANT, "s", "AMAZON", limit=25, offset=100)
    assert [v["number"] for v in p["versions"]] == list(range(101, 126)) and p["total"] == 130 and p["hasMore"] is True and p["order"] == "asc"
    last = cmo_perf_view.versions(TENANT, "s", "AMAZON", limit=25, offset=125)
    assert [v["number"] for v in last["versions"]] == [126, 127, 128, 129, 130] and last["hasMore"] is False


def test_newest_first_is_a_stable_reverse_and_no_limit_means_every_version(many):
    d = cmo_perf_view.versions(TENANT, "s", "AMAZON", limit=25, offset=0, order="desc")
    assert [v["number"] for v in d["versions"]][:3] == [130, 129, 128] and d["order"] == "desc"
    everything = cmo_perf_view.versions(TENANT, "s", "AMAZON")
    assert len(everything["versions"]) == 130 and everything["hasMore"] is False


def test_a_bad_order_is_refused(many):
    with pytest.raises(cmo_perf_view.PerformanceRefused):
        cmo_perf_view.versions(TENANT, "s", "AMAZON", order="sideways")
