"""The deterministic version comparison (CMO 3.0 M7). Given two saved versions of one product + marketplace it returns every difference in the text, the keywords, the saved audits and the
confirmed facts. Pure: no model, no I/O, no unit. Reproducible: the same two versions always give the same result.

A version is a mapping: id, number, sku, marketplace, source, sections {title, bullets, description, keywords, backend_terms (None when the marketplace has none), hashtags (None when the version has
none)}, audit {verdict, findings, checks, rulesBasis, createdAt} or None. Nothing here scores a listing or says that a change helped: a change is a change, and the audit says what is wrong."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from slim_cmo.history import diff
from slim_cmo.listing.text import count_phrases, norm, sentences

CLAIM_CODES = frozenset({"UNSUPPORTED_CLAIM", "UNCONFIRMED_TOPIC", "UNCONFIRMED_VALUE", "UNSUPPORTED_NUMBER", "FORBIDDEN_CONTENT", "CAPACITY_CONTRADICTION", "CAPACITY_DISAGREES",
                         "MATERIAL_CONTRADICTION", "COLOUR_CONTRADICTION", "CI_UNSUPPORTED_THEME_USED"})
_RANK = {"TITLE": 0, "BULLET": 1, "DESCRIPTION": 2, "KEYWORDS": 3, "BACKEND_TERMS": 4}
NO_VOLUME = "Search volume, ranking and demand are not assessed."


def section_family(label: str) -> str:
    return "BULLET" if label.startswith("BULLET") else label


def _quoted(text: str) -> str | None:
    a, b = text.find("“"), text.find("”")
    return text[a + 1:b] if 0 <= a < b else None


def _all_text(s: Mapping[str, Any]) -> str:
    return " ".join([s.get("title") or "", *(s.get("bullets") or []), s.get("description") or "", *(s.get("keywords") or [])])


def placements(sections: Mapping[str, Any], phrases: Sequence[str]) -> dict[str, list[str]]:
    """Where each phrase appears in ONE version: TITLE, BULLET n, DESCRIPTION, KEYWORDS (the keyword list), BACKEND_TERMS. Whole words, from the saved text; never from the model."""
    out: dict[str, list[str]] = {p: [] for p in phrases}
    for p, n in count_phrases(sections.get("title") or "", phrases).items():
        if n:
            out[p].append("TITLE")
    for i, b in enumerate(sections.get("bullets") or []):
        for p, n in count_phrases(b, phrases).items():
            if n:
                out[p].append(f"BULLET {i + 1}")
    for p, n in count_phrases(sections.get("description") or "", phrases).items():
        if n:
            out[p].append("DESCRIPTION")
    kw = {norm(k) for k in sections.get("keywords") or []}
    be = {norm(k) for k in sections.get("backend_terms") or []}
    for p in phrases:
        if norm(p) in kw:
            out[p].append("KEYWORDS")
        if norm(p) in be:
            out[p].append("BACKEND_TERMS")
    return out


def _candidate_index(candidates: Sequence[Mapping[str, Any]] | None) -> dict[str, Mapping[str, Any]]:
    return {norm(str(c.get("keyword"))): c for c in candidates or [] if c.get("keyword")}


def _history_rows(v: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    km = v.get("keywordMap") if isinstance(v.get("keywordMap"), Mapping) else {}
    return {norm(str(r.get("keyword"))): r for r in (km.get("candidates") or []) if r.get("keyword")}


def keyword_movement(older: Mapping[str, Any], newer: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Every keyword that appears in either version (as a researched candidate, a listed keyword, or a backend term) with where it was and where it is. ADDED = not present before, present now;
    REMOVED = present before, gone now (in no section); MOVED = present in both but not in the same places; RETAINED = same places. A keyword that moved is never reported as removed."""
    so, sn = older["sections"], newer["sections"]
    index = _candidate_index(candidates)
    hist = {**_history_rows(older), **_history_rows(newer)}
    names: dict[str, str] = {}
    for src in (so.get("keywords") or [], sn.get("keywords") or [], so.get("backend_terms") or [], sn.get("backend_terms") or [],
                [str(r["keyword"]) for r in hist.values()], [str(c["keyword"]) for c in index.values()]):
        for k in src:
            if norm(k):
                names.setdefault(norm(k), str(k))
    phrases = list(names.values())
    before, after = placements(so, phrases), placements(sn, phrases)
    rows = []
    for key, name in sorted(names.items(), key=lambda kv: kv[1].casefold()):
        b, a = before[name], after[name]
        if not b and not a:
            continue
        result = "ADDED" if not b and a else "REMOVED" if b and not a else "RETAINED" if b == a else "MOVED"
        cand = index.get(key)
        h = hist.get(key)
        if cand is not None:
            trace = {"state": "TRACEABLE", "candidateId": cand.get("id"), "confidence": cand.get("confidence"), "recommended": cand.get("recommended"), "intent": cand.get("intent"),
                     "evidence": "AVAILABLE" if cand.get("confidence") not in (None, "NOT_ASSESSED") else "UNAVAILABLE"}
        elif h is not None:
            trace = {"state": "NOT_IN_CURRENT_CANDIDATES", "candidateId": None, "confidence": None, "recommended": None, "intent": h.get("intent"), "evidence": "UNAVAILABLE"}
        else:
            trace = {"state": "NOT_A_RESEARCHED_CANDIDATE", "candidateId": None, "confidence": None, "recommended": None, "intent": None, "evidence": "UNAVAILABLE"}
        crossed = result == "MOVED" and {section_family(x) for x in b} != {section_family(x) for x in a}
        rows.append({"keyword": name, "before": b, "after": a, "result": result, "crossSection": crossed, "trace": trace})

    def dist(v: dict[str, list[str]]) -> dict[str, int]:
        d: dict[str, int] = {}
        for locs in v.values():
            for x in {section_family(x) for x in locs}:
                d[x] = d.get(x, 0) + 1
        return d
    counts = {r: sum(1 for x in rows if x["result"] == r) for r in ("ADDED", "REMOVED", "RETAINED", "MOVED")}
    return {"rows": rows, "counts": counts, "distribution": {"before": dist(before), "after": dist(after)}, "limits": NO_VOLUME}


