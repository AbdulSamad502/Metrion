"""Deterministic listing-performance maths and grounded insights (CMO 3.0 M8). Pure: integers only (rates in basis points), no model, no I/O, no floats.

Nothing here is estimated. A figure is AVAILABLE only when every row in the chosen period carries it and the period is fully covered by imported reports; otherwise it is NOT_ASSESSED (the data is
there but incomplete) or UNAVAILABLE (the reports never carried it), with the reason in words. Differences between two periods are observations ("higher", "lower"); the wording never says a listing
change caused them. Every insight is assembled from measured figures by fixed templates, so it can state no number that was not measured."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

AVAILABLE, NOT_ASSESSED, UNAVAILABLE = "AVAILABLE", "NOT_ASSESSED", "UNAVAILABLE"
COUNTS = ("impressions", "clicks", "orders", "units", "sales")
RATES = ("ctr", "cvr")
LABEL = {"impressions": "Impressions", "clicks": "Clicks", "orders": "Orders", "units": "Units sold", "sales": "Sales", "ctr": "Click-through rate", "cvr": "Conversion rate"}
FLAT_BP = 10      # a rate that moved by under 0.10 percentage point is described as unchanged (a display tolerance, not a statistical test)
STABLE_BP = 500   # a count that moved by under 5% is described as stable (same note)
NEVER_CAUSE = "This compares two periods. It does not show that anything you changed caused the difference, and other things (season, price, stock, advertising, competitors) also move these figures."


# ------------------------------------------------------------------------------------------------ formatting (integers only)
def rate_bp(num: int | None, den: int | None) -> int | None:
    """num / den as basis points (1/100 of a percent), half rounded up; None when it cannot be worked out."""
    if num is None or den is None or den <= 0:
        return None
    return (num * 20000 + den) // (2 * den)


def fmt_rate(bp: int) -> str:
    sign = "-" if bp < 0 else ""
    a = abs(bp)
    return f"{sign}{a // 100}.{a % 100:02d}%"


def fmt_money(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(paise), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head, *parts, tail]) if head else ",".join([*parts, tail])
    return f"{sign}₹{s}.{p:02d}"


def fmt(metric: str, v: int) -> str:
    return fmt_money(v) if metric == "sales" else fmt_rate(v) if metric in RATES else f"{v:,}"


# ------------------------------------------------------------------------------------------------ one period
def days_between(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def summarise(daily: Sequence[Mapping[str, Any]], start: date, end: date, covered: Mapping[str, set[date]]) -> dict[str, Any]:
    """Totals for [start, end]. `daily`: one dict per day with `rows` and, per count metric m, `m` (sum) and `n_m` (rows that carry it). `covered`: marketplace -> the days some import for it covers.
    The period is complete only when every marketplace in the data covers every day of it."""
    want = set(days_between(start, end))
    gaps = {mp: len(want - days) for mp, days in covered.items()}
    complete = bool(covered) and not any(gaps.values())
    missing_days = max(gaps.values()) if gaps else len(want)
    rows = sum(int(d.get("rows") or 0) for d in daily)
    out: dict[str, Any] = {}
    for m in COUNTS:
        carried = sum(int(d.get(f"n_{m}") or 0) for d in daily)
        if rows == 0 or carried == 0:
            out[m] = {"state": UNAVAILABLE, "value": None, "reason": "Your imported reports have no rows for this period." if rows == 0 else f"Your reports do not carry {LABEL[m].lower()} for this period."}
        elif carried < rows:
            out[m] = {"state": NOT_ASSESSED, "value": None, "reason": f"{rows - carried} of {rows} report rows have no {LABEL[m].lower()}, so a total would be misleading."}
        elif not complete:
            out[m] = {"state": NOT_ASSESSED, "value": None, "reason": f"Imported reports leave {missing_days} of {len(want)} days of this period uncovered, so a total would be misleading."}
        else:
            out[m] = {"state": AVAILABLE, "value": sum(int(d.get(m) or 0) for d in daily), "reason": None}
    for r, (n, d) in {"ctr": ("clicks", "impressions"), "cvr": ("orders", "clicks")}.items():
        a, b = out[n], out[d]
        v = rate_bp(a["value"], b["value"]) if a["state"] == b["state"] == AVAILABLE else None
        if v is not None:
            out[r] = {"state": AVAILABLE, "value": v, "reason": None}
        else:
            bad = a if a["state"] != AVAILABLE else b
            why = bad["reason"] if bad["state"] != AVAILABLE else f"There were no {LABEL[d].lower()} in this period, so {LABEL[r].lower()} cannot be worked out."
            out[r] = {"state": bad["state"] if bad["state"] != AVAILABLE else NOT_ASSESSED, "value": None, "reason": why}
    return {"periodStart": start.isoformat(), "periodEnd": end.isoformat(), "days": len(want), "coveredDays": len(want) - missing_days, "complete": complete, "metrics": out}


def previous_period(start: date, end: date) -> tuple[date, date]:
    n = (end - start).days + 1
    return start - timedelta(days=n), start - timedelta(days=1)


def trend(daily: Sequence[Mapping[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """One point per day with data: each count only when every row that day carries it (otherwise None, drawn as a gap), the rates only when both parts are known. Days with no rows are absent."""
    by = {d["date"]: d for d in daily}
    pts = []
    for day in days_between(start, end):
        d = by.get(day)
        if not d or not d.get("rows"):
            continue
        p: dict[str, Any] = {"date": day.isoformat()}
        for m in COUNTS:
            p[m] = int(d.get(m) or 0) if d.get(f"n_{m}") == d["rows"] else None
        p["ctr"] = rate_bp(p["clicks"], p["impressions"])
        p["cvr"] = rate_bp(p["orders"], p["clicks"])
        pts.append(p)
    return pts


# ------------------------------------------------------------------------------------------------ two periods
def compare(prev: Mapping[str, Any], cur: Mapping[str, Any]) -> dict[str, Any]:
    """Per metric: both values, the absolute difference and (where the earlier value is above zero) the relative difference in basis points; NOT_ASSESSED with the reason otherwise.
    Rates differ in percentage points (basis points), never as a ratio of ratios."""
    out: dict[str, Any] = {}
    for m in (*COUNTS, *RATES):
        a, b = prev["metrics"][m], cur["metrics"][m]
        if a["state"] != AVAILABLE or b["state"] != AVAILABLE:
            bad = a if a["state"] != AVAILABLE else b
            out[m] = {"state": NOT_ASSESSED, "reason": ("The earlier period: " if a["state"] != AVAILABLE else "The later period: ") + str(bad["reason"])}
            continue
        diff = b["value"] - a["value"]
        rel = None if m in RATES or a["value"] == 0 else (1 if diff >= 0 else -1) * ((abs(diff) * 20000 + a["value"]) // (2 * a["value"]))
        out[m] = {"state": AVAILABLE, "previous": a["value"], "current": b["value"], "difference": diff, "relativeBp": rel,
                  "direction": "UP" if diff > 0 else "DOWN" if diff < 0 else "SAME"}
    return out


def _flat(m: str, c: Mapping[str, Any]) -> bool:
    if m in RATES:
        return abs(c["difference"]) < FLAT_BP
    return c["difference"] == 0 or (c["relativeBp"] is not None and abs(c["relativeBp"]) < STABLE_BP)


def _word(c: Mapping[str, Any], m: str) -> str:
    return "unchanged" if _flat(m, c) and c["difference"] == 0 else ("about the same" if _flat(m, c) else "higher" if c["direction"] == "UP" else "lower")


def sentence(m: str, c: Mapping[str, Any], when: str) -> str:
    """One observation, in words that describe and do not explain: 'Orders were higher after ... (30 → 42).'"""
    if c["state"] != AVAILABLE:
        return f"{LABEL[m]} cannot be compared: {c['reason']}"
    w = _word(c, m)
    verb = {"higher": "was higher", "lower": "was lower", "unchanged": "was unchanged", "about the same": "was about the same"}[w]
    return f"{LABEL[m]} {verb} {when} ({fmt(m, c['previous'])} → {fmt(m, c['current'])})."


def describe_change(m: str, c: Mapping[str, Any]) -> str:
    """A difference in words and a mark (never colour alone). Rates differ in percentage points; counts also carry the relative change when the earlier value was above zero."""
    if c["state"] != AVAILABLE:
        return "Not assessed"
    d = c["difference"]
    if d == 0:
        return "● Same as the previous period"
    a = abs(d)
    amount = f"{a // 100}.{a % 100:02d} points" if m in RATES else fmt(m, a)
    rb = c.get("relativeBp")
    rel = "" if rb is None else f" ({'+' if d > 0 else '-'}{abs(rb) // 100}.{abs(rb) % 100:02d}%)"
    return f"{'▲ Up' if d > 0 else '▼ Down'} {amount}{rel} from the previous period"


def facts(comparison: Mapping[str, Any], prev: Mapping[str, Any], cur: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in (*COUNTS, *RATES):
        c = comparison[m]
        if c["state"] == AVAILABLE:
            out.append({"metric": m, "label": LABEL[m], "previous": fmt(m, c["previous"]), "current": fmt(m, c["current"]), "previousPeriod": f"{prev['periodStart']} to {prev['periodEnd']}",
                        "currentPeriod": f"{cur['periodStart']} to {cur['periodEnd']}"})
    return out


# ------------------------------------------------------------------------------------------------ insights
def _ins(kind: str, what: str, metrics: list[str], comparison: Mapping[str, Any], prev: Mapping[str, Any], cur: Mapping[str, Any], matters: str, step: str, action: Mapping[str, str] | None, limits: list[str]) -> dict[str, Any]:
    ev = [f for f in facts(comparison, prev, cur) if f["metric"] in metrics]
    return {"kind": kind, "what": what, "evidence": ev, "whyItMatters": matters, "nextStep": step, "action": dict(action) if action else None,
            "limits": [*limits, NEVER_CAUSE], "measured": bool(ev),
            "explanation": "Measured facts are the figures above. “Why it may matter” and “Next step” are possible explanations and suggestions, not findings."}


ACTIONS = {
    "TITLE": {"kind": "TITLE", "route": "M3", "label": "Review title clarity and keyword relevance", "ask": "analyse my title options"},
    "CONTENT": {"kind": "CONTENT", "route": "M5", "label": "Review listing content and buyer questions", "ask": "what questions will buyers ask about my product"},
    "KEYWORDS": {"kind": "KEYWORDS", "route": "M2", "label": "Review the keyword evidence", "ask": "research keywords for my product"},
    "REVISE": {"kind": "REVISE", "route": "M6", "label": "Consider a listing revision (you approve it first)", "ask": "rewrite a section of my listing"},
}
_MP_WORD = {"AMAZON": "Amazon", "FLIPKART": "Flipkart", "MEESHO": "Meesho"}
# The sentence each hand-off puts in the chat bar. Every one is answered by CODE that already exists (free, no model, nothing generated or changed): the saved-audit and keyword advice of M7 (which cites the
# M2 keyword evidence), the M5 buyer-question answer, and the M7 view of the latest saved version with its own audit. The seller presses send; nothing runs on arrival. The frontend mirrors these strings.
HANDOFF = {
    "TITLE": "What should I improve next in my {product} listing on {marketplace}?",
    "KEYWORDS": "What should I improve next in my {product} listing on {marketplace}?",
    "CONTENT": "What questions will buyers ask about my {product}?",
    "REVISE": "Show my latest {product} listing on {marketplace}",
}


def with_handoff(items: Sequence[Mapping[str, Any]], product: str | None, marketplace: str | None) -> list[dict[str, Any]]:
    """Each insight's action gains the chat-bar sentence for ITS product and marketplace (None when either is not known, so nothing ambiguous is offered)."""
    out = []
    for i in items:
        a = i.get("action")
        if a and product and marketplace in _MP_WORD:
            a = {**a, "draft": HANDOFF[a["kind"]].format(product=product, marketplace=_MP_WORD[marketplace]), "product": product, "marketplace": marketplace}
        elif a:
            a = {**a, "draft": None}
        out.append({**i, "action": a})
    return out


