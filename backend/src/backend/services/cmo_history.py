"""Listing history, version comparison and optimisation advice (CMO 3.0 M7; docs/specs/slim-cmo-agent.md section 6.19).

What this module IS: a READ-ONLY layer over what M6 already stores. Every saved listing pack is one immutable version; its lineage is the stored `revision_of`; its audit is its own saved
`cmo_listing_audit` row. The comparison, keyword movement, claim checks and recommendations are the deterministic rules in `slim_cmo.history`. No model is called, no unit is used or reserved,
nothing is regenerated and no version is ever edited. The only write is the free M6 audit of a version that was never opened (the same row opening its card would save), so that its audit can be shown.

What it is NOT: it never says a version was published, that a change improved sales, ranking, conversion, visibility or demand, or that the latest version is approved.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from slim_cmo.history import compare as compare_rules
from slim_cmo.history import lineage, performance, recommend
from slim_cmo.listing import revise
from slim_cmo.listing.text import norm
from slim_cmo.service.errors import NotFound
from slim_cmo.service.listing_audit import ListingAuditStore
from slim_cmo.service.readiness import keyword_analysis

from backend.repositories import cmo_chat_repo
from backend.services import cmo_listing

logger = logging.getLogger(__name__)
MAX_PAGE = 100
NOT_PUBLISHED = "Metrion cannot see or change what is on a marketplace, so it does not know which version, if any, is live."
CLAIMS = "Approved for use means you approved that version inside Metrion. It does not mean it is published, live or accepted by a marketplace."


class HistoryRefused(Exception):
    def __init__(self, code: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


# ------------------------------------------------------------------------------------------------ the versions of one product + marketplace
def _groups(tenant: UUID, sku: str | None, marketplace: str | None) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """{(sku, marketplace): versions oldest first} with number, parent, source and the separately recorded states attached."""
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in cmo_chat_repo.history_rows(tenant, sku=sku, marketplace=marketplace):
        by_key.setdefault((r["sku"], r["marketplace"]), []).append(r)
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for key, rows in by_key.items():
        meta = lineage.resolve([{"id": r["id"], "createdAt": r["createdAt"], "parentId": r["parentId"], "sku": r["sku"], "marketplace": r["marketplace"],
                                 "source": lineage.source_of({"revision": r["revision"], "revision_of": r["parentId"]}, has_parent=bool(r["parentId"])),
                                 "section": (r["revision"] or {}).get("section")} for r in rows])
        raw = {r["id"]: r for r in rows}
        for m in meta:  # a parent that is not in this product + marketplace may still exist elsewhere in the account: then say what is wrong with it instead of "missing"
            if m["lineageIssue"] == "MISSING_PARENT" and m["claimedParentId"]:
                try:
                    other = cmo_chat_repo.listing_pack(tenant, UUID(m["claimedParentId"]))
                except ValueError:
                    other = None
                if other is not None:
                    m["lineageIssue"] = "CROSS_PRODUCT" if other["sku"] != key[0] else "CROSS_MARKETPLACE"
        latest = max(m["number"] for m in meta)
        versions = []
        for m in meta:
            r = raw[m["id"]]
            versions.append({**m, "sku": key[0], "marketplace": key[1], "createdAt": r["createdAt"].isoformat(), "title": r["title"], "isLatest": m["number"] == latest,
                             "states": {"approvedForUse": {"done": r["approvedAt"] is not None, "at": r["approvedAt"].isoformat() if r["approvedAt"] else None},
                                        "audited": {"done": r["verdict"] is not None, "verdict": r["verdict"], "at": r["auditedAt"].isoformat() if r["auditedAt"] else None, "records": r["auditRecords"]},
                                        "copied": r["copied"], "markedUsed": r["used"], "published": {"known": False}}})
        out[key] = versions
    return out


def _find(tenant: UUID, generation_id: UUID) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pack = cmo_chat_repo.listing_pack(tenant, generation_id)
    if pack is None or not pack["sku"]:
        raise NotFound("listing not found")
    group = _groups(tenant, pack["sku"], pack["marketplace"]).get((pack["sku"], pack["marketplace"]), [])
    me = next((v for v in group if v["id"] == str(generation_id)), None)
    if me is None:
        raise NotFound("listing not found")
    return group, me


def history(tenant: UUID, *, sku: str | None = None, marketplace: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Every saved version, newest first, with product, marketplace, date, source, parent and the separate states. Filter by product (`sku`) and marketplace; paged."""
    limit, offset = max(1, min(int(limit), MAX_PAGE)), max(0, int(offset))
    if marketplace is not None and marketplace not in ("AMAZON", "FLIPKART", "MEESHO"):
        raise HistoryRefused("BAD_MARKETPLACE", "Marketplace must be Amazon, Flipkart or Meesho.")
    groups = _groups(tenant, sku, marketplace)
    names: dict[str, str | None] = {}
    flat: list[dict[str, Any]] = []
    for (k_sku, _mp), versions in groups.items():
        if k_sku not in names:
            names[k_sku] = cmo_chat_repo.product_label(tenant, k_sku)
        flat.extend({**v, "product": names[k_sku]} for v in versions)
    flat.sort(key=lambda v: (v["createdAt"], v["id"]), reverse=True)
    summary = [{"sku": k[0], "product": names.get(k[0]), "marketplace": k[1], "versionCount": len(v), "latestNumber": v[-1]["number"], "latestId": v[-1]["id"]} for k, v in sorted(groups.items())]
    return {"kind": "LISTING_HISTORY", "view": "HISTORY", "filters": {"sku": sku, "marketplace": marketplace}, "total": len(flat), "limit": limit, "offset": offset, "hasMore": offset + limit < len(flat),
            "versions": flat[offset:offset + limit], "groups": summary, "empty": not flat, "notice": CLAIMS, "published": NOT_PUBLISHED}


