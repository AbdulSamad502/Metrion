"""R3: PI usage recording, end to end through the real routes (fake providers only).

One idempotent usage event per logical run and meter, only for a usable result; failed / empty / interrupted runs record nothing; the decision is stored once on the
run; legacy runs are never billed. Operational counts (started / failed / interrupted / successful) stay separate from usage."""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from tests.integration.owner_db import owner_tenant_scope

from market_signals.youtube_client import YoutubeUnavailable
from product_intelligence.direct_path.pi_discover import PiRunResult
from product_intelligence.repositories import pi_research_run_repo
from product_intelligence.supplier.google_places_client import PlaceDetails, PlaceIdResult

from backend.repositories import accounting_cutover_repo
from backend.services import pi_actions, pi_usage
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import T0
from tests.integration.test_pi_discover_api import (  # noqa: F401  (fixtures + fakes reused, not reimplemented)
    _FakeEmbeddingClient,
    _FakeTavilyClient,
    _FakeTextExtractor,
    _FakeYoutubeClient,
    _NoVideosYoutube,
    _register_owner,
    app_client,
    fake_clerk,
    tenant,
)

pytestmark = pytest.mark.usefixtures("two_tenants")


def events(tenant_id):
    with tenant_scope(tenant_id) as conn:
        return sorted(tuple(r) for r in conn.execute(text("SELECT agent_code, event_kind, quantity, idempotency_key FROM metered_event")))


def run_row(tenant_id, run_id):
    return pi_research_run_repo.get_run(tenant_id, uuid.UUID(run_id))


