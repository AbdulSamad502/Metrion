"""CMO 3.0 M10: Smart Market Opportunities and marketplace news for the seller's own products. Zero AI credits; no model; no new web search; nothing is invented.

It reads the market-trend reports the seller has already saved (a paid, approved step that exists elsewhere) and the seller's own product profiles and saved listings, and hands them to the pure rules in
`slim_cmo.market.intel`: news with headline, source, publication date, marketplace, freshness and seller impact; opportunities that name why they relate to a product, what the sources reported, a possible
explanation labelled as possible, the strength of the evidence, and next steps in PI, CMO and CFO. Demand is always shown as UNAVAILABLE: Metrion holds no search-volume or sales data. With no saved report
the answer is NO_REPORT, never an invented item."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from slim_cmo.market import intel

from backend.repositories import cmo_chat_repo, cmo_market_repo
from backend.services import cmo_history, cmo_runtime

logger = logging.getLogger(__name__)
MAX_REPORTS = 8
FACT_NAMES = frozenset({"brand", "product_type", "category", "material", "type", "color", "colour", "use_case", "style"})
NOTES = ["Everything here comes from your own saved market-trend reports and your product details. Metrion searched nothing new and invented nothing.",
         "Corroboration describes how widely attention is reported. It is not demand, sales or profit; demand is UNAVAILABLE.",
         "Metrion never changes a marketplace listing or setting."]


class MarketRefused(Exception):
    def __init__(self, code: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def _today() -> date:
    return cmo_runtime.build_runtime().clock().date()


def products(tenant: UUID) -> list[dict[str, Any]]:
    """The seller's products: name, a few confirmed facts, and the marketplaces they have a saved listing on."""
    names = dict(cmo_chat_repo.product_names(tenant))
    mps: dict[str, set[str]] = {}
    for g in cmo_history.history(tenant, limit=1)["groups"]:
        mps.setdefault(g["sku"], set()).add(g["marketplace"])
        names.setdefault(g["sku"], g["product"] or g["sku"])
    out = []
    for sku, name in sorted(names.items(), key=lambda kv: (kv[1].casefold(), kv[0])):
        try:
            facts = [f["value"] for f in cmo_chat_repo.saved_facts(tenant, sku) if str(f["name"]).casefold() in FACT_NAMES and len(f["value"]) <= 60]
        except Exception:  # noqa: BLE001 - facts only sharpen relevance; their absence never blocks the page
            logger.exception("could not read product facts")
            facts = []
        out.append({"sku": sku, "name": name, "facts": facts, "marketplaces": sorted(mps.get(sku, set()))})
    return out


def _check(marketplace: str | None) -> str | None:
    if marketplace is None:
        return None
    m = str(marketplace).upper()
    if m not in intel.MARKETPLACES:
        raise MarketRefused("BAD_MARKETPLACE", "Choose Amazon, Flipkart or Meesho.")
    return m


def overview(tenant: UUID, *, sku: str | None = None, marketplace: str | None = None, today: date | None = None) -> dict[str, Any]:
    """News and opportunities, optionally for one product and/or one marketplace. A product filter keeps only items that relate to that product; a marketplace filter keeps only items that name it
    (an item that names no marketplace is counted, not guessed into one)."""
    mp = _check(marketplace)
    day = today or _today()
    allp = products(tenant)
    if sku is not None and not any(p["sku"] == sku for p in allp):
        raise MarketRefused("UNKNOWN_PRODUCT", "That product is not one of yours yet.", 404)
    ctx = intel.product_context([p for p in allp if sku is None or p["sku"] == sku])
    reports = cmo_market_repo.recent_reports(tenant, MAX_REPORTS)
    ov = intel.overview(reports, ctx, day)
    news, opps = ov["news"], ov["opportunities"]
    unplaced = 0
    if mp:
        unplaced = sum(1 for n in news if not n["marketplaces"])
        news = [n for n in news if mp in n["marketplaces"]]
        opps = [o for o in opps if any(mp in a["marketplaces"] for a in o["relevance"]["affects"]) or not o["relevance"]["affects"]]
    if sku:
        news = [n for n in news if any(a["sku"] == sku for a in n["relevance"]["affects"]) or n["relevance"]["level"] == "NOT_ASSESSED" or not n["marketplaces"]]
        opps = [o for o in opps if any(a["sku"] == sku for a in o["relevance"]["affects"])]
    for i, o in enumerate(opps, start=1):
        o["rank"] = i
    return {**ov, "news": news, "opportunities": opps, "newsWithoutMarketplace": unplaced, "filters": {"sku": sku, "marketplace": mp},
            "products": [{"sku": p["sku"], "name": p["name"], "marketplaces": p["marketplaces"]} for p in allp], "marketplaces": list(intel.MARKETPLACES), "today": day.isoformat(),
            "freshnessRules": {"freshDays": intel.FRESH_DAYS, "recentDays": intel.RECENT_DAYS, "reportStaleDays": intel.REPORT_STALE_DAYS}, "notes": NOTES, "aiCredits": 0}


def news_only(tenant: UUID, *, sku: str | None, marketplace: str | None) -> dict[str, Any]:
    o = overview(tenant, sku=sku, marketplace=marketplace)
    return {k: o[k] for k in ("state", "message", "latestReportAt", "reportCount", "news", "newsWithoutMarketplace", "filters", "today", "freshnessRules", "notes", "aiCredits")}


def opportunities_only(tenant: UUID, *, sku: str | None, marketplace: str | None) -> dict[str, Any]:
    o = overview(tenant, sku=sku, marketplace=marketplace)
    return {k: o[k] for k in ("state", "message", "latestReportAt", "reportCount", "opportunities", "filters", "today", "notes", "aiCredits")}