# ------------------------------------------------------------------------------------------------ one version in full
def _terms(tenant: UUID, pack: Mapping[str, Any]) -> list[str] | None:
    if pack["marketplace"] != "AMAZON":
        return None
    saved = pack["structured"].get("backend_terms_saved")
    return list(saved) if isinstance(saved, list) else (cmo_chat_repo.backend_terms_for(tenant, pack["requestKey"]) or [])


def _engine_version(tenant: UUID, user: UUID, rt: Any, meta: Mapping[str, Any]) -> dict[str, Any]:
    """A version as the comparison engine reads it: its saved text and its OWN saved audit (the free M6 audit is saved first if the version was never opened). Nothing is rewritten."""
    gid = UUID(meta["id"])
    pack = cmo_chat_repo.listing_pack(tenant, gid)
    if pack is None:
        raise NotFound("listing not found")
    store = ListingAuditStore()
    saved = store.latest(tenant, gid)
    if saved is None:
        try:
            built = cmo_listing.audit_pack(tenant, user, rt, gid)
            cmo_listing.save_audit(tenant, user, gid, built)
            saved = store.latest(tenant, gid)
        except (cmo_listing.ListingRefused, NotFound):
            saved = None
    title = cmo_chat_repo.approval_text(tenant, pack["approvalId"]) if pack["approvalId"] else None
    title = title or (pack["structured"].get("provenance") or {}).get("grounding_title") or meta.get("title") or ""
    s = pack["structured"]
    secs = revise.sections_from(s, title=str(title), backend_terms=_terms(tenant, pack))
    sections = {**secs.as_dict(), "hashtags": list(s["hashtags"]) if isinstance(s.get("hashtags"), list) else None}
    return {"id": meta["id"], "number": meta["number"], "sku": meta["sku"], "marketplace": meta["marketplace"], "source": meta["source"], "sourceText": meta["sourceText"],
            "createdAt": meta["createdAt"], "approved": meta["states"]["approvedForUse"]["done"], "sections": sections,
            "audit": ({"verdict": saved["verdict"], "rulesBasis": saved["rulesBasis"], "createdAt": saved["createdAt"], "checks": saved["checks"], "findings": saved["findings"],
                       "measured": saved["measured"], "limits": None} if saved else None),
            "keywordMap": saved["keywordMap"] if saved else None, "changedSection": meta.get("changedSection")}


