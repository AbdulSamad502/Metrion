"""The CEO-driven product research chain after an approved `pi.discover` (docs/specs/ceo-pi-research-flow.md §5.3, C2, C4, C5).

One approval covers: the research run, then (decided by CODE from its result) the five seller-facing products, a supplier lookup for exactly those five, the final
case, and a read of the saved report. Every step goes through the same choke point as any leg (per-leg permission, entitlement and metering still apply) or the
`ceo_pi_research` service seam. Product Intelligence never calls CFO: any CFO result reaches the case only through the CEO (CP4).

What this module writes is TEXT assembled by code from PI's stored fields (scores, themes, leads, named gaps) and the seller's own brief. It computes no figure, asks
no model anything, and states a missing cost, margin or quantity as missing, never as a number. Only the five final products are ever described: the other
discovered candidates are internal.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from backend.auth.context import AuthContext
from backend.ceo import orchestrator
from backend.ceo.contract import ApprovalGrant, LegResult, LegStatus
from backend.ceo.dispatch import CeoTurn
from backend.ceo.evidence import BATCH_PARTIAL_TEXT
from backend.ceo.figure_format import format_paise
from backend.ceo.plans import ResolvedSlots
from backend.ceo.presentation import present_leg
from backend.ceo.runtime import CeoRuntime, EventLog, StageClock
from backend.services import ceo_pi_research

logger = logging.getLogger(__name__)

LOOKUP = "pi.supplier_lookup"
_OK = (LegStatus.COMPLETE, LegStatus.PARTIAL)
_SOURCE_LABEL = {"GOOGLE_PLACES": "Google Places listing", "TAVILY": "web search lead, not verified", "INDIAMART_LOOKUP": "IndiaMART lookup"}


def _run_id_of(legs: Sequence[LegResult]) -> UUID | None:
    run = next((l for l in legs if l.action_key == "pi.discover" and l.status in _OK and (l.payload or {}).get("runId")), None)
    if run is None:
        return None
    try:
        return UUID(str((run.payload or {})["runId"]))
    except ValueError:
        return None


def run_followups(
    ctx: AuthContext, runtime: CeoRuntime, turn: CeoTurn, now: datetime, legs: list[LegResult], attached: frozenset[str], clock: StageClock, log: EventLog,
    grant: ApprovalGrant, then_keys: Sequence[str],
) -> tuple[list[LegResult], list[str], UUID | None]:
    """Returns (all legs including the follow-ups and the final `pi.report` read, named gaps, the run id). A failed follow-up is a named gap: the seller still gets
    what was found, and nothing is retried or invented."""
    tenant = ctx.tenant_id
    assert tenant is not None
    gaps: list[str] = []
    run_id = _run_id_of(legs)
    if run_id is None:
        return legs, ["The research run did not finish, so no products were shortlisted."], None
    try:
        top5 = ceo_pi_research.select_top5(tenant, run_id, investigation_id=turn.investigation_id)
    except Exception:  # noqa: BLE001 - nothing internal reaches the seller; the log has it
        logger.exception("could not choose the five products (tenant=%s run=%s)", tenant, run_id)
        top5 = []
        gaps.append("The five products could not be chosen from the research run, so no shortlist is shown.")
    if top5 and LOOKUP in then_keys:
        if orchestrator._preflight(ctx, runtime, LOOKUP, attached, now):
            slots = {"run_id": str(run_id), "candidate_ids": [str(i) for i in top5]}
            leg = orchestrator._run_leg(turn, runtime, ResolvedSlots(tenant_id=tenant, today=now.date()), LOOKUP, attached, clock, log, {LOOKUP: slots}, grant)
            legs = [*legs, leg]
            if leg.status not in _OK:
                gaps.append("The supplier lookup did not complete, so supplier leads may be missing for some products.")
        else:
            gaps.append("The supplier lookup is not available to you here, so no supplier leads were looked up.")
    if top5:
        try:
            ceo_pi_research.finalize(tenant, run_id)
        except Exception:  # noqa: BLE001
            logger.exception("could not finalise the research case (tenant=%s run=%s)", tenant, run_id)
            gaps.append("The research case could not be finalised, so the saved report may be incomplete.")
    legs = orchestrator._with_pi_report(runtime, turn, tenant, now, legs, attached, clock, log)
    orchestrator._record_pi_finding(tenant, ctx.app_user_id, legs)
    return legs, gaps, run_id


# ---------------------------------------------------------------------------------------------------- the summary (written by code)
# The answer uses a tiny, fixed markup the chat renders safely (frontend `RichText`): "## " / "### " headings, "- " bullets, **bold**, and [label](https://...) links. Plain
# text readers still get a readable message. Nothing here is model-written.
_DIRECTORY_LABEL = (("indiamart.com", "IndiaMART listing"), ("tradeindia.com", "TradeIndia listing"), ("exportersindia.com", "ExportersIndia listing"))


def _join(items: Sequence[str], n: int = 2) -> str:
    return ", ".join(items[:n])


def _safe_url(url: Any) -> str | None:
    u = str(url or "").strip()
    return u if u.startswith(("https://", "http://")) and " " not in u and ")" not in u else None


def _source_label(lead: Mapping[str, Any]) -> str:
    url = str(lead.get("source_url") or "").lower()
    for domain, label in _DIRECTORY_LABEL:
        if domain in url:
            return label
    return _SOURCE_LABEL.get(str(lead.get("source")), "lead")


def _rupees_short(paise: int) -> str:
    return format_paise(paise).removesuffix(".00")


def _supplier_line(lead: Mapping[str, Any] | None) -> str:
    if not lead:
        return "No supplier lead was found for this product."
    contact = lead.get("contact") if isinstance(lead.get("contact"), Mapping) else {}
    name = " ".join(str(lead.get("supplier_name") or "Supplier").split())[:90].replace("[", "(").replace("]", ")")
    url = _safe_url(contact.get("website")) or _safe_url(lead.get("source_url"))
    head = f"[{name}]({url})" if url else name
    bits = [head, _source_label(lead) + (" (not verified)" if lead.get("source") == "TAVILY" else "")]
    if lead.get("locality"):
        bits.append(str(lead["locality"]))
    price = contact.get("published_price") if isinstance(contact, Mapping) else None
    if isinstance(price, Mapping):
        low, high = int(price["low_paise"]), int(price["high_paise"])
        shown = _rupees_short(low) if low == high else f"{_rupees_short(low)} to {_rupees_short(high)}"
        bits.append(f"**published price {shown} per {price.get('unit') or 'unit'}** (on their page; not a quote)")
    return " · ".join(bits)


def _financial_lines(p: Mapping[str, Any], brief: Mapping[str, Any]) -> list[str]:
    """Landed cost, the units ceiling and profit/loss, each either a verified CFO result or the plain reason it is missing. Nothing is computed here."""
    fins = list(p.get("financials") or [])
    landed = next((f for f in fins if f.get("leg_key") == "cfo.landed_cost" and f.get("display")), None)
    units = next((f for f in fins if f.get("leg_key") == "cfo.batch_size" and f.get("display")), None)
    band = ""
    if brief.get("targetPriceMinPaise") is not None and brief.get("targetPriceMaxPaise") is not None:
        band = f" Your target selling band is {_rupees_short(int(brief['targetPriceMinPaise']))} to {_rupees_short(int(brief['targetPriceMaxPaise']))}."
    return [
        f"- **Landed cost per unit:** {landed['display']} (from your confirmed quote)" if landed else "- **Landed cost per unit:** not calculated; it needs your supplier quote.",
        (f"- **Units / batch size:** {units['display']} is the most your budget allows, a ceiling and not a recommendation to buy that many" if units
         else "- **Units / batch size:** not calculated; it needs your supplier quote (price, and the minimum order or delivery time). It will be a budget ceiling, not a recommendation."),
        "- **Profit / loss:** not calculated; it needs your cost and a selling price after fees and tax." + band,
    ]


def _first_supplier(rec: Mapping[str, Any]) -> str:
    lead = rec.get("supplier_option")
    return _supplier_line(lead) if lead else "no supplier lead found yet"


def _recommendation_lines(products: Sequence[Mapping[str, Any]], brief: Mapping[str, Any]) -> list[str]:
    """ONE recommendation for the whole investigation (not one per product): the order to consider the five in, each with its best supplier, the units figure when the CFO has produced
    one (else how to get it), and what to improve or watch based on what viewers/web commentary said. Every line comes from PI's stored fields or a verified CFO result; nothing is computed here."""
    if not products:
        return []
    out = ["## Recommendation", "Consider them in this order. Nothing below is a purchase instruction.", ""]
    for p in products:
        rec = p.get("recommendation") or {}
        title = (p.get("candidate") or {}).get("candidate_title")
        fins = list(p.get("financials") or [])
        units = next((f for f in fins if f.get("leg_key") == "cfo.batch_size" and f.get("display")), None)
        landed = next((f for f in fins if f.get("leg_key") == "cfo.landed_cost" and f.get("display")), None)
        cons = list(rec.get("cons") or [])
        pros = list(rec.get("pros") or [])
        out.append(f"{p['rank']}. **{title}**")
        out.append(f"   - Supplier: {_first_supplier(rec)}")
        landed_txt = str(landed["display"]) if landed else "needs your supplier quote"
        units_txt = f"{units['display']} at most with your budget (a ceiling, not a recommendation)" if units else f"needs your supplier quote: say “how many units should I buy of #{p['rank']}?”"
        out.append(f"   - Landed cost: {landed_txt} · Units / batch size: {units_txt}")
        out.append("   - Improve / watch: " + (f"customers complain about {_join(cons, 3)}; address this in your listing and sourcing." if cons else f"no complaints found in the commentary; lean on what customers like ({_join(pros, 3)})." if pros else "no review commentary found for this product."))
    out.append("")
    return out


