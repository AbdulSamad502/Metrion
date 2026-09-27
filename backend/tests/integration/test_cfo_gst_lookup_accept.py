"""G4 — `accept_gst_lookup_result` / `POST /api/v1/cfo/gst-lookup/accept` (deterministic-
engine.md §7.2.1 `gst_rate_override` / §8.4's updated L2 rule), real Postgres.

Covers:
1. `accept_gst_lookup_result`'s happy path against a real `gst_lookup_result` row — creates a
   real, readable `manual_adjustment` row.
2. Rejection when `gst_lookup_result_id` does not exist for this tenant.
3. Correction/supersession: accepting a second, different lookup result for the same SKU
   inserts a NEW row whose `supersedes_id` points at the prior override — both rows still
   exist afterward (append-only, never mutated), mirroring
   `test_manual_adjustment_append_only.py`'s own supersession pattern.
4. `POST /api/v1/cfo/gst-lookup/accept`'s three permission gates — a real `403` when
   `financials.adjust` is absent (with `agent.cfo` + `service.gst_lookup` both present), and a
   real success path creating a real, readable `manual_adjustment` row end-to-end.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fractions import Fraction

import pytest
from sqlalchemy import text

from calc_engine.gst_lookup.types import GstLookupResult
from calc_engine.repositories import gst_lookup_repo, manual_adjustment_repo

_NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_gst_tables(migrate_engine):
    """`gst_lookup_result` and `manual_adjustment` are both calc-engine-owned tables, cleaned
    directly, mirroring `test_cfo_gst_lookup.py`'s own before/after convention."""
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM gst_lookup_result"))
        conn.execute(text("DELETE FROM manual_adjustment"))
    yield
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM gst_lookup_result"))
        conn.execute(text("DELETE FROM manual_adjustment"))


def _seed_lookup_result(
    tenant_id: uuid.UUID,
    *,
    rate_pct: Fraction,
    hsn: str,
    category: str,
    query_text: str = "Mobile phone",
) -> GstLookupResult:
    result = GstLookupResult(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        query_text=query_text,
        source_url="https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517",
        retrieved_at=_NOW,
        likely_rate_pct=rate_pct,
        likely_hsn=hsn,
        likely_category=category,
        source_title="GetSwipe",
    )
    gst_lookup_repo.save(tenant_id, result)
    return result


# --- accept_gst_lookup_result: happy path, rejection, supersession --------------------------


def test_accept_gst_lookup_result_creates_a_real_readable_manual_adjustment(two_tenants):
    from backend.services.cfo_actions import AcceptGstLookupRequest, accept_gst_lookup_result

    tenant_a, _ = two_tenants
    seeded = _seed_lookup_result(tenant_a, rate_pct=Fraction(18), hsn="8517", category="mobile phones")

    outcome = accept_gst_lookup_result(
        tenant_a,
        AcceptGstLookupRequest(
            gst_lookup_result_id=seeded.id,
            sku="SKU-1",
            accepted_by=uuid.uuid4(),
            accepted_at=_NOW,
        ),
    )

    assert outcome.rejected_reason is None
    assert outcome.manual_adjustment_id is not None

    rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_a, target_type="SKU", target_ref="SKU-1", field="gst_rate_override"
    )
    assert len(rows) == 1
    assert rows[0]["id"] == outcome.manual_adjustment_id
    # the real stored `numeric(7,4)` column round-trips as Decimal("18.0000") via
    # `gst_lookup_repo.get_by_id` -> `str(...)` -> "18.0000", not the bare "18" the in-memory
    # `Fraction(18)` would str() to — this proves the value really came from Postgres.
    assert rows[0]["value"]["rate_pct"] == "18.0000"
    assert rows[0]["value"]["hsn"] == "8517"
    assert rows[0]["value"]["category"] == "mobile phones"
    assert rows[0]["value"]["gst_lookup_result_id"] == str(seeded.id)


def test_accept_gst_lookup_result_rejects_nonexistent_lookup_row(two_tenants):
    from backend.services.cfo_actions import AcceptGstLookupRequest, accept_gst_lookup_result

    tenant_a, _ = two_tenants
    missing_id = uuid.uuid4()

    outcome = accept_gst_lookup_result(
        tenant_a,
        AcceptGstLookupRequest(gst_lookup_result_id=missing_id, sku="SKU-1", accepted_by=uuid.uuid4()),
    )

    assert outcome.manual_adjustment_id is None
    assert outcome.rejected_reason is not None

    rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_a, target_type="SKU", target_ref="SKU-1", field="gst_rate_override"
    )
    assert rows == []


def test_accept_gst_lookup_result_rejects_a_cross_tenant_lookup_row(two_tenants):
    """RLS makes a cross-tenant id indistinguishable from a nonexistent one — tenant B's own
    lookup row must not be acceptable by tenant A."""
    from backend.services.cfo_actions import AcceptGstLookupRequest, accept_gst_lookup_result

    tenant_a, tenant_b = two_tenants
    seeded_for_b = _seed_lookup_result(tenant_b, rate_pct=Fraction(18), hsn="8517", category="mobile phones")

    outcome = accept_gst_lookup_result(
        tenant_a,
        AcceptGstLookupRequest(gst_lookup_result_id=seeded_for_b.id, sku="SKU-1", accepted_by=uuid.uuid4()),
    )

    assert outcome.manual_adjustment_id is None
    assert outcome.rejected_reason is not None


