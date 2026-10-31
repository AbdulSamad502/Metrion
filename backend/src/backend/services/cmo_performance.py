"""CMO 3.0 B8: performance OBSERVED alongside a saved listing version, from two things only the seller can state (their SKU in the sales report; the date the version went live) plus their own uploaded
sales rows. Never a claim of impact: `slim_cmo.history.performance.assess` decides whether two observations are comparable and always says the change is not shown to be the cause.

Nothing is guessed. A missing link, a missing or single go-live date, an unset window length, uploaded data that does not cover a window, or sales rows without order references each leave the answer
NOT_ASSESSED and are named in `needs`. The window length is an operator setting (`performance_window_days`) with NO default, because choosing it is a business decision, not ours."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from backend.repositories import cmo_chat_repo, cmo_performance_repo as repo
from backend.services import cmo_runtime
from slim_cmo.history import performance

WINDOW_KEY = "performance_window_days"
SOURCE = "your uploaded sales reports"
METRIC = "orders (distinct order references)"
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")


class PerformanceRefused(Exception):
    def __init__(self, code: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def _mp(marketplace: str) -> str:
    m = str(marketplace or "").upper()
    if m not in MARKETPLACES:
        raise PerformanceRefused("BAD_MARKETPLACE", "Choose Amazon, Flipkart or Meesho.")
    return m


def sku_candidates(tenant: UUID, marketplace: str) -> dict[str, Any]:
    """What the seller can choose from: the SKUs in their own uploaded reports for this marketplace. Nothing is matched for them."""
    mp = _mp(marketplace)
    seen: dict[str, dict[str, Any]] = {c["reportSku"]: c for c in repo.report_sku_candidates(tenant, mp)}
    for c in repo.import_skus(tenant, mp):
        seen.setdefault(c["reportSku"], c)
    return {"marketplace": mp, "candidates": list(seen.values()),
            "note": "These are the SKUs in the reports you uploaded. Metrion does not guess which one is your product; you choose."}


def confirm_link(tenant: UUID, user: UUID, *, sku: str, marketplace: str, report_sku: str, replace: bool = False) -> dict[str, Any]:
    """The seller's statement: this CMO product on this marketplace is that SKU in their reports. The SKU must really appear in THEIR uploaded rows; the product must have a saved listing."""
    mp = _mp(marketplace)
    if not cmo_chat_repo.listing_targets(tenant, sku=sku, marketplace=mp):
        raise PerformanceRefused("NO_LISTING", "That product has no saved listing on this marketplace yet.", 404)
    if not (repo.report_sku_exists(tenant, mp, report_sku) or repo.sku_in_imports(tenant, mp, report_sku)):
        raise PerformanceRefused("SKU_NOT_IN_REPORTS", "That SKU does not appear in the sales or performance reports you uploaded for this marketplace, so it cannot be linked.")
    before = repo.current_link(tenant, sku, mp)
    if before is not None and before["reportSku"] != report_sku and not replace:  # a different earlier statement is never silently replaced
        raise PerformanceRefused("LINK_EXISTS", f"You already confirmed that this product is “{before['reportSku']}” in your reports. Confirm the change explicitly to replace it; the earlier statement stays in the history.", 409)
    saved = repo.add_link(tenant, user, sku=sku, marketplace=mp, report_sku=report_sku)
    return {"linked": True, **saved, "sku": sku, "marketplace": mp, "reportSku": report_sku, "previous": before["reportSku"] if before and before["reportSku"] != report_sku else None,
            "message": "Saved as your statement. It lets Metrion read your sales for this product; it does not publish or change anything."}


def confirm_golive(tenant: UUID, user: UUID, *, generation_id: UUID, went_live_on: date, today: date, replace: bool = False) -> dict[str, Any]:
    """The seller's statement that this saved version went live on a date. Not in the future and not before the version was created; a correction is a new statement."""
    pack = cmo_chat_repo.listing_pack(tenant, generation_id)
    if pack is None:
        raise PerformanceRefused("NOT_FOUND", "That listing version was not found.", 404)
    if went_live_on > today:
        raise PerformanceRefused("DATE_IN_FUTURE", "A go-live date cannot be in the future.")
    created = pack["createdAt"].date() if hasattr(pack["createdAt"], "date") else pack["createdAt"]
    if went_live_on < created:
        raise PerformanceRefused("BEFORE_CREATED", f"This version was created on {created.isoformat()}; it cannot have gone live before that.")
    earlier = next((h for h in repo.golive_history(tenant) if h["generationId"] == str(generation_id)), None)  # newest first
    if earlier is not None and earlier["wentLiveOn"] != went_live_on and not replace:  # a different earlier date is never silently replaced
        raise PerformanceRefused("GOLIVE_EXISTS", f"You already confirmed {earlier['wentLiveOn'].isoformat()} as the go-live date of this version. Confirm the change explicitly to replace it; the earlier statement stays in the history.", 409)
    saved = repo.add_golive(tenant, user, generation_id=generation_id, marketplace=pack["marketplace"], went_live_on=went_live_on)
    return {"recorded": True, **saved, "previous": earlier["wentLiveOn"].isoformat() if earlier and earlier["wentLiveOn"] != went_live_on else None, "generationId": str(generation_id), "wentLiveOn": went_live_on.isoformat(),
            "message": "Saved as your statement. Metrion cannot see the marketplace, so it uses your date as given."}


