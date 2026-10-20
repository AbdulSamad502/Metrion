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
from calc_engine.formulas.fee_resolution import FeeReference
from calc_engine.formulas.batch_size import BudgetConstrainedQuantity, budget_constrained_quantity
from calc_engine.formulas.landed_cost import LandedCostQuote, landed_cost_per_unit
from calc_engine.formulas.margin_curve import margin_at_price
from calc_engine.formulas.metric_delta import metric_delta
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
from calc_engine.formulas.return_rate import CALCULATION_BASIS as _RETURN_RATE_CALCULATION_BASIS
from calc_engine.formulas.return_rate import return_rate_pct as _return_rate_pct
from calc_engine.formulas.settlement_lag import SettlementLagAggregate
from calc_engine.gst.normalization import Basis
from calc_engine.gst.summary import DEFAULT_TAX_HEADS, gst_period_summary
from calc_engine.types import (
    CanonicalLine,
    Confidence,
    Paise,
    RecognitionState,
    Unavailable,
    combine_confidence,
)
from calc_engine.versioning import derive_canonical_data_version


@dataclass(frozen=True, slots=True)
class MetricResult:
    """Mirrors deterministic-engine.md §9 `metric_result`. `id` is the engine_result_ref."""

    id: UUID
    metric_code: str
    value_paise: int | None  # None for a Fraction-valued result (see value_fraction below), or when UNAVAILABLE
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
    # E3 (docs/specs/anomaly-detection.md §6.1 MARGIN_PCT) — the engine's first Fraction-valued
    # (percentage) result. Populated INSTEAD OF value_paise, never alongside it (exactly one of
    # the two is non-None for an available result) — see
    # `20260925_0006_metric_result_value_fraction.py`'s own docstring for why `value_paise`
    # structurally cannot hold this without misrepresenting its "paise" unit.
    value_fraction: Fraction | None = None


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


