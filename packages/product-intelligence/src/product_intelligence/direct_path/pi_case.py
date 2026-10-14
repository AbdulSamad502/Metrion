"""pi_case — assembles the seller-facing research case from a finished run's PERSISTED rows (docs/specs/ceo-pi-research-flow.md §5, C4, D3).

Three steps, none of which fetches anything or calls an external service, and none of which computes a money figure:

1. `select_top5`  — the deterministic pre-rank (`discovery/prerank.py`) picks the five products suppliers will be looked up for.
2. `finalize_case` — after supplier leads exist: Stage 4 (`shortlist_scoring.score_shortlist`, unchanged) gives the FINAL order of the five; a deterministic
   recommendation is composed FROM PI's own fields (explanations, themes, leads, the stored feasibility snapshot); the case is stored, stamped complete, and the
   tenant's history limit is applied (oldest unpinned archived, pinned never touched).
3. `render_case`  — the read the dashboard and the CEO use: exactly the five products, never the other discovered candidates.

PI never calls CFO here. CFO results are attached by the CEO as references (`pi_research_case_repo.attach_cfo_results`) and only rendered here.
The recommendation holds no number of its own: every figure is a PI column copied verbatim or a reference. `§0a`/`§0b`: "opportunity candidate" and
"viewer/web commentary" wording only; verified marketplace buyer reviews are named unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID

from product_intelligence.discovery.prerank import TOP_N, clean_display_title, prerank
from product_intelligence.discovery.ranking import DEMAND_UNAVAILABLE_REASON
from product_intelligence.discovery.shortlist_scoring import score_shortlist
from product_intelligence.discovery.top5_images import is_video_host
from product_intelligence.repositories import (
    niche_brief_repo,
    pi_research_case_repo,
    pi_research_history_repo,
    product_candidate_repo,
    product_review_insight_repo,
    supplier_lead_repo,
)

NOT_AN_INSTRUCTION = "These are estimates from public web signal and are not a purchase instruction."

_UNAVAILABLE_ALWAYS: tuple[dict[str, str], ...] = (
    {"field": "verified_buyer_reviews", "reason": "no marketplace access exists in V1, so verified buyer reviews are not available; the commentary shown is viewer/web commentary"},
    {"field": "demand_signal", "reason": DEMAND_UNAVAILABLE_REASON},
    {"field": "marketplace_price_and_competition", "reason": "candidates come from open web and video signal; no live marketplace listing was checked"},
)


class CaseNotAvailable(ValueError):
    """The run is unknown, another tenant's, archived or not finished: all look identical to the caller (no existence leak)."""


