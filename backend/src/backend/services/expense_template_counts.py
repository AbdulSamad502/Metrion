"""The engine's order and unit counts for per-order and per-unit expense templates (engine section 5.18.2, kickoff S4b).

Selects the tenant's sales lines in a window through the same assembly the period P&L uses (so a line's cancellation, return and RTO status come from the same observed
columns and seller overrides), then hands them to `calc_engine.formulas.expense_templates.count_for_scope`, which does all the counting. This module adds nothing up: a line
that could not be assembled is passed on as `blocked_lines`, so a count is never built from a partial set.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from calc_engine.formulas.expense_templates import CountOutcome, count_for_scope
from calc_engine.repositories import canonical_repo

from backend.services import cfo_actions


def count_provider(tenant_id: UUID):  # noqa: ANN201
    """A `CountProvider` bound to one tenant: `(period_start, period_end, "ORDER" | "UNIT") -> CountOutcome`."""

    def get(period_start: date, period_end: date, per: str) -> CountOutcome:
        assembled = cfo_actions.assemble_canonical_lines_for_period(tenant_id, period_start=period_start, period_end=period_end)
        rows = canonical_repo.sales_lines_in_period(tenant_id, period_start=period_start, period_end=period_end)
        order_ref = {str(r["sales_line_id"]): r.get("order_ref") for r in rows}
        return count_for_scope(assembled.lines, order_ref, per, blocked_lines=len(assembled.blocked))

    return get