def _finding_key(f: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(f.get("code")), str(f.get("section")), _quoted(str(f.get("explanation") or "")) or "")


def audit_diff(older: Mapping[str, Any], newer: Mapping[str, Any]) -> dict[str, Any]:
    ao, an = older.get("audit"), newer.get("audit")
    if not ao or not an:
        return {"available": False, "reason": "AUDIT_MISSING_FOR_" + ("BOTH" if not ao and not an else "OLDER" if not ao else "NEWER"), "new": [], "resolved": [], "unresolved": []}
    fo, fn = {_finding_key(f): f for f in ao["findings"]}, {_finding_key(f): f for f in an["findings"]}
    short = ("check", "severity", "section", "code", "explanation", "correction")
    pick = lambda f: {k: f.get(k) for k in short}  # noqa: E731
    co = {c["id"]: c["status"] for c in ao.get("checks") or [] if "id" in c and "status" in c}
    cn = {c["id"]: c["status"] for c in an.get("checks") or [] if "id" in c and "status" in c}
    return {"available": True, "reason": None, "olderVerdict": ao.get("verdict"), "newerVerdict": an.get("verdict"), "olderBasis": ao.get("rulesBasis"), "newerBasis": an.get("rulesBasis"),
            "new": [pick(f) for k, f in fn.items() if k not in fo], "resolved": [pick(f) for k, f in fo.items() if k not in fn], "unresolved": [pick(f) for k, f in fn.items() if k in fo],
            "checkChanges": [{"check": i, "older": co.get(i), "newer": cn.get(i)} for i in sorted(set(co) | set(cn)) if co.get(i) != cn.get(i)]}


def claims(older: Mapping[str, Any], newer: Mapping[str, Any]) -> dict[str, Any]:
    """Claims the NEWER version makes that your confirmed facts do not support and the older version's audit did not flag: the exact section, the claim, why, and the audit finding."""
    an, ao = newer.get("audit"), older.get("audit")
    if not an:
        return {"available": False, "reason": "AUDIT_MISSING_FOR_NEWER", "new": [], "baseline": ao is not None}
    seen = {_finding_key(f) for f in (ao or {}).get("findings", [])}
    out = []
    for f in an["findings"]:
        if f.get("code") not in CLAIM_CODES or (ao and _finding_key(f) in seen):
            continue
        out.append({"section": f["section"], "claim": _quoted(str(f.get("explanation") or "")), "why": f["explanation"], "reference": "your confirmed product facts", "nextStep": f.get("correction"),
                    "auditCheck": f.get("check"), "auditCode": f.get("code"), "severity": f.get("severity"), "introducedHere": True if ao else None})
    return {"available": True, "reason": None, "new": out, "baseline": ao is not None}


