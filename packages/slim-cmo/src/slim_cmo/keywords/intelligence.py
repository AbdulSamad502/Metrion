"""Evidence-backed keyword intelligence (CMO 3.0 M2; docs/specs/slim-cmo-agent.md section 6.14).

What this module IS: pure, deterministic code. From the seller's own CONFIRMED facts it builds keyword candidates, and for each one it states - by named rules, never by a model - how
relevant it is to THIS product, what kind of buyer search it matches (intent), where it belongs in a listing (placement), how much evidence supports it, and where that evidence came from.
Wording that needs a product claim the seller never confirmed ("insulated", "leakproof", "dishwasher safe"...) is listed as EXCLUDED with the reason, never offered.

What it is NOT: it calls no model, reads no database, and has no source of search volume, buyer demand, marketplace ranking or sales. Those fields are always `NOT_ASSESSED` - they are
never zero and never estimated. "Relevance" and "confidence" here are about the fit with the seller's own product and the evidence behind that fit, NOT about how often anyone searches.
Competitor evidence is the DERIVED theme words the CEO brokered from Competitor Intelligence (no competitor text, no price); a theme is a hint about the field, never a fact about the product.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from slim_cmo.claims import Attribute, assess
from slim_cmo.types import Marketplace

METHOD = "keyword-intel-v1"
NOT_ASSESSED = "NOT_ASSESSED"
MAX_WORDS = 6
MAX_CANDIDATES = 15

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset({"a", "an", "the", "for", "of", "and", "with", "in", "to", "by", "on"})

# Product claims that are true only if the seller says so. A candidate that needs one of these, with no confirmed fact behind it, is excluded. Closed list; a stem is matched as a whole word.
CLAIM_TERMS: Mapping[str, tuple[str, ...]] = {
    "insulated": ("insulated", "insulation", "thermal", "vacuum"), "leakproof": ("leakproof", "leak", "spillproof", "spill"), "dishwasher safe": ("dishwasher",),
    "microwave safe": ("microwave",), "freezer safe": ("freezer",), "waterproof": ("waterproof",), "BPA free": ("bpa",), "rustproof": ("rustproof", "rust"),
    "food grade": ("food",), "heat resistant": ("heat",), "unbreakable": ("unbreakable", "shatterproof"), "non toxic": ("toxic",), "hot and cold": ("hot", "cold"),
}
_USE_CASES = frozenset({"gym", "school", "office", "travel", "kids", "daily", "home", "camping", "running", "hiking", "sports", "yoga", "college", "outdoor", "everyday", "work"})
_UNITS = frozenset({"litre", "litres", "liter", "liters", "l", "ml", "kg", "g", "gm", "gram", "grams", "cm", "mm", "inch", "inches", "oz", "pcs", "piece", "pieces", "pack", "set"})
_SIZE_ATTRS = frozenset({"size", "capacity", "volume", "weight", "dimensions"})
_COLOR_ATTRS = frozenset({"color", "colour"})
_USE_ATTRS = frozenset({"main use", "use", "key features", "features"})
_PRIORITY = {"TITLE": 0, "BULLETS": 1, "DESCRIPTION": 2, "BACKEND_TERMS": 3, "KEYWORDS": 3}


def _words(text: str) -> list[str]:
    return [w.casefold() for w in _WORDS.findall(text or "")]


def _content(words: Iterable[str]) -> list[str]:
    return [w for w in words if w not in _STOP]


@dataclass(frozen=True, slots=True)
class CiTheme:
    """One derived theme word and how many of the seller's tracked competitors' saved listings carried it (counted, not estimated)."""

    word: str
    insight_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KeywordInputs:
    product_name: str | None
    brand: str | None
    attributes: tuple[Attribute, ...]  # eligible + ineligible, as assessed by the claims rules
    fact_ids: tuple[str, ...]
    ci_themes: tuple[CiTheme, ...] = ()
    ci_insight_count: int = 0
    niche_terms: tuple[str, ...] = ()  # CONFIRMED by the seller
    marketplace: Marketplace | None = None


def _eligible(attrs: Sequence[Attribute]) -> list[Attribute]:
    return [a for a in attrs if a.value and assess(a).eligible]


def _claim_in(words: Iterable[str]) -> str | None:
    ws = set(words)
    for claim, stems in CLAIM_TERMS.items():
        if any(s in ws for s in stems):
            return claim
    return None


def _claim_confirmed(claim: str, eligible: Sequence[Attribute], product_words: set[str]) -> bool:
    stems = set(CLAIM_TERMS[claim])
    return any(stems & set(_words(f"{a.name} {a.value}")) for a in eligible) or bool(stems & product_words)


def _intent(words: list[str], inp: KeywordInputs, claim: str | None, size_words: set[str]) -> str:
    brand = set(_words(inp.brand or ""))
    if brand and brand & set(words):
        return "BRAND"
    if claim:
        return "FEATURE"
    if any(w in _USE_CASES for w in words):
        return "USE_CASE"
    if size_words & set(words) or any(w.isdigit() or w in _UNITS for w in words):
        return "SPECIFICATION"
    return "PRODUCT_TYPE"


def analyse(inp: KeywordInputs) -> dict[str, Any]:
    """The whole analysis as plain data (no floats, no money, no unassessed number)."""
    elig = _eligible(inp.attributes)
    brand_words = set(_words(inp.brand or ""))
    name_words = _words(inp.product_name or "")
    by_name = {a.name.casefold(): a for a in elig}
    size_vals = [a.value for a in elig if a.name.casefold() in _SIZE_ATTRS and a.value]
    size_words = {w for v in size_vals for w in _words(v)}
    material = next((a.value for a in elig if a.name.casefold() == "material" and a.value), None)
    material_words = set(_words(material or ""))
    color = next((a.value for a in elig if a.name.casefold() in _COLOR_ATTRS and a.value), None)
    fact_words = set(name_words) | brand_words | size_words | material_words | set(_words(color or "")) | {w for a in elig for w in _words(f"{a.name} {a.value}")}
    product_words = set(name_words)
    core = [w for w in name_words if w not in brand_words and w not in size_words and not w.isdigit() and w not in _UNITS and w not in _STOP]
    broad = [w for w in core if w not in material_words] or core

    if not elig and not name_words:
        return {"method": METHOD, "status": "NO_FACTS", "candidates": [], "excluded": [], "limits": _limits(inp),
                "needs": ["the product name", "a few confirmed details (brand, size, material, colour)"], "evidence": _evidence(inp, elig)}

    # ---- seeds: (text words, evidence kind, evidence detail)
    seeds: list[tuple[list[str], str, str]] = []

    def seed(ws: list[str], kind: str, detail: str) -> None:
        ws = [w for w in ws if w]
        if 1 <= len(ws) <= MAX_WORDS:
            seeds.append((ws, kind, detail))

    if core:
        seed(core, "SELLER_FACT", "your product name")
    if broad and broad != core:
        seed(broad, "SELLER_FACT", "your product name")
    if size_vals and broad:
        seed([*_words(size_vals[0]), *broad], "SELLER_FACT", "your product name and size")
    if color and broad:
        seed([*_words(color), *broad], "SELLER_FACT", "your product name and colour")
    if brand_words and broad:
        seed([*_words(inp.brand or ""), *broad], "SELLER_FACT", "your brand and product name")
    for a in elig:
        if a.name.casefold() in _USE_ATTRS and a.value:
            for part in re.split(r"[,;/]", a.value):
                pw = _words(part)
                if 1 <= len(pw) <= 3 and broad:
                    seed([*pw, *broad], "SELLER_FACT", f"your {a.name.casefold()}")
    for t in inp.ci_themes:
        if broad:
            seed([t.word, *broad], "CI_THEME", f"{len(t.insight_ids)} of {inp.ci_insight_count} tracked competitor listing(s)")
    for term in inp.niche_terms:
        seed(_words(term), "NICHE_TERM", "a niche term you confirmed")

    # ---- merge by text, exclude unconfirmed claims
    merged: dict[str, dict[str, Any]] = {}
    excluded: dict[str, dict[str, Any]] = {}
    for ws, kind, detail in seeds:
        text = " ".join(ws)
        claim = _claim_in(ws)
        if claim and not _claim_confirmed(claim, elig, product_words):
            ex = excluded.setdefault(text, {"keyword": text, "claim": claim, "reason": f"Needs the claim “{claim}”, which you have not confirmed for this product. It is not offered.", "evidence": []})
            ex["evidence"].append({"kind": kind, "detail": detail})
            continue
        c = merged.setdefault(text, {"keyword": text, "words": ws, "claim": claim, "evidence": []})
        if not any(e["kind"] == kind and e["detail"] == detail for e in c["evidence"]):
            c["evidence"].append({"kind": kind, "detail": detail})
    for a in inp.attributes:  # a claim carried only by an unverified hint or an estimate is named, not offered
        if a.value and not assess(a).eligible:
            claim = _claim_in(_words(f"{a.name} {a.value}"))
            if claim and not _claim_confirmed(claim, elig, product_words):
                excluded.setdefault(f"{a.name} {a.value}".casefold(), {"keyword": f"{a.name} {a.value}".casefold(), "claim": claim, "reason": f"“{claim}” is only a suggestion or estimate, not something you confirmed. It is not offered.", "evidence": []})

    candidates: list[dict[str, Any]] = []
    for text, c in merged.items():
        ws, claim = c["words"], c["claim"]
        content = _content(ws)
        supported = [w for w in content if w in fact_words]  # a confirmed niche term is corroboration, never proof of fit with THIS product
        share = (len(supported), len(content))
        relevance = "HIGH" if share[0] == share[1] else "MEDIUM" if share[0] * 2 >= share[1] else "LOW"
        kinds = {e["kind"] for e in c["evidence"]}
        external = bool(kinds & {"CI_THEME", "NICHE_TERM"})
        confidence = NOT_ASSESSED if not c["evidence"] else ("STRONG" if relevance == "HIGH" and external and "SELLER_FACT" in kinds else "MODERATE" if relevance == "HIGH" else "WEAK")
        intent = _intent(ws, inp, claim, size_words)
        placement = _placement(intent, relevance, text, bool(size_vals), inp.marketplace)
        theme = next((t for t in inp.ci_themes if t.word in ws), None)
        candidates.append({
            "keyword": text, "intent": intent, "placement": placement, "relevance": relevance,
            "relevanceBasis": f"{share[0]} of {share[1]} words are backed by your confirmed facts or product name", "confidence": confidence, "evidence": c["evidence"],
            "competitorOccurrence": ({"status": "OBSERVED", "listings": len(theme.insight_ids), "of": inp.ci_insight_count} if theme else {"status": NOT_ASSESSED}),
            "searchVolume": NOT_ASSESSED, "buyerDemand": NOT_ASSESSED, "marketplaceRank": NOT_ASSESSED,
            "recommended": relevance != "LOW",
        })
    candidates.sort(key=lambda c: (not c["recommended"], _PRIORITY[c["placement"][0]], {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[c["relevance"]], c["keyword"]))
    return {"method": METHOD, "status": "COMPLETE", "candidates": candidates[:MAX_CANDIDATES], "excluded": sorted(excluded.values(), key=lambda e: e["keyword"]), "limits": _limits(inp),
            "evidence": _evidence(inp, elig)}


def _placement(intent: str, relevance: str, text: str, has_size: bool, marketplace: Marketplace | None) -> list[str]:
    low = "BACKEND_TERMS" if marketplace is Marketplace.AMAZON else "KEYWORDS"
    if relevance == "LOW":
        return [low]
    if intent in ("BRAND", "PRODUCT_TYPE"):
        return ["TITLE", "BULLETS"] if relevance == "HIGH" else ["BULLETS", low]
    if intent == "SPECIFICATION":
        return ["TITLE", "BULLETS"] if has_size else ["BULLETS", "DESCRIPTION"]
    if intent == "USE_CASE":
        return ["BULLETS", "DESCRIPTION"]
    return ["BULLETS", "DESCRIPTION"]  # FEATURE: only reached for a claim the seller confirmed


def _evidence(inp: KeywordInputs, elig: Sequence[Attribute]) -> dict[str, Any]:
    return {"sellerFacts": len(elig), "factIds": list(inp.fact_ids), "competitorListingsUsed": inp.ci_insight_count, "confirmedNicheTerms": len(inp.niche_terms)}


def _limits(inp: KeywordInputs) -> list[str]:
    lines = [
        "Search volume, buyer demand and marketplace ranking are not assessed: Metrion has no source for them, so they are shown as NOT_ASSESSED, never as zero or an estimate.",
        "Relevance and confidence describe the fit with your own confirmed facts and the evidence listed. They are not Amazon SEO rankings, search counts, conversion rates or sales predictions.",
    ]
    if not inp.ci_insight_count:
        lines.append("No competitor evidence was used: competitor occurrence is NOT_ASSESSED.")
    return lines
