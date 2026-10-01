"""Per-candidate feasibility — PI build plan §1/§6.7, closing a real gap found during the
2026-10-01 quality pass: `calc_engine.api.estimate_product_feasibility` was built and
unit-tested but had no caller anywhere in PI, so a discovered candidate never carried any
feasibility/profitability figure at all. This module is that missing wiring — the single
piece that turns "here is a product idea" into "here is a product idea, and here is a rough
sense of whether it could be worth the money," which is the whole point of PI per the plan's
own framing.

**Inputs come from the seller's stated target-price band and budget on `niche_brief`, never
an observed marketplace listing price** — `ProspectiveObservationSet`'s own docstring states
this and it holds here unchanged, since PI discovers candidates without marketplace access
(plan Context). `stated_cogs_paise` is always `None` at discovery time: no supplier-quote
mechanism exists yet in PI's data model (`supplier_lead` carries contact info only, not a
quote) — that is Phase 2/3 scope, not invented here. Every estimate this module produces is
therefore `cogs_basis="UNKNOWN"` today: a price/fee-spread range, never a margin estimate,
exactly as `estimate_product_feasibility`'s own rule 6 requires and renders.

**Never silently skipped.** When a candidate's feasibility cannot be computed (no target
price band on the brief, no budget stated, no category resolvable), `feasibility_status`
is explicitly `UNAVAILABLE` with a named reason — the same "missing data is named, never
hidden" discipline as every other PI field (plan §0e).

This module owns the one cross-package call PI makes into `calc_engine` — `discovery_run.py`
and `candidate_synthesis.py` deliberately have no `calc_engine` import at all (their own
docstrings), keeping `web_price_signal`'s isolation from Brain 1 structurally obvious. This
module is the one place that import is allowed, and it never touches `web_price_signal`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from calc_engine.api.estimate_product_feasibility import (
    ProductFeasibilityEstimate,
    ProspectiveObservationSet,
    estimate_product_feasibility,
)
from calc_engine.formulas.fee_resolution import resolve_fee_or_unavailable
from calc_engine.repositories import config_repo, product_feasibility_estimate_repo
from calc_engine.types import Paise

_FEE_TYPE = "COMMISSION"  # the dominant marketplace fee component — same choice CFO's own
# feasibility-adjacent pricing paths default to when a single representative fee is needed.


@dataclass(frozen=True, slots=True)
class FeasibilityOutcome:
    status: str  # COMPUTED | UNAVAILABLE
    estimate_ref: UUID | None
    low_paise: int | None
    high_paise: int | None
    cogs_basis: str | None
    assumptions: list[str] | None
    unavailable_reason: str | None


def _unavailable(reason: str) -> FeasibilityOutcome:
    return FeasibilityOutcome(
        status="UNAVAILABLE",
        estimate_ref=None,
        low_paise=None,
        high_paise=None,
        cogs_basis=None,
        assumptions=None,
        unavailable_reason=reason,
    )


def compute_candidate_feasibility(
    tenant_id: UUID,
    *,
    niche_brief: dict[str, Any],
    candidate: dict[str, Any],
    now: datetime | None = None,
) -> FeasibilityOutcome:
    """Computes and persists one candidate's feasibility estimate, returning the snapshot to
    write back onto `product_candidate` (the caller's job — this function has no dependency
    on `product_candidate_repo`, keeping the direction of the dependency one-way: discovery
    modules may call this, this module never calls back into them)."""
    now = now or datetime.now()
    as_of = now.date() if isinstance(now, datetime) else now

    marketplaces = niche_brief.get("marketplaces")
    if not marketplaces:
        return _unavailable("no marketplace selected on the niche brief — feasibility needs one to resolve fees against")
    marketplace = marketplaces[0]

    category = niche_brief.get("category_text") or candidate.get("observed_category")
    if not category:
        return _unavailable("no category available (neither the niche brief nor the candidate names one) to resolve a fee reference against")

    budget_paise = niche_brief.get("budget_paise")
    if budget_paise is None:
        return _unavailable("seller has not stated a budget on the niche brief")

    price_min = niche_brief.get("target_price_min_paise")
    price_max = niche_brief.get("target_price_max_paise")
    candidate_price_values = [p for p in (price_min, price_max) if p is not None]
    if not candidate_price_values:
        return _unavailable("seller has not stated a target price band on the niche brief")

    source_urls = candidate.get("source_urls") or []
    source_url = source_urls[0]["url"] if source_urls and isinstance(source_urls[0], dict) and "url" in source_urls[0] else "UNAVAILABLE"

    fee_row = config_repo.resolve_fee_reference(
        tenant_id, marketplace=marketplace, category=str(category), fee_type=_FEE_TYPE, as_of_date=as_of
    )
    try:
        fee_reference = resolve_fee_or_unavailable(fee_row)
    except ValueError as exc:
        # Bug-hunt pass (2026-10-01): `resolve_fee_or_unavailable` deliberately raises when a
        # `fee_reference` row exists but all three rate fields are NULL — a malformed config
        # row, which is realistic operational data drift (a bad seed/admin-tool entry), not a
        # programming error. Previously this propagated straight through this function (no
        # try/except at all) and aborted the WHOLE discovery run for every future niche_brief
        # in that category until the bad row was manually fixed. Degrading this one
        # candidate's feasibility to UNAVAILABLE, with the malformed-config reason named,
        # matches this module's own "never silently skipped" contract (module docstring) —
        # every other missing-data case already degrades this way, this is not a new carve-out.
        return _unavailable(f"fee_reference config for this category is malformed: {exc}")

    observation = ProspectiveObservationSet(
        marketplace=marketplace,
        category=str(category),
        candidate_prices=tuple(Paise(v) for v in candidate_price_values),
        stated_cogs_paise=None,  # no supplier-quote mechanism in PI yet — module docstring
        budget_paise=Paise(budget_paise),
        as_of_date=as_of,
        source_url=source_url,
        fetched_at=now,
    )

    estimate: ProductFeasibilityEstimate = estimate_product_feasibility(
        observation, fee_reference=fee_reference, tenant_id=tenant_id, computed_at=now
    )
    product_feasibility_estimate_repo.save(tenant_id, estimate)

    return FeasibilityOutcome(
        status="COMPUTED",
        estimate_ref=estimate.id,
        low_paise=estimate.low_paise.value,
        high_paise=estimate.high_paise.value,
        cogs_basis=estimate.cogs_basis,
        assumptions=list(estimate.assumptions),
        unavailable_reason=None,
    )
