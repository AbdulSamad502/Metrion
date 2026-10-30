"""CMO 3.0 M6 pure rules: the section-edit sentence (spec 6.18.7a), phrase counting, the keyword map, competitor evidence and the rules-unavailable basis (6.18.11)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from slim_cmo.ci_inputs import CiInputs, CiInsight
from slim_cmo.claims import Attribute
from slim_cmo.constraints import ConstraintUnavailable, FormatConstraint, ResolvedConstraint, UnavailableReason
from slim_cmo.listing import basis, ci_evidence, edit, keyword_map, limits
from slim_cmo.listing.text import content_hash, count_phrases, sentences
from slim_cmo.types import AttributeBasis, ConstraintRowKind, CountRule, Marketplace

SP = AttributeBasis.SELLER_PROVIDED
NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------- edit sentence
@pytest.mark.parametrize("message,target,extra", [
    ("Change bullet 3 to: Wide mouth opening makes filling and cleaning easy.", "bullet", {"bullet_number": 3}),
    ("For my AquaNest bottle, change description to: AquaNest is a 1 litre stainless steel water bottle in silver.", "description", {"product": "AquaNest bottle"}),
    ("Change keywords on Flipkart to: stainless steel, water bottle, 1 litre, silver", "keywords", {"marketplace": "FLIPKART"}),
    ("change backend terms to: steel flask, reusable bottle", "backend_terms", {}),
    ("  CHANGE   BULLET   2   TO :  Reusable.  ", "bullet", {"bullet_number": 2}),
])
def test_valid_edit_sentences_parse(message, target, extra):
    r = edit.parse(message)
    assert r.kind == edit.EDIT and r.target == target
    for k, v in extra.items():
        assert getattr(r, k) == v


def test_keywords_and_backend_terms_are_split_on_commas():
    assert edit.parse("Change keywords to: a b, c ,d").terms == ("a b", "c", "d")


@pytest.mark.parametrize("message,code", [
    ("Change bullet 2 to:", "EMPTY_TEXT"),
    ("Change bullet 2 to:    ", "EMPTY_TEXT"),
    ("Change title to: Anything", "TITLE_NOT_EDITABLE"),
    ("Change backend terms on Flipkart to: a, b", "BACKEND_TERMS_AMAZON_ONLY"),
    ("Change bullet 1 to: " + "x" * (limits.EDIT_BULLET_MAX + 1), "TOO_LONG"),
    ("Change description to: " + "x" * (limits.EDIT_DESCRIPTION_MAX + 1), "TOO_LONG"),
    ("Change keywords to: " + ", ".join(f"k{i}" for i in range(limits.EDIT_LIST_MAX_TERMS + 1)), "TOO_MANY_TERMS"),
    ("Change keywords to: " + "y" * (limits.EDIT_TERM_MAX + 1), "TERM_TOO_LONG"),
    ("Change bullet 0 to: x", "BAD_BULLET_NUMBER"),
    ("Change bullet 1 to: bad\x00text", "INVALID_CHARACTERS"),
    ("Change keywords to: , ,", "EMPTY_TEXT"),
])
def test_recognised_but_invalid_edits_are_refused_with_a_code(message, code):
    r = edit.parse(message)
    assert r.kind == edit.REFUSED and r.code == code and r.reason


def test_the_ceilings_themselves_are_accepted():
    assert edit.parse("Change bullet 1 to: " + "x" * limits.EDIT_BULLET_MAX).kind == edit.EDIT
    assert edit.parse("Change keywords to: " + ", ".join(f"k{i}" for i in range(limits.EDIT_LIST_MAX_TERMS))).kind == edit.EDIT


@pytest.mark.parametrize("message", ["make bullet 2 shorter", "Change bullet 2", "change the description please", "write 5 titles", "", "approve this listing", "Change bullet two to: x"])
def test_anything_else_is_not_an_edit_and_never_guessed(message):
    assert edit.parse(message).kind == edit.NOT_AN_EDIT


def test_edit_sentence_never_looks_like_an_approval():
    assert edit.parse("yes").kind == edit.NOT_AN_EDIT and edit.parse("Approve").kind == edit.NOT_AN_EDIT


# ---------------------------------------------------------------- phrase counting
def test_longest_candidate_first_and_non_overlapping():
    got = count_phrases("Stainless steel water bottle", ["stainless steel water bottle", "water bottle", "steel"])
    assert got == {"stainless steel water bottle": 1, "water bottle": 0, "steel": 0}


def test_whole_word_only_and_punctuation_insensitive():
    got = count_phrases("A water-bottle, WATER BOTTLE! waterbottle bottles", ["water bottle"])
    assert got["water bottle"] == 2


def test_sentences_split_on_stops_and_newlines():
    assert sentences("One. Two!\nThree") == ["One.", "Two!", "Three"]


def test_content_hash_is_stable_and_sensitive():
    a = content_hash("AMAZON", {"title": "t", "bullets": ["a"]})
    assert a == content_hash("AMAZON", {"bullets": ["a"], "title": "t"})
    assert a != content_hash("AMAZON", {"title": "t", "bullets": ["b"]})
    assert a != content_hash("FLIPKART", {"title": "t", "bullets": ["a"]})


# ---------------------------------------------------------------- keyword map
CANDS = [
    {"keyword": "stainless steel", "recommended": True, "confidence": "STRONG", "placement": ["TITLE", "BULLETS"], "intent": "SPECIFICATION"},
    {"keyword": "water bottle", "recommended": True, "confidence": "MODERATE", "placement": ["TITLE", "DESCRIPTION"], "intent": "PRODUCT_TYPE"},
    {"keyword": "reusable", "recommended": True, "confidence": "WEAK", "placement": ["BULLETS"], "intent": "FEATURE"},
    {"keyword": "gym", "recommended": False, "confidence": "MODERATE", "placement": ["BULLETS"], "intent": "USE_CASE"},
    {"keyword": "bottle", "recommended": True, "confidence": "NOT_ASSESSED", "placement": ["BACKEND_TERMS"], "intent": "PRODUCT_TYPE"},
    {"keyword": "steel flask", "recommended": True, "confidence": "MODERATE", "placement": ["BACKEND_TERMS"], "intent": "PRODUCT_TYPE"},
]


def test_only_recommended_strong_or_moderate_candidates_are_placeable():
    assert [c["keyword"] for c in keyword_map.placeable(CANDS)] == ["stainless steel", "water bottle", "steel flask"]
    why = {n["keyword"]: n["reason"] for n in keyword_map.not_placeable(CANDS)}
    assert set(why) == {"reusable", "gym", "bottle"} and all(r.startswith("Not used") for r in why.values())


def test_map_reports_where_each_candidate_appears_and_never_a_demand_number():
    m = keyword_map.build(CANDS, title="AquaNest Stainless Steel Water Bottle", bullets=["Stainless steel body", "Lid"], description="A water bottle for daily use.", keywords=["steel flask"],
                          backend_terms=None)
    rows = {r["keyword"]: r for r in m["candidates"]}
    assert [w["section"] for w in rows["stainless steel"]["where"]] == ["TITLE", "BULLET 1"]
    assert [w["section"] for w in rows["water bottle"]["where"]] == ["TITLE", "DESCRIPTION"]
    assert [w["section"] for w in rows["steel flask"]["where"]] == ["KEYWORDS"]
    assert m["searchVolume"] == m["buyerDemand"] == m["marketplaceRank"] == "NOT_ASSESSED"
    assert "not search volume" in m["limits"]


def test_unplaced_candidates_get_a_closed_reason():
    cands = [
        {"keyword": "steel flask", "recommended": True, "confidence": "MODERATE", "placement": ["BACKEND_TERMS"], "intent": "PRODUCT_TYPE"},
        {"keyword": "silver bottle", "recommended": True, "confidence": "MODERATE", "placement": ["BULLETS"], "intent": "SPECIFICATION"},
        {"keyword": "bottle", "recommended": True, "confidence": "MODERATE", "placement": ["BULLETS"], "intent": "PRODUCT_TYPE"},
    ]
    m = keyword_map.build(cands, title="Silver Steel Bottle", bullets=["x"], description="y", keywords=["z"], backend_terms=None)
    reasons = {r["keyword"]: r["reason"] for r in m["candidates"]}
    assert reasons["steel flask"] == keyword_map.PLACEMENT_HINT_NOT_THIS_FIELD  # backend terms do not exist off Amazon
    assert reasons["silver bottle"] == keyword_map.ALREADY_IN_TITLE  # all its words are in the title but not as a phrase
    assert reasons["bottle"] is None or reasons["bottle"] in {keyword_map.NOT_NEEDED, keyword_map.WOULD_REPEAT_WITHOUT_BENEFIT, None}


# ---------------------------------------------------------------- competitor evidence
def _ci(themes=("reusable", "insulated", "bpa"), diff=("insulated",)):
    a = CiInsight("i1", keyword_themes=tuple(themes), differentiation_opportunities=tuple(diff), benefit_terms=("durable",))
    b = CiInsight("i2", keyword_themes=("reusable", "steel"))
    return CiInputs(insights=(a, b), references=("Competitor title text",), exclude_terms=("caspian",))


FACTS = (Attribute("Material", "stainless steel", SP), Attribute("Main use", "reusable daily bottle", SP), Attribute("insulated", "yes", AttributeBasis.IMAGE_OBSERVED))


def test_only_themes_the_confirmed_facts_carry_are_supported():
    rows = {r["theme"]: r for r in ci_evidence.evidence_rows(_ci(), FACTS)}
    assert rows["reusable"]["support"] == "SUPPORTED" and rows["reusable"]["sharedBy"] == {"count": 2, "of": 2}
    assert rows["steel"]["support"] == "SUPPORTED"
    assert rows["insulated"]["support"] == ci_evidence.CONSIDER_IF_TRUE  # an unverified photo hint never supports a competitor theme
    assert rows["bpa"]["support"] == ci_evidence.CONSIDER_IF_TRUE
    assert all("not a claim about your product" in r["limitation"] for r in rows.values())
    assert sorted(ci_evidence.consider_if_true(list(rows.values()))) == ["bpa", "insulated"]


def test_the_model_only_sees_supported_themes():
    narrowed = ci_evidence.supported_only(_ci(), FACTS)
    assert narrowed is not None
    assert set(narrowed.themes()) == {"reusable", "steel"}
    assert all(not i.differentiation_opportunities and not i.benefit_terms for i in narrowed.insights)
    assert "insulated" not in narrowed.prompt_block() and "bpa" not in narrowed.prompt_block()


def test_no_supported_theme_means_no_competitor_input_at_all():
    assert ci_evidence.supported_only(_ci(), (Attribute("Brand", "AquaNest", SP),)) is None
    assert ci_evidence.supported_only(None, FACTS) is None and ci_evidence.evidence_rows(None, FACTS) == []


def test_competitor_brand_words_are_never_themes():
    ci = CiInputs(insights=(CiInsight("i1", keyword_themes=("caspian", "reusable")),), exclude_terms=("caspian",))
    assert "caspian" not in {r["theme"] for r in ci_evidence.evidence_rows(ci, FACTS)}


# ---------------------------------------------------------------- rules-unavailable basis
def _na(reason):
    return ConstraintUnavailable(reason, Marketplace.AMAZON, "x")


ON = basis.BasisSettings(enabled=True, bullet_target=5, workflow=basis.FULL_LISTING)


@pytest.mark.parametrize("raw,expected", [(True, True), ("true", True), ("TRUE", True), (" True ", True), (False, False), ("false", False), ("1", False), (1, False), ("yes", False), (None, False), ("", False)])
def test_the_flag_defaults_to_off_and_only_true_enables(raw, expected):
    assert basis.parse_flag(raw) is expected


@pytest.mark.parametrize("raw,expected", [(5, 5), ("5", 5), (" 7 ", 7), (0, None), (-1, None), ("0", None), ("five", None), (None, None), (True, None), (2.5, None)])
def test_the_bullet_target_must_be_a_positive_integer(raw, expected):
    assert basis.parse_target(raw) == expected


@pytest.mark.parametrize("reason", [UnavailableReason.NO_ROW, UnavailableReason.NO_VERIFIED_ROW, UnavailableReason.STALE, UnavailableReason.COUNTING_RULE_UNVERIFIED])
def test_missing_marketplace_data_opens_the_basis_only_inside_the_workflow_with_the_flag_on(reason):
    assert basis.applies(_na(reason), ON)
    assert not basis.applies(_na(reason), basis.BasisSettings(enabled=False, bullet_target=5, workflow=basis.FULL_LISTING))
    assert not basis.applies(_na(reason), basis.BasisSettings(enabled=True, bullet_target=5, workflow=None))
    assert not basis.applies(_na(reason), basis.BasisSettings(enabled=True, bullet_target=5, workflow="STANDALONE"))


@pytest.mark.parametrize("reason", [UnavailableReason.CONFIG_MISSING, UnavailableReason.INVALID_ROW, UnavailableReason.FUTURE_VERIFIED_AT, UnavailableReason.MISSING_REQUIRED_LIMIT,
                                    UnavailableReason.UNSUPPORTED_COMBINATION])
def test_a_configuration_or_data_fault_never_opens_the_basis(reason):
    assert not basis.applies(_na(reason), ON)


def test_disabled_reason_is_only_given_inside_the_workflow():
    assert basis.disabled_reason(basis.BasisSettings(False, 5, basis.FULL_LISTING)) == "unverified drafts are not enabled"
    assert basis.disabled_reason(basis.BasisSettings(False, 5, None)) is None
    assert basis.disabled_reason(ON) is None


def test_the_synthetic_constraint_states_no_marketplace_limit_and_cites_no_source():
    res = basis.synthetic(Marketplace.AMAZON, settings=ON, title_option_count=5, now=NOW, needs_bullets=True)
    assert isinstance(res, ResolvedConstraint) and basis.rules_basis_of(res.row) == basis.UNVERIFIED
    r = res.row
    assert r.bullet_count == 5 and r.title_option_count == 5
    for f in ("title_max_chars", "bullet_max_chars", "description_max_chars", "keywords_max_count", "keywords_max_chars", "backend_terms_max_bytes", "hashtags_supported"):
        assert getattr(r, f) is None
    cite = r.cite()
    assert cite["rules_basis"] == "UNVERIFIED" and cite["source_url"] is None and cite["verified_at"] is None and cite["format_constraint_ref"] is None
    assert not r.hashtags_in_listing_allowed


def test_a_missing_bullet_target_is_a_configuration_fault_not_a_hidden_default():
    res = basis.synthetic(Marketplace.AMAZON, settings=basis.BasisSettings(True, None, basis.FULL_LISTING), title_option_count=5, now=NOW, needs_bullets=True)
    assert isinstance(res, ConstraintUnavailable) and res.reason is UnavailableReason.CONFIG_MISSING and res.missing == (basis.BULLET_TARGET_KEY,)
    ok = basis.synthetic(Marketplace.AMAZON, settings=basis.BasisSettings(True, None, basis.FULL_LISTING), title_option_count=5, now=NOW, needs_bullets=False)
    assert isinstance(ok, ResolvedConstraint) and ok.row.bullet_count is None


def test_a_real_row_is_reported_as_verified():
    real = FormatConstraint(id=__import__("uuid").uuid4(), marketplace=Marketplace.AMAZON, category=None, version=1, row_kind=ConstraintRowKind.VERIFIED, source_url="https://x", verified_at=NOW,
                            count_rule=CountRule.CODE_POINTS)
    assert basis.rules_basis_of(real) == basis.VERIFIED


# ---------------------------------------------------------------- the ask "rewrite bullet 3 to mention X" (Q26)
@pytest.mark.parametrize("message,expected", [
    ("rewrite bullet 3 to mention wide opening", ("bullet 3", "wide opening")),
    ("Rewrite the description to mention stainless steel.", ("description", "stainless steel")),
    ("please reword bullet point 2 of my listing to include the BPA free material", ("bullet 2", "the BPA free material")),
    ("redo bullet #4 so it mentions easy cleaning!", ("bullet 4", "easy cleaning")),
])
def test_the_rewrite_ask_names_the_section_and_the_topic(message, expected):
    assert edit.parse_rewrite_ask(message) == expected


@pytest.mark.parametrize("message", [
    "rewrite my listing", "rewrite bullet 3", "rewrite the title to mention steel", "change bullet 3 to: wide opening", "what does bullet 3 mention?", "", "rewrite bullet 3 to mention x",
])
def test_anything_else_is_not_a_rewrite_ask(message):
    assert edit.parse_rewrite_ask(message) is None
