"""Revision lineage for a product + marketplace (pure). The database already records `revision_of`; nothing is reconstructed or guessed. A link that cannot be trusted is reported and the version is
treated as a starting point, never silently followed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ORIGINAL, SELLER_EDIT, AI_REWRITE, REVISION_UNKNOWN = "ORIGINAL", "SELLER_EDIT", "AI_REWRITE", "REVISION_UNKNOWN"
SOURCE_TEXT = {ORIGINAL: "Original listing written by Metrion", SELLER_EDIT: "Your own edit", AI_REWRITE: "Rewritten by the model, with your approval", REVISION_UNKNOWN: "A revision (source not recorded)"}
SECTION_WORDS = {"TITLE": "the title", "DESCRIPTION": "the description", "KEYWORDS": "the keywords", "BACKEND_TERMS": "the backend search terms"}
_BY = {"SELLER_TEXT": SELLER_EDIT, "MODEL_REWRITE": AI_REWRITE}


def source_of(structured: Mapping[str, Any], *, has_parent: bool) -> str:
    """How a version came to be, from what was stored with it (`revision.by`). No stored revision marker and no parent = the original; a parent with an unrecognised marker is REVISION_UNKNOWN."""
    rev = structured.get("revision") if isinstance(structured, Mapping) else None
    by = rev.get("by") if isinstance(rev, Mapping) else None
    if by in _BY:
        return _BY[by]
    return REVISION_UNKNOWN if (has_parent or by or structured.get("revision_of")) else ORIGINAL


def changed_label(structured: Mapping[str, Any]) -> str | None:
    rev = structured.get("revision") if isinstance(structured, Mapping) else None
    sec = rev.get("section") if isinstance(rev, Mapping) else None
    return str(sec) if sec else None


def describe(source: str, section: str | None) -> str:
    base = SOURCE_TEXT[source]
    if source == ORIGINAL or not section:
        return base
    if section.startswith("BULLET "):
        return f"{base}: bullet {section.split(' ', 1)[1]}"
    return f"{base}: {SECTION_WORDS.get(section, section.lower().replace('_', ' '))}"


def resolve(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Order the packs of ONE product + marketplace and attach number, parent and lineage problems.

    Each row needs: id, createdAt (sortable), parentId (the stored `revision_of` or None), sku, marketplace, source, section. Numbers are 1..N by creation time (id breaks ties), so they never change
    when a later version is added. A parent is trusted only when it exists in these rows, has the same product and marketplace, was created before the child and the chain has no loop; otherwise the
    problem is recorded (MISSING_PARENT, CROSS_PRODUCT, CROSS_MARKETPLACE, NOT_EARLIER, CYCLE) and the version is a starting point."""
    ordered = sorted(rows, key=lambda r: (r["createdAt"], str(r["id"])))
    by_id = {str(r["id"]): r for r in ordered}
    number = {str(r["id"]): i + 1 for i, r in enumerate(ordered)}
    pos = {str(r["id"]): i for i, r in enumerate(ordered)}
    out: list[dict[str, Any]] = []
    for r in ordered:
        rid, pid = str(r["id"]), (str(r["parentId"]) if r.get("parentId") else None)
        issue: str | None = None
        parent = by_id.get(pid) if pid else None
        if pid and parent is None:
            issue = "MISSING_PARENT"
        elif parent is not None:
            if parent["sku"] != r["sku"]:
                issue = "CROSS_PRODUCT"
            elif parent["marketplace"] != r["marketplace"]:
                issue = "CROSS_MARKETPLACE"
            elif pos[pid] >= pos[rid]:
                issue = "CYCLE" if pid == rid or _loops(rid, by_id) else "NOT_EARLIER"
        trusted = pid if (pid and issue is None) else None
        out.append({"id": rid, "number": number[rid], "parentId": trusted, "parentNumber": number[trusted] if trusted else None, "claimedParentId": pid, "lineageIssue": issue,
                    "source": r["source"], "sourceText": describe(r["source"], r.get("section")), "changedSection": r.get("section"), "createdAt": r["createdAt"]})
    root: dict[str, str] = {}
    for o in out:  # the starting version of each chain, for "the original"
        root[o["id"]] = root[o["parentId"]] if o["parentId"] else o["id"]
        o["originalId"], o["originalNumber"] = root[o["id"]], number[root[o["id"]]]
    return out


def _loops(start: str, by_id: Mapping[str, Mapping[str, Any]]) -> bool:
    seen: set[str] = set()
    cur = start
    while cur and cur in by_id and cur not in seen:
        seen.add(cur)
        cur = str(by_id[cur]["parentId"]) if by_id[cur].get("parentId") else ""
    return bool(cur) and cur in seen


def validate_pair(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> str | None:
    """None when two versions may be compared, else the machine-readable reason. Different products or marketplaces are never compared."""
    if a is None or b is None:
        return "VERSION_NOT_FOUND"
    if a["sku"] != b["sku"]:
        return "DIFFERENT_PRODUCT"
    if a["marketplace"] != b["marketplace"]:
        return "DIFFERENT_MARKETPLACE"
    return None