MIN_WINDOW, MAX_WINDOW = 7, 90


def window_days(tenant: UUID) -> tuple[int | None, str | None]:
    """(days, who set it): the seller's own setting wins; otherwise the operator's platform config; otherwise unset. There is no default."""
    own = repo.window_setting(tenant)
    if own is not None:
        return own["days"], "YOU"
    n = _window_days(tenant)
    return (n, "OPERATOR") if n is not None else (None, None)


def set_window(tenant: UUID, user: UUID, days: Any) -> dict[str, Any]:
    if type(days) is not int or not MIN_WINDOW <= days <= MAX_WINDOW:
        raise PerformanceRefused("BAD_WINDOW", f"Choose a whole number of days from {MIN_WINDOW} to {MAX_WINDOW}.")
    return {**repo.set_window(tenant, user, days), "message": f"Saved. Listing versions are now compared over {days}-day periods."}


def _window_days(tenant: UUID) -> int | None:
    rt = cmo_runtime.build_runtime()
    v = rt.store.load_config(tenant, (WINDOW_KEY,), rt.clock().date()).get(WINDOW_KEY)
    return v if type(v) is int and v >= 1 else None


def observations(tenant: UUID, sku: str, marketplace: str) -> tuple[list[dict[str, Any]], list[str]]:
    """(observations, what is still needed). One observation per version that has a seller-stated go-live date: distinct orders in the N days starting that date, for the linked report SKU."""
    needs: list[str] = []
    mp = marketplace.upper()
    n = window_days(tenant)[0]
    if n is None:
        needs.append("the comparison period length in days (you can set it on the performance page or tell me in chat)")
    link = repo.current_link(tenant, sku, mp)
    if link is None:
        needs.append("your confirmation of which SKU in your sales reports is this product")
    live = repo.golives(tenant, sku, mp)
    if len(live) < 2:
        needs.append("a go-live date you confirmed for at least two saved versions")
    if needs:
        return [], needs
    assert n is not None and link is not None
    rng = repo.data_range(tenant, mp)
    if rng is None:
        return [], ["sales reports uploaded for this marketplace"]
    out: list[dict[str, Any]] = []
    for v in sorted(live, key=lambda x: (x["wentLiveOn"], x["generationId"])):
        start = v["wentLiveOn"]
        end = start + timedelta(days=n - 1)
        if start < rng[0] or end > rng[1]:
            needs.append(f"uploaded sales data covering {start.isoformat()} to {end.isoformat()} (you have {rng[0].isoformat()} to {rng[1].isoformat()})")
            continue
        count = repo.orders_between(tenant, mp, link["reportSku"], start, end)
        if count is None:
            needs.append(f"an order reference on every sales row between {start.isoformat()} and {end.isoformat()}")
            continue
        out.append({"source": SOURCE, "metric": METRIC, "periodStart": start.isoformat(), "periodEnd": end.isoformat(), "value": count, "versionId": v["generationId"]})
    return out, sorted(set(needs))


def assess_for(tenant: UUID, sku: str, marketplace: str) -> dict[str, Any]:
    """The `performance` block of a history answer: the engine's verdict on real observations, plus exactly what is still needed when it cannot assess."""
    try:
        obs, needs = observations(tenant, sku, marketplace)
    except Exception:  # noqa: BLE001 - a failed read never invents data: the answer stays NOT_ASSESSED
        obs, needs = [], ["the sales data could not be read just now"]
    result = performance.assess(obs)
    result["needs"] = needs
    try:  # M8: the same product's imported-report view (before/after each confirmed go-live date); a failure leaves it out and never invents it
        from backend.services import cmo_perf_view  # noqa: PLC0415 - cmo_perf_view imports this module

        result["versionAnalysis"] = cmo_perf_view.versions(tenant, sku, marketplace.upper())
    except Exception:  # noqa: BLE001
        result["versionAnalysis"] = None
    return result
