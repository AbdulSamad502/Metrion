"""`backend.services.cfo_actions.list_expenses` / `set_expense_budget` /
`check_expense_budget` — the two additive expense-tracking gaps closed alongside the existing,
unchanged `enter_expense` write path (`test_cfo_actions_expense.py`).

`manual_adjustment_repo.active_adjustments_by_field` / `active_adjustments_for_target` /
`insert_adjustment` all open a real DB connection — no live Postgres in this session, so each is
monkeypatched to a fake returning canned rows / recording its call, mirroring
`test_cfo_actions_expense.py`'s own `_capture_insert` pattern exactly.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    EnterExpenseBudgetRequest,
    check_expense_budget,
    list_expenses,
    set_expense_budget,
)


def _row(
    *,
    row_id: UUID,
    target_type: str,
    target_ref: str,
    field: str,
    value: dict[str, object],
    created_by: UUID,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "id": row_id,
        "target_type": target_type,
        "target_ref": target_ref,
        "field": field,
        "value": value,
        "reason": None,
        "created_by": created_by,
        "created_at": created_at,
        "supersedes_id": None,
        "status": "ACTIVE",
    }


# ---------------------------------------------------------------------------------------
# Feature 1: list_expenses
# ---------------------------------------------------------------------------------------


def test_list_expenses_filters_by_category(monkeypatch: pytest.MonkeyPatch) -> None:
    created_by = uuid4()
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    packaging_row = _row(
        row_id=uuid4(),
        target_type="PERIOD",
        target_ref="2026-09",
        field="expense.packaging",
        value={"amount_paise": 5_000},
        created_by=created_by,
        created_at=now,
    )

    def _fake(tenant_id, *, field=None, field_prefix=None):
        assert field == "expense.packaging"
        return [packaging_row]

    monkeypatch.setattr(cfo_actions_module.manual_adjustment_repo, "active_adjustments_by_field", _fake)

    outcome = list_expenses(uuid4(), category="packaging")

    assert len(outcome.entries) == 1
    assert outcome.entries[0].category == "packaging"
    assert outcome.entries[0].amount_paise.value == 5_000
    assert outcome.total_paise.value == 5_000


def test_list_expenses_excludes_expense_budget_rows_from_prefix_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    created_by = uuid4()
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    rows = [
        _row(
            row_id=uuid4(),
            target_type="PERIOD",
            target_ref="2026-09",
            field="expense.advertising",
            value={"amount_paise": 9_000},
            created_by=created_by,
            created_at=now,
        ),
        _row(
            row_id=uuid4(),
            target_type="ACCOUNT",
            target_ref="acct-1",
            field="expense.budget",
            value={
                "category": "advertising",
                "amount_paise": 100_000,
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
            },
            created_by=created_by,
            created_at=now,
        ),
    ]

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_by_field",
        lambda tenant_id, *, field=None, field_prefix=None: rows,
    )

    outcome = list_expenses(uuid4())

    assert len(outcome.entries) == 1
    assert outcome.entries[0].category == "advertising"
    assert outcome.total_paise.value == 9_000


def test_list_expenses_filters_by_period_using_month_target_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    created_by = uuid4()
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    september_row = _row(
        row_id=uuid4(),
        target_type="PERIOD",
        target_ref="2026-09",
        field="expense.other",
        value={"amount_paise": 1_000},
        created_by=created_by,
        created_at=now,
    )
    october_row = _row(
        row_id=uuid4(),
        target_type="PERIOD",
        target_ref="2026-10",
        field="expense.other",
        value={"amount_paise": 2_000},
        created_by=created_by,
        created_at=now,
    )

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_by_field",
        lambda tenant_id, *, field=None, field_prefix=None: [september_row, october_row],
    )

    outcome = list_expenses(
        uuid4(), category="other", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)
    )

    assert len(outcome.entries) == 1
    assert outcome.entries[0].target_ref == "2026-09"
    assert outcome.total_paise.value == 1_000


def test_list_expenses_excludes_rows_with_unrecoverable_period_when_period_filter_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_by = uuid4()
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    account_row = _row(
        row_id=uuid4(),
        target_type="ACCOUNT",
        target_ref="acct-1",
        field="expense.other",
        value={"amount_paise": 3_000},
        created_by=created_by,
        created_at=now,
    )

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_by_field",
        lambda tenant_id, *, field=None, field_prefix=None: [account_row],
    )

    outcome = list_expenses(
        uuid4(), category="other", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)
    )

    assert outcome.entries == []
    assert outcome.total_paise.value == 0


def test_list_expenses_total_paise_is_a_real_sum_not_fabricated(monkeypatch: pytest.MonkeyPatch) -> None:
    created_by = uuid4()
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    rows = [
        _row(
            row_id=uuid4(),
            target_type="PERIOD",
            target_ref="2026-09",
            field="expense.other",
            value={"amount_paise": amount},
            created_by=created_by,
            created_at=now,
        )
        for amount in (1_000, 2_500, 3_300)
    ]

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_by_field",
        lambda tenant_id, *, field=None, field_prefix=None: rows,
    )

    outcome = list_expenses(uuid4(), category="other")

    assert outcome.total_paise.value == 1_000 + 2_500 + 3_300


def test_list_expenses_rejects_unknown_category() -> None:
    with pytest.raises(ValueError, match="not a real expense category"):
        list_expenses(uuid4(), category="made_up")


# ---------------------------------------------------------------------------------------
# Feature 2: set_expense_budget / check_expense_budget
# ---------------------------------------------------------------------------------------


def test_set_expense_budget_writes_a_real_manual_adjustment_row(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def _fake_insert(tenant_id, **kwargs):
        calls.append({"tenant_id": tenant_id, **kwargs})
        return uuid4()

    monkeypatch.setattr(cfo_actions_module, "insert_adjustment", _fake_insert)

    tenant_id = uuid4()
    created_by = uuid4()
    result_id = set_expense_budget(
        tenant_id,
        EnterExpenseBudgetRequest(
            category="packaging",
            amount_paise=500_000,
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            created_by=created_by,
        ),
    )

    assert result_id is not None
    assert len(calls) == 1
    call = calls[0]
    assert call["target_type"] == "ACCOUNT"
    assert call["target_ref"] == str(tenant_id)
    assert call["field"] == "expense.budget"
    assert call["value"] == {
        "category": "packaging",
        "amount_paise": 500_000,
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
    }


def test_set_expense_budget_rejects_unknown_category(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfo_actions_module, "insert_adjustment", lambda *a, **k: uuid4())
    with pytest.raises(ValueError, match="not a real expense category"):
        set_expense_budget(
            uuid4(),
            EnterExpenseBudgetRequest(
                category="made_up",
                amount_paise=500_000,
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 30),
                created_by=uuid4(),
            ),
        )


def test_check_expense_budget_flags_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    created_by = uuid4()
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    budget_row = _row(
        row_id=uuid4(),
        target_type="ACCOUNT",
        target_ref=str(tenant_id),
        field="expense.budget",
        value={
            "category": "packaging",
            "amount_paise": 5_000,
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
        },
        created_by=created_by,
        created_at=now,
    )
    spend_row = _row(
        row_id=uuid4(),
        target_type="PERIOD",
        target_ref="2026-09",
        field="expense.packaging",
        value={"amount_paise": 6_500},
        created_by=created_by,
        created_at=now,
    )

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda tenant_id, *, target_type, target_ref, field: [budget_row],
    )
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_by_field",
        lambda tenant_id, *, field=None, field_prefix=None: [spend_row],
    )

    status = check_expense_budget(
        tenant_id, category="packaging", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)
    )

    assert status.no_budget_set is False
    assert status.budget_paise.value == 5_000
    assert status.spent_paise.value == 6_500
    assert status.exceeded is True
    assert status.remaining_paise.value == -1_500  # real overage, never floored to zero


def test_check_expense_budget_under_budget_not_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    created_by = uuid4()
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    budget_row = _row(
        row_id=uuid4(),
        target_type="ACCOUNT",
        target_ref=str(tenant_id),
        field="expense.budget",
        value={
            "category": "packaging",
            "amount_paise": 5_000,
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
        },
        created_by=created_by,
        created_at=now,
    )
    spend_row = _row(
        row_id=uuid4(),
        target_type="PERIOD",
        target_ref="2026-09",
        field="expense.packaging",
        value={"amount_paise": 2_000},
        created_by=created_by,
        created_at=now,
    )

    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda tenant_id, *, target_type, target_ref, field: [budget_row],
    )
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_by_field",
        lambda tenant_id, *, field=None, field_prefix=None: [spend_row],
    )

    status = check_expense_budget(
        tenant_id, category="packaging", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)
    )

    assert status.exceeded is False
    assert status.remaining_paise.value == 3_000


def test_check_expense_budget_no_budget_set_is_a_real_distinguished_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda tenant_id, *, target_type, target_ref, field: [],
    )
    monkeypatch.setattr(
        cfo_actions_module.manual_adjustment_repo,
        "active_adjustments_by_field",
        lambda tenant_id, *, field=None, field_prefix=None: [],
    )

    status = check_expense_budget(
        uuid4(), category="packaging", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)
    )

    assert status.no_budget_set is True
    assert status.budget_paise is None
    assert status.remaining_paise is None
    assert status.exceeded is False  # never a silent pass being confused with "under budget"
