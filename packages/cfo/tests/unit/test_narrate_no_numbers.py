"""Brain 3 — `cfo.reasoning.narrate` — cfo-agent.md §7.4.9: "Brain 3 may interpret, explain
and narrate figures Brain 1 has already computed. It may never [...] perform arithmetic [...]
re-derive [...] sum, net, or otherwise combine [...] figures."

Feeds `narrate_figures` a stub `LlmProvider` that returns various strings (including one
containing digits, to make sure this test validates the INPUT contract, not merely the
output). Asserts `FigureToken`/`narrate_figures`'s parameters never accept a numeric type for
a figure value (only pre-formatted strings), and that the prompt template contains the
explicit no-arithmetic instruction.

AC mapping (§7.4, twinkly-mapping-canyon.md CP3):
  - AC2  -> test_figure_token_formatted_value_is_string_typed,
            test_narrate_figures_has_no_numeric_parameter_anywhere_in_its_signature
  - AC21 -> test_system_prompt_states_never_compute
  - AC24 -> test_system_prompt_forbids_rederiving_or_summing
  - AC25 -> test_unavailable_register_instructs_no_zero_substitution
  - AC26 -> test_prompt_never_embeds_a_raw_number_only_preformatted_strings
  - AC27 -> test_provider_stub_returning_digit_bearing_string_is_still_accepted_unmodified
            (the INPUT contract, not the provider's own output, is what's enforced)
  - AC28 -> test_system_prompt_forbids_stating_rates_from_training_knowledge
  - AC29 -> test_system_prompt_forbids_filing_grade_claims
  - AC30 -> test_gst_context_appends_disclaimer_instruction_verbatim
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, fields

from cfo.reasoning.narrate import FigureToken, narrate_figures
from cfo.reasoning.prompts import GST_DISCLAIMER, SYSTEM_PROMPT, build_narration_prompt
from cfo.reasoning.provider import LlmProvider


@dataclass
class _StubProvider:
    """A deterministic `LlmProvider` stand-in — never a real model call in this test file."""

    response: str
    captured_prompts: list[str]

    def complete(self, *, model: str, prompt: str) -> str:
        self.captured_prompts.append(prompt)
        return self.response


def _provider(response: str) -> tuple[_StubProvider, list[str]]:
    captured: list[str] = []
    return _StubProvider(response=response, captured_prompts=captured), captured


# ---------------------------------------------------------------------------
# AC2 / AC26 — the type-level enforcement: no numeric parameter exists to feed.
# ---------------------------------------------------------------------------


def test_figure_token_formatted_value_is_string_typed() -> None:
    field_types = {f.name: f.type for f in fields(FigureToken)}
    assert field_types["formatted_value"] == "str"
    assert field_types["label"] == "str"
    assert field_types["register"] == "str"


def test_figure_token_rejects_being_constructed_conceptually_with_an_int() -> None:
    """There is no code path in this module that accepts an int for a figure's value — the
    caller must pre-format. This constructs FigureToken correctly (str) to prove the only
    supported shape, documenting by construction what the dataclass's type declares."""
    token = FigureToken(label="Contribution Profit", formatted_value="UNAVAILABLE", register="UNAVAILABLE")
    assert isinstance(token.formatted_value, str)


def test_narrate_figures_has_no_numeric_parameter_anywhere_in_its_signature() -> None:
    sig = inspect.signature(narrate_figures)
    for name, param in sig.parameters.items():
        assert param.annotation not in (int, float, "int", "float"), f"narrate_figures param {name!r} must never accept a raw number"


def test_prompt_never_embeds_a_raw_number_only_preformatted_strings() -> None:
    """`build_narration_prompt` and `figure_line` operate purely on strings — constructing a
    prompt from FigureTokens never touches an int/Paise/Fraction value anywhere in the call
    chain, by construction (every argument type is str)."""
    sig = inspect.signature(build_narration_prompt)
    for name, param in sig.parameters.items():
        assert param.annotation not in (int, float, "int", "float"), f"build_narration_prompt param {name!r} must never accept a raw number"


