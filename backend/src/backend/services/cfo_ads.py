"""Advertising evaluation per marketplace (docs/specs/cfo-phase3-scope.md 3b): coverage, ownership, spend, status.

Which source speaks for advertising in a marketplace and period (an ingested report, a hand-entered pool, a ledger entry confirmed as advertising, or an explicit
"no advertising" declaration) is decided by the cost-ownership arbitration in `cfo_costs` — one source counts, or the marketplace is reported as a conflict. The
chosen figures go to the engine (`ad_spend_status`, `consolidate_ads`, `ad_ratios`). No money arithmetic here.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from calc_engine.formulas.ad_spend import AdCoverage, AdCoverageSource, AdMarketplaceInput, AdSpendStatus, ad_spend_status
from calc_engine.repositories import ad_report_repo
from calc_engine.types import Paise, sum_paise

from backend.services import cfo_costs

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
NO_EVIDENCE = "no advertising report, cost or 'no advertising' statement exists for this marketplace and period"
CONFLICT = "advertising appears in more than one place for the same dates (an uploaded report, a cost entered by hand, or the expense ledger); choose which one is right"
ACCOUNT_LEVEL = "advertising was entered as one amount for the whole account, which cannot be split by marketplace"


def _overlaps(a: AdCoverage, start: date, end: date) -> bool:
    return a.start <= end and a.end >= start


def evaluate_marketplace(tenant_id: UUID, marketplace: str, start: date, end: date, *, net_revenue_paise: int | None,
                         sources: cfo_costs.Sources | None = None) -> AdMarketplaceInput:
    """The advertising standing of one marketplace in one period."""
    src = sources if sources is not None else cfo_costs.load_sources(tenant_id, [marketplace], start, end)
    ads = cfo_costs.Sources([i for i in src.pools if i.component == "ADVERTISING"], [i for i in src.ledger if i.component == "ADVERTISING"],
                            [i for i in src.reports if i.component == "ADVERTISING" and i.marketplace == marketplace])
    res = cfo_costs.resolve(ads, [marketplace], cfo_costs.chooser(tenant_id, start, end))
    if any(c.component == "ADVERTISING" and c.marketplace in (marketplace, "ALL") for c in res.conflicts):
        return AdMarketplaceInput(marketplace, AdSpendStatus.UNKNOWN, None, None, net_revenue_paise, CONFLICT)
    counted = [i for i in res.counted if i.component == "ADVERTISING"]
    mine = [i for i in counted if i.marketplace == marketplace]
    account_level = [i for i in ads.pools if i.marketplace is None] + [i for i in ads.ledger if i.marketplace is None]
    declared = ad_report_repo.declared_no_ads(tenant_id, marketplace)
    if not mine and account_level and not declared:
        return AdMarketplaceInput(marketplace, AdSpendStatus.UNKNOWN, None, None, net_revenue_paise, ACCOUNT_LEVEL)

    coverage: list[AdCoverage] = list(declared)
    spend: int | None = None
    attributed: int | None = None
    report_items = [i for i in mine if i.source == "REPORT"]
    hand_items = [i for i in mine if i.source in ("POOL", "LEDGER")]
    if report_items:
        coverage += [c for c in ad_report_repo.report_coverage(tenant_id, marketplace) if _overlaps(c, start, end)]
        got = ad_report_repo.spend_in_period(tenant_id, marketplace, start, end)
        if got is not None:
            spend, attributed = got.spend_paise, got.attributed_sales_paise
    elif hand_items:
        coverage += [AdCoverage(marketplace, i.span[0], i.span[1], AdCoverageSource.MANUAL_POOL) for i in hand_items if i.span is not None]
        spend = sum_paise([Paise(int(i.value["amount_paise"])) for i in hand_items]).value  # type: ignore[call-overload]
    status = ad_spend_status(marketplace=marketplace, period_start=start, period_end=end, coverage=coverage, spend_paise=spend)
    reason = None
    if status is AdSpendStatus.MISSING_COVERAGE:
        reason = "the advertising data does not cover the whole period"
    elif status is AdSpendStatus.UNKNOWN:
        reason = NO_EVIDENCE
    if status is AdSpendStatus.VERIFIED_ZERO and spend is None:
        spend = 0  # a seller's explicit declaration: a verified zero, not a guess
    return AdMarketplaceInput(marketplace, status, spend, attributed, net_revenue_paise, reason)
