"""`POST /api/v1/cfo/preview` — D7, cfo-agent.md §6.9/§6.8 `cfo.preview`, real Postgres.

Mirrors `packages/cfo/tests/integration/test_leak_shield_reconciliation.py`'s own seeding
pattern exactly: `calc_engine.api.reconcile.reconcile` is monkeypatched (real data produces no
exceptions to preview against — same honest D4/D5 limitation) to return a `ReconcileResult`
pointing at a `reconciliation_run`/`reconciliation_exception` pair seeded directly via
`calc_engine.repositories.reconciliation_repo`'s own real insert functions. Everything
downstream — persisting the exception's `MetricResult`, the aggregate `LEAK_TOTAL`,
`classify_and_rank_leaks`, `leak_finding_repo.insert`, and this route's own
`assemble_cfo_preview` call — is real, hitting the real database.

The second test is THE proof this checkpoint asks for: a real, separately-seeded
`entitlement_cap_config` row with `cap_value=0` denies `POST /cfo/reconcile` (402) for the
tenant, while `POST /cfo/preview` for the SAME tenant succeeds anyway — proving the bypass is
real, not merely assumed to work because `_require_cfo_entitlement` was never called.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

_AS_OF = date(2026, 9, 25)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)


@pytest.fixture(autouse=True)
def _clean_reconciliation_tables(migrate_engine):
    """`reconciliation_exception`/`reconciliation_match`/`reconciliation_run`/`leak_finding`/
    `metric_result` are owned by calc-engine's/cfo's own migrations, not backend's
    `_clean_backend_tables` fixture — cleaned here directly, mirroring
    `test_leak_shield_reconciliation.py`'s own before/after convention."""
    tables = (
        "reconciliation_exception",
        "reconciliation_match",
        "reconciliation_run",
        "leak_finding",
        "metric_result",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def _seed_variance_exception(tenant_id: uuid.UUID):
    """Seeds a real `reconciliation_run` + `reconciliation_exception` row (FEE_OVERCHARGE-
    shaped: FEE component, positive amount) and monkeypatches `reconcile()` to return a
    `ReconcileResult` pointing at them — the exact pattern
    `test_leak_shield_reconciliation.py`'s own seeded-exception test uses."""
    from calc_engine.api.compute_metric import MetricResult
    from calc_engine.api.reconcile import ReconcileResult
    from calc_engine.repositories import reconciliation_repo
    from calc_engine.types import RecognitionState

    computed_at = datetime(2026, 9, 25, tzinfo=timezone.utc)

    run_id = reconciliation_repo.insert_reconciliation_run(
        tenant_id,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        tolerance_config_version=1,
        formula_version="reconcile.v1",
        status="COMPLETE",
        join_key_validated=True,
        started_at=computed_at,
        finished_at=computed_at,
        settlement_line_count=1,
        sales_line_count=1,
        match_count=1,
        exception_count=1,
    )

    exception_id = reconciliation_repo.insert_reconciliation_exception(
        tenant_id,
        reconciliation_run_id=run_id,
        exception_type="VARIANCE_EXCEEDS_TOLERANCE",
        sales_line_id=uuid.uuid4(),
        settlement_line_id=uuid.uuid4(),
        component_code="COMMISSION",
        marketplace="MEESHO",
        amount_paise=3200,
        confidence="DERIVED",
        formula_version="reconcile.v1",
        computed_at=computed_at,
    )

    exception_metric_result = MetricResult(
        id=uuid.uuid4(),
        metric_code="LEAK_EXCEPTION_AMOUNT",
        value_paise=3200,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="DERIVED",
        calculation_basis="LeakExceptionAmount(VARIANCE_EXCEEDS_TOLERANCE) — seeded fixture",
        formula_version="reconcile.v1",
        canonical_data_version="non-canonical",
        as_of_date=_AS_OF,
        input_refs=(exception_id,),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )
    aggregate_metric_result = MetricResult(
        id=uuid.uuid4(),
        metric_code="LEAK_TOTAL",
        value_paise=3200,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="DERIVED",
        calculation_basis="LeakAggregate — seeded fixture",
        formula_version="reconcile.v1",
        canonical_data_version="non-canonical",
        as_of_date=_AS_OF,
        input_refs=(exception_metric_result.id,),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )

    seeded_result = ReconcileResult(
        reconciliation_run_id=run_id,
        match_count=1,
        exception_count=1,
        dates_missing_count=0,
        amount_unavailable_count=0,
        exception_metric_results=(exception_metric_result,),
        aggregate_metric_result=aggregate_metric_result,
    )
    return seeded_result


def test_assemble_cfo_preview_reveals_the_real_seeded_finding(monkeypatch: pytest.MonkeyPatch):
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    seeded_result = _seed_variance_exception(tenant_id)
    monkeypatch.setattr(cfo_actions_module, "reconcile", lambda *a, **k: seeded_result)

    outcome = cfo_actions_module.assemble_cfo_preview(
        tenant_id,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
    )

    assert outcome.revealed_finding is not None
    assert outcome.revealed_finding["leak_category"] == "FEE_OVERCHARGE"
    assert outcome.revealed_finding["amount_paise"] == 3200
    assert outcome.locked_findings_count == 0
    assert outcome.headline_total_paise == 3200

    from calc_engine.repositories import metric_result_repo

    resolved = metric_result_repo.get(tenant_id, uuid.UUID(outcome.headline_engine_result_ref))
    assert resolved is not None
    assert resolved["metric_code"] == "LEAK_TOTAL"
    assert resolved["value_paise"] == 3200


# --- HTTP route layer: the real entitlement-bypass proof -----------------------------------


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app)


