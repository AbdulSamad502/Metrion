"""PI's direct-execution routes end-to-end against a real Postgres — niche-brief CRUD, the
happy path of `POST /api/v1/pi/discover` (both permission gates present, real
`services.pi_actions.run_discovery` composition, fake Tavily/YouTube/text-extraction/
embedding clients — same fake pattern `packages/product-intelligence`'s own
`tests/integration/test_pi_discover_end_to_end.py` uses, reused here rather than
reimplemented), and `GET /api/v1/pi/report/{run_id}` reading the resulting run back.

No test in this file ever constructs `HttpTavilyClient`/`HttpYoutubeClient`/`HttpPlacesClient`/
`OllamaTextInsightExtractor`/`OllamaEmbeddingClient` — grepped directly before finishing.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from product_intelligence.embedding.embed import MODEL_DIM
from product_intelligence.review_insight.text_extraction import TextExtractionResult, TextObservation
from product_intelligence.sources.tavily_client import TavilyImage, TavilySearchResult, TavilyUnavailable
from product_intelligence.sources.youtube_client import YoutubeVideo

_APP_URL = os.environ.get("DATABASE_URL_APP")
_MIGRATE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _APP_URL or not _MIGRATE_URL,
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)

_PI_TABLES: tuple[str, ...] = (
    "product_embedding",
    "supplier_lead",
    "product_review_insight",
    "product_candidate",
    "pi_research_run",
    "niche_brief",
)


@pytest.fixture(autouse=True)
def _clean_pi_tables():
    """PI's own tables live in a separate migration history from `backend`'s (own alembic
    version table), so `backend/tests/integration/conftest.py`'s `_clean_backend_tables` never
    touches them — cleaned here directly, mirroring `product-intelligence`'s own conftest."""
    engine = create_engine(_MIGRATE_URL)
    with engine.begin() as conn:
        for t in _PI_TABLES:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with engine.begin() as conn:
        for t in _PI_TABLES:
            conn.execute(text(f"DELETE FROM {t}"))
    engine.dispose()


class _FakeTavilyClient:
    def __init__(self, raises: bool = False) -> None:
        self._raises = raises

    def search(self, query, *, include_images=False, max_results=10):
        if self._raises:
            raise TavilyUnavailable("simulated Tavily outage")
        return [
            TavilySearchResult(
                url="https://example.com/wireless-earbuds",
                title="Wireless Earbuds Charging Case Review",
                content="These wireless earbuds with a charging case are priced at ₹1,499 in most listings",
                score=0.95,
                published_date="2026-09-20",
                retrieved_at=_NOW,
            )
        ]

    def images_for(self, query, *, max_images=5):
        return [
            TavilyImage(
                url="https://img.example.com/earbuds.jpg",
                source_url="https://example.com/wireless-earbuds",
                description="wireless earbuds charging case",
            )
        ]


class _FakeYoutubeClient:
    def search_videos(self, query, *, max_results=10):
        return [
            YoutubeVideo(
                video_id="abc123",
                title="Wireless Earbuds Charging Case Unboxing",
                channel_title="Tech Reviews India",
                view_count=25_000,
                comment_count=120,
                thumbnail_url="https://img.example.com/thumb.jpg",
                published_at=_NOW,
                retrieved_at=_NOW,
            )
        ]

    def top_comments_for(self, video_id, *, max_comments=20):
        return ["Great battery life on these!", "Case broke after a month, disappointed"]


class _FakeTextExtractor:
    def extract(self, texts, *, insight_source_type):
        sentiments = ["POSITIVE", "NEGATIVE"]
        return TextExtractionResult(
            insight_source_type=insight_source_type,
            observations=tuple(
                TextObservation(sentiment=sentiments[i % 2], themes=("battery life",)) for i in range(len(texts))
            ),
        )


class _FakeEmbeddingClient:
    def embed(self, text: str) -> list[float]:
        return [0.1] * MODEL_DIM


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


@pytest.fixture
def tenant(migrate_engine):
    tenant_id = uuid.uuid4()
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenant (id, clerk_org_id, business_name, status, created_at) "
                "VALUES (:id, :clerk_org_id, 'Test Tenant', 'ACTIVE', now())"
            ),
            {"id": str(tenant_id), "clerk_org_id": f"org_{tenant_id}"},
        )
    yield tenant_id


def _register_owner(fake_clerk, tenant_id: uuid.UUID) -> dict[str, str]:
    """OWNER — holds every permission implicitly (§5.2), so both `agent.pi` and
    `research.niche_run` pass without a permissions-grid entry."""
    from backend.auth.permissions import OWNER_ROLE
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
    membership_repo.upsert_partner(tenant_id, user_row["id"], role=OWNER_ROLE, status="ACTIVE")

    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


def _register_partner_with_permissions(fake_clerk, tenant_id: uuid.UUID, *, permissions: dict[str, object]) -> dict[str, str]:
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


# --- niche_brief CRUD: plain tenant-write, no agent.* key ------------------------------------


