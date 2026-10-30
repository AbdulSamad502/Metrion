"""Small shared text helpers for the M6 rules: normalised tokens, whole-word phrase counting (longest phrase first, non-overlapping), sentences and the content hash."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence

from slim_cmo.textnorm import dedupe_key


def norm(text: str) -> str:
    """Equality key: the same words in the same order, case/punctuation/spacing/Unicode form ignored (spec 6.4.1: exact duplicates only)."""
    return dedupe_key(text or "")


def words(text: str) -> list[str]:
    return norm(text).split()


def count_phrases(text: str, phrases: Iterable[str]) -> dict[str, int]:
    """Whole-word, non-overlapping occurrences of each phrase in `text`, matching the LONGEST phrase first, so "stainless steel water bottle" counts once for that candidate and not
    again for "water bottle" or "steel". Phrases are compared in normalised form; the result is keyed by the phrase as given."""
    toks = words(text)
    used = [False] * len(toks)
    out: dict[str, int] = {}
    for phrase in sorted({p for p in phrases if norm(p)}, key=lambda p: (-len(norm(p).split()), p)):
        pw = norm(phrase).split()
        n, hits, i = len(pw), 0, 0
        while i <= len(toks) - n:
            if toks[i:i + n] == pw and not any(used[i:i + n]):
                for j in range(i, i + n):
                    used[j] = True
                hits += 1
                i += n
            else:
                i += 1
        out[phrase] = hits
    return out


def sentences(text: str) -> list[str]:
    """Rough sentence split used only by the repetition checks (W5, W6)."""
    out: list[str] = []
    cur: list[str] = []
    for ch in text or "":
        cur.append(ch)
        if ch in ".!?\n":
            s = "".join(cur).strip()
            if s:
                out.append(s)
            cur = []
    tail = "".join(cur).strip()
    if tail:
        out.append(tail)
    return out


def content_hash(marketplace: str, sections: Mapping[str, object]) -> str:
    """Stable hash of the saved listing text (marketplace + every section), so an audit is tied to exactly one version."""
    canon = json.dumps({"marketplace": marketplace, "sections": sections}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def all_texts(title: str, bullets: Sequence[str], description: str, keywords: Sequence[str], backend: Sequence[str] | None) -> list[tuple[str, str]]:
    """(section label, text) for every section, in listing order."""
    out = [("TITLE", title)]
    out += [(f"BULLET {i + 1}", b) for i, b in enumerate(bullets)]
    out.append(("DESCRIPTION", description))
    out += [("KEYWORDS", k) for k in keywords]
    out += [("BACKEND_TERMS", b) for b in (backend or [])]
    return out
