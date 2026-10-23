"""How the business performed in a period, through the CEO (docs/specs/cfo-3-growth-advisor.md, Phase 0).

The same deterministic planner path as the CFO dashboard's Overview and By marketplace tables (a fixed plan, no model), so the CEO's answer and the dashboard can never disagree: each figure is a
stored engine result with a reference, an unavailable figure carries the inputs it needs, and a marketplace whose data is incomplete is named, never guessed. Nothing is computed here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from cfo.planner.pipeline import PlannerAnswer
from pydantic import BaseModel, ConfigDict

from backend.auth.context import AuthContext
from backend.services import cfo_dashboard

_ALL = ("GROSS_SALES", "NET_REALIZED_REVENUE", "MARKETPLACE_FEES", "CONTRIBUTION_PROFIT", "OPERATING_PROFIT")
_BY_MARKETPLACE = ("GROSS_SALES", "NET_REALIZED_REVENUE", "CONTRIBUTION_PROFIT")


class PerformanceSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: date
    period_end: date
    as_of_date: date


def summary(slots: PerformanceSlots, ctx: AuthContext) -> dict[str, Any]:
    from backend.api.v1.cfo import packet_payload

    assert ctx.tenant_id is not None and ctx.app_user_id is not None
    scope = cfo_dashboard.Scope(slots.period_start, slots.period_end, slots.as_of_date)
    total = cfo_dashboard.run(ctx.tenant_id, ctx.app_user_id, scope, [cfo_dashboard._metric(m) for m in _ALL])
    if not isinstance(total, PlannerAnswer):
        return {"status": "REFUSED", "code": total.code, "message": total.message}
    by = cfo_dashboard.run(ctx.tenant_id, ctx.app_user_id, scope, [{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, *[cfo_dashboard._metric(m) for m in _BY_MARKETPLACE]])
    out = packet_payload(total.packet)
    if isinstance(by, PlannerAnswer):
        extra = packet_payload(by.packet)
        out["figures"] = [*out["figures"], *[f for f in extra["figures"] if f.get("dimensionKeys")]]  # type: ignore[operator]
        out["coverage"] = [*out["coverage"], *extra["coverage"]]  # type: ignore[operator]
        out["dataRequests"] = list(dict.fromkeys([*out["dataRequests"], *extra["dataRequests"]]))  # type: ignore[arg-type]
    return out
