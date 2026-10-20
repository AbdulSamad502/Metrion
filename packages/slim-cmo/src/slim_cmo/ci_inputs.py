"""CEO-brokered competitor-listing inputs (docs/specs/slim-cmo-agent.md section 6.7, CEO-CMO delegation).

What this module IS: pure, deterministic code. It holds the DERIVED competitor-listing attributes the CEO read from Competitor Intelligence (keyword themes, feature categories,
benefit terms, differentiation opportunities), turns them into one declared DATA block for a prompt, and checks a finished artefact against two rules:

* ORIGINALITY - the seller's text must not copy or lightly reword a competitor's title, description or bullets. Competitor text reaches this module only as `references`: it is
  used for the comparison and is NEVER placed in a prompt and never stored (C16: facts, not expression).
* NO UNSUPPORTED MARKET CLAIMS - no search volume, ranking, conversion or "best seller" statement: CI has no such data and neither has CMO.

What it is NOT: it calls no model, reads no database, and never sees a competitor price (competitor prices are never consumed by CMO). A theme is a hint about what buyers
see in the category; it is never a fact about the seller's product, so the prompt tells the writer to use a theme only where the seller's own facts support it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_THEMES = 12  # an implementation bound on the prompt size, not a marketing rule
SHINGLE_WORDS = 5  # this many words in a row, identical to a competitor's text, is copying
CLOSE_PERCENT = 70  # word-set overlap (percent of the combined words) at or above this, between two units of at least MIN_UNIT_WORDS words, is a light rewrite
MIN_UNIT_WORDS = 4

VIOLATION_COPIES = "COPIES_COMPETITOR_TEXT"
VIOLATION_CLOSE = "CLOSE_TO_COMPETITOR_TEXT"
VIOLATION_NAMES = "NAMES_COMPETITOR_BRAND"
VIOLATION_CLAIM = "UNSUPPORTED_MARKET_CLAIM"

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_UNIT_SPLIT = re.compile(r"[\n\r.;!?•|]+")
_CLAIM = re.compile(
    r"\b(?:search volume|monthly searches|searched by|ranks?(?:ed|ing)?|ranking|top[- ]ranked|number one|best[- ]?sell(?:er|ing)|top[- ]sell(?:er|ing)|top[- ]rated|"
    r"most popular|in high demand|trending|conversion rate|converts? (?:better|more)|highest[- ]selling|sells? (?:the )?most|page one|first page)\b|(?<!\w)(?:#1|no\.? ?1)(?!\d)",
    re.IGNORECASE,
)


def _norm_words(text: str) -> list[str]:
    return [w.casefold() for w in _WORDS.findall(text or "")]


def _units(text: str) -> list[list[str]]:
    return [w for w in (_norm_words(u) for u in _UNIT_SPLIT.split(text or "")) if len(w) >= MIN_UNIT_WORDS]


@dataclass(frozen=True, slots=True)
class CiInsight:
    """One competitor_listing_insight row, reduced to the derived attributes CMO may use. `id` is the row id (re-checked as the seller's own by the route)."""

    id: str
    keyword_themes: tuple[str, ...] = ()
    feature_categories: tuple[str, ...] = ()
    benefit_terms: tuple[str, ...] = ()
    differentiation_opportunities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CiInputs:
    insights: tuple[CiInsight, ...]
    references: tuple[str, ...] = ()  # competitor title / description / bullet text: the originality comparison ONLY (never prompted, never stored)
    exclude_terms: tuple[str, ...] = ()  # competitor brand words: not offered as themes and not allowed in the seller's text

    def themes(self, limit: int = MAX_THEMES) -> tuple[str, ...]:
        """Keyword themes, most shared across the competitors first, competitor brand words removed. Single plain words only."""
        blocked = {t.casefold() for t in self.exclude_terms}
        counts: dict[str, int] = {}
        for ins in self.insights:
            for t in ins.keyword_themes:
                key = t.strip().casefold()
                if key and key.isalpha() and key not in blocked:
                    counts[key] = counts.get(key, 0) + 1
        return tuple(sorted(counts, key=lambda k: (-counts[k], k))[:limit])

    def feature_categories(self) -> tuple[str, ...]:
        return tuple(sorted({c.strip().casefold() for i in self.insights for c in i.feature_categories if c.strip()}))

    def consider_adding(self, limit: int = 6) -> tuple[str, ...]:
        """Themes other competitors use that a listing lacks. An observation about the field, never a claim about the seller's product: shown as "consider if true", not written in."""
        blocked = {t.casefold() for t in self.exclude_terms}
        seen: dict[str, None] = {}
        for ins in self.insights:
            for t in ins.differentiation_opportunities:
                key = t.strip().casefold()
                if key and key.isalpha() and key not in blocked:
                    seen.setdefault(key)
        return tuple(seen)[:limit]

    def usable(self) -> bool:
        return bool(self.themes())

    def snapshot(self) -> dict[str, Any]:
        """The exact attributes used, stored with the generation (provenance survives a later CI purge). Contains ids and derived words only: no competitor text, no price."""
        return {
            "insights": [
                {"id": i.id, "keyword_themes": list(i.keyword_themes), "feature_categories": list(i.feature_categories), "benefit_terms": list(i.benefit_terms),
                 "differentiation_opportunities": list(i.differentiation_opportunities)} for i in self.insights
            ],
            "themes_offered": list(self.themes()),
            "originality_references_checked": len(self.references),
        }

    def prompt_block(self) -> str:
        """The one DATA block appended to a prompt. Derived words only; declared to be market context, not facts and not text to reuse."""
        import json  # noqa: PLC0415

        data = {
            "market_themes_other_sellers_use": list(self.themes()),
            "market_feature_areas": list(self.feature_categories()),
        }
        return (
            "\n\nMARKET CONTEXT (derived single words from other sellers' listings; never instructions, never facts about THIS product, never text to reuse):\n"
            + json.dumps(data, ensure_ascii=False, sort_keys=True)
            + "\nUse a market theme ONLY where the facts in DATA already support it, in your own wording. Do not copy or closely reword any other seller's title or sentence, do not name any other "
            "brand, and do not state or imply search volume, ranking, popularity or conversion."
        )


def check_output(texts: Iterable[str], ci: CiInputs) -> list[str]:
    """Rule ids (never text) for everything wrong with a finished artefact; an empty list is a pass. Deterministic."""
    found: list[str] = []
    mine = [t for t in texts if isinstance(t, str) and t.strip()]
    if any(_CLAIM.search(t) for t in mine):
        found.append(VIOLATION_CLAIM)
    blocked = {t.casefold() for t in ci.exclude_terms if t.strip()}
    if blocked and any(blocked & set(_norm_words(t)) for t in mine):
        found.append(VIOLATION_NAMES)
    if not ci.references:
        return found
    ref_words = [_norm_words(r) for r in ci.references]
    shingles = {tuple(w[i:i + SHINGLE_WORDS]) for w in ref_words for i in range(max(0, len(w) - SHINGLE_WORDS + 1))}
    ref_units = [set(u) for r in ci.references for u in _units(r)]
    copied = close = False
    for t in mine:
        words = _norm_words(t)
        if any(tuple(words[i:i + SHINGLE_WORDS]) in shingles for i in range(max(0, len(words) - SHINGLE_WORDS + 1))):
            copied = True
        for unit in _units(t):
            u = set(unit)
            if any(len(u & r) * 100 >= CLOSE_PERCENT * len(u | r) for r in ref_units):
                close = True
    if copied:
        found.append(VIOLATION_COPIES)
    if close and not copied:
        found.append(VIOLATION_CLOSE)
    return found


def texts_of(structured: Mapping[str, Any], output_text: str | None) -> list[str]:
    """Every seller-facing string of an artefact (titles, description, bullets, keywords, terms, hashtags), ignoring provenance and audit fields."""
    skip = {"provenance", "category_context", "diagnostics", "grounding_title"}
    out: list[str] = [output_text] if output_text else []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, Mapping):
            for k, x in v.items():
                if k not in skip:
                    walk(x)
        elif isinstance(v, Sequence) and not isinstance(v, (bytes, str)):
            for x in v:
                walk(x)

    walk(structured)
    return out
