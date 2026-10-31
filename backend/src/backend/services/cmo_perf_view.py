"""CMO 3.0 M8: reading the seller's imported performance for the dashboard, for a saved listing version, and for the CEO chat. Zero AI credits; deterministic; nothing is generated or changed.

Every figure comes from `slim_cmo.history.metrics` over the seller's own imported rows. A product's rows are found only through the seller's confirmed SKU link; nothing is matched by name. A version's
"before" and "after" periods are equal-length windows either side of the seller-confirmed go-live date, and are compared only when the imported reports cover every day of both."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from backend.repositories import cmo_performance_repo as repo
from backend.services import cmo_history, cmo_runtime
from backend.services.cmo_performance import MARKETPLACES, PerformanceRefused, window_days
from slim_cmo.history import metrics as mx
from slim_cmo.history import performance

IMPORT_SOURCE = "your imported performance reports"
MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30
NO_WINDOW = "the comparison period length in days (set it on the performance page or tell me in chat)"
NO_LINK = "your confirmation of which SKU in your reports is this product"


def _today() -> date:
    return cmo_runtime.build_runtime().clock().date()


def _products(tenant: UUID) -> dict[tuple[str, str], dict[str, Any]]:
    """(sku, marketplace) -> {product name, versions oldest first}: the saved listings the seller can attach performance to. The account-wide history list is paged (newest first), so the product groups
    come from its summary (never truncated) and each product's versions are read on their own, ALL of them (no page limit): a seller with many versions of other products, or of this one, loses none."""
    top = cmo_history.history(tenant, limit=1)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for g in top["groups"]:
        out[(g["sku"], g["marketplace"])] = {"name": g["product"] or g["sku"], "versions": cmo_history.product_versions(tenant, g["sku"], g["marketplace"])}
    return out


def _links(tenant: UUID) -> dict[tuple[str, str], dict[str, Any]]:
    cur: dict[tuple[str, str], dict[str, Any]] = {}
    for r in repo.link_history(tenant):  # newest first
        cur.setdefault((r["sku"], r["marketplace"]), r)
    return cur


