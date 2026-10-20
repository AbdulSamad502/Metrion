"""The data reads behind the CEO's CI conversations (`ceo/ci_conversation.py`).

The CEO package may not import a specialist package directly (the CEO reaches specialists only through the registry and the service layer, `tests/unit/test_ceo_architecture.py`), so
these tenant-scoped reads live here. Each takes the tenant first, reads through the specialist's own RLS-scoped repository, and returns plain rows; nothing is written.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from competitor_intelligence.monitor.wording import currency_claims as _currency_claims
from competitor_intelligence.repositories import (
    ci_candidate_repo,
    ci_discovery_run_repo,
    ci_info_request_repo,
    competitor_evidence_repo,
    competitor_url_repo,
)


_ASIN = re.compile(r"/(?:dp|gp/product|product-reviews)/([A-Z0-9]{10})(?:[/?]|$)")
_FLIPKART = re.compile(r"^(https://www\.flipkart\.com/[^/?]+)/p/(itm[a-z0-9]+)\?[^#]*?\bpid=([A-Z0-9]+)", re.IGNORECASE)


def review_source_url(marketplace: str, url: str) -> str:
    """Where the reviews of a listing live, built from the listing link the seller gave (nothing is fetched). Amazon and Flipkart have a reviews page; for anything else (or a link
    shape this does not recognise) the listing link itself is returned, as the reviews are on that page."""
    if str(marketplace).upper() == "AMAZON":
        m = _ASIN.search(url)
        if m:
            return f"https://www.amazon.in/product-reviews/{m.group(1)}"
    if str(marketplace).upper() == "FLIPKART":
        m = _FLIPKART.match(url)
        if m:
            return f"{m.group(1)}/product-reviews/{m.group(2)}?pid={m.group(3)}"
    return url


def review_sources(tenant_id: UUID) -> dict[str, Any]:
    """For the seller's tracked competitors: where each one's reviews live and whether any review evidence (a screenshot the seller sent, with its sample size) is saved. A read."""
    from competitor_intelligence.repositories import ci_tenant_config_repo, competitor_review_insight_repo

    rows = competitor_url_repo.list_active_with_url(tenant_id)
    out = []
    for r in rows:
        saved = competitor_review_insight_repo.latest_for_url(tenant_id, r["url"])
        out.append({"id": str(r["id"]), "label": r.get("label"), "marketplace": r["marketplace"], "url": r["url"], "reviewsUrl": review_source_url(str(r["marketplace"]), str(r["url"])),
                    "hasEvidence": saved is not None})
    return {"competitors": out, "minSample": ci_tenant_config_repo.get_review_min_sample(tenant_id)}


def open_requests(tenant_id: UUID) -> list[dict[str, Any]]:
    """The seller's unanswered CI confirmation questions, oldest first."""
    return ci_info_request_repo.list_open(tenant_id)


def evidence_exists(tenant_id: UUID, sha256: str) -> bool:
    return competitor_evidence_repo.find_by_sha(tenant_id, sha256) is not None


def linked_skus(tenant_id: UUID) -> list[str]:
    return competitor_url_repo.list_linked_skus(tenant_id)


def _basis(candidate: dict[str, Any]) -> dict[str, Any]:
    raw = candidate.get("identity_match_basis")
    if isinstance(raw, str):
        import json  # noqa: PLC0415

        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def identity_note(candidate: dict[str, Any]) -> str | None:
    """Why CI could or could not say a lead is the seller's own product, in words, from what the identity check stored."""
    if candidate.get("category"):  # found for a business-profile category: there is no product of the seller's to compare identity with
        return f"found for your category “{candidate['category']}”"
    match = candidate.get("identity_match")
    basis = _basis(candidate)
    if match == "UNCERTAIN":
        if not basis.get("seller_brand"):
            return "I cannot tell if it is the same product as yours: your product has no brand recorded"
        if not basis.get("candidate_brand"):
            return "I cannot tell if it is the same product as yours: its title shows no brand"
        return "I cannot tell if it is the same product as yours" + (f" ({basis['notes']})" if basis.get("notes") else "")
    if match == "NOT_A_MATCH":
        return "a different product from yours, so a competing one"
    if match == "LIKELY_VARIANT":
        return "may be a variant of your product"
    if match == "EXACT_MATCH":
        return "looks like the same product as yours"
    return None