def version_detail(tenant: UUID, user: UUID, rt: Any, generation_id: UUID) -> dict[str, Any]:
    group, me = _find(tenant, generation_id)
    v = _engine_version(tenant, user, rt, me)
    parent = next((g for g in group if g["id"] == me["parentId"]), None)
    return {"kind": "LISTING_HISTORY", "view": "VERSION", "version": {**me, "product": cmo_chat_repo.product_label(tenant, me["sku"])}, "sections": v["sections"], "audit": v["audit"],
            "keywordMap": v["keywordMap"], "parent": ({"id": parent["id"], "number": parent["number"], "createdAt": parent["createdAt"]} if parent else None),
            "versionCount": len(group), "original": next(({"id": g["id"], "number": g["number"]} for g in group if g["id"] == me["originalId"]), None),
            "whyRevised": _why(me), "notice": CLAIMS, "published": NOT_PUBLISHED}


def _why(me: Mapping[str, Any]) -> dict[str, Any]:
    """What is RECORDED about why a version exists: its source and the section it changed. Metrion does not record the seller's motive, so none is invented."""
    return {"recorded": me["sourceText"], "section": me.get("changedSection"), "reasonRecorded": False,
            "note": "Metrion records how and where a version changed, not your reason for changing it." if me["source"] != lineage.ORIGINAL else "This is the version Metrion first wrote."}


# ------------------------------------------------------------------------------------------------ the evidence the comparison and the advice rest on
def _context(tenant: UUID, rt: Any, sku: str, mp: str) -> dict[str, Any]:
    """Confirmed facts, the researched candidates (the newest SAVED M2 analysis, so each carries its id; else computed from the same facts with no id) and the buyer questions still open."""
    from slim_cmo.types import Marketplace  # noqa: PLC0415

    live, ctx = keyword_analysis(rt.store, tenant, sku, Marketplace(mp), None)
    facts = [{"name": a.name, "value": a.value} for a in ctx.eligible if a.value and a.name.casefold() != "product_name"]
    saved = cmo_chat_repo.latest_keyword_analysis(tenant, sku, mp)
    if saved and saved["candidates"]:
        cands = [{**c, "id": f"{saved['id']}:{norm(str(c['keyword']))}", "analysisId": saved["id"]} for c in saved["candidates"] if c.get("keyword")]
        source = {"kind": "SAVED_M2_ANALYSIS", "analysisId": saved["id"], "savedAt": saved["createdAt"].isoformat()}
    else:
        cands = [{**c, "id": None} for c in live.get("candidates") or [] if c.get("keyword")]
        source = {"kind": "COMPUTED_FROM_CONFIRMED_FACTS", "analysisId": None, "savedAt": None}
    try:
        from backend.ceo import cmo_profile  # noqa: PLC0415
        from slim_cmo.buyer.questions import analyse  # noqa: PLC0415

        profile = cmo_profile.profile_from_rows(cmo_chat_repo.profile_rows(tenant, sku))
        qs = analyse(profile, cmo_chat_repo.product_label(tenant, sku), (), 0)["questions"]
        open_q = [{"question": q["question"], "nextStep": q.get("ask")} for q in qs if q["status"] == "NOT_CONFIRMED" and q["importance"] in ("ESSENTIAL", "COMPETITOR_RELEVANT")]
    except Exception:  # noqa: BLE001 - advice without the buyer-question rule is better than no advice
        logger.exception("could not read the buyer questions for the recommendations")
        open_q = []
    return {"facts": facts, "candidates": cands, "candidateSource": source, "questions": open_q}


def _check_pair(group: Sequence[Mapping[str, Any]], a_id: UUID, b_id: UUID) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    a = next((v for v in group if v["id"] == str(a_id)), None)
    b = next((v for v in group if v["id"] == str(b_id)), None)
    bad = lineage.validate_pair(a, b)
    if bad:
        raise HistoryRefused(bad, {"VERSION_NOT_FOUND": "One of those versions is not in your saved listings.", "DIFFERENT_PRODUCT": "Those versions belong to different products, so I will not compare them.",
                                   "DIFFERENT_MARKETPLACE": "Those versions are for different marketplaces, so I will not compare them."}[bad], 404 if bad == "VERSION_NOT_FOUND" else 422)
    assert a is not None and b is not None
    return a, b


