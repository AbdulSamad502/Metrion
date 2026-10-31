"""Exact text and list differences for two listing versions. Comparison keys ignore case, punctuation and spacing; the ORIGINAL text is always what is returned for display."""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any

from slim_cmo.listing.text import norm, sentences

_TOKEN = re.compile(r"\S+")
_SIMILAR_PERMILLE = 500  # two unmatched items are the "same item, reworded" when at least this share (in thousandths) of their words match; integers only, as everywhere in Metrion


def _key(token: str) -> str:
    return norm(token)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def lengths(text: str) -> dict[str, int]:
    t = text or ""
    return {"characters": len(t), "words": len(tokens(t))}


def text_diff(old: str, new: str) -> dict[str, Any]:
    """Word-level difference. `ops` is the full ordered edit script (equal / insert / delete / replace) in the original words; `added`/`removed` list words by occurrence count."""
    a, b = tokens(old), tokens(new)
    ka, kb = [_key(t) for t in a], [_key(t) for t in b]
    ops: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
        o, n = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        ops.append({"op": {"equal": "equal", "insert": "insert", "delete": "delete", "replace": "replace"}[tag], "old": o, "new": n})
    added = [t for op in ops if op["op"] in ("insert", "replace") for t in tokens(op["new"]) if _key(t)]
    removed = [t for op in ops if op["op"] in ("delete", "replace") for t in tokens(op["old"]) if _key(t)]
    return {"changed": ka != kb, "exactTextChanged": (old or "") != (new or ""), "ops": ops, "addedWords": added, "removedWords": removed,
            "old": old or "", "new": new or "", "oldLength": lengths(old), "newLength": lengths(new),
            "characterDelta": len(new or "") - len(old or ""), "wordDelta": len(tokens(new)) - len(tokens(old))}


def _similarity(x: str, y: str) -> int:
    """Shared words as thousandths of the two lengths: 2 x matching words / (words in x + words in y), integer arithmetic."""
    kx, ky = [_key(t) for t in tokens(x)], [_key(t) for t in tokens(y)]
    if not kx or not ky:
        return 0
    matched = sum(b.size for b in SequenceMatcher(None, kx, ky, autojunk=False).get_matching_blocks())
    return (2000 * matched) // (len(kx) + len(ky))


def list_diff(old: Sequence[str], new: Sequence[str]) -> dict[str, Any]:
    """Compare two ordered lists of texts (bullets, sentences). Each item is exactly one of: unchanged (same text, same position), reordered (same text, new position), modified (reworded, with a
    word-level diff), removed or added. Positions are 1-based. Duplicate texts are matched one-to-one, in order."""
    olds, news = list(old), list(new)
    ko, kn = [norm(x) for x in olds], [norm(x) for x in news]
    pair: dict[int, int] = {}  # new index -> old index
    free_old = set(range(len(olds)))
    for j, k in enumerate(kn):  # exact matches first, same position preferred
        if not k:
            continue
        cands = [i for i in sorted(free_old) if ko[i] == k]
        if not cands:
            continue
        i = j if j in cands else cands[0]
        pair[j] = i
        free_old.discard(i)
    modified: dict[int, int] = {}
    for j in range(len(news)):
        if j in pair:
            continue
        best = max(((i, _similarity(olds[i], news[j])) for i in free_old), key=lambda p: (p[1], -p[0]), default=None)
        if best is not None and best[1] >= _SIMILAR_PERMILLE:
            modified[j] = best[0]
            free_old.discard(best[0])
    items: list[dict[str, Any]] = []
    for j, text in enumerate(news):
        if j in pair:
            i = pair[j]
            items.append({"status": "unchanged" if i == j else "reordered", "old": olds[i], "new": text, "oldPosition": i + 1, "newPosition": j + 1})
        elif j in modified:
            i = modified[j]
            items.append({"status": "modified", "old": olds[i], "new": text, "oldPosition": i + 1, "newPosition": j + 1, "diff": text_diff(olds[i], text)})
        else:
            items.append({"status": "added", "old": None, "new": text, "oldPosition": None, "newPosition": j + 1})
    for i in sorted(free_old):
        items.append({"status": "removed", "old": olds[i], "new": None, "oldPosition": i + 1, "newPosition": None})
    count = {s: sum(1 for it in items if it["status"] == s) for s in ("unchanged", "reordered", "modified", "added", "removed")}
    return {"items": items, "counts": count, "changed": any(count[s] for s in ("reordered", "modified", "added", "removed")), "oldCount": len(olds), "newCount": len(news)}


def term_diff(old: Sequence[str] | None, new: Sequence[str] | None) -> dict[str, Any]:
    """Added / removed / retained terms (keywords, backend terms, hashtags), matched on the normalised text, shown as the seller wrote them. None = the field is not part of that version."""
    if old is None and new is None:
        return {"available": False, "reason": "NOT_IN_EITHER_VERSION", "added": [], "removed": [], "retained": [], "changed": False}
    missing = "older" if old is None else "newer" if new is None else None  # a version without the field has no terms in it: everything in the other one is added or removed
    old, new = old or [], new or []
    ko, kn = {norm(t): t for t in old if norm(t)}, {norm(t): t for t in new if norm(t)}
    added = [kn[k] for k in kn if k not in ko]
    removed = [ko[k] for k in ko if k not in kn]
    retained = [kn[k] for k in kn if k in ko]
    return {"available": True, "reason": None, "missingIn": missing, "added": added, "removed": removed, "retained": retained, "changed": bool(added or removed), "oldCount": len(ko), "newCount": len(kn)}


def sentence_diff(old: str, new: str) -> dict[str, Any]:
    d = list_diff(sentences(old or ""), sentences(new or ""))
    d["oldLength"], d["newLength"] = lengths(old), lengths(new)
    d["characterDelta"] = len(new or "") - len(old or "")
    return d
