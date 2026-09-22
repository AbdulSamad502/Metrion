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
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Sequence
from uuid import UUID, uuid4

from calc_engine.formulas.component_sum import BearerResolver
from calc_engine.formulas.contribution_profit import contribution_profit
from calc_engine.formulas.net_realized_revenue import net_realized_revenue
from calc_engine.formulas.price_band import (
    ENGINE_MIN_COMPETITORS_FOR_PRICE_BAND,
    compute_price_band as _compute_price_band,
)
from calc_engine.formulas.price_positioning import (
    CompetitorPrice,
    RepricingStance,
    compute_position_gaps,
    compute_repricing_scenario as _compute_repricing_scenario,
)
from calc_engine.types import (
    CanonicalLine,
    Confidence,
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


def _format_pct(gap_pct: Fraction) -> str:
    """Single presentation-time rounding of an otherwise-unrounded Fraction (§5.15 rule 5).
    `metric_result` has no dedicated percentage column (it's a money-grained table), so this
    is recorded in `calculation_basis` for audit/traceability rather than as a queryable
    typed field — a real, acknowledged limitation, not an oversight. A future metric needing
    a queryable percentage should add a proper column via its own migration rather than
    reusing this text-encoding trick."""
    decimal_value = Decimal(gap_pct.numerator) / Decimal(gap_pct.denominator)
    return str(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_price_positioning(
    *,
    seller_price_paise: Paise | Unavailable,
    seller_price_confidence: Confidence,
    competitor_prices: Sequence[CompetitorPrice],
    computed_at: datetime,
    as_of_date: date | None = None,
) -> list[MetricResult]:
    """deterministic-engine.md §5.15. Returns one MetricResult per PositionGap reference
    (AVERAGE, MIN, MAX) — rule 1 explicitly calls for "one or more metric_result rows", not a
    single aggregate row. Reproducible for a fixed input tuple; NOT part of
    canonical_data_version (rule 7) since competitor prices are not canonical seller data —
    a fresh CI snapshot produces a new result, never a correction of the old one.
    """
    gaps = compute_position_gaps(seller_price_paise, seller_price_confidence, competitor_prices)

    if isinstance(gaps, Unavailable):
        return [
            MetricResult(
                id=uuid4(),
                metric_code="PRICE_POSITIONING",
                value_paise=None,
                recognition_state=RecognitionState.UNAVAILABLE,
                confidence="DERIVED",
                calculation_basis="PricePositioning (§5.15) — UNAVAILABLE, see unavailable_reason",
                formula_version="PRICE_POSITIONING.v1",
                canonical_data_version="non-canonical",
                as_of_date=as_of_date,
                input_refs=(),
                exclusions=(),
                computed_at=computed_at,
                is_available=False,
                unavailable_reason=gaps.reason,
            )
        ]

    results: list[MetricResult] = []
    for gap in gaps:
        results.append(
            MetricResult(
                id=uuid4(),
                metric_code="PRICE_POSITIONING",
                value_paise=gap.gap_paise.value,
                recognition_state=RecognitionState.RECOGNISED,
                confidence=gap.confidence.value,
                calculation_basis=(
                    f"PricePositioning vs {gap.reference.value} "
                    f"(reference_price_paise={gap.reference_price_paise.value}, "
                    f"gap_pct={_format_pct(gap.gap_pct)}%) — deterministic-engine.md §5.15"
                ),
                formula_version="PRICE_POSITIONING.v1",
                canonical_data_version="non-canonical",
                as_of_date=as_of_date,
                input_refs=tuple(cp.source_ref for cp in competitor_prices),
                exclusions=(),
                computed_at=computed_at,
                is_available=True,
            )
        )
    return results


def compute_repricing_scenario(
    *,
    seller_price_paise: Paise | Unavailable,
    seller_price_confidence: Confidence,
    competitor_prices: Sequence[CompetitorPrice],
    stance: RepricingStance,
    stance_param: Fraction | Paise | None,
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """deterministic-engine.md §5.15. Explicitly not margin-aware (rule 2) — no COGS, no fee
    reference, no profitability implication. A suggested price here may be unprofitable;
    that's margin_curve's (§5.13.1) determination to make, never this function's.
    """
    result = _compute_repricing_scenario(
        seller_price_paise, seller_price_confidence, competitor_prices, stance, stance_param
    )

    if isinstance(result, Unavailable):
        return MetricResult(
            id=uuid4(),
            metric_code="REPRICING_SCENARIO",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis="RepricingScenario (§5.15) — UNAVAILABLE, see unavailable_reason",
            formula_version="REPRICING_SCENARIO.v1",
            canonical_data_version="non-canonical",
            as_of_date=as_of_date,
            input_refs=(),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            unavailable_reason=result.reason,
        )

    return MetricResult(
        id=uuid4(),
        metric_code="REPRICING_SCENARIO",
        value_paise=result.suggested_price_paise.value,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=result.confidence.value,
        calculation_basis=(
            f"RepricingScenario stance={stance.value} "
            f"(gap_paise={result.gap_paise.value}, gap_pct={_format_pct(result.gap_pct)}%) "
            "— not margin-aware, no COGS/fees — deterministic-engine.md §5.15"
        ),
        formula_version="REPRICING_SCENARIO.v1",
        canonical_data_version="non-canonical",
        as_of_date=as_of_date,
        input_refs=tuple(cp.source_ref for cp in competitor_prices),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )


def compute_price_band(
    *,
    product_ref: str,
    category: str | None,
    competitor_prices: Sequence[CompetitorPrice],
    computed_at: datetime,
    min_competitors: int = ENGINE_MIN_COMPETITORS_FOR_PRICE_BAND,
    as_of_date: date | None = None,
) -> list[MetricResult]:
    """deterministic-engine.md §5.15.1. Returns one MetricResult per rule-7 output row
    (Q1/Q3/IQR/fences/typical range, plus one per supplied price carrying its outlier flag)
    — never a single aggregate row. `product_ref`/`category` are scoping context recorded in
    `calculation_basis`; they never touch the arithmetic (see price_band.py's own docstring).
    Reproducible for a fixed input tuple; NOT part of canonical_data_version (rule 11) —
    identical reasoning to compute_price_positioning/compute_repricing_scenario.
    """
    scope = f"product_ref={product_ref}, category={category or 'UNKNOWN'}"
    band = _compute_price_band(competitor_prices, min_competitors=min_competitors)

    if isinstance(band, Unavailable):
        return [
            MetricResult(
                id=uuid4(),
                metric_code="PRICE_BAND",
                value_paise=None,
                recognition_state=RecognitionState.UNAVAILABLE,
                confidence="DERIVED",
                calculation_basis=f"PriceBand ({scope}) — UNAVAILABLE, see unavailable_reason — deterministic-engine.md §5.15.1",
                formula_version="PRICE_BAND.v1",
                canonical_data_version="non-canonical",
                as_of_date=as_of_date,
                input_refs=(),
                exclusions=(),
                computed_at=computed_at,
                is_available=False,
                unavailable_reason=band.reason,
            )
        ]

    input_refs = tuple(cp.source_ref for cp in competitor_prices)
    results: list[MetricResult] = []

    def _row(label: str, value: "Paise") -> None:
        results.append(
            MetricResult(
                id=uuid4(),
                metric_code="PRICE_BAND",
                value_paise=value.value,
                recognition_state=RecognitionState.RECOGNISED,
                confidence=band.confidence.value,
                calculation_basis=f"PriceBand {label} ({scope}) — deterministic-engine.md §5.15.1",
                formula_version="PRICE_BAND.v1",
                canonical_data_version="non-canonical",
                as_of_date=as_of_date,
                input_refs=input_refs,
                exclusions=(),
                computed_at=computed_at,
                is_available=True,
            )
        )

    _row("Q1", band.q1_paise)
    _row("Q3", band.q3_paise)
    _row("IQR", band.iqr_paise)
    _row("LOWER_FENCE", band.lower_fence_paise)
    _row("UPPER_FENCE", band.upper_fence_paise)
    # Rule 7: TYPICAL_LOW/HIGH are absent, not fabricated, in the extreme edge case where
    # every supplied price was an outlier (see price_band.py's PriceBand docstring).
    if band.typical_low_paise is not None:
        _row("TYPICAL_LOW", band.typical_low_paise)
    if band.typical_high_paise is not None:
        _row("TYPICAL_HIGH", band.typical_high_paise)

    for point in band.points:
        results.append(
            MetricResult(
                id=uuid4(),
                metric_code="PRICE_BAND",
                value_paise=point.price.value_paise.value,
                recognition_state=RecognitionState.RECOGNISED,
                confidence=point.price.confidence.value,
                calculation_basis=(
                    f"PriceBand PRICE_POINT ({scope}, source_ref={point.price.source_ref}, "
                    f"is_outlier={point.is_outlier}) — deterministic-engine.md §5.15.1"
                ),
                formula_version="PRICE_BAND.v1",
                canonical_data_version="non-canonical",
                as_of_date=as_of_date,
                input_refs=(point.price.source_ref,),
                exclusions=(),
                computed_at=computed_at,
                is_available=True,
            )
        )

    return results
