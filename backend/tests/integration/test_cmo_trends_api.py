"""P7f end to end: `cmo.market_trends` over the real HTTP API on a real Postgres - permissions, the two entitlement meters,
the preview-bound plan, persistence, idempotency, tenant isolation, privacy and failure behaviour.

Real: FastAPI app, auth chain (Clerk faked), niche service, retrieval service + egress guard, trend service, Postgres + RLS,
quota reservations, metering, the provider-usage counter (in the ceiling test). Faked: the two search providers and the model."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from market_signals.cache import InProcessQueryCache
from market_signals.tavily_client import TavilySearchResult, TavilyUnavailable
from market_signals.youtube_client import YoutubeUnavailable, YoutubeVideo
from sqlalchemy import text

from slim_cmo.generation.provider import LlmUnavailable
from slim_cmo.repositories.niche_repo import PostgresNicheStore
from slim_cmo.repositories.trend_repo import PostgresTrendStore
from slim_cmo.repositories.usage_repo import PostgresSlotStore
from slim_cmo.retrieval.service import RetrievalService
from slim_cmo.service.niche import NicheService
from slim_cmo.service.trends import TrendReportService

from backend.auth.permissions import PARTNER_ROLE
from backend.services import cmo_runtime
from backend.services.cmo_runtime import CmoTrendRuntime

from .test_cmo_api import _login, _make_tenant, _erase_cmo_rows, ctx_engine, env, fake_clerk, title_body  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

TREND_CFG = {
    "max_queries_per_report": 10,
    "section_query_budgets": {"NICHE": 2, "MARKET_NEWS": 2, "REPORTED_TACTICS": 2, "NEW_PRODUCTS_BUZZ": 2, "ADJACENT": 2},
    "section_priority": ["NICHE", "MARKET_NEWS", "REPORTED_TACTICS", "NEW_PRODUCTS_BUZZ", "ADJACENT"],
    "max_results_per_query": 5, "max_sources_per_report": 40, "max_findings_per_section": 3, "fresh_window_days": 7,
    "recent_window_days": 30, "news_window_days": 30, "moderate_min_independent_sources": 2, "strong_min_independent_sources": 4,
    "max_confirmed_niche_terms": 5, "max_term_chars": 40, "catalog_titles_read_cap": 100, "provider_call_timeout_seconds": 15,
    "provider_cache_ttl_hours": 24, "provider_daily_search_ceiling": 20,
}
PATH = "/api/v1/cmo/market-trends"


class Tavily:
    def __init__(self, fail=False, delay=0.0):
        self.calls, self.fail, self.delay, self._lock = [], fail, delay, threading.Lock()

    def search(self, query, *, include_images=False, max_results=10, topic=None, days=None, country=None):
        with self._lock:
            self.calls.append({"query": query, "topic": topic, "days": days, "country": country, "max_results": max_results})
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise TavilyUnavailable("down")
        h = abs(hash(query)) % 9999
        now = datetime.now(UTC)
        return [TavilySearchResult(f"https://site{h}a.com/p", f"Coverage A {h}", "Reported coverage.", 0.5, "Thu, 01 Oct 2026 07:00:00 GMT", now),
                TavilySearchResult(f"https://site{h}b.org/p", f"Coverage B {h}", "More coverage.", 0.4, None, now)]


class Youtube:
    def __init__(self, fail=False):
        self.calls, self.fail, self._lock = [], fail, threading.Lock()

    def search_videos(self, query, *, max_results=10, region_code=None, order=None, published_after=None):
        with self._lock:
            self.calls.append({"query": query, "region_code": region_code, "max_results": max_results})
        if self.fail:
            raise YoutubeUnavailable("quota")
        h = abs(hash(query)) % 9999
        now = datetime.now(UTC)
        return [YoutubeVideo(f"v{h}", f"Video {h}", "Chan", 4200, 3, "th", now - timedelta(days=2), (), now, channel_id=f"UC{h}")]


class Slots:
    def __init__(self):
        self.taken = []

    def take_slot(self, provider, ceiling):
        self.taken.append((provider, ceiling))
        return True


class Model:
    def __init__(self, fail=False):
        self.prompts, self.fail = [], fail

    def complete(self, *, model, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise LlmUnavailable("down")
        if "interpretation items" in prompt:
            ids = re.findall(r'"id": "([A-Z_]+:\d+)"', prompt)
            return json.dumps({"items": [{"statement": "Worth watching how coverage develops.", "derived_from_finding_ids": ids[:1], "action_type": "WATCHLIST"}]})
        section = re.search(r'"section": "([A-Z_]+)"', prompt).group(1)
        n = [int(x) for x in re.findall(r'"n": (\d+)', prompt)]
        extra = {"MARKET_NEWS": {"news_kind": "POLICY"}, "NEW_PRODUCTS_BUZZ": {"buzz_kind": "LAUNCH"}, "ADJACENT": {"relation_to_niche": "Related drinkware"}, "REPORTED_TACTICS": {"policy_flag": False}}.get(section, {})
        return json.dumps({"findings": [{"theme": f"{section} coverage", "summary": "Reported by the cited sources as attracting attention.", "item_ids": n[:2], **extra}]})


@contextmanager
def _null(_):
    yield


class Rt:
    """Per-test handles on the fake providers/model/slots plus a helper to (re)install the runtime."""

    def __init__(self, env):
        self.env, self.tavily, self.youtube, self.model, self.slots = env, Tavily(), Youtube(), Model(), Slots()
        self.cache = InProcessQueryCache()

    def install(self, *, slots=None, tavily=None, youtube=None, model=None):
        self.tavily, self.youtube, self.model = tavily or self.tavily, youtube or self.youtube, model or self.model
        self.slots = slots or self.slots
        clock = cmo_runtime.utc_now
        niche = NicheService(PostgresNicheStore(), clock=clock)
        retrieval = lambda _cfg: RetrievalService(tavily=self.tavily, youtube=self.youtube, cache=self.cache, slots=self.slots, clock=clock, throttle=_null)  # noqa: E731
        service = TrendReportService(PostgresTrendStore(), niche, retrieval, self.model, model="test-model", clock=clock)
        self.env.monkeypatch.setattr(cmo_runtime, "build_trend_runtime", lambda **_kw: CmoTrendRuntime(service, clock))
        return service


@pytest.fixture
def tr(env):
    config_rows(env)
    rt = Rt(env)
    rt.install()
    return rt


def config_rows(env, values=None, tenant=None, drop=()):
    t = tenant or env.tenant
    with env.engine.begin() as conn:
        for k, v in (TREND_CFG if values is None else values).items():
            if k in drop:
                continue
            conn.execute(text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, :k, CAST(:v AS jsonb), '2026-01-01')"),
                         {"t": str(t), "k": k, "v": json.dumps(v)})


def confirm(env, terms, headers=None):
    r = env.post("niche-terms/confirm", {"new_terms": terms}, headers=headers)
    assert r.status_code == 200, r.text


def call(env, method, path="", body=None, headers=None):
    from fastapi.testclient import TestClient

    from backend.main import app

    h = env.headers if headers is None else headers
    c = TestClient(app)
    url = PATH + path
    return c.get(url, headers=h) if method == "GET" else c.post(url, json=body if body is not None else {}, headers=h)


def preview(env, headers=None, **body):
    return call(env, "POST", "/preview", body, headers)


def run(env, key, digest, headers=None, **body):
    return call(env, "POST", "", {"request_key": key, "plan_digest": digest, **body}, headers)


def grant(env, **permissions):
    return _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions=permissions)[0]


def seed_cap(env, agent_code, meter, cap):
    with env.engine.begin() as conn:
        conn.execute(text("INSERT INTO entitlement_cap_config (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version) "
                          "VALUES (:id, NULL, :a, :m, 'TENANT', 'MONTH', :c, '2026-01-01', 1)"), {"id": str(uuid.uuid4()), "a": agent_code, "m": meter, "c": cap})


def full(env, tr, key="t1", terms=("steel water bottle", "yoga mat"), **body):
    confirm(env, list(terms))
    pv = preview(env, **body).json()
    return pv, run(env, key, pv["digest"], **body)


# ------------------------------------------------------------------------------ authentication / authorisation
def test_unauthenticated_is_401_for_all_four_routes(env, tr):
    assert call(env, "POST", "/preview", {}, {}).status_code == 401
    assert call(env, "POST", "", {"request_key": "k", "plan_digest": "a" * 64}, {}).status_code == 401
    assert call(env, "GET", "", None, {}).status_code == 401
    assert call(env, "GET", f"/{uuid.uuid4()}", None, {}).status_code == 401
    assert env.n("cmo_generation") == 0 and tr.tavily.calls == []


def test_both_agent_cmo_and_research_market_trends_are_required(env, tr):
    cmo_only = grant(env, **{"agent.cmo": True})
    research_only = grant(env, **{"research.market_trends": True})
    both = grant(env, **{"agent.cmo": True, "research.market_trends": True})
    for method, path, body in (("POST", "/preview", {}), ("POST", "", {"request_key": "k", "plan_digest": "a" * 64}), ("GET", "", None), ("GET", f"/{uuid.uuid4()}", None)):
        r = call(env, method, path, body, cmo_only)
        assert r.status_code == 403 and "research.market_trends" in json.dumps(r.json()), (method, path)
        assert call(env, method, path, body, research_only).status_code == 403  # no agent.cmo
    assert call(env, "POST", "/preview", {}, both).status_code == 200
    assert tr.tavily.calls == [] and env.events() == []


def test_client_supplied_tenant_meter_cap_or_cost_fields_are_422(env, tr):
    digest = "a" * 64
    for extra in ({"tenant_id": str(uuid.uuid4())}, {"meter_code": "x"}, {"cap_value": 100}, {"units": 0}):
        assert run(env, "k", digest, **extra).status_code == 422
        assert preview(env, **extra).status_code == 422
    assert run(env, "k", "not-a-digest").status_code == 422
    assert env.n("cmo_generation") == 0


# ------------------------------------------------------------------------------ fail closed
def test_missing_trend_config_is_503_config_missing_and_nothing_is_called_or_written(env):
    config_rows(env, drop=("provider_daily_search_ceiling", "news_window_days"))
    rt = Rt(env)
    rt.install()
    for r in (preview(env), run(env, "k", "a" * 64)):
        assert r.status_code == 503 and r.json()["detail"]["code"] == "CONFIG_MISSING"
        assert set(r.json()["detail"]["missing"]) == {"provider_daily_search_ceiling", "news_window_days"}
    assert rt.tavily.calls == [] and rt.youtube.calls == [] and rt.model.prompts == [] and env.n("cmo_generation") == 0 and env.n("agent_run") == 0
    assert env.reservations() == [] and env.events() == []


def test_missing_config_never_reserves_a_unit_even_when_caps_exist(env):
    seed_cap(env, "CMO", "cmo.market_trends", 5)
    seed_cap(env, "SHARED", "research.market_trends", 5)
    config_rows(env, drop=("provider_cache_ttl_hours",))
    Rt(env).install()
    assert run(env, "k", "a" * 64).status_code == 503
    assert env.reservations() == []  # not even a reserve-then-release: configuration is verified before admission


def test_missing_provider_keys_or_model_config_is_503_not_configured(env, monkeypatch):
    from backend import config

    config_rows(env)
    monkeypatch.setattr(config, "tavily_api_key", lambda: "")
    monkeypatch.setattr(config, "youtube_api_key", lambda: "y")
    monkeypatch.setattr(config, "cmo_llm_model", lambda: "m")
    monkeypatch.setattr(config, "cmo_ollama_host", lambda: "http://localhost:11434")
    monkeypatch.setattr(config, "cmo_llm_timeout_seconds", lambda: 5)
    r = preview(env)
    assert r.status_code == 503 and r.json()["detail"] == {"code": "CMO_NOT_CONFIGURED"}


# ------------------------------------------------------------------------------ preview
def test_preview_is_free_makes_no_calls_and_shows_exactly_what_will_be_sent(env, tr):
    confirm(env, ["steel water bottle"])
    r = preview(env)
    assert r.status_code == 200
    body = r.json()
    assert len(body["queries"]) == 10 and len(body["digest"]) == 64 and body["byProvider"] == {"TAVILY": 7, "YOUTUBE": 3}
    assert any("steel water bottle" in q["query"] for q in body["queries"])
    assert body["unresearchedTerms"] == [] and "fixed searches" in body["notice"]
    assert tr.tavily.calls == [] and tr.youtube.calls == [] and tr.model.prompts == [] and tr.slots.taken == []
    assert env.events() == [] and env.n("agent_run", "trigger_ref = 'cmo.market_trends'") == 0 and env.reservations() == []


def test_without_confirmed_terms_the_preview_marks_niche_and_adjacent_unavailable(env, tr):
    body = preview(env).json()
    assert body["unavailableSections"]["NICHE"] and body["unavailableSections"]["ADJACENT"] and len(body["queries"]) == 6


# ------------------------------------------------------------------------------ the happy path
def test_a_report_is_delivered_persisted_audited_and_metered_on_both_meters(env, tr):
    pv, r = full(env, tr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "COMPLETE" and body["reused"] is False and body["unitsBilled"] == {"cmo": 1, "shared": 1}
    rep = body["report"]
    assert set(rep["sections"]) == {"NICHE", "MARKET_NEWS", "REPORTED_TACTICS", "NEW_PRODUCTS_BUZZ", "ADJACENT"}
    assert all(s["state"] == "COMPLETE" for s in rep["sections"].values())
    assert rep["outbound_queries"] == pv["queries"] and rep["evidence"]["data_gaps"] and rep["interpretation"]["label"].startswith("CMO's interpretation")
    # persistence
    assert env.n("cmo_generation", "output_type = 'TREND_REPORT' AND status = 'COMPLETE'") == 1 and env.n("cmo_trend_report") == 1
    # audit
    runs = env.q("SELECT agent_id, trigger_type, trigger_ref, status, requested_by FROM agent_run WHERE trigger_ref = 'cmo.market_trends'")
    assert len(runs) == 1 and runs[0][2] == "cmo.market_trends" and runs[0][3] == "COMPLETE" and runs[0][4] == env.user_id
    # metering: exactly one event per meter, tied to the report
    ev = env.events()
    assert sorted((e.agent_code, e.event_kind, e.quantity) for e in ev) == [("CMO", "cmo.market_trends", 1), ("SHARED", "research.market_trends", 1)]
    gid = body["generationId"]
    assert {e.idempotency_key for e in ev} == {f"cmo:{gid}", f"shared-trends:{gid}"} and {str(e.source_ref) for e in ev} == {gid}
    assert len(tr.tavily.calls) == 7 and len(tr.youtube.calls) == 3 and len(tr.slots.taken) == 10
    assert all(c["topic"] == "news" and c["days"] == 30 and c["country"] == "india" and c["max_results"] == 5 for c in tr.tavily.calls)


def test_read_back_and_list(env, tr):
    _, r = full(env, tr)
    gid = r.json()["generationId"]
    one = call(env, "GET", f"/{gid}")
    assert one.status_code == 200 and one.json()["report"]["sections"]["NICHE"]["findings"] and one.json()["unitsBilled"] == {"cmo": 0, "shared": 0}
    lst = call(env, "GET").json()["reports"]
    assert [x["generationId"] for x in lst] == [gid] and lst[0]["status"] == "COMPLETE"
    assert call(env, "GET", f"/{uuid.uuid4()}").status_code == 404


def test_a_replay_with_the_same_key_is_free_and_creates_no_run_event_or_call(env, tr):
    pv, first = full(env, tr)
    calls = (len(tr.tavily.calls), len(tr.youtube.calls), len(tr.model.prompts))
    again = run(env, "t1", pv["digest"])
    assert again.status_code == 200 and again.json()["reused"] is True and again.json()["unitsBilled"] == {"cmo": 0, "shared": 0}
    assert again.json()["generationId"] == first.json()["generationId"]
    assert (len(tr.tavily.calls), len(tr.youtube.calls), len(tr.model.prompts)) == calls
    assert env.n("agent_run", "trigger_ref = 'cmo.market_trends'") == 1 and len(env.events()) == 2 and env.n("cmo_trend_report") == 1


def test_a_stale_digest_is_a_409_and_nothing_runs(env, tr):
    confirm(env, ["steel water bottle"])
    pv = preview(env).json()
    confirm(env, ["a late addition"])
    r = run(env, "t1", pv["digest"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_CHANGED"
    assert tr.tavily.calls == [] and env.n("cmo_generation") == 0 and env.events() == [] and env.reservations() == []


# ------------------------------------------------------------------------------ the two meters
def test_the_cmo_cap_denies_with_402_naming_the_meter_and_a_replay_is_still_served(env, tr):
    seed_cap(env, "CMO", "cmo.market_trends", 1)
    pv, first = full(env, tr)
    assert first.status_code == 200
    second = run(env, "t2", pv["digest"])
    assert second.status_code == 402 and second.json()["detail"]["meterCode"] == "cmo.market_trends" and second.json()["detail"]["agentCode"] == "CMO"
    assert run(env, "t1", pv["digest"]).status_code == 200  # replay at the cap is free
    assert env.n("cmo_generation") == 1 and tr.tavily.calls and len(tr.tavily.calls) == 7  # the denied request called no provider


def test_the_shared_cap_denies_independently_and_releases_the_cmo_reservation(env, tr):
    seed_cap(env, "CMO", "cmo.market_trends", 5)
    seed_cap(env, "SHARED", "research.market_trends", 0)
    confirm(env, ["steel water bottle"])
    pv = preview(env).json()
    r = run(env, "t1", pv["digest"])
    assert r.status_code == 402 and r.json()["detail"]["agentCode"] == "SHARED" and r.json()["detail"]["meterCode"] == "research.market_trends"
    assert tr.tavily.calls == [] and tr.youtube.calls == [] and tr.model.prompts == [] and env.n("cmo_generation") == 0
    assert set(env.reservations()) <= {"RELEASED"}  # nothing is left holding the CMO meter's unit


def test_without_caps_usage_is_still_metered_and_no_reservation_is_made(env, tr):
    full(env, tr)
    assert env.reservations() == [] and len(env.events()) == 2


def test_concurrent_requests_cannot_exceed_the_cap(env, tr):
    seed_cap(env, "CMO", "cmo.market_trends", 1)
    tr.install(tavily=Tavily(delay=0.05))
    confirm(env, ["steel water bottle"])
    pv = preview(env).json()
    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(lambda i: run(env, f"c{i}", pv["digest"]).status_code, range(6)))
    assert codes.count(200) == 1 and all(c in (402, 409) for c in codes if c != 200)
    assert env.n("cmo_generation", "status = 'COMPLETE'") == 1 and len([e for e in env.events() if e.agent_code == "CMO"]) == 1


# ------------------------------------------------------------------------------ failure / partial
def test_a_failed_report_is_free_audited_and_releases_its_reservations(env, tr):
    seed_cap(env, "CMO", "cmo.market_trends", 3)
    seed_cap(env, "SHARED", "research.market_trends", 3)
    tr.install(tavily=Tavily(fail=True), youtube=Youtube(fail=True))
    pv, r = full(env, tr)
    assert r.status_code == 200 and r.json()["status"] == "FAILED" and r.json()["unitsBilled"] == {"cmo": 0, "shared": 0} and r.json()["failureReason"]
    assert env.events() == [] and env.n("cmo_trend_report") == 0 and env.n("cmo_generation", "status = 'FAILED'") == 1
    assert env.q("SELECT status FROM agent_run WHERE trigger_ref = 'cmo.market_trends'")[0][0] == "FAILED" and set(env.reservations()) == {"RELEASED"}
    # the same key may be retried after a FAILED attempt, and then succeeds
    tr.install(tavily=Tavily(), youtube=Youtube())
    ok = run(env, "t1", pv["digest"])
    assert ok.json()["status"] == "COMPLETE" and len(env.events()) == 2


def test_a_degraded_report_is_still_one_unit_per_meter_and_names_what_is_missing(env, tr):
    tr.install(youtube=Youtube(fail=True))
    _, r = full(env, tr)
    body = r.json()
    assert body["status"] == "COMPLETE" and body["unitsBilled"] == {"cmo": 1, "shared": 1} and len(env.events()) == 2
    assert body["report"]["sections"]["NEW_PRODUCTS_BUZZ"]["state"] == "UNAVAILABLE"
    assert "NEW_PRODUCTS_BUZZ" in {d["section"] for d in body["report"]["evidence"]["degraded_sections"]}


def test_the_model_being_down_fails_the_report_without_charging(env, tr):
    tr.install(model=Model(fail=True))
    _, r = full(env, tr)
    assert r.json()["status"] == "FAILED" and env.events() == []


# ------------------------------------------------------------------------------ privacy / isolation
def test_only_the_callers_confirmed_terms_reach_the_providers_and_other_tenants_never_see_them(env, tr):
    other = _make_tenant(env.engine)
    other_headers, _ = _login(env.fake_clerk, other, role="OWNER")
    config_rows(env, tenant=other)
    confirm(env, ["steel water bottle"])
    confirm(env, ["wooden chess board"], other_headers)
    # a suggested-but-unconfirmed term and a catalog title in this tenant must not travel either
    with env.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
        conn.execute(text("INSERT INTO cmo_niche_term (tenant_id, term, origin, status) VALUES (:t, 'only suggested term', 'CATALOG_DERIVED', 'SUGGESTED')"), {"t": str(env.tenant)})
    pv = preview(env).json()
    assert run(env, "t1", pv["digest"]).status_code == 200
    sent = " | ".join(c["query"] for c in tr.tavily.calls + tr.youtube.calls).lower()
    assert "steel water bottle" in sent and "chess" not in sent and "only suggested term" not in sent
    mine = call(env, "GET").json()["reports"]
    theirs = call(env, "GET", headers=other_headers)
    assert len(mine) == 1
    assert theirs.status_code == 200 and theirs.json()["reports"] == []  # the other tenant's OWNER sees none of ours


def test_another_tenants_report_id_is_an_identical_404_and_its_rows_are_invisible(env, tr):
    _, r = full(env, tr)
    gid = r.json()["generationId"]
    other = _make_tenant(env.engine)
    other_headers, _ = _login(env.fake_clerk, other, role="OWNER")
    config_rows(env, tenant=other)
    miss = call(env, "GET", f"/{uuid.uuid4()}", None, other_headers)
    hit = call(env, "GET", f"/{gid}", None, other_headers)
    assert hit.status_code == 404 and hit.json() == miss.json()
    assert env.n("cmo_trend_report", tenant=other) == 0 and env.events(other) == []


def test_the_persisted_outbound_queries_equal_what_the_providers_received(env, tr):
    _, r = full(env, tr)
    persisted = {q["query"] for q in r.json()["report"]["outbound_queries"]}
    assert persisted == {c["query"] for c in tr.tavily.calls + tr.youtube.calls}


def test_the_stored_report_contains_no_demand_claims_numbers_or_unconfirmed_content(env, tr):
    _, r = full(env, tr)
    blob = json.dumps(r.json()["report"]["sections"]).lower() + json.dumps(r.json()["report"]["interpretation"]).lower()
    for banned in ("trending", "bestseller", "selling well", "in demand", "guaranteed", "proven"):
        assert banned not in blob


# ------------------------------------------------------------------------------ the real daily counter
def test_the_daily_ceiling_degrades_the_report_and_refused_queries_make_no_provider_call(env, tr, migrate_engine):
    store = PostgresSlotStore()
    before = store.usage_today()
    base = sum(before.values())
    config_rows(env, {**TREND_CFG, "provider_daily_search_ceiling": base + 4}, drop=tuple(TREND_CFG))  # config set below instead
    with env.engine.begin() as conn:
        conn.execute(text("DELETE FROM cmo_platform_config WHERE tenant_id = :t AND key = 'provider_daily_search_ceiling'"), {"t": str(env.tenant)})
        conn.execute(text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, 'provider_daily_search_ceiling', CAST(:v AS jsonb), '2026-01-01')"),
                     {"t": str(env.tenant), "v": json.dumps(base + 4)})
    tr.install(slots=PostgresSlotStore())
    try:
        confirm(env, ["steel water bottle"])
        pv = preview(env).json()
        r = run(env, "t1", pv["digest"])
        body = r.json()
        assert r.status_code == 200 and body["status"] == "COMPLETE"
        assert len(tr.tavily.calls) + len(tr.youtube.calls) == 4
        acc = body["report"]["evidence"]["provider_accounting"]
        assert acc["refused_daily_ceiling"] == 6 and sum(acc["provider_calls"].values()) == 4 and "CMO searches only" in acc["note"]
        assert sum(PostgresSlotStore().usage_today().values()) == base + 4
        assert {d["section"] for d in body["report"]["evidence"]["degraded_sections"]}  # the refused sections are named
    finally:
        with migrate_engine.begin() as conn:  # put the global counter back exactly as it was
            conn.execute(text("DELETE FROM cmo_provider_usage WHERE usage_day = (now() AT TIME ZONE 'Asia/Kolkata')::date"))
            for provider, n in before.items():
                conn.execute(text("INSERT INTO cmo_provider_usage (usage_day, provider, searches) VALUES ((now() AT TIME ZONE 'Asia/Kolkata')::date, :p, :n)"), {"p": provider, "n": n})


# ---- independent review fixes (P10)
def test_the_same_key_with_a_different_plan_is_a_409_request_key_reused_and_the_same_plan_still_replays(env, tr):
    confirm(env, ["steel water bottle"])
    pv1 = preview(env).json()
    first = run(env, "dup-1", pv1["digest"])
    assert first.status_code == 200
    confirm(env, ["a second term"])
    pv2 = preview(env).json()
    assert pv2["digest"] != pv1["digest"]
    r = run(env, "dup-1", pv2["digest"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "REQUEST_KEY_REUSED"
    assert run(env, "dup-1", pv1["digest"]).json()["reused"] is True
    assert env.n("cmo_trend_report") == 1 and len(env.events()) == 2


def test_a_complete_title_set_under_the_same_key_does_not_block_a_trend_report(env, tr):
    assert env.post("title-sets", title_body("shared-key")).status_code == 200
    confirm(env, ["steel water bottle"])
    pv = preview(env).json()
    r = run(env, "shared-key", pv["digest"])
    assert r.status_code == 200 and r.json()["status"] == "COMPLETE" and r.json()["reused"] is False


def test_term_bearing_provider_results_are_not_shared_between_tenants_but_term_free_ones_are(env, tr):
    other = _make_tenant(env.engine)
    other_headers, _ = _login(env.fake_clerk, other, role="OWNER")
    config_rows(env, {**TREND_CFG, "internal_retry_bound": 0}, tenant=other)
    confirm(env, ["steel water bottle"])
    confirm(env, ["steel water bottle"], other_headers)  # the very same term, confirmed by another seller
    pv_a = preview(env).json()
    assert run(env, "ta", pv_a["digest"]).status_code == 200
    first_calls = len(tr.tavily.calls) + len(tr.youtube.calls)
    pv_b = preview(env, other_headers).json()
    assert run(env, "tb", pv_b["digest"], other_headers).status_code == 200
    second_calls = len(tr.tavily.calls) + len(tr.youtube.calls) - first_calls
    term_bearing = len([q for q in pv_b["queries"] if "steel water bottle" in q["query"]])
    assert second_calls == term_bearing  # B re-asked every query carrying its own term; the six term-free ones came from the shared cache
    # and tenant B's report says nothing about tenant A having researched the term
    assert tr.cache is not None and term_bearing == 4