def test_accept_gst_lookup_result_second_acceptance_supersedes_the_first(two_tenants):
    """Append-only: accepting a second, different lookup result for the same SKU inserts a NEW
    manual_adjustment row whose `supersedes_id` points at the first — the first row is never
    mutated, both still exist afterward."""
    from backend.services.cfo_actions import AcceptGstLookupRequest, accept_gst_lookup_result

    tenant_a, _ = two_tenants
    first_lookup = _seed_lookup_result(tenant_a, rate_pct=Fraction(18), hsn="8517", category="mobile phones")
    second_lookup = _seed_lookup_result(
        tenant_a, rate_pct=Fraction(12), hsn="8517", category="feature phones", query_text="Feature phone"
    )

    first_outcome = accept_gst_lookup_result(
        tenant_a,
        AcceptGstLookupRequest(gst_lookup_result_id=first_lookup.id, sku="SKU-1", accepted_by=uuid.uuid4()),
    )
    second_outcome = accept_gst_lookup_result(
        tenant_a,
        AcceptGstLookupRequest(gst_lookup_result_id=second_lookup.id, sku="SKU-1", accepted_by=uuid.uuid4()),
    )

    assert first_outcome.manual_adjustment_id is not None
    assert second_outcome.manual_adjustment_id is not None
    assert first_outcome.manual_adjustment_id != second_outcome.manual_adjustment_id

    from calc_engine.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(
            text("SELECT id, supersedes_id FROM manual_adjustment WHERE field = 'gst_rate_override' ORDER BY created_at")
        ).fetchall()
    assert len(rows) == 2  # both rows still exist — nothing was overwritten
    rows_by_id = {str(r[0]): r[1] for r in rows}
    assert rows_by_id[str(first_outcome.manual_adjustment_id)] is None
    assert str(rows_by_id[str(second_outcome.manual_adjustment_id)]) == str(first_outcome.manual_adjustment_id)


# --- POST /api/v1/cfo/gst-lookup/accept: the three permission gates ------------------------


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from backend.main import app

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
            header = request.headers.get("authorization", "")
            token = header.removeprefix("Bearer ").strip()
            if token in self.tokens:
                clerk_user_id, clerk_org_id = self.tokens[token]
                return _FakeAuthState(is_signed_in=True, payload={"sub": clerk_user_id, "org_id": clerk_org_id})
            return _FakeAuthState(is_signed_in=False, payload=None)

    client = _FakeClerkClient()
    monkeypatch.setattr(auth_context_module, "get_clerk_client", lambda: client)
    return client


def _register_partner_with_permissions(fake_clerk, tenant_id: uuid.UUID, *, permissions: dict[str, object]) -> dict[str, str]:
    """A PARTNER (not OWNER — OWNER bypasses the permission grid entirely, per §5.2) with
    EXACTLY the given permissions grid — mirrors `test_cfo_gst_lookup.py`'s own helper."""
    from backend.auth.permissions import PARTNER_ROLE
    from backend.repositories import app_user_repo, membership_repo

    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=f"{clerk_user_id}@example.com",
        email_verified=True,
        auth_provider="GOOGLE",
        display_name="Test Partner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.upsert_partner(tenant_id, user_row["id"], role=PARTNER_ROLE, status="ACTIVE")
    membership_repo.set_permissions(tenant_id, user_row["id"], permissions)

    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


def test_accept_route_denies_403_when_financials_adjust_absent(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    seeded = _seed_lookup_result(tenant_a, rate_pct=Fraction(18), hsn="8517", category="mobile phones")
    headers = _register_partner_with_permissions(
        fake_clerk, tenant_a, permissions={"agent.cfo": True, "service.gst_lookup": True}
    )

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup/accept",
        json={"gst_lookup_result_id": str(seeded.id), "sku": "SKU-1"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert "financials.adjust" in resp.json()["detail"]

    rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_a, target_type="SKU", target_ref="SKU-1", field="gst_rate_override"
    )
    assert rows == []


def test_accept_route_denies_403_when_service_gst_lookup_absent(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    seeded = _seed_lookup_result(tenant_a, rate_pct=Fraction(18), hsn="8517", category="mobile phones")
    headers = _register_partner_with_permissions(
        fake_clerk, tenant_a, permissions={"agent.cfo": True, "financials.adjust": True}
    )

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup/accept",
        json={"gst_lookup_result_id": str(seeded.id), "sku": "SKU-1"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert "service.gst_lookup" in resp.json()["detail"]


def test_accept_route_denies_403_when_agent_cfo_absent(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    seeded = _seed_lookup_result(tenant_a, rate_pct=Fraction(18), hsn="8517", category="mobile phones")
    headers = _register_partner_with_permissions(
        fake_clerk, tenant_a, permissions={"service.gst_lookup": True, "financials.adjust": True}
    )

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup/accept",
        json={"gst_lookup_result_id": str(seeded.id), "sku": "SKU-1"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


def test_accept_route_succeeds_when_all_three_permissions_present(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    seeded = _seed_lookup_result(tenant_a, rate_pct=Fraction(18), hsn="8517", category="mobile phones")
    headers = _register_partner_with_permissions(
        fake_clerk,
        tenant_a,
        permissions={"agent.cfo": True, "service.gst_lookup": True, "financials.adjust": True},
    )

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup/accept",
        json={"gst_lookup_result_id": str(seeded.id), "sku": "SKU-1"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    manual_adjustment_id = resp.json()["manualAdjustmentId"]

    rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_a, target_type="SKU", target_ref="SKU-1", field="gst_rate_override"
    )
    assert len(rows) == 1
    assert str(rows[0]["id"]) == manual_adjustment_id
    assert rows[0]["value"]["rate_pct"] == "18.0000"


def test_accept_route_returns_400_for_a_nonexistent_lookup_id(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_partner_with_permissions(
        fake_clerk,
        tenant_a,
        permissions={"agent.cfo": True, "service.gst_lookup": True, "financials.adjust": True},
    )

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup/accept",
        json={"gst_lookup_result_id": str(uuid.uuid4()), "sku": "SKU-1"},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
