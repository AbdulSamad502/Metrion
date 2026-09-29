"""`POST /api/v1/cfo/funding-readiness` — `cashConversionTiming`, real Postgres end-to-end.

Closes the gap: `assemble_funding_readiness_reduced` now fetches real, already-persisted
`SETTLEMENT_LAG_DAYS` rows (anomaly-detection.md §6.1/§6.6) instead of leaving cash-conversion
timing permanently deferred. This file proves the FULL real path: seed a matched
(sales_line, settlement_line) pair -> `POST /cfo/preview` runs real `reconcile()` and persists a
real `SETTLEMENT_LAG_DAYS` row (`run_leak_shield_reconciliation`'s own established behaviour,
unchanged by this checkpoint) -> `POST /cfo/funding-readiness` for the SAME period picks that row
up and removes `cash_conversion_timing` from `deferredSections`. No new arithmetic anywhere in
this checkpoint's own code — this is a real composition proof, not a mocked shortcut.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pytest
from sqlalchemy import text

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)
_AS_OF = date(2026, 1, 20)


@pytest.fixture(autouse=True)
def _clean_tables(migrate_engine):
    tables = (
        "reconciliation_exception",
        "reconciliation_match",
        "reconciliation_run",
        "metric_result",
        "leak_finding",
        "line_component",
        "sales_line",
        "settlement_line",
        "ingestion_run",
        "report_file",
        "reconciliation_tolerance_config",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def _insert_report_file_and_run(tenant_id: uuid.UUID, *, marketplace: str) -> uuid.UUID:
    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

    file_id = uuid.uuid4()
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_file
                    (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                     byte_size, storage_uri, uploaded_by, uploaded_at)
                VALUES
                    (:id, :tenant_id, :marketplace, 'SETTLEMENT', :sha, 'synthetic.xlsx', 100,
                     's3://bucket/x', :uploaded_by, :uploaded_at)
                """
            ),
            {
                "id": str(file_id),
                "tenant_id": str(tenant_id),
                "marketplace": marketplace,
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                "uploaded_by": str(uuid.uuid4()),
                "uploaded_at": datetime.now(timezone.utc),
            },
        )
    return ingestion_run_repo.insert_ingestion_run(
        tenant_id,
        report_file_id=file_id,
        adapter_id="meesho.synthetic.v1",
        adapter_version="v1",
        started_at=datetime.now(timezone.utc),
    )


def _insert_sales_line(tenant_id: uuid.UUID, *, ingestion_run_id: uuid.UUID, order_ref: str, line_ref: str) -> uuid.UUID:
    from data_foundation.repositories import sales_line_repo

    return sales_line_repo.insert_sales_line(
        tenant_id,
        ingestion_run_id=ingestion_run_id,
        marketplace="MEESHO",
        canonical_fields={"order_ref": order_ref, "line_ref": line_ref, "order_date": date(2026, 1, 10)},
        source_row_number=1,
        source_row_json={},
        confidence="VERIFIED",
    )


