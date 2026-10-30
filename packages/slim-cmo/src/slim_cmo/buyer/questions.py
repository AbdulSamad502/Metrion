"""Buyer questions intelligence (CMO 3.0 M5; docs/specs/slim-cmo-agent.md section 6.17).

What this module IS: pure, deterministic code. For one product it lists the questions buyers commonly ask about THIS KIND of product, and for each one says - from the seller's own CONFIRMED
facts only - whether it can be answered. A question is:

* CONFIRMED - a fact the seller stated supports an answer; the answer is that statement, quoted with where it came from and when (never rewritten, never completed);
* SELLER_UNKNOWN - the seller said they do not know / have not tested it: it is a settled "do not claim", and is shown as exactly that;
* NOT_CONFIRMED - nothing the seller said answers it: the question is shown unanswered and the seller is asked for the missing detail. It is never answered from general knowledge.

What it is NOT: it calls no model, reads no database, and has no data about what buyers actually search for or ask (no search, review or Q&A source exists), so it NEVER says how often a
question is asked or how many buyers care. The question bank is a fixed, reviewable list (below); a question is included when its product kind matches or it applies to every product.
Competitor evidence is the DERIVED theme words the CEO brokered from Competitor Intelligence: a question a tracked competitor's listing emphasises is flagged "competitor relevant", nothing more.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

METHOD = "buyer-questions-v1"
CONFIRMED, NOT_CONFIRMED, SELLER_UNKNOWN = "CONFIRMED", "NOT_CONFIRMED", "SELLER_UNKNOWN"
ESSENTIAL, LIKELY, COMPETITOR_RELEVANT = "ESSENTIAL", "LIKELY", "COMPETITOR_RELEVANT"
_ORDER = {COMPETITOR_RELEVANT: 0, ESSENTIAL: 1, LIKELY: 2}
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_UNKNOWN = re.compile(r"^\W*(?:no|not|unknown|untested|un-?tested|not tested|not sure|unsure|n/?a|na|not yet|(?:i )?(?:do not|don'?t|have not|haven'?t|did not|didn'?t) (?:know|tested|test))\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:not|no|never|untested|unknown|unsure|n/a)\b|n't\b", re.IGNORECASE)  # a negative anywhere in a longer statement means it is not an affirmative answer
DRINKWARE = frozenset({"bottle", "flask", "tumbler", "mug", "sipper", "jug", "thermos", "cup", "bottles", "flasks", "tumblers", "mugs"})
MAX_VALUE_CHARS = 200


@dataclass(frozen=True, slots=True)
class Topic:
    id: str
    label: str  # the fact name a seller's answer is stored under
    question: str
    attrs: frozenset[str]  # fact names (case-insensitive) that answer it
    stems: frozenset[str]  # words that, inside a fact's value, also answer it (claims only)
    claim: bool  # a product claim: only ever stated when the seller confirmed it
    kinds: frozenset[str] | None = None  # product-kind words that make it relevant; None = every product
    essential: bool = False


TOPICS: tuple[Topic, ...] = (
    Topic("material", "Material", "What is it made of?", frozenset({"material"}), frozenset(), False, None, True),
    Topic("size", "Size", "What size or capacity is it?", frozenset({"size", "capacity", "volume"}), frozenset(), False, None, True),
    Topic("color", "Color", "What colour is it?", frozenset({"color", "colour"}), frozenset(), False, None, True),
    Topic("brand", "Brand", "Which brand is it?", frozenset({"brand"}), frozenset(), False, None, True),
    Topic("dimensions", "Dimensions", "What are its dimensions?", frozenset({"dimensions", "dimension"}), frozenset(), False),
    Topic("weight", "Weight", "How much does it weigh?", frozenset({"weight"}), frozenset(), False),
    Topic("included", "What is included", "What is in the box?", frozenset({"what is included", "included", "in the box", "package contents", "pack contents"}), frozenset(), False),
    Topic("warranty", "Warranty", "Does it come with a warranty?", frozenset({"warranty"}), frozenset({"warranty"}), True),
    Topic("care", "Care instructions", "How do I clean and care for it?", frozenset({"care instructions", "care", "cleaning"}), frozenset(), False),
    Topic("origin", "Country of origin", "Where is it made?", frozenset({"country of origin", "origin", "made in"}), frozenset(), False),
    Topic("insulated", "Insulated", "Does it keep drinks hot or cold?", frozenset({"insulated", "insulation", "thermal"}), frozenset({"insulated", "insulation", "thermal", "vacuum"}), True, DRINKWARE),
    Topic("leakproof", "Leakproof", "Is it leakproof?", frozenset({"leakproof", "leak proof", "spillproof", "spill proof"}), frozenset({"leakproof", "spillproof", "leak"}), True, DRINKWARE),
    Topic("dishwasher", "Dishwasher safe", "Is it dishwasher safe?", frozenset({"dishwasher safe", "dishwasher"}), frozenset({"dishwasher"}), True, DRINKWARE),
    Topic("bpa", "BPA free", "Is it BPA free and food safe?", frozenset({"bpa free", "food grade", "food safe", "bpa"}), frozenset({"bpa", "food"}), True, DRINKWARE),
    Topic("lid", "Lid type", "What kind of lid or cap does it have?", frozenset({"lid type", "lid", "cap"}), frozenset(), False, DRINKWARE),
)
BY_LABEL = {t.label.casefold(): t for t in TOPICS}


def _words(text: str) -> list[str]:
    return [w.casefold() for w in _WORDS.findall(text or "")]


def is_unknown_value(value: str) -> bool:
    """True when the seller's statement says they do not know / have not tested it (a settled "do not claim", not an answer)."""
    return bool(_UNKNOWN.match(value or ""))


