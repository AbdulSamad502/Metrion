"""The CEO's seam to Product Intelligence's research case (docs/specs/ceo-pi-research-flow.md §5.3).

The CEO package contains no SQL and imports no specialist, so the three things the CEO does between the approved research legs go through this one module:
choosing the five seller-facing products (a deterministic pre-rank over the saved run, plus a verified image for those five), finalising the case (the final
order and the deterministic recommendation, stored from PI's own fields), and reading the finished case back for the summary. Every function is tenant-scoped,
fetches no marketplace and computes no money figure. `finalize` and `select_top5` write only PI's own case rows (`pi_research_case`, the run's history flags).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from backend.services import pi_actions


def select_top5(tenant_id: UUID, run_id: UUID, *, investigation_id: UUID | None = None) -> list[UUID]:
    return pi_actions.select_research_top5(tenant_id, run_id, investigation_id=investigation_id)


def finalize(tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
    return pi_actions.finalize_research_case(tenant_id, run_id)


def load_case(tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
    """The finished case, or None when this tenant has no visible report for the run."""
    try:
        return pi_actions.load_research_case(tenant_id, run_id)
    except pi_actions.CaseNotAvailable:
        return None


def attach_cfo_figures(tenant_id: UUID, product_name: str, entries: list[dict[str, Any]]) -> UUID | None:
    """Attaches the CFO results the CEO obtained for a numbered product to the newest case; returns the run id, or None when the name matches none of its five."""
    return pi_actions.attach_cfo_figures(tenant_id, product_name, entries)
