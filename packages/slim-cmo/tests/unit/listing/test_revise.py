"""CMO 3.0 M6 section revision (spec 6.18.7a; acceptance N-15a, N-15g, N-14b, N-14c): the edit changes exactly one section, the title never, and a blocker in the changed section refuses it."""

from __future__ import annotations

import pytest

from slim_cmo.listing import audit, edit, revise
from slim_cmo.listing.revise import Applied, Refused, Sections

from .test_audit import BULLETS, DESC, TITLE, base

S = Sections(title=TITLE, bullets=tuple(BULLETS), description=DESC, keywords=("steel flask", "silver"), backend_terms=("steel flask",))


def run(message, sections=S, **kw):
    req = edit.parse(message)
    assert req.kind == edit.EDIT, message
    applied = revise.apply_edit(sections, req)
    if isinstance(applied, Refused):
        return applied, None, None
    result, refused = revise.check_edit(applied, base(**kw))
    return applied, result, refused


def test_a_bullet_edit_changes_only_that_bullet_and_never_the_title():
    applied, result, refused = run("Change bullet 3 to: Wide mouth makes filling and cleaning easy.")
    assert refused is None and isinstance(applied, Applied)
    new = applied.sections
    assert new.bullets[2] == "Wide mouth makes filling and cleaning easy." and applied.changed == "BULLET 3"
    assert new.title == S.title and new.description == S.description and new.keywords == S.keywords and new.backend_terms == S.backend_terms
    assert new.bullets[:2] == S.bullets[:2] and new.bullets[3:] == S.bullets[3:]
    assert S.bullets[2] == "Holds 1 litre"  # the saved version is never mutated
    assert result["verdict"] in {audit.CHECKED_NOT_VERIFIED, audit.NEEDS_ATTENTION}


def test_a_new_version_has_a_new_hash_and_an_identical_edit_has_the_same_hash():
    a1, *_ = run("Change bullet 3 to: Wide mouth makes filling easy.")
    a2, *_ = run("Change bullet 3 to: Wide mouth makes filling easy.")
    assert a1.sections.hash("AMAZON") == a2.sections.hash("AMAZON") != S.hash("AMAZON")


def test_description_keywords_and_backend_terms_edits():
    assert run("Change description to: The AquaNest water bottle holds 1 litre of stainless steel.")[2] is None
    a, _r, refused = run("Change keywords to: steel flask, silver, 1 litre")
    assert refused is None and a.sections.keywords == ("steel flask", "silver", "1 litre")
    a2, _r2, refused2 = run("Change backend terms to: steel flask")
    assert refused2 is None and a2.sections.backend_terms == ("steel flask",)


def test_bullet_number_out_of_range_is_refused_before_anything_else():
    applied, _r, _x = run("Change bullet 7 to: x")
    assert isinstance(applied, Refused) and applied.code == "BULLET_OUT_OF_RANGE" and "1-5" in applied.reason


def test_backend_terms_edit_on_a_listing_without_them_is_refused():
    applied, _r, _x = run("Change backend terms to: steel flask", sections=Sections(S.title, S.bullets, S.description, S.keywords, None), backend_terms=None)
    assert isinstance(applied, Refused) and applied.code == "BACKEND_TERMS_AMAZON_ONLY"


@pytest.mark.parametrize("message,code", [
    ("Change bullet 2 to: Keeps drinks cold for 24 hours", "UNSUPPORTED_CLAIM"),
    ("Change bullet 2 to: Lasts 12 years", "UNSUPPORTED_NUMBER"),
    ("Change keywords to: leakproof, water bottle", "KEYWORD_NOT_TRACEABLE"),
    ("Change description to: It holds 750 ml of water.", "CAPACITY_CONTRADICTION"),
    ("Change bullet 1 to: Plastic body", "MATERIAL_CONTRADICTION"),
])
def test_a_blocker_in_the_changed_section_refuses_the_edit_and_names_the_rule(message, code):
    applied, result, refused = run(message)
    blockers = {f["code"] for f in result["findings"] if f["severity"] == audit.BLOCKER and f["section"] == applied.changed}
    assert refused is not None and refused.reason and refused.code in blockers and code in blockers  # several rules can fire on one edit; the named one is among them
    assert result["verdict"] == audit.BLOCKED


def test_a_blocker_that_already_existed_elsewhere_does_not_refuse_an_unrelated_edit():
    bad = Sections(S.title, ("Insulated for hot and cold", *S.bullets[1:]), S.description, S.keywords, S.backend_terms)  # bullet 1 already has a blocker
    applied, result, refused = run("Change bullet 3 to: Easy to carry.", sections=bad)
    assert refused is None and result["verdict"] == audit.BLOCKED  # the audit still reports it
    again, _r, refused_same = run("Change bullet 1 to: Insulated and leakproof", sections=bad)
    assert refused_same is not None  # touching the bad bullet with another bad text is refused


def test_a_revision_is_re_audited_with_a_fresh_result_on_the_new_text():
    _a, result, _x = run("Change bullet 4 to: Stainless steel and stainless steel again")
    assert any(f["code"] == "W1_REPEATED_IN_BULLET" for f in result["findings"])


def test_sections_from_a_saved_pack():
    s = revise.sections_from({"bullets": ["a", "b"], "description": "d", "keywords": ["k"]}, title="T", backend_terms=["x"])
    assert s == Sections("T", ("a", "b"), "d", ("k",), ("x",))
    assert revise.sections_from({}, title="T", backend_terms=None).backend_terms is None