def topic_for_label(label: str) -> Topic | None:
    return BY_LABEL.get(" ".join((label or "").casefold().split()))


def _match(topic: Topic, attributes: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for a in attributes:
        name = " ".join(str(a["label"]).casefold().split())
        if name in topic.attrs:
            return a
    if topic.claim:
        for a in attributes:
            if topic.stems & set(_words(f"{a['label']} {a['value']}")):
                return a
    return None


def analyse(profile: Mapping[str, Any], product_name: str | None, ci_stems: Sequence[str] = (), ci_listing_count: int = 0) -> dict[str, Any]:
    """`profile` is the M1 product profile (`cmo_profile.profile_from_rows`): the seller's latest statement per detail with its source and date."""
    attributes = list(profile.get("attributes") or [])
    name_words = set(_words(product_name or profile.get("name") or ""))
    competitor = set(ci_stems)
    questions: list[dict[str, Any]] = []
    for t in TOPICS:
        if t.kinds is not None and not (t.kinds & name_words):
            continue
        hit = _match(t, attributes)
        value = str(hit["value"]) if hit else None
        if hit and (is_unknown_value(value or "") or (_NEGATION.search(value or "") and not (hit["label"].casefold() in t.attrs))):
            status, answer = SELLER_UNKNOWN, None
        elif hit:
            status, answer = CONFIRMED, value
        else:
            status, answer = NOT_CONFIRMED, None
        seen = bool(competitor & (t.stems | set(_words(t.label))))
        importance = COMPETITOR_RELEVANT if seen else ESSENTIAL if t.essential else LIKELY
        ev = []
        if seen:
            ev.append({"kind": "COMPETITOR_THEME", "detail": f"a theme in your tracked competitors' saved listings ({ci_listing_count} listing{'s' if ci_listing_count != 1 else ''} read)"})
        ev.append({"kind": "QUESTION_BANK", "detail": "a question buyers commonly ask about this kind of product (not drawn from search or review data)"})
        questions.append({
            "id": t.id, "topic": t.label, "question": t.question, "importance": importance, "claim": t.claim, "evidence": ev, "status": status, "answer": answer,
            "source": ({"label": hit["label"], "origin": hit["source"], "at": hit["at"].date().isoformat() if hasattr(hit["at"], "date") else str(hit["at"])} if hit else None),
            "ask": (None if status == CONFIRMED else (f"Tell me about its {t.label.lower()}. I will use it exactly as you say it." if status == NOT_CONFIRMED else f"You told me this is not confirmed (“{value}”). I will not claim it unless you tell me otherwise.")),
            "listingUse": ("Can be used in your listing exactly as you stated it." if status == CONFIRMED else "Must NOT be claimed in your listing until you confirm it." if t.claim else "Not stated in your listing until you confirm it."),
        })
    questions.sort(key=lambda q: (_ORDER[q["importance"]], q["status"] == CONFIRMED, q["id"]))
    counts = {s: sum(1 for q in questions if q["status"] == s) for s in (CONFIRMED, SELLER_UNKNOWN, NOT_CONFIRMED)}
    return {
        "method": METHOD, "status": "COMPLETE" if questions else "NO_QUESTIONS", "questions": questions, "counts": counts,
        "limits": ["These are questions buyers commonly ask about this kind of product. They are not drawn from search, review or marketplace Q&A data, so nothing here says how often a question is asked or how many buyers care.",
                   "An answer is only ever what you told me, quoted as you said it. A question you have not answered is NOT CONFIRMED, never answered from general knowledge, and a claim you have not confirmed is never used in your listing."],
    }
