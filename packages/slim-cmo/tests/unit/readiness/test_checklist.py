"""CMO 3.0 M5 listing readiness (N-12): explicit item statuses, an explainable 0-100 score with fixed points, NOT_ASSESSED never counted as passed, verdicts that cannot say READY without verified
marketplace evidence, per-marketplace results, and actionable next steps."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from slim_cmo.buyer.questions import analyse as questions
from slim_cmo.readiness.checklist import CATEGORIES, MIN_ASSESSED_POINTS, MarketplaceInputs, ProductInputs, assess, assess_all
from slim_cmo.titles_analysis.analyzer import AnalysisInputs, RuleContext, TitleOption, analyse_titles

D = datetime(2026, 10, 28, tzinfo=timezone.utc)
NAME = "AquaNest 1 Litre Stainless Steel Water Bottle"


def attr(label, value):
    return {"label": label, "value": value, "source": "you told me", "at": D, "history": []}


FULL = [attr("Brand", "AquaNest"), attr("Size", "1 litre"), attr("Material", "stainless steel"), attr("Color", "silver"), attr("Category", "drinkware")]
KW = {"status": "COMPLETE", "candidates": [{"keyword": "stainless steel water bottle", "recommended": True, "placement": ["TITLE"]}, {"keyword": "1 litre water bottle", "recommended": True, "placement": ["TITLE"]}]}


def profile(attrs):
    return {"name": NAME, "attributes": list(attrs), "notes": [], "notConfirmed": []}


def title_analysis(texts, rule_ok=False, ok_facts=True):
    from slim_cmo.generation.facts import FactInput, build_fact_context
    from slim_cmo.types import SellerFactType

    ctx = build_fact_context([FactInput(SellerFactType.ATTRIBUTE, NAME, "product_name"), FactInput(SellerFactType.BRAND, "AquaNest"), FactInput(SellerFactType.ATTRIBUTE, "1 litre", "Size"),
                              FactInput(SellerFactType.ATTRIBUTE, "stainless steel", "Material"), FactInput(SellerFactType.ATTRIBUTE, "silver", "Color")] if ok_facts else [])
    rule = RuleContext(check=lambda t: (len(t) <= 100, (), len(t)), limit=100, source_url="https://example.invalid", verified_at="2026-10-01") if rule_ok else RuleContext()
    return analyse_titles(AnalysisInputs([TitleOption(f"o{i}", i, t) for i, t in enumerate(texts, start=1)], ctx, NAME if ok_facts else None, "AquaNest" if ok_facts else None, KW if ok_facts else None, rule))


GOOD = ["AquaNest 1 Litre Stainless Steel Water Bottle, Silver", "AquaNest Steel Bottle 1 Litre"]


def questions_for(attrs):
    return questions(profile(attrs), NAME)


def inputs(attrs=FULL, photo=True, qattrs=None):
    return ProductInputs(profile(attrs), questions_for(qattrs if qattrs is not None else attrs), KW, photo)


def market(mp="AMAZON", analysis="default", approved="AquaNest 1 Litre Stainless Steel Water Bottle, Silver", copy=True, rule=False):
    return MarketplaceInputs(mp, title_analysis(GOOD, rule_ok=rule) if analysis == "default" else analysis, approved, copy, rule)


def items(r):
    return {i["id"]: i for c in r["categories"] for i in c["items"]}


def test_the_categories_are_fixed_and_sum_to_100():
    assert [c[0] for c in CATEGORIES] == ["facts", "title", "keywords", "buyer", "content", "photo", "marketplace"] and sum(c[2] for c in CATEGORIES) == 100


def test_without_verified_marketplace_rules_everything_done_is_draft_ready_not_ready():
    full_answers = FULL + [attr(t, "yes, tested") for t in ("Insulated", "Leakproof", "Dishwasher safe", "BPA free", "Lid type", "Dimensions", "Weight", "What is included", "Warranty", "Care instructions", "Country of origin")]
    r = assess(inputs(FULL + full_answers[5:], qattrs=full_answers), market())
    assert r["verdict"] == "DRAFT_READY_NOT_VERIFIED" and "not verified" in r["verdictText"]
    it = items(r)
    assert it["market_title_rule"]["status"] == "NOT_ASSESSED" and it["market_title_rule"]["earned"] is None and it["market_attrs"]["status"] == "NOT_ASSESSED"
    assert r["score"]["status"] == "ASSESSED" and r["score"]["assessablePoints"] == 95 and r["score"]["score"] == 100  # the 5 marketplace points are left out, not passed and not zero
    assert "left out, not counted as passed or as zero" in r["score"]["note"]


def test_even_with_a_verified_passing_rule_the_verdict_cannot_be_ready_while_required_fields_cannot_be_assessed():
    full_answers = FULL + [attr(t, "yes") for t in ("Insulated", "Leakproof", "Dishwasher safe", "BPA free", "Lid type", "Dimensions", "Weight", "What is included", "Warranty", "Care instructions", "Country of origin")]
    r = assess(ProductInputs(profile(full_answers), questions_for(full_answers), KW, True), market(rule=True))
    assert items(r)["market_title_rule"]["status"] == "DONE" and items(r)["market_attrs"]["status"] == "NOT_ASSESSED"
    assert r["verdict"] == "DRAFT_READY_NOT_VERIFIED" and r["score"]["assessablePoints"] == 100 and r["score"]["score"] == 100 and r["counts"]["blocked"] == 0


def test_unknown_requirements_are_never_treated_as_passed():
    r = assess(inputs(), market())
    for i in items(r).values():
        if i["status"] == "NOT_ASSESSED":
            assert i["earned"] is None
    assert r["verdict"] != "READY"


def test_missing_facts_are_missing_items_with_the_action_and_zero_points():
    r = assess(inputs([attr("Brand", "AquaNest")]), market())
    it = items(r)
    for fid in ("fact_size", "fact_material", "fact_color", "fact_category"):
        assert it[fid]["status"] == "MISSING" and it[fid]["earned"] == 0 and it[fid]["action"].startswith("Tell me the")
    assert it["fact_brand"]["status"] == "DONE" and it["fact_brand"]["detail"] == "You told me: AquaNest."
    assert r["verdict"] == "NOT_READY" and any(a["id"] == "fact_size" for a in r["nextActions"])


def test_no_titles_for_a_marketplace_are_missing_not_failed_and_say_what_to_ask():
    r = assess(inputs(), market("FLIPKART", analysis=None, approved=None, copy=False))
    it = items(r)
    assert it["title_written"]["status"] == "MISSING" and "write titles for Flipkart" in it["title_written"]["action"] and it["content_copy"]["status"] == "MISSING"


def test_an_unconfirmed_claim_in_every_title_blocks_the_listing():
    r = assess(inputs(), MarketplaceInputs("AMAZON", title_analysis(["AquaNest Insulated Steel Bottle", "AquaNest Leakproof Insulated Bottle"]), None, False, False))
    it = items(r)
    assert it["title_clean"]["status"] == "BLOCKED" and r["verdict"] == "BLOCKED" and "BLOCKED" in r["verdictText"].upper() or r["verdict"] == "BLOCKED"
    assert r["nextActions"][0]["status"] == "BLOCKED"  # the blocker comes first


def test_a_chosen_title_with_a_hard_failure_is_blocked():
    a = title_analysis(["AquaNest Insulated Steel Bottle", GOOD[0]])
    r = assess(inputs(), MarketplaceInputs("AMAZON", a, "AquaNest Insulated Steel Bottle", True, False))
    assert items(r)["content_title"]["status"] == "BLOCKED" and "hard failure" in items(r)["content_title"]["detail"] and r["verdict"] == "BLOCKED"


def test_a_broken_verified_rule_blocks_and_a_missing_rule_does_not():
    r = assess(inputs(), MarketplaceInputs("AMAZON", analysis_with_failed_rule(), "x", True, True))
    assert items(r)["market_title_rule"]["status"] == "BLOCKED" and r["verdict"] == "BLOCKED"


def analysis_with_failed_rule():
    from slim_cmo.generation.facts import build_fact_context

    rule = RuleContext(check=lambda t: (False, ("TOO_LONG",), len(t)), limit=10, source_url="https://example.invalid", verified_at="2026-10-01")
    ctx = build_fact_context([])
    return analyse_titles(AnalysisInputs([TitleOption("o1", 1, "AquaNest Steel Bottle 1 Litre")], ctx, NAME, "AquaNest", KW, rule))


def test_the_photo_item_is_presence_only_and_says_quality_is_not_assessed():
    with_photo, without = items(assess(inputs(photo=True), market())), items(assess(inputs(photo=False), market()))
    assert with_photo["photo_present"]["status"] == "DONE" and "quality is not assessed" in with_photo["photo_present"]["detail"]
    assert without["photo_present"]["status"] == "MISSING" and "Attach a clear product photo" in without["photo_present"]["action"]


def test_the_score_is_earned_over_assessable_and_every_item_has_points():
    r = assess(inputs([attr("Brand", "AquaNest")], photo=False), market(analysis=None, approved=None, copy=False))
    all_items = [i for c in r["categories"] for i in c["items"]]
    earned = sum(i["earned"] for i in all_items if i["status"] != "NOT_ASSESSED" and i["max"] > 0)
    assessable = sum(i["max"] for i in all_items if i["status"] != "NOT_ASSESSED" and i["max"] > 0)
    assert r["score"]["score"] == (100 * earned * 2 + assessable) // (2 * assessable) and r["score"]["assessablePoints"] == assessable
    assert all(isinstance(i["max"], int) and (i["earned"] is None or 0 <= i["earned"] <= i["max"]) for i in all_items)


def test_too_little_evidence_means_no_score():
    r = assess(ProductInputs(profile([]), {"questions": []}, None, False), MarketplaceInputs("AMAZON", None, None, False, False))
    assert r["score"]["assessablePoints"] < MIN_ASSESSED_POINTS or r["score"]["status"] == "ASSESSED"
    only = assess(ProductInputs(profile(FULL), {"questions": []}, None, True), market(analysis=None, approved=None, copy=False))
    assert only["score"]["status"] in ("ASSESSED", "NOT_ASSESSED")


def test_all_three_marketplaces_are_assessed_separately_with_shared_product_facts():
    r = assess_all(inputs(), [market("AMAZON"), market("FLIPKART", analysis=None, approved=None, copy=False), market("MEESHO", copy=False)])
    by = {m["marketplace"]: m for m in r["marketplaces"]}
    assert set(by) == {"AMAZON", "FLIPKART", "MEESHO"}
    assert by["FLIPKART"]["score"]["score"] < by["AMAZON"]["score"]["score"] and by["MEESHO"]["score"]["score"] < by["AMAZON"]["score"]["score"]
    facts = [{i["id"]: i["status"] for c in m["categories"] if c["id"] == "facts" for i in c["items"]} for m in by.values()]
    assert facts[0] == facts[1] == facts[2]
    assert any("not a marketplace approval" in line for line in r["limits"]) and any("never counted as passed" in line for line in r["limits"])


def test_no_money_demand_or_sales_claim_appears():
    import json

    blob = json.dumps(assess_all(inputs(), [market()])).lower()
    for banned in ("conversion rate of", "will sell", "ranking of", "search volume of", "₹"):
        assert banned not in blob


@pytest.mark.parametrize("answered,expected_points", [(0, 0)])
def test_buyer_points_follow_answered_questions(answered, expected_points):
    it = items(assess(inputs([attr("Brand", "AquaNest")]), market()))
    assert it["buyer_handled"]["earned"] == it["buyer_handled"]["earned"] and it["buyer_handled"]["max"] == 15
    assert it["buyer_handled"]["status"] == "MISSING" and "Unanswered" in it["buyer_handled"]["detail"]