def with_titles(tenant_id: UUID, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each candidate with the title and snippet its search result carried (empty when the search gave none)."""
    from competitor_intelligence.repositories import ci_search_result_repo  # noqa: PLC0415

    found = ci_search_result_repo.titles_by_url(tenant_id, [r["candidate_url"] for r in rows if r.get("candidate_url")])
    from sqlalchemy import text  # noqa: PLC0415

    from backend.tenant_context import tenant_scope  # noqa: PLC0415

    scores: dict[str, int] = {}
    ids = [str(r["id"]) for r in rows]
    if ids:
        with tenant_scope(tenant_id) as conn:
            for cid, score in conn.execute(
                text("SELECT DISTINCT ON (candidate_id) candidate_id, total_score FROM ci_candidate_relevance WHERE tenant_id = :t AND candidate_id = ANY(CAST(:ids AS uuid[])) ORDER BY candidate_id, scored_at DESC"),
                {"t": str(tenant_id), "ids": ids},
            ):
                scores[str(cid)] = int(score)
    from competitor_intelligence.discovery.lead_quality import clean_title  # noqa: PLC0415

    return [{**r, "title": clean_title((found.get(r.get("candidate_url")) or {}).get("title")) or None, "snippet": (found.get(r.get("candidate_url")) or {}).get("snippet"),
             "relevance_score": scores.get(str(r["id"]))} for r in rows]


def listing_patterns(tenant_id: UUID) -> dict[str, Any]:
    """What the competitors' saved listing captures show: how many were read, the title words and feature areas they share, the average title length. Derived words only; no competitor
    text and no prices."""
    from competitor_intelligence.repositories import competitor_listing_insight_repo  # noqa: PLC0415

    rows = [r for r in competitor_listing_insight_repo.list_recent_with_text(tenant_id, limit=10) if str(r.get("insight_state")) == "COMPLETE" and r.get("keyword_themes")]
    words: dict[str, int] = {}
    feats: dict[str, int] = {}
    lengths: list[int] = []
    for r in rows:
        for w in (r.get("keyword_themes") or {}):
            words[w] = words.get(w, 0) + 1
        for f in (r.get("feature_categories") or {}):
            feats[f] = feats.get(f, 0) + 1
        if isinstance(r.get("title"), str) and r["title"].strip():
            lengths.append(len(r["title"].split()))
    top = lambda d: [k for k, _ in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]  # noqa: E731
    return {"competitors": len(rows), "words": top(words), "features": top(feats), "avgTitleWords": round(sum(lengths) / len(lengths)) if lengths else None}


def all_competitors(tenant_id: UUID) -> list[dict[str, Any]]:
    """Every ACTIVE tracked competitor as the Competitors page shows it (price, evidence date, freshness, what a buyer pays), whichever product or category it is grouped under."""
    from backend.services import ci_workspace  # noqa: PLC0415

    ws = ci_workspace.build_workspace(tenant_id, None)
    seen: dict[str, dict[str, Any]] = {}
    for p in ws["products"]:
        for c in ci_workspace.build_workspace(tenant_id, p["productId"])["competitors"]:
            seen.setdefault(c["id"], {**c, "group": p["title"] or p["productId"], "groupId": p["productId"]})
    for c in ws["competitors"]:
        seen.setdefault(c["id"], {**c, "group": None, "groupId": None})
    return list(seen.values())


def review_summary(tenant_id: UUID, competitor_url_id: str) -> dict[str, Any] | None:
    """What was read from the seller's review screenshots of one competitor (reviews read, themes), or None when none was sent."""
    from competitor_intelligence.repositories import ci_tenant_config_repo, competitor_review_insight_repo  # noqa: PLC0415

    row = competitor_url_repo.get_any_by_id(tenant_id, UUID(str(competitor_url_id)))
    if row is None:
        return None
    ins = competitor_review_insight_repo.latest_for_url(tenant_id, row["url"])
    if ins is None:
        return None
    return {"reviewsConsidered": ins.get("reviews_considered"), "complaints": list((ins.get("complaint_themes") or {}).keys()), "positives": list((ins.get("positive_themes") or {}).keys()),
            "minSample": ci_tenant_config_repo.get_review_min_sample(tenant_id)}


def latest_run_candidates(tenant_id: UUID) -> list[dict[str, Any]]:
    """Every candidate of the tenant's newest discovery run (the caller filters and orders them)."""
    run = ci_discovery_run_repo.latest_for_tenant(tenant_id)
    if run is None:
        return []
    from backend.services import ci_categories  # noqa: PLC0415

    if not str(run.get("seller_product_ref") or "").startswith(ci_categories.CATEGORY_PREFIX):
        return with_titles(tenant_id, ci_candidate_repo.list_candidates_for_run(tenant_id, run["id"]))
    out: list[dict[str, Any]] = []  # a category search: every category of this request, each lead tagged with the category it was found for
    for r in ci_discovery_run_repo.category_batch(tenant_id):
        name = ci_categories.category_name(r["seller_product_ref"])
        out.extend({**c, "category": name} for c in with_titles(tenant_id, ci_candidate_repo.list_candidates_for_run(tenant_id, r["id"])))
    return out


def seller_price_paise(tenant_id: UUID, product_id: str) -> int | None:
    """The price the seller entered for this product in their own profile (never inferred), or None."""
    from competitor_intelligence.repositories import seller_product_profile_repo  # noqa: PLC0415

    row = seller_product_profile_repo.get_profile(tenant_id, product_id)
    return int(row["price_paise"]) if row and row.get("price_paise") else None


def watchlist_status(tenant_id: UUID) -> dict[str, Any]:
    """The competitor slots (limit, used, free, who holds them)."""
    return competitor_url_repo.watchlist_status(tenant_id)


def tenant_timezone(tenant_id: UUID) -> str | None:
    """The seller's configured timezone (the tenant row), or None when it cannot be read."""
    from sqlalchemy import text  # noqa: PLC0415

    from backend.tenant_context import tenant_scope  # noqa: PLC0415

    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT timezone FROM tenant WHERE id = :t"), {"t": str(tenant_id)}).first()
    return row[0] if row and row[0] else None


def workspace(tenant_id: UUID, product_id: str | None = None) -> dict[str, Any]:
    """The same read model the Competitors page shows, so a chat answer and the page can never disagree."""
    from backend.services import ci_workspace  # noqa: PLC0415

    return ci_workspace.build_workspace(tenant_id, product_id)


def archived_competitors(tenant_id: UUID) -> list[dict[str, Any]]:
    return competitor_url_repo.list_archived(tenant_id)


def currency_claims(text: str) -> list[str]:
    """Phrases in `text` that claim live or current knowledge CI does not have (CI spec C40, AC47)."""
    return _currency_claims(text)
