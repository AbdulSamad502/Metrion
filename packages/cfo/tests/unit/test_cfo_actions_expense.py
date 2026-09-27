"""`backend.services.cfo_actions.enter_expense` — cfo-agent.md §7.2.1 field registry, AC11.

`manual_adjustment_repo.insert_adjustment` (imported into `cfo_actions` as `insert_adjustment`)
opens a real DB connection — no live Postgres in this session, so it is monkeypatched to a
fake that records its call and returns a UUID, letting these tests assert on the write it
would have made without needing a live database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import enter_expense


@pytest.fixture
def _capture_insert(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def _fake_insert(tenant_id, **kwargs):
        calls.append({"tenant_id": tenant_id, **kwargs})
        return uuid4()

    monkeypatch.setattr(cfo_actions_module, "insert_adjustment", _fake_insert)
    return calls


def test_accepted_field_writes_a_real_manual_adjustment_row(_capture_insert: list[dict[str, object]]) -> None:
    tenant_id = uuid4()
    created_by = uuid4()
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)

    result_id = enter_expense(
        tenant_id,
        target_type="SKU",
        target_ref="SKU-1",
        field="expense.advertising",
        value={"amount_paise": 5000_00},
        created_by=created_by,
        reason="Q3 ad spend",
        now=now,
    )

    assert result_id is not None
    assert len(_capture_insert) == 1
    call = _capture_insert[0]
    assert call["tenant_id"] == tenant_id
    assert call["target_type"] == "SKU"
    assert call["target_ref"] == "SKU-1"
    assert call["field"] == "expense.advertising"
    assert call["value"] == {"amount_paise": 5000_00}
    assert call["created_by"] == created_by
    assert call["reason"] == "Q3 ad spend"
    assert call["created_at"] == now


@pytest.mark.parametrize(
    "field",
    [
        "cogs_per_unit",
        "expense.advertising",
        "expense.packaging",
        "expense.storage",
        "expense.logistics",
        "expense.other",
        "settlement.receipt",
        "supplier.quote",
        "batch.budget",
    ],
)
def test_every_registry_field_is_accepted(field: str, _capture_insert: list[dict[str, object]]) -> None:
    enter_expense(
        uuid4(),
        target_type="ACCOUNT",
        target_ref="acct-1",
        field=field,
        value={"amount_paise": 1},
        created_by=uuid4(),
    )
    assert len(_capture_insert) == 1


def test_field_outside_registry_raises_value_error_not_silently_accepted(
    _capture_insert: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError, match="not in the engine"):
        enter_expense(
            uuid4(),
            target_type="SKU",
            target_ref="SKU-1",
            field="expense.made_up_field",
            value={"amount_paise": 100},
            created_by=uuid4(),
        )
    # No write was attempted for the rejected field.
    assert _capture_insert == []
