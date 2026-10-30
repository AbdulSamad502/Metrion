"""CMO 3.0 M3 five-title analyzer (N-03 a-d): explainable per-dimension results, hard failures, NOT_ASSESSED, rule-based recommendation, no numeric score."""

from __future__ import annotations

from slim_cmo.generation.facts import FactInput, build_fact_context
from slim_cmo.keywords.intelligence import KeywordInputs, analyse
from slim_cmo.titles_analysis.analyzer import NOT_ASSESSED, AnalysisInputs, RuleContext, TitleOption, analyse_titles
from slim_cmo.types import Marketplace, SellerFactType

NAME = "AquaNest 1 Litre Stainless Steel Water Bottle"
T = {
    1: "AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use",
    2: "AquaNest Stainless Steel Water Bottle 1L for Everyday Drinking Water, Silver",
    3: "AquaNest Insulated Stainless Steel Water Bottle 1 Litre",
    4: "AquaNest Stainless Steel Water Bottle 2 Litre, Silver",
    5: "Water Bottle Water Bottle Water Bottle AquaNest",
}


def facts():
    rows = [FactInput(SellerFactType.ATTRIBUTE, NAME, "product_name"), FactInput(SellerFactType.BRAND, "AquaNest"), FactInput(SellerFactType.ATTRIBUTE, "1 litre", "Size"),
            FactInput(SellerFactType.ATTRIBUTE, "stainless steel", "Material"), FactInput(SellerFactType.ATTRIBUTE, "silver", "Color"), FactInput(SellerFactType.ATTRIBUTE, "reusable", "Key Features")]
    return build_fact_context(rows)


def keywords(ctx):
    attrs = tuple(a for a in [*ctx.eligible, *(a for a, _ in ctx.ineligible)] if a.name.casefold() != "product_name")
    return analyse(KeywordInputs(NAME, "AquaNest", attrs, (), marketplace=Marketplace.AMAZON))


def rule(limit=100, ok=True):
    def check(text):
        n = len(text)
        return n <= limit, (() if n <= limit else ("TOO_LONG",)), n

    return RuleContext(check=check, limit=limit, source_url="https://example.invalid/rule", verified_at="2026-10-01") if ok else RuleContext()


def run(texts=T, rl=None, ctx=None, kw="auto", **extra):
    ctx = ctx or facts()
    return analyse_titles(AnalysisInputs([TitleOption(f"o{k}", k, v) for k, v in texts.items()], ctx, NAME, "AquaNest", keywords(ctx) if kw == "auto" else kw, rl or rule(), marketplace=Marketplace.AMAZON, **extra))


def opt(r, n):
    return next(o for o in r["options"] if o["rank"] == n)


def test_every_option_gets_every_dimension_and_every_criterion_with_a_reason():
    r = run()
    for o in r["options"]:
        assert set(o["dimensions"]) == {"marketplaceRules", "factAccuracy", "keywordRelevance", "buyerIntent", "positioning", "readability"}
        assert all(d.get("detail") for d in o["dimensions"].values()) and o["strategy"]
        assert set(o["scores"]["criteria"]) == {"keywordRelevance", "factAccuracy", "readability", "buyerIntent", "structure"}
        assert all(c["detail"] for c in o["scores"]["criteria"].values())


def test_all_numbers_are_integers():
    def floats(x):
        if isinstance(x, float):
            return True
        if isinstance(x, dict):
            return any(floats(v) for v in x.values())
        if isinstance(x, (list, tuple)):
            return any(floats(v) for v in x)
        return False

    assert not floats(run())


def test_an_unconfirmed_claim_and_an_invented_number_are_hard_failures_and_never_recommended():
    r = run()
    assert opt(r, 3)["hardFailures"] and "insulated" in opt(r, 3)["hardFailures"][0]
    assert opt(r, 4)["hardFailures"] and "number 2" in opt(r, 4)["hardFailures"][0]
    assert not opt(r, 1)["hardFailures"] and not opt(r, 2)["hardFailures"]
    assert r["recommendation"].get("optionId") not in ("o3", "o4")


def test_a_title_that_breaks_the_verified_rule_is_a_hard_failure_with_the_length_shown():
    r = run(rl=rule(limit=40))
    o = opt(r, 1)
    assert o["dimensions"]["marketplaceRules"]["status"] == "FAIL" and o["hardFailures"] and o["dimensions"]["marketplaceRules"]["limit"] == 40
    assert r["recommendation"]["status"] == "NONE_ELIGIBLE" and r["recommendation"]["optionId"] is None


