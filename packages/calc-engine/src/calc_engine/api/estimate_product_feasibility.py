"""estimate_product_feasibility() — deterministic-engine.md §5.13.2. PI-exclusive.

Feasibility for a discovered candidate the seller does not yet own — a distinct surface
from `estimate_competitor_margin_range` (§5.13, CI-exclusive) and from `margin_curve`
(CFO-exclusive, a seller's own SKU only). Backed by `product_feasibility_estimate`
(`20260929_0012_product_feasibility_estimate.py`), never `metric_result` — the result
carries an `estimate_ref`, never an `engine_result_ref` (§9.1).

**Checkpoint 1 scaffolding only.** This module defines the real, frozen input/output
dataclasses per the PI build plan §1 — `ProspectiveObservationSet` and
`ProductFeasibilityEstimate` — so downstream Checkpoint-1 code (PI's `direct_path/` stubs)
can already reference the real shape. `estimate_product_feasibility(...)` itself is a stub
that raises `NotImplementedError`: the real fee-resolution / STATED-vs-UNKNOWN cogs_basis
logic (§5.13.2 rules 1-6) is Checkpoint 2's job, not this one's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from calc_engine.types import Confidence, Paise


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
    tenant_id: UUID,
    computed_at: datetime,
) -> ProductFeasibilityEstimate:
    """Real logic — fee resolution mirroring `formulas/fee_resolution.py`, `cogs_basis`
    branching (STATED when `observation.stated_cogs_paise` is given, else UNKNOWN with the
    range reflecting price/fee spread only), missing-fee-reference range-widening with the
    gap named in `assumptions`, never a `MetricResult` — is Checkpoint 2's job
    (`docs/specs/deterministic-engine.md` §5.13.2). This stub exists only so the frozen
    dataclass shapes above are real and importable at Checkpoint 1.
    """
    raise NotImplementedError(
        "estimate_product_feasibility: real logic lands in PI build plan Checkpoint 2 "
        "(deterministic-engine.md §5.13.2) — Checkpoint 1 only scaffolds the dataclass shapes."
    )
