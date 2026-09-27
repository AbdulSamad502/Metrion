"""`backend.services.cfo_actions.compute_landed_cost_for_quote` — end-to-end at the unit
level, real engine functions (`parse_supplier_quote_adjustment`, `compute_landed_cost`,
`landed_cost_per_unit`). The two DB-touching calls this composition makes
(`manual_adjustment_repo.active_adjustments_for_target`, `metric_result_repo.save`) and the
data-request insert are monkeypatched — no live Postgres in this session, mirroring
`test_cfo_actions_pricing.py`'s own `_stub_persistence`/`insert_data_request` monkeypatch
conventions exactly.

Activates twinkly-mapping-canyon.md CP A4 / cfo-agent.md §6.11's supplier-ranking PRIMITIVE
only — one quote's landed cost, never a comparison/ranking across quotes (Phase B1).

Covers:
  - one ACTIVE `supplier.quote` row -> correct `MetricResult`
    (`metric_code == "LANDED_COST_PER_UNIT"`, `engine_result_ref`/`.id` present,
    `canonical_data_version == "non-canonical"`), persisted, no data request raised.
  - zero ACTIVE rows -> exactly one `agent_data_request` raised (§6.11: "CFO never scores a
    supplier it has no quote for"), `compute_landed_cost` never called, `result is None`.
  - a malformed quote (missing `unit_cost_paise`) -> `parse_supplier_quote_adjustment`'s real
    `ValueError` propagates uncaught, exercised by actually calling the real code path.
  - more than one ACTIVE row for the same target -> exactly one `agent_data_request` raised
    naming the ambiguity, never a silent pick of one row.
  - AC13 structural guardrail: `compute_landed_cost_for_quote`/`LandedCostRequest`/
    `LandedCostOutcome` carry no ranking/ordering/"best" concept at all — a pure single-quote
    lookup.
  - the no-arithmetic lint (`test_no_arithmetic_lint.py`) already scans `cfo_actions.py`
    broadly — confirmed by inspection, not duplicated here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import LandedCostOutcome, LandedCostRequest, compute_landed_cost_for_quote

_AS_OF = date(2026, 9, 23)
_COMPUTED_AT = datetime(2026, 9, 23, tzinfo=timezone.utc)

_VALID_QUOTE_VALUE = {
    "supplier_name": "Acme Textiles",
    "sku": "SKU-1",
    "unit_cost_paise": 150_00,
    "moq": 100,
    "lead_time_days": 14,
    "shipping_paise": 500_00,
    "payment_terms": "50% advance",
    "reliability_note": "On-time last 3 orders",
}


def _adjustment_row(value: dict[str, object], *, row_id=None) -> dict[str, object]:
    return {
        "id": row_id or uuid4(),
        "target_type": "SKU",
        "target_ref": "SKU-1",
        "field": "supplier.quote",
        "value": value,
        "reason": None,
        "created_by": uuid4(),
        "created_at": _COMPUTED_AT,
        "supersedes_id": None,
        "status": "ACTIVE",
    }


def _base_request(*, quantity: int = 100) -> LandedCostRequest:
    return LandedCostRequest(
        sku="SKU-1",
        supplier_quote_target_type="SKU",
        supplier_quote_target_ref="SKU-1",
        quantity=quantity,
        active_adjustment_ids=[],
        requested_by=uuid4(),
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )


@pytest.fixture(autouse=True)
def _stub_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """`metric_result_repo.save` opens a real DB connection — no live Postgres in this
    session, so persistence is stubbed to a no-op, exactly as `test_cfo_actions_pricing.py`'s
    own `_stub_persistence` fixture does."""
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", lambda *a, **k: None)


def test_valid_single_quote_yields_landed_cost_metric_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: [_adjustment_row(_VALID_QUOTE_VALUE)],
    )
    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = compute_landed_cost_for_quote(uuid4(), _base_request())

    assert isinstance(outcome, LandedCostOutcome)
    assert outcome.data_request_id is None
    assert captured_requests == []
    assert outcome.result is not None
    assert outcome.result.metric_code == "LANDED_COST_PER_UNIT"
    assert outcome.result.id is not None  # engine_result_ref
    assert outcome.result.is_available is True
    assert outcome.result.canonical_data_version == "non-canonical"
    # unit_cost_paise (150_00) + shipping_paise (500_00) / quantity (100) = 150_00 + 500 = 155_00
    assert outcome.result.value_paise == 155_00


def test_zero_active_quotes_yields_data_request_never_scores_missing_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: [],
    )
    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = compute_landed_cost_for_quote(uuid4(), _base_request())

    assert outcome.result is None
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["requested_field"] == "supplier.quote"
    assert captured_requests[0]["blocking_metric"] == "LANDED_COST_PER_UNIT"
    assert "no quote" in captured_requests[0]["reason"] or "CFO never scores" in captured_requests[0]["reason"]


def test_malformed_quote_missing_unit_cost_paise_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    malformed = {"supplier_name": "Acme Textiles"}  # missing unit_cost_paise
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: [_adjustment_row(malformed)],
    )

    with pytest.raises(ValueError, match="unit_cost_paise"):
        compute_landed_cost_for_quote(uuid4(), _base_request())


def test_multiple_active_quotes_for_same_target_raises_data_request_never_picks_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _adjustment_row(_VALID_QUOTE_VALUE, row_id=uuid4()),
        _adjustment_row({**_VALID_QUOTE_VALUE, "unit_cost_paise": 200_00}, row_id=uuid4()),
    ]
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: rows,
    )
    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = compute_landed_cost_for_quote(uuid4(), _base_request())

    assert outcome.result is None
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["requested_field"] == "supplier.quote"
    assert captured_requests[0]["blocking_metric"] == "LANDED_COST_PER_UNIT"
    assert "2 ACTIVE" in captured_requests[0]["reason"]


def test_ac13_no_ranking_or_comparison_concept_exists_on_this_surface() -> None:
    """AC13 structural guardrail: this primitive never compares/ranks across quotes. Neither
    the request, the outcome, nor the function itself carries any notion of ordering/"best"/
    multiple-quotes-at-once — a pure single-quote lookup."""
    import inspect

    request_fields = set(LandedCostRequest.__dataclass_fields__.keys())
    outcome_fields = set(LandedCostOutcome.__dataclass_fields__.keys())
    banned_terms = {"rank", "best", "compare", "sort", "order", "top"}

    for field_name in request_fields | outcome_fields:
        lowered = field_name.lower()
        assert not any(term in lowered for term in banned_terms), field_name

    sig = inspect.signature(compute_landed_cost_for_quote)
    assert "quotes" not in sig.parameters  # singular "request" only, never a plural collection
    assert set(sig.parameters.keys()) == {"tenant_id", "request"}

    # LandedCostOutcome.result is a single MetricResult (or None), never a list/sequence of them.
    result_type = LandedCostOutcome.__dataclass_fields__["result"].type
    assert "list" not in str(result_type).lower()
    assert "sequence" not in str(result_type).lower()