def attribute_changes(older: Mapping[str, Any], newer: Mapping[str, Any], facts: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Confirmed facts (name + value) that are stated in one version and not the other. Only CONFIRMED facts are passed in; a value that is unknown is never treated as a fact."""
    if not facts:
        return {"available": False, "reason": "NO_CONFIRMED_FACTS", "removed": [], "introduced": [], "kept": [], "title": {"removed": [], "introduced": []}}
    vals = [(str(f["name"]), str(f["value"])) for f in facts if f.get("name") and f.get("value")]
    phrases = sorted({v for _, v in vals})

    def present(text: str) -> set[str]:
        return {p for p, n in count_phrases(text, phrases).items() if n}
    o_all, n_all = present(_all_text(older["sections"])), present(_all_text(newer["sections"]))
    o_t, n_t = present(older["sections"].get("title") or ""), present(newer["sections"].get("title") or "")
    mk = lambda names, ps: [{"attribute": n, "value": v} for n, v in vals if v in ps]  # noqa: E731
    return {"available": True, "reason": None, "removed": mk(vals, o_all - n_all), "introduced": mk(vals, n_all - o_all), "kept": mk(vals, o_all & n_all),
            "title": {"removed": mk(vals, o_t - n_t), "introduced": mk(vals, n_t - o_t)}}


def repeated(v: Mapping[str, Any]) -> dict[str, Any]:
    s = v["sections"]
    bullets, seen, dup_b = s.get("bullets") or [], {}, []
    for i, b in enumerate(bullets):
        k = norm(b)
        if k and k in seen:
            dup_b.append({"bullet": i + 1, "sameAs": seen[k] + 1})
        seen.setdefault(k, i)
    sents, ss, dup_s = sentences(s.get("description") or ""), set(), []
    for x in sents:
        k = norm(x)
        if k and k in ss:
            dup_s.append(x)
        ss.add(k)
    in_bul = [x for x in sents if norm(x) and any(norm(x) == norm(b) for b in bullets)]
    return {"duplicateBullets": dup_b, "repeatedSentences": dup_s, "descriptionSentencesCopiedFromBullets": in_bul}


def compare(older: Mapping[str, Any], newer: Mapping[str, Any], *, facts: Sequence[Mapping[str, Any]] | None = None, candidates: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Compare two versions of ONE product + marketplace. The earlier version (by number) is always `older`, whichever order they were asked for in."""
    swapped = older["number"] > newer["number"]
    if swapped:
        older, newer = newer, older
    so, sn = older["sections"], newer["sections"]
    title = diff.text_diff(so.get("title") or "", sn.get("title") or "")
    title["attributes"] = attribute_changes(older, newer, facts)["title"] if facts else {"removed": [], "introduced": []}
    bullets = diff.list_diff(so.get("bullets") or [], sn.get("bullets") or [])
    desc = diff.sentence_diff(so.get("description") or "", sn.get("description") or "")
    kw = diff.term_diff(so.get("keywords"), sn.get("keywords"))
    be = diff.term_diff(so.get("backend_terms"), sn.get("backend_terms"))
    if not be["available"] and so.get("backend_terms") is None and sn.get("backend_terms") is None:
        be["reason"] = "NOT_USED_BY_THIS_MARKETPLACE"
    ht = diff.term_diff(so.get("hashtags"), sn.get("hashtags"))
    if not ht["available"] and so.get("hashtags") is None and sn.get("hashtags") is None:
        ht["reason"] = "NOT_PART_OF_THESE_VERSIONS"
    movement = keyword_movement(older, newer, candidates)
    sec_changed = {"title": title["changed"], "bullets": bullets["changed"], "description": desc["changed"], "keywords": kw["changed"], "backendTerms": be["changed"], "hashtags": ht["changed"]}
    meta = lambda v: {k: v.get(k) for k in ("id", "number", "createdAt", "source", "sourceText", "approved")}  # noqa: E731
    return {
        "older": meta(older), "newer": meta(newer), "swapped": swapped, "identical": not any(sec_changed.values()), "sectionsChanged": sec_changed,
        "title": title, "bullets": bullets, "description": desc, "keywords": kw, "backendTerms": be, "hashtags": ht,
        "keywordMovement": movement, "audit": audit_diff(older, newer), "claims": claims(older, newer), "attributes": attribute_changes(older, newer, facts),
        "repetition": {"older": repeated(older), "newer": repeated(newer)},
        "notice": "These are differences in the saved text and in the saved audits. They do not show that a version performs better or worse, or that either was published.",
    }
