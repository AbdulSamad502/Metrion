"""CMO 3.0 M2 keyword intelligence (N-02, N-02b): rule-based relevance, intent, placement, confidence and evidence; unconfirmed claims excluded; volume / demand / rank never assessed."""

from __future__ import annotations

import pytest

from slim_cmo.claims import Attribute
from slim_cmo.keywords.intelligence import NOT_ASSESSED, CiTheme, KeywordInputs, analyse
from slim_cmo.types import AttributeBasis, Marketplace

SP = AttributeBasis.SELLER_PROVIDED


def facts(**extra):
    base = [Attribute("brand", "AquaNest", SP), Attribute("Size", "1 litre", SP), Attribute("Material", "stainless steel", SP), Attribute("Color", "silver", SP)]
    return tuple(base + [Attribute(k, v, SP) for k, v in extra.items()])


def inp(attrs=None, **kw):
    base = dict(product_name="AquaNest 1 Litre Stainless Steel Water Bottle", brand="AquaNest", attributes=facts() if attrs is None else attrs, fact_ids=("f1", "f2"), marketplace=Marketplace.AMAZON)
    base.update(kw)
    return KeywordInputs(**base)


def by_kw(result):
    return {c["keyword"]: c for c in result["candidates"]}


def test_candidates_come_from_the_confirmed_facts_with_rules_not_numbers():
    r = analyse(inp())
    c = by_kw(r)
    assert {"stainless steel water bottle", "water bottle", "1 litre water bottle", "silver water bottle", "aquanest water bottle"} <= set(c)
    assert c["stainless steel water bottle"]["intent"] == "PRODUCT_TYPE" and c["stainless steel water bottle"]["placement"][0] == "TITLE"
    assert c["1 litre water bottle"]["intent"] == "SPECIFICATION" and c["1 litre water bottle"]["placement"] == ["TITLE", "BULLETS"]
    assert c["aquanest water bottle"]["intent"] == "BRAND"
    assert all(x["relevance"] == "HIGH" and x["confidence"] == "MODERATE" for x in c.values())  # facts only: relevant to the product, no outside corroboration


def test_volume_demand_and_rank_are_never_assessed_and_no_number_is_invented():
    r = analyse(inp())
    for c in r["candidates"]:
        assert c["searchVolume"] == c["buyerDemand"] == c["marketplaceRank"] == NOT_ASSESSED
        assert c["competitorOccurrence"] == {"status": NOT_ASSESSED}  # no competitor evidence was supplied
    assert any("not assessed" in line for line in r["limits"]) and any("No competitor evidence" in line for line in r["limits"])

    def floats(x):
        if isinstance(x, float):
            return True
        if isinstance(x, dict):
            return any(floats(v) for v in x.values())
        if isinstance(x, (list, tuple)):
            return any(floats(v) for v in x)
        return False

    assert not floats(r)


def test_competitor_themes_add_evidence_and_an_unconfirmed_claim_is_excluded_with_its_reason():
    themes = (CiTheme("insulated", ("a", "b", "c")), CiTheme("reusable", ("a", "b")), CiTheme("durable", ("a",)))
    r = analyse(inp(attrs=facts(**{"Key Features": "reusable"}), ci_themes=themes, ci_insight_count=3))
    c = by_kw(r)
    assert "insulated water bottle" not in c
    [ex] = [e for e in r["excluded"] if e["keyword"] == "insulated water bottle"]
    assert ex["claim"] == "insulated" and "have not confirmed" in ex["reason"]
    reusable = c["reusable water bottle"]
    assert reusable["competitorOccurrence"] == {"status": "OBSERVED", "listings": 2, "of": 3} and reusable["confidence"] == "STRONG"
    assert {e["kind"] for e in reusable["evidence"]} == {"SELLER_FACT", "CI_THEME"}
    durable = c["durable water bottle"]  # competitors use the word, the seller never said it: partly supported, flagged, not strong
    assert durable["relevance"] == "MEDIUM" and durable["confidence"] == "WEAK" and durable["evidence"][0]["kind"] == "CI_THEME"


def test_a_claim_the_seller_confirmed_is_allowed():
    r = analyse(inp(attrs=facts(**{"Key Features": "insulated"}), ci_themes=(CiTheme("insulated", ("a",)),), ci_insight_count=1))
    assert "insulated water bottle" in by_kw(r) and not r["excluded"]


def test_a_claim_that_is_only_a_photo_hint_or_an_estimate_is_named_not_offered():
    hint = Attribute("feature", "leakproof", AttributeBasis.IMAGE_OBSERVED, trust_state="UNVERIFIED_HINT")
    r = analyse(inp(attrs=(*facts(), hint)))
    assert any(e["claim"] == "leakproof" and "not something you confirmed" in e["reason"] for e in r["excluded"])
    assert not any("leakproof" in k for k in by_kw(r))


def test_low_relevance_goes_to_the_low_priority_field_for_the_marketplace_and_is_not_recommended():
    r = analyse(inp(niche_terms=("garden hose reel",)))
    low = by_kw(r)["garden hose reel"]
    assert low["relevance"] == "LOW" and low["recommended"] is False and low["placement"] == ["BACKEND_TERMS"]
    other = by_kw(analyse(inp(niche_terms=("garden hose reel",), marketplace=Marketplace.FLIPKART)))["garden hose reel"]
    assert other["placement"] == ["KEYWORDS"]
    assert by_kw(r)["water bottle"]["recommended"] is True


def test_use_case_words_become_bullet_and_description_keywords():
    r = analyse(inp(attrs=facts(**{"Main Use": "gym, office"})))
    c = by_kw(r)
    assert c["gym water bottle"]["intent"] == "USE_CASE" and c["gym water bottle"]["placement"] == ["BULLETS", "DESCRIPTION"] and "office water bottle" in c


def test_no_confirmed_facts_asks_for_them_and_invents_nothing():
    r = analyse(KeywordInputs(product_name=None, brand=None, attributes=(), fact_ids=()))
    assert r["status"] == "NO_FACTS" and r["candidates"] == [] and r["needs"]


def test_the_analysis_is_deterministic():
    a, b = analyse(inp(ci_themes=(CiTheme("reusable", ("a",)),), ci_insight_count=1)), analyse(inp(ci_themes=(CiTheme("reusable", ("a",)),), ci_insight_count=1))
    assert a == b


@pytest.mark.parametrize("claim_word", ["leakproof", "dishwasher", "bpa", "waterproof", "microwave", "rustproof"])
def test_every_listed_claim_is_excluded_without_a_confirming_fact(claim_word):
    r = analyse(inp(ci_themes=(CiTheme(claim_word, ("a",)),), ci_insight_count=1))
    assert not any(claim_word in k for k in by_kw(r)) and any(claim_word in e["keyword"] for e in r["excluded"])


def test_competitor_themes_are_counted_per_listing_from_derived_words_only():
    from slim_cmo.ci_inputs import CiInputs, CiInsight
    from slim_cmo.service.keywords import ci_themes

    ci = CiInputs(insights=(CiInsight("a", keyword_themes=("reusable", "Insulated", "aquakeep")), CiInsight("b", keyword_themes=("reusable",), benefit_terms=("durable",))), exclude_terms=("aquakeep",))
    themes, n = ci_themes(ci)
    got = {t.word: t.insight_ids for t in themes}
    assert n == 2 and got == {"durable": ("b",), "insulated": ("a",), "reusable": ("a", "b")}  # a competitor brand word is never a theme
    assert ci_themes(None) == ((), 0)
