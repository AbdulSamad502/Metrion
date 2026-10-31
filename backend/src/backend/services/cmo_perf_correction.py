"""Correcting a wrongly imported performance record (docs/CMO-3.0/CMO_M8_PERFORMANCE.md sections 6c and 10). Zero AI credits; deterministic; nothing is estimated.

The imported row is never changed. A correction is a new, append-only record that says what the effective values are now, what they were, why, who and when; the dashboard, the trends and the before/after
comparisons read the effective values (the `cmo_perf_line_effective` view), and every screen can show the original beside the corrected value. A blank stays blank (NOT_REPORTED, never zero); a void sets every
effective metric to blank. A correction needs a reason, the exact record, and the seller's knowledge of the latest correction they saw, so two corrections made from the same starting point cannot both be saved."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from slim_cmo.history import report_import

from backend.repositories import cmo_performance_repo as repo
from backend.services.cmo_performance import MARKETPLACES, PerformanceRefused

METRICS = ("impressions", "clicks", "orders", "units", "sales")
MAX_PAGE = 100
DEFAULT_DAYS = 30
MAX_DAYS = 366
NEVER_ZERO = "A blank value means the report did not carry it. It is kept blank, never treated as zero."


def _mp(marketplace: str) -> str:
    m = str(marketplace or "").upper()
    if m not in MARKETPLACES:
        raise PerformanceRefused("BAD_MARKETPLACE", "Choose Amazon, Flipkart or Meesho.")
    return m


def _show(v: dict[str, Any]) -> dict[str, Any]:
    return {k: (None if x is None else int(x)) for k, x in v.items()}


def list_lines(tenant: UUID, marketplace: str, *, report_sku: str | None, start: date | None, end: date | None, limit: int = 25, offset: int = 0, today: date) -> dict[str, Any]:
    """The imported records of one marketplace (optionally one report SKU and a date range, newest first, paged): the original values, the effective values, and whether each was corrected."""
    mp = _mp(marketplace)
    limit, offset = max(1, min(int(limit), MAX_PAGE)), max(0, int(offset))
    if (start is None) != (end is None):
        raise PerformanceRefused("BAD_RANGE", "Give both a start and an end date, or neither.")
    if start is None or end is None:
        end = today
        start = today - timedelta(days=DEFAULT_DAYS - 1)
    if end < start or (end - start).days >= MAX_DAYS:
        raise PerformanceRefused("BAD_RANGE", f"Choose a range of at most {MAX_DAYS} days with the end on or after the start.")
    rows, total = repo.lines(tenant, mp, (report_sku or "").strip() or None, start, end, limit, offset)
    for r in rows:
        r["original"], r["effective"] = _show(r["original"]), _show(r["effective"])
    return {"marketplace": mp, "reportSku": report_sku or None, "start": start.isoformat(), "end": end.isoformat(), "total": total, "limit": limit, "offset": offset, "hasMore": offset + limit < total,
            "lines": rows, "note": NEVER_ZERO, "aiCredits": 0}


def history(tenant: UUID, *, marketplace: str | None, report_sku: str | None, limit: int = 25, offset: int = 0) -> dict[str, Any]:
    limit, offset = max(1, min(int(limit), MAX_PAGE)), max(0, int(offset))
    mp = _mp(marketplace) if marketplace else None
    rows = repo.corrections(tenant, mp, (report_sku or "").strip() or None, limit + 1, offset)
    return {"corrections": [{**r, "previous": _show(r["previous"]), "corrected": _show(r["corrected"])} for r in rows[:limit]], "limit": limit, "offset": offset, "hasMore": len(rows) > limit, "aiCredits": 0,
            "note": "Corrections are kept for good. The imported value is never changed or deleted; the corrected value is used in the numbers."}


def _parse(metric: str, raw: Any) -> int | None:
    """None or an empty string = blank (not reported). Otherwise a whole non-negative number (sales in rupees, up to two decimals)."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    try:
        return report_import.parse_paise(raw) if metric == "sales" else report_import.parse_count(raw)
    except ValueError as exc:
        raise PerformanceRefused("BAD_VALUE", f"{metric.title()}: {exc}") from None


def correct(tenant: UUID, user: UUID, *, line_id: UUID, changes: dict[str, Any], void: bool, reason: str, expected_correction_id: UUID | None) -> dict[str, Any]:
    """Saves one correction. `changes` maps a metric to its new value (blank = not reported); metrics not mentioned keep their current effective value. `expected_correction_id` is the correction the seller
    saw as current for this record (None = they saw none). Refused: no reason, no change, an impossible value (clicks above impressions), or a record that was corrected since the seller looked."""
    why = (reason or "").strip()
    if not 3 <= len(why) <= 300:
        raise PerformanceRefused("REASON_REQUIRED", "Say why you are correcting this record (3 to 300 characters).")
    cur = repo.line(tenant, line_id)
    if cur is None:
        raise PerformanceRefused("NOT_FOUND", "That imported record was not found.", 404)
    if (cur["correctionId"] or None) != (str(expected_correction_id) if expected_correction_id else None):
        raise PerformanceRefused("STALE", "This record was corrected after you opened it. Reload it and check the current values first.", 409)
    unknown = [k for k in changes if k not in METRICS]
    if unknown:
        raise PerformanceRefused("BAD_METRIC", "Unknown value: " + ", ".join(sorted(unknown)) + ".")
    prev = cur["effective"]
    if void:
        if changes:
            raise PerformanceRefused("VOID_WITH_CHANGES", "Either void the record or change its values, not both.")
        new: dict[str, int | None] = {m: None for m in METRICS}
    else:
        new = {m: (_parse(m, changes[m]) if m in changes else prev[m]) for m in METRICS}
        if not changes:
            raise PerformanceRefused("NO_CHANGE", "Nothing to correct: give at least one new value.")
    changed = [m for m in METRICS if new[m] != prev[m]]
    if not changed:
        raise PerformanceRefused("NO_CHANGE", "Those values are already the effective values of this record.", 409)
    if new["clicks"] is not None and new["impressions"] is not None and new["clicks"] > new["impressions"]:
        raise PerformanceRefused("BAD_VALUE", "Clicks cannot be higher than impressions.")
    try:
        saved = repo.add_correction(tenant, user, current=cur, new=new, voided=bool(void), changed=changed, reason=why)
    except repo.CorrectionConflict:
        raise PerformanceRefused("CONFLICT", "Another correction of this record was saved first. Reload it and check the current values.", 409) from None
    return {"corrected": True, "correctionId": saved["id"], "at": saved["createdAt"], "lineId": cur["lineId"], "voided": bool(void), "changed": changed, "previous": _show(prev), "now": _show(new),
            "original": _show(cur["original"]), "message": "Saved. The imported value is kept and shown beside the corrected one; the corrected value is used in your numbers. " + NEVER_ZERO, "aiCredits": 0}
