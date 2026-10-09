"""What the composition gate does and does not catch — an independent characterization (spec §6.5, AC21, Q13).

The digit forms the model could plausibly emit are all caught (Python's `\d` is Unicode-aware). The xfail(strict) cases document a REAL
gap found in review: QUANTITY WORDS WITHOUT DIGITS — "a third of orders", "fees doubled", "twice", "half", "½" — pass the gate although
each states a quantity that is not in any cited figure. Closing it risks false positives (e.g. "quarter" is also a reporting period),
and spec Q13 makes gate strictness a measured decision, so this is recorded, not changed. `strict=True` means: when someone tightens the
gate, these tests flip to XPASS and fail loudly, forcing this file to be updated deliberately.
"""

from __future__ import annotations

import pytest

from backend.ceo.composition_gate import check_composition

FIG = {"F1": True, "F2": False}


def _codes(text: str) -> set[str]:
    return set(check_composition(text, figure_tokens=FIG, other_tokens=["G1", "D1"]).codes())


@pytest.mark.parametrize(
    "text",
    [
        "Revenue was 482150 last month.",
        "Revenue was ₹ lots.",
        "Revenue was ४८२१५० last month.",  # Devanagari digits
        "Revenue was ４８２１５０ last month.",  # full-width digits
        "Revenue was ٤٨٢١٥٠ last month.",  # Arabic-Indic digits
        "Margin is about 1² times.",  # superscript
        "Revenue was 4\u200b8\u200b2 last month.",  # zero-width characters splitting digits
        "Fees 1️⃣ up",  # keycap emoji
        "Fees rose 3x.",
        "Revenue was four hundred eighty two thousand rupees.",
        "Revenue crossed four lakh.",
        "Margin is XII per cent.",
        "| a | b |\n| 1 | 2 |",  # markdown table
    ],
)
def test_digit_and_currency_forms_are_caught(text):
    assert _codes(text), text


@pytest.mark.parametrize("text, code", [("Revenue is {{F9}}.", "UNKNOWN_TOKEN"), ("Revenue is {{F2}}.", "UNAVAILABLE_AS_VALUE")])
def test_marker_misuse_is_caught(text, code):
    assert code in _codes(text)


@pytest.mark.parametrize("text", ["Revenue is {{F1}}.", "Revenue is {{ F1 }}.", "This is the third month in a row of falling margin."])
def test_legitimate_prose_passes(text):
    assert _codes(text) == set()


@pytest.mark.xfail(strict=True, reason="REVIEW FINDING: quantity words without digits pass the gate (spec Q13: strictness is a measured decision)")
@pytest.mark.parametrize(
    "text",
    [
        "About a third of orders were returned.",
        "Fees doubled this month.",
        "Fees are twice what they were.",
        "Profit is up by half.",
        "Fees rose by ½ this month.",
        "Profit grew by twelve and a half.",
    ],
)
def test_known_gap_quantity_words_are_not_yet_caught(text):
    assert _codes(text), text
