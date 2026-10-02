"""`GET /api/v1/cfo/imports` and `/imports/{report_file_id}` — the read-only import viewer
(backend/services/cfo_imports.py), real Postgres, real `POST /cfo/ingest` to create the imports.

Covers: an owner sees their own import with persisted rows; another tenant gets a plain 404;
a duplicate upload resolves to the existing report and creates no second ingestion run; pagination;
rejected-row diagnostics (and the explicit "not persisted" answer when there are none); a missing
report is a normal 404; the response never leaks a storage path or raw seller row.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

_CSV_HEADER = "Meesho Order Number,Sub Order No,Reason for Credit Entry,Return Status\r\n"


def _csv(n: int) -> bytes:
    rows = "".join(f"ORD-{i},ORD-{i}_1,DELIVERED,Delivered\r\n" for i in range(1, n + 1))
    return (_CSV_HEADER + rows).encode()


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend.api.v1 import cfo as cfo_routes
    from backend.main import app

    # Uploads write the raw file to local disk — point that at a throwaway directory.
    monkeypatch.setattr(cfo_routes, "cfo_report_storage_dir", lambda: str(tmp_path))
    return TestClient(app)


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
            token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
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
        clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", email_verified=True,
        auth_provider="GOOGLE", display_name="Test Owner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.create_owner(tenant_id, user_row["id"])
    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


def _upload(app_client, headers, content: bytes, name: str = "meesho_orders.csv") -> dict:
    resp = app_client.post(
        "/api/v1/cfo/ingest",
        params={"marketplace": "MEESHO", "adapter_id": "meesho.orders.v1"},
        files={"file": (name, content, "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run_count(tenant_id: uuid.UUID, report_file_id: str) -> int:
    # FORCE RLS applies to every role, so even a direct count needs the tenant context.
    from data_foundation.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_id) as conn:
        return conn.execute(
            text("SELECT count(*) FROM ingestion_run WHERE report_file_id = :id"), {"id": report_file_id}
        ).scalar_one()


def test_owner_views_own_import_with_persisted_rows(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    uploaded = _upload(app_client, headers, _csv(3))

    resp = app_client.get(f"/api/v1/cfo/imports/{uploaded['reportFileId']}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["reportFileId"] == uploaded["reportFileId"]
    assert body["ingestionRunId"] == uploaded["ingestionRunId"]
    assert body["filename"] == "meesho_orders.csv"
    assert body["marketplace"] == "MEESHO"
    assert body["adapter"] == "meesho.orders.v1"
    assert body["status"] == "VALIDATED"
    assert body["counts"] == {"read": 3, "accepted": 3, "rejected": 0, "duplicate": 0, "persisted": 3}
    assert body["lineKind"] == "SALES_LINE"
    assert [r["orderRef"] for r in body["rows"]] == ["ORD-1", "ORD-2", "ORD-3"]
    assert all(r["salesLineId"] for r in body["rows"])
    assert body["pagination"] == {"limit": 50, "offset": 0, "total": 3}
    assert body["originalCsv"]["available"] is False

    # Nothing internal leaks: no storage location, no content hash, no raw seller row.
    text_body = resp.text
    assert "file://" not in text_body and "storage" not in text_body.lower()
    assert "source_row_json" not in text_body and "content_sha256" not in text_body


def test_another_tenant_cannot_view_the_import(app_client, fake_clerk, two_tenants):
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)
    uploaded = _upload(app_client, headers_a, _csv(2))

    resp = app_client.get(f"/api/v1/cfo/imports/{uploaded['reportFileId']}", headers=headers_b)
    assert resp.status_code == 404

    # ...and it is not in tenant B's history either, while tenant A still sees it.
    assert app_client.get("/api/v1/cfo/imports", headers=headers_b).json() == []
    ids_a = [i["reportFileId"] for i in app_client.get("/api/v1/cfo/imports", headers=headers_a).json()]
    assert ids_a == [uploaded["reportFileId"]]


def test_duplicate_upload_resolves_to_existing_report_without_a_second_run(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    first = _upload(app_client, headers, _csv(2))
    second = _upload(app_client, headers, _csv(2))

    assert second["duplicate"] is True
    assert second["reportFileId"] == first["reportFileId"]

    resp = app_client.get(f"/api/v1/cfo/imports/{second['reportFileId']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["counts"]["persisted"] == 2

    # Viewing — and the duplicate upload itself — created no further ingestion run.
    assert _run_count(tenant_a, first["reportFileId"]) == 1
    app_client.get(f"/api/v1/cfo/imports/{first['reportFileId']}", headers=headers)
    assert _run_count(tenant_a, first["reportFileId"]) == 1


def test_rows_are_paginated(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    uploaded = _upload(app_client, headers, _csv(5))
    url = f"/api/v1/cfo/imports/{uploaded['reportFileId']}"

    page1 = app_client.get(url, params={"limit": 2, "offset": 0}, headers=headers).json()
    page2 = app_client.get(url, params={"limit": 2, "offset": 2}, headers=headers).json()
    page3 = app_client.get(url, params={"limit": 2, "offset": 4}, headers=headers).json()

    assert [r["orderRef"] for r in page1["rows"]] == ["ORD-1", "ORD-2"]
    assert [r["orderRef"] for r in page2["rows"]] == ["ORD-3", "ORD-4"]
    assert [r["orderRef"] for r in page3["rows"]] == ["ORD-5"]
    assert page1["pagination"] == {"limit": 2, "offset": 0, "total": 5}
    # Counts describe the whole import, not the page.
    assert page2["counts"]["persisted"] == 5


def test_rejected_diagnostics_returned_only_when_persisted(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    uploaded = _upload(app_client, headers, _csv(2))
    url = f"/api/v1/cfo/imports/{uploaded['reportFileId']}"

    # The live upload path does not persist findings — the response must say so explicitly.
    none_yet = app_client.get(url, headers=headers).json()["rejected"]
    assert none_yet["diagnosticsPersisted"] is False and none_yet["findings"] == []

    from data_foundation.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text(
                """
                INSERT INTO validation_finding
                    (id, tenant_id, ingestion_run_id, sales_line_id, rule_id, severity, message, source_row_number)
                VALUES (:id, :tenant_id, :run_id, NULL, 'V-ENUM-001', 'WARNING', 'unmapped Return Status value', 7)
                """
            ),
            {"id": str(uuid.uuid4()), "tenant_id": str(tenant_a), "run_id": uploaded["ingestionRunId"]},
        )

    rejected = app_client.get(url, headers=headers).json()["rejected"]
    assert rejected["diagnosticsPersisted"] is True
    assert rejected["findings"] == [
        {"ruleId": "V-ENUM-001", "severity": "WARNING", "message": "unmapped Return Status value", "sourceRowNumber": 7}
    ]


def test_missing_report_is_a_plain_404(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    resp = app_client.get(f"/api/v1/cfo/imports/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "import not found"


def test_requires_authentication(app_client):
    assert app_client.get(f"/api/v1/cfo/imports/{uuid.uuid4()}").status_code in (401, 403)