def test_niche_brief_crud_round_trip_needs_no_agent_permission(app_client, fake_clerk, tenant):
    """PARTNER with an EMPTY permissions grid (no `agent.pi`) can still author a niche_brief —
    proves this route genuinely needs no `agent.*` key, per §6.1."""
    headers = _register_partner_with_permissions(fake_clerk, tenant, permissions={})

    resp = app_client.post(
        "/api/v1/pi/niche-briefs",
        json={"category_text": "wireless earbuds", "budget_paise": 500_000, "marketplaces": ["AMAZON"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    brief_id = resp.json()["nicheBriefId"]

    resp = app_client.get(f"/api/v1/pi/niche-briefs/{brief_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "DRAFT"

    resp = app_client.post(f"/api/v1/pi/niche-briefs/{brief_id}/mark-ready", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "READY"

    resp = app_client.get("/api/v1/pi/niche-briefs", headers=headers)
    assert resp.status_code == 200, resp.text
    assert any(b["id"] == brief_id for b in resp.json())


# --- POST /api/v1/pi/discover: happy path, real composition, fake external sources ----------


def test_discover_route_happy_path_reaches_complete_with_real_composition(
    app_client, fake_clerk, tenant, monkeypatch
):
    from backend.services import pi_actions

    monkeypatch.setattr(pi_actions, "_tavily_client", lambda: _FakeTavilyClient())
    monkeypatch.setattr(pi_actions, "_youtube_client", lambda: _FakeYoutubeClient())
    monkeypatch.setattr(pi_actions, "_text_extractor", lambda: _FakeTextExtractor())
    monkeypatch.setattr(pi_actions, "_embedding_client", lambda: _FakeEmbeddingClient())

    headers = _register_owner(fake_clerk, tenant)

    resp = app_client.post(
        "/api/v1/pi/niche-briefs",
        json={"category_text": "wireless earbuds", "budget_paise": 500_000, "marketplaces": ["AMAZON"]},
        headers=headers,
    )
    brief_id = resp.json()["nicheBriefId"]
    app_client.post(f"/api/v1/pi/niche-briefs/{brief_id}/mark-ready", headers=headers)

    resp = app_client.post(
        "/api/v1/pi/discover",
        json={"niche_brief_id": brief_id, "depth": "SHALLOW"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "COMPLETE"
    assert len(body["candidateIds"]) >= 1
    assert body["agentRunId"]

    report_resp = app_client.get(f"/api/v1/pi/report/{body['runId']}", headers=headers)
    assert report_resp.status_code == 200, report_resp.text
    report_body = report_resp.json()
    assert report_body["status"] == "COMPLETE"
    assert len(report_body["candidates"]) == len(body["candidateIds"])
    unavailable_fields = {u["field"] for u in report_body["unavailable"]}
    assert "marketplace_price_and_competition" in unavailable_fields
    assert "demand_signal" in unavailable_fields


def test_discover_route_requires_niche_brief_to_be_ready(app_client, fake_clerk, tenant, monkeypatch):
    """A `DRAFT` (never marked `READY`) brief fails closed — `submit_pi_discover` itself
    enforces this (§6.1 rule 4), surfaced through the route as a `FAILED` run, not a 500."""
    from backend.services import pi_actions

    monkeypatch.setattr(pi_actions, "_tavily_client", lambda: _FakeTavilyClient())
    monkeypatch.setattr(pi_actions, "_youtube_client", lambda: _FakeYoutubeClient())
    monkeypatch.setattr(pi_actions, "_text_extractor", lambda: _FakeTextExtractor())
    monkeypatch.setattr(pi_actions, "_embedding_client", lambda: _FakeEmbeddingClient())

    headers = _register_owner(fake_clerk, tenant)

    resp = app_client.post(
        "/api/v1/pi/niche-briefs",
        json={"category_text": "wireless earbuds", "budget_paise": 500_000, "marketplaces": ["AMAZON"]},
        headers=headers,
    )
    brief_id = resp.json()["nicheBriefId"]

    resp = app_client.post(
        "/api/v1/pi/discover",
        json={"niche_brief_id": brief_id, "depth": "SHALLOW"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "FAILED"


def test_discover_route_denies_403_when_agent_pi_present_but_research_niche_run_absent(
    app_client, fake_clerk, tenant
):
    """T31-equivalent for PI's own pair: `agent.pi` present, `research.niche_run` absent ->
    403, symmetric to CFO's `agent.cfo`/`service.gst_lookup` gate."""
    headers = _register_partner_with_permissions(fake_clerk, tenant, permissions={"agent.pi": True})

    resp = app_client.post(
        "/api/v1/pi/discover",
        json={"niche_brief_id": str(uuid.uuid4()), "depth": "SHALLOW"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert "research.niche_run" in resp.json()["detail"]


def test_discover_route_denies_403_when_neither_permission_present(app_client, fake_clerk, tenant):
    headers = _register_partner_with_permissions(fake_clerk, tenant, permissions={})

    resp = app_client.post(
        "/api/v1/pi/discover",
        json={"niche_brief_id": str(uuid.uuid4()), "depth": "SHALLOW"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
