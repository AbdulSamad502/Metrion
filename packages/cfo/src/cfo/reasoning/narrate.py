"""`narrate_figures` — composes a prompt from already-computed figures and calls the
`LlmProvider`, returning prose. cfo-agent.md §7.4.9: "Brain 3 may interpret, explain and
narrate figures Brain 1 has already computed. It may never [...] perform arithmetic [...]
re-derive [...] sum, net, or otherwise combine [...] figures."

`FigureToken.formatted_value` is a `str`, not an `int`/`Paise`/`Fraction` — this is the
structural enforcement of that rule at this layer's boundary: there is no numeric parameter
anywhere in this module's public surface for an LLM prompt to be built from, so there is
nothing here an LLM could be tempted to compute with even if it tried. The caller (e.g.
`backend.services.cfo_actions`) is responsible for formatting each `MetricResult.value_paise`
into a display string (rupee-formatted, or "UNAVAILABLE") *before* calling this module —
that formatting is presentation, not calculation, and stays outside the deterministic engine
by the same logic the frontend's own no-float rule applies to money display.
"""

from __future__ import annotations

from dataclasses import dataclass

from cfo.reasoning.prompts import SYSTEM_PROMPT, build_narration_prompt, figure_line
from cfo.reasoning.provider import LlmProvider


@dataclass(frozen=True, slots=True)
class FigureToken:
    """One already-computed figure, passed to Brain 3 as an opaque display string plus its
    §7.4.7 register — never a number this layer could operate on."""

    label: str
    formatted_value: str  # e.g. "₹12,345.00" or "UNAVAILABLE" — pre-formatted by the caller
    register: str  # VERIFIED | DERIVED | MANUAL | ESTIMATE | UNAVAILABLE (§7.4.7)
    engine_result_ref: str | None = None  # provenance citation, never used in arithmetic here
    note: str | None = None


def narrate_figures(
    provider: LlmProvider,
    *,
    model: str,
    context: str,
    figures: list[FigureToken],
    gst_context: bool = False,
) -> str:
    """Builds the prompt from `figures` (each already-formatted) and returns the provider's
    prose response unchanged. This function performs no arithmetic and inspects no numeric
    field — `figures` carries only strings plus a provenance ref it never dereferences."""
    figure_lines = [
        figure_line(label=f.label, formatted_value=f.formatted_value, register=f.register, note=f.note)
        for f in figures
    ]
    prompt = build_narration_prompt(context=context, figure_lines=figure_lines, gst_context=gst_context)
    full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
    return provider.complete(model=model, prompt=full_prompt)
