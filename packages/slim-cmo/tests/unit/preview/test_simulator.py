"""CMO 3.0 M4 preview simulation: truncation, keyword and detail visibility, labelled limits (verified only with a source and a fresh date), suggestions, and nothing invented."""

from __future__ import annotations

from datetime import date

import pytest

from slim_cmo.preview.simulator import (
    ILLUSTRATIVE_VISIBLE_CHARS,
    DisplayRule,
    detail_visibility,
    display_rules,
    keyword_visibility,
    option_preview,
    set_preview,
    split_visible,
)

TODAY = date(2026, 10, 30)
LONG = "AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use at Home, Gym and Office"
ILLUSTRATIVE = {m: DisplayRule(ILLUSTRATIVE_VISIBLE_CHARS[m], "ILLUSTRATIVE", "demo") for m in ("mobile", "desktop")}


def test_a_short_title_is_not_truncated():
    assert split_visible("AquaNest Steel Bottle 1 Litre", 60) == ("AquaNest Steel Bottle 1 Litre", "", False)


def test_a_long_title_is_cut_on_a_word_boundary_and_nothing_is_lost():
    shown, hidden, cut = split_visible(LONG, 60)
    assert cut and len(shown) <= 60 and not shown.endswith((" ", ",")) and LONG.startswith(shown)
    assert " ".join((shown + " " + hidden).replace(",", ", ").split()).replace(" ,", ",") .startswith("AquaNest") and hidden
    assert (shown + hidden).replace(" ", "").replace(",", "") == LONG.replace(" ", "").replace(",", "")  # every character is either shown or hidden


def test_the_cut_is_exactly_at_the_limit_boundary():
    t = "a" * 10 + " " + "b" * 10
    assert split_visible(t, 21) == (t, "", False) and split_visible(t, 20)[2] is True


def test_the_mobile_view_hides_more_than_the_desktop_view():
    p = option_preview(LONG, ILLUSTRATIVE, [], {}, False)
    assert p["mobile"]["truncated"] and len(p["mobile"]["hidden"]) > len(p["desktop"]["hidden"])
    assert not option_preview("AquaNest Steel Bottle 1 Litre", ILLUSTRATIVE, [], {}, False)["mobile"]["truncated"]


def test_keyword_and_detail_visibility_follow_the_cut():
    shown, _hidden, _ = split_visible(LONG, 60)
    kw = {k["keyword"]: k["status"] for k in keyword_visibility(shown, LONG, ["stainless steel water bottle", "gym water bottle", "garden hose"])}
    assert kw == {"stainless steel water bottle": "VISIBLE", "gym water bottle": "CUT_OFF", "garden hose": "NOT_IN_TITLE"}
    det = {d["label"]: d["status"] for d in detail_visibility(shown, LONG, {"Brand": "AquaNest", "Color": "silver", "Material": "steel", "Weight": "500 g"})}
    assert det["Brand"] == "VISIBLE" and det["Material"] == "VISIBLE" and det["Weight"] == "NOT_IN_TITLE"


def test_suggestions_come_only_from_what_was_computed():
    p = option_preview("Stainless Steel Water Bottle with a Wide Mouth and Handle for Daily Use, 1 Litre, Silver by AquaNest", ILLUSTRATIVE, ["water bottle"], {"Brand": "AquaNest", "Size": "1 litre"}, False)
    m = p["mobile"]["suggestions"]
    assert any("would be hidden on mobile" in s and "brand" in s.lower() for s in m)
    assert all("sales" not in s.lower() and "rank" not in s.lower() and "conversion" not in s.lower() for s in sum((x["suggestions"] for x in p.values()), []))
    assert option_preview("AquaNest Steel Bottle 1 Litre", ILLUSTRATIVE, [], {"Brand": "AquaNest"}, False)["desktop"]["suggestions"] == ["The whole title fits in this illustrative desktop view."]


def test_a_missing_detail_is_suggested_not_assumed():
    p = option_preview("Steel Bottle", ILLUSTRATIVE, [], {"Color": "silver"}, False)
    assert any("silver" not in s and "colour" not in s.lower() and "color" in s.lower() and "not in this title" in s for s in p["mobile"]["suggestions"])


