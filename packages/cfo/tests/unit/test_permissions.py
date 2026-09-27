"""`api/v1/cfo.py`'s expense-write route logic — the second, in-handler `FINANCIALS_ADJUST`
gate (§8 rule 4 / E19, twinkly-mapping-canyon.md judgment call 3). Exercised as a plain
function call against a constructed `AuthContext`, without a live FastAPI server/DB — the
route function itself is the unit under test, called directly.

OWNER always passes `FINANCIALS_ADJUST` (§5.2: implicit, unconditional). PARTNER without the
grant is denied (403-equivalent, E19/T11); PARTNER with the grant succeeds (T12).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

import backend.services.cfo_actions as cfo_actions_module
from backend.api.v1.cfo import EnterExpenseRequest, put_expense
from backend.auth.context import AuthContext
from backend.auth.permissions import FINANCIALS_ADJUST, OWNER_ROLE, PARTNER_ROLE, has_permission


def _ctx(*, role: str, permissions: dict[str, object]) -> AuthContext:
    return AuthContext(
        app_user_id=uuid4(),
        clerk_user_id="user_test",
        email_verified=True,
        tenant_id=uuid4(),
        membership_status="ACTIVE",
        role=role,
        permissions=permissions,
        onboarding_state="ACTIVE",
    )


def _body() -> EnterExpenseRequest:
    return EnterExpenseRequest(
        target_type="SKU",
        target_ref="SKU-1",
        field="expense.advertising",
        value={"amount_paise": 1000_00},
    )


@pytest.fixture(autouse=True)
def _stub_insert(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cfo_actions_module, "insert_adjustment", lambda tenant_id, **kwargs: uuid4())


def test_has_permission_owner_always_passes_regardless_of_grid() -> None:
    assert has_permission(role=OWNER_ROLE, permissions={}, key=FINANCIALS_ADJUST) is True


def test_has_permission_partner_without_grant_is_denied() -> None:
    assert has_permission(role=PARTNER_ROLE, permissions={}, key=FINANCIALS_ADJUST) is False


def test_has_permission_partner_with_grant_passes() -> None:
    assert has_permission(role=PARTNER_ROLE, permissions={FINANCIALS_ADJUST: True}, key=FINANCIALS_ADJUST) is True


def test_put_expense_owner_always_passes_the_second_gate() -> None:
    ctx = _ctx(role=OWNER_ROLE, permissions={})  # deny-all grid, but OWNER bypasses (§5.2)
    result = put_expense(_body(), ctx)
    assert "manualAdjustmentId" in result


def test_put_expense_partner_without_grant_is_denied_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """E19/T11: PARTNER lacking financials.adjust is denied even though `require_auth` only
    checked `agent.cfo` (the single permission passed to it at the route decorator) — this is
    the second, in-handler gate."""
    ctx = _ctx(role=PARTNER_ROLE, permissions={})  # no financials.adjust grant
    with pytest.raises(HTTPException) as exc_info:
        put_expense(_body(), ctx)
    assert exc_info.value.status_code == 403
    assert "financials.adjust" in exc_info.value.detail


def test_put_expense_partner_with_grant_succeeds() -> None:
    """T12."""
    ctx = _ctx(role=PARTNER_ROLE, permissions={FINANCIALS_ADJUST: True})
    result = put_expense(_body(), ctx)
    assert "manualAdjustmentId" in result


def test_put_expense_invalid_field_returns_400_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(role=OWNER_ROLE, permissions={})
    bad_body = EnterExpenseRequest(
        target_type="SKU", target_ref="SKU-1", field="not.a.real.field", value={"amount_paise": 1}
    )
    with pytest.raises(HTTPException) as exc_info:
        put_expense(bad_body, ctx)
    assert exc_info.value.status_code == 400
