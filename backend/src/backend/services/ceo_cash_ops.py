"""The seller's cash position through the CEO (docs/specs/cfo-3-growth-advisor.md, Phase 0): expected marketplace settlements and open payables.

A READ over the SAME deterministic path as the CFO dashboard's Cash & Tax view (`cfo_dashboard.cash` and `payables`): the planner mints each expected-receipts figure as an ESTIMATE with an
`estimate_ref`; payables are the seller's own entries. Nothing is computed here. Expected settlements are a projection from the seller's OWN settlement history, never a bank balance, and the
answer says so. The window of sold-but-unsettled lines looked at is the last 90 days.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.auth.context import AuthContext
from backend.services import cfo_dashboard

WINDOW_DAYS = 90


class CashSlots(BaseModel):
    """No inputs: the cash view always looks at the same trailing window."""

    model_config = ConfigDict(extra="forbid")


def position(slots: CashSlots, ctx: AuthContext) -> dict[str, Any]:
    assert ctx.tenant_id is not None and ctx.app_user_id is not None
    today = datetime.now(timezone.utc).date()
    scope = cfo_dashboard.Scope(today - timedelta(days=WINDOW_DAYS - 1), today, today)
    out = cfo_dashboard.cash(ctx.tenant_id, ctx.app_user_id, scope)
    out["payables"] = cfo_dashboard.payables(ctx.tenant_id).get("items", [])
    out["window"] = {"start": scope.start.isoformat(), "end": scope.end.isoformat()}
    return out
