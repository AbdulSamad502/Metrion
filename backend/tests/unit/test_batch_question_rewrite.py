"""'How many units should we buy of the top #1 product?' becomes the stocking question for that product (references.batch_rewrite); a title's video hashtags are not part of its name."""

from __future__ import annotations

from backend.ceo.composer import WEB_ARTEFACT_TITLE
from backend.ceo.references import batch_rewrite

FINDINGS = [{"source": "PI", "created_at": 1, "presentation": {"artefacts": [{"title": WEB_ARTEFACT_TITLE, "items": ["Designer Artificial Jewellery", "Suflix"]}]}}]


def test_a_units_question_about_a_listed_product_becomes_the_stocking_question() -> None:
    assert batch_rewrite(FINDINGS, "ok how much units or batch size should we buy? the top #1 product ?")[0] == "is Designer Artificial Jewellery worth stocking?"
    assert batch_rewrite(FINDINGS, "how many units of #2 should I buy")[0] == "is Suflix worth stocking?"
    assert batch_rewrite(FINDINGS, "what is the batch size for the second product")[0] == "is Suflix worth stocking?"


def test_other_questions_and_unknown_positions_are_left_alone() -> None:
    assert batch_rewrite(FINDINGS, "what is my profit") is None
    assert batch_rewrite(FINDINGS, "how many units of #9 should I buy") is None
    assert batch_rewrite([], "how many units of #1 should I buy") is None