def test_without_a_verified_rule_the_rule_check_is_not_assessed_never_a_pass():
    r = run(rl=rule(ok=False))
    d = opt(r, 1)["dimensions"]
    assert d["marketplaceRules"]["status"] == NOT_ASSESSED and "no verified marketplace rule" in d["marketplaceRules"]["detail"] and d["readability"]["lengthCheck"] == NOT_ASSESSED
    assert not opt(r, 1)["hardFailures"]  # nothing was failed on a rule that could not be checked
    assert any("marketplace rules" in n for n in r["notes"])


def test_missing_keyword_evidence_is_not_assessed_and_left_out_of_the_comparison():
    r = run(kw=None)
    assert all(o["dimensions"]["keywordRelevance"]["status"] == NOT_ASSESSED for o in r["options"])
    assert any("keyword relevance" in n for n in r["notes"])
    assert r["recommendation"]["status"] in ("RECOMMENDED", "TIE")


def test_no_confirmed_facts_means_fact_accuracy_is_not_assessed():
    ctx = build_fact_context([])
    r = analyse_titles(AnalysisInputs([TitleOption("a", 1, "Steel Bottle 1 Litre")], ctx, None, None, None, rule()))
    assert r["options"][0]["dimensions"]["factAccuracy"]["status"] == NOT_ASSESSED and r["options"][0]["dimensions"]["buyerIntent"]["status"] == NOT_ASSESSED


def test_stuffing_is_a_reading_flag_and_the_stuffed_title_is_not_the_recommendation():
    r = run()
    rd = opt(r, 5)["dimensions"]["readability"]
    assert rd["status"] != "STRONG" and any("repeats water" in f for f in rd["flags"])
    assert r["recommendation"].get("optionId") != "o5"


def test_strategies_are_descriptive_labels_from_the_wording():
    r = run({1: T[1], 2: "Water Bottle 1 Litre in Stainless Steel by AquaNest", 3: "1 Litre Stainless Steel Water Bottle", 4: "Gym Water Bottle 1 Litre"})
    assert [o["strategy"] for o in r["options"]] == ["Brand-first", "Search-coverage", "Specification-first", "Use-case-first"]
    assert opt(r, 3)["strategy"] == "Specification-first" and opt(r, 2)["strategy"] == "Search-coverage"


def test_competitor_positioning_is_not_assessed_without_evidence_and_counted_with_it():
    assert opt(run(), 1)["dimensions"]["positioning"]["competitorThemesMentioned"] == NOT_ASSESSED
    got = opt(run(ci_theme_words=("reusable", "durable")), 1)["dimensions"]["positioning"]["competitorThemesMentioned"]
    assert got == ["reusable"]


def test_a_single_best_option_is_recommended_with_reasons_and_equal_options_are_a_tie_not_an_arbitrary_pick():
    r = run({1: T[1], 2: T[5]})
    assert r["recommendation"]["optionId"] == "o1" and r["recommendation"]["reasons"]
    same = run({1: "AquaNest Stainless Steel Water Bottle 1 Litre", 2: "AquaNest Stainless Steel Water Bottle 1 Litre"})
    assert same["recommendation"]["status"] == "TIE" and same["recommendation"]["optionId"] is None and len(same["recommendation"]["tiedOptionIds"]) == 2


def test_the_analysis_is_deterministic_and_states_its_limits():
    assert run() == run()
    text = " ".join(run()["limits"])
    assert "not an Amazon SEO ranking" in text and "hard failures" in text and "not a ranking" in text and "internal listing-quality assessment" in text
    assert "Marketplace compliance is not part of the score" in text and "never counted as zero" in text


# ------------------------------------------------------------------------------------------------ the 0-100 score
def crit(o, name):
    return o["scores"]["criteria"][name]


def test_the_weights_are_25_25_20_15_15_and_every_criterion_stays_within_its_maximum():
    from slim_cmo.titles_analysis.analyzer import MAX_POINTS

    assert MAX_POINTS == {"keywordRelevance": 25, "factAccuracy": 25, "readability": 20, "buyerIntent": 15, "structure": 15} and sum(MAX_POINTS.values()) == 100
    for o in run()["options"]:
        for name, c in o["scores"]["criteria"].items():
            assert c["status"] == "ASSESSED" and 0 <= c["earned"] <= MAX_POINTS[name] and c["max"] == MAX_POINTS[name]


