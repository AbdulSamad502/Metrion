"""The entitlement chokepoint — auth.md §7.2's second gate ("has this tenant purchased/is
entitled to use CI, and is there room left?"), kept distinct from `agent.ci` permission
(`auth/permissions.py`), exactly as §7.2 requires.

**No entitlement spec exists yet** (`auth.md` line 5: "entitlement spec (not yet written)"),
and every numeric limit anyone has mentioned for CI — 25 URLs / 100 runs per month
(`competitor-intelligence-agent.md` §12 Q3) — is explicitly flagged **provisional and
unlocked**, and `phase-1-readiness-review.md` 3.3 defers "final pricing, tiers, and credit
values... by agreement." Implementing any of those numbers as a real deny threshold would be
inventing a business rule this codebase has not actually decided, which is exactly what was
asked not to do here.

What this module DOES do, instead of leaving `entitlement_check` a bare hardcoded string:
compute the tenant's REAL current CI usage (from already-persisted data, not a stub number)
and route every call through one named function. `phase-1-readiness-review.md` calls the
entitlement chokepoint "live from day one, not a stub" — this is that chokepoint's
plumbing, minus the one number nobody has decided yet. When the entitlement spec lands, only
`resolve_ci_entitlement`'s body changes — no caller of it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from competitor_intelligence.repositories import competitor_url_repo


@dataclass(frozen=True, slots=True)
class CiEntitlementResult:
    passed: bool
    reason: str | None
    active_competitor_urls: int


def resolve_ci_entitlement(tenant_id: UUID) -> CiEntitlementResult:
    """Always passes today — see module docstring for why a deny path isn't implemented
    yet. `active_competitor_urls` is real, live-queried usage, so a future cap can be
    compared against actual numbers from day one rather than needing its own telemetry
    added later."""
    active = competitor_url_repo.count_active(tenant_id)
    return CiEntitlementResult(passed=True, reason=None, active_competitor_urls=active)


def entitlement_check_value(result: CiEntitlementResult) -> str:
    """Maps to `agent_run.entitlement_check`'s existing `PASS | DENIED` column contract
    (`backend/migrations/versions/20260917_0002_orchestration_tables.py`)."""
    return "PASS" if result.passed else "DENIED"
