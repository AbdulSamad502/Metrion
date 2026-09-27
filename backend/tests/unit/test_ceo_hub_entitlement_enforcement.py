"""F3 of the entitlement roadmap — `agents.ceo_hub`'s `dispatch_cfo_*` functions must actually
REFUSE to run their composition function when `resolve_cfo_entitlement` denies, not merely log
the denial on the `agent_run` row (F2 computed a real result; nothing enforced it until now).

True unit tests: `resolve_cfo_entitlement` and `agent_run_repo.insert_run`/`finish_run` are
monkeypatched (no real Postgres needed — that's the integration suite's job,
`test_entitlement.py`'s own pattern), and the underlying composition function is replaced with
a spy that fails the test if it is ever called. Covers 3 representative dispatch functions
(`dispatch_cfo_pnl`, `dispatch_cfo_pricing`, `dispatch_cfo_reconcile`) — the other 8 follow the
identical, mechanically-applied pattern (see `agents/ceo_hub.py` itself).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from backend.agents import ceo_hub
from backend.entitlement import EntitlementDenied, EntitlementResult

_OCCURRED_AT = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def _denied_result(*, meter_code: str) -> EntitlementResult:
    return EntitlementResult(
        passed=False,
        reason="OVER_CAP",
        meter_code=meter_code,
        usage_count=5,
        cap_value=5,
        evaluation_basis="OVER_CAP",
        denial_rendering="ERROR",
        reduced_payload_action_code=None,
        period_key="2026-09",
    )


class _FakeAgentRunRepo:
    """Records insert_run/finish_run calls without touching a real database."""

    def __init__(self) -> None:
        self.inserted: list[dict[str, object]] = []
        self.finished: list[dict[str, object]] = []
        self._run_id = uuid.uuid4()

    def insert_run(self, tenant_id, **kwargs):
        self.inserted.append({"tenant_id": tenant_id, **kwargs})
        return self._run_id

    def finish_run(self, tenant_id, run_id, **kwargs):
        self.finished.append({"tenant_id": tenant_id, "run_id": run_id, **kwargs})


def _never_call(*args, **kwargs):
    raise AssertionError("composition function must NOT be called when entitlement is denied")


def test_dispatch_cfo_pnl_refuses_to_run_when_entitlement_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_repo = _FakeAgentRunRepo()
    monkeypatch.setattr(ceo_hub, "resolve_cfo_entitlement", lambda *a, **k: _denied_result(meter_code="cfo.pnl"))
    monkeypatch.setattr(ceo_hub, "agent_run_repo", fake_repo)
    monkeypatch.setattr(ceo_hub, "compute_period_pnl", _never_call)

    tenant_id = uuid.uuid4()
    with pytest.raises(EntitlementDenied) as exc_info:
        ceo_hub.dispatch_cfo_pnl(
            tenant_id,
            requested_by=uuid.uuid4(),
            request=object(),  # never touched — compute_period_pnl is never called
            permission_check="PASS",
            now=_OCCURRED_AT,
        )

    assert exc_info.value.result.passed is False
    assert exc_info.value.result.reason == "OVER_CAP"
    assert len(fake_repo.inserted) == 1
    assert fake_repo.inserted[0]["entitlement_check"] == "DENIED"
    assert len(fake_repo.finished) == 1
    assert fake_repo.finished[0]["status"] == "FAILED"
    assert fake_repo.finished[0]["error_reason"] == "OVER_CAP"


def test_dispatch_cfo_pricing_refuses_to_run_when_entitlement_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_repo = _FakeAgentRunRepo()
    monkeypatch.setattr(ceo_hub, "resolve_cfo_entitlement", lambda *a, **k: _denied_result(meter_code="cfo.pricing"))
    monkeypatch.setattr(ceo_hub, "agent_run_repo", fake_repo)
    monkeypatch.setattr(ceo_hub, "compute_pricing_curve", _never_call)

    tenant_id = uuid.uuid4()
    with pytest.raises(EntitlementDenied):
        ceo_hub.dispatch_cfo_pricing(
            tenant_id,
            requested_by=uuid.uuid4(),
            request=object(),
            permission_check="PASS",
            now=_OCCURRED_AT,
        )

    assert len(fake_repo.inserted) == 1
    assert len(fake_repo.finished) == 1
    assert fake_repo.finished[0]["status"] == "FAILED"


def test_dispatch_cfo_reconcile_refuses_to_run_when_entitlement_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reconciliation dispatch is the one most directly writing money-touching
    `leak_finding` rows (D5) — proving it is refused, not merely logged, is the sharpest test
    of this task's actual requirement."""
    fake_repo = _FakeAgentRunRepo()
    monkeypatch.setattr(ceo_hub, "resolve_cfo_entitlement", lambda *a, **k: _denied_result(meter_code="cfo.reconcile"))
    monkeypatch.setattr(ceo_hub, "agent_run_repo", fake_repo)
    monkeypatch.setattr(ceo_hub, "run_leak_shield_reconciliation", _never_call)

    tenant_id = uuid.uuid4()
    with pytest.raises(EntitlementDenied):
        ceo_hub.dispatch_cfo_reconcile(
            tenant_id,
            requested_by=uuid.uuid4(),
            marketplace="AMAZON",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            as_of_date=date(2026, 9, 25),
            permission_check="PASS",
            now=_OCCURRED_AT,
        )

    assert len(fake_repo.inserted) == 1
    assert len(fake_repo.finished) == 1
    assert fake_repo.finished[0]["status"] == "FAILED"


def test_dispatch_cfo_enter_expense_refuses_to_run_when_entitlement_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second, differently-shaped dispatch function (no `request` dataclass, individual
    scalar params) — proving the pattern generalizes beyond the `request`-object shape."""
    fake_repo = _FakeAgentRunRepo()
    monkeypatch.setattr(
        ceo_hub, "resolve_cfo_entitlement", lambda *a, **k: _denied_result(meter_code="cfo.enter_expense")
    )
    monkeypatch.setattr(ceo_hub, "agent_run_repo", fake_repo)
    monkeypatch.setattr(ceo_hub, "enter_expense", _never_call)

    tenant_id = uuid.uuid4()
    with pytest.raises(EntitlementDenied):
        ceo_hub.dispatch_cfo_enter_expense(
            tenant_id,
            requested_by=uuid.uuid4(),
            target_type="SKU",
            target_ref="SKU-1",
            field="expense.packaging",
            value={"amount_paise": 100},
            reason=None,
            permission_check="PASS",
            now=_OCCURRED_AT,
        )

    assert len(fake_repo.inserted) == 1
    assert len(fake_repo.finished) == 1
    assert fake_repo.finished[0]["status"] == "FAILED"
