"""CMO 3.0 M10 in the CEO chat: "Find opportunities for my products", "Show latest marketplace news", "What has changed on Amazon?", "Which opportunities should I focus on?", "How does this news affect
my products?", "What should I do about this update?". Free: no model, no AI credit, no new web search, nothing generated or changed.

The answers come from `services.cmo_market` (the seller's saved market-trend reports and own product details, read by fixed rules). The CEO only works out WHICH marketplace the seller means, asks ONE short
question when it is not clear, and shows the stored result as a card. The phrases are deliberately narrow so the existing market-research request ("latest news in ecommerce", "Amazon news") still starts the
research plan; this reads what has already been researched. With no saved report it says so and invents nothing."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)
KIND = "MARKET_INTELLIGENCE"
PAGE = "/dashboard/cmo/market"
MP_NAME = {"AMAZON": "Amazon", "FLIPKART": "Flipkart", "MEESHO": "Meesho"}
FAILED = "I could not read your saved market information just now. Nothing was changed. Please try again."
_FOLD = lambda t: " ".join(re.sub(r"[?!.,;\"“”']", " ", t.casefold()).split())  # noqa: E731
TOP = 5

OPPS, FOCUS, NEWS, CHANGED, AFFECTS, ACTION = "OPPORTUNITIES", "FOCUS", "NEWS", "CHANGED", "AFFECTS", "ACTION"
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (FOCUS, re.compile(r"\bwhich\b.{0,25}\bopportunit\w+\b.{0,35}\b(?:focus|prioriti[sz]e|start with|pursue|go after|first|chase)\b|\bwhich opportunit\w+ (?:are|is) (?:the )?(?:best|most (?:relevant|important))\b")),
    (AFFECTS, re.compile(r"\bhow\b.{0,12}\b(?:does|do|will|would|could)\b.{0,15}\b(?:this|that|the|these|the latest)\b.{0,15}\b(?:news|update|updates|announcement|change|changes)\b.{0,25}\baffect\b")),
    (ACTION, re.compile(r"\bwhat\b.{0,12}\b(?:should|do|can|shall)\b.{0,6}\b(?:i|we)\b.{0,12}\bdo\b.{0,20}\b(?:about|with|regarding)\b.{0,12}\b(?:this|that|the|the latest)\b.{0,10}\b(?:update|news|announcement|change)\b")),
    (OPPS, re.compile(r"\b(?:find|show|list|discover|give me|see|what are)\b.{0,25}\b(?:market |smart |new )?opportunit\w+\b")),
    (CHANGED, re.compile(r"\bwhat\b.{0,6}\b(?:has|have)\b.{0,12}\bchanged\b.{0,14}\b(?:on|at|in|with)\b.{0,6}\b(amazon|flipkart|meesho)\b|\bwhat\b.{0,6}\bchanged\b.{0,14}\b(?:on|at|in|with)\b.{0,6}\b(amazon|flipkart|meesho)\b")),
    (NEWS, re.compile(r"\b(?:show|see|open|give|get|read)\b.{0,12}\b(?:me )?(?:the |my |any )?(?:latest|recent|saved|new)\b.{0,12}\bmarketplace news\b|\bmy (?:saved )?marketplace news\b|\bmarketplace news (?:summary|feed|digest)\b")),
)
_MP = re.compile(r"\b(amazon|flipkart|meesho)\b")


def classify(text: str) -> str | None:
    t = _FOLD(text or "")
    if not t or len(t) > 300:
        return None
    return next((k for k, rx in _RULES if rx.search(t)), None)


def _mp_in(text: str) -> str | None:
    found = {m.group(1).upper() for m in _MP.finditer(_FOLD(text))}
    return next(iter(found)) if len(found) == 1 else None


def _prior(tenant: UUID, investigation_id: UUID) -> dict[str, Any] | None:
    from backend.repositories import investigation_repo as inv_repo  # noqa: PLC0415

    try:
        for m in reversed(inv_repo.list_messages(tenant, investigation_id)):
            c = m.get("choices") if isinstance(m, dict) else None
            if m.get("role") == "CEO" and isinstance(c, dict):
                return c if c.get("kind") == KIND else None
    except Exception:  # noqa: BLE001 - no history means no remembered item
        logger.exception("could not read the previous card")
    return None


def _card(view: str, **kw: Any) -> dict[str, Any]:
    return {"version": 1, "kind": KIND, "view": view, "page": PAGE, "aiCredits": 0, **kw}


def _slim(o: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("state", "message", "latestReportAt", "reportCount", "newsWithoutMarketplace", "notes")
    return {k: o.get(k) for k in keys}


def reply(ctx: Any, text: str, investigation_id: UUID) -> tuple[str, dict[str, Any]] | None:
    """A code-written answer for a market request, or None when the message is not one (it then goes on to the rest of the CEO unchanged)."""
    from backend.services import cmo_market  # noqa: PLC0415

    tenant = ctx.tenant_id
    prior = _prior(tenant, investigation_id)
    pending = prior.get("ask") if isinstance(prior, dict) and prior.get("view") == "CLARIFY" and isinstance(prior.get("ask"), dict) else None
    kind = classify(text)
    if kind is None and pending is not None and len(_FOLD(text).split()) <= 4 and _mp_in(text):
        kind = pending.get("kind")  # a short answer to the marketplace question I just asked
    if kind is None:
        return None
    try:
        return _answer(tenant, kind, text, prior, pending, cmo_market)
    except cmo_market.MarketRefused as exc:
        return exc.detail, _card("REFUSED", message=exc.detail, code=exc.code)
    except Exception:  # noqa: BLE001
        logger.exception("market request failed")
        return FAILED, _card("REFUSED", message=FAILED, code="FAILED")


def _answer(tenant: UUID, kind: str, text: str, prior: Mapping[str, Any] | None, pending: Mapping[str, Any] | None, svc: Any) -> tuple[str, dict[str, Any]]:
    mp = (pending or {}).get("marketplace") or _mp_in(text)
    if kind == CHANGED and mp is None:
        q = "Which marketplace do you mean?"
        return q, _card("CLARIFY", question=q, options=[{"label": MP_NAME[m], "marketplace": m} for m in MP_NAME], ask={"kind": CHANGED})
    o = svc.overview(tenant, marketplace=mp)
    base = _slim(o)
    if o["state"] == "NO_REPORT":
        return o["message"], _card("NO_REPORT", **base, news=[], opportunities=[])
    stale = f" {o['message']}" if o["state"] == "STALE_REPORTS" and o.get("message") else ""
    news, opps = o["news"], o["opportunities"]
    where = f" on {MP_NAME[mp]}" if mp else ""
    if kind in (NEWS, CHANGED):
        if not news:
            msg = f"Your saved reports contain no marketplace news{where} that names it." + (f" {o['newsWithoutMarketplace']} item(s) name no marketplace." if o["newsWithoutMarketplace"] else "") + stale
            return msg, _card("NEWS", **base, news=[], filter={"marketplace": mp})
        top = news[0]
        msg = f"From your saved reports, {len(news)} marketplace news item(s){where}. Newest first: “{top['headline']}” ({top['publishedAt'] or 'date unknown'}, {top['freshness'].lower().replace('_', ' ')}). {top['sourceNote']}{stale}"
        return msg, _card("NEWS" if kind == NEWS else "CHANGED", **base, news=news[:TOP], moreNews=max(0, len(news) - TOP), filter={"marketplace": mp})
    if kind in (OPPS, FOCUS):
        if not opps:
            msg = "Your saved reports contain no opportunity that relates to your products." + stale
            return msg, _card("OPPORTUNITIES", **base, opportunities=[])
        top = opps[0]
        if kind == FOCUS:
            msg = (f"Start with “{top['title']}”: relevance to your products {top['relevance']['level']}, evidence {top['evidenceStrength']}, freshness {top['observed']['freshness'].lower().replace('_', ' ')}. "
                   f"{top['rankedBecause']} Demand is UNAVAILABLE: Metrion holds no search-volume or sales data.{stale}")
            return msg, _card("FOCUS", **base, opportunities=opps[:TOP], moreOpportunities=max(0, len(opps) - TOP))
        msg = f"{len(opps)} opportunit{'y' if len(opps) == 1 else 'ies'} from your saved reports that relate to your products, strongest first. These are leads to check, not predictions.{stale}"
        return msg, _card("OPPORTUNITIES", **base, opportunities=opps[:TOP], moreOpportunities=max(0, len(opps) - TOP))
    # AFFECTS / ACTION: about "this" update: the one the previous card focused on, else the most relevant stored news item
    pool = (prior or {}).get("news") or []
    pick = None
    fid = (prior or {}).get("focusId")
    if fid:
        pick = next((n for n in news if n["id"] == fid), None)
    if pick is None and pool:
        pick = next((n for n in news if n["id"] == pool[0].get("id")), None)
    if pick is None and news:
        pick = news[0]
    if pick is None:
        return "Your saved reports contain no marketplace news to relate to your products." + stale, _card("NEWS", **base, news=[])
    if kind == AFFECTS:
        aff = pick["relevance"]["affects"]
        msg = (f"About “{pick['headline']}” ({pick['publishedAt'] or 'date unknown'}): " + (f"it may affect {len(aff)} of your product(s). {pick['relevance']['reason']}" if aff else pick["relevance"]["reason"]) + f" {pick['impact']}{stale}")
        return msg, _card("AFFECTS", **base, news=[pick], focusId=pick["id"])
    msg = f"About “{pick['headline']}”: {pick['impact']} Next steps are on the card; Metrion changes nothing on a marketplace.{stale}"
    return msg, _card("ACTION", **base, news=[pick], focusId=pick["id"])
