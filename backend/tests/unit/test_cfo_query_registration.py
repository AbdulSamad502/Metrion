"""The CEO reaches the planner only through the registered `cfo.query` action, whose slots are a question and periods — never a plan, a metric,
SQL or a tenant (cfo-query-planner.md Q1, Q5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.ceo.registry import build_default_registry

GOOD = {"question": "why did my profit fall?", "period_start": "2026-10-01", "period_end": "2026-10-31", "as_of_date": "2026-11-01"}


def _spec():
    reg = build_default_registry()
    return next(s for s in reg.specs() if s.key == "cfo.query") if hasattr(reg, "specs") else reg.get("cfo.query")


def test_cfo_query_is_registered_read_only_and_entitlement_gated() -> None:
    spec = _spec()
    assert spec.source == "CFO" and spec.effect.value == "READ" and spec.entitlement is not None


def test_the_slots_are_a_question_and_periods_and_reject_anything_else() -> None:
    model = _spec().slot_model
    assert model.model_validate(GOOD).question == "why did my profit fall?"
    for extra in ({"tenant_id": "00000000-0000-0000-0000-000000000000"}, {"plan": {"steps": []}}, {"sql": "select 1"}, {"metric": "GROSS_SALES"}):
        with pytest.raises(ValidationError):
            model.model_validate({**GOOD, **extra})


def test_a_comparison_period_must_be_complete() -> None:
    model = _spec().slot_model
    with pytest.raises(ValidationError):
        model.model_validate({**GOOD, "compare_period_start": "2026-09-01"})
    ok = model.model_validate({**GOOD, "compare_period_start": "2026-09-01", "compare_period_end": "2026-09-30", "compare_as_of_date": "2026-10-01"})
    assert ok.compare_period_end.isoformat() == "2026-09-30"


def test_an_expense_upload_is_the_businesss_not_a_marketplaces() -> None:
    from backend.services import cfo_ingestion

    assert cfo_ingestion.validate_upload_request("e.csv", "ALL", "EXPENSE") == ".csv"
    for bad in (("e.csv", "MEESHO", "EXPENSE", None), ("e.csv", "ALL", "SALES", None), ("e.csv", "ALL", "EXPENSE", "meesho.orders.v1"), ("e.pdf", "ALL", "EXPENSE", None)):
        with pytest.raises(cfo_ingestion.UploadRejected):
            cfo_ingestion.validate_upload_request(*bad)
    assert cfo_ingestion.validate_upload_request("s.csv", "MEESHO", "SALES") == ".csv"  # unchanged for orders
