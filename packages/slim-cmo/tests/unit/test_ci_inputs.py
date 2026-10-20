"""CEO-brokered competitor-listing inputs (slim-cmo-agent.md section 6.7): derived words only in a prompt, and the originality / claims guard."""

from __future__ import annotations

from slim_cmo.ci_inputs import (
    VIOLATION_CLAIM,
    VIOLATION_CLOSE,
    VIOLATION_COPIES,
    VIOLATION_NAMES,
    CiInputs,
    CiInsight,
    check_output,
    texts_of,
)

COMP_TITLE = "CASPIAN Stainless Steel Insulated Water Bottle 1 Litre Leakproof Cap Keeps Drinks Cold"
COMP_BULLET = "Double wall vacuum insulation keeps your drink cold for hours outdoors"


def _ci(**kw) -> CiInputs:
    ins = CiInsight("11111111-1111-1111-1111-111111111111", keyword_themes=("insulated", "caspian", "leakproof", "steel"), feature_categories=("insulation",),
                    differentiation_opportunities=("bpa",))
    return CiInputs(insights=(ins,), references=(COMP_TITLE, COMP_BULLET), exclude_terms=("caspian",), **kw)


def test_themes_drop_competitor_brand_and_are_single_words():
    assert "caspian" not in _ci().themes()
    assert set(_ci().themes()) == {"insulated", "leakproof", "steel"}


def test_prompt_block_has_derived_words_only_no_competitor_text_no_price():
    block = _ci().prompt_block()
    assert "insulated" in block and "MARKET CONTEXT" in block
    assert "CASPIAN Stainless" not in block and "vacuum insulation" not in block  # the saved competitor text never reaches a prompt
    assert "₹" not in block and "price" not in block.lower().replace("not state or imply", "")


def test_snapshot_holds_ids_and_derived_words_not_competitor_text():
    snap = _ci().snapshot()
    flat = str(snap)
    assert snap["insights"][0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert snap["originality_references_checked"] == 2
    assert "CASPIAN Stainless" not in flat and "vacuum insulation" not in flat


def test_copied_competitor_wording_is_caught():
    mine = ["Double wall vacuum insulation keeps your drink cold for hours outdoors, in a steel bottle"]
    assert VIOLATION_COPIES in check_output(mine, _ci())


def test_light_rewrite_is_caught():
    mine = ["Stainless Steel Insulated Water Bottle 1 Litre Leakproof Cap Keeps Drinks Chilled"]
    out = check_output(mine, _ci())
    assert VIOLATION_COPIES in out or VIOLATION_CLOSE in out


def test_original_wording_from_seller_facts_passes():
    mine = ["Zyquora steel water bottle, 1 litre, matte black, with a screw-on lid"]
    assert check_output(mine, _ci()) == []


def test_naming_a_competitor_brand_is_caught():
    assert VIOLATION_NAMES in check_output(["A bottle better than Caspian"], _ci())


def test_search_volume_ranking_and_conversion_claims_are_caught():
    for claim in ("The top-ranked bottle on Amazon", "Best seller in water bottles", "High search volume keyword", "converts better than rivals", "Trending now", "#1 choice"):
        assert VIOLATION_CLAIM in check_output([claim], _ci()), claim


def test_no_references_means_only_claims_and_brands_are_checked():
    ci = CiInputs(insights=_ci().insights, references=(), exclude_terms=())
    assert check_output(["Steel water bottle 1 litre"], ci) == []


def test_texts_of_collects_seller_facing_strings_and_skips_provenance():
    structured = {"titles": ["A b c d e", "F g h"], "description": "Some text here", "provenance": {"ci_note": "ignore me"}, "category_context": {"category_hint": "ignore"}}
    got = texts_of(structured, "plain")
    assert "A b c d e" in got and "Some text here" in got and "plain" in got
    assert "ignore me" not in got and "ignore" not in got


def test_unusable_when_no_themes():
    ci = CiInputs(insights=(CiInsight("x"),))
    assert not ci.usable()
