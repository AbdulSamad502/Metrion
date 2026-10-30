"""Claim-gated competitor evidence for the M6 listing (docs/specs/slim-cmo-agent.md section 6.18.6). Pure, no I/O, no new CI contract.

It works ONLY on what `CiInputs` already carries (derived single words from the seller's tracked competitors' saved listings). Whether a theme may be used is decided here, in code:

* SUPPORTED - the theme word is carried by a claim-eligible attribute (name or value) of the seller's product, so the text may use it in the seller's own words;
* CONSIDER_IF_TRUE - the seller's confirmed facts do not carry it. It is shown to the seller as a suggestion to check and is NEVER given to the model and never written.

A competitor feature therefore never becomes a claim about the seller's product, and absence of a theme is never evidence about the seller.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from slim_cmo.ci_inputs import CiInputs, CiInsight
from slim_cmo.claims import Attribute, assess
from slim_cmo.listing.text import words

SUPPORTED, CONSIDER_IF_TRUE = "SUPPORTED", "CONSIDER_IF_TRUE"
LIMITATION = ("Derived words from your tracked competitors' saved listings. Not search demand and not a claim about your product; a theme a competitor lacks is not proof it does not apply.")


def _fact_words(attributes: Sequence[Attribute]) -> set[str]:
    out: set[str] = set()
    for a in attributes:
        if a.value and assess(a).eligible:
            out.update(words(f"{a.name} {a.value}"))
    return out


def evidence_rows(ci: CiInputs | None, attributes: Sequence[Attribute]) -> list[dict[str, Any]]:
    """One row per theme, with how many of the supplied competitor captures carried it (counted, never estimated) and whether the seller's confirmed facts support it."""
    if ci is None or not ci.insights:
        return []
    fact_words = _fact_words(attributes)
    total = len(ci.insights)
    rows: dict[str, dict[str, Any]] = {}

    def add(theme: str, insight: CiInsight, source: str) -> None:
        r = rows.setdefault(theme, {"theme": theme, "sharedBy": {"count": 0, "of": total}, "support": SUPPORTED if theme in fact_words else CONSIDER_IF_TRUE,
                                    "insightIds": [], "sources": [], "limitation": LIMITATION})
        if insight.id not in r["insightIds"]:
            r["insightIds"].append(insight.id)
            r["sharedBy"]["count"] += 1
        if source not in r["sources"]:
            r["sources"].append(source)

    blocked = {t.casefold() for t in ci.exclude_terms}
    for ins in ci.insights:
        for t in ins.keyword_themes:
            key = t.strip().casefold()
            if key and key.isalpha() and key not in blocked:
                add(key, ins, "keyword_themes")
        for t in ins.differentiation_opportunities:
            key = t.strip().casefold()
            if key and key.isalpha() and key not in blocked:
                add(key, ins, "differentiation_opportunities")
    return sorted(rows.values(), key=lambda r: (r["support"] != SUPPORTED, -r["sharedBy"]["count"], r["theme"]))


def supported_only(ci: CiInputs | None, attributes: Sequence[Attribute]) -> CiInputs | None:
    """The competitor inputs the model may see: only themes the seller's confirmed facts support. Everything else is withheld from the prompt. None when nothing is supported."""
    if ci is None:
        return None
    ok = {r["theme"] for r in evidence_rows(ci, attributes) if r["support"] == SUPPORTED}
    if not ok:
        return None
    trimmed = tuple(replace(i, keyword_themes=tuple(t for t in i.keyword_themes if t.strip().casefold() in ok), benefit_terms=(), differentiation_opportunities=()) for i in ci.insights)
    narrowed = replace(ci, insights=trimmed)
    return narrowed if narrowed.usable() else None


def consider_if_true(rows: Sequence[dict[str, Any]]) -> list[str]:
    return [r["theme"] for r in rows if r["support"] == CONSIDER_IF_TRUE]