def test_when_everything_is_assessable_the_overall_score_is_the_sum_and_every_lost_point_has_a_reason():
    for o in run()["options"]:
        ov = o["scores"]["overall"]
        pts = sum(c["earned"] for c in o["scores"]["criteria"].values())
        assert ov["status"] == "ASSESSED" and ov["score"] == pts and ov["assessablePoints"] == 100 and 0 <= ov["score"] <= 100
        for c in o["scores"]["criteria"].values():
            lost = c["max"] - c["earned"]
            assert lost == 0 or c["deductions"]  # a lost point always has a stated reason


def test_keyword_points_follow_the_stated_formula_and_name_the_missing_keywords():
    r = run({1: "AquaNest Bottle"})
    d = r["options"][0]["dimensions"]["keywordRelevance"]
    covered, total = len(d["covered"]), len(d["covered"]) + len(d["missing"])
    c = crit(r["options"][0], "keywordRelevance")
    assert c["earned"] == (25 * covered * 2 + total) // (2 * total) and f"25 x {covered}/{total}" in c["detail"]
    assert c["earned"] < 25 and any("Leaves out" in x["reason"] for x in c["deductions"])


def test_an_unsupported_claim_scores_zero_for_facts_is_not_usable_and_is_never_recommended():
    good = "AquaNest 1 Litre Stainless Steel Water Bottle, Silver"
    bad = "AquaNest Insulated 1 Litre Stainless Steel Water Bottle, Silver"  # the same wording plus a claim the seller never confirmed
    r = run({1: good, 2: bad})
    o = opt(r, 2)
    assert crit(o, "factAccuracy")["earned"] == 0 and crit(o, "factAccuracy")["deductions"][0]["points"] == 25
    assert o["scores"]["overall"]["band"] == "NOT_USABLE" and "never recommended" in o["scores"]["overall"]["note"]
    assert r["recommendation"]["optionId"] == "o1"
    only = run({1: bad})
    assert only["recommendation"]["status"] == "NONE_ELIGIBLE" and only["recommendation"]["optionId"] is None


def test_a_criterion_without_evidence_is_not_assessed_and_left_out_not_counted_as_zero():
    none = run(kw=None)
    o = opt(none, 1)
    assert crit(o, "keywordRelevance")["status"] == NOT_ASSESSED and crit(o, "keywordRelevance")["earned"] is None
    ov = o["scores"]["overall"]
    assert ov["assessablePoints"] == 75 and ov["score"] == (100 * ov["earnedPoints"] * 2 + 75) // 150 and "left out, not counted as zero" in ov["note"]
    assert run()["options"][0]["scores"]["overall"]["assessablePoints"] == 100


def test_too_little_evidence_gives_no_overall_score_and_no_recommendation():
    ctx = build_fact_context([])
    r = analyse_titles(AnalysisInputs([TitleOption("a", 1, "Steel Bottle 1 Litre"), TitleOption("b", 2, "Bottle Steel")], ctx, None, None, None, rule()))
    ov = r["options"][0]["scores"]["overall"]
    assert ov["status"] == NOT_ASSESSED and ov["assessablePoints"] == 35 and "at least 50" in ov["note"] and "score" not in ov
    assert r["recommendation"]["status"] == "NOT_ASSESSED" and r["recommendation"]["optionId"] is None


def test_marketplace_compliance_is_separate_from_the_score():
    ok, over = run(rl=rule(limit=100)), run(rl=rule(limit=40))
    assert opt(ok, 1)["scores"]["overall"]["score"] == opt(over, 1)["scores"]["overall"]["score"]  # the limit does not move a single point
    assert opt(ok, 1)["dimensions"]["marketplaceRules"]["status"] == "PASS" and opt(over, 1)["dimensions"]["marketplaceRules"]["status"] == "FAIL"
    assert over["recommendation"]["optionId"] is None  # a verified-rule failure is a hard failure
    assert opt(run(rl=rule(ok=False)), 1)["scores"]["overall"]["score"] == opt(ok, 1)["scores"]["overall"]["score"]


def test_readability_loses_stated_points_per_flag():
    c = crit(opt(run({1: "WATER BOTTLE Water Bottle Water Bottle"}), 1), "readability")
    assert c["earned"] == 20 - 8 - 5 and {d["points"] for d in c["deductions"]} == {8, 5}  # stuffing costs 8, ALL CAPS costs 5
    assert crit(opt(run({1: "Steel"}), 1), "readability")["earned"] == 12  # very short costs 8


