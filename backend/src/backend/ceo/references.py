"""Following up on earlier results — spec §6.35 (dependent features).

When Product Intelligence has listed product ideas in this conversation, the seller can refer to them the way they would to a list: "write titles for #3", "GST rate for
the second one", "hashtags for number 5". This module turns such a reference into the idea's NAME before routing, so every agent that takes a product (CMO, the GST
lookup, ...) works on it without the seller retyping. It is deterministic and reads only what this conversation already shows the seller: the numbering is the numbering
of the list as displayed. A reference with no list, or a number beyond it, is left exactly as typed (nothing is guessed), and what was substituted is told to the seller.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from backend.ceo.composer import WEB_ARTEFACT_TITLE

_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
_NOUN = r"(?:one|idea|product|option|item|result)"
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"#(?P<n>\d{1,2})\b"),
    re.compile(rf"\b(?:number|no\.?|option|item|idea|product|result)\s*(?P<n>\d{{1,2}})\b", re.IGNORECASE),
    re.compile(rf"\b(?:the\s+)?(?P<n>\d{{1,2}})(?:st|nd|rd|th)\s+{_NOUN}\b", re.IGNORECASE),
    re.compile(rf"\b(?:the\s+)?(?P<w>{'|'.join(_ORDINALS)})\s+{_NOUN}\b", re.IGNORECASE),
)
_LAST = re.compile(rf"\b(?:the\s+)?last\s+{_NOUN}\b", re.IGNORECASE)


def latest_ideas(findings: Sequence[Mapping[str, Any]]) -> list[str]:
    """The names in the newest Product Intelligence list shown in this conversation, in the order the seller saw them."""
    for f in sorted(findings, key=lambda r: r.get("created_at"), reverse=True):
        if f.get("source") != "PI":
            continue
        for art in (f.get("presentation") or {}).get("artefacts") or []:
            if str(art.get("title", "")).startswith(WEB_ARTEFACT_TITLE):
                return [str(i) for i in art.get("items") or []]
    return []


def expand(findings: Sequence[Mapping[str, Any]], text: str) -> tuple[str, list[str]]:
    """The text with each in-range reference replaced by the idea's name, and one plain line per substitution for the seller."""
    ideas = latest_ideas(findings)
    if not ideas:
        return text, []
    notes: list[str] = []

    def pick(n: int) -> str | None:
        return ideas[n - 1] if 1 <= n <= len(ideas) else None

    def sub(m: re.Match[str], n: int | None) -> str:
        name = pick(n) if n is not None else None
        if name is None:
            return m.group(0)
        note = f"Taking #{n} as “{name}” from the product ideas above."
        if note not in notes:
            notes.append(note)
        return name

    out = text
    for rx in _PATTERNS:
        out = rx.sub(lambda m: sub(m, int(m.group("n")) if "n" in rx.groupindex and m.group("n") else _ORDINALS.get((m.groupdict().get("w") or "").lower())), out)
    m = _LAST.search(out)
    if m:
        out = out[: m.start()] + sub(m, len(ideas)) + out[m.end():]
    return out, notes


# "how many units / what batch size should we buy of the top #1 product?" is the stocking decision for that product: it is rewritten (deterministically, only when the seller
# named a product by position or as the top one of a list shown in this conversation) into the exact question the stocking flow already handles.
_BATCH_ASK = re.compile(
    r"\bbatch size\b|\bhow (?:many|much)\b[^?.]*\b(?:units?|pieces?|pcs|quantity|stock|buy|order|purchase)\b|\b(?:units?|quantity|pieces?)\b[^?.]*\b(?:to|should)\b[^?.]*\b(?:buy|order|stock|purchase)\b",
    re.IGNORECASE)
_TOP_ONE = re.compile(rf"\b(?:the\s+)?(?:top|best|first|#1)\s*(?:one|{_NOUN}|pick)?\b", re.IGNORECASE)


def batch_rewrite(findings: Sequence[Mapping[str, Any]], text: str) -> tuple[str, list[str]] | None:
    """`(new_text, notes)` when the message asks how many units to buy of a product named by position ("#2", "the top product") in the list above, else None."""
    if not _BATCH_ASK.search(text):
        return None
    ideas = latest_ideas(findings)
    if not ideas:
        return None
    n: int | None = None
    for rx in _PATTERNS:
        m = rx.search(text)
        if m:
            n = int(m.group("n")) if "n" in rx.groupindex and m.group("n") else _ORDINALS.get((m.groupdict().get("w") or "").lower())
            break
    if n is None and _TOP_ONE.search(text):
        n = 1
    if n is None or not 1 <= n <= len(ideas):
        return None
    name = ideas[n - 1]
    return f"is {name} worth stocking?", [f"Taking #{n} as “{name}” from the product ideas above."]
