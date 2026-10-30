"""The keyword placement map (docs/specs/slim-cmo-agent.md section 6.18.4). Pure, deterministic, computed from the SAVED text and the M2 analysis; the model never reports where it put a keyword.

Relevance and placement describe fit with the seller's own facts. They are NOT search volume, ranking, demand or conversion, and the map says so.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from slim_cmo.listing.text import count_phrases, norm, words

NOT_ASSESSED = "NOT_ASSESSED"
PLACEABLE_CONFIDENCE = frozenset({"STRONG", "MODERATE"})
# closed list of reasons a recommended candidate is not in the listing
ALREADY_IN_TITLE, PLACEMENT_HINT_NOT_THIS_FIELD, WOULD_REPEAT_WITHOUT_BENEFIT, NOT_NEEDED = ("ALREADY_IN_TITLE", "PLACEMENT_HINT_NOT_THIS_FIELD", "WOULD_REPEAT_WITHOUT_BENEFIT", "NOT_NEEDED")
LIMITS_NOTE = ("Fit with your own confirmed facts and where each word appears. This is not search volume, ranking, buyer demand or conversion; those are not assessed.")


def placeable(candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The only candidates a listing may place: recommended, with evidence strong or moderate (a WEAK or NOT_ASSESSED candidate is shown as not used, never placed)."""
    return [c for c in candidates if c.get("recommended") and c.get("confidence") in PLACEABLE_CONFIDENCE]


def not_placeable(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    out = []
    for c in candidates:
        if c in placeable(candidates):
            continue
        why = "not recommended for your product" if not c.get("recommended") else f"evidence is {str(c.get('confidence', NOT_ASSESSED)).lower().replace('_', ' ')}"
        out.append({"keyword": str(c["keyword"]), "reason": f"Not used: {why}."})
    return out


def build(candidates: Sequence[Mapping[str, Any]], *, title: str, bullets: Sequence[str], description: str, keywords: Sequence[str], backend_terms: Sequence[str] | None,
          excluded: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Where every placeable candidate appears (TITLE, BULLET n, DESCRIPTION, KEYWORDS, BACKEND_TERMS) with counts, or why it is not in the listing."""
    use = placeable(candidates)
    phrases = [str(c["keyword"]) for c in use]
    rows: list[dict[str, Any]] = []
    title_counts = count_phrases(title, phrases)
    bullet_counts = [count_phrases(b, phrases) for b in bullets]
    desc_counts = count_phrases(description, phrases)
    kw_keys = {norm(k) for k in keywords}
    be_keys = {norm(k) for k in (backend_terms or [])}
    placed_phrases = []
    for c in use:
        p = str(c["keyword"])
        where: list[dict[str, Any]] = []
        if title_counts.get(p):
            where.append({"section": "TITLE", "count": title_counts[p]})
        for i, bc in enumerate(bullet_counts):
            if bc.get(p):
                where.append({"section": f"BULLET {i + 1}", "count": bc[p]})
        if desc_counts.get(p):
            where.append({"section": "DESCRIPTION", "count": desc_counts[p]})
        if norm(p) in kw_keys:
            where.append({"section": "KEYWORDS", "count": 1})
        if norm(p) in be_keys:
            where.append({"section": "BACKEND_TERMS", "count": 1})
        if where:
            placed_phrases.append(norm(p))
        rows.append({"keyword": p, "placed": bool(where), "where": where, "intent": c.get("intent"), "m2Placement": list(c.get("placement") or []), "reason": None})
    present_fields = {"TITLE", "BULLETS", "DESCRIPTION", "KEYWORDS"} | ({"BACKEND_TERMS"} if backend_terms is not None else set())
    title_words = set(words(title))
    for r, c in zip(rows, use):
        if r["placed"]:
            continue
        pw = words(r["keyword"])
        if not (set(map(str.upper, c.get("placement") or [])) & present_fields):
            r["reason"] = PLACEMENT_HINT_NOT_THIS_FIELD
        elif pw and set(pw) <= title_words:
            r["reason"] = ALREADY_IN_TITLE
        elif any(pw != words(o) and set(pw) <= set(words(o)) for o in placed_phrases):
            r["reason"] = WOULD_REPEAT_WITHOUT_BENEFIT
        else:
            r["reason"] = NOT_NEEDED
    return {
        "candidates": rows,
        "notUsed": not_placeable(candidates),
        "excluded": [{"keyword": str(e.get("keyword")), "reason": str(e.get("reason"))} for e in excluded],
        "searchVolume": NOT_ASSESSED, "buyerDemand": NOT_ASSESSED, "marketplaceRank": NOT_ASSESSED,
        "limits": LIMITS_NOTE,
    }