def insights(comparison: Mapping[str, Any], prev: Mapping[str, Any], cur: Mapping[str, Any], limits: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Grounded observations from two periods. Fewer than a measured pair = one 'not enough data' item and nothing else."""
    lim = list(limits)
    c = comparison
    ok = lambda m: c[m]["state"] == AVAILABLE  # noqa: E731
    up = lambda m: ok(m) and c[m]["direction"] == "UP" and not _flat(m, c[m])  # noqa: E731
    down = lambda m: ok(m) and c[m]["direction"] == "DOWN" and not _flat(m, c[m])  # noqa: E731
    flat = lambda m: ok(m) and _flat(m, c[m])  # noqa: E731
    p = f"{prev['periodStart']} to {prev['periodEnd']}"
    q = f"{cur['periodStart']} to {cur['periodEnd']}"
    found: list[dict[str, Any]] = []
    if up("impressions") and down("ctr"):
        found.append(_ins("IMPRESSIONS_UP_CTR_DOWN", f"Impressions were higher in {q} than in {p}, but the click-through rate was lower.", ["impressions", "clicks", "ctr"], c, prev, cur,
                          "More people saw the listing while a smaller share clicked. That can happen when the listing is shown to less relevant searches, or when the title or main image is less convincing.",
                          "Review the title for clarity and the keywords it uses against what buyers search for.", ACTIONS["TITLE"], lim))
    if up("clicks") and flat("cvr"):
        found.append(_ins("CLICKS_UP_CVR_FLAT", f"Clicks were higher in {q} than in {p}, while the conversion rate stayed about the same.", ["clicks", "orders", "cvr"], c, prev, cur,
                          "Extra interest did not turn into a larger share of orders. Orders can still rise because there were more visitors.", "Check that the bullets and description answer what buyers ask before they buy.", ACTIONS["CONTENT"], lim))
    if up("clicks") and down("cvr"):
        found.append(_ins("CLICKS_UP_CVR_DOWN", f"Clicks were higher in {q} than in {p}, but the conversion rate was lower.", ["clicks", "orders", "cvr"], c, prev, cur,
                          "More visitors came, but a smaller share ordered. Visitors may have found less of what they expected on the page.", "Review the listing content and the questions buyers ask.", ACTIONS["CONTENT"], lim))
    if down("orders"):
        found.append(_ins("ORDERS_DOWN", f"Orders were lower in {q} than in {p}.", ["orders", "clicks", "impressions"], c, prev, cur,
                          "Fewer orders can come from fewer visits, a smaller share ordering, or things outside the listing.", "Look at whether impressions, clicks or the conversion rate fell with it, and review the matching part of the listing.", ACTIONS["CONTENT"], lim))
    if up("sales") and flat("units"):
        found.append(_ins("SALES_UP_UNITS_STABLE", f"Sales were higher in {q} than in {p} while units sold stayed about the same.", ["sales", "units"], c, prev, cur,
                          "The same number of units brought in more money, which usually means a higher price or a different product mix.", "Check the price and the mix of products in the report before reading this as listing performance.", None, lim))
    if down("impressions") and not any(f["kind"] == "IMPRESSIONS_UP_CTR_DOWN" for f in found):
        found.append(_ins("IMPRESSIONS_DOWN", f"Impressions were lower in {q} than in {p}.", ["impressions"], c, prev, cur,
                          "Fewer impressions mean the listing was shown less often, which can follow changes in keywords, availability, ads or demand.", "Review the keyword evidence for the terms in the title.", ACTIONS["KEYWORDS"], lim))
    if not found:
        measured = [m for m in (*COUNTS, *RATES) if ok(m)]
        if not measured:
            return [{"kind": "INSUFFICIENT_DATA", "what": "There is not enough data to identify a reliable trend.", "evidence": [], "whyItMatters": "Without a complete, comparable pair of periods any statement would be a guess.",
                     "nextStep": "Import the missing report periods and confirm the SKU and go-live date.", "action": None, "limits": [*lim, NEVER_CAUSE], "measured": False, "explanation": "Nothing here was measured."}]
        found.append(_ins("NO_CLEAR_CHANGE", f"No change large enough to describe was measured between {p} and {q}.", measured[:3], c, prev, cur,
                          "A steady listing is not evidence that it cannot be improved or that it should not be.", "Keep the listing under review; compare again after the next report.", None, lim))
    return found
