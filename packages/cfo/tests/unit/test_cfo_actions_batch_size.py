"""`backend.services.cfo_actions.assemble_batch_size_estimate` — end-to-end at the unit level,
real engine functions (`parse_supplier_quote_adjustment`, `parse_batch_budget_adjustment`,
`observed_units_sold`, `compute_landed_cost`, `compute_batch_constrained_quantity`). The
DB-touching calls this composition makes (`manual_adjustment_repo.active_adjustments_for_target`,
`metric_result_repo.save`) and the data-request insert are monkeypatched — no live Postgres in
this session, mirroring `test_cfo_actions_landed_cost.py`/`test_cfo_actions_supplier_ranking.py`'s
own monkeypatch conventions exactly.

Activates twinkly-mapping-canyon.md CP B3b / cfo-agent.md §6.12's full batch-size estimate
(T34/AC17f) — B3a's engine core (`budget_constrained_quantity`/`compute_batch_constrained_
quantity`) wired with sales velocity, `batch.budget`, and §6.12's `agent_data_request` rule.

Covers:
  - full happy path with real observed velocity -> correct `MetricResult`, both landed-cost and
    batch-quantity results persisted.
  - never-sold SKU (empty `lines`) WITH moq+lead_time supplied -> degraded-but-not-refused path
    (T34), `velocity_status == "NEVER_SOLD"`, estimate still computed.
  - never-sold SKU with NEITHER moq NOR lead_time supplied -> exactly one `agent_data_request`,
    `result is None` (§6.12's precise "all three missing" rule).
  - `Unavailable` velocity (an unclassified line) WITH moq/lead_time supplied -> degrades, does
    not refuse.
  - expired `batch.budget` -> data request, budget never silently used.
  - zero / multiple ACTIVE `supplier.quote` rows -> data request, mirroring CP A4 exactly.
  - zero / multiple ACTIVE `batch.budget` rows -> data request, same discipline.
  - Subtlety 1 disclosure: present and states whether it applies, correctly keyed off
    `shipping_paise` being set or `None`.
  - AC17f structural guardrail: no forecast/guarantee/"will sell" language anywhere in field
    names or docstrings on the new dataclasses/function.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    BatchSizeOutcome,
    BatchSizeRequest,
    assemble_batch_size_estimate,
)
from calc_engine.types import CanonicalLine, Confidence, Paise

_AS_OF = date(2026, 9, 24)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 24)
_COMPUTED_AT = datetime(2026, 9, 24, tzinfo=timezone.utc)

_VALID_QUOTE_WITH_SHIPPING = {
    "supplier_name": "Acme Textiles",
    "sku": "SKU-1",
    "unit_cost_paise": 100_00,
    "moq": 50,
    "lead_time_days": 14,
    "shipping_paise": 50_00,
}

_VALID_QUOTE_NO_SHIPPING = {
    "supplier_name": "Acme Textiles",
    "sku": "SKU-1",
    "unit_cost_paise": 100_00,
    "moq": 50,
    "lead_time_days": 14,
}

_VALID_QUOTE_NO_MOQ_NO_LEAD_TIME = {
    "supplier_name": "Acme Textiles",
    "sku": "SKU-1",
    "unit_cost_paise": 100_00,
}

_VALID_BUDGET = {"amount_paise": 100_00_00, "valid_until": "2099-01-01"}


def _line(quantity: int = 5) -> CanonicalLine:
    """A fully-resolved, nothing-happened line (no return/RTO/cancellation set at all, every
    tri-state field defaults to `None`/`0` per `CanonicalLine`'s own dataclass defaults) —
    `billable_quantity` falls straight to `quantity - 0 - 0 == quantity` for a line like this."""
    return CanonicalLine(
        sales_line_id=uuid4(),
        marketplace="MEESHO",
        document_type="INVOICE",
        quantity=quantity,
        invoice_date=date(2026, 9, 10),
        dispatch_date=None,
        order_date=None,
        gross_item_amount=Paise(quantity * 100_00),
        components=(),
        confidence=Confidence.PROVISIONAL,
    )


def _unclassified_cancelled_after_dispatch_line() -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=uuid4(),
        marketplace="MEESHO",
        document_type="INVOICE",
        quantity=1,
        invoice_date=date(2026, 9, 10),
        dispatch_date=date(2026, 9, 12),
        order_date=None,
        gross_item_amount=Paise(100_00),
        components=(),
        confidence=Confidence.PROVISIONAL,
        cancellation_state="CANCELLED",
        rto_outcome=None,
    )


def _quote_row(value: dict[str, object], *, row_id=None) -> dict[str, object]:
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


def _budget_row(value: dict[str, object], *, row_id=None) -> dict[str, object]:
    return {
        "id": row_id or uuid4(),
        "target_type": "SKU",
        "target_ref": "SKU-1",
        "field": "batch.budget",
        "value": value,
        "reason": None,
        "created_by": uuid4(),
        "created_at": _COMPUTED_AT,
        "supersedes_id": None,
        "status": "ACTIVE",
    }


def _base_request(*, lines=None) -> BatchSizeRequest:
    return BatchSizeRequest(
        sku="SKU-1",
        supplier_quote_target_type="SKU",
        supplier_quote_target_ref="SKU-1",
        budget_target_type="SKU",
        budget_target_ref="SKU-1",
        lines=lines if lines is not None else [_line(5), _line(3)],
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        active_adjustment_ids=[],
        requested_by=uuid4(),
        computed_at=_COMPUTED_AT,
    )


@pytest.fixture(autouse=True)
def _stub_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def _fake_save(tenant_id, result, **kwargs):
        calls.append({"tenant_id": tenant_id, "result": result, **kwargs})

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", _fake_save)
    monkeypatch.setattr(cfo_actions_module, "_save_calls", calls, raising=False)


def _save_calls() -> list[dict[str, object]]:
    return cfo_actions_module._save_calls  # type: ignore[attr-defined]


def _stub_adjustments(monkeypatch: pytest.MonkeyPatch, *, quote_rows, budget_rows) -> None:
    def _fake_fetch(tenant_id, *, target_type, target_ref, field):
        if field == "supplier.quote":
            return quote_rows
        if field == "batch.budget":
            return budget_rows
        raise AssertionError(f"unexpected field {field!r}")

    monkeypatch.setattr(cfo_actions_module.manual_adjustment_repo, "active_adjustments_for_target", _fake_fetch)


def _stub_data_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured.append(kwargs) or uuid4(),
    )
    return captured


# --- Full happy path -------------------------------------------------------------------------


def test_full_happy_path_with_real_observed_velocity(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_WITH_SHIPPING)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request(lines=[_line(5), _line(3)]))

    assert isinstance(outcome, BatchSizeOutcome)
    assert captured_requests == []
    assert outcome.data_request_id is None
    assert outcome.velocity_status == "OBSERVED"
    assert outcome.observed_units_sold == 8  # 5 + 3, both fully resolved lines
    assert outcome.velocity_unavailable_reason is None

    # Reference quantity = moq (50), since moq is declared.
    assert outcome.reference_quantity == 50
    assert outcome.reference_quantity_basis == "MOQ"

    # unit_cost_paise (100_00=10000) + shipping_paise (50_00=5000) / moq (50) = 10000 + 100 = 10100 = 101_00
    assert outcome.landed_cost_result is not None
    assert outcome.landed_cost_result.metric_code == "LANDED_COST_PER_UNIT"
    assert outcome.landed_cost_result.value_paise == 101_00

    assert outcome.result is not None
    assert outcome.result.metric_code == "BATCH_CONSTRAINED_QUANTITY"
    # floor(100_00_00 / 101_00) = floor(1000000 / 10100) = 99 (99*10100=999900, 100*10100=1010000)
    assert outcome.result.value_paise == 99

    assert outcome.moq == 50
    assert outcome.lead_time_days == 14

    # Both intermediate and final MetricResults persisted, grain="SKU".
    calls = _save_calls()
    assert len(calls) == 2
    for call in calls:
        assert call["grain"] == "SKU"
        assert call["target_ref"] == "SKU-1"
        assert call["config_version"] == cfo_actions_module._BATCH_SIZE_CONFIG_VERSION


# --- Never-sold SKU, degraded-but-not-refused (T34) ------------------------------------------


def test_never_sold_sku_with_moq_and_lead_time_degrades_but_does_not_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_NO_SHIPPING)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request(lines=[]))

    assert captured_requests == []
    assert outcome.data_request_id is None
    assert outcome.velocity_status == "NEVER_SOLD"
    assert outcome.observed_units_sold is None
    assert outcome.velocity_unavailable_reason is not None
    assert "never sold" in outcome.velocity_unavailable_reason.lower()

    # Still computes a real budget-and-MOQ estimate -- the honest degraded floor, not a refusal.
    assert outcome.result is not None
    assert outcome.result.metric_code == "BATCH_CONSTRAINED_QUANTITY"
    assert outcome.moq == 50
    assert outcome.lead_time_days == 14


def test_unavailable_velocity_with_moq_supplied_degrades_but_does_not_refuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_NO_SHIPPING)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(
        uuid4(), _base_request(lines=[_unclassified_cancelled_after_dispatch_line()])
    )

    assert captured_requests == []
    assert outcome.data_request_id is None
    assert outcome.velocity_status == "UNAVAILABLE"
    assert outcome.observed_units_sold is None
    assert outcome.velocity_unavailable_reason is not None
    assert outcome.result is not None


# --- Never-sold SKU, NEITHER moq NOR lead_time -> refused -------------------------------------


def test_never_sold_sku_with_no_moq_and_no_lead_time_raises_data_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_NO_MOQ_NO_LEAD_TIME)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request(lines=[]))

    assert outcome.result is None
    assert outcome.landed_cost_result is None
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["blocking_metric"] == "BATCH_CONSTRAINED_QUANTITY"
    reason = captured_requests[0]["reason"]
    assert "velocity" in reason.lower()
    assert "lead_time_days" in reason or "moq" in reason


def test_moq_alone_present_is_enough_to_proceed_without_data_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote_with_moq_only = {**_VALID_QUOTE_NO_MOQ_NO_LEAD_TIME, "moq": 20}
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(quote_with_moq_only)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request(lines=[]))

    assert captured_requests == []
    assert outcome.data_request_id is None
    assert outcome.result is not None


def test_lead_time_alone_present_is_enough_to_proceed_without_data_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote_with_lead_time_only = {**_VALID_QUOTE_NO_MOQ_NO_LEAD_TIME, "lead_time_days": 21}
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(quote_with_lead_time_only)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request(lines=[]))

    assert captured_requests == []
    assert outcome.data_request_id is None
    assert outcome.result is not None


# --- Expired batch.budget -----------------------------------------------------------------------


def test_expired_budget_raises_data_request_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    expired_budget = {"amount_paise": 50_00_00, "valid_until": "2020-01-01"}
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_WITH_SHIPPING)],
        budget_rows=[_budget_row(expired_budget)],
    )
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert outcome.result is None
    assert outcome.landed_cost_result is None
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["requested_field"] == "batch.budget"
    assert "expired" in captured_requests[0]["reason"].lower()
    # Nothing was ever persisted for an expired budget.
    assert _save_calls() == []


def test_budget_valid_until_equal_to_as_of_is_not_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    budget_expiring_today = {"amount_paise": 50_00_00, "valid_until": _AS_OF.isoformat()}
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_WITH_SHIPPING)],
        budget_rows=[_budget_row(budget_expiring_today)],
    )
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert captured_requests == []
    assert outcome.result is not None


# --- Zero / multiple supplier.quote rows (mirrors CP A4) ---------------------------------------


def test_zero_active_supplier_quotes_yields_data_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_adjustments(monkeypatch, quote_rows=[], budget_rows=[_budget_row(_VALID_BUDGET)])
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert outcome.result is None
    assert outcome.data_request_id is not None
    assert captured_requests[0]["requested_field"] == "supplier.quote"
    assert captured_requests[0]["blocking_metric"] == "BATCH_CONSTRAINED_QUANTITY"


def test_multiple_active_supplier_quotes_yields_data_request_never_picks_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _quote_row(_VALID_QUOTE_WITH_SHIPPING, row_id=uuid4()),
        _quote_row({**_VALID_QUOTE_WITH_SHIPPING, "unit_cost_paise": 200_00}, row_id=uuid4()),
    ]
    _stub_adjustments(monkeypatch, quote_rows=rows, budget_rows=[_budget_row(_VALID_BUDGET)])
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert outcome.result is None
    assert outcome.data_request_id is not None
    assert "2 ACTIVE" in captured_requests[0]["reason"]


# --- Zero / multiple batch.budget rows ----------------------------------------------------------


def test_zero_active_budgets_yields_data_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_adjustments(monkeypatch, quote_rows=[_quote_row(_VALID_QUOTE_WITH_SHIPPING)], budget_rows=[])
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert outcome.result is None
    assert outcome.data_request_id is not None
    assert captured_requests[0]["requested_field"] == "batch.budget"


def test_multiple_active_budgets_yields_data_request_never_picks_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _budget_row(_VALID_BUDGET, row_id=uuid4()),
        _budget_row({**_VALID_BUDGET, "amount_paise": 60_00_00}, row_id=uuid4()),
    ]
    _stub_adjustments(monkeypatch, quote_rows=[_quote_row(_VALID_QUOTE_WITH_SHIPPING)], budget_rows=rows)
    captured_requests = _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert outcome.result is None
    assert outcome.data_request_id is not None
    assert "2 ACTIVE" in captured_requests[0]["reason"]


# --- Malformed quote / budget propagate uncaught ------------------------------------------------


def test_malformed_quote_raises_value_error_uncaught(monkeypatch: pytest.MonkeyPatch) -> None:
    malformed = {"supplier_name": "Acme"}  # missing unit_cost_paise
    _stub_adjustments(monkeypatch, quote_rows=[_quote_row(malformed)], budget_rows=[_budget_row(_VALID_BUDGET)])

    with pytest.raises(ValueError, match="unit_cost_paise"):
        assemble_batch_size_estimate(uuid4(), _base_request())


def test_malformed_budget_raises_value_error_uncaught(monkeypatch: pytest.MonkeyPatch) -> None:
    malformed = {"valid_until": "2099-01-01"}  # missing amount_paise
    _stub_adjustments(
        monkeypatch, quote_rows=[_quote_row(_VALID_QUOTE_WITH_SHIPPING)], budget_rows=[_budget_row(malformed)]
    )

    with pytest.raises(ValueError, match="amount_paise"):
        assemble_batch_size_estimate(uuid4(), _base_request())


# --- Subtlety 1: reference-quantity/shipping-apportionment disclosure --------------------------


def test_reference_quantity_caveat_applies_when_shipping_paise_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_WITH_SHIPPING)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert outcome.reference_quantity_caveat_applies is True
    assert outcome.reference_quantity_caveat is not None
    assert "shipping" in outcome.reference_quantity_caveat.lower()
    assert "lower" in outcome.reference_quantity_caveat.lower()


def test_reference_quantity_caveat_does_not_apply_when_no_shipping_paise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_NO_SHIPPING)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert outcome.reference_quantity_caveat_applies is False
    assert outcome.reference_quantity_caveat is not None
    assert "does not apply" in outcome.reference_quantity_caveat.lower()

    # landed cost == unit_cost_paise exactly (no shipping to apportion at any quantity).
    assert outcome.landed_cost_result is not None
    assert outcome.landed_cost_result.value_paise == 100_00


def test_reference_quantity_is_one_when_no_moq_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    quote_no_moq = {"supplier_name": "Acme", "unit_cost_paise": 100_00, "shipping_paise": 100_00}
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(quote_no_moq)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    assert outcome.reference_quantity == 1
    assert outcome.reference_quantity_basis == "DEFAULT_ONE"
    # unit_cost_paise (100_00) + shipping_paise (100_00) / quantity (1) = 200_00
    assert outcome.landed_cost_result.value_paise == 200_00


# --- AC17f structural guardrail: no forecast/guarantee language ---------------------------------
#
# D9/§6.12's own "Never" row is itself worded "A demand forecast, a guaranteed sell-through, or
# a claim about future volume" — so the WORDS "forecast"/"guarantee"/"predict" legitimately
# appear in this checkpoint's own docstrings, stating exactly that prohibition (as this session's
# other checkpoints already do, e.g. `PricingCurveOutcome`'s own "never asserted as a single
# optimal price" pattern). A blanket substring ban would therefore fail on the very sentence
# required to disclose the constraint. This guardrail instead checks two structurally different
# things: (1) no FIELD NAME (an identifier a caller could read as an affirmative claim) contains
# a banned term at all, mirroring `test_cfo_actions_landed_cost.py`'s AC13 field-name check; and
# (2) every PROSE occurrence of a banned term is part of a negation (preceded within a short
# window by "never"/"not a"/"no "), i.e. the term is only ever used to state the prohibition,
# never to assert the thing itself.

_BANNED_TERMS = ("forecast", "guarantee", "will sell", "predict")
_NEGATION_MARKERS = ("never", "not a", "not an", "no ", "not ")


def _assert_only_negated_occurrences(text: str, *, where: str) -> None:
    lowered = text.lower()
    for term in _BANNED_TERMS:
        start = 0
        while True:
            idx = lowered.find(term, start)
            if idx == -1:
                break
            window = lowered[max(0, idx - 80) : idx]
            assert any(marker in window for marker in _NEGATION_MARKERS), (
                f"{where}: {term!r} appears without a negation marker nearby — "
                f"context: {lowered[max(0, idx - 80): idx + len(term) + 10]!r}"
            )
            start = idx + len(term)


def test_ac17f_no_affirmative_forecast_or_guarantee_field_names() -> None:
    """No field name on the new dataclasses, nor the composition function's own name, could be
    read as an affirmative forecast/guarantee claim (e.g. no `predicted_units_sold`,
    `guaranteed_quantity`, `forecast_result` field exists anywhere)."""
    for cls in (BatchSizeRequest, BatchSizeOutcome):
        for field in fields(cls):
            lowered_name = field.name.lower()
            for term in _BANNED_TERMS:
                assert term not in lowered_name, f"{cls.__name__}.{field.name} contains banned term {term!r}"

    assert "forecast" not in assemble_batch_size_estimate.__name__.lower()
    assert "predict" not in assemble_batch_size_estimate.__name__.lower()


def test_ac17f_every_prose_occurrence_of_banned_terms_is_a_negation() -> None:
    """Every place `forecast`/`guarantee`/`will sell`/`predict` appears in this checkpoint's own
    docstrings is part of stating the D9/§6.12 prohibition ("never a demand forecast..."), never
    an affirmative claim that this estimate forecasts or guarantees anything."""
    for cls in (BatchSizeRequest, BatchSizeOutcome):
        _assert_only_negated_occurrences(cls.__doc__ or "", where=cls.__name__)

    _assert_only_negated_occurrences(
        assemble_batch_size_estimate.__doc__ or "", where="assemble_batch_size_estimate"
    )


def test_ac17f_runtime_outcome_never_asserts_a_forecast_or_guarantee(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real computed outcome's own string fields (`velocity_unavailable_reason`,
    `reference_quantity_caveat`, and the underlying `MetricResult.calculation_basis`) never use
    an affirmative forecast/guarantee claim either — checked on an actual assembled outcome, not
    just static docstrings."""
    _stub_adjustments(
        monkeypatch,
        quote_rows=[_quote_row(_VALID_QUOTE_WITH_SHIPPING)],
        budget_rows=[_budget_row(_VALID_BUDGET)],
    )
    _stub_data_requests(monkeypatch)

    outcome = assemble_batch_size_estimate(uuid4(), _base_request())

    for text in (
        outcome.reference_quantity_caveat,
        outcome.result.calculation_basis if outcome.result else None,
        outcome.landed_cost_result.calculation_basis if outcome.landed_cost_result else None,
    ):
        if text is None:
            continue
        lowered = text.lower()
        for term in _BANNED_TERMS:
            assert term not in lowered, f"runtime outcome text unexpectedly contains {term!r}: {text!r}"
