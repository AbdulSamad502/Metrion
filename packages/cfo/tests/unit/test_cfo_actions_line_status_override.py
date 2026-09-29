"""`backend.services.cfo_actions.declare_line_status_override` / `get_line_status_overrides` —
deterministic-engine.md §7.2.1's `cancellation_state_override`/`return_status_override`/
`rto_status_override`, added to close the CFO end-to-end evaluation's headline finding
(docs/evaluation/cfo-e2e-evaluation-mtr-mock-2026-09-27.md §1/§3/§4/§11): real MTR files with
no resolvable cancellation/return/RTO status at all.

`manual_adjustment_repo.insert_adjustment`/`active_adjustments_for_target` both open a real DB
connection — no live Postgres in this session, so each is monkeypatched, mirroring
`test_cfo_actions_expense.py`'s own `_capture_insert` pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    DeclareLineCountOverrideRequest,
    DeclareLineStatusOverrideRequest,
    declare_line_count_override,
    declare_line_status_override,
    get_line_status_overrides,
)


@pytest.fixture
def _capture_insert(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def _fake_insert(tenant_id, **kwargs):
        calls.append({"tenant_id": tenant_id, **kwargs})
        return uuid4()

    monkeypatch.setattr(cfo_actions_module, "insert_adjustment", _fake_insert)
    return calls


# --- declare_line_status_override -------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("cancellation_state_override", "CANCELLED"),
        ("cancellation_state_override", "NOT_CANCELLED"),
        ("return_status_override", "RETURNED"),
        ("return_status_override", "NOT_RETURNED"),
        ("rto_status_override", "RTO"),
        ("rto_status_override", "NOT_RTO"),
    ],
)
def test_every_real_field_and_value_is_accepted(
    field: str, value: str, _capture_insert: list[dict[str, object]]
) -> None:
    tenant_id = uuid4()
    created_by = uuid4()
    sales_line_id = uuid4()
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)

    result_id = declare_line_status_override(
        tenant_id,
        DeclareLineStatusOverrideRequest(
            sales_line_id=sales_line_id,
            field=field,
            value=value,
            created_by=created_by,
            reason="seller confirmed via WhatsApp support",
            now=now,
        ),
    )

    assert result_id is not None
    assert len(_capture_insert) == 1
    call = _capture_insert[0]
    assert call["tenant_id"] == tenant_id
    assert call["target_type"] == "LINE"
    assert call["target_ref"] == str(sales_line_id)
    assert call["field"] == field
    assert call["value"] == value
    assert call["reason"] == "seller confirmed via WhatsApp support"


def test_unknown_field_raises_value_error_not_silently_accepted(
    _capture_insert: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError, match="not one of"):
        declare_line_status_override(
            uuid4(),
            DeclareLineStatusOverrideRequest(
                sales_line_id=uuid4(),
                field="rto_outcome",  # a real §7.2.1 field, but not one of THIS trio
                value="RECOVERED_SELLABLE",
                created_by=uuid4(),
            ),
        )
    assert _capture_insert == []


def test_invalid_value_for_a_real_field_raises_value_error_not_silently_accepted(
    _capture_insert: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError, match="not a valid value"):
        declare_line_status_override(
            uuid4(),
            DeclareLineStatusOverrideRequest(
                sales_line_id=uuid4(),
                field="rto_status_override",
                value="MAYBE",  # not in {"RTO", "NOT_RTO"}
                created_by=uuid4(),
            ),
        )
    assert _capture_insert == []


# --- declare_line_count_override --------------------------------------------------------------


@pytest.mark.parametrize("field", ["returned_qty_override", "rto_qty_override"])
def test_count_override_accepts_a_non_negative_integer(field: str, _capture_insert: list[dict[str, object]]) -> None:
    tenant_id = uuid4()
    sales_line_id = uuid4()

    result_id = declare_line_count_override(
        tenant_id,
        DeclareLineCountOverrideRequest(sales_line_id=sales_line_id, field=field, value=3, created_by=uuid4()),
    )

    assert result_id is not None
    call = _capture_insert[0]
    assert call["target_type"] == "LINE"
    assert call["target_ref"] == str(sales_line_id)
    assert call["field"] == field
    assert call["value"] == 3


def test_count_override_unknown_field_raises(_capture_insert: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError, match="not one of"):
        declare_line_count_override(
            uuid4(),
            DeclareLineCountOverrideRequest(sales_line_id=uuid4(), field="quantity", value=1, created_by=uuid4()),
        )
    assert _capture_insert == []


@pytest.mark.parametrize("bad_value", [-1, True, "3"])
def test_count_override_rejects_negative_bool_or_non_int_value(
    bad_value: object, _capture_insert: list[dict[str, object]]
) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        declare_line_count_override(
            uuid4(),
            DeclareLineCountOverrideRequest(
                sales_line_id=uuid4(), field="returned_qty_override", value=bad_value, created_by=uuid4()  # type: ignore[arg-type]
            ),
        )
    assert _capture_insert == []


# --- get_line_status_overrides ----------------------------------------------------------------


def test_reads_back_active_rows_for_each_field(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    sales_line_id = uuid4()

    def _fake_active_for_target(tid, *, target_type, target_ref, field):
        assert tid == tenant_id
        assert target_type == "LINE"
        assert target_ref == str(sales_line_id)
        if field == "cancellation_state_override":
            return [{"value": "CANCELLED"}]
        if field == "rto_status_override":
            return [{"value": "RTO"}]
        if field == "returned_qty_override":
            return [{"value": 2}]
        return []  # return_status_override/rto_qty_override: no ACTIVE row

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo, "active_adjustments_for_target", _fake_active_for_target
    )

    overrides = get_line_status_overrides(tenant_id, sales_line_id=sales_line_id)

    assert overrides.cancellation_state_override == "CANCELLED"
    assert overrides.return_status_override is None
    assert overrides.rto_status_override == "RTO"
    assert overrides.returned_qty_override == 2
    assert overrides.rto_qty_override is None


def test_no_active_rows_at_all_returns_all_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda *a, **k: [],
    )

    overrides = get_line_status_overrides(uuid4(), sales_line_id=uuid4())

    assert overrides.cancellation_state_override is None
    assert overrides.return_status_override is None
    assert overrides.rto_status_override is None


def test_seller_goal_round_trips(monkeypatch: pytest.MonkeyPatch, _capture_insert: list[dict[str, object]]) -> None:
    from backend.services.cfo_actions import get_seller_goal, set_seller_goal

    tenant_id = uuid4()
    monkeypatch.setattr(cfo_actions_module.manual_adjustment_repo, "active_adjustments_for_target", lambda *a, **k: [])
    set_seller_goal(
        tenant_id, target_margin_pct="15.00", priority_category="reduce_fees", note="Q4 push",
        created_by=uuid4(),
    )
    assert _capture_insert[0]["field"] == "seller.goal"
    assert _capture_insert[0]["value"]["target_margin_pct"] == "15.00"

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo, "active_adjustments_for_target",
        lambda *a, **k: [{"id": uuid4(), "value": {"target_margin_pct": "15.00", "priority_category": "reduce_fees", "note": "Q4 push"}}],
    )
    goal = get_seller_goal(tenant_id)
    assert goal is not None
    assert goal.target_margin_pct == "15.00"


def test_no_seller_goal_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.cfo_actions import get_seller_goal

    monkeypatch.setattr(cfo_actions_module.manual_adjustment_repo, "active_adjustments_for_target", lambda *a, **k: [])
    assert get_seller_goal(uuid4()) is None
