"""Evidence-based optimisation recommendations for a saved listing version (CMO 3.0 M7). Deterministic rules only: every recommendation names the section, the evidence it rests on, the reason,
the next step, what the evidence cannot tell, and the version it is about. Nothing here is a score, a prediction or a claim about sales, ranking, search volume or demand, and a recommendation never
suggests a claim the seller has not confirmed, or copies anything from a competitor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from slim_cmo.history.compare import CLAIM_CODES, _RANK, placements, section_family
from slim_cmo.listing.text import count_phrases

LIMIT = "Based on your confirmed facts and the saved text. It says nothing about search volume, ranking, buyer demand, conversion or sales."
NO_EVIDENCE = "NO_EVIDENCE"
_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _rec(code: str, priority: str, version: Mapping[str, Any], section: str, recommendation: str, evidence: list[str], reason: str, next_action: str, limitations: str = LIMIT,
         refs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "priority": priority, "recommendation": recommendation, "section": section, "evidence": evidence, "reason": reason, "nextAction": next_action, "limitations": limitations,
            "versionId": version["id"], "versionNumber": version["number"], "refs": dict(refs or {})}


def _hint_section(c: Mapping[str, Any]) -> str:
    p = [str(x).upper() for x in c.get("placement") or []]
    return {"TITLE": "TITLE", "BULLETS": "BULLETS", "DESCRIPTION": "DESCRIPTION", "KEYWORDS": "KEYWORDS", "BACKEND_TERMS": "BACKEND_TERMS"}.get(p[0], "KEYWORDS") if p else "KEYWORDS"


def recommend(latest: Mapping[str, Any], *, previous: Mapping[str, Any] | None = None, comparison: Mapping[str, Any] | None = None, facts: Sequence[Mapping[str, Any]] | None = None,
              candidates: Sequence[Mapping[str, Any]] | None = None, unanswered_questions: Sequence[Mapping[str, Any]] | None = None, limit: int = 12) -> dict[str, Any]:
    """Recommendations for `latest`. `comparison` is the saved-version comparison of `previous` -> `latest` when there is one. Inputs that are missing simply produce no rule from that source; when
    nothing at all is available the answer says so (NO_EVIDENCE) instead of inventing advice."""
    s = latest["sections"]
    audit = latest.get("audit")
    recs: list[dict[str, Any]] = []
    sources = {"audit": bool(audit), "facts": bool(facts), "keywords": bool(candidates), "buyerQuestions": bool(unanswered_questions), "history": comparison is not None}

    for f in (audit or {}).get("findings", []):  # R3 / R4: what the saved audit of this version already found
        if f.get("code") in CLAIM_CODES:
            recs.append(_rec("UNSUPPORTED_CLAIM", "HIGH", latest, f["section"], "Remove or confirm an unsupported claim", [f["explanation"], f"Audit check {f['check']} ({f['code']})"],
                             "Your confirmed facts do not support it, so the listing should not say it.", f.get("correction") or "Remove it, or confirm the detail for this product first.",
                             refs={"auditCode": f["code"]}))
        elif str(f.get("code", "")).startswith("W") and f.get("severity") == "WARNING":
            recs.append(_rec("REPEATED_CONTENT", "LOW", latest, f["section"], "Reduce repeated wording", [f["explanation"], f"Audit check {f['check']} ({f['code']})"],
                             "Repeating the same words adds nothing a buyer can use.", f.get("correction") or "Say it once.", refs={"auditCode": f["code"]}))

    placeable = [c for c in candidates or [] if c.get("recommended") and c.get("confidence") in ("STRONG", "MODERATE")]  # R1: supported researched keywords the listing does not use
    if placeable:
        where = placements(s, [str(c["keyword"]) for c in placeable])
        for c in placeable:
            if not where[str(c["keyword"])]:
                sec = _hint_section(c)
                recs.append(_rec("MISSING_SUPPORTED_KEYWORD", "MEDIUM", latest, sec, f"Consider using “{c['keyword']}”",
                                 [f"Researched from your confirmed facts: confidence {str(c.get('confidence')).lower()}", f"It does not appear anywhere in version {latest['number']}"],
                                 "It fits your product and is not in this version.", f"Add “{c['keyword']}” to {sec.lower().replace('_', ' ')} if it reads naturally.", refs={"candidateId": c.get("id"), "keyword": c["keyword"]}))

    if facts:  # R6: a confirmed attribute the listing never mentions
        text = " ".join([s.get("title") or "", *(s.get("bullets") or []), s.get("description") or ""])
        for f in facts:
            if f.get("value") and not count_phrases(text, [str(f["value"])]).get(str(f["value"])):
                recs.append(_rec("MISSING_CONFIRMED_ATTRIBUTE", "MEDIUM", latest, "WHOLE_LISTING", f"State your confirmed {str(f['name']).lower()}: {f['value']}",
                                 [f"You confirmed {f['name']} = {f['value']}", f"Version {latest['number']} never mentions it in the title, bullets or description"],
                                 "A buyer cannot see a detail the listing does not state.", f"Mention {f['value']} in a bullet or the description.", refs={"attribute": f["name"]}))

    for q in unanswered_questions or []:  # R7: a buyer question the listing does not answer yet
        recs.append(_rec("UNANSWERED_BUYER_QUESTION", "MEDIUM", latest, "WHOLE_LISTING", f"Buyers may ask: {q.get('question')}", ["A question buyers commonly ask about this kind of product (the M5 question bank; not drawn from search or review data)"],
                         "Your listing does not answer it yet.", q.get("nextStep") or "Tell me the answer if it is true for your product, then I can help you state it.", refs={"question": q.get("question")}))

    if comparison:  # what the last revision did
        n = previous["number"] if previous else "?"
        for m in comparison["keywordMovement"]["rows"]:
            if m["result"] == "REMOVED" and m["trace"]["recommended"]:
                recs.append(_rec("REVISION_REMOVED_KEYWORD", "MEDIUM", latest, (m["before"][0] if m["before"] else "KEYWORDS"), f"“{m['keyword']}” was removed in version {latest['number']}",
                                 [f"It was in version {n} ({', '.join(m['before'])}) and is in no section now", "It is still a researched keyword for your product"],
                                 "A researched keyword stopped being used.", "Put it back if the removal was not on purpose.", refs={"keyword": m["keyword"]}))
            if m["result"] == "MOVED" and m["before"] and m["after"] and min(_RANK[section_family(x)] for x in m["after"]) > min(_RANK[section_family(x)] for x in m["before"]):
                recs.append(_rec("KEYWORD_MOVED_LOWER", "LOW", latest, m["after"][0], f"“{m['keyword']}” moved to a less prominent place",
                                 [f"Version {n}: {', '.join(m['before'])}", f"Version {latest['number']}: {', '.join(m['after'])}"], "Title and bullets are read before the description and the keyword fields.",
                                 "Move it back if it matters most for this product.", refs={"keyword": m["keyword"]}))
        for a in comparison["attributes"].get("removed", []):
            recs.append(_rec("REVISION_REMOVED_CONFIRMED_INFO", "MEDIUM", latest, "WHOLE_LISTING", f"A confirmed detail was removed: {a['attribute']} = {a['value']}",
                             [f"Stated in version {n}, not stated in version {latest['number']}"], "The revision dropped information you confirmed.", "Put it back unless you meant to leave it out.", refs={"attribute": a["attribute"]}))
        for c in comparison["claims"].get("new", []):
            recs.append(_rec("REVISION_INTRODUCED_UNSUPPORTED_WORDING", "HIGH", latest, c["section"], "This revision introduced unsupported wording", [c["why"], f"Audit check {c['auditCheck']} ({c['auditCode']})"],
                             "It was not flagged in the earlier version and your confirmed facts do not support it.", c.get("nextStep") or "Remove it, or confirm it first.", refs={"auditCode": c["auditCode"]}))
        for u in comparison["audit"].get("unresolved", []):
            recs.append(_rec("ISSUE_NOT_RESOLVED", "MEDIUM" if u["severity"] == "BLOCKER" else "LOW", latest, u["section"], "An earlier audit finding is still there",
                             [u["explanation"], f"Present in version {n} and in version {latest['number']}"], "The revision did not fix it.", u.get("correction") or "Fix it in this section.", refs={"auditCode": u["code"]}))

    seen, unique = set(), []
    for r in sorted(recs, key=lambda r: (_ORDER[r["priority"]], r["section"], r["code"], str(r["refs"]))):
        k = (r["code"], r["section"], str(r["refs"]))
        if k not in seen:
            seen.add(k)
            unique.append(r)
    if not any(sources.values()):
        return {"state": NO_EVIDENCE, "recommendations": [], "versionId": latest["id"], "versionNumber": latest["number"], "sources": sources,
                "message": "There is not enough saved evidence (audit, confirmed facts or researched keywords) to recommend anything for this version.", "limitations": LIMIT}
    return {"state": "RECOMMENDATIONS" if unique else "NOTHING_TO_RECOMMEND", "recommendations": unique[:limit], "total": len(unique), "versionId": latest["id"], "versionNumber": latest["number"],
            "sources": sources, "message": None if unique else "Nothing in the saved evidence points to a change for this version.", "limitations": LIMIT,
            "notice": "These are suggestions for you to decide. Metrion does not change or publish your listing, and a suggestion is not a promise of better results."}