def discover(app_client, headers, monkeypatch, *, tavily=None, youtube=None, ready=True):
    from product_intelligence.sources.cache import InProcessQueryCache

    monkeypatch.setattr(pi_actions, "_QUERY_CACHE", InProcessQueryCache())
    monkeypatch.setattr(pi_actions, "_tavily_client", lambda: tavily or _FakeTavilyClient())
    monkeypatch.setattr(pi_actions, "_youtube_client", lambda: youtube or _NoVideosYoutube())
    monkeypatch.setattr(pi_actions, "_text_extractor", lambda: _FakeTextExtractor())
    monkeypatch.setattr(pi_actions, "_embedding_client", lambda: _FakeEmbeddingClient())
    brief = app_client.post("/api/v1/pi/niche-briefs", json={"category_text": "wireless earbuds", "budget_paise": 500_000, "marketplaces": ["AMAZON"]}, headers=headers).json()["nicheBriefId"]
    if ready:
        app_client.post(f"/api/v1/pi/niche-briefs/{brief}/mark-ready", headers=headers)
    resp = app_client.post("/api/v1/pi/discover", json={"niche_brief_id": brief, "depth": "SHALLOW"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


class _DownTavily(_FakeTavilyClient):
    def __init__(self) -> None:
        super().__init__(raises=True)

    def images_for(self, query, *, max_images=5):
        return []


class _DownYoutube:
    def search_videos(self, query, *, max_results=10):
        raise YoutubeUnavailable("simulated outage")

    def top_comments_for(self, video_id, *, max_comments=20):
        return []


def test_a_usable_complete_run_records_exactly_one_event_per_meter(app_client, fake_clerk, tenant, monkeypatch):
    body = discover(app_client, _register_owner(fake_clerk, tenant), monkeypatch)
    assert body["status"] == "COMPLETE"
    run = body["runId"]
    assert events(tenant) == [
        ("PI", "pi.discover", 1, f"pi:run:{run}:pi.discover"),
        ("SHARED", "research.niche_run", 1, f"pi:run:{run}:research.niche_run"),
    ]
    row = run_row(tenant, run)
    assert (row["usage_due"], row["outcome_code"]) == (True, "USABLE") and row["created_at"] is not None
    assert pi_research_run_repo.operational_counts(tenant) == {"started": 1, "failed": 0, "interrupted": 0, "successful": 1}


def test_a_partial_run_with_a_usable_result_is_billable(app_client, fake_clerk, tenant, monkeypatch):
    body = discover(app_client, _register_owner(fake_clerk, tenant), monkeypatch, youtube=_DownYoutube())
    assert body["status"] == "PARTIAL" and body["candidateIds"], body
    assert run_row(tenant, body["runId"])["outcome_code"] == "USABLE_PARTIAL"
    assert len(events(tenant)) == 2


def test_an_empty_run_is_never_billable_even_though_it_finished(app_client, fake_clerk, tenant, monkeypatch):
    body = discover(app_client, _register_owner(fake_clerk, tenant), monkeypatch, tavily=_DownTavily(), youtube=_NoVideosYoutube())
    assert body["status"] == "PARTIAL" and body["candidateIds"] == []  # status alone says "finished"; there is nothing usable
    row = run_row(tenant, body["runId"])
    assert (row["usage_due"], row["outcome_code"]) == (False, "EMPTY_RESULT")
    assert events(tenant) == []
    assert pi_research_run_repo.operational_counts(tenant)["successful"] == 0


def test_a_failed_run_records_nothing_and_is_counted_as_failed(app_client, fake_clerk, tenant, monkeypatch):
    body = discover(app_client, _register_owner(fake_clerk, tenant), monkeypatch, ready=False)  # brief never marked READY
    assert body["status"] == "FAILED"
    assert events(tenant) == []
    counts = pi_research_run_repo.operational_counts(tenant)
    assert counts["started"] == 1 and counts["failed"] == 1 and counts["successful"] == 0
    assert run_row(tenant, body["runId"])["outcome_code"] == "FAILED"


def test_an_exception_after_the_providers_answered_records_no_usage(app_client, fake_clerk, tenant, monkeypatch):
    from backend.api.v1 import pi as pi_api

    headers = _register_owner(fake_clerk, tenant)
    monkeypatch.setattr(pi_api, "run_discovery", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom after the providers answered")))
    brief = app_client.post("/api/v1/pi/niche-briefs", json={"category_text": "wireless earbuds", "budget_paise": 500_000, "marketplaces": ["AMAZON"]}, headers=headers).json()["nicheBriefId"]
    app_client.post(f"/api/v1/pi/niche-briefs/{brief}/mark-ready", headers=headers)
    with pytest.raises(RuntimeError):
        app_client.post("/api/v1/pi/discover", json={"niche_brief_id": brief, "depth": "SHALLOW"}, headers=headers)
    assert events(tenant) == []


def test_a_failed_usage_write_never_blocks_the_answer_and_the_decision_is_kept(app_client, fake_clerk, tenant, monkeypatch):
    monkeypatch.setattr(pi_usage, "record_metered_event", lambda *a, **k: None)  # "the write failed"
    body = discover(app_client, _register_owner(fake_clerk, tenant), monkeypatch)
    assert body["status"] == "COMPLETE" and events(tenant) == []
    assert run_row(tenant, body["runId"])["usage_due"] is True  # decided once; the missing event is what a repair (R5c, blocked) would need


def test_settling_the_same_run_repeatedly_and_concurrently_writes_one_event_per_meter(app_client, fake_clerk, tenant, monkeypatch, app_user):
    body = discover(app_client, _register_owner(fake_clerk, tenant), monkeypatch)
    result = PiRunResult(run_id=uuid.UUID(body["runId"]), agent_run_id=uuid.uuid4(), status="COMPLETE", candidate_ids=(), shortlisted_candidate_ids=(), partial_reason=None, failed_reason=None)
    now = T0 + timedelta(days=400)
    threads = [threading.Thread(target=pi_usage.settle_discover, args=(tenant,), kwargs={"requested_by": app_user, "result": result, "route_agent_run_id": None, "held": None, "now": now}) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    pi_usage.settle_discover(tenant, requested_by=app_user, result=result, route_agent_run_id=None, held=None, now=now)
    assert len(events(tenant)) == 2  # still one PI event and one SHARED event


def test_a_legacy_run_without_created_at_is_never_decided_or_billed(app_client, fake_clerk, tenant, monkeypatch, app_user):
    body = discover(app_client, _register_owner(fake_clerk, tenant), monkeypatch)
    run = uuid.UUID(body["runId"])
    with owner_tenant_scope(tenant) as conn:  # make it look like a row from before the accounting migration, and forget the live billing (the ledger is append-only for the app role)
        conn.execute(text("UPDATE pi_research_run SET created_at = NULL, usage_due = NULL, outcome_code = NULL WHERE id = :i"), {"i": str(run)})
        conn.execute(text("DELETE FROM metered_event"))
    result = PiRunResult(run_id=run, agent_run_id=uuid.uuid4(), status="COMPLETE", candidate_ids=(), shortlisted_candidate_ids=(), partial_reason=None, failed_reason=None)
    assert pi_usage.settle_discover(tenant, requested_by=app_user, result=result, route_agent_run_id=None, held=None, now=T0) == "LEGACY"
    assert events(tenant) == [] and pi_research_run_repo.get_run(tenant, run)["usage_due"] is None


def test_runs_before_the_cutover_are_decided_but_never_billed(app_client, fake_clerk, tenant, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: datetime.now(timezone.utc) + timedelta(days=1))  # the rule starts tomorrow
    body = discover(app_client, _register_owner(fake_clerk, tenant), monkeypatch)
    assert body["status"] == "COMPLETE" and events(tenant) == []


class _Places:
    def __init__(self, found: bool) -> None:
        self.found = found

    def search_place_ids(self, query, *, max_results=10):
        return [PlaceIdResult(place_id="pl1", display_name="Acme Traders", retrieved_at=T0)] if self.found else []

    def enrich_place(self, place_id):
        return PlaceDetails(place_id=place_id, display_name="Acme Traders", phone=None, website=None, formatted_address=None, retrieved_at=T0)


class _NoWebTavily(_FakeTavilyClient):
    def search(self, query, *, include_images=False, max_results=10, topic=None, days=None, country=None, include_domains=None):
        return []


def lookup(app_client, headers, monkeypatch, body, *, found: bool, web: bool):
    monkeypatch.setattr(pi_actions, "_places_client", lambda: _Places(found))
    monkeypatch.setattr(pi_actions, "_tavily_client", lambda: _FakeTavilyClient() if web else _NoWebTavily())
    resp = app_client.post("/api/v1/pi/supplier-lookup", json={"run_id": body["runId"], "candidate_ids": body["candidateIds"][:5]}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_supplier_lookup_with_a_usable_lead_records_one_event_keyed_by_the_call(app_client, fake_clerk, tenant, monkeypatch):
    headers = _register_owner(fake_clerk, tenant)
    body = discover(app_client, headers, monkeypatch)
    before = events(tenant)
    out = lookup(app_client, headers, monkeypatch, body, found=True, web=True)
    new = [e for e in events(tenant) if e not in before]
    assert new == [("PI", "pi.supplier_lookup", 1, f"pi:supplier:{out['agentRunId']}")]


def test_a_supplier_lookup_with_no_usable_lead_is_not_billable(app_client, fake_clerk, tenant, monkeypatch):
    headers = _register_owner(fake_clerk, tenant)
    body = discover(app_client, headers, monkeypatch)
    before = events(tenant)
    lookup(app_client, headers, monkeypatch, body, found=False, web=False)
    assert events(tenant) == before


def test_the_existing_started_count_keeps_its_meaning_and_enforcement_uses_successful_runs_only(app_client, fake_clerk, tenant, monkeypatch):
    from backend.entitlement import resolve_niche_run_entitlement

    headers = _register_owner(fake_clerk, tenant)
    discover(app_client, headers, monkeypatch, ready=False)  # a failed run
    discover(app_client, headers, monkeypatch)  # a successful run
    r = resolve_niche_run_entitlement(tenant)
    assert r.niche_run_count == 2 == pi_research_run_repo.count_runs_for_tenant(tenant)  # rows ever started: unchanged meaning
    assert r.niche_runs_successful == 1 and r.usage_count == 1  # usage = recorded successful executions only
    assert r.passed is True and r.evaluation_basis == "NO_CAP_CONFIGURED"