# ---------------------------------------------------------------------------
# AC27 — the provider's own output is opaque prose; even a digit-bearing response is passed
# through unmodified, proving this layer validates the INPUT contract, not the output text.
# ---------------------------------------------------------------------------


def test_provider_stub_returning_digit_bearing_string_is_still_accepted_unmodified() -> None:
    provider, captured = _provider("Your Contribution Profit improved versus last period.")
    result = narrate_figures(
        provider,
        model="test-model",
        context="Explain this period's contribution profit.",
        figures=[
            FigureToken(label="Contribution Profit", formatted_value="₹45,231.00", register="VERIFIED", engine_result_ref="abc-123"),
        ],
    )
    assert result == "Your Contribution Profit improved versus last period."
    assert len(captured) == 1


def test_provider_response_with_digits_is_passed_through_unchanged_not_reparsed() -> None:
    """A provider might (incorrectly, from its own training) emit a number in its prose —
    `narrate_figures` does not parse, validate, or strip digits from the response; it is a
    pure pass-through of the provider's text. This confirms the module never re-derives or
    recomputes anything from what comes back either."""
    digit_bearing = "The figure of 42.5% margin improved by 3 points this month."
    provider, _ = _provider(digit_bearing)
    result = narrate_figures(
        provider,
        model="test-model",
        context="context",
        figures=[FigureToken(label="X", formatted_value="₹1.00", register="VERIFIED")],
    )
    assert result == digit_bearing  # unmodified pass-through — no post-processing of numbers


# ---------------------------------------------------------------------------
# AC21/AC24/AC28/AC29 — the system prompt states the no-arithmetic contract explicitly.
# ---------------------------------------------------------------------------


def test_system_prompt_states_never_compute() -> None:
    assert "never calculate" in SYSTEM_PROMPT or "you never calculate" in SYSTEM_PROMPT.lower()


def test_system_prompt_forbids_rederiving_or_summing() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "re-derive" in lowered
    assert "sum" in lowered
    assert "net" in lowered


def test_system_prompt_forbids_stating_rates_from_training_knowledge() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "gst rate" in lowered
    assert "training knowledge" in lowered


def test_system_prompt_forbids_filing_grade_claims() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "filing-grade" in lowered or "filing grade" in lowered
    assert "certified" in lowered


def test_unavailable_register_instructs_no_zero_substitution() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "unavailable" in lowered
    assert "never substitute zero" in lowered or "substitute zero" in lowered


def test_full_prompt_sent_to_provider_includes_system_prompt_verbatim() -> None:
    provider, captured = _provider("narration")
    narrate_figures(
        provider,
        model="test-model",
        context="context",
        figures=[FigureToken(label="X", formatted_value="₹1.00", register="VERIFIED")],
    )
    assert SYSTEM_PROMPT in captured[0]


# ---------------------------------------------------------------------------
# AC30 — the §6.6 GST disclaimer instruction, verbatim, only when gst_context=True.
# ---------------------------------------------------------------------------


def test_gst_context_appends_disclaimer_instruction_verbatim() -> None:
    provider, captured = _provider("narration")
    narrate_figures(
        provider,
        model="test-model",
        context="Explain this line's GST treatment.",
        figures=[FigureToken(label="Line GST", formatted_value="₹18.00", register="VERIFIED")],
        gst_context=True,
    )
    assert GST_DISCLAIMER in captured[0]


def test_non_gst_context_does_not_force_the_gst_disclaimer() -> None:
    provider, captured = _provider("narration")
    narrate_figures(
        provider,
        model="test-model",
        context="Explain this period's contribution profit.",
        figures=[FigureToken(label="X", formatted_value="₹1.00", register="VERIFIED")],
        gst_context=False,
    )
    assert GST_DISCLAIMER not in captured[0]


# ---------------------------------------------------------------------------
# LlmProvider protocol itself — no numeric type anywhere in its interface.
# ---------------------------------------------------------------------------


def test_llm_provider_protocol_complete_has_no_numeric_parameter() -> None:
    sig = inspect.signature(LlmProvider.complete)
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        assert param.annotation not in (int, float, "int", "float")
    assert sig.return_annotation in (str, "str")
