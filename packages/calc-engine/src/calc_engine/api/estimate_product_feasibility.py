"""estimate_product_feasibility() — deterministic-engine.md §5.13.2. PI-exclusive.

Feasibility for a discovered candidate the seller does not yet own — a distinct surface
from `estimate_competitor_margin_range` (§5.13, CI-exclusive) and from `margin_curve`
(CFO-exclusive, a seller's own SKU only). Backed by `product_feasibility_estimate`
(`20260929_0012_product_feasibility_estimate.py`), never `metric_result` — the result
carries an `estimate_ref`, never an `engine_result_ref` (§9.1).

**Checkpoint 2 — real implementation.** Checkpoint 1 scaffolded the frozen dataclass
shapes below (`ProspectiveObservationSet`, `ProductFeasibilityEstimate`) with a stub body.
This module now implements the real §5.13.2 rules 1-6.

**Signature refinement from the Checkpoint-1 stub — `fee_reference` added as a keyword
parameter.** §5.13.2's rule 1 ("identical in spirit" to §5.13 rule 1) says the caller
passes no rates and no fee amounts, and the engine resolves them. This module honours that
intent the same way `compute_margin_curve`/`margin_at_price` already do for the CFO-exclusive
margin surface: this `api` layer is pure and DB-free (`compute_metric.py`'s own docstring:
"it does not persist anything or touch Postgres"), so the actual `config_repo
.resolve_fee_reference()` DB call is the caller's job (PI's `direct_path/` layer), which then
passes the already-resolved `FeeReference | Unavailable` in here unchanged — the caller never
invents, guesses, or supplies a raw rate of its own, which is the substance of rule 1. This is
the same shape `margin_at_price`/`compute_margin_curve` already established for the sibling
CFO-exclusive surface; there is no reason for this PI-exclusive surface to invent a different
one. Distinct from `ProspectiveObservationSet` (unchanged from Checkpoint 1) — `fee_reference`
is deliberately NOT a field on the observation set, since it is not something PI observes, it
is something the engine (via its caller) resolves from config.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction
from uuid import UUID, uuid4

from calc_engine.formulas.fee_resolution import FeeReference
from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Confidence, Paise, Unavailable


@dataclass(frozen=True, slots=True)
class ProspectiveObservationSet:
    """§5.13.2 / PI build plan §1. Inputs come from the seller's stated target-price band
    and budget on `niche_brief` — never an observed marketplace listing price, since PI
    discovers candidates without marketplace access (see the PI build plan's Context)."""

    marketplace: str
    category: str
    candidate_prices: tuple[Paise, ...]
    stated_cogs_paise: Paise | None
    """OPTIONAL. Only ever a value the seller stated, sourced from a `supplier.quote`
    manual_adjustment. Never derived, estimated, or supplied by PI itself
    (`product-intelligence-agent.md` §6.7)."""
    budget_paise: Paise
    as_of_date: date
    source_url: str
    fetched_at: datetime
    confidence: Confidence = Confidence.DERIVED
    """Always DERIVED at this boundary, same rule as §5.13 — a PI observation never enters
    an engine call as anything stronger (`product-intelligence-agent.md` §5.1)."""


@dataclass(frozen=True, slots=True)
class ProductFeasibilityEstimate:
    """§5.13.2 / §9.1. `id` is the `estimate_ref` — scoped to `product_feasibility_estimate`
    only, never interchangeable with `competitor_estimate.id` or a `metric_result.id`
    (`engine_result_ref`)."""

    id: UUID
    tenant_id: UUID
    low_paise: Paise
    high_paise: Paise
    confidence: Confidence  # DERIVED, never better (§5.13.2)
    basis: str
    assumptions: tuple[str, ...]
    cogs_basis: str  # "STATED" | "UNKNOWN" (§5.13.2 rule 6)
    fee_reference_version: int
    observation_ref: dict[str, object]
    formula_version: str
    config_version: str
    computed_at: datetime


def estimate_product_feasibility(
    observation: ProspectiveObservationSet,
    *,
    fee_reference: FeeReference | Unavailable,
    tenant_id: UUID,
    computed_at: datetime,
) -> ProductFeasibilityEstimate:
    """Real logic, §5.13.2 rules 1-6.

    - Rule 1: output is always a range (`low_paise`/`high_paise`), never a point.
    - Rule 2: a missing/range-only `fee_reference` widens the range rather than suppressing
      the figure or defaulting to zero; the gap is always named in `assumptions`.
    - Rule 3: never written to `metric_result` — this function never returns (or constructs)
      one, only `ProductFeasibilityEstimate`.
    - Rule 4: `confidence` is fixed at `Confidence.DERIVED`, never better.
    - Rule 5: the engine never estimates a cost itself — `observation.stated_cogs_paise` is
      either the caller's seller-declared figure or absent; this function only branches on it.
    - Rule 6: absent `stated_cogs_paise` -> `cogs_basis="UNKNOWN"`, range reflects price/fee
      spread only, and `assumptions` explicitly states this is not a margin estimate.

    All arithmetic is `Paise`/`Fraction` — no float anywhere in the calculation path (AC3).

    `observation.candidate_prices` must be non-empty (a caller bug otherwise, mirroring
    `landed_cost_per_unit`'s own "caller bug raises, not UNAVAILABLE" precedent for
    structurally-invalid input) — every other genuinely-missing-input case is a *data* gap,
    handled by widening + naming, never by raising.
    """
    if not observation.candidate_prices:
        raise ValueError(
            "estimate_product_feasibility requires at least one candidate_price on the "
            "observation set — an empty price band is a caller bug, not a missing-data case"
        )

    assumptions: list[str] = []

    # --- Fee resolution (rule 2) -------------------------------------------------------
    # fee_rate_low/fee_rate_high bound the fee percentage applied at each candidate price.
    # A resolved point rate collapses both to the same value (no widening needed). A
    # range-only or wholly-missing fee_reference widens the spread between them instead of
    # failing or defaulting to zero — the gap is always named below.
    if isinstance(fee_reference, Unavailable):
        fee_rate_low = Fraction(0)
        fee_rate_high = Fraction(0)
        fee_reference_version = 0
        config_version = "UNAVAILABLE"
        assumptions.append(
            f"fee_reference unavailable ({fee_reference.reason}) — no marketplace fee is "
            "reflected in this range at all, which WIDENS (raises) the estimate relative to "
            "what a resolved fee would produce; treat the high end of this range especially "
            "cautiously until a real fee_reference is resolved"
        )
    elif fee_reference.rate_pct is not None:
        fee_rate_low = fee_reference.rate_pct
        fee_rate_high = fee_reference.rate_pct
        fee_reference_version = fee_reference.version
        config_version = str(fee_reference.version)
        assumptions.append(
            f"fee_reference resolved to a point rate {fee_reference.rate_pct}% "
            f"(source={fee_reference.source}, version={fee_reference.version})"
        )
    else:
        # Range-only FeeReference (§5.14's "never collapse a range" rule, mirrored from
        # fee_resolution.py) — unlike margin_at_price (which has no range to widen into and
        # must fail UNAVAILABLE), this estimation surface's whole point is a range, so both
        # ends of the fee range are used directly rather than refusing the figure.
        if fee_reference.rate_low_pct is None or fee_reference.rate_high_pct is None:
            raise ValueError(f"fee_reference is malformed (no rate populated at all): {fee_reference!r}")
        fee_rate_low = fee_reference.rate_low_pct
        fee_rate_high = fee_reference.rate_high_pct
        fee_reference_version = fee_reference.version
        config_version = str(fee_reference.version)
        assumptions.append(
            f"fee_reference provided only a rate range ({fee_reference.rate_low_pct}% - "
            f"{fee_reference.rate_high_pct}%), not a resolved point rate — this range is "
            f"WIDENED accordingly rather than guessing a midpoint (source={fee_reference.source}, "
            f"version={fee_reference.version})"
        )

    # --- COGS basis (rules 5, 6) -------------------------------------------------------
    if observation.stated_cogs_paise is not None:
        cogs_basis = "STATED"
        cogs_fraction = Fraction(observation.stated_cogs_paise.value)
        assumptions.append(
            f"stated_cogs_paise={observation.stated_cogs_paise.value} (seller-declared, via a "
            "supplier.quote manual_adjustment) is subtracted at every candidate price — this IS "
            "a margin estimate"
        )
    else:
        cogs_basis = "UNKNOWN"
        cogs_fraction = Fraction(0)
        assumptions.append(
            "no stated_cogs_paise was provided (no supplier.quote yet) — cogs_basis=UNKNOWN, "
            "this range reflects candidate price and marketplace fee spread ONLY; it is NOT a "
            "margin estimate and must never be presented as one"
        )

    # --- Range across candidate_prices (rule 1) -----------------------------------------
    net_low_candidates: list[Fraction] = []
    net_high_candidates: list[Fraction] = []
    for price in observation.candidate_prices:
        price_fraction = Fraction(price.value)
        fee_amount_at_low_rate = price_fraction * fee_rate_low / 100
        fee_amount_at_high_rate = price_fraction * fee_rate_high / 100
        # Higher fee rate -> lower net figure; lower fee rate -> higher net figure. Taking
        # both ends per price (rather than one fee rate for the whole band) is what makes the
        # missing/range-only fee_reference cases above actually widen the final range.
        net_low_candidates.append(price_fraction - fee_amount_at_high_rate - cogs_fraction)
        net_high_candidates.append(price_fraction - fee_amount_at_low_rate - cogs_fraction)

    low_paise = round_half_up_paise(min(net_low_candidates))
    high_paise = round_half_up_paise(max(net_high_candidates))

    basis = (
        "ProductFeasibilityEstimate = candidate_price - marketplace_fee (§5.14) - cogs (where "
        f"stated), evaluated across {len(observation.candidate_prices)} candidate price(s) in "
        f"{observation.marketplace}/{observation.category} — cogs_basis={cogs_basis} "
        "(deterministic-engine.md §5.13.2)"
    )

    observation_ref: dict[str, object] = {
        "marketplace": observation.marketplace,
        "category": observation.category,
        "candidate_prices_paise": [p.value for p in observation.candidate_prices],
        "stated_cogs_paise": (
            observation.stated_cogs_paise.value if observation.stated_cogs_paise is not None else None
        ),
        "budget_paise": observation.budget_paise.value,
        "as_of_date": observation.as_of_date.isoformat(),
        "source_url": observation.source_url,
        "fetched_at": observation.fetched_at.isoformat(),
        "confidence": observation.confidence.value,
    }

    return ProductFeasibilityEstimate(
        id=uuid4(),
        tenant_id=tenant_id,
        low_paise=low_paise,
        high_paise=high_paise,
        confidence=Confidence.DERIVED,
        basis=basis,
        assumptions=tuple(assumptions),
        cogs_basis=cogs_basis,
        fee_reference_version=fee_reference_version,
        observation_ref=observation_ref,
        formula_version="PRODUCT_FEASIBILITY_ESTIMATE.v1",
        config_version=config_version,
        computed_at=computed_at,
    )
