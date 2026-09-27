"""G3 — `cfo.gst_lookup`: wiring the already-complete G2 lookup (`calc_engine.gst_lookup`)
into CFO as a direct execution path (cfo-agent.md §6.6 C5/C6/§6.8, AC17b/T31), real Postgres.

Covers:
1. `run_gst_applicability_lookup`'s cache-hit path — a pre-seeded `gst_lookup_result` row
   (via `gst_lookup_repo.save` directly) is served WITHOUT touching the injected fetcher/LLM
   (both configured to raise if called at all, proving the cache path is really taken).
2. `run_gst_applicability_lookup`'s cache-miss path — a FAKE fetcher/LLM (never real
   network/Ollama) produces a fresh `GstLookupResult`, which gets persisted via
   `gst_lookup_repo.save` (confirmed by a second `find_cached` call).
3. `POST /api/v1/cfo/gst-lookup`'s two independent permission gates (T31 and its symmetric
   reverse case) — `agent.cfo` alone is not sufficient, `service.gst_lookup` alone is not
   sufficient, either missing one denies with 403.

No test in this file ever constructs `calc_engine.gst_lookup.fetcher.HttpxGstFetcher` or
`cfo.reasoning.ollama_provider.OllamaLlmProvider` — grepped directly before finishing (see the
task's own "before you finish" instruction).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction

import pytest
from sqlalchemy import text

from calc_engine.gst_lookup.fetcher import RawPage
from calc_engine.gst_lookup.types import GstLookupResult
from calc_engine.repositories import gst_lookup_repo

_NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_gst_lookup_table(migrate_engine):
    """`gst_lookup_result` is owned by calc-engine's own migration chain, not backend's
    `_clean_backend_tables` fixture — cleaned here directly, mirroring
    `test_cfo_preview.py`'s own before/after convention for calc-engine-owned tables."""
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM gst_lookup_result"))
    yield
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM gst_lookup_result"))


class _RaisingFetcher:
    """Injected in the cache-hit test — raises if `fetch` is ever called, proving the cache
    path never reaches a fetch attempt."""

    def fetch(self, url: str):  # pragma: no cover - only reached on a real bug
        raise AssertionError("fetch() must not be called on a cache hit")


class _RaisingLlm:
    """Injected in the cache-hit test — raises if `complete` is ever called, proving the cache
    path never reaches an LLM call."""

    def complete(self, *, model: str, prompt: str) -> str:  # pragma: no cover
        raise AssertionError("complete() must not be called on a cache hit")


@dataclass
class _FakeFetcher:
    """A fake `GstFetcher` — never touches the network. Returns a fixed `RawPage` for every
    URL, mirroring `calc_engine.gst_lookup.fetcher.RawPage`'s real shape."""

    body: str = "Mobile phones and telephone sets attract GST at 18%. HSN code 8517."

    def fetch(self, url: str):
        return RawPage(url=url, status_code=200, body=self.body, fetched_at=_NOW)


@dataclass
class _FakeLlm:
    """A fake `LlmProvider` — never touches Ollama. Returns a fixed, well-formed extraction
    response matching `calc_engine.gst_lookup.extraction.parse_extraction_response`'s expected
    shape."""

    response: str = (
        "MATCH: YES\n"
        "RATE_PCT: 18\n"
        "HSN: 8517\n"
        "CATEGORY: mobile phones\n"
        "AMBIGUOUS: NO\n"
        "AMBIGUITY_NOTE: NONE\n"
    )
    calls: list[str] | None = None

    def complete(self, *, model: str, prompt: str) -> str:
        if self.calls is not None:
            self.calls.append(prompt)
        return self.response


def _seed_cached_result(tenant_id: uuid.UUID, *, query_text: str, retrieved_at: datetime) -> GstLookupResult:
    result = GstLookupResult(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        query_text=query_text,
        source_url="https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517",
        retrieved_at=retrieved_at,
        likely_rate_pct=Fraction(18),
        likely_hsn="8517",
        likely_category="mobile phones",
        source_title="GetSwipe",
    )
    gst_lookup_repo.save(tenant_id, result)
    return result


# --- run_gst_applicability_lookup: cache-hit vs cache-miss ----------------------------------


def test_run_gst_applicability_lookup_cache_hit_never_touches_fetcher_or_llm(two_tenants):
    from backend.services.cfo_actions import GstLookupRequest, run_gst_applicability_lookup

    tenant_a, _ = two_tenants
    seeded = _seed_cached_result(tenant_a, query_text="Mobile phone", retrieved_at=_NOW)

    outcome = run_gst_applicability_lookup(
        tenant_a,
        GstLookupRequest(product_title="Mobile phone", computed_at=_NOW),
        fetcher=_RaisingFetcher(),
        llm=_RaisingLlm(),
    )

    assert outcome.from_cache is True
    assert outcome.no_match is None
    assert outcome.result is not None
    assert outcome.result.id == seeded.id
    assert outcome.result.likely_rate_pct == Fraction(18)
    assert outcome.result.source_url == seeded.source_url


