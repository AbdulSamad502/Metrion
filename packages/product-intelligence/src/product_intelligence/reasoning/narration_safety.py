"""`check_narration_safety` — PI's copy of `cfo.reasoning.narration_safety`'s mechanism
(regex number-diff against `FigureToken`s, `UNAVAILABLE`-stated-as-real check), extended with
three PI-specific checks per the build plan §2/§0:

1. **Estimate-range language required** whenever a `product_feasibility_estimate` (or an
   `UNKNOWN`-cogs-basis batch-size figure, §3's CFO handoff) is narrated — not testable yet
   against a real CFO handoff (Phase 2), but the check function is built now so Phase 2 can
   call it without a second implementation pass.
2. **No "trending"/"bestseller"/"popular" language anywhere in narrated text** (§0a) — a
   structural echo of `ranking.py`'s own output-contract discipline, checked here on Brain 3's
   free-text output where the architecture can't enforce it by construction.
3. **"review" never appears unqualified** by "viewer"/"web" when narrating a
   `product_review_insight` figure (§0b).

This package has no dependency on `packages/cfo` (see `pyproject.toml`), so `FigureToken`
below is PI's own copy of the same three-field shape (`label`, `formatted_value`, `register`)
— not an import, a deliberate structural duplicate, since the two packages' narration surfaces
are independent Brain-3 call sites that happen to share a design, not a shared library
dependency.

Same stated limits as CFO's version: number extraction is a heuristic (a real, cited number
expressed unusually can produce a false positive — review, don't auto-reject), and this module
checks text-scannable properties only, never a structural correctness guarantee.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NUMBER_PATTERN = re.compile(
    r"(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*%|\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b"
)

_UNAVAILABLE_WORDS = ("unavailable", "not available", "no data", "missing", "unknown", "cannot be")

_TRENDING_WORDS = ("trending", "bestseller", "best-seller", "best seller", "popular")

_ESTIMATE_QUALIFIER_WORDS = (
    "estimate", "estimated", "estimated range", "approximate", "approximately", "range",
    "not confirmed", "not a guarantee", "rough",
)

_REVIEW_QUALIFIERS = ("viewer", "web")


@dataclass(frozen=True, slots=True)
class FigureToken:
    label: str
    formatted_value: str
    register: str  # VERIFIED | DERIVED | MANUAL | ESTIMATE | UNAVAILABLE


def _normalize_number(raw: str) -> str:
    stripped = re.sub(r"[₹%,]|Rs\.?|INR", "", raw, flags=re.IGNORECASE)
    return stripped.strip()


def _numbers_in(text: str) -> set[str]:
    return {_normalize_number(m) for m in _NUMBER_PATTERN.findall(text)}


@dataclass(frozen=True, slots=True)
class NarrationSafetyResult:
    is_safe: bool
    fabricated_numbers: tuple[str, ...]
    unavailable_figures_stated_as_real: tuple[str, ...]
    trending_language_found: tuple[str, ...]  # §0a check 2
    estimate_figures_missing_qualifier: tuple[str, ...]  # check 1
    unqualified_review_mentions: bool  # §0b check 3


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
            continue
        window_start = max(0, idx - 20)
        window_end = min(len(lowered_narrative), idx + len(label_lower) + 60)
        window = lowered_narrative[window_start:window_end]
        if not any(word in window for word in _UNAVAILABLE_WORDS):
            unavailable_stated_as_real.append(figure.label)

    # Check 2 (§0a): "trending"/"bestseller"/"popular" never appears anywhere in narrated text.
    trending_found = tuple(sorted({word for word in _TRENDING_WORDS if word in lowered_narrative}))

    # Check 1: every ESTIMATE-register figure narrated must have estimate-qualifying language
    # nearby — same proximity-window technique as the UNAVAILABLE check above.
    estimate_missing_qualifier: list[str] = []
    for figure in figures:
        if figure.register != "ESTIMATE":
            continue
        label_lower = figure.label.lower()
        idx = lowered_narrative.find(label_lower)
        if idx == -1:
            continue
        window_start = max(0, idx - 40)
        window_end = min(len(lowered_narrative), idx + len(label_lower) + 80)
        window = lowered_narrative[window_start:window_end]
        if not any(word in window for word in _ESTIMATE_QUALIFIER_WORDS):
            estimate_missing_qualifier.append(figure.label)

    # Check 3 (§0b): "review" never appears unqualified by "viewer"/"web" — scans every
    # occurrence of the bare word "review"/"reviews" (word-boundary) and requires one of the
    # qualifier words within a nearby window; "viewer review(s)"/"web review(s)" pass, a bare
    # "reviews say..." does not.
    unqualified_review_found = False
    for match in re.finditer(r"\breview(s)?\b", lowered_narrative):
        window_start = max(0, match.start() - 15)
        window_end = min(len(lowered_narrative), match.end() + 15)
        window = lowered_narrative[window_start:window_end]
        if not any(qualifier in window for qualifier in _REVIEW_QUALIFIERS):
            unqualified_review_found = True
            break

    is_safe = (
        not fabricated
        and not unavailable_stated_as_real
        and not trending_found
        and not estimate_missing_qualifier
        and not unqualified_review_found
    )

    return NarrationSafetyResult(
        is_safe=is_safe,
        fabricated_numbers=fabricated,
        unavailable_figures_stated_as_real=tuple(unavailable_stated_as_real),
        trending_language_found=trending_found,
        estimate_figures_missing_qualifier=tuple(estimate_missing_qualifier),
        unqualified_review_mentions=unqualified_review_found,
    )