def _visible_run(tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
    run = pi_research_history_repo.get_visible_run(tenant_id, run_id)
    if run is None:
        raise CaseNotAvailable(f"no finished research report {run_id} for this tenant")
    return run


def _without_video_frame(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """An image hosted on a video site (a thumbnail saved by an older run) is never shown as a product photo."""
    row = dict(candidate)
    row["candidate_title"] = clean_display_title(row.get("candidate_title")) or row.get("candidate_title")
    if (row.get("image_url") and is_video_host(str(row["image_url"]))) or (row.get("image_source_url") and is_video_host(str(row["image_source_url"]))):
        row["image_url"], row["image_source_url"] = None, None
    return row


def _entries(tenant_id: UUID, candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in candidates:
        c = _without_video_frame(c)
        cid = UUID(str(c["id"]))
        out.append({
            "candidate": dict(c), "candidate_id": cid, "candidate_title": c.get("candidate_title"), "proxy_score": c.get("proxy_score"), "proxy_state": c.get("proxy_state"),
            "review_insights": product_review_insight_repo.list_insights_for_candidate(tenant_id, cid),
            "supplier_leads": supplier_lead_repo.list_leads_for_candidate(tenant_id, cid),
        })
    return out


def select_top5(tenant_id: UUID, run_id: UUID, *, investigation_id: UUID | None = None) -> list[UUID]:
    """Step 1. Persists the case with the pre-ranked five. Safe to repeat (same result)."""
    _visible_run(tenant_id, run_id)
    entries = _entries(tenant_id, product_candidate_repo.list_candidates_for_run(tenant_id, run_id))
    chosen = prerank(entries, top_n=TOP_N)
    ids = [UUID(str(p.candidate_id)) for p in chosen]
    pi_research_case_repo.upsert_case(
        tenant_id, run_id, investigation_id=investigation_id, top5_candidate_ids=ids,
        prerank_explanation=[{"candidate_id": str(p.candidate_id), "prerank_score": p.prerank_score, "explanation": p.explanation} for p in chosen],
    )
    return ids


# ---------------------------------------------------------------------------------------------------- deterministic recommendation
def _theme_names(themes: Any) -> list[str]:
    if isinstance(themes, Mapping):
        return [str(k) for k, _ in sorted(themes.items(), key=lambda kv: (-(kv[1] if isinstance(kv[1], (int, float)) else 0), str(kv[0])))]
    if isinstance(themes, (list, tuple)):
        return [str(t) for t in themes]
    return []


def _themes(insights: Sequence[Mapping[str, Any]], key: str) -> list[str]:
    seen: list[str] = []
    for ins in insights:
        if ins.get("insight_state") not in ("COMPLETE", "DEGRADED"):
            continue
        for name in _theme_names(ins.get(key)):
            if name not in seen:
                seen.append(name)
    return seen[:5]


def best_evidenced_lead(leads: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The lead with the MOST evidence fields present (phone, website, locality, MOQ, a published price, a source link). This is evidence completeness, never
    a ranking of suppliers (PI C4): ties keep the first lead in the list's own order."""
    best: tuple[int, int, Mapping[str, Any], list[str]] | None = None
    for index, lead in enumerate(leads):
        contact = lead.get("contact") if isinstance(lead.get("contact"), Mapping) else {}
        present = [name for name, ok in (
            ("phone", bool(contact.get("phone"))), ("website", bool(contact.get("website"))), ("locality", bool(lead.get("locality"))),
            ("moq", contact.get("moq") is not None), ("published_price", contact.get("published_price") is not None), ("source_link", bool(lead.get("source_url"))),
        ) if ok]
        if best is None or len(present) > best[0]:
            best = (len(present), index, lead, present)
    if best is None:
        return None
    lead = dict(best[2])
    lead["evidence_fields"] = best[3]
    return lead


def _recommendation_for(rank: int, entry: Mapping[str, Any], final: Any) -> dict[str, Any]:
    c = entry["candidate"]
    insights, leads = entry["review_insights"], entry["supplier_leads"]
    pros, cons = _themes(insights, "positive_themes"), _themes(insights, "complaint_themes")
    lead = best_evidenced_lead(leads)
    explanation = final.final_score_explanation if final is not None else None
    feasibility = {
        "status": c.get("feasibility_status"), "estimate_ref": str(c["feasibility_estimate_ref"]) if c.get("feasibility_estimate_ref") else None,
        "low_paise": c.get("feasibility_low_paise"), "high_paise": c.get("feasibility_high_paise"), "cogs_basis": c.get("feasibility_cogs_basis"),
        "unavailable_reason": c.get("feasibility_unavailable_reason"),
    }
    gaps: list[str] = []
    if not pros and not cons:
        gaps.append("no viewer/web commentary themes were available for this product")
    if lead is None:
        gaps.append("no supplier lead was found for this product")
    if feasibility["status"] != "COMPUTED":
        gaps.append("no feasibility estimate: " + str(feasibility["unavailable_reason"] or "not computed"))
    return {
        "candidate_id": str(entry["candidate_id"]), "rank": rank, "title": c.get("candidate_title"),
        "final_score": final.final_score if final is not None else None, "final_score_state": final.final_score_state if final is not None else "UNAVAILABLE",
        "why_ranked": [s.get("reason") for s in (explanation or {}).get("signals", []) if s.get("reason")],
        "pros": pros, "cons": cons, "supplier_option": lead, "feasibility": feasibility, "gaps": gaps, "note": NOT_AN_INSTRUCTION,
    }


def _compose(tenant_id: UUID, run: Mapping[str, Any], ids: Sequence[UUID]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, list[str]]:
    """Returns (entries in final order, per-product recommendations, overall pick, run-level gaps). Pure assembly from persisted rows."""
    rows = {UUID(str(c["id"])): c for c in product_candidate_repo.list_candidates_by_ids(tenant_id, list(ids))}
    ordered_ids = [i for i in ids if i in rows]
    entries = _entries(tenant_id, [rows[i] for i in ordered_ids])
    brief = niche_brief_repo.get_brief(tenant_id, UUID(str(run["niche_brief_id"])))
    budget = brief.get("budget_paise") if brief else None
    finals = {UUID(str(f.candidate_id)): f for f in score_shortlist([
        {"candidate_id": e["candidate_id"], "proxy_score": e["proxy_score"], "proxy_state": e["proxy_state"], "review_insights": e["review_insights"],
         "supplier_leads": e["supplier_leads"], "budget_paise": budget} for e in entries
    ])}
    position = {cid: i for i, cid in enumerate(ordered_ids)}

    def sort_key(e: Mapping[str, Any]) -> tuple[Any, ...]:
        f = finals.get(e["candidate_id"])
        # COMPUTED scores first, higher first (2-decimal string compared as a number via its integer cents); ties keep the pre-rank position.
        cents = int(f.final_score.replace(".", "")) if f is not None and f.final_score is not None else -1
        return (-cents, position[e["candidate_id"]])

    entries.sort(key=sort_key)
    recs = [_recommendation_for(i + 1, e, finals.get(e["candidate_id"])) for i, e in enumerate(entries)]
    first = recs[0] if recs and recs[0]["final_score_state"] == "COMPUTED" else None
    overall = {
        "candidate_id": first["candidate_id"], "title": first["title"], "final_score": first["final_score"],
        "reason": f"highest combined score ({first['final_score']}/100) across proxy score, viewer/web commentary sentiment and supplier availability",
        "note": NOT_AN_INSTRUCTION,
    } if first else None
    run_gaps: list[str] = []
    if len(entries) < TOP_N:
        run_gaps.append(f"only {len(entries)} opportunity candidate(s) had enough signal to shortlist")
    return entries, recs, overall, run_gaps


def finalize_case(tenant_id: UUID, run_id: UUID, *, now: datetime | None = None) -> dict[str, Any]:
    """Step 2. Call after supplier lookup for the five. Stores the final order and recommendation, stamps the run complete and applies the history limit."""
    now = now or datetime.now(timezone.utc)
    run = _visible_run(tenant_id, run_id)
    case = pi_research_case_repo.get_case(tenant_id, run_id)
    if case is None:
        raise CaseNotAvailable("the top five were not selected for this run yet")
    entries, recs, overall, run_gaps = _compose(tenant_id, run, [UUID(str(i)) for i in case["top5_candidate_ids"]])
    pi_research_case_repo.set_final(
        tenant_id, run_id, top5_candidate_ids=[e["candidate_id"] for e in entries], recommendation={"products": recs, "overall": overall}, gaps=run_gaps,
    )
    pi_research_history_repo.mark_completed(tenant_id, run_id, completed_at=now)
    archived = pi_research_history_repo.archive_over_limit(
        tenant_id, limit=pi_research_history_repo.get_history_unpinned_limit(tenant_id), now=now,
    )
    return {"runId": str(run_id), "top5": [str(e["candidate_id"]) for e in entries], "archivedCount": archived}


# ---------------------------------------------------------------------------------------------------- reads
def _brief_echo(tenant_id: UUID, run: Mapping[str, Any]) -> dict[str, Any]:
    row = niche_brief_repo.get_brief(tenant_id, UUID(str(run["niche_brief_id"])))
    if row is None:
        return {}
    return {
        "category": row.get("category_text"), "budgetPaise": row.get("budget_paise"), "targetPriceMinPaise": row.get("target_price_min_paise"),
        "targetPriceMaxPaise": row.get("target_price_max_paise"), "marketplaces": row.get("marketplaces"),
    }


def render_case(tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
    """Step 3, a pure read of persisted data. Exactly the five seller-facing products. A run that never had its case finalised (an older run) is assembled
    on the fly from its rows and flagged `caseSaved: false`; nothing is written."""
    run = _visible_run(tenant_id, run_id)
    case = pi_research_case_repo.get_case(tenant_id, run_id)
    if case is not None:
        ids = [UUID(str(i)) for i in case["top5_candidate_ids"]]
    else:
        ids = [UUID(str(p.candidate_id)) for p in prerank(_entries(tenant_id, product_candidate_repo.list_candidates_for_run(tenant_id, run_id)))]
    entries, recs, overall, run_gaps = _compose(tenant_id, run, ids)
    stored = case.get("recommendation") if case else None
    if isinstance(stored, Mapping) and stored.get("products"):  # what the CEO summarised is what the dashboard shows
        recs, overall = list(stored["products"]), stored.get("overall")
        by_id = {e["candidate_id"]: e for e in entries}
        entries = [by_id[UUID(r["candidate_id"])] for r in recs if UUID(r["candidate_id"]) in by_id]
    gaps = list(case["gaps"]) if case and case.get("gaps") else run_gaps
    products = []
    for rec, e in zip(recs, entries):
        lead = rec.get("supplier_option")
        products.append({
            "rank": rec["rank"], "candidate": e["candidate"], "reviewInsights": e["review_insights"], "supplierLeads": e["supplier_leads"],
            "bestSupplierLeadId": str(lead["id"]) if lead and lead.get("id") else None, "finalScore": rec["final_score"],
            "financials": [r for r in (case["cfo_refs"] if case else []) if str(r.get("candidate_id")) == str(rec["candidate_id"])],
            "finalScoreState": rec["final_score_state"], "recommendation": rec,
        })
    unavailable = [dict(u) for u in _UNAVAILABLE_ALWAYS]
    if run.get("status") == "PARTIAL":
        unavailable.append({"field": "run_completeness", "reason": str(run.get("partial_reason") or "one or more sources were unavailable for this run")})
    return {
        "runId": str(run_id), "status": run.get("status"), "pinned": run.get("pinned_at") is not None, "pinnedAt": run.get("pinned_at"),
        "completedAt": run.get("completed_at") or run.get("finished_at"), "caseSaved": case is not None, "brief": _brief_echo(tenant_id, run),
        "products": products, "overall": overall, "cfoRefs": list(case["cfo_refs"]) if case else [], "gaps": gaps, "unavailable": unavailable,
        "investigationId": str(case["investigation_id"]) if case and case.get("investigation_id") else None,
    }


def list_history(tenant_id: UUID) -> list[dict[str, Any]]:
    """History rail: pinned first, then newest unpinned (archived never). Each item names the top product when the case was finalised."""
    out: list[dict[str, Any]] = []
    for row in pi_research_history_repo.list_history(tenant_id):
        case = pi_research_case_repo.get_case(tenant_id, UUID(str(row["id"])))
        rec = (case or {}).get("recommendation") or {}
        products = rec.get("products") or []
        out.append({
            "runId": str(row["id"]), "status": row["status"], "pinned": row["pinned_at"] is not None, "pinnedAt": row["pinned_at"], "completedAt": row["sort_at"],
            "category": row.get("category_text"), "budgetPaise": row.get("budget_paise"), "targetPriceMinPaise": row.get("target_price_min_paise"),
            "targetPriceMaxPaise": row.get("target_price_max_paise"), "marketplaces": row.get("marketplaces"), "caseSaved": case is not None,
            "topProducts": [{"candidateId": p["candidate_id"], "title": p["title"], "finalScore": p["final_score"]} for p in products],
        })
    return out


def attach_cfo_figures(tenant_id: UUID, product_name: str, entries: Sequence[Mapping[str, Any]]) -> UUID | None:
    """The CEO attaches the CFO results it obtained for a product the seller asked about by name ("is #1 worth stocking?"). The product is found by its exact title
    (case-insensitive) among the five of the tenant's newest finished case; no match attaches nothing. Returns the run id attached to, else None. Only references and the
    display text the CEO resolved from them are stored."""
    wanted = clean_display_title(product_name).casefold()
    for row in pi_research_history_repo.list_history(tenant_id):
        run_id = UUID(str(row["id"]))
        case = pi_research_case_repo.get_case(tenant_id, run_id)
        if case is None:
            continue
        for candidate in product_candidate_repo.list_candidates_by_ids(tenant_id, [UUID(str(i)) for i in case["top5_candidate_ids"]]):
            if clean_display_title(str(candidate["candidate_title"])).casefold() == wanted:
                cid = UUID(str(candidate["id"]))
                pi_research_case_repo.replace_cfo_results(tenant_id, run_id, cid, [{**dict(e), "candidate_id": str(cid)} for e in entries])
                return run_id
        return None  # only the newest case is considered: an older report's product is not updated by a newer question
    return None


def research_budget_for_product(tenant_id: UUID, product_name: str) -> int | None:
    """The budget (paise) the seller gave in the research brief that produced the newest saved case holding this product among its five, or None. Offered back to the seller
    as a choice when the CEO asks for a batch budget (a stated value is reused, never re-asked), never filled in silently."""
    wanted = clean_display_title(product_name).casefold()
    for row in pi_research_history_repo.list_history(tenant_id):
        case = pi_research_case_repo.get_case(tenant_id, UUID(str(row["id"])))
        if case is None:
            continue
        for candidate in product_candidate_repo.list_candidates_by_ids(tenant_id, [UUID(str(i)) for i in case["top5_candidate_ids"]]):
            if clean_display_title(str(candidate["candidate_title"])).casefold() == wanted:
                return int(row["budget_paise"]) if row.get("budget_paise") is not None else None
        return None
    return None


def suppliers_for_product(tenant_id: UUID, product_name: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """The supplier leads Product Intelligence found for a product of the tenant's newest saved case (matched by exact title, case-insensitive), best evidenced first:
    `{supplier_name, source, locality, source_url, published_price: {low_paise, high_paise, unit} | None}`. Used by the CEO to OFFER the seller these names and prices as choices
    when it asks for a quote (the seller still picks; a published price is never filled in silently and is never a quote). Another tenant's leads are never visible."""
    wanted = clean_display_title(product_name).casefold()
    for row in pi_research_history_repo.list_history(tenant_id):
        case = pi_research_case_repo.get_case(tenant_id, UUID(str(row["id"])))
        if case is None:
            continue
        for candidate in product_candidate_repo.list_candidates_by_ids(tenant_id, [UUID(str(i)) for i in case["top5_candidate_ids"]]):
            if clean_display_title(str(candidate["candidate_title"])).casefold() != wanted:
                continue
            leads = supplier_lead_repo.list_leads_for_candidate(tenant_id, UUID(str(candidate["id"])))
            best = best_evidenced_lead(leads)
            ordered = ([best] if best else []) + [l for l in leads if not best or l.get("id") != best.get("id")]
            out = []
            for lead in ordered[:limit]:
                price = (lead.get("contact") or {}).get("published_price") if isinstance(lead.get("contact"), Mapping) else None
                out.append({
                    "supplier_name": lead.get("supplier_name"), "source": lead.get("source"), "locality": lead.get("locality"), "source_url": lead.get("source_url"),
                    "published_price": {"low_paise": price["low_paise"], "high_paise": price["high_paise"], "unit": price.get("unit")} if isinstance(price, Mapping) else None,
                })
            return out
        return []
    return []
