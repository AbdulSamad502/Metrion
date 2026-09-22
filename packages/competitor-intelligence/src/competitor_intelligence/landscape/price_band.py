"""CI's role in the price band — competitor-intelligence-agent.md §6.16.3: select and
supply the tenant's tracked competitor prices; the quartile/IQR/fence/outlier arithmetic
lives exclusively in `deterministic-engine.md` §5.15.1 (`compute_price_band`). Nothing in
this module computes a percentile, a fence or an outlier flag.

Eligibility (§6.16.3: "currently tracked EXACT_MATCH-or-LIKELY_VARIANT competitors"):
a tracked (ACTIVE) `competitor_url` scoped to one seller product (`linked_sku == product_id`)
counts if either (a) it has no `ci_candidate` record at all — added through the manual-URL
path, where the seller's own action is itself the identity confirmation (C21) — or (b) its
recorded `identity_match` is `EXACT_MATCH` or `LIKELY_VARIANT`. A competitor whose
`identity_match` is `UNCERTAIN` or `NOT_A_MATCH` is excluded from the aggregate distribution
even if the seller separately accepted it (accept/reject and identity match are independent
axes, §5.4) — it stays visible elsewhere, just never counted in a market-wide band.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from competitor_intelligence.discovery.identity_resolution import IdentityMatch
from competitor_intelligence.repositories import (
    ci_candidate_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)

_ELIGIBLE_IDENTITY_MATCHES = frozenset({IdentityMatch.EXACT_MATCH.value, IdentityMatch.LIKELY_VARIANT.value})


@dataclass(frozen=True, slots=True)
class EligibleCompetitorPrice:
    """One tracked competitor's current usable price, ready to cross the boundary into
    `calc_engine.formulas.price_positioning.CompetitorPrice` (always `DERIVED`, per
    competitor-intelligence-agent.md §5.1/§5.2). `is_likely_variant` is carried so a caller
    can attach the §6.13.2 caveat to anything it renders from this fact — this module itself
    performs no rendering."""

    competitor_url_id: UUID
    snapshot_id: UUID
    value_paise: int
    is_likely_variant: bool


def eligible_competitor_prices(tenant_id: UUID, product_id: str) -> list[EligibleCompetitorPrice]:
    """Never fabricates a price: a tracked competitor with no usable snapshot yet (still
    `PENDING_MANUAL_ENTRY`, or no evidence submitted at all) is silently excluded, not
    defaulted to zero or omitted-with-an-error — the caller (deterministic-engine.md
    §5.15.1 rule 1) correctly reports `UNAVAILABLE` if too few remain."""
    urls = competitor_url_repo.list_active_by_linked_sku(tenant_id, product_id)
    eligible: list[EligibleCompetitorPrice] = []
    for url in urls:
        candidate = ci_candidate_repo.get_by_competitor_url_id(tenant_id, url["id"])
        if candidate is not None and candidate["identity_match"] not in _ELIGIBLE_IDENTITY_MATCHES:
            continue
        snapshot = competitor_snapshot_repo.latest_usable_snapshot(tenant_id, url["id"])
        if snapshot is None:
            continue
        eligible.append(
            EligibleCompetitorPrice(
                competitor_url_id=url["id"],
                snapshot_id=snapshot["id"],
                value_paise=snapshot["listed_price_paise"],
                is_likely_variant=(
                    candidate is not None and candidate["identity_match"] == IdentityMatch.LIKELY_VARIANT.value
                ),
            )
        )
    return eligible