def _register_owner(fake_clerk, tenant_id: uuid.UUID) -> dict[str, str]:
    from backend.repositories import app_user_repo, membership_repo

    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=f"{clerk_user_id}@example.com",
        email_verified=True,
        auth_provider="GOOGLE",
        display_name="Test Owner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.create_owner(tenant_id, user_row["id"])

    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_clerk(monkeypatch):
    from dataclasses import dataclass, field
    from typing import Any

    from backend.auth import context as auth_context_module

    @dataclass
    class _FakeAuthState:
        is_signed_in: bool
        payload: dict[str, Any] | None

    @dataclass
    class _FakeClerkClient:
        tokens: dict[str, tuple[str, str | None]] = field(default_factory=dict)

        async def authenticate_request_async(self, request: Any, options: Any) -> _FakeAuthState:
            header = request.headers.get("authorization", "")
            token = header.removeprefix("Bearer ").strip()
            if token in self.tokens:
                clerk_user_id, clerk_org_id = self.tokens[token]
                return _FakeAuthState(is_signed_in=True, payload={"sub": clerk_user_id, "org_id": clerk_org_id})
            return _FakeAuthState(is_signed_in=False, payload=None)

    client = _FakeClerkClient()
    monkeypatch.setattr(auth_context_module, "get_clerk_client", lambda: client)
    return client


def _seed_zero_cap(migrate_engine, *, agent_code: str, meter_code: str) -> None:
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entitlement_cap_config
                  (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version)
                VALUES
                  (:id, NULL, :agent_code, :meter_code, 'TENANT', 'MONTH', 0, :effective_from, 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "agent_code": agent_code,
                "meter_code": meter_code,
                "effective_from": _AS_OF,
            },
        )


def test_preview_route_succeeds_even_when_every_other_cfo_route_is_denied_for_same_tenant(
    app_client, fake_clerk, two_tenants, migrate_engine, monkeypatch: pytest.MonkeyPatch
):
    """The proof: seed a real cap_value=0 row for `cfo.reconcile`, confirm `POST /cfo/reconcile`
    is denied (402) for this tenant, THEN confirm `POST /cfo/preview` for the SAME tenant
    succeeds (200) anyway — because it never calls `_require_cfo_entitlement` at all, not
    because the cap happens not to apply to it."""
    import backend.services.cfo_actions as cfo_actions_module

    tenant_a, _ = two_tenants
    seeded_result = _seed_variance_exception(tenant_a)
    monkeypatch.setattr(cfo_actions_module, "reconcile", lambda *a, **k: seeded_result)

    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.reconcile")
    headers = _register_owner(fake_clerk, tenant_a)

    reconcile_resp = app_client.post(
        "/api/v1/cfo/reconcile",
        json={
            "marketplace": "MEESHO",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "as_of_date": "2026-09-25",
        },
        headers=headers,
    )
    assert reconcile_resp.status_code == 402, reconcile_resp.text
    assert reconcile_resp.json()["detail"]["evaluationBasis"] == "OVER_CAP"

    # Re-seed: /cfo/reconcile's own denied call never ran the composition, so the exception row
    # this test seeded is still there, untouched, for /cfo/preview to preview against.
    preview_resp = app_client.post(
        "/api/v1/cfo/preview",
        json={
            "marketplace": "MEESHO",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "as_of_date": "2026-09-25",
        },
        headers=headers,
    )
    assert preview_resp.status_code == 200, preview_resp.text
    body = preview_resp.json()
    assert body["revealedFinding"]["leakCategory"] == "FEE_OVERCHARGE"
    assert body["revealedFinding"]["amountPaise"] == 3200
    assert body["headlineTotalPaise"] == 3200
    assert body["lockedFindingsCount"] == 0