def test_a_hard_failed_option_says_so_first():
    assert "hard failure" in option_preview("AquaNest Insulated Bottle", ILLUSTRATIVE, [], {}, True)["mobile"]["suggestions"][0]


# ------------------------------------------------------------------------------------------------ limits are labelled
def test_without_a_configured_rule_the_limit_is_illustrative_and_says_so_with_the_reason():
    r = display_rules(None, "AMAZON", today=TODAY, max_age_days=90)
    assert {m: (x.chars, x.basis) for m, x in r.items()} == {"mobile": (60, "ILLUSTRATIVE"), "desktop": (110, "ILLUSTRATIVE")}
    assert "not an official limit" in r["mobile"].note and "no verified display rule is configured" in r["mobile"].note


GOOD = {"AMAZON": {"mobile": {"visible_chars": 70, "source_url": "https://example.test/rule", "verified_at": "2026-10-01"}, "desktop": {"visible_chars": 130, "source_url": "https://example.test/rule", "verified_at": "2026-10-01"}}}


def test_a_complete_fresh_rule_with_a_source_is_verified():
    r = display_rules(GOOD, "AMAZON", today=TODAY, max_age_days=90)
    assert r["mobile"] == DisplayRule(70, "VERIFIED", "From the display rule checked 2026-10-01 (https://example.test/rule).", "https://example.test/rule", "2026-10-01")
    assert display_rules(GOOD, "FLIPKART", today=TODAY, max_age_days=90)["mobile"].basis == "ILLUSTRATIVE"  # a rule for one marketplace is never applied to another


@pytest.mark.parametrize("change,why", [({"visible_chars": 0}, "usable character count"), ({"visible_chars": 70.5}, "usable character count"), ({"source_url": "http://x"}, "no source page"),
                                        ({"source_url": None}, "no source page"), ({"verified_at": "never"}, "valid check date"), ({"verified_at": "2027-01-01"}, "valid check date"),
                                        ({"verified_at": "2026-01-01"}, "stale")])
def test_an_incomplete_unsourced_or_stale_rule_is_not_verified(change, why):
    raw = {"AMAZON": {"mobile": {**GOOD["AMAZON"]["mobile"], **change}}}
    r = display_rules(raw, "AMAZON", today=TODAY, max_age_days=90)["mobile"]
    assert r.basis == "ILLUSTRATIVE" and why in r.note


def test_a_verified_rule_without_a_staleness_window_is_not_trusted():
    assert display_rules(GOOD, "AMAZON", today=TODAY, max_age_days=None)["mobile"].basis == "ILLUSTRATIVE"


def test_the_set_preview_copies_score_coverage_and_compliance_from_the_analysis_and_adds_both_screens():
    analysis = {"options": [{"optionId": "o1", "rank": 1, "text": "AquaNest Steel Bottle 1 Litre", "strategy": "Brand-first", "hardFailures": [],
                             "scores": {"overall": {"status": "ASSESSED", "score": 82, "band": "STRONG", "assessablePoints": 85, "note": "n"}, "criteria": {"readability": {"status": "ASSESSED", "earned": 20, "max": 20}}},
                             "dimensions": {"marketplaceRules": {"status": "NOT_ASSESSED", "detail": "Not assessed: x"}}}]}
    [o] = set_preview(analysis, {"candidates": [{"keyword": "steel bottle", "recommended": True, "placement": ["TITLE"]}, {"keyword": "weak", "recommended": False, "placement": ["TITLE"]}]}, {"Brand": "AquaNest"}, ILLUSTRATIVE)
    assert o["score"]["score"] == 82 and o["score"]["assessablePoints"] == 85 and o["compliance"]["status"] == "NOT_ASSESSED"
    assert set(o["modes"]) == {"mobile", "desktop"} and [k["keyword"] for k in o["modes"]["mobile"]["keywords"]] == ["steel bottle"]


def test_the_preview_contains_no_invented_commercial_number():
    import json

    analysis = {"options": [{"optionId": "o1", "rank": 1, "text": LONG, "strategy": "x", "hardFailures": [], "scores": {"overall": {}, "criteria": {}}, "dimensions": {}}]}
    text = json.dumps(set_preview(analysis, None, {}, ILLUSTRATIVE)).lower()
    for banned in ("price", "rating", "review", "sales", "ranking", "conversion", "stars", "₹"):
        assert banned not in text
