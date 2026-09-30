"""pi.report — re-renders a completed run from persisted data only, **no new fetch** (PI
build plan §2). Loads `product_candidate`/`product_review_insight`/`supplier_lead` rows for a
`run_id` and returns a structured report shape, always including an `unavailable[]` list
naming what wasn't obtained — marketplace price/competition (always, no legal V1 path per
the plan's Context), `demand_signal` (always this build, Checkpoint 0), and anything a source
degraded on for this specific run (`pi_research_run.status == PARTIAL`'s own reason).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from product_intelligence.discovery.ranking import DEMAND_UNAVAILABLE_REASON
from product_intelligence.discovery.shortlist_scoring import score_shortlist
from product_intelligence.repositories import (
    pi_research_run_repo,
    product_candidate_repo,
    product_review_insight_repo,
    supplier_lead_repo,
)

_MARKETPLACE_UNAVAILABLE = {
    "field": "marketplace_price_and_competition",
    "reason": (
        "no marketplace-side integration exists in V1 (Amazon PA-API deprecated, "
        "Flipkart/Meesho fetching and the Flipkart Affiliate API both ruled out) — "
        "candidates are discovered from open web/video signal only, never verified "
        "against a live marketplace listing"
    ),
}

_DEMAND_UNAVAILABLE = {
    "field": "demand_signal",
    "reason": DEMAND_UNAVAILABLE_REASON,
}


@dataclass(frozen=True, slots=True)
class PiReport:
    run_id: UUID
    status: str
    candidates: list[dict[str, Any]]
    unavailable: list[dict[str, str]]


def render_report(tenant_id: UUID, run_id: UUID) -> PiReport:
    run = pi_research_run_repo.get_run(tenant_id, run_id)
    if run is None:
        raise ValueError(f"no pi_research_run {run_id} for this tenant")

    candidates = product_candidate_repo.list_candidates_for_run(tenant_id, run_id)

    unavailable: list[dict[str, str]] = [dict(_MARKETPLACE_UNAVAILABLE), dict(_DEMAND_UNAVAILABLE)]
    partial_reason = run.get("partial_reason") if isinstance(run, dict) else None
    if run.get("status") == "PARTIAL" and partial_reason:
        unavailable.append({"field": "run_completeness", "reason": str(partial_reason)})

    shortlist_inputs = []
    rendered_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = UUID(str(candidate["id"]))
        insights = product_review_insight_repo.list_insights_for_candidate(tenant_id, candidate_id)
        candidate_leads = supplier_lead_repo.list_leads_for_candidate(tenant_id, candidate_id)

        rendered_candidates.append(
            {
                "candidate": candidate,
                "review_insights": insights,
                "supplier_leads": candidate_leads,
            }
        )
        shortlist_inputs.append(
            {
                "candidate_id": candidate_id,
                "proxy_score": candidate.get("proxy_score"),
                "proxy_state": candidate.get("proxy_state"),
                "review_insights": insights,
                "supplier_leads": candidate_leads,
                "budget_paise": None,
            }
        )

    final_scores = {fs.candidate_id: fs for fs in score_shortlist(shortlist_inputs)}
    for entry in rendered_candidates:
        candidate_id = UUID(str(entry["candidate"]["id"]))
        final = final_scores.get(candidate_id)
        entry["final_score"] = final.final_score if final else None
        entry["final_score_state"] = final.final_score_state if final else "UNAVAILABLE"
        entry["final_score_explanation"] = final.final_score_explanation if final else None

    return PiReport(
        run_id=run_id,
        status=str(run.get("status", "")),
        candidates=rendered_candidates,
        unavailable=unavailable,
    )
