"""The expense ledger as an input to the period P&L (S4a; expense-tracker.md F6/F7, AC17; engine §5.17). Only called when `config.expense_ledger_feeds_pnl()` is on.

Everything here is selection and routing; no amount is added, compared or signed (the engine feed `calc_engine.formulas.ledger_feed` selects and sums, and the signed pool is
passed on as is). The feed's pools map to the existing P&L terms:

* ADVERTISING pool -> the advertising term (one entry, unless the caller already supplied advertising entries: those win and the ledger's is reported as skipped, so a
  figure is never counted twice);
* DIRECT pool (seller-attributed direct costs) -> the other-attributed term (likewise);
* STORAGE and OVERHEAD pools are NOT allocated to contribution profit: `CONTRIBUTION_PROFIT.v1` has no storage term (the explicit StorageCosts term belongs to the v2 formula
  version, which is inactive until the release date, engine §5.17 "Cost-class mapping"; routing storage into the other-attributed term was not adopted). They are returned as
  unallocated lines (UnallocatedStorage, UnallocatedOverhead) to show beside contribution profit, labelled with the formula version.

A cost class with no counted row is "not entered" (None), never zero. Metric results for the unallocated lines are minted and stored through the same path as the dashboard
summary, so each carries an `engine_result_ref`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID

from calc_engine.api.expense_metrics import mint_ledger_feed_metrics
from calc_engine.formulas.ledger_feed import ledger_feed
from calc_engine.repositories import expense_tracker_repo as ledger
from calc_engine.repositories import metric_result_repo

from backend.services import expense_assignment_data as assignment_data

FORMULA_VERSION = "CONTRIBUTION_PROFIT.v1"
CONFIG_VERSION = "EXPENSE_LEDGER_FEED.v1"
_UNALLOCATED = ("STORAGE", "OVERHEAD")


@dataclass(frozen=True, slots=True)
class UnallocatedLine:
    cost_class: str
    paise: int | None  # None = not entered
    engine_result_ref: str | None


@dataclass(frozen=True, slots=True)
class LedgerPnlFeed:
    advertising_entries: tuple[Mapping[str, object], ...]
    other_entries: tuple[Mapping[str, object], ...]
    unallocated: tuple[UnallocatedLine, ...]
    skipped: tuple[str, ...]  # classes the caller already supplied, so the ledger's was not added
    watermark: str
    formula_version: str = FORMULA_VERSION


def build(
    tenant_id: UUID,
    *,
    period_start: date,
    period_end: date,
    as_of_date: date,
    request_has_advertising: bool,
    request_has_other: bool,
    computed_at: datetime | None = None,
) -> LedgerPnlFeed:
    events = ledger.feed_events(tenant_id, period_start=period_start, period_end=period_end)
    catalog = {sku: sku for sku in ledger.known_skus(tenant_id)}
    feed = ledger_feed(
        events, period_start=period_start, period_end=period_end, channel_scope=None, catalog=catalog,
        basis_data=assignment_data.basis_data(tenant_id, period_start=period_start, period_end=period_end, events=events, as_of=as_of_date),
    )

    skipped: list[str] = []
    ads: tuple[Mapping[str, object], ...] = ()
    other: tuple[Mapping[str, object], ...] = ()
    for cost_class, supplied, assign in (("ADVERTISING", request_has_advertising, "ads"), ("DIRECT", request_has_other, "other")):
        pool = feed.pools[cost_class].total
        if pool is None:
            continue  # not entered: no term is created (a missing input is not zero)
        if supplied:
            skipped.append(cost_class)
            continue
        entry = ({"amount_paise": pool.value},)
        if assign == "ads":
            ads = entry
        else:
            other = entry

    now = computed_at or datetime.now(timezone.utc)
    minted = mint_ledger_feed_metrics(feed, ingestion_run_ids=[], adapter_versions=[], active_adjustment_ids=[], computed_at=now, as_of_date=as_of_date)
    period = f"{period_start.isoformat()}/{period_end.isoformat()}"
    metric_result_repo.save_many(
        tenant_id,
        [(m.result, {"grain": m.grain, "target_ref": str(tenant_id) if m.target_ref == "tenant" else m.target_ref, "period": period, "config_version": CONFIG_VERSION})
         for m in minted],
    )
    refs: dict[str, Any] = {m.target_ref: m.result for m in minted if m.result.metric_code == "EXPENSE_BY_COST_CLASS"}
    lines = []
    for cost_class in _UNALLOCATED:
        pool = feed.pools[cost_class].total
        result = refs.get(cost_class)
        lines.append(UnallocatedLine(cost_class, None if pool is None else pool.value, str(result.id) if (result is not None and pool is not None) else None))
    return LedgerPnlFeed(ads, other, tuple(lines), tuple(skipped), feed.watermark)
