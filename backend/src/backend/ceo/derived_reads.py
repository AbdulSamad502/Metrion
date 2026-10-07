"""The ONE place `backend.ceo` may import a CFO service function (spec §6.13 "persisted-derived reads").

`assemble_financial_health` only FETCHES persisted `metric_result` rows, reconstructs them and applies the engine's
deterministic band classification with configured thresholds. It creates no new Brain 1 figure, writes nothing, and calls no
external service or model — which is exactly the definition of a persisted-derived read. Anything that would need a NEW
money figure is a specialist action (registry), never a state read.

`tests/unit/test_ceo_architecture.py` pins this module's imports so it cannot quietly grow into a compute path.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from backend.services.cfo_actions import FinancialHealthOutcome, FinancialHealthRequest, assemble_financial_health


def financial_health_for_period(
    tenant_id: UUID, *, period_start: date, period_end: date, as_of_date: date
) -> FinancialHealthOutcome:
    return assemble_financial_health(
        tenant_id, FinancialHealthRequest(period_start=period_start, period_end=period_end, as_of_date=as_of_date)
    )