def summary_text(case: Mapping[str, Any], gaps: Sequence[str]) -> str:
    """The CEO's answer: exactly the final products (never the other discovered candidates), each laid out the same way: what customers say, the supplier lead (as a link, with a
    published price when the supplier states one), landed cost, units and profit/loss (a verified CFO result or the reason it is missing) and PI's recommendation; then the
    strongest opportunity, the optional next step and the notes."""
    brief = case.get("brief") or {}
    where = ", ".join(str(m).title() for m in (brief.get("marketplaces") or []))
    budget = f" (budget {_rupees_short(int(brief['budgetPaise']))})" if brief.get("budgetPaise") is not None else ""
    products = list(case.get("products") or [])
    lines = [f"## Top {len(products)} products: {brief.get('category') or 'your niche'}{' on ' + where if where else ''}{budget}",
             "These are opportunity candidates found from public web and video signal. They are not verified as selling well.", ""]
    if not products:
        lines.append("No product had enough signal to shortlist.")
    for p in products:
        rec = p.get("recommendation") or {}
        cand = p.get("candidate") or {}
        score = f"{str(p['finalScore']).removesuffix('.00')}/100" if p.get("finalScore") else "no score"
        lines.append(f"### {p['rank']}. {cand.get('candidate_title')} · {score}")
        pros, cons = list(rec.get("pros") or []), list(rec.get("cons") or [])
        lines.append("- **Customers say:** " + (f"liked for {_join(pros)}" if pros else "no positive themes found") + "; " + (f"watch out for {_join(cons)}." if cons else "no complaints found."))
        lines.append(f"- **Supplier:** {_supplier_line(rec.get('supplier_option'))}")
        if any(f.get("display") for f in (p.get("financials") or [])):  # only verified CFO results are listed per product; what is still missing is said once, in the recommendation
            lines += _financial_lines(p, brief)
        lines.append("")
    overall = case.get("overall")
    if overall:
        lines += [f"**Strongest opportunity: {overall.get('title')}** - {overall.get('reason')}.", ""]
    lines += _recommendation_lines(products, brief)
    if products:
        lines += ["### Next step (optional)",
                  f"- To get the landed cost and how many units to buy, say “how many units should I buy of #1?” (#1 to #{len(products)}). I will offer the suppliers and published price above and your research budget as choices, ask for the minimum order or delivery time, show exactly what I will save, and save only when you say yes. The CFO then works out the numbers.",
                  "- You can skip this. Units are a budget ceiling, not a recommendation to buy that many, and profit/loss also needs a selling price after fees and tax.", ""]
    notes = [*gaps, *(case.get("gaps") or [])]
    lines.append("### Notes")
    for n in dict.fromkeys(str(n) for n in notes):
        lines.append(f"- {n}.")
    lines += ["- Verified marketplace buyer reviews are not available; the commentary comes from public videos and articles.",
              "- Supplier leads are not checked by Metrion. These are estimates, not a purchase instruction."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------- CFO results for a shortlisted product (CEO -> CFO -> CEO)
CFO_LEGS = ("cfo.landed_cost", "cfo.batch_size")


def attach_results_to_case(tenant: UUID, product_name: str, legs: Sequence[LegResult]) -> None:
    """After the seller asked "is #N worth stocking?" (their own confirmed quote and budget, saved through the existing confirm card) and the CFO legs ran, the CEO
    writes what the CFO returned onto the saved research case of that product so the dashboard shows it: each verified figure with the display text the CEO resolved from
    its engine reference (`present_leg`, the same gate the chat uses), and each missing result as a named gap. PI computes nothing here. Best-effort: it never costs the
    seller the answer they already have."""
    if not product_name.strip():
        return
    try:
        entries: list[dict[str, Any]] = []
        for leg in legs:
            if leg.action_key not in CFO_LEGS:
                continue
            snap = present_leg(tenant, leg)
            for f in snap.get("figures", []):
                entries.append({"kind": "ENGINE", "authoritative": True, "leg_key": leg.action_key, "label": f["label"], "display": f["value"], "register": f["register"],
                                "as_of": f["as_of"], "note": f.get("note"), "ref": f["ref"], "status": "COMPLETE"})
            for gap in snap.get("gaps", []):
                gap = BATCH_PARTIAL_TEXT if leg.action_key == "cfo.batch_size" and "partial" in gap else gap
                entries.append({"kind": "GAP", "authoritative": True, "leg_key": leg.action_key, "label": CFO_LABELS[leg.action_key], "display": None, "status": "UNAVAILABLE", "reason": gap})
        if entries:
            ceo_pi_research.attach_cfo_figures(tenant, product_name, entries)
    except Exception:  # noqa: BLE001
        logger.exception("could not attach the CFO results to the research case")


CFO_LABELS = {"cfo.landed_cost": "Landed cost per unit", "cfo.batch_size": "Most units your budget allows"}
