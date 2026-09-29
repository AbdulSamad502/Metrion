"""`cfo.reasoning.narration_safety.check_narration_safety` — CLAUDE.md's LLM-evals requirement
for the Strategic Briefing narration surface (cfo-agent.md §7.5): never states a number not
present in its cited figures, never narrates an UNAVAILABLE figure as if it were a real value.

Real, deterministic assertions — no live Ollama call anywhere in this file."""

from __future__ import annotations

from cfo.reasoning.narrate import FigureToken
from cfo.reasoning.narration_safety import check_narration_safety


def _figures() -> list[FigureToken]:
    return [
        FigureToken(label="Contribution Margin", formatted_value="12.50%", register="VERIFIED"),
        FigureToken(label="Fee Ratio Pct", formatted_value="₹4,500.00", register="DERIVED"),
        FigureToken(label="Return Rate Pct", formatted_value="UNAVAILABLE", register="UNAVAILABLE"),
    ]


def test_narrative_citing_only_given_figures_is_safe():
    narrative = (
        "Your Contribution Margin sits at 12.50% this period, a healthy level. Fees came to "
        "₹4,500.00, which is worth watching. Return Rate Pct is not available this period."
    )
    result = check_narration_safety(narrative, _figures())
    assert result.is_safe is True
    assert result.fabricated_numbers == ()
    assert result.unavailable_figures_stated_as_real == ()


def test_narrative_with_a_number_not_in_any_figure_is_flagged():
    narrative = "Your Contribution Margin sits at 12.50%, and your fees dropped by 8.25% this month."
    result = check_narration_safety(narrative, _figures())
    assert result.is_safe is False
    assert "8.25" in result.fabricated_numbers


def test_narrative_stating_unavailable_figure_as_a_real_number_is_flagged():
    """The model hallucinates a value for a figure the caller marked UNAVAILABLE — exactly the
    failure CLAUDE.md's eval requirement names."""
    narrative = "Return Rate Pct came in at 3.20% this period, a slight improvement."
    result = check_narration_safety(narrative, _figures())
    assert result.is_safe is False
    assert "Return Rate Pct" in result.unavailable_figures_stated_as_real
    # The fabricated 3.20% is caught by the OTHER check too — both flags are real, independent
    # signals, not a single failure counted twice under one name.
    assert "3.20" in result.fabricated_numbers


def test_narrative_correctly_stating_unavailable_is_not_flagged_for_that_figure():
    narrative = "Return Rate Pct is unavailable this period — we don't yet have enough return data."
    result = check_narration_safety(narrative, _figures())
    assert result.unavailable_figures_stated_as_real == ()


def test_narrative_never_mentioning_an_unavailable_figure_is_not_flagged_for_it():
    """A narrative that simply omits an UNAVAILABLE figure entirely is not itself unsafe —
    only claiming a real value for it is."""
    narrative = "Your Contribution Margin sits at 12.50% this period."
    result = check_narration_safety(narrative, _figures())
    assert result.unavailable_figures_stated_as_real == ()


def test_small_ordinary_numbers_in_prose_do_not_false_positive():
    """Single-digit numbers ('3 findings', 'a 2-day lag') are common, harmless prose and are
    deliberately excluded from the number-extraction pattern — this is not itself a fabrication
    risk since it never resembles a money or percentage figure."""
    narrative = "There are 3 findings this period, with a 2-day average settlement lag."
    result = check_narration_safety(narrative, _figures())
    assert result.fabricated_numbers == ()


def test_currency_and_plain_digit_renderings_of_the_same_figure_are_treated_as_equal():
    narrative = "Fees came to 4500.00 this period."  # same figure, different rendering
    result = check_narration_safety(narrative, _figures())
    assert result.fabricated_numbers == ()