def test_run_gst_applicability_lookup_cache_miss_persists_a_fresh_result(two_tenants):
    from backend.services.cfo_actions import GstLookupRequest, run_gst_applicability_lookup

    tenant_a, _ = two_tenants
    assert gst_lookup_repo.find_cached(tenant_a, query_text="Mobile phone", now=_NOW) is None

    fake_fetcher = _FakeFetcher()
    fake_llm = _FakeLlm(calls=[])

    outcome = run_gst_applicability_lookup(
        tenant_a,
        GstLookupRequest(product_title="Mobile phone", computed_at=_NOW),
        fetcher=fake_fetcher,
        llm=fake_llm,
        model="fake-model",
    )

    assert outcome.from_cache is False
    assert outcome.no_match is None
    assert outcome.result is not None
    assert outcome.result.likely_rate_pct == Fraction(18)
    assert outcome.result.likely_hsn == "8517"
    assert len(fake_llm.calls) == 1  # the LLM really was called on this cache-miss path

    cached = gst_lookup_repo.find_cached(tenant_a, query_text="Mobile phone", now=_NOW)
    assert cached is not None
    assert str(cached["id"]) == str(outcome.result.id)


def test_run_gst_applicability_lookup_no_match_persists_nothing(two_tenants):
    """A `GstLookupNoMatch` outcome (every known page attempted, no genuine match) writes NO
    row — a fresh attempt next time is correct, never a remembered permanent failure."""
    from backend.services.cfo_actions import GstLookupRequest, run_gst_applicability_lookup

    tenant_a, _ = two_tenants

    class _NoMatchLlm:
        def complete(self, *, model: str, prompt: str) -> str:
            return "MATCH: NO\nRATE_PCT: NONE\nHSN: NONE\nCATEGORY: NONE\nAMBIGUOUS: NO\nAMBIGUITY_NOTE: NONE\n"

    outcome = run_gst_applicability_lookup(
        tenant_a,
        GstLookupRequest(product_title="Some entirely novel unmatched product", computed_at=_NOW),
        fetcher=_FakeFetcher(),
        llm=_NoMatchLlm(),
        model="fake-model",
    )

    assert outcome.result is None
    assert outcome.from_cache is False
    assert outcome.no_match is not None

    from calc_engine.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_a) as conn:
        row_count = conn.execute(text("SELECT count(*) FROM gst_lookup_result")).scalar_one()
    assert row_count == 0


# --- POST /api/v1/cfo/gst-lookup: the two independent permission gates (T31 + symmetric) ---


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
    """A PARTNER (not OWNER — OWNER bypasses the permission grid entirely, per §5.2, which
    would make it impossible to test either half of this two-permission gate) with EXACTLY the
    given permissions grid."""
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


def test_gst_lookup_route_denies_403_when_agent_cfo_present_but_service_gst_lookup_absent(
    app_client, fake_clerk, two_tenants
):
    """T31, exact scenario: `agent.cfo` present, `service.gst_lookup` absent -> 403."""
    tenant_a, _ = two_tenants
    headers = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={"agent.cfo": True})

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup",
        json={"product_title": "Mobile phone"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert "service.gst_lookup" in resp.json()["detail"]


def test_gst_lookup_route_denies_403_when_service_gst_lookup_present_but_agent_cfo_absent(
    app_client, fake_clerk, two_tenants
):
    """The symmetric reverse of T31 — not named explicitly in the spec's own table, but
    symmetry requires it: `service.gst_lookup` present, `agent.cfo` absent -> 403. `require_auth
    (permission=AGENT_CFO)` denies this before the handler body (and its `service.gst_lookup`
    check) is ever reached."""
    tenant_a, _ = two_tenants
    headers = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={"service.gst_lookup": True})

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup",
        json={"product_title": "Mobile phone"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


def test_gst_lookup_route_denies_403_when_neither_permission_present(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={})

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup",
        json={"product_title": "Mobile phone"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


def test_gst_lookup_route_succeeds_when_both_permissions_present_cache_hit(
    app_client, fake_clerk, two_tenants
):
    """Both gates present, plus a pre-seeded cache row (cache-hit path) — proves the full route
    end-to-end without touching any real fetcher/LLM (the route always composes the real
    `HttpxGstFetcher`/`OllamaLlmProvider` defaults, but a cache hit never reaches them)."""
    tenant_a, _ = two_tenants
    seeded = _seed_cached_result(tenant_a, query_text="Mobile phone", retrieved_at=_NOW)
    headers = _register_partner_with_permissions(
        fake_clerk, tenant_a, permissions={"agent.cfo": True, "service.gst_lookup": True}
    )

    resp = app_client.post(
        "/api/v1/cfo/gst-lookup",
        json={"product_title": "Mobile phone"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fromCache"] is True
    assert body["result"]["id"] == str(seeded.id)
    assert body["result"]["likelyRatePct"] == "18"
    assert body["noMatch"] is None
