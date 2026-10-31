"""CMO 3.0 M10: market opportunities and marketplace news from saved reports. Pure rules; synthetic reports only. (Written with the feature; see the docs for whether it has been run.)"""

from __future__ import annotations

from datetime import date

from slim_cmo.market import intel

TODAY = date(2026, 11, 1)


def finding(fid="f1", theme="Amazon India updates return policy for steel bottles", published="2026-10-20T00:00:00", official=True, **kw):
    base = {"finding_id": fid, "theme": theme, "summary": "The returns window changes.", "news_kind": "POLICY", "independent_source_count": 1, "corroboration": "SINGLE_SOURCE", "limitation_note": "n",
            "sources": [{"url": f"https://sell.amazon.in/{fid}", "title": "Return policy", "published_at": published, "retrieved_at": "2026-10-30T00:00:00", "source_class": "OFFICIAL_MARKETPLACE" if official else "THIRD_PARTY"}]}
    base.update(kw)
    return base


def report(rid="r1", at="2026-10-30T10:00:00+00:00", **sections):
    return {"id": rid, "generatedAt": at, "sections": {k: {"findings": v} for k, v in sections.items()}}


def prods(marketplaces=("AMAZON",)):
    return intel.product_context([{"sku": "aqua", "name": "AquaNest steel bottle", "facts": ["steel"], "marketplaces": list(marketplaces)}])


def test_nothing_saved_means_no_items_and_a_plain_statement_never_invented_news():
    o = intel.overview([], prods(), TODAY)
    assert o["state"] == "NO_REPORT" and "invent" in o["message"].lower()
    assert o["news"] == [] and o["opportunities"] == []


def test_news_carries_headline_source_date_marketplace_freshness_impact_and_relevance():
    n = intel.news_items([report(MARKET_NEWS=[finding()])], prods(), TODAY)[0]
    assert n["headline"].startswith("Amazon India") and n["marketplaces"] == ["AMAZON"] and n["publishedAt"] == "2026-10-20" and n["freshness"] == "FRESH" and n["ageDays"] == 12
    assert n["sources"][0]["url"].startswith("https://") and n["officialSource"] is True and "official" in n["sourceNote"]
    assert n["relevance"]["level"] == "HIGH" and n["relevance"]["affects"][0]["sku"] == "aqua" and "policy" in n["impact"].lower()
    assert any(s["agent"] == "CMO" for s in n["recommendations"]) and n["recommendations"][0]["agent"] == "YOU"


def test_freshness_is_recomputed_from_todays_date_and_an_undated_item_is_never_fresh():
    assert intel.freshness("2026-10-25", TODAY)[0] == "FRESH"
    assert intel.freshness("2026-09-15", TODAY)[0] == "RECENT"
    assert intel.freshness("2026-01-01", TODAY)[0] == "STALE"
    assert intel.freshness(None, TODAY) == ("DATE_UNKNOWN", None)
    assert intel.freshness("2027-01-01", TODAY)[0] == "DATE_UNKNOWN"  # a future date is not believed
    old = intel.news_items([report(MARKET_NEWS=[finding(published="2026-01-01T00:00:00")])], prods(), TODAY)[0]
    assert old["isStale"] is True and any("old or undated" in s["text"] for s in old["recommendations"])
    undated = intel.news_items([report(MARKET_NEWS=[finding(published=None)])], prods(), TODAY)[0]
    assert undated["freshness"] == "DATE_UNKNOWN" and undated["publishedAt"] is None


def test_a_third_party_source_is_marked_unconfirmed():
    n = intel.news_items([report(MARKET_NEWS=[finding(official=False)])], prods(), TODAY)[0]
    assert n["officialSource"] is False and "unconfirmed" in n["sourceNote"]


def test_the_same_story_in_two_reports_is_shown_once_from_the_newest_report():
    a = report("r1", "2026-10-01T10:00:00+00:00", MARKET_NEWS=[finding("f1")])
    b = report("r2", "2026-10-30T10:00:00+00:00", MARKET_NEWS=[finding("f9", theme="Amazon India updates return policy for steel bottles")])
    items = intel.news_items([a, b], prods(), TODAY)
    assert len(items) == 1 and items[0]["reportId"] == "r2" and items[0]["seenInReports"] == 2
    shared = intel.news_items([report("r1", MARKET_NEWS=[finding("f1")]), report("r2", "2026-10-31T00:00:00+00:00", MARKET_NEWS=[finding("f1", theme="Completely different words here")])], prods(), TODAY)
    assert len(shared) == 1  # the same source address is the same story


