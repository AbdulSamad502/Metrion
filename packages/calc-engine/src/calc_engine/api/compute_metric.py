"""compute_metric() — the one place formula evaluation and metric_result-shaped output meet.

This is the pure/in-memory form: it wraps formula results into a metric_result-shaped object
and mints an engine_result_ref (§9), but it does not persist anything or touch Postgres — that
is repositories/metric_result_repo.py's job, which is a later, separate DB-integration pass
(see packages/calc-engine/migrations/README.md). No clock is read internally: `computed_at`
and `as_of_date` are supplied by the caller, per §4's determinism contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence
from uuid import UUID, uuid4

from calc_engine.formulas.component_sum import BearerResolver
from calc_engine.formulas.contribution_profit import contribution_profit
from calc_engine.formulas.net_realized_revenue import net_realized_revenue
from calc_engine.types import (
    CanonicalLine,
    Paise,
    RecognitionState,
    Unavailable,
)
from calc_engine.versioning import derive_canonical_data_version


@dataclass(frozen=True, slots=True)
class MetricResult:
    """Mirrors deterministic-engine.md §9 `metric_result`. `id` is the engine_result_ref."""

    id: UUID
    metric_code: str
    value_paise: int | None  # None only when the whole result is UNAVAILABLE
    recognition_state: RecognitionState
    confidence: str
    calculation_basis: str
    formula_version: str
    canonical_data_version: str
    as_of_date: date | None
    input_refs: tuple[Any, ...]
    exclusions: tuple[dict[str, Any], ...]
    computed_at: datetime
    is_available: bool
    # The ACTIVE manual_adjustment ids in scope for this result (§9's metric_result.
    # manual_adjustment_set) — always the same set that fed canonical_data_version's hash
    # (§4.3), stamped here too so a stored row can show *which* adjustments it used, not
    # just that some were folded into its version fingerprint.
    manual_adjustment_set: tuple[str, ...] = ()
    unavailable_reason: str | None = None


def compute_net_realized_revenue(
    lines: Sequence[CanonicalLine],
    *,
    bearer_resolver: BearerResolver,
    recognition_state: RecognitionState,
    ingestion_run_ids: Sequence[UUID | str],
    adapter_versions: Sequence[str],
    active_adjustment_ids: Sequence[UUID | str],
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    result = net_realized_revenue(lines, bearer_resolver, recognition_state)
    canonical_data_version = derive_canonical_data_version(
        ingestion_run_ids, adapter_versions, active_adjustment_ids
    )
    manual_adjustment_set = tuple(str(a) for a in active_adjustment_ids)

    if isinstance(result, Unavailable):
        return MetricResult(
            id=uuid4(),
            metric_code="NET_REALIZED_REVENUE",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis="NetRealizedRevenue (§5.5) — UNAVAILABLE, see unavailable_reason",
            formula_version="NET_REALIZED_REVENUE.v1",
            canonical_data_version=canonical_data_version,
            as_of_date=as_of_date,
            input_refs=(),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason=result.reason,
        )

    return MetricResult(
        id=uuid4(),
        metric_code="NET_REALIZED_REVENUE",
        value_paise=result.value.value,
        recognition_state=result.recognition_state,
        confidence=result.confidence.value,
        calculation_basis=result.calculation_basis,
        formula_version="NET_REALIZED_REVENUE.v1",
        canonical_data_version=canonical_data_version,
        as_of_date=as_of_date,
        input_refs=result.input_refs,
        exclusions=result.exclusions,
        computed_at=computed_at,
        is_available=True,
        manual_adjustment_set=manual_adjustment_set,
    )


def compute_contribution_profit(
    nrr_result: MetricResult,
    *,
    cogs: Paise | Unavailable,
    marketplace_fees: Paise,
    shipping_logistics: Paise,
    advertising_costs: Paise,
    return_rto_losses: Paise | Unavailable,
    other_allocated_costs: Paise,
    ingestion_run_ids: Sequence[UUID | str],
    adapter_versions: Sequence[str],
    active_adjustment_ids: Sequence[UUID | str],
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """Consumes an already-computed NetRealizedRevenue MetricResult — Contribution Profit
    is never recomputed from raw lines independently of the NRR figure it's built on (this
    is what keeps the two figures reconcilable to each other on a seller-facing screen)."""
    canonical_data_version = derive_canonical_data_version(
        ingestion_run_ids, adapter_versions, active_adjustment_ids
    )
    manual_adjustment_set = tuple(str(a) for a in active_adjustment_ids)

    if not nrr_result.is_available:
        return MetricResult(
            id=uuid4(),
            metric_code="CONTRIBUTION_PROFIT",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis="ContributionProfit (§5.8) — UNAVAILABLE because NetRealizedRevenue is UNAVAILABLE",
            formula_version="CONTRIBUTION_PROFIT.v1",
            canonical_data_version=canonical_data_version,
            as_of_date=as_of_date,
            input_refs=(nrr_result.id,),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason=f"NetRealizedRevenue unavailable: {nrr_result.unavailable_reason}",
        )

    nrr_paise = Paise(nrr_result.value_paise)  # type: ignore[arg-type]
    result = contribution_profit(
        net_realized_revenue=nrr_paise,
        cogs=cogs,
        marketplace_fees=marketplace_fees,
        shipping_logistics=shipping_logistics,
        advertising_costs=advertising_costs,
        return_rto_losses=return_rto_losses,
        other_allocated_costs=other_allocated_costs,
    )

    if isinstance(result, Unavailable):
        return MetricResult(
            id=uuid4(),
            metric_code="CONTRIBUTION_PROFIT",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis="ContributionProfit (§5.8) — UNAVAILABLE, see unavailable_reason",
            formula_version="CONTRIBUTION_PROFIT.v1",
            canonical_data_version=canonical_data_version,
            as_of_date=as_of_date,
            input_refs=(nrr_result.id,),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason=result.reason,
        )

    return MetricResult(
        id=uuid4(),
        metric_code="CONTRIBUTION_PROFIT",
        value_paise=result.value,
        recognition_state=nrr_result.recognition_state,
        confidence=nrr_result.confidence,  # a total can never present as more certain than its weakest input
        calculation_basis=(
            "ContributionProfit = NetRealizedRevenue - COGS - MarketplaceFees - ShippingLogistics "
            "- AdvertisingCosts - ReturnRTOLosses - OtherAllocatedCosts (deterministic-engine.md §5.8)"
        ),
        formula_version="CONTRIBUTION_PROFIT.v1",
        canonical_data_version=canonical_data_version,
        as_of_date=as_of_date,
        input_refs=(nrr_result.id,),
        exclusions=nrr_result.exclusions,
        computed_at=computed_at,
        is_available=True,
        manual_adjustment_set=manual_adjustment_set,
    )