def test_structure_rules_and_buyer_intent_points_are_explained():
    good = opt(run({1: "AquaNest Stainless Steel Water Bottle 1 Litre"}), 1)
    assert crit(good, "structure")["earned"] == 15 and not crit(good, "structure")["deductions"]
    late = opt(run({1: "Stainless Steel 1 Litre Silver Reusable Daily Use Light Strong Water Bottle by AquaNest"}), 1)
    s = crit(late, "structure")
    assert s["earned"] < 15 and "within the first" in s["deductions"][0]["reason"]
    bi = crit(opt(run({1: "Water Bottle"}), 1), "buyerIntent")
    assert bi["earned"] < 15 and "Leaves out" in bi["deductions"][0]["reason"]


def test_the_best_score_wins_and_equal_scores_are_a_tie_never_a_positional_pick():
    r = run({1: T[1], 2: T[5]})
    assert r["recommendation"]["optionId"] == "o1" and "highest internal quality score" in r["recommendation"]["text"] and "/100" in r["recommendation"]["text"]
    tie = run({1: "AquaNest Stainless Steel Water Bottle 1 Litre", 2: "AquaNest Stainless Steel Water Bottle 1 Litre"})
    assert tie["recommendation"]["status"] == "TIE" and "tied at" in tie["recommendation"]["text"]


def test_bands_are_fixed_ranges_of_the_overall_score():
    from slim_cmo.titles_analysis.analyzer import BANDS

    assert BANDS == ((80, "STRONG"), (65, "GOOD"), (50, "FAIR"), (0, "WEAK"))
    for o in run()["options"]:
        ov = o["scores"]["overall"]
        if ov["band"] != "NOT_USABLE":
            assert ov["band"] == next(b for floor, b in BANDS if ov["score"] >= floor)


# ------------------------------------------------------------------------------------------------ evidence coverage (assessable points) and fair recommendations
def row(rank, score, assessable, hard=False):
    return {"optionId": f"o{rank}", "rank": rank, "eligible": not hard, "strengths": ["Reads cleanly"],
            "scores": {"overall": {"status": "ASSESSED", "score": score, "assessablePoints": assessable, "band": "STRONG"}}}


def test_every_overall_score_states_how_many_of_the_100_points_it_rests_on():
    for o in run()["options"]:
        ov = o["scores"]["overall"]
        assert ov["assessablePoints"] == 100 and "100 of 100 points assessable" in ov["note"]
    for o in run(kw=None)["options"]:
        ov = o["scores"]["overall"]
        assert ov["assessablePoints"] == 75 and "75 of 100 points assessable" in ov["note"]
    assert run()["recommendation"]["assessablePoints"] == 100 and "100 of 100 points assessable" in run()["recommendation"]["text"]


def test_all_options_of_one_analysis_share_the_same_evidence_coverage():
    for kw in ("auto", None):
        assert len({o["scores"]["overall"]["assessablePoints"] for o in run(kw=kw)["options"]}) == 1


def test_titles_assessed_on_fewer_points_are_not_compared_with_titles_assessed_on_more():
    from slim_cmo.titles_analysis.analyzer import _recommendation

    rec = _recommendation([row(1, 95, 60), row(2, 80, 100), row(3, 78, 100)])  # 95/100 on 60 points is not the same evidence as 80/100 on 100
    assert rec["optionId"] == "o2" and rec["comparedOptionIds"] == ["o2", "o3"] and rec["assessablePoints"] == 100
    assert "Option(s) 1 could be checked on fewer points" in rec["text"] and "not compared" in rec["text"]


def test_a_lower_coverage_option_is_never_recommended_over_a_fully_assessed_one_and_ties_stay_within_a_coverage_group():
    from slim_cmo.titles_analysis.analyzer import _recommendation

    assert _recommendation([row(1, 99, 75), row(2, 60, 100)])["optionId"] == "o2"
    tie = _recommendation([row(1, 70, 100), row(2, 70, 100), row(3, 90, 75)])
    assert tie["status"] == "TIE" and set(tie["tiedOptionIds"]) == {"o1", "o2"} and "100 of 100 points assessable" in tie["text"]
    same = _recommendation([row(1, 70, 75), row(2, 80, 75)])  # equal coverage: the plain comparison, no fairness note
    assert same["optionId"] == "o2" and "could be checked on fewer points" not in same["text"]


def test_a_hard_failed_option_never_enters_the_comparison_whatever_its_coverage_or_score():
    from slim_cmo.titles_analysis.analyzer import _recommendation

    rec = _recommendation([row(1, 99, 100, hard=True), row(2, 60, 100)])
    assert rec["optionId"] == "o2" and "o1" not in rec["comparedOptionIds"]
    assert _recommendation([row(1, 99, 100, hard=True)])["status"] == "NONE_ELIGIBLE"
