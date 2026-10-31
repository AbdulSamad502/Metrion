"""Listing content is not business performance (CMO 3.0 M7). Metrion cannot see when a listing change went live on a marketplace (it publishes nothing and reads nothing back), and a change in
sales, revenue, conversion, ranking, visibility or demand has many causes. So no revision is ever called an improvement or a cause here. This module only reports whether real, comparable
observations were supplied, and states plainly what is missing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

NOT_ASSESSED, COMPARABLE, INCOMPARABLE = "NOT_ASSESSED", "OBSERVED_COMPARABLE", "INCOMPARABLE"
NEVER = "Sales, revenue, conversion, search ranking, visibility and demand are not assessed for a listing revision."
MISSING = ("No comparable marketplace performance data is available. To assess a change you would need your uploaded sales or traffic reports for the same product and marketplace, for two periods of "
           "the same length, from the same source and measure.")
CAUSE = ("This shows what was observed in each period. It does not show that the listing change caused it. Go-live dates are the dates you stated; Metrion cannot see the marketplace and cannot verify them.")


def _d(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def assess(observations: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Each observation: {source, metric, periodStart, periodEnd, value}. Fewer than two, or any that cannot be read = NOT_ASSESSED. Two or more are COMPARABLE only when they share source and
    metric, cover periods of the same length and do not overlap; otherwise INCOMPARABLE with the reason. A comparable result is never attributed to a version."""
    base: dict[str, Any] = {"state": NOT_ASSESSED, "never": NEVER, "missing": MISSING, "periods": [], "attribution": "NOT_ATTRIBUTED", "note": CAUSE}
    obs = list(observations or [])
    if len(obs) < 2:
        return base
    rows = []
    for o in obs:
        s, e = _d(o.get("periodStart")), _d(o.get("periodEnd"))
        if s is None or e is None or e < s or o.get("value") is None or not o.get("source") or not o.get("metric"):
            return base
        rows.append({"source": str(o["source"]), "metric": str(o["metric"]), "start": s, "end": e, "value": o["value"], "days": (e - s).days + 1, **({"versionId": str(o["versionId"])} if o.get("versionId") else {})})
    rows.sort(key=lambda r: r["start"])
    reasons = []
    if len({r["source"] for r in rows}) > 1:
        reasons.append("DIFFERENT_SOURCE")
    if len({r["metric"] for r in rows}) > 1:
        reasons.append("DIFFERENT_MEASURE")
    if len({r["days"] for r in rows}) > 1:
        reasons.append("DIFFERENT_PERIOD_LENGTH")
    if any(a["end"] >= b["start"] for a, b in zip(rows, rows[1:])):
        reasons.append("OVERLAPPING_PERIODS")
    periods = [{"source": r["source"], "metric": r["metric"], "periodStart": r["start"].isoformat(), "periodEnd": r["end"].isoformat(), "days": r["days"], "value": r["value"],
                **({"versionId": r["versionId"]} if "versionId" in r else {})} for r in rows]
    if reasons:
        return {**base, "state": INCOMPARABLE, "reasons": reasons, "periods": periods, "missing": "These periods cannot be compared: " + ", ".join(r.lower().replace("_", " ") for r in reasons) + "."}
    return {**base, "state": COMPARABLE, "periods": periods, "missing": None}
