"""CMO 3.0 M6 listing audit (spec 6.18.5, 6.18.5a; acceptance N-14a-j, N-05j, N-08c): deterministic checks A01-A15, repetition warnings W1-W7 at their exact thresholds, statuses, verdict."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from slim_cmo.ci_inputs import CiInputs, CiInsight
from slim_cmo.claims import Attribute
from slim_cmo.constraints import FormatConstraint
from slim_cmo.listing import audit, ci_evidence, limits
from slim_cmo.types import AttributeBasis, ConstraintRowKind, CountRule, Marketplace

SP = AttributeBasis.SELLER_PROVIDED
NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
ATTRS = (Attribute("brand", "AquaNest", SP), Attribute("Size", "1 litre", SP), Attribute("Material", "stainless steel", SP), Attribute("Color", "silver", SP),
         Attribute("Main use", "reusable daily bottle", SP))
CANDS = [
    {"keyword": "stainless steel", "recommended": True, "confidence": "STRONG", "placement": ["TITLE", "BULLETS"], "intent": "SPECIFICATION"},
    {"keyword": "water bottle", "recommended": True, "confidence": "MODERATE", "placement": ["TITLE", "DESCRIPTION"], "intent": "PRODUCT_TYPE"},
    {"keyword": "reusable", "recommended": True, "confidence": "MODERATE", "placement": ["BULLETS"], "intent": "FEATURE"},
    {"keyword": "1 litre", "recommended": True, "confidence": "MODERATE", "placement": ["TITLE"], "intent": "SPECIFICATION"},
    {"keyword": "steel flask", "recommended": True, "confidence": "MODERATE", "placement": ["BACKEND_TERMS"], "intent": "PRODUCT_TYPE"},
    {"keyword": "silver", "recommended": True, "confidence": "MODERATE", "placement": ["BULLETS"], "intent": "SPECIFICATION"},
]
EXCLUDED = [{"keyword": "insulated bottle", "reason": "needs a claim you have not confirmed"}]
TITLE = "AquaNest 1 Litre Stainless Steel Water Bottle, Silver"
BULLETS = ["Stainless steel body for everyday use", "Reusable bottle in silver", "Holds 1 litre", "Wide opening for easy filling", "Simple to carry"]
DESC = "The AquaNest water bottle holds 1 litre. It is made of stainless steel and is reusable."
QUESTIONS = {"questions": [
    {"id": "material", "topic": "Material", "importance": "ESSENTIAL", "claim": False, "status": "CONFIRMED", "answer": "stainless steel"},
    {"id": "leakproof", "topic": "Leakproof", "importance": "LIKELY", "claim": True, "status": "SELLER_UNKNOWN", "answer": None},
    {"id": "insulated", "topic": "Insulated", "importance": "LIKELY", "claim": True, "status": "NOT_CONFIRMED", "answer": None},
]}


def base(**kw):
    d = dict(marketplace="AMAZON", rules_basis=audit.UNVERIFIED, constraint=None, approved_title=TITLE, title=TITLE, bullets=BULLETS, description=DESC, keywords=["steel flask", "silver"],
             backend_terms=["steel flask"], attributes=ATTRS, candidates=CANDS, excluded=EXCLUDED, questions=QUESTIONS, gaps=("Category",))
    d.update(kw)
    return audit.AuditInputs(**d)


def codes(res, check=None):
    return sorted(f["code"] for f in res["findings"] if check is None or f["check"] == check)


def status(res):
    return {c["id"]: c["status"] for c in res["checks"]}


def verified_row(**kw):
    d = dict(id=uuid4(), marketplace=Marketplace.AMAZON, category=None, version=1, row_kind=ConstraintRowKind.VERIFIED, source_url="https://x", verified_at=NOW, count_rule=CountRule.CODE_POINTS)
    d.update(kw)
    return FormatConstraint(**d)


# ---------------------------------------------------------------- the clean case and the verdict
def test_a_clean_listing_on_the_unverified_basis_is_checked_not_verified_never_ready():
    r = audit.run(base())
    s = status(r)
    assert r["verdict"] == audit.CHECKED_NOT_VERIFIED and r["counts"]["blockers"] == 0 and r["counts"]["warnings"] == 0
    assert s["A15"] == audit.NOT_ASSESSED and s["A13"] == audit.NOT_ASSESSED and s["A03"] == audit.NOT_ASSESSED
    assert s["A01"] == s["A02"] == s["A04"] == s["A05"] == s["A06"] == s["A07"] == audit.PASS
    assert "READY" not in str(r["verdict"]) and "ready" not in r["verdict"].lower().replace("not_verified", "")
    assert r["rulesBasis"] == "UNVERIFIED" and "not checked against any marketplace rule" in r["measured"]["note"]
    assert "not a marketplace review" in r["limits"] and "score" not in r and all("score" not in k for k in r)


def test_not_applicable_is_only_for_checks_that_do_not_exist():
    r = audit.run(base(marketplace="FLIPKART", backend_terms=None, keywords=["silver"]))
    assert status(r)["A12"] == audit.NOT_APPLICABLE
    assert audit.run(base())["checks"][11]["status"] == audit.NOT_ASSESSED  # Amazon: the cap is unverified, never a pass


def test_unverified_basis_with_a_stray_constraint_still_ignores_it():
    r = audit.run(base(constraint=verified_row(bullet_count=1)))
    assert status(r)["A03"] == audit.NOT_ASSESSED and "A03" not in {f["check"] for f in r["findings"]}


# ---------------------------------------------------------------- A01 / A02
def test_a01_title_must_be_the_approved_title():
    r = audit.run(base(title="Something Else"))
    assert "TITLE_CHANGED" in codes(r, "A01") and r["verdict"] == audit.BLOCKED
    assert status(audit.run(base(title=TITLE.upper())))["A01"] == audit.PASS  # case is not a change
    assert status(audit.run(base(title=TITLE.replace(",", ""))))["A01"] == audit.PASS  # nor is punctuation


def test_a02_title_hard_failures_are_reused_not_rescored():
    r = audit.run(base(title_hard_failures=("contains a price figure",)))
    assert codes(r, "A02") == ["TITLE_HARD_FAILURE"] and status(r)["A02"] == audit.FAIL


# ---------------------------------------------------------------- A03 / A13 with a VERIFIED row
def test_a03_a13_enforce_only_what_a_verified_row_states():
    row = verified_row(bullet_count=3, bullet_max_chars=20, description_max_chars=30, keywords_max_count=1, keywords_max_chars=5, title_max_chars=10)
    r = audit.run(base(rules_basis="VERIFIED", constraint=row))
    c3 = codes(r, "A03")
    assert {"BULLET_COUNT", "BULLET_TOO_LONG", "DESCRIPTION_TOO_LONG", "TOO_MANY_KEYWORDS", "KEYWORD_TOO_LONG"} <= set(c3)
    assert codes(r, "A13") == ["TITLE_TOO_LONG"] and r["verdict"] == audit.BLOCKED
    loose = audit.run(base(rules_basis="VERIFIED", constraint=verified_row(bullet_count=5, title_max_chars=500)))
    assert status(loose)["A03"] == audit.PASS and status(loose)["A13"] == audit.PASS


def test_a03_sections_must_exist_even_on_the_unverified_basis():
    r = audit.run(base(description="", bullets=[], keywords=[]))
    assert codes(r, "A03") == ["SECTION_MISSING"] * 3 and status(r)["A03"] == audit.FAIL


def test_a12_amazon_byte_cap_only_from_a_verified_row():
    over = audit.run(base(rules_basis="VERIFIED", constraint=verified_row(backend_terms_max_bytes=5)))
    assert codes(over, "A12") == ["BACKEND_TERMS_TOO_LONG"]
    ok = audit.run(base(rules_basis="VERIFIED", constraint=verified_row(backend_terms_max_bytes=500)))
    assert status(ok)["A12"] == audit.PASS
    assert status(audit.run(base()))["A12"] == audit.NOT_ASSESSED and "bytes measured" in audit.run(base())["checks"][11]["detail"]


# ---------------------------------------------------------------- A04 claims
@pytest.mark.parametrize("bullet,code", [
    ("Keeps drinks cold for 24 hours", "UNSUPPORTED_CLAIM"), ("Insulated for hot and cold", "UNSUPPORTED_CLAIM"), ("100% leakproof lid", "UNSUPPORTED_CLAIM"),
    ("BPA free and food grade", "UNSUPPORTED_CLAIM"), ("Dishwasher safe", "UNSUPPORTED_CLAIM"),
])
def test_a04_unconfirmed_claims_are_blockers(bullet, code):
    r = audit.run(base(bullets=[*BULLETS[:4], bullet]))
    assert code in codes(r, "A04") and r["verdict"] == audit.BLOCKED


def test_a04_seller_unknown_and_not_confirmed_topics_must_not_be_asserted():
    r = audit.run(base(description=DESC + " The lid is leakproof."))
    assert "UNCONFIRMED_TOPIC" in codes(r, "A04") or "UNSUPPORTED_CLAIM" in codes(r, "A04")


def test_a04_a_confirmed_claim_is_allowed():
    attrs = (*ATTRS, Attribute("Leakproof", "yes, tested", SP))
    qs = {"questions": [{**QUESTIONS["questions"][1], "status": "CONFIRMED", "answer": "yes, tested"}]}
    r = audit.run(base(attributes=attrs, questions=qs, description=DESC + " The lid is leakproof."))
    assert "UNSUPPORTED_CLAIM" not in codes(r, "A04") and "UNCONFIRMED_TOPIC" not in codes(r, "A04")


def test_a04_forbidden_content_and_unconfirmed_photo_values():
    r = audit.run(base(bullets=[*BULLETS[:4], "Best seller, call 9876543210 now"]))
    assert "FORBIDDEN_CONTENT" in codes(r, "A04")
    hint = Attribute("Weight", "750 grams", AttributeBasis.ESTIMATED)
    r2 = audit.run(base(attributes=(*ATTRS, hint), description=DESC + " Weighs 750 grams."))
    assert "UNCONFIRMED_VALUE" in codes(r2, "A04") or "UNSUPPORTED_NUMBER" in codes(r2, "A05")


# ---------------------------------------------------------------- A05 / A06
def test_a05_numbers_must_be_supported_by_confirmed_facts():
    r = audit.run(base(bullets=[*BULLETS[:4], "Lasts 12 years"]))
    assert codes(r, "A05") == ["UNSUPPORTED_NUMBER"]


def test_a06_capacity_material_colour_contradictions():
    assert "CAPACITY_CONTRADICTION" in codes(audit.run(base(description="The AquaNest water bottle holds 750 ml.")), "A06")
    assert "MATERIAL_CONTRADICTION" in codes(audit.run(base(bullets=[*BULLETS[:4], "Plastic lid"])), "A06")
    assert "COLOUR_CONTRADICTION" in codes(audit.run(base(bullets=[*BULLETS[:4], "Also in blue"])), "A06")
    assert "CAPACITY_CONTRADICTION" not in codes(audit.run(base(description="Holds 1000 ml.")), "A06")  # 1 litre == 1000 ml
    no_cap = tuple(a for a in ATTRS if a.name != "Size")
    r = audit.run(base(attributes=no_cap, description="Holds 500 ml.", bullets=[*BULLETS[:4], "Holds 1 litre"]))
    assert "CAPACITY_DISAGREES" in codes(r, "A06")


# ---------------------------------------------------------------- A07
def test_a07_every_keyword_traces_to_a_recommended_candidate():
    r = audit.run(base(keywords=["steel flask", "cheap flask"], backend_terms=["insulated bottle"]))
    assert codes(r, "A07") == ["KEYWORD_EXCLUDED", "KEYWORD_NOT_TRACEABLE"]
    weak = [dict(c) for c in CANDS]
    weak[4]["confidence"] = "WEAK"
    assert "KEYWORD_NOT_TRACEABLE" in codes(audit.run(base(candidates=weak)), "A07")  # a WEAK candidate is never placed


# ---------------------------------------------------------------- A08 W1-W7 at the exact thresholds
def w(res, code):
    return [f for f in res["findings"] if f["code"] == code]


def test_w1_one_bullet_two_or_more():
    one = audit.run(base(bullets=["Stainless steel body that resists dents", *BULLETS[1:]]))
    assert not w(one, "W1_REPEATED_IN_BULLET")
    three = audit.run(base(bullets=["Stainless steel bottle with a stainless steel body and stainless steel lid", *BULLETS[1:]]))
    assert w(three, "W1_REPEATED_IN_BULLET") and three["verdict"] == audit.NEEDS_ATTENTION
    two = audit.run(base(bullets=["Stainless steel body with a stainless steel lid", *BULLETS[1:]]))
    assert w(two, "W1_REPEATED_IN_BULLET")  # the threshold itself (2) triggers


def test_w2_four_different_bullets():
    mk = lambda n: [("Reusable bottle number %d" % i) if i < n else "Simple to carry" for i in range(5)]  # noqa: E731
    assert not w(audit.run(base(bullets=mk(3))), "W2_REPEATED_ACROSS_BULLETS")
    assert w(audit.run(base(bullets=mk(4))), "W2_REPEATED_ACROSS_BULLETS")


def test_w3_description_four_or_more():
    three = "A water bottle. Your water bottle. The water bottle."
    four = three + " Every water bottle."
    assert not w(audit.run(base(description=three)), "W3_REPEATED_IN_DESCRIPTION")
    assert w(audit.run(base(description=four)), "W3_REPEATED_IN_DESCRIPTION")


def test_w4_whole_listing_eight_or_more():
    title = "AquaNest Stainless Steel Water Bottle"  # 1
    bullets = ["Stainless steel A", "Stainless steel B", "Stainless steel C", "Simple", "Simple too"]  # 3 -> total 4
    seven = audit.run(base(title=title, approved_title=title, bullets=bullets, description="Stainless steel one. Stainless steel two. Stainless steel three."))  # 4 + 3 = 7
    assert not w(seven, "W4_REPEATED_IN_LISTING")
    eight = audit.run(base(title=title, approved_title=title, bullets=bullets, description="Stainless steel one. Stainless steel two. Stainless steel three. Stainless steel four."))
    assert w(eight, "W4_REPEATED_IN_LISTING")


def test_w5_exact_duplicate_bullets_and_bullet_equals_description_sentence():
    r = audit.run(base(bullets=["Reusable and eco friendly.", "Simple to carry", "Holds 1 litre", "Reusable and eco friendly!", "Wide opening"]))
    assert w(r, "W5_DUPLICATE_BULLET")
    r2 = audit.run(base(bullets=["Simple to carry", *BULLETS[1:]], description="Simple to carry. It holds 1 litre."))
    assert w(r2, "W5_BULLET_IN_DESCRIPTION")
    assert not w(audit.run(base(bullets=["Simple to carry.", "Simple to carry easily", "Holds 1 litre", "Wide opening for easy filling", "Stainless steel body"])), "W5_DUPLICATE_BULLET")  # near-identical is NOT a duplicate (exact only)


def test_w6_bare_keyword_list_four_or_more_items():
    four = audit.run(base(bullets=["Stainless steel, water bottle, reusable, silver.", *BULLETS[1:]]))
    assert w(four, "W6_BARE_KEYWORD_LIST")
    three = audit.run(base(bullets=["Stainless steel, reusable, silver.", *BULLETS[1:]]))
    assert not w(three, "W6_BARE_KEYWORD_LIST")
    assert not w(audit.run(base(bullets=["Stainless steel, water bottle, reusable, plus a wide opening.", *BULLETS[1:]])), "W6_BARE_KEYWORD_LIST")


def test_w7_duplicate_backend_term():
    assert w(audit.run(base(backend_terms=["steel flask", "Steel  Flask"])), "W7_DUPLICATE_TERM")
    assert not w(audit.run(base(backend_terms=["steel flask"])), "W7_DUPLICATE_TERM")


def test_repetition_findings_are_warnings_never_blockers_and_say_they_are_not_marketplace_rules():
    r = audit.run(base(bullets=["Stainless steel and stainless steel", *BULLETS[1:]]))
    f = w(r, "W1_REPEATED_IN_BULLET")[0]
    assert f["severity"] == audit.WARNING and "not a marketplace or ranking rule" in f["explanation"]
    assert limits.W1_SAME_CANDIDATE_IN_ONE_BULLET == 2 and limits.W2_SAME_CANDIDATE_IN_BULLETS == 4 and limits.W3_SAME_CANDIDATE_IN_DESCRIPTION == 4
    assert limits.W4_SAME_CANDIDATE_IN_LISTING == 8 and limits.W6_BARE_KEYWORD_LIST_ITEMS == 4


# ---------------------------------------------------------------- A09 / A10 / A14
def test_a09_title_fact_never_repeated_is_a_note_not_a_failure():
    r = audit.run(base(bullets=["Reusable", "Holds easy", "Wide opening", "Simple to carry", "Lid included"], description="Great for the gym."))
    assert any(f["code"] == "TITLE_FACT_NOT_REPEATED" and f["severity"] == audit.NOTE for f in r["findings"]) and r["verdict"] == audit.CHECKED_NOT_VERIFIED


def test_a10_buyer_question_coverage_lists_unanswered_topics_and_never_guesses():
    r = audit.run(base())
    d = [c for c in r["checks"] if c["id"] == "A10"][0]
    assert "Leakproof" in d["detail"] and "Insulated" in d["detail"]
    assert status(audit.run(base(questions=None)))["A10"] == audit.NOT_ASSESSED
    shown = audit.run(base(bullets=["Reusable", "Easy fill", "Wide opening", "Simple to carry", "Lid"], description="A bottle."))
    assert any(f["code"] == "ANSWER_NOT_SHOWN" for f in shown["findings"])


def test_a14_missing_information_is_listed_as_next_actions():
    r = audit.run(base(gaps=("Category", "Warranty")))
    assert [f["code"] for f in r["findings"] if f["check"] == "A14"] == ["FACT_NOT_GIVEN"] * 2 and status(r)["A14"] == audit.PASS


# ---------------------------------------------------------------- A11 competitor evidence
def _ci():
    return CiInputs(insights=(CiInsight("i1", keyword_themes=("reusable", "insulated"), differentiation_opportunities=("insulated",)),), references=("A competitor sells the Caspian bottle with a wide opening",),
                    exclude_terms=("caspian",))


def test_a11_an_unsupported_competitor_theme_in_the_text_is_a_blocker():
    ci = _ci()
    rows = ci_evidence.evidence_rows(ci, ATTRS)
    clean = audit.run(base(ci=ci_evidence.supported_only(ci, ATTRS), ci_rows=rows))
    assert status(clean)["A11"] == audit.PASS
    # the claim list also fires on "insulated"; A11 must name the competitor theme itself
    leaked = audit.run(base(ci=ci, ci_rows=rows, bullets=[*BULLETS[:4], "Insulated design"]))
    assert "CI_UNSUPPORTED_THEME_USED" in codes(leaked, "A11") and leaked["verdict"] == audit.BLOCKED


def test_a11_originality_failure_and_no_ci_used():
    ci = _ci()
    copied = audit.run(base(ci=ci_evidence.supported_only(ci, ATTRS), ci_rows=ci_evidence.evidence_rows(ci, ATTRS), bullets=[*BULLETS[:4], "Sells the Caspian bottle with a wide opening"]))
    assert "CI_ORIGINALITY" in codes(copied, "A11")
    none_used = audit.run(base())
    assert status(none_used)["A11"] == audit.PASS and [c for c in none_used["checks"] if c["id"] == "A11"][0]["detail"] == "No competitor themes were used."


def test_a12_competitor_brand_words_are_blockers_in_backend_terms():
    r = audit.run(base(ci=_ci(), backend_terms=["caspian flask"], candidates=[*CANDS, {"keyword": "caspian flask", "recommended": True, "confidence": "MODERATE", "placement": ["BACKEND_TERMS"], "intent": "BRAND"}]))
    assert "COMPETITOR_BRAND_TERM" in codes(r, "A12")


# ---------------------------------------------------------------- determinism and shape
def test_the_audit_is_deterministic_has_no_score_and_lists_all_fifteen_checks():
    a, b = audit.run(base()), audit.run(base())
    assert a == b
    assert [c["id"] for c in a["checks"]] == [f"A{i:02d}" for i in range(1, 16)]
    assert a["method"] == limits.METHOD_VERSION
    assert {"BLOCKER", "WARNING", "NOTE"} >= {f["severity"] for f in audit.run(base(description="Plastic. 12 years.")).get("findings", [])}


def test_findings_are_ordered_blockers_first_and_name_a_section_and_a_correction():
    r = audit.run(base(bullets=["Stainless steel and stainless steel", *BULLETS[1:4], "Insulated"]))
    sev = [f["severity"] for f in r["findings"]]
    assert sev == sorted(sev, key=lambda s: {"BLOCKER": 0, "WARNING": 1, "NOTE": 2}[s])
    assert all(f["section"] and f["explanation"] for f in r["findings"])
    assert all(f["correction"] for f in r["findings"] if f["severity"] == audit.BLOCKER)


def test_measured_lengths_are_reported_but_never_a_pass():
    m = audit.run(base())["measured"]
    assert m["title"]["codePoints"] == len(TITLE) and m["backendTermsBytes"] == len("steel flask") and len(m["bullets"]) == 5