def compare(tenant: UUID, user: UUID, rt: Any, older_id: UUID, newer_id: UUID) -> dict[str, Any]:
    """Compare any two saved versions of one product + marketplace (not only neighbours). Different products or marketplaces are refused. Free; nothing is created beyond a missing audit."""
    pa = cmo_chat_repo.listing_pack(tenant, older_id)
    pb = cmo_chat_repo.listing_pack(tenant, newer_id)
    if pa is None or pb is None:
        raise HistoryRefused("VERSION_NOT_FOUND", "One of those versions is not in your saved listings.", 404)
    if (pa["sku"], pa["marketplace"]) != (pb["sku"], pb["marketplace"]):
        raise HistoryRefused("DIFFERENT_PRODUCT" if pa["sku"] != pb["sku"] else "DIFFERENT_MARKETPLACE", "Those versions are for different products or marketplaces, so I will not compare them.")
    group = _groups(tenant, pa["sku"], pa["marketplace"]).get((pa["sku"], pa["marketplace"]), [])
    a, b = _check_pair(group, older_id, newer_id)
    va, vb = _engine_version(tenant, user, rt, a), _engine_version(tenant, user, rt, b)
    ctx = _context(tenant, rt, pa["sku"], pa["marketplace"])
    out = compare_rules.compare(va, vb, facts=ctx["facts"], candidates=ctx["candidates"])
    out.update({"kind": "LISTING_HISTORY", "view": "COMPARE", "sku": pa["sku"], "marketplace": pa["marketplace"], "product": cmo_chat_repo.product_label(tenant, pa["sku"]),
                "evidence": {"candidates": ctx["candidateSource"], "confirmedFacts": len(ctx["facts"])}, "performance": performance.assess(performance_observations(tenant, pa["sku"], pa["marketplace"])),
                "published": NOT_PUBLISHED, "notice": out["notice"] + " " + CLAIMS})
    return out


def recommendations(tenant: UUID, user: UUID, rt: Any, generation_id: UUID) -> dict[str, Any]:
    """Evidence-based suggestions for ONE saved version (and what its last revision did). Deterministic; free."""
    group, me = _find(tenant, generation_id)
    latest = _engine_version(tenant, user, rt, me)
    prev_meta = next((g for g in group if g["id"] == me["parentId"]), None) or next((g for g in reversed(group) if g["number"] < me["number"]), None)
    prev = _engine_version(tenant, user, rt, prev_meta) if prev_meta else None
    ctx = _context(tenant, rt, me["sku"], me["marketplace"])
    comp = compare_rules.compare(prev, latest, facts=ctx["facts"], candidates=ctx["candidates"]) if prev else None
    out = recommend.recommend(latest, previous=prev, comparison=comp, facts=ctx["facts"], candidates=ctx["candidates"], unanswered_questions=ctx["questions"])
    out.update({"kind": "LISTING_HISTORY", "view": "RECOMMEND", "sku": me["sku"], "marketplace": me["marketplace"], "product": cmo_chat_repo.product_label(tenant, me["sku"]),
                "comparedWith": prev_meta["number"] if prev_meta else None, "evidence": {"candidates": ctx["candidateSource"], "confirmedFacts": len(ctx["facts"])},
                "performance": performance.assess(performance_observations(tenant, me["sku"], me["marketplace"])), "published": NOT_PUBLISHED})
    return out


def performance_observations(tenant: UUID, sku: str, marketplace: str) -> list[dict[str, Any]]:
    """Real, comparable marketplace performance observations for this product. None are read here yet: the uploaded sales and traffic reports are not wired to listing versions, and Metrion cannot
    see when a listing change went live. Until they are, every performance question is NOT_ASSESSED (see `slim_cmo.history.performance`)."""
    return []
