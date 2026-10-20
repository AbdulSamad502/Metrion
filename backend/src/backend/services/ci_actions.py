"""CI action composition shared by `api/v1/ci.py`'s direct-execution endpoints and
`agents/ceo_hub.py`'s CEO-routed actions (C20: "both entry paths enforce the same checks").
Extracted rather than duplicated so the two paths can never quietly diverge on how inputs are
assembled for calc-engine or for `start_discovery_run`.

Neither function here does money arithmetic (CLAUDE.md hard rule) — `run_price_scenario`
only resolves a competitor price from CI's own persisted snapshot and a caller-supplied
seller price, then hands both to calc-engine's `compute_price_positioning`/
`compute_repricing_scenario` unchanged, exactly as `handoff.py`'s own docstring specifies.
`run_discovery` does no arithmetic at all — it is a pass-through to
`competitor_intelligence.discovery.discovery_run.start_discovery_run`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

from calc_engine.api.compute_metric import MetricResult, compute_price_positioning, compute_repricing_scenario
from calc_engine.formulas.price_positioning import CompetitorPrice, RepricingStance
from calc_engine.repositories import metric_result_repo
from calc_engine.types import Confidence, Paise
from competitor_intelligence.discovery.discovery_run import DiscoveryRunOutcome, start_discovery_run
from competitor_intelligence.discovery.search_cache import PostgresSearchResultCache
from competitor_intelligence.repositories import (
    ci_tenant_config_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
    seller_product_profile_repo,
)

from competitor_intelligence.seller_product.derive import derive_canonical
from competitor_intelligence.seller_product.merge import merge_seller_product
from competitor_intelligence.seller_product.types import SellerProduct
from competitor_intelligence.types import CaptureStatus

from backend.services.ci_search import select_search_provider

_METRIC_CONFIG_VERSION = "CI_PRICE_SCENARIO.v1"


def load_seller_product(tenant_id: UUID, product_id: str) -> SellerProduct | None:
    """The exact §5.5.1 composition `get_seller_product`/`put_seller_product` use — shared
    here so the discovery-run start endpoint, the price-scenario/discovery CEO Hub actions,
    and the direct-execution routes never each re-derive it slightly differently."""
    canonical = derive_canonical(tenant_id, sku=product_id, marketplace_item_id=product_id)
    manual_row = seller_product_profile_repo.get_profile(tenant_id, product_id)
    manual_overrides = seller_product_profile_repo.profile_to_manual_overrides(manual_row)
    if canonical is None and not manual_overrides:
        return None
    if canonical is None:
        manual_overrides = dict(manual_overrides)
        manual_overrides.setdefault("product_id", product_id)
    return merge_seller_product(canonical, manual_overrides)


def _metric_result_to_dict(result: MetricResult) -> dict[str, object]:
    return {
        "engineResultRef": str(result.id),
        "metricCode": result.metric_code,
        "valuePaise": result.value_paise,
        "isAvailable": result.is_available,
        "confidence": result.confidence,
        "calculationBasis": result.calculation_basis,
        "unavailableReason": result.unavailable_reason,
        "asOfDate": result.as_of_date.isoformat() if result.as_of_date else None,
    }


def _latest_usable_competitor_snapshot(tenant_id: UUID, url_id: UUID) -> dict[str, object] | None:
    """This competitor's most recent snapshot that actually carries a usable price — skips
    PENDING_MANUAL_ENTRY (no resolved price at all) and any snapshot with a null
    `listed_price_paise`, without inventing a price for either case (§6.18 rule 1)."""
    for snapshot in competitor_snapshot_repo.list_snapshots(tenant_id, url_id, limit=20):
        if (
            snapshot["capture_status"] in (CaptureStatus.COMPLETE.value, CaptureStatus.PARTIAL.value)
            and snapshot["listed_price_paise"] is not None
        ):
            return snapshot
    return None


@dataclass(frozen=True, slots=True)
class PriceScenarioOutcome:
    price_positioning: list[dict[str, object]]
    repricing_scenario: dict[str, object] | None


def run_price_scenario(
    tenant_id: UUID,
    url_id: UUID,
    *,
    seller_price_paise: int,
    stance: str | None = None,
    stance_param_pct: Decimal | None = None,
    stance_param_paise: int | None = None,
    now: datetime | None = None,
) -> PriceScenarioOutcome | None:
    """Wires §5.15's `compute_price_positioning`/`compute_repricing_scenario` in for real —
    CI never derives this itself; this function only assembles the inputs (this competitor's
    current price, DERIVED per the CI boundary) and passes through whatever the engine
    returns, unchanged. Returns `None` when the competitor_url doesn't exist / isn't ACTIVE /
    isn't owned by this tenant — the caller (an HTTP route or the CEO dispatcher) decides how
    to surface that (404 vs. a failed `agent_run`)."""
    urls = competitor_url_repo.get_by_ids(tenant_id, [url_id])
    if not urls:
        return None
    url_row = urls[0]

    now = now or datetime.now(timezone.utc)
    snapshot = _latest_usable_competitor_snapshot(tenant_id, url_id)
    competitor_prices = (
        [
            CompetitorPrice(
                value_paise=Paise(int(snapshot["listed_price_paise"])),
                confidence=Confidence.DERIVED,  # CI-sourced price — never VERIFIED/PROVISIONAL downstream
                source_ref=str(snapshot["id"]),
            )
        ]
        if snapshot is not None
        else []
    )

    grain = "SKU" if url_row.get("linked_sku") else "COMPETITOR_URL"
    target_ref = url_row.get("linked_sku") or str(url_id)

    seller_price = Paise(seller_price_paise)
    # MANUAL per data-foundation.md §7.1: "incorporates a seller-supplied value" — entered
    # directly by the caller, not read off canonical sales-ledger data.
    seller_price_confidence = Confidence.MANUAL

    positioning_results = compute_price_positioning(
        seller_price_paise=seller_price,
        seller_price_confidence=seller_price_confidence,
        competitor_prices=competitor_prices,
        computed_at=now,
    )
    for result in positioning_results:
        metric_result_repo.save(
            tenant_id,
            result,
            grain=grain,
            target_ref=target_ref,
            period=None,
            config_version=_METRIC_CONFIG_VERSION,
        )

    repricing_dict: dict[str, object] | None = None
    if stance is not None:
        stance_enum = RepricingStance(stance)
        stance_param: Fraction | Paise | None
        if stance_enum == RepricingStance.BEAT_LOWEST_BY_PCT:
            stance_param = Fraction(stance_param_pct) if stance_param_pct is not None else None
        elif stance_enum == RepricingStance.BEAT_LOWEST_BY_PAISE:
            stance_param = Paise(stance_param_paise) if stance_param_paise is not None else None
        else:
            stance_param = None

        repricing_result = compute_repricing_scenario(
            seller_price_paise=seller_price,
            seller_price_confidence=seller_price_confidence,
            competitor_prices=competitor_prices,
            stance=stance_enum,
            stance_param=stance_param,
            computed_at=now,
        )
        metric_result_repo.save(
            tenant_id,
            repricing_result,
            grain=grain,
            target_ref=target_ref,
            period=None,
            config_version=_METRIC_CONFIG_VERSION,
        )
        repricing_dict = _metric_result_to_dict(repricing_result)

    return PriceScenarioOutcome(
        price_positioning=[_metric_result_to_dict(r) for r in positioning_results],
        repricing_scenario=repricing_dict,
    )


def run_discovery(tenant_id: UUID, *, requested_by: UUID, seller_product: SellerProduct) -> DiscoveryRunOutcome:
    """§6.10-§6.15's direct-execution composition, shared by the `POST /discovery-runs` route and
    the CEO action. The provider is chosen in one place, `services.ci_search.select_search_provider`
    (Tavily, owner-approved 2026-10-18, C34; the mock only when `CI_SEARCH_PROVIDER=mock`).
    Tavily sends the seller's product search terms to a third party, so `ceo/effects.py` classifies
    this action as seller data out — that row and this composition must change together."""
    discovery_enabled = ci_tenant_config_repo.get_discovery_enabled(tenant_id)
    budget = ci_tenant_config_repo.get_discovery_budget(tenant_id)
    selected = select_search_provider(tenant_id)
    return start_discovery_run(
        tenant_id,
        requested_by=requested_by,
        seller_product=seller_product,
        provider=selected.provider,
        provider_name=selected.provider_name,
        cache=PostgresSearchResultCache(),
        budget=budget,
        discovery_enabled=discovery_enabled,
    )
