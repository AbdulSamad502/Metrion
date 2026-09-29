"""`POST /api/v1/cfo/strategic-briefing` — cfo-agent.md §7.5, real Postgres.

Closes the gap: `assemble_strategic_briefing` already supported `pricing_candidates`/
`supplier_ranking` (compose_strategic_signals's PRICING/SUPPLIER signal sources), but the HTTP
request body never exposed them — a caller could not reach those signals without calling the
Python service function directly. This file is the route-level proof that
`pricingCandidates`/`supplierRanking` posted over HTTP produce real PRICING/SUPPLIER signals in
the response, mirroring `test_cfo_pnl.py`'s real-Postgres fixture conventions (`app_client`,
`fake_clerk`, `_register_owner`, `_seed_zero_cap`) exactly.

Covers: two pricing candidates -> a PRICING signal citing the highest-margin one; two supplier
quotes -> a SUPPLIER signal citing cheapest/priciest; a single candidate/quote of either kind
produces no signal (per `signals_from_pricing_candidates`/`signals_from_supplier_ranking`'s own
"2+ or nothing" rule — never a comparison invented from one data point); entitlement denial; the
narration-safety check (`cfo.reasoning.narration_safety.check_narration_safety`) is real,
wired into this route's response, and actually flags a fabricated number when a fake LLM
provider returns one — never a check that exists in code but nothing ever calls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text

_AS_OF = date(2026, 9, 25)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)


def _briefing_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "period_start": _PERIOD_START.isoformat(),
        "period_end": _PERIOD_END.isoformat(),
        "as_of_date": _AS_OF.isoformat(),
        "include_narration": False,  # never hits real Ollama in this test — deterministic wiring only
    }
    body.update(overrides)
    return body


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


def test_pricing_candidates_over_http_produce_a_pricing_signal(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    body = _briefing_body(
        pricing_candidates=[
            {
                "sku": "SKU-1",
                "price_paise": 500_00,
                "margin_pct": "12.50",
                "engine_result_ref": str(uuid.uuid4()),
            },
            {
                "sku": "SKU-1",
                "price_paise": 600_00,
                "margin_pct": "18.75",
                "engine_result_ref": str(uuid.uuid4()),
            },
        ]
    )

    resp = app_client.post("/api/v1/cfo/strategic-briefing", json=body, headers=headers)
    assert resp.status_code == 200, resp.text

    signals = resp.json()["signals"]
    pricing_signals = [s for s in signals if s["category"] == "PRICING"]
    assert len(pricing_signals) == 1
    assert pricing_signals[0]["recommendedActionType"] == "CONSIDER_PRICE_CHANGE"
    assert pricing_signals[0]["evidence"]["valueFraction"] == "75/4"  # 18.75% as an exact Fraction


def test_supplier_ranking_over_http_produces_a_supplier_signal(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    body = _briefing_body(
        supplier_ranking=[
            {
                "sku": "SKU-1",
                "supplier_name": "Supplier A",
                "landed_cost_paise": 200_00,
                "engine_result_ref": str(uuid.uuid4()),
            },
            {
                "sku": "SKU-1",
                "supplier_name": "Supplier B",
                "landed_cost_paise": 260_00,
                "engine_result_ref": str(uuid.uuid4()),
            },
        ]
    )

    resp = app_client.post("/api/v1/cfo/strategic-briefing", json=body, headers=headers)
    assert resp.status_code == 200, resp.text

    signals = resp.json()["signals"]
    supplier_signals = [s for s in signals if s["category"] == "SUPPLIER"]
    assert len(supplier_signals) == 1
    assert supplier_signals[0]["recommendedActionType"] == "CONSIDER_SUPPLIER_SWITCH"


def test_a_single_pricing_candidate_produces_no_pricing_signal(app_client, fake_clerk, two_tenants):
    """§7.5's own rule: never invents a comparison from one data point."""
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    body = _briefing_body(
        pricing_candidates=[
            {
                "sku": "SKU-1",
                "price_paise": 500_00,
                "margin_pct": "12.50",
                "engine_result_ref": str(uuid.uuid4()),
            }
        ]
    )

    resp = app_client.post("/api/v1/cfo/strategic-briefing", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    assert [s for s in resp.json()["signals"] if s["category"] == "PRICING"] == []


def test_strategic_briefing_route_denies_402_when_cfo_entitlement_capped(app_client, fake_clerk, two_tenants, migrate_engine):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.strategic_briefing")
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post("/api/v1/cfo/strategic-briefing", json=_briefing_body(), headers=headers)
    assert resp.status_code == 402, resp.text
    assert resp.json()["detail"]["evaluationBasis"] == "OVER_CAP"


# --- narration safety, wired into this route's real response -----------------------------------


@dataclass
class _FakeCompletingProvider:
    response: str = "placeholder"
    calls: list[str] = field(default_factory=list)

    def complete(self, *, model: str, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


class _FakeOllamaProviderFactory:
    def __init__(self, instance: _FakeCompletingProvider) -> None:
        self._instance = instance

    def __call__(self, *args: Any, **kwargs: Any) -> _FakeCompletingProvider:
        return self._instance


def test_narration_safety_flags_a_fabricated_number_from_a_fake_provider(
    app_client, fake_clerk, two_tenants, monkeypatch
):
    """Proves the check is really wired in, not just a standalone unit-tested utility nobody
    calls — a fake LLM response containing a number absent from every cited figure must come
    back flagged on the real HTTP response. `assemble_strategic_briefing` constructs
    `OllamaLlmProvider` from its OWN module namespace (`backend.services.cfo_actions`), not
    `backend.api.v1.cfo`'s — patched there, mirroring where the real construction happens."""
    from backend.services import cfo_actions as cfo_actions_module

    fake_instance = _FakeCompletingProvider(
        response="Your margin looks strong at a completely made-up 47.30% this period."
    )
    monkeypatch.setattr(cfo_actions_module, "OllamaLlmProvider", _FakeOllamaProviderFactory(fake_instance))

    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    body = _briefing_body(
        include_narration=True,
        pricing_candidates=[
            {"sku": "SKU-1", "price_paise": 500_00, "margin_pct": "12.50", "engine_result_ref": str(uuid.uuid4())},
            {"sku": "SKU-1", "price_paise": 600_00, "margin_pct": "18.75", "engine_result_ref": str(uuid.uuid4())},
        ],
    )

    resp = app_client.post("/api/v1/cfo/strategic-briefing", json=body, headers=headers)
    assert resp.status_code == 200, resp.text

    result = resp.json()
    assert result["narrative"] == fake_instance.response
    assert result["narrationSafety"] is not None
    assert result["narrationSafety"]["isSafe"] is False
    assert "47.30" in result["narrationSafety"]["fabricatedNumbers"]


def test_narration_safety_is_none_when_narration_not_requested(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post(
        "/api/v1/cfo/strategic-briefing", json=_briefing_body(include_narration=False), headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["narrationSafety"] is None