def test_relevance_needs_shared_words_or_marketplaces_and_says_why():
    f = finding(theme="Flipkart changes commission for garden hoses", sources=[{"url": "https://news.example/x", "title": "News", "published_at": "2026-10-20T00:00:00", "retrieved_at": "2026-10-30T00:00:00", "source_class": "THIRD_PARTY"}])
    assert intel.relate(f, prods(("AMAZON",)))["level"] == "LOW"
    assert intel.relate(finding(theme="Flipkart announces a seller event", sources=[{"url": "https://news.example/x", "title": "News", "published_at": "2026-10-20T00:00:00", "retrieved_at": "2026-10-30T00:00:00", "source_class": "THIRD_PARTY"}]), prods(("FLIPKART",)))["level"] == "MEDIUM"
    assert intel.relate(f, [])["level"] == "NOT_ASSESSED"
    assert "steel" in intel.relate(finding(theme="Steel bottle demand note", sources=[{"url": "https://news.example/x", "title": "News", "published_at": "2026-10-20T00:00:00", "retrieved_at": "2026-10-30T00:00:00", "source_class": "THIRD_PARTY"}]), prods())["affects"][0]["sharedTerms"]


def test_opportunities_separate_what_was_reported_from_a_possible_explanation_and_never_claim_demand():
    adj = finding("f2", theme="Insulated steel bottle gifting", news_kind=None, corroboration="MODERATE", independent_source_count=2, relation_to_niche="gifting")
    o = intel.opportunities([report(ADJACENT=[adj])], prods(), TODAY)[0]
    assert o["observed"]["label"].startswith("What the saved sources reported") and o["possible"]["label"].startswith("A possible explanation (not measured)")
    assert o["demand"]["state"] == "UNAVAILABLE" and "search-volume" in o["demand"]["note"] and "not evidence of demand" in o["possible"]["text"]
    assert o["evidenceStrength"] == "MODERATE" and o["rank"] == 1 and o["observed"]["sources"][0]["url"]
    assert {s["agent"] for s in o["recommendations"]} >= {"YOU", "PI", "CMO", "CFO"}


def test_weak_old_or_unsourced_evidence_is_labelled_not_promoted():
    stale = finding("f3", theme="Steel bottle trend", published="2026-01-01T00:00:00", corroboration="STRONG")
    assert intel.opportunities([report(ADJACENT=[stale])], prods(), TODAY)[0]["evidenceStrength"] == "WEAK"
    single = finding("f4", theme="Steel bottle idea", corroboration="SINGLE_SOURCE")
    assert intel.opportunities([report(NEW_PRODUCTS_BUZZ=[single])], prods(), TODAY)[0]["evidenceStrength"] == "WEAK"
    none = finding("f5", theme="Steel bottle idea two", sources=[])
    assert intel.opportunities([report(NICHE=[none])], prods(), TODAY)[0]["evidenceStrength"] == "NOT_ASSESSED"


def test_a_tactic_with_an_identified_policy_risk_is_never_offered_and_an_unrelated_finding_is_left_out():
    risky = finding("f6", theme="Steel bottle review trick", caution=True, policy_risk="REVIEW_MANIPULATION")
    clean = finding("f7", theme="Steel bottle bundle idea", caution=False, policy_risk="NONE_IDENTIFIED")
    offered = [o["title"] for o in intel.opportunities([report(REPORTED_TACTICS=[risky, clean])], prods(), TODAY)]
    assert offered == ["Steel bottle bundle idea"]
    assert intel.opportunities([report(ADJACENT=[finding("f8", theme="Garden hose reels surge", sources=[{"url": "https://news.example/x", "title": "News", "published_at": "2026-10-20T00:00:00", "retrieved_at": "2026-10-30T00:00:00", "source_class": "THIRD_PARTY"}])])], prods(), TODAY) == []


def test_opportunities_are_ranked_by_relevance_then_evidence_then_freshness_without_a_score():
    a = finding("a", theme="Steel bottle gifting", corroboration="WEAK")
    b = finding("b", theme="Steel bottle camping", corroboration="STRONG", independent_source_count=4)
    out = intel.opportunities([report(ADJACENT=[a, b])], prods(), TODAY)
    assert [o["title"] for o in out] == ["Steel bottle camping", "Steel bottle gifting"] and [o["rank"] for o in out] == [1, 2]
    assert "no score or forecast" in out[0]["rankedBecause"]


def test_old_reports_are_flagged_stale():
    o = intel.overview([report(at="2026-08-01T00:00:00+00:00", MARKET_NEWS=[finding()])], prods(), TODAY)
    assert o["state"] == "STALE_REPORTS" and "days old" in o["message"]
