"""CMO 3.0 M10: Smart Market Opportunities and marketplace news, read from what the seller has ALREADY researched. Pure: no I/O, no model, no clock (the date is passed in), no floats.

Everything here is derived from the findings stored in the seller's saved market-trend reports (`cmo_trend_report.sections`): each finding already carries its cited sources, their publication dates and source
class, the independent-source count and the corroboration computed in code when the report was made. This module only (1) picks the marketplace-news findings and the product-relevant opportunity findings,
(2) collapses duplicates across reports, (3) recomputes freshness against today's date, (4) relates each finding to the seller's own products and marketplaces by shared words and marketplace names, and
(5) writes fixed-template explanations and next steps. It invents nothing: no news, no source, no date, no demand, search volume, sales growth, ranking or competitor performance. Corroboration describes how
widely ATTENTION is reported; it is never evidence of demand."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
MP_NAME = {"AMAZON": "Amazon", "FLIPKART": "Flipkart", "MEESHO": "Meesho"}
_MP_WORDS = {"AMAZON": ("amazon",), "FLIPKART": ("flipkart",), "MEESHO": ("meesho",)}
FRESH_DAYS, RECENT_DAYS, REPORT_STALE_DAYS = 14, 60, 30
KIND_IMPACT = {
    "POLICY": "A policy or rules update. It may change what you can list or how. Read the source and check your seller account before changing any listing.",
    "FEE": "A fee update. It may change your costs. Check your fee settings and landed cost before changing a price.",
    "SELLER_PROGRAM": "A seller-programme update. It may open or close a programme you can join. Check eligibility in your seller account.",
    "SEASONAL": "A seasonal or event update. It may change when buyers shop. Check the dates in your seller account before planning stock or promotions.",
}
NO_IMPACT = "How this affects your account is not known from the report. Read the source."
DEMAND = {"state": "UNAVAILABLE", "note": "Metrion holds no search-volume, sales or demand data for this topic, so none is shown."}
ATTENTION = "Corroboration describes how widely attention is reported. It is not evidence of demand, sales or profit."
_STOP = frozenset("the and for with your you our are was were this that these those from have has had not but can will new best top good great into out use used using set pack pcs piece pieces item items".split())
_WORD = re.compile(r"[a-z0-9]+")
_FRESH_RANK = {"FRESH": 0, "RECENT": 1, "STALE": 2, "DATE_UNKNOWN": 3}
_STRENGTH_RANK = {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "NOT_ASSESSED": 3}
_REL_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NOT_ASSESSED": 3}


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").casefold()) if len(w) > 2 and w not in _STOP}


def _day(iso: Any) -> date | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def freshness(published: Any, today: date) -> tuple[str, int | None]:
    """(FRESH | RECENT | STALE | DATE_UNKNOWN, age in days) from a publication date, against today. An undated item is never called fresh."""
    d = _day(published)
    if d is None or d > today:
        return "DATE_UNKNOWN", None
    age = (today - d).days
    return ("FRESH" if age <= FRESH_DAYS else "RECENT" if age <= RECENT_DAYS else "STALE"), age


def marketplaces_in(finding: Mapping[str, Any]) -> list[str]:
    """The marketplaces a finding is about: those named in its theme, summary, or its sources' titles and web addresses. None named = unknown (not guessed)."""
    blob = " ".join([str(finding.get("theme", "")), str(finding.get("summary", ""))] + [f"{s.get('title', '')} {s.get('url', '')}" for s in finding.get("sources", [])]).casefold()
    return [m for m in MARKETPLACES if any(w in blob for w in _MP_WORDS[m])]


def _sources(finding: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"url": s.get("url"), "title": s.get("title"), "publishedAt": s.get("published_at"), "retrievedAt": s.get("retrieved_at"), "sourceClass": s.get("source_class")}
            for s in finding.get("sources", []) if s.get("url")]


def _dup_key(finding: Mapping[str, Any]) -> str:
    return " ".join(sorted(words(str(finding.get("theme", "")))))