def compute_contribution_margin_pct(
    cp_result: MetricResult,
    nrr_result: MetricResult,
    *,
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """`ContributionMargin% = ContributionProfit / NetRealizedRevenue * 100`
    (deterministic-engine.md line 352) — docs/specs/anomaly-detection.md §6.1's `MARGIN_PCT`
    series is built by calling this function once per period, exactly the same composition
    pattern `deterministic-engine.md §6.6` already names for `SETTLEMENT_LAG_DAYS` ("analogous
    to how MARGIN_PCT's series is built by calling compute_contribution_profit once per
    period"). `metric_code = "CONTRIBUTION_MARGIN_PCT"` — this file's own naming convention
    (`CONTRIBUTION_PROFIT`, `NET_REALIZED_REVENUE`), NOT the anomaly spec's `MARGIN_PCT` label,
    which is the anomaly-config-side name (`anomaly_detection_config.metric`), mapped onto this
    metric_code by the caller, never persisted as this metric_code itself.

    Consumes two ALREADY-COMPUTED `MetricResult`s — never recomputes `ContributionProfit` or
    `NetRealizedRevenue` independently, exactly mirroring `compute_contribution_profit`'s own
    "Contribution Profit is never recomputed from raw lines independently of the NRR figure
    it's built on" discipline, one level up.

    `value` is a `Fraction` PERCENTAGE, not paise — `MetricResult.value_fraction`, not
    `value_paise` (see that field's own docstring and
    `20260925_0006_metric_result_value_fraction.py` for the schema-gap reasoning this
    resolves). `value_paise` is left `None` for every available result this function returns.

    `confidence` is `combine_confidence(cp_result.confidence, nrr_result.confidence)` — "a
    total can never present as more certain than its weakest input" (the same comment pattern
    `compute_contribution_profit` already carries, generalised to two independent inputs rather
    than one input plus a formula's own internal figures)."""
    canonical_data_version = (
        cp_result.canonical_data_version
        if cp_result.canonical_data_version == nrr_result.canonical_data_version
        else f"{cp_result.canonical_data_version}+{nrr_result.canonical_data_version}"
    )
    manual_adjustment_set = tuple(
        dict.fromkeys(cp_result.manual_adjustment_set + nrr_result.manual_adjustment_set)
    )

    if not cp_result.is_available or not nrr_result.is_available:
        missing = []
        if not cp_result.is_available:
            missing.append(f"ContributionProfit unavailable: {cp_result.unavailable_reason}")
        if not nrr_result.is_available:
            missing.append(f"NetRealizedRevenue unavailable: {nrr_result.unavailable_reason}")
        return MetricResult(
            id=uuid4(),
            metric_code="CONTRIBUTION_MARGIN_PCT",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis=(
                "ContributionMargin% = ContributionProfit / NetRealizedRevenue x 100 "
                "(deterministic-engine.md line 352) — UNAVAILABLE, see unavailable_reason"
            ),
            formula_version="CONTRIBUTION_MARGIN_PCT.v1",
            canonical_data_version=canonical_data_version,
            as_of_date=as_of_date,
            input_refs=(cp_result.id, nrr_result.id),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason="; ".join(missing),
        )

    if nrr_result.value_paise == 0:
        return MetricResult(
            id=uuid4(),
            metric_code="CONTRIBUTION_MARGIN_PCT",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis=(
                "ContributionMargin% = ContributionProfit / NetRealizedRevenue x 100 "
                "(deterministic-engine.md line 352) — UNAVAILABLE, division by zero is not a "
                "valid margin"
            ),
            formula_version="CONTRIBUTION_MARGIN_PCT.v1",
            canonical_data_version=canonical_data_version,
            as_of_date=as_of_date,
            input_refs=(cp_result.id, nrr_result.id),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason=(
                "NetRealizedRevenue is zero for this period — ContributionMargin% is "
                "mathematically undefined, never silently reported as 0% or infinite"
            ),
        )

    margin_pct = Fraction(cp_result.value_paise, nrr_result.value_paise) * 100  # type: ignore[arg-type]
    confidence = combine_confidence(Confidence(cp_result.confidence), Confidence(nrr_result.confidence))

    return MetricResult(
        id=uuid4(),
        metric_code="CONTRIBUTION_MARGIN_PCT",
        value_paise=None,
        value_fraction=margin_pct,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=confidence.value,
        calculation_basis=(
            "ContributionMargin% = ContributionProfit / NetRealizedRevenue x 100 "
            "(deterministic-engine.md line 352)"
        ),
        formula_version="CONTRIBUTION_MARGIN_PCT.v1",
        canonical_data_version=canonical_data_version,
        as_of_date=as_of_date,
        input_refs=(cp_result.id, nrr_result.id),
        exclusions=cp_result.exclusions,
        computed_at=computed_at,
        is_available=True,
        manual_adjustment_set=manual_adjustment_set,
    )


def compute_marketplace_fees(
    marketplace_fees: Paise,
    *,
    computed_at: datetime,
    as_of_date: date | None = None,
    input_refs: Sequence[UUID] = (),
    confidence: str = "DERIVED",
) -> MetricResult:
    """anomaly-detection.md §6.1 P2's real gap: `MarketplaceFees` is currently only ever a
    plain, untracked `Paise` parameter `compute_contribution_profit` consumes (line ~139
    above) — no `MetricResult` is ever minted for it independently, so there is nothing with a
    real `engine_result_ref` for `compute_fee_ratio_pct` (below) to compose a ratio from.

    This is a THIN MINTING WRAPPER ONLY, deliberately minimal (no existing function in this
    file just wraps an already-resolved `Paise` with zero further logic, so there is no exact
    precedent to mirror — checked against every `compute_*` function above). The real
    resolution/summation over canonical line fee components already happened in
    `cfo.pnl.inputs.resolve_marketplace_fees` (real, unchanged, itself a pass-through to
    `formulas.marketplace_fees.marketplace_fees`) — this function performs no arithmetic of
    its own; it only gives that already-computed figure a real, citable `engine_result_ref`.

    `canonical_data_version="non-canonical"`: this wrapper's signature deliberately does not
    accept `ingestion_run_ids`/`adapter_versions`/`active_adjustment_ids` (kept minimal, per
    above) — mirroring `compute_price_positioning`/`compute_landed_cost`'s own "non-canonical"
    precedent for a result minted without independently re-deriving a version fingerprint. The
    real canonical_data_version for this period is already derived once, on
    `NET_REALIZED_REVENUE`/`CONTRIBUTION_PROFIT`, by the same caller (`compute_period_pnl`)
    that calls this function — this figure does not need a second, independent one.
    """
    return MetricResult(
        id=uuid4(),
        metric_code="MARKETPLACE_FEES",
        value_paise=marketplace_fees.value,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=confidence,
        calculation_basis=(
            "MarketplaceFees — already-resolved sum over canonical line fee components "
            "(cfo.pnl.inputs.resolve_marketplace_fees, deterministic-engine.md §5.6) — this "
            "wrapper mints an engine_result_ref only, it performs no summation itself"
        ),
        formula_version="MARKETPLACE_FEES.v1",
        canonical_data_version="non-canonical",
        as_of_date=as_of_date,
        input_refs=tuple(input_refs),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )


def compute_fee_ratio_pct(
    fees_result: MetricResult,
    nrr_result: MetricResult,
    *,
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """`FeeRatio% = MarketplaceFees / NetRealizedRevenue x 100` (anomaly-detection.md §6.1
    `FEE_RATIO_PCT`, P2's resolution) — structurally identical to
    `compute_contribution_margin_pct` immediately above: consumes two ALREADY-COMPUTED
    `MetricResult`s, never recomputes `MarketplaceFees` or `NetRealizedRevenue`
    independently. `metric_code = "FEE_RATIO_PCT"` — the anomaly-config-side name itself
    (unlike `CONTRIBUTION_MARGIN_PCT`'s own file-convention naming), since no other name for
    this ratio is defined anywhere in this codebase.

    `value_fraction` is a `Fraction` PERCENTAGE, never `value_paise` — same convention as
    `compute_contribution_margin_pct`. `confidence = combine_confidence(fees_result.confidence,
    nrr_result.confidence)` — "a total can never present as more certain than its weakest
    input", the same comment pattern this file already carries twice.
    """
    canonical_data_version = (
        fees_result.canonical_data_version
        if fees_result.canonical_data_version == nrr_result.canonical_data_version
        else f"{fees_result.canonical_data_version}+{nrr_result.canonical_data_version}"
    )
    manual_adjustment_set = tuple(
        dict.fromkeys(fees_result.manual_adjustment_set + nrr_result.manual_adjustment_set)
    )

    if not fees_result.is_available or not nrr_result.is_available:
        missing = []
        if not fees_result.is_available:
            missing.append(f"MarketplaceFees unavailable: {fees_result.unavailable_reason}")
        if not nrr_result.is_available:
            missing.append(f"NetRealizedRevenue unavailable: {nrr_result.unavailable_reason}")
        return MetricResult(
            id=uuid4(),
            metric_code="FEE_RATIO_PCT",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis=(
                "FeeRatio% = MarketplaceFees / NetRealizedRevenue x 100 "
                "(anomaly-detection.md §6.1) — UNAVAILABLE, see unavailable_reason"
            ),
            formula_version="FEE_RATIO_PCT.v1",
            canonical_data_version=canonical_data_version,
            as_of_date=as_of_date,
            input_refs=(fees_result.id, nrr_result.id),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason="; ".join(missing),
        )

    if nrr_result.value_paise == 0:
        return MetricResult(
            id=uuid4(),
            metric_code="FEE_RATIO_PCT",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis=(
                "FeeRatio% = MarketplaceFees / NetRealizedRevenue x 100 "
                "(anomaly-detection.md §6.1) — UNAVAILABLE, division by zero is not a valid "
                "fee ratio"
            ),
            formula_version="FEE_RATIO_PCT.v1",
            canonical_data_version=canonical_data_version,
            as_of_date=as_of_date,
            input_refs=(fees_result.id, nrr_result.id),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason=(
                "NetRealizedRevenue is zero for this period — FeeRatio% is mathematically "
                "undefined, never silently reported as 0% or infinite"
            ),
        )

    fee_ratio_pct = Fraction(fees_result.value_paise, nrr_result.value_paise) * 100  # type: ignore[arg-type]
    confidence = combine_confidence(Confidence(fees_result.confidence), Confidence(nrr_result.confidence))

    return MetricResult(
        id=uuid4(),
        metric_code="FEE_RATIO_PCT",
        value_paise=None,
        value_fraction=fee_ratio_pct,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=confidence.value,
        calculation_basis=(
            "FeeRatio% = MarketplaceFees / NetRealizedRevenue x 100 (anomaly-detection.md §6.1)"
        ),
        formula_version="FEE_RATIO_PCT.v1",
        canonical_data_version=canonical_data_version,
        as_of_date=as_of_date,
        input_refs=(fees_result.id, nrr_result.id),
        exclusions=fees_result.exclusions,
        computed_at=computed_at,
        is_available=True,
        manual_adjustment_set=manual_adjustment_set,
    )


def compute_return_rate_pct(
    lines: Sequence[CanonicalLine],
    *,
    ingestion_run_ids: Sequence[UUID | str],
    adapter_versions: Sequence[str],
    active_adjustment_ids: Sequence[UUID | str],
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """`RETURN_RATE_PCT` (anomaly-detection.md §6.1) —
    `(returned_qty + rto_qty) / quantity x 100`, aggregated over `lines` for one period.
    Delegates the one arithmetic step to `formulas.return_rate.return_rate_pct` (real,
    unchanged); this wrapper only shapes the result, exactly like every other `compute_*`
    function in this module.

    This is a FRESH computation over canonical lines (not a composition of two prior
    `MetricResult`s, unlike `compute_fee_ratio_pct`/`compute_contribution_margin_pct`) — so
    `canonical_data_version` is derived the normal way via `derive_canonical_data_version`,
    exactly as `compute_net_realized_revenue`/`compute_gst_period_summary` already do for the
    same reason (their own docstrings state this explicitly).

    `confidence` mirrors `compute_net_realized_revenue`'s own "derive from the input lines' own
    confidence signals" pattern: `combine_confidence(*(line.confidence for line in lines))` —
    the weakest line confidence wins. NRR additionally floors its own result at
    `Confidence.PROVISIONAL` to reflect a DIFFERENT concern specific to itself (discount-bearer
    resolution uncertainty, `discount_attribution`'s UNKNOWN-bearer fallback) — this ratio has
    no bearer-resolution step of its own, so that extra, unrelated floor is deliberately not
    carried over; only the base "combine every line's own confidence" step is mirrored, per this
    checkpoint's "don't invent a new confidence-derivation rule" instruction.
    """
    canonical_data_version = derive_canonical_data_version(
        ingestion_run_ids, adapter_versions, active_adjustment_ids
    )
    manual_adjustment_set = tuple(str(a) for a in active_adjustment_ids)
    input_refs = tuple(line.sales_line_id for line in lines)

    result = _return_rate_pct(lines)

    if isinstance(result, Unavailable):
        return MetricResult(
            id=uuid4(),
            metric_code="RETURN_RATE_PCT",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis=f"{_RETURN_RATE_CALCULATION_BASIS} — UNAVAILABLE, see unavailable_reason",
            formula_version="RETURN_RATE_PCT.v1",
            canonical_data_version=canonical_data_version,
            as_of_date=as_of_date,
            input_refs=input_refs,
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason=result.reason,
        )

    confidence = combine_confidence(*(line.confidence for line in lines))

    return MetricResult(
        id=uuid4(),
        metric_code="RETURN_RATE_PCT",
        value_paise=None,
        value_fraction=result,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=confidence.value,
        calculation_basis=_RETURN_RATE_CALCULATION_BASIS,
        formula_version="RETURN_RATE_PCT.v1",
        canonical_data_version=canonical_data_version,
        as_of_date=as_of_date,
        input_refs=input_refs,
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
        manual_adjustment_set=manual_adjustment_set,
    )


def compute_settlement_lag_days(
    aggregate: SettlementLagAggregate | Unavailable,
    *,
    reconciliation_run_id: UUID,
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """`SETTLEMENT_LAG_DAYS` (anomaly-detection.md §6.1/§6.6, closing that spec's own §10 P1
    blocker: "no period-level aggregate function anywhere in packages/calc-engine"). The mean
    (not median — a disclosed choice, see `calc_engine.formulas.settlement_lag`'s own docstring
    for the full reasoning: consistency with `Z_SCORE`/`PERIOD_OVER_PERIOD_DELTA`'s own
    mean-based baseline statistics, `calc_engine/anomaly/_stats.py`) days-to-settle across every
    matched (sales_line, settlement_line) pair from one `reconcile()` run.

    Consumes an ALREADY-COMPUTED `SettlementLagAggregate` (or `Unavailable`) — this function
    performs no join, no date resolution and no averaging of its own;
    `calc_engine.formulas.settlement_lag.settlement_lag_days_aggregate` is the one place that
    arithmetic happens, exactly mirroring `compute_return_rate_pct`'s "delegates the one
    arithmetic step" pattern one level up.

    `value_fraction`, never `value_paise` — a day count is not money, the same convention
    `compute_contribution_margin_pct`/`compute_fee_ratio_pct`/`compute_return_rate_pct` already
    established for every non-money series this file mints.

    `UNAVAILABLE` when zero matched pairs produced a usable lag for this run (`aggregate` is
    `Unavailable`) — never a fabricated 0-day lag (CLAUDE.md's "missing input is UNAVAILABLE,
    never zero").

    `confidence = combine_confidence(*aggregate.confidences)` — every contributing pair's own
    `reconciliation_match.confidence` folded in. This is the one place the per-marketplace
    join-key confidence cap (deterministic-engine.md §5.12.2 — Amazon/Flipkart capped at
    PROVISIONAL, Meesho VERIFIED-eligible) flows through into this metric, since
    `reconciliation_match.confidence` already carries that cap from `reconcile()`'s own
    construction — `aggregate.confidences` is guaranteed non-empty whenever `aggregate` is not
    `Unavailable` (the formula only returns a real `SettlementLagAggregate` once at least one
    pair has contributed a value), so `combine_confidence`'s "requires at least one level"
    precondition always holds here.

    `canonical_data_version="non-canonical"` — mirrors `calc_engine.api.reconcile`'s own
    `_NON_CANONICAL` choice for `LEAK_TOTAL`/`LEAK_EXCEPTION_AMOUNT`: `reconcile()`'s signature
    carries no `ingestion_run_ids`/`adapter_versions`/`active_adjustment_ids` to derive a real
    fingerprint from, and this metric is one further composition step downstream of the same
    run, for the identical reason."""
    input_refs: tuple[Any, ...] = (reconciliation_run_id,)

    if isinstance(aggregate, Unavailable):
        return MetricResult(
            id=uuid4(),
            metric_code="SETTLEMENT_LAG_DAYS",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis=(
                "SettlementLagDays = mean(settlement_date - resolved_sales_date) across matched "
                "(sales_line, settlement_line) pairs (anomaly-detection.md §6.1/§6.6) — "
                "UNAVAILABLE, see unavailable_reason"
            ),
            formula_version="SETTLEMENT_LAG_DAYS.v1",
            canonical_data_version="non-canonical",
            as_of_date=as_of_date,
            input_refs=input_refs,
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            unavailable_reason=aggregate.reason,
        )

    confidence = combine_confidence(*aggregate.confidences)

    return MetricResult(
        id=uuid4(),
        metric_code="SETTLEMENT_LAG_DAYS",
        value_paise=None,
        value_fraction=aggregate.mean_lag_days,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=confidence.value,
        calculation_basis=(
            "SettlementLagDays = mean(settlement_date - resolved_sales_date) across "
            f"{aggregate.pair_count} matched pair(s) (anomaly-detection.md §6.1/§6.6) — MEAN, "
            "not median, a disclosed choice for consistency with Z_SCORE/PERIOD_OVER_PERIOD_"
            f"DELTA's own mean-based baseline statistics; {aggregate.negative_lag_excluded_count} "
            f"pair(s) excluded for a negative lag, {aggregate.dates_missing_count} pair(s) "
            "excluded for a missing date"
        ),
        formula_version="SETTLEMENT_LAG_DAYS.v1",
        canonical_data_version="non-canonical",
        as_of_date=as_of_date,
        input_refs=input_refs,
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )


def compute_metric_delta(
    result_a: MetricResult,
    result_b: MetricResult,
    *,
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """Period-over-period delta for two already-computed MetricResults of the SAME
    metric_code — `result_a` the earlier period, `result_b` the later one. deterministic-engine.md
    §9. Delegates the one arithmetic step to formulas.metric_delta.metric_delta(); this wrapper
    only shapes the result, exactly like every other compute_* function in this module.

    A `metric_code` mismatch is a caller bug (comparing two different metrics), not missing
    data — metric_delta() raises ValueError for it, and this function does not catch it,
    matching how compute_landed_cost lets a caller-bug exception propagate rather than
    converting it into a soft UNAVAILABLE result.
    """
    delta = metric_delta(result_a, result_b)
    manual_adjustment_set = tuple(
        dict.fromkeys(result_a.manual_adjustment_set + result_b.manual_adjustment_set)
    )

    if isinstance(delta, Unavailable):
        return MetricResult(
            id=uuid4(),
            metric_code=f"{result_a.metric_code}_DELTA",
            value_paise=None,
            recognition_state=RecognitionState.UNAVAILABLE,
            confidence="DERIVED",
            calculation_basis=f"{result_a.metric_code} delta — UNAVAILABLE, see unavailable_reason",
            formula_version=f"{result_a.metric_code}_DELTA.v1",
            canonical_data_version=result_b.canonical_data_version,
            as_of_date=as_of_date,
            input_refs=(result_a.id, result_b.id),
            exclusions=(),
            computed_at=computed_at,
            is_available=False,
            manual_adjustment_set=manual_adjustment_set,
            unavailable_reason=delta.reason,
        )

    return MetricResult(
        id=uuid4(),
        metric_code=f"{result_a.metric_code}_DELTA",
        value_paise=delta,
        recognition_state=result_b.recognition_state,
        confidence=combine_confidence(Confidence(result_a.confidence), Confidence(result_b.confidence)).value,
        calculation_basis=f"{result_a.metric_code} delta = value_paise(result_b) - value_paise(result_a)",
        formula_version=f"{result_a.metric_code}_DELTA.v1",
        canonical_data_version=result_b.canonical_data_version,
        as_of_date=as_of_date,
        input_refs=(result_a.id, result_b.id),
        exclusions=result_a.exclusions + result_b.exclusions,
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
                    f"gap_pct={_format_pct(gap.gap_pct)}%, "
                    f"gap_pct_of_seller_price={_format_pct(gap.gap_pct_of_seller) if gap.gap_pct_of_seller is not None else 'UNAVAILABLE'}%) — deterministic-engine.md §5.15"
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


def compute_landed_cost(
    quote: LandedCostQuote,
    quantity: int,
    *,
    sku: str,
    active_adjustment_ids: Sequence[UUID | str],
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """deterministic-engine.md §5.13.1: `landed_cost(manual_adjustment_ref, sku, quantity)` ->
    `metric_result`, `metric_code = LANDED_COST_PER_UNIT`. Consumed by supplier ranking and
    batch size, never by any margin/profit figure (`quote` is a seller-declared `supplier.quote`
    manual_adjustment, §7.2.1 — not canonical sales data).

    This wrapper only extracts `.value` from the `Paise` `landed_cost_per_unit` returns; it
    performs no arithmetic of its own. That formula has no `Unavailable` path left once a quote
    has parsed successfully (`parse_supplier_quote_adjustment` already gates the one real
    missing-input case) — a `quantity <= 0` caller bug raises `ValueError`, and this function
    does not catch it, matching how `contribution_profit`'s own callers let a formula's raised
    exception propagate rather than converting it into a soft UNAVAILABLE result.
    """
    result_paise = landed_cost_per_unit(quote, quantity)
    manual_adjustment_set = tuple(str(a) for a in active_adjustment_ids)

    return MetricResult(
        id=uuid4(),
        metric_code="LANDED_COST_PER_UNIT",
        value_paise=result_paise.value,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=Confidence.MANUAL.value,
        calculation_basis=(
            f"LandedCostPerUnit(sku={sku}, supplier={quote.supplier_name!r}, quantity={quantity}) "
            "= unit_cost_paise + ((shipping_paise + duties_paise) / quantity), each term only if the quote states it, rounded half-up to one paise "
            "(round_half_up_paise, §5.11) — every unit priced identically, not a per-recipient "
            "largest-remainder split — deterministic-engine.md §5.13.1"
        ),
        formula_version="LANDED_COST_PER_UNIT.v2",
        canonical_data_version="non-canonical",
        as_of_date=as_of_date,
        input_refs=(),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
        manual_adjustment_set=manual_adjustment_set,
    )


def compute_batch_constrained_quantity(
    budget: Paise,
    landed_cost_per_unit_value: Paise,
    moq: int | None,
    *,
    sku: str,
    active_adjustment_ids: Sequence[UUID | str],
    computed_at: datetime,
    as_of_date: date | None = None,
) -> MetricResult:
    """cfo-agent.md §6.12 (Batch size) — the budget-and-MOQ arithmetic ceiling only (CP B3a).
    `metric_code = BATCH_CONSTRAINED_QUANTITY` — no metric_code is named anywhere in
    deterministic-engine.md or cfo-agent.md for this capability (checked both), so this name
    was chosen to match this file's existing convention (`LANDED_COST_PER_UNIT`,
    `GST_PERIOD_SUMMARY`) — a plain, descriptive, all-caps snake case name for what the value
    represents.

    This is NOT yet the full "budget-constrained order-quantity range" §6.12 describes — that
    range additionally incorporates observed sales velocity, which is a later checkpoint's job
    (CFO wiring, consuming `CanonicalLine` sales history), not this formula's. This wrapper
    exposes exactly the honest floor §6.12 itself names: "For a SKU the seller has never sold,
    there is no velocity — the estimate degrades to a budget-and-MOQ arithmetic exercise."

    `budget`/`moq` are seller-declared, non-canonical inputs (`batch.budget` and
    `supplier.quote`, both §7.2.1) — like `compute_landed_cost`, there is no `Unavailable` path
    left once inputs are validated; a caller-bug input (`landed_cost_per_unit_value.value <= 0`,
    negative `budget`, or non-positive `moq`) raises `ValueError` and this wrapper does not
    catch it, matching `compute_landed_cost`'s own precedent of letting the formula's raised
    exception propagate.

    `value_paise` is a genuine shape mismatch here: `MetricResult.value_paise` is documented as
    a money amount in paise, but this result is a unit COUNT (`max_affordable_units`), not
    money. There is no other numeric field on `MetricResult` to carry it. Rather than silently
    forcing that fit, `value_paise` is deliberately still used to carry the count so this result
    can be persisted like every other metric (no other slot exists), but `calculation_basis`
    below says explicitly that the figure is a unit count, not paise, and this docstring flags
    the mismatch rather than papering over it — see the CP B3a report for the design-tension
    note in full.
    """
    result: BudgetConstrainedQuantity = budget_constrained_quantity(budget, landed_cost_per_unit_value, moq)
    manual_adjustment_set = tuple(str(a) for a in active_adjustment_ids)

    return MetricResult(
        id=uuid4(),
        metric_code="BATCH_CONSTRAINED_QUANTITY",
        value_paise=result.max_affordable_units,
        recognition_state=RecognitionState.RECOGNISED,
        confidence=Confidence.MANUAL.value,
        calculation_basis=(
            f"BudgetConstrainedQuantity(sku={sku}, budget_paise={budget.value}, "
            f"landed_cost_per_unit_paise={landed_cost_per_unit_value.value}, moq={moq!r}) "
            f"= floor(budget / landed_cost_per_unit) = {result.max_affordable_units} "
            "-- a unit COUNT, not paise; meets_moq="
            f"{result.meets_moq}, recommended_quantity={result.recommended_quantity}, "
            f"units_short={result.units_short} -- budget-and-MOQ arithmetic only (no sales "
            "velocity), never rounded up (floor division) -- deterministic-engine.md §7.2.1, "
            "cfo-agent.md §6.12"
        ),
        formula_version="BATCH_CONSTRAINED_QUANTITY.v1",
        canonical_data_version="non-canonical",
        as_of_date=as_of_date,
        input_refs=(),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
        manual_adjustment_set=manual_adjustment_set,
    )


def compute_gst_period_summary(
    lines: Sequence[CanonicalLine],
    *,
    ingestion_run_ids: Sequence[UUID | str],
    adapter_versions: Sequence[str],
    active_adjustment_ids: Sequence[UUID | str],
    computed_at: datetime,
    as_of_date: date | None = None,
    tax_heads: frozenset[str] = DEFAULT_TAX_HEADS,
) -> list[MetricResult]:
    """deterministic-engine.md §8.3. Returns one MetricResult per tax head in `tax_heads`,
    mirroring compute_price_positioning's precedent: `metric_code` is CONSTANT
    ("GST_PERIOD_SUMMARY") across every row, differentiated only via `calculation_basis`.

    This is a fresh computation over canonical lines (not a composition of two prior
    MetricResults, unlike compute_metric_delta), so `canonical_data_version` is derived the
    normal way, exactly as compute_net_realized_revenue does.

    `gst_period_summary` has no Unavailable path (a period sum over canonical lines never
    fails for missing data — see gst/summary.py), so every row here is always available;
    zero-amount tax heads are included, never omitted.
    """
    summary = gst_period_summary(lines, tax_heads=tax_heads)
    canonical_data_version = derive_canonical_data_version(
        ingestion_run_ids, adapter_versions, active_adjustment_ids
    )
    manual_adjustment_set = tuple(str(a) for a in active_adjustment_ids)

    results: list[MetricResult] = []
    for head, amount in summary.items():
        results.append(
            MetricResult(
                id=uuid4(),
                metric_code="GST_PERIOD_SUMMARY",
                value_paise=amount.value,
                recognition_state=RecognitionState.RECOGNISED,
                confidence="DERIVED",
                calculation_basis=f"GSTPeriodSummary — {head} collected (deterministic-engine.md §8.3)",
                formula_version="GST_PERIOD_SUMMARY.v1",
                canonical_data_version=canonical_data_version,
                as_of_date=as_of_date,
                input_refs=(),
                exclusions=(),
                computed_at=computed_at,
                is_available=True,
                manual_adjustment_set=manual_adjustment_set,
            )
        )
    return results


def compute_margin_curve(
    candidate_prices: Sequence[Paise],
    *,
    basis: Basis,
    gst_rate: Fraction | None,
    cogs: Paise | Unavailable,
    fee_reference: FeeReference | Unavailable,
    shipping_logistics: Paise | Unavailable,
    advertising_costs: Paise | Unavailable,
    return_rto_losses: Paise | Unavailable,
    other_allocated_costs: Paise | Unavailable,
    ingestion_run_ids: Sequence[UUID | str],
    adapter_versions: Sequence[str],
    active_adjustment_ids: Sequence[UUID | str],
    computed_at: datetime,
    as_of_date: date | None = None,
) -> list[MetricResult]:
    """deterministic-engine.md §5.13.1: `margin_curve(sku, candidate_prices[], period,
    as_of_date)` -> `metric_result[]`, `metric_code = MARGIN_AT_PRICE`. **CFO-exclusive** —
    reserved for the seller's own owned `sku` with COGS history (`cfo-agent.md` §6.7), never
    for a candidate the seller does not yet own (§5.13.2 covers that unrelated case).

    Returns one `MetricResult` per entry in `candidate_prices`, in the SAME order as the
    input sequence (deterministic — never reordered). `metric_code` is CONSTANT
    ("MARGIN_AT_PRICE") across every row, mirroring compute_price_positioning's and
    compute_gst_period_summary's precedent — rows are differentiated only via
    `calculation_basis`, which names the specific candidate price each row is for.

    `canonical_data_version="non-canonical"` for EVERY row (approved decision), mirroring
    compute_price_positioning/compute_repricing_scenario's precedent for a hypothetical
    scenario result — a margin-at-a-candidate-price figure is not itself canonical sales
    data, even though the cost/fee inputs feeding it may ultimately trace back to canonical
    figures elsewhere. `ingestion_run_ids`/`adapter_versions`/`active_adjustment_ids` are
    still accepted and folded into `manual_adjustment_set` (for audit traceability of which
    manual adjustments were in scope), but deliberately not into a derived
    `canonical_data_version` here.

    A single missing input (e.g. COGS unavailable) never kills the whole candidate-price
    list — only the affected row(s) come back UNAVAILABLE; other rows are still computed.

    `FIXED`-type `fee_reference` rows cannot be represented — see margin_curve.py's module
    docstring; callers must resolve a percentage-bearing FeeReference before calling this.
    """
    manual_adjustment_set = tuple(str(a) for a in active_adjustment_ids)
    results: list[MetricResult] = []

    for price in candidate_prices:
        margin = margin_at_price(
            price,
            basis=basis,
            gst_rate=gst_rate,
            cogs=cogs,
            fee_reference=fee_reference,
            shipping_logistics=shipping_logistics,
            advertising_costs=advertising_costs,
            return_rto_losses=return_rto_losses,
            other_allocated_costs=other_allocated_costs,
        )

        if isinstance(margin, Unavailable):
            results.append(
                MetricResult(
                    id=uuid4(),
                    metric_code="MARGIN_AT_PRICE",
                    value_paise=None,
                    recognition_state=RecognitionState.UNAVAILABLE,
                    confidence="DERIVED",
                    calculation_basis=(
                        f"MarginAtPrice(candidate_price_paise={price.value}) — UNAVAILABLE, "
                        "see unavailable_reason"
                    ),
                    formula_version="MARGIN_AT_PRICE.v1",
                    canonical_data_version="non-canonical",
                    as_of_date=as_of_date,
                    input_refs=(),
                    exclusions=(),
                    computed_at=computed_at,
                    is_available=False,
                    manual_adjustment_set=manual_adjustment_set,
                    unavailable_reason=margin.reason,
                )
            )
            continue

        # Judgment call (flagged, not silently decided): the only confidence-bearing input
        # this function actually has is `fee_reference.confidence` (a str, per fee_resolution's
        # FeeReference shape) — cogs/shipping/advertising/return_rto_losses/other_allocated_costs
        # arrive as plain Paise with no confidence attached, so there is nothing else to
        # combine it with. Rather than discard that one real signal in favour of a blanket
        # literal "DERIVED", this uses combine_confidence on the single available source, which
        # degrades to that source unchanged (monotonic combination of one input, data-foundation
        # §7.1) — still never presents the curve as more certain than fee_reference itself.
        confidence = combine_confidence(Confidence(fee_reference.confidence))  # type: ignore[union-attr]

        results.append(
            MetricResult(
                id=uuid4(),
                metric_code="MARGIN_AT_PRICE",
                value_paise=margin.value,
                recognition_state=RecognitionState.RECOGNISED,
                confidence=confidence.value,
                calculation_basis=(
                    f"MarginAtPrice(candidate_price_paise={price.value}) — "
                    "deterministic-engine.md §5.13.1"
                ),
                formula_version="MARGIN_AT_PRICE.v1",
                canonical_data_version="non-canonical",
                as_of_date=as_of_date,
                input_refs=(),
                exclusions=(),
                computed_at=computed_at,
                is_available=True,
                manual_adjustment_set=manual_adjustment_set,
            )
        )

    return results
