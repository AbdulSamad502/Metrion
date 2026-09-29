"""`check_narration_safety` — a mechanical post-hoc check on Brain 3's own output, against the
`FigureToken`s it was given. CLAUDE.md's LLM-evals requirement for any new Brain-3 narration
surface: "does it ever state a number not present in its cited figures... does it narrate a
non-result... as if it were a real negative result."

**What this checks, honestly scoped — two properties, not a general correctness guarantee:**

1. **No fabricated number.** Every numeric substring in the narrative (currency amounts,
   percentages, plain counts) must appear, in normalized form, among the `formatted_value`
   strings of the `FigureToken`s it was given. A number that appears nowhere in the source
   figures is flagged as a possible fabrication.
2. **No silent UNAVAILABLE-as-real.** For every `FigureToken` at `register == "UNAVAILABLE"`,
   if its `label` appears in the narrative text, an "unavailable"-family word must appear near
   it — otherwise the narrative may be presenting a missing figure as if it had a real value.

**What this does NOT check, and does not claim to.** Whether the narrative recommends a
DIFFERENT action than the one deterministically assigned (§7.4.9 rule 2's "propose no action
other than the deterministically-assigned one") is a structural guarantee, not a text-scannable
one in this codebase: `recommended_action_type` never reaches the LLM as a free-choice — it is
fixed before the prompt is built (`cfo.reasoning.signals.compose_strategic_signals`) and the
narration prompt never asks the model to choose or suggest an action at all, only to explain the
figures. This module does not attempt a second, weaker text-based check of a property the
architecture already enforces structurally, since a heuristic here could create false confidence
about a class of failure the prompt shape does not admit in the first place.

**Number extraction is a heuristic, not a proof.** Free text can express a real, cited number in
a way this regex misses (e.g. spelled out, or reformatted with different rounding) — a false
positive is possible and should be reviewed, not auto-rejected. This module is a real, useful
safety net, not a formal verifier; its own limits are stated here rather than implied away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cfo.reasoning.narrate import FigureToken

# Matches a currency amount (₹12,345.00 / Rs. 500 / INR 1,234), a percentage (12.5%), or a
# plain integer of 2+ digits (single digits are excluded — too many false positives from
# ordinary prose like "one line", "a 2-day lag").
_NUMBER_PATTERN = re.compile(
    r"(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*%|\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b"
)

_UNAVAILABLE_WORDS = ("unavailable", "not available", "no data", "missing", "unknown", "cannot be")


def _normalize_number(raw: str) -> str:
    """Strips currency symbols, the word Rs/INR, percent signs, commas and surrounding
    whitespace — leaves just the digits (and decimal point) so "₹12,345.00" and "12345.00"
    compare equal, matching how a seller reads the same figure in two different renderings."""
    stripped = re.sub(r"[₹%,]|Rs\.?|INR", "", raw, flags=re.IGNORECASE)
    return stripped.strip()


def _numbers_in(text: str) -> set[str]:
    return {_normalize_number(m) for m in _NUMBER_PATTERN.findall(text)}


@dataclass(frozen=True, slots=True)
class NarrationSafetyResult:
    is_safe: bool
    fabricated_numbers: tuple[str, ...]  # normalized numbers found in the narrative but not in any figure
    unavailable_figures_stated_as_real: tuple[str, ...]  # labels of UNAVAILABLE figures with no "unavailable" cue nearby


def check_narration_safety(narrative: str, figures: list[FigureToken]) -> NarrationSafetyResult:
    source_numbers: set[str] = set()
    for figure in figures:
        source_numbers |= _numbers_in(figure.formatted_value)

    narrative_numbers = _numbers_in(narrative)
    fabricated = tuple(sorted(narrative_numbers - source_numbers))

    lowered_narrative = narrative.lower()
    unavailable_stated_as_real: list[str] = []
    for figure in figures:
        if figure.register != "UNAVAILABLE":
            continue
        label_lower = figure.label.lower()
        idx = lowered_narrative.find(label_lower)
        if idx == -1:
            continue  # the narrative never mentions this figure at all — nothing to flag
        # Look at a window around the mention for an "unavailable"-family word — narrow enough
        # to require genuine proximity, wide enough to survive ordinary phrasing like
        # "Fee Ratio Pct is not available this period".
        window_start = max(0, idx - 20)
        window_end = min(len(lowered_narrative), idx + len(label_lower) + 60)
        window = lowered_narrative[window_start:window_end]
        if not any(word in window for word in _UNAVAILABLE_WORDS):
            unavailable_stated_as_real.append(figure.label)

    is_safe = not fabricated and not unavailable_stated_as_real
    return NarrationSafetyResult(
        is_safe=is_safe,
        fabricated_numbers=fabricated,
        unavailable_figures_stated_as_real=tuple(unavailable_stated_as_real),
    )