def _flat(reports: Sequence[Mapping[str, Any]], section: str) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    out = []
    for r in reports:
        sec = (r.get("sections") or {}).get(section) or {}
        for f in sec.get("findings") or []:
            out.append((r, f))
    return out


def _collapse(pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> list[tuple[Mapping[str, Any], Mapping[str, Any], int]]:
    """Duplicates across reports (the same story researched twice): same normalised theme, or any shared source address. The occurrence in the NEWEST report is kept; the count of reports it appeared in is shown."""
    ordered = sorted(pairs, key=lambda p: (str(p[0].get("generatedAt")), str(p[1].get("finding_id"))), reverse=True)
    kept: list[list[Any]] = []
    for r, f in ordered:
        urls = {s.get("url") for s in f.get("sources", []) if s.get("url")}
        key = _dup_key(f)
        for k in kept:
            if (key and key == k[3]) or (urls & k[2]):
                k[4] += 1
                k[2] |= urls
                break
        else:
            kept.append([r, f, urls, key, 1])
    return [(k[0], k[1], k[4]) for k in kept]


def product_context(products: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Each product as its words (name and a few confirmed facts) and the marketplaces it has a saved listing on."""
    return [{"sku": p["sku"], "name": p["name"], "terms": words(" ".join([p["name"], *p.get("facts", [])])), "marketplaces": sorted(set(p.get("marketplaces", [])))} for p in products]


def relate(finding: Mapping[str, Any], prods: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """How a finding relates to the seller's products: shared words and shared marketplaces, each stated. HIGH needs both (or two shared words when the finding names no marketplace); MEDIUM one of them;
    LOW neither; NOT_ASSESSED when the seller has no product to compare with."""
    if not prods:
        return {"level": "NOT_ASSESSED", "reason": "You have no saved products yet, so relevance to your products cannot be assessed.", "affects": []}
    text_words = words(f"{finding.get('theme', '')} {finding.get('summary', '')}")
    f_mps = set(marketplaces_in(finding))
    affects, best = [], "LOW"
    for p in prods:
        shared = sorted(text_words & p["terms"])
        mps = sorted(f_mps & set(p["marketplaces"])) if f_mps else []
        if shared and (mps or (not f_mps and len(shared) >= 2)):
            level = "HIGH"
        elif shared or mps:
            level = "MEDIUM"
        else:
            continue
        reason = ("It mentions " + ", ".join(f"“{w}”" for w in shared) + " from your product" if shared else "") + (" and " if shared and mps else "") + \
                 (("it concerns " + ", ".join(MP_NAME[m] for m in mps) + ", where you have a saved listing") if mps else "")
        affects.append({"sku": p["sku"], "name": p["name"], "level": level, "sharedTerms": shared, "marketplaces": mps, "reason": reason + "."})
        if _REL_RANK[level] < _REL_RANK[best]:
            best = level
    affects.sort(key=lambda a: (_REL_RANK[a["level"]], a["name"].casefold(), a["sku"]))
    if not affects:
        return {"level": "LOW", "reason": "It shares no words with your products and names none of the marketplaces you list on.", "affects": []}
    return {"level": best, "reason": affects[0]["reason"], "affects": affects}


# ------------------------------------------------------------------------------------------------ news
def news_items(reports: Sequence[Mapping[str, Any]], prods: Sequence[Mapping[str, Any]], today: date) -> list[dict[str, Any]]:
    out = []
    for r, f, seen in _collapse(_flat(reports, "MARKET_NEWS")):
        srcs = _sources(f)
        dates = [d for d in (_day(s["publishedAt"]) for s in srcs) if d is not None]
        newest = max(dates).isoformat() if dates else None
        fresh, age = freshness(newest, today)
        kind = f.get("news_kind")
        official = any(s.get("sourceClass") == "OFFICIAL_MARKETPLACE" for s in srcs)
        rel = relate(f, prods)
        out.append({"id": f"{r.get('id')}:{f.get('finding_id')}", "headline": f.get("theme"), "summary": f.get("summary"), "newsKind": kind, "marketplaces": marketplaces_in(f), "sources": srcs,
                    "publishedAt": newest, "ageDays": age, "freshness": fresh, "isStale": fresh in ("STALE", "DATE_UNKNOWN"), "officialSource": official,
                    "sourceNote": "From an official marketplace source." if official else "From a third-party source: treat as unconfirmed until the marketplace says so.",
                    "impact": KIND_IMPACT.get(str(kind), NO_IMPACT), "relevance": rel, "reportId": str(r.get("id")), "reportDate": str(r.get("generatedAt"))[:10], "seenInReports": seen,
                    "independentSources": f.get("independent_source_count"), "corroboration": f.get("corroboration"), "limitation": f.get("limitation_note"),
                    "recommendations": _news_steps(f, rel, official, fresh)})
    out.sort(key=lambda n: (_FRESH_RANK[n["freshness"]], _REL_RANK[n["relevance"]["level"]], n["ageDays"] if n["ageDays"] is not None else 10**6, str(n["headline"]).casefold()))
    return out


def _news_steps(f: Mapping[str, Any], rel: Mapping[str, Any], official: bool, fresh: str) -> list[dict[str, str]]:
    steps = [{"agent": "YOU", "text": "Open the source and read it yourself" + ("" if official else ", and look for the marketplace's own announcement") + ". Metrion does not change any marketplace rule or your listings."}]
    if fresh in ("STALE", "DATE_UNKNOWN"):
        steps.append({"agent": "YOU", "text": "This item is old or undated. Check that it is still current before acting on it."})
    kind = f.get("news_kind")
    first = (rel.get("affects") or [None])[0]
    if first and kind in ("POLICY", "SELLER_PROGRAM"):
        steps.append({"agent": "CMO", "text": f"Check your {first['name']} listing against the update.", "ask": f"Show my latest {first['name']} listing"})
    if kind == "FEE":
        steps.append({"agent": "CFO", "text": "Check how the fee change affects your margin before changing a price.", "ask": "What is my profit by product?"})
    if kind == "SEASONAL" and first:
        steps.append({"agent": "CMO", "text": f"Check what buyers will ask about your {first['name']} before the season.", "ask": f"What questions will buyers ask about my {first['name']}?"})
    return steps


# ------------------------------------------------------------------------------------------------ opportunities
_OPP_SECTIONS = ("ADJACENT", "NEW_PRODUCTS_BUZZ", "REPORTED_TACTICS", "NICHE")
_SECTION_LABEL = {"ADJACENT": "Adjacent topic", "NEW_PRODUCTS_BUZZ": "New-product buzz", "REPORTED_TACTICS": "Tactic sellers report", "NICHE": "Your niche"}


def _strength(f: Mapping[str, Any], fresh: str) -> tuple[str, str]:
    if not _sources(f):
        return "NOT_ASSESSED", "No citable source is stored for this finding."
    corr = f.get("corroboration")
    base = {"STRONG": "STRONG", "MODERATE": "MODERATE", "WEAK": "WEAK", "SINGLE_SOURCE": "WEAK"}.get(str(corr), "NOT_ASSESSED")
    if base == "NOT_ASSESSED":
        return base, "The report does not say how widely this was reported."
    if fresh in ("STALE", "DATE_UNKNOWN") and base in ("STRONG", "MODERATE"):
        return "WEAK", "Reported by several sources, but the freshest is old or undated."
    note = {"STRONG": "Reported by several independent sources recently.", "MODERATE": "Reported by more than one independent source.", "WEAK": "Reported by one source or only weakly corroborated."}[base]
    return base, note


def opportunities(reports: Sequence[Mapping[str, Any]], prods: Sequence[Mapping[str, Any]], today: date) -> list[dict[str, Any]]:
    out = []
    for section in _OPP_SECTIONS:
        for r, f, seen in _collapse(_flat(reports, section)):
            if section == "REPORTED_TACTICS" and (f.get("caution") or f.get("policy_risk") not in (None, "NONE_IDENTIFIED")):
                continue  # a tactic with any identified policy risk is never offered as an opportunity
            rel = relate(f, prods)
            if rel["level"] in ("LOW",):
                continue  # not about this seller's products or marketplaces
            srcs = _sources(f)
            dates = [d for d in (_day(s["publishedAt"]) for s in srcs) if d is not None]
            newest = max(dates).isoformat() if dates else None
            fresh, age = freshness(newest, today)
            strength, why = _strength(f, fresh)
            first = (rel.get("affects") or [None])[0]
            out.append({"id": f"{r.get('id')}:{f.get('finding_id')}", "title": f.get("theme"), "section": section, "kind": _SECTION_LABEL[section], "relevance": rel,
                        "observed": {"label": "What the saved sources reported (verified as reported, not as true)", "summary": f.get("summary"), "sources": srcs, "independentSources": f.get("independent_source_count"),
                                     "freshestPublishedAt": newest, "freshness": fresh, "ageDays": age, "reportId": str(r.get("id")), "reportDate": str(r.get("generatedAt"))[:10], "seenInReports": seen},
                        "possible": {"label": "A possible explanation (not measured)", "text": (f"This topic sits next to your niche ({f.get('relation_to_niche')})." if f.get("relation_to_niche") else "Attention to this topic is reported by the sources above.") + " " + ATTENTION},
                        "evidenceStrength": strength, "evidenceStrengthWhy": why, "demand": DEMAND, "limitation": f.get("limitation_note"),
                        "recommendations": _opp_steps(first, section, strength)})
    out.sort(key=lambda o: (_REL_RANK[o["relevance"]["level"]], _STRENGTH_RANK[o["evidenceStrength"]], _FRESH_RANK[o["observed"]["freshness"]],
                            o["observed"]["ageDays"] if o["observed"]["ageDays"] is not None else 10**6, str(o["title"]).casefold()))
    for i, o in enumerate(out, start=1):
        o["rank"] = i
        o["rankedBecause"] = f"Relevance to your products: {o['relevance']['level']}; evidence: {o['evidenceStrength']}; freshness: {o['observed']['freshness']}. Ranked by those three in that order, with no score or forecast."
    return out


def _opp_steps(first: Mapping[str, Any] | None, section: str, strength: str) -> list[dict[str, str]]:
    steps = [{"agent": "YOU", "text": "Open the sources and judge for yourself. Nothing here shows that buyers want this or that it would sell."}]
    if strength in ("WEAK", "NOT_ASSESSED"):
        steps.append({"agent": "YOU", "text": "The evidence is weak or incomplete. Treat this as a lead to check, not a reason to act."})
    steps.append({"agent": "PI", "text": "Research the topic in Product Intelligence before you commit to a product.", "ask": "Find product ideas I could sell"})
    if first:
        steps.append({"agent": "CMO", "text": f"See what is missing from your {first['name']} listing before you change it.", "ask": f"What should I improve next in my {first['name']} listing?"})
    steps.append({"agent": "CFO", "text": "Check the margin before stocking anything new.", "ask": "What is my profit by product?"})
    return steps


# ------------------------------------------------------------------------------------------------ the overview
def overview(reports: Sequence[Mapping[str, Any]], prods: Sequence[Mapping[str, Any]], today: date) -> dict[str, Any]:
    if not reports:
        return {"state": "NO_REPORT", "message": "You have no saved market-trend report yet, so there is no news or opportunity to show. Metrion does not invent any. Ask me to research current market trends; that is a separate paid step you approve first.",
                "latestReportAt": None, "reportCount": 0, "news": [], "opportunities": []}
    latest = max(str(r.get("generatedAt")) for r in reports)
    age = (today - _day(latest)).days if _day(latest) else None
    news, opps = news_items(reports, prods, today), opportunities(reports, prods, today)
    stale = age is None or age > REPORT_STALE_DAYS
    return {"state": "STALE_REPORTS" if stale else "OK",
            "message": (f"Your newest market-trend report is {age} days old. What follows may be out of date." if stale and age is not None else "Your newest report has no usable date." if stale else None),
            "latestReportAt": latest[:10], "reportCount": len(reports), "news": news, "opportunities": opps}