def _insert_settlement_line(tenant_id: uuid.UUID, *, ingestion_run_id: uuid.UUID, line_ref: str) -> uuid.UUID:
    from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

    settlement_line_id = uuid.uuid4()
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO settlement_line
                    (id, tenant_id, ingestion_run_id, marketplace, order_ref, line_ref,
                     settlement_id, gross_settlement_amount, currency, settlement_date,
                     document_type, source_row_number, source_row_json, confidence)
                VALUES
                    (:id, :tenant_id, :ingestion_run_id, 'MEESHO', NULL, :line_ref,
                     NULL, 5000, 'INR', :settlement_date, 'SETTLEMENT', 1, '{}'::jsonb, 'VERIFIED')
                """
            ),
            {
                "id": str(settlement_line_id),
                "tenant_id": str(tenant_id),
                "ingestion_run_id": str(ingestion_run_id),
                "line_ref": line_ref,
                "settlement_date": date(2026, 1, 15),
            },
        )
    return settlement_line_id


def _insert_tolerance(tenant_id: uuid.UUID) -> None:
    from calc_engine.repositories.tenant_context import tenant_scope as engine_tenant_scope

    with engine_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_tolerance_config
                    (id, tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps,
                     settlement_lag_days, grace_period_days, effective_from, version)
                VALUES
                    (:id, NULL, 'MEESHO', :component_code, 0, 100000, 90, 30, '2026-01-01', 1)
                """
            ),
            {"id": str(uuid.uuid4()), "component_code": "*"},
        )
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_tolerance_config
                    (id, tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps,
                     settlement_lag_days, grace_period_days, effective_from, version)
                VALUES
                    (:id, NULL, 'MEESHO', 'COMMISSION', 0, 100000, 90, 30, '2026-01-01', 1)
                """
            ),
            {"id": str(uuid.uuid4())},
        )


def _insert_matching_components(tenant_id: uuid.UUID, *, sales_line_id: uuid.UUID, settlement_line_id: uuid.UUID) -> None:
    """`reconcile()`'s Path A only inserts a `reconciliation_match` row for a `component_code`
    present on BOTH the invoice and settlement side of a matched pair (Decision A) — real
    `settlement_lag_pairs_for_run` data needs at least one such match to exist, so this seeds one
    shared, within-tolerance COMMISSION component on both sides."""
    from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, :sales_line_id, NULL, 'FEE', 'COMMISSION', 'INVOICE', 500,
                     NULL, NULL, 'synthetic', false, NULL)
                """
            ),
            {"id": str(uuid.uuid4()), "tenant_id": str(tenant_id), "sales_line_id": str(sales_line_id)},
        )
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, NULL, :settlement_line_id, 'FEE', 'COMMISSION', 'SETTLEMENT', 500,
                     NULL, NULL, 'synthetic', false, NULL)
                """
            ),
            {"id": str(uuid.uuid4()), "tenant_id": str(tenant_id), "settlement_line_id": str(settlement_line_id)},
        )


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app)


@pytest.fixture
def fake_clerk(monkeypatch):
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


def test_funding_readiness_surfaces_real_cash_conversion_timing_after_a_preview_run(
    app_client, fake_clerk, two_tenants
):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    run_id = _insert_report_file_and_run(tenant_a, marketplace="MEESHO")
    sales_line_id = _insert_sales_line(tenant_a, ingestion_run_id=run_id, order_ref="M-1", line_ref="M-1_1")
    settlement_line_id = _insert_settlement_line(tenant_a, ingestion_run_id=run_id, line_ref="M-1_1")
    _insert_matching_components(tenant_a, sales_line_id=sales_line_id, settlement_line_id=settlement_line_id)
    _insert_tolerance(tenant_a)

    # Before any reconciliation has run: cash_conversion_timing is empty and deferred.
    before = app_client.post(
        "/api/v1/cfo/funding-readiness",
        json={"period_start": _PERIOD_START.isoformat(), "period_end": _PERIOD_END.isoformat(), "as_of_date": _AS_OF.isoformat()},
        headers=headers,
    )
    assert before.status_code == 200, before.text
    assert before.json()["cashConversionTiming"] == []
    before_names = {s["name"] for s in before.json()["deferredSections"]}
    assert "cash_conversion_timing" in before_names

    # Run the real reconciliation (POST /cfo/preview — real reconcile(), no entitlement gate).
    preview = app_client.post(
        "/api/v1/cfo/preview",
        json={
            "marketplace": "MEESHO",
            "period_start": _PERIOD_START.isoformat(),
            "period_end": _PERIOD_END.isoformat(),
            "as_of_date": _AS_OF.isoformat(),
        },
        headers=headers,
    )
    assert preview.status_code == 200, preview.text

    # Now funding-readiness for the SAME period picks up the real, persisted SETTLEMENT_LAG_DAYS row.
    after = app_client.post(
        "/api/v1/cfo/funding-readiness",
        json={"period_start": _PERIOD_START.isoformat(), "period_end": _PERIOD_END.isoformat(), "as_of_date": _AS_OF.isoformat()},
        headers=headers,
    )
    assert after.status_code == 200, after.text

    body = after.json()
    assert len(body["cashConversionTiming"]) == 1
    assert body["cashConversionTiming"][0]["metricCode"] == "SETTLEMENT_LAG_DAYS"
    assert body["cashConversionTiming"][0]["isAvailable"] is True
    after_names = {s["name"] for s in body["deferredSections"]}
    assert "cash_conversion_timing" not in after_names
    assert "margin_stability" in after_names  # unrelated deferrals stay untouched