def _period(start: date | None, end: date | None, span: dict[str, Any], tenant: UUID) -> tuple[date, date]:
    if (start is None) != (end is None):
        raise PerformanceRefused("BAD_RANGE", "Give both a start and an end date, or neither.")
    if start is None or end is None:
        last = span["last"]
        if last is None:
            t = _today()
            return t - timedelta(days=DEFAULT_RANGE_DAYS - 1), t
        n = window_days(tenant)[0] or DEFAULT_RANGE_DAYS
        return last - timedelta(days=n - 1), last
    if end < start:
        raise PerformanceRefused("BAD_RANGE", "The end date is before the start date.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise PerformanceRefused("BAD_RANGE", f"Choose a range of at most {MAX_RANGE_DAYS} days.")
    return start, end


def _pairs(tenant: UUID, sku: str | None, marketplace: str | None) -> tuple[list[str] | None, list[str]]:
    """The 'MARKETPLACE|report sku' pairs to read, and what is missing. No product chosen = everything imported (None)."""
    if sku is None:
        return None, []
    links = {k: v for k, v in _links(tenant).items() if k[0] == sku and (marketplace is None or k[1] == marketplace)}
    if not links:
        return [], [NO_LINK]
    return [f"{mp}|{v['reportSku']}" for (_, mp), v in links.items()], []


def _slice(tenant: UUID, start: date, end: date, marketplace: str | None, pairs: list[str] | None) -> dict[str, Any]:
    daily = repo.daily(tenant, start, end, marketplace, pairs) if pairs != [] else []
    covered = repo.covered_days(tenant, start, end, marketplace)
    if pairs:
        wanted = {p.split("|", 1)[0] for p in pairs}
        covered = {m: d for m, d in covered.items() if m in wanted}
    s = mx.summarise(daily, start, end, covered)
    s["_daily"] = daily
    return s


def _json(s: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in s.items() if not k.startswith("_")}


def dashboard(tenant: UUID, *, marketplace: str | None, sku: str | None, start: date | None, end: date | None) -> dict[str, Any]:
    if marketplace is not None and marketplace.upper() not in MARKETPLACES:
        raise PerformanceRefused("BAD_MARKETPLACE", "Choose Amazon, Flipkart or Meesho.")
    mp = marketplace.upper() if marketplace else None
    span = repo.data_span(tenant, mp)
    a, b = _period(start, end, span, tenant)
    prods, links = _products(tenant), _links(tenant)
    if sku is not None and not any(k[0] == sku for k in prods):
        raise PerformanceRefused("NOT_FOUND", "That product has no saved listing.", 404)
    pairs, needs = _pairs(tenant, sku, mp)
    cur = _slice(tenant, a, b, mp, pairs)
    pa, pb = mx.previous_period(a, b)
    prev = _slice(tenant, pa, pb, mp, pairs)
    comparison = mx.compare(prev, cur)
    limits = []
    if not cur["complete"]:
        limits.append(f"Imported reports cover {cur['coveredDays']} of {cur['days']} days of the chosen period.")
    if not prev["complete"]:
        limits.append(f"Imported reports cover {prev['coveredDays']} of {prev['days']} days of the previous period, so previous-period differences are not shown where they would mislead.")
    corrected = repo.corrected_count(tenant, a, b, mp, pairs)
    if corrected:
        limits.append(f"{corrected} imported record(s) in this period were corrected by you. The corrected values are used in these numbers; the imported values are kept.")
    name_of = {k[0]: v["name"] for k, v in prods.items()}
    hand_mp = mp or (next(iter({k[1] for k in prods if k[0] == sku}), None) if sku and len({k[1] for k in prods if k[0] == sku}) == 1 else None)
    ins = mx.with_handoff(mx.insights(comparison, _json(prev), _json(cur), limits), name_of.get(sku or ""), hand_mp)
    options = sorted({k[0] for k in prods})
    return {"filters": {"marketplace": mp, "sku": sku, "start": a.isoformat(), "end": b.isoformat()}, "aiCredits": 0,
            "products": [{"sku": s, "name": name_of[s], "marketplaces": sorted(k[1] for k in prods if k[0] == s), "linked": sorted(k[1] for k in links if k[0] == s)} for s in options],
            "marketplaces": sorted({k[1] for k in prods} | set(repo.covered_days(tenant, a, b).keys())),
            "dataSpan": {"lastImportAt": span["lastImportAt"].isoformat() if span["lastImportAt"] else None, "first": span["first"].isoformat() if span["first"] else None,
                         "last": span["last"].isoformat() if span["last"] else None},
            "source": IMPORT_SOURCE, "current": _json(cur), "previous": _json(prev), "comparison": comparison, "trend": mx.trend(cur["_daily"], a, b),
            "insights": ins, "needs": needs, "limits": limits, "imports": [{**i, "periodStart": i["periodStart"].isoformat(), "periodEnd": i["periodEnd"].isoformat(), "importedAt": i["importedAt"].isoformat()}
                                                                                for i in repo.imports(tenant, mp, 5)],
            "correctedRecords": corrected, "never": mx.NEVER_CAUSE}


# ------------------------------------------------------------------------------------------------ one saved listing, version by version
MAX_VERSION_PAGE = 100


def versions(tenant: UUID, sku: str, marketplace: str, *, limit: int | None = None, offset: int = 0, order: str = "asc") -> dict[str, Any]:
    """For each version of this product on this marketplace that has a seller-confirmed go-live date: the N days before and the N days from that date, side by side. Equal length by construction and
    re-checked by the same comparability rules as the sales-order observation (`performance.assess`). Observational only. Every version of the product is known (its go-live dates decide which periods overlap);
    `limit`/`offset`/`order` choose which versions are ANALYSED and returned (limit None = all). Oldest first by default, newest first with order=\"desc\"; the order is stable."""
    mp = marketplace.upper()
    prods = _products(tenant)
    prod = prods.get((sku, mp))
    if prod is None:
        raise PerformanceRefused("NOT_FOUND", "That product has no saved listing on this marketplace.", 404)
    n, who = window_days(tenant)
    link = _links(tenant).get((sku, mp))
    live = {g["generationId"]: g["wentLiveOn"] for g in repo.golives(tenant, sku, mp)}
    needs: list[str] = []
    if n is None:
        needs.append(NO_WINDOW)
    if link is None:
        needs.append(NO_LINK)
    out: list[dict[str, Any]] = []
    for v in prod["versions"]:
        row: dict[str, Any] = {"versionId": v["id"], "number": v["number"], "createdAt": str(v["createdAt"])[:10], "source": v["sourceText"], "changedSection": v.get("changedSection"),
                               "wentLiveOn": live[v["id"]].isoformat() if v["id"] in live else None, "state": "NOT_ASSESSED", "needs": [], "reasons": []}
        if v["id"] not in live:
            row["needs"].append(f"the date you put version {v['number']} live (nothing is assumed from when it was created or approved)")
        out.append(row)
    if order not in ("asc", "desc"):
        raise PerformanceRefused("BAD_ORDER", "Order must be asc (oldest first) or desc (newest first).")
    offset = max(0, int(offset))
    ordered = out if order == "asc" else list(reversed(out))
    page = ordered if limit is None else ordered[offset:offset + max(1, min(int(limit), MAX_VERSION_PAGE))]
    has_more = limit is not None and offset + len(page) < len(ordered)
    for row in page:
        if row["wentLiveOn"] is None or n is None or link is None:
            continue
        g = date.fromisoformat(row["wentLiveOn"])
        others = [d for k, d in live.items() if k != row["versionId"] and g - timedelta(days=n) <= d <= g + timedelta(days=n - 1)]
        if others:
            row.update(state="INCOMPARABLE", reasons=["OVERLAPPING_PERIODS"], needs=[], note="Another version went live inside these periods, so the two periods are not a clean before and after.")
            continue
        pairs = [f"{mp}|{link['reportSku']}"]
        before, after = _slice(tenant, g - timedelta(days=n), g - timedelta(days=1), mp, pairs), _slice(tenant, g, g + timedelta(days=n - 1), mp, pairs)
        row["previous"], row["following"] = _json(before), _json(after)
        if not (before["complete"] and after["complete"]):
            row["needs"].append(f"imported reports covering {(g - timedelta(days=n)).isoformat()} to {(g + timedelta(days=n - 1)).isoformat()} "
                                f"(covered: {before['coveredDays']} of {before['days']} days before, {after['coveredDays']} of {after['days']} days after)")
            continue
        comp = mx.compare(before, after)
        bad = [m for m in (*mx.COUNTS, *mx.RATES) if comp[m]["state"] == mx.AVAILABLE and performance.assess([
            {"source": IMPORT_SOURCE, "metric": m, "periodStart": before["periodStart"], "periodEnd": before["periodEnd"], "value": comp[m]["previous"]},
            {"source": IMPORT_SOURCE, "metric": m, "periodStart": after["periodStart"], "periodEnd": after["periodEnd"], "value": comp[m]["current"], "versionId": row["versionId"]}])["state"] != performance.COMPARABLE]
        if bad:
            row.update(state="INCOMPARABLE", reasons=["PERIODS_NOT_COMPARABLE"], note="These periods failed the comparability check.")
            continue
        facts = [mx.sentence(m, comp[m], f"in the {n} days after version {row['number']} went live than in the {n} days before") for m in (*mx.COUNTS, *mx.RATES) if comp[m]["state"] == mx.AVAILABLE]
        row.update(state="OBSERVED_COMPARABLE", comparison=comp, observations=facts, insights=mx.with_handoff(mx.insights(comp, _json(before), _json(after), [f"Go-live date is the date you stated ({row['wentLiveOn']}); Metrion cannot verify it."]), prod["name"], mp),
                   attribution="NOT_ATTRIBUTED", note=performance.CAUSE)
    return {"sku": sku, "marketplace": mp, "product": prod["name"], "source": IMPORT_SOURCE, "windowDays": n, "windowSetBy": who, "linked": link["reportSku"] if link else None, "versions": page, "total": len(out), "limit": limit, "offset": offset, "hasMore": has_more, "order": order, "needs": needs, "aiCredits": 0}


# ------------------------------------------------------------------------------------------------ what the seller still has to confirm (dashboard + chat)
def mappings(tenant: UUID) -> dict[str, Any]:
    prods, links = _products(tenant), _links(tenant)
    golive_hist = repo.golive_history(tenant)
    live = {}
    for g in golive_hist:  # newest first
        live.setdefault(g["generationId"], g)
    n, who = window_days(tenant)
    items = []
    for (sku, mp), p in sorted(prods.items()):
        link = links.get((sku, mp))
        vs = []
        for v in p["versions"]:
            g = live.get(v["id"])
            vs.append({"versionId": v["id"], "number": v["number"], "createdAt": str(v["createdAt"])[:10], "wentLiveOn": g["wentLiveOn"].isoformat() if g else None,
                       "confirmedAt": g["confirmedAt"].isoformat() if g else None})
        missing = ([] if link else [NO_LINK]) + ([f"a go-live date for version {x['number']}" for x in vs if x["wentLiveOn"] is None])
        items.append({"sku": sku, "product": p["name"], "marketplace": mp, "reportSku": link["reportSku"] if link else None, "linkConfirmedAt": link["confirmedAt"].isoformat() if link else None,
                      "versions": vs, "status": "COMPLETE" if not missing else "NEEDS_CONFIRMATION", "missing": missing,
                      "history": {"links": [{"reportSku": r["reportSku"], "confirmedAt": r["confirmedAt"].isoformat()} for r in repo.link_history(tenant) if r["sku"] == sku and r["marketplace"] == mp][:10],
                                  "golives": [{"versionId": g["generationId"], "wentLiveOn": g["wentLiveOn"].isoformat(), "confirmedAt": g["confirmedAt"].isoformat()} for g in golive_hist
                                              if g["sku"] == sku and g["marketplace"] == mp][:20]}})
    return {"items": items, "windowDays": n, "windowSetBy": who, "windowBounds": [7, 90], "missing": ([] if n else [NO_WINDOW]) + list(dict.fromkeys(m for i in items for m in i["missing"])),
            "hasImports": bool(repo.imports(tenant, None, 1)), "aiCredits": 0}


def imports(tenant: UUID) -> dict[str, Any]:
    return {"imports": [{**i, "periodStart": i["periodStart"].isoformat(), "periodEnd": i["periodEnd"].isoformat(), "importedAt": i["importedAt"].isoformat()} for i in repo.imports(tenant, None, 30)], "aiCredits": 0}


# ------------------------------------------------------------------------------------------------ ranking the seller's own listings against each other (chat)
def ranking(tenant: UUID, metric: str) -> dict[str, Any]:
    """Each linked product over the latest `window` days of imported data, ordered by one rate (lowest first). A comparison within the seller's own listings only; there is no outside benchmark."""
    if metric not in mx.RATES:
        raise PerformanceRefused("BAD_METRIC", "Rank by CTR or conversion rate.")
    span = repo.data_span(tenant, None)
    a, b = _period(None, None, span, tenant)
    rows, missing = [], []
    prods = _products(tenant)
    for (sku, mp), link in sorted(_links(tenant).items()):
        if (sku, mp) not in prods:
            continue
        s = _slice(tenant, a, b, mp, [f"{mp}|{link['reportSku']}"])
        m = s["metrics"][metric]
        row = {"sku": sku, "product": prods[(sku, mp)]["name"], "marketplace": mp, "state": m["state"], "value": m["value"], "text": mx.fmt(metric, m["value"]) if m["value"] is not None else None, "reason": m["reason"]}
        (rows if m["state"] == mx.AVAILABLE else missing).append(row)
    rows.sort(key=lambda r: (r["value"], r["product"]))
    return {"metric": metric, "label": mx.LABEL[metric], "periodStart": a.isoformat(), "periodEnd": b.isoformat(), "ranked": rows, "notAssessed": missing, "source": IMPORT_SOURCE,
            "note": "This compares your own listings with each other over the same period. It is not a benchmark against other sellers.", "aiCredits": 0}
