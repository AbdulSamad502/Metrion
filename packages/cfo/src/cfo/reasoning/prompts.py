"""Prompt templates for Brain 3 narration — cfo-agent.md §7.4.6/§7.4.7/§7.4.8/§7.4.9.

Every template here composes from **already-formatted strings** the caller supplies (a
figure's label, its pre-rounded display value, and its §7.4.7 register) — never a raw `int`,
`Paise`, or `Fraction`. That is enforced at the type level in `narrate.py`'s `FigureToken`
(all string fields), not just by convention here.
"""

from __future__ import annotations

# cfo-agent.md §7.4.9 — restated verbatim in the system prompt so the model is told, not just
# trusted, never to compute.
SYSTEM_PROMPT = (
    "You are Metrion's CFO agent, Brain 3 — a narration layer only. Every figure you are given "
    "has already been computed by a deterministic engine (Brain 1); you never calculate, "
    "re-derive, sum, net, round, or 'sanity-check' any number. You only explain, in plain "
    "Indian CA/CFO vocabulary, what the given figures mean and why they matter. If a figure is "
    "marked UNAVAILABLE, say so plainly and never substitute zero or a guess. Never state a GST "
    "rate, fee percentage, or any other rate from your own training knowledge — only the rates "
    "you are explicitly given. Never claim a number is filing-grade, certified, or compliance-"
    "ready. "
    "A few more domain rules you must never drift on: the three RTO outcomes — recovered-"
    "sellable, recovered-damaged, and lost-in-transit — are separate outcomes and must never be "
    "collapsed into one bucket, even informally. TCS and TDS are cash items, never P&L items — "
    "never describe them as reducing profit. A discount's bearer (seller, marketplace, or "
    "unknown) is stated using exactly the tag you were given; you never infer or reclassify who "
    "bears a discount yourself. Reconciliation, in this product, means the invoice-vs-"
    "settlement delta for a single component — never call it an audit or an accounting review, "
    "which overstates what this check does. Metrion computes Contribution Profit, not EBITDA or "
    "PAT — you may use those terms only to explain the profit ladder conceptually, never as a "
    "number you state as a result."
)

# cfo-agent.md §7.4.7 — the five registers Brain 3's language must map onto, verbatim labels.
REGISTER_DESCRIPTIONS: dict[str, str] = {
    "VERIFIED": "Verified data — an engine figure at VERIFIED confidence.",
    "DERIVED": "Derived analysis — an engine figure at DERIVED confidence (e.g. an allocated pool).",
    "MANUAL": "An assumption you've entered — a MANUAL confidence figure sourced from a manual_adjustment.",
    "ESTIMATE": "An estimate — CI-sourced, estimate_ref-bearing, never presented as engine-verified.",
    "UNAVAILABLE": "Not available — flagged, explained, never defaulted to zero.",
}

# cfo-agent.md §6.6 — verbatim, mandatory on every GST surface.
GST_DISCLAIMER = (
    "Indicative management summary. Not a GST return. Not filing-grade. "
    "Verify with your tax professional."
)


def figure_line(*, label: str, formatted_value: str, register: str, note: str | None = None) -> str:
    """One line of the prompt's figure block — plain string composition, no arithmetic."""
    register_text = REGISTER_DESCRIPTIONS.get(register, register)
    line = f"- {label}: {formatted_value} ({register_text})"
    if note:
        line += f" — {note}"
    return line


def build_narration_prompt(
    *,
    context: str,
    figure_lines: list[str],
    gst_context: bool = False,
) -> str:
    """Assembles the user-turn prompt: a plain-language context sentence the caller supplies,
    followed by the figure block, followed (when relevant) by the §6.6 disclaimer instruction.
    Returns text only — this function never touches a numeric type."""
    parts = [context, "", "Figures (already computed — narrate these, do not recompute them):", *figure_lines]
    if gst_context:
        parts.append("")
        parts.append(f"Include this disclaimer verbatim, once: \"{GST_DISCLAIMER}\"")
    return "\n".join(parts)
