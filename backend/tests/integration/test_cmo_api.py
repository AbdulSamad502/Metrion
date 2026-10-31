"""P5 end-to-end: authenticated Slim CMO routes against a real Postgres (spec §8, entitlement.md, auth.md).

Real: FastAPI app, auth chain (only Clerk is faked), P3/P4 services, Postgres store, entitlement
resolution, quota reservations, metering. Faked: the model provider (a deterministic router). Every
tenant-owned row a test creates is erased by `_erase_cmo_rows`, then the shared tenant purge runs."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from slim_cmo.generation.provider import LlmUnavailable
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.service.approve import ApprovalService
from slim_cmo.service.catalog import CatalogService
from slim_cmo.service.generate import GenerationService
from slim_cmo.types import ConstraintRowKind as K

from backend import config
from backend.entitlement import cmo_metering_key, resolve_cmo_entitlement
from backend.repositories import app_user_repo, cmo_quota_repo, membership_repo
from backend.services import cmo_actions, cmo_runtime
from backend.services.cmo_runtime import CmoRuntime
from testkit.tenant_cleanup import TRACKER as _tenant_tracker

_APP_URL = os.environ.get("DATABASE_URL_APP")
_MIGRATE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not _APP_URL or not _MIGRATE_URL, reason="DATABASE_URL_APP/DATABASE_URL not set")

_REAL_BUILD_RUNTIME = cmo_runtime.build_runtime
AMAZON, FLIPKART, MEESHO = "AMAZON", "FLIPKART", "MEESHO"
TITLES = ["AquaKeep Steel Bottle", "AquaKeep Insulated Flask", "AquaKeep Water Bottle"]
PACK = {"description": "A steel bottle from AquaKeep for everyday use.", "bullets": ["Stainless steel build", "Easy to carry", "Simple to clean"],
        "keywords": ["steel bottle", "water bottle"]}

_CMO_TENANT_TABLES = ("cmo_perf_line", "cmo_perf_import", "cmo_perf_setting", "cmo_listing_golive", "cmo_listing_sku_link", "cmo_listing_audit", "cmo_readiness_assessment", "cmo_buyer_question_set", "cmo_title_analysis", "cmo_keyword_analysis", "cmo_trend_report", "seller_fact", "cmo_niche_term", "cmo_title_approval", "cmo_title_option", "cmo_generation",
                      "product_image_analysis", "seller_image_asset", "cmo_quota_reservation", "cmo_platform_config")


# ---- infrastructure ---------------------------------------------------------------------------


@pytest.fixture
def ctx_engine():
    """A NullPool owner-role engine for every statement that sets tenant context: `set_config(..., true)` leaves
    an empty-string GUC on a POOLED connection, which would break the shared fixtures' later unscoped cleanup."""
    engine = create_engine(_MIGRATE_URL, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _erase_cmo_rows(migrate_engine, ctx_engine):
    """slim-cmo's `cmo_generation` and `cmo_title_approval` reference each other at table level, which the generic
    tenant purge cannot order: erase them here (constraints deferred, per tenant) BEFORE that purge runs."""
    yield
    for tenant in sorted(set(_tenant_tracker.tenants), key=str):
        with ctx_engine.begin() as conn:
            conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            for table in _CMO_TENANT_TABLES:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": str(tenant)})
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM format_constraint WHERE row_kind = 'TEST_FIXTURE'"))


@dataclass
class _AuthState:
    is_signed_in: bool
    payload: dict[str, Any] | None


@dataclass
class _FakeClerk:
    tokens: dict[str, tuple[str, str | None]] = field(default_factory=dict)

    async def authenticate_request_async(self, request: Any, options: Any) -> _AuthState:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if token in self.tokens:
            user, org = self.tokens[token]
            return _AuthState(True, {"sub": user, "org_id": org})
        return _AuthState(False, None)


@pytest.fixture
def fake_clerk(monkeypatch):
    from backend.auth import context as auth_context

    client = _FakeClerk()
    monkeypatch.setattr(auth_context, "get_clerk_client", lambda: client)
    return client


def _make_tenant(migrate_engine) -> uuid.UUID:
    tid = uuid.uuid4()
    with migrate_engine.begin() as conn:
        conn.execute(text("INSERT INTO tenant (id, clerk_org_id, business_name, status, created_at) VALUES (:id, :org, 'Test Tenant', 'ACTIVE', now())"),
                     {"id": str(tid), "org": f"org_{tid}"})
    return tid


def _login(fake_clerk, tenant: uuid.UUID, *, role: str, permissions: dict[str, object] | None = None) -> tuple[dict[str, str], uuid.UUID]:
    user = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(clerk_user_id=user, email=f"{user}@example.com", email_verified=True, auth_provider="GOOGLE", display_name="T")
    row = app_user_repo.get_by_clerk_user_id(user)
    membership_repo.upsert_partner(tenant, row["id"], role=role, status="ACTIVE")
    if permissions is not None:
        membership_repo.set_permissions(tenant, row["id"], permissions)
    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (user, f"org_{tenant}")
    return {"Authorization": f"Bearer {token}"}, uuid.UUID(str(row["id"]))


class RoutingProvider:
    """Deterministic stand-in for the model: answers by the artefact shape the prompt asks for."""

    def __init__(self, mode: str = "ok", delay: float = 0.0) -> None:
        self.mode, self.delay, self.calls, self.prompts = mode, delay, 0, []
        self._lock = threading.Lock()

    def complete(self, *, model: str, prompt: str) -> str:
        with self._lock:
            self.calls += 1
            self.prompts.append(prompt)
        if self.delay:
            time.sleep(self.delay)
        if self.mode == "raise":
            raise LlmUnavailable("boom-secret-token http://internal-ollama:11434")
        if self.mode == "garbage":
            return "this is not json at all SECRET-RAW-MODEL-OUTPUT"
        shape = prompt.split("Reply shape:")[1].split("\n")[0]
        if '"bullets"' in shape and '"keywords"' in shape:
            return json.dumps(PACK)
        if '"titles"' in shape:
            return json.dumps({"titles": TITLES})
        if '"hashtags"' in shape:
            return json.dumps({"hashtags": ["#steelbottle", "#aquakeep"]})
        if '"terms"' in shape:
            return json.dumps({"terms": ["steel flask", "water bottle"]})
        if '"bullets"' in shape:
            return json.dumps({"bullets": PACK["bullets"]})
        if '"keywords"' in shape:
            return json.dumps({"keywords": PACK["keywords"]})
        return json.dumps({"description": PACK["description"]})


def _seed_rules(migrate_engine, tenant: uuid.UUID, *, marketplaces=(AMAZON, FLIPKART, MEESHO), config_values=None) -> None:
    values = {"format_constraint_max_age_days": 30, "internal_retry_bound": 0, "hashtag_set_size": 3} if config_values is None else config_values
    with migrate_engine.begin() as conn:
        for mp in marketplaces:
            conn.execute(text(
                "INSERT INTO format_constraint (marketplace, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type, "
                "description_max_chars, keywords_max_count, keywords_max_chars, backend_terms_max_bytes, count_rule, source_url, verified_at, version, row_kind) "
                "VALUES (:mp, 80, 3, 3, 100, 'plain', 500, 10, 40, :bt, 'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture', now(), 1, 'TEST_FIXTURE')"),
                {"mp": mp, "bt": 249 if mp == AMAZON else None})
        for k, v in values.items():
            conn.execute(text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, :k, CAST(:v AS jsonb), '2026-01-01')"),
                         {"t": str(tenant), "k": k, "v": json.dumps(v)})


def seed_cap(migrate_engine, meter: str, cap: int) -> None:
    with migrate_engine.begin() as conn:
        conn.execute(text("INSERT INTO entitlement_cap_config (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version) "
                          "VALUES (:id, NULL, 'CMO', :m, 'TENANT', 'MONTH', :c, '2026-01-01', 1)"), {"id": str(uuid.uuid4()), "m": meter, "c": cap})


def seed_analysis(ctx_engine, tenant: uuid.UUID, attrs: list[dict[str, Any]]) -> uuid.UUID:
    asset, analysis = uuid.uuid4(), uuid.uuid4()
    with ctx_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
        conn.execute(text("INSERT INTO seller_image_asset (id, tenant_id, storage_uri, sha256, content_type, byte_size, uploaded_by, status) "
                          "VALUES (:id, :t, 'file:///x', :sha, 'image/jpeg', 10, :u, 'ACTIVE')"),
                     {"id": str(asset), "t": str(tenant), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": str(uuid.uuid4())})
        conn.execute(text("INSERT INTO product_image_analysis (id, tenant_id, image_asset_id, schema_version, provider, model, attributes, analysis_state) "
                          "VALUES (:id, :t, :a, 'v1', 'test', 'test', CAST(:attrs AS jsonb), 'COMPLETE')"),
                     {"id": str(analysis), "t": str(tenant), "a": str(asset), "attrs": json.dumps(attrs)})
    return analysis


class Env:
    def __init__(self, migrate_engine, ctx_engine, tenant, headers, user_id, provider, runtime, monkeypatch, fake_clerk):
        self.engine, self.cengine, self.tenant, self.headers, self.user_id = migrate_engine, ctx_engine, tenant, headers, user_id
        self.provider, self.runtime, self.monkeypatch, self.fake_clerk = provider, runtime, monkeypatch, fake_clerk

    def client(self):
        from fastapi.testclient import TestClient

        from backend.main import app

        return TestClient(app)

    def post(self, path: str, body: dict[str, Any], headers: dict[str, str] | None = None, client=None):
        return (client or self.client()).post(f"/api/v1/cmo/{path}", json=body, headers=self.headers if headers is None else headers)

    def q(self, sql: str, tenant: uuid.UUID | None = None, **params: Any):
        with self.cengine.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant or self.tenant)})
            return conn.execute(text(sql), params).all()

    def n(self, table: str, where: str = "true", tenant: uuid.UUID | None = None, **params: Any) -> int:
        return int(self.q(f"SELECT count(*) FROM {table} WHERE {where}", tenant, **params)[0][0])

    def events(self, tenant=None):
        return self.q("SELECT idempotency_key, event_kind, quantity, source_ref, agent_run_id, agent_code, meter_code FROM metered_event ORDER BY occurred_at", tenant)

    def reservations(self, tenant=None):
        return [r[0] for r in self.q("SELECT state FROM cmo_quota_reservation ORDER BY created_at", tenant)]

    def other_tenant(self):
        t = _make_tenant(self.engine)
        headers, uid = _login(self.fake_clerk, t, role="OWNER")
        _seed_rules(self.engine, t, config_values={"format_constraint_max_age_days": 30, "internal_retry_bound": 0, "hashtag_set_size": 3}, marketplaces=())
        return t, headers


def _install(monkeypatch, provider, **kw) -> CmoRuntime:
    store = PostgresGenerationStore()
    kinds = frozenset({K.TEST_FIXTURE})
    clock = kw.get("clock") or cmo_runtime.utc_now
    rt = CmoRuntime(store=store, generation=GenerationService(store, provider, model="test-model", clock=clock, accepted_row_kinds=kinds),
                    approvals=ApprovalService(store, clock=clock, accepted_row_kinds=kinds), catalog=CatalogService(store), clock=clock)
    monkeypatch.setattr(cmo_runtime, "build_runtime", lambda **_kw: rt)
    return rt


@pytest.fixture
def env(migrate_engine, ctx_engine, fake_clerk, monkeypatch):
    monkeypatch.setenv("CMO_QUOTA_RESERVATION_TTL_SECONDS", "300")
    config.cmo_quota_reservation_ttl_seconds.cache_clear()
    tenant = _make_tenant(migrate_engine)
    headers, uid = _login(fake_clerk, tenant, role="OWNER")
    _seed_rules(migrate_engine, tenant)
    provider = RoutingProvider()
    rt = _install(monkeypatch, provider)
    yield Env(migrate_engine, ctx_engine, tenant, headers, uid, provider, rt, monkeypatch, fake_clerk)
    config.cmo_quota_reservation_ttl_seconds.cache_clear()


def title_body(key: str, mps=(AMAZON,), **extra: Any) -> dict[str, Any]:
    return {"request_key": key, "sku": "SKU1", "brand": "AquaKeep", "marketplaces": list(mps), **extra}


TS_METER = "cmo.generate_title_sets"


# ---- authentication / authorisation / isolation -------------------------------------------------


def test_unauthenticated_requests_are_401_and_do_nothing(env):
    for path, body in (("title-sets", title_body("k")), ("catalog-answers", {"request_key": "k", "questions": ["COLOR"]}),
                       ("title-approvals", {"generation_id": str(uuid.uuid4()), "option_id": str(uuid.uuid4())}),
                       ("image-hints/confirm", {"analysis_id": str(uuid.uuid4()), "attribute_name": "color", "sku": "S"})):
        assert env.post(path, body, headers={}).status_code == 401
        assert env.post(path, body, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert env.provider.calls == 0 and env.n("cmo_generation") == 0 and env.n("agent_run") == 0


def test_missing_agent_cmo_permission_is_403_and_a_granted_partner_works(env):
    from backend.auth.permissions import PARTNER_ROLE

    denied, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={})
    r = env.post("title-sets", title_body("k1"), headers=denied)
    assert r.status_code == 403 and "agent.cmo" in json.dumps(r.json())
    assert env.provider.calls == 0 and env.n("cmo_generation") == 0
    allowed, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    assert env.post("title-sets", title_body("k2"), headers=allowed).status_code == 200


def test_wrong_tenant_ids_are_404_and_leak_nothing(env):
    other, other_headers = env.other_tenant()
    ts = env.post("title-sets", title_body("a1")).json()
    gen_id, opt_id = ts["artefacts"][0]["id"], ts["artefacts"][0]["options"][0]["id"]
    approval = env.post("title-approvals", {"generation_id": gen_id, "option_id": opt_id}).json()["approvalId"]
    analysis = seed_analysis(env.cengine, env.tenant, [{"name": "color", "value": "blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}])
    before = env.n("cmo_generation")

    attempts = [
        ("title-approvals", {"generation_id": gen_id, "option_id": opt_id}),
        ("title-approvals", {"generation_id": gen_id, "edited_text": "AquaKeep Mug"}),
        ("listing-copy", {**title_body("b1"), "marketplace": AMAZON, "approval_id": approval}),
        ("catalog-answers", {"request_key": "b2", "questions": ["COLOR"], "image_analysis_id": str(analysis)}),
        ("image-hints/confirm", {"analysis_id": str(analysis), "attribute_name": "color", "sku": "SKU1"}),
    ]
    for path, body in attempts:
        body = {k: v for k, v in body.items() if k not in ("marketplaces",)}
        r = env.post(path, body, headers=other_headers)
        assert r.status_code == 404, (path, r.status_code, r.text)
        assert r.json() == {"detail": "Not found"}
    assert env.n("cmo_generation", tenant=other) == 0 and env.n("seller_fact", tenant=other) == 0 and env.events(other) == []
    assert env.n("cmo_generation") == before  # nothing happened to the owning tenant either


def test_a_client_supplied_tenant_member_meter_or_cap_is_a_422(env):
    other, _ = env.other_tenant()
    for extra in ({"tenant_id": str(other)}, {"member_id": str(env.user_id)}, {"meter_code": "x"}, {"cap_value": 99}, {"units": 0}):
        r = env.post("title-sets", {**title_body("k"), **extra})
        assert r.status_code == 422, extra
    assert env.n("cmo_generation") == 0 and env.n("cmo_generation", tenant=other) == 0 and env.provider.calls == 0


# ---- the happy path, billing and the agent_run contract -------------------------------------------


def test_one_successful_artefact_is_exactly_one_metered_event_and_one_agent_run(env):
    r = env.post("title-sets", title_body("ok1"))
    assert r.status_code == 200, r.text
    body = r.json()
    art = body["artefacts"][0]
    assert body["runStatus"] == "COMPLETE" and body["unitsBilled"] == 1 and art["status"] == "COMPLETE" and art["reused"] is False
    assert [o["text"] for o in art["options"]] == TITLES and art["constraint"]["sourceUrl"] == "https://example.invalid/test-fixture"
    events = env.events()
    assert len(events) == 1
    key, kind, qty, source_ref, run_id, agent, meter = events[0]
    assert (key, kind, qty, agent, meter) == (cmo_metering_key(uuid.UUID(art["id"])), TS_METER, 1, "CMO", TS_METER)
    assert str(source_ref) == art["id"] and str(run_id) == body["agentRunId"]
    runs = env.q("SELECT agent_id, trigger_type, trigger_ref, status, permission_check, entitlement_check, requested_by FROM agent_run")
    assert len(runs) == 1 and tuple(runs[0])[:6] == ("CMO", "DIRECT", TS_METER, "COMPLETE", "PASS", "PASS") and runs[0][6] == env.user_id
    assert env.q("SELECT agent_run_id FROM cmo_generation")[0][0] == uuid.UUID(body["agentRunId"])


def test_without_a_cap_nothing_is_reserved_but_usage_is_still_metered(env):
    assert env.post("title-sets", title_body("nc")).status_code == 200
    assert env.reservations() == [] and len(env.events()) == 1


def test_same_request_key_replay_reuses_the_result_the_run_and_the_event(env):
    seed_cap(env.engine, TS_METER, 2)
    first = env.post("title-sets", title_body("rep", (AMAZON, FLIPKART))).json()
    assert first["unitsBilled"] == 2 and first["runStatus"] == "COMPLETE"
    runs, events, rows, resv = env.n("agent_run"), len(env.events()), env.n("cmo_generation"), env.reservations()
    again = env.post("title-sets", title_body("rep", (AMAZON, FLIPKART)))
    assert again.status_code == 200
    body = again.json()
    assert all(a["reused"] for a in body["artefacts"]) and body["unitsBilled"] == 0
    assert [a["id"] for a in body["artefacts"]] == [a["id"] for a in first["artefacts"]] and body["agentRunId"] == first["agentRunId"]
    assert (env.n("agent_run"), len(env.events()), env.n("cmo_generation"), env.reservations()) == (runs, events, rows, resv)


def test_distinct_requests_under_the_cap_all_succeed_and_settle_their_reservations(env):
    seed_cap(env.engine, TS_METER, 5)
    for i in range(3):
        assert env.post("title-sets", title_body(f"d{i}")).status_code == 200
    assert len(env.events()) == 3 and env.reservations() == ["SETTLED"] * 3
    ent = resolve_cmo_entitlement(env.tenant, direct_action_code=TS_METER)
    assert (ent.usage_count, ent.cap_value) == (3, 5)  # reservations are not billing records: usage counts metered events only


def test_a_replay_at_the_cap_is_still_served_and_free(env):
    seed_cap(env.engine, TS_METER, 1)
    first = env.post("title-sets", title_body("only"))
    assert first.status_code == 200
    again = env.post("title-sets", title_body("only"))
    assert again.status_code == 200 and again.json()["artefacts"][0]["reused"] is True
    assert len(env.events()) == 1


def test_workflow_title_set_approval_listing_copy_is_two_units_and_three_runs(env):
    ts = env.post("title-sets", title_body("w1")).json()["artefacts"][0]
    approval = env.post("title-approvals", {"generation_id": ts["id"], "option_id": ts["options"][0]["id"]})
    assert approval.status_code == 200 and approval.json()["unitsBilled"] == 0
    copy = env.post("listing-copy", {"request_key": "w2", "sku": "SKU1", "brand": "AquaKeep", "marketplace": AMAZON, "approval_id": approval.json()["approvalId"]})
    assert copy.status_code == 200, copy.text
    art = copy.json()["artefacts"][0]
    assert art["description"] and art["bullets"] == PACK["bullets"] and art["constraint"]["sourceUrl"]
    assert len(env.events()) == 2 and env.n("agent_run") == 3  # approval wrote a run and no event
    assert {e[1] for e in env.events()} == {TS_METER, "cmo.generate_listing_copy"}


def test_catalog_answers_bill_one_unit_per_marketplace_and_hashtags_one_unit(env):
    r = env.post("catalog-answers", {"request_key": "c1", "sku": "S", "questions": ["COLOR", "WEIGHT"], "attributes": [{"name": "colour", "value": "red"}],
                                     "marketplaces": [AMAZON, FLIPKART]})
    assert r.status_code == 200, r.text
    arts = r.json()["artefacts"]
    assert r.json()["unitsBilled"] == 2 and {a["marketplace"] for a in arts} == {AMAZON, FLIPKART}
    by = {x["attribute"]: x for x in arts[0]["attributes"]}
    assert by["COLOR"]["basis"] == "SELLER_PROVIDED" and by["WEIGHT"]["basis"] == "UNKNOWN" and "source_fact_id" not in json.dumps(arts[0]) and "sourceFactId" not in json.dumps(arts[0])
    assert env.post("hashtags", {"request_key": "h1", "brand": "AquaKeep"}).json()["unitsBilled"] == 1
    assert len(env.events()) == 3


# ---- entitlement, quota, concurrency ----------------------------------------------------------------


def test_a_cap_of_zero_denies_before_any_work_or_write(env):
    seed_cap(env.engine, TS_METER, 0)
    r = env.post("title-sets", title_body("z"))
    assert r.status_code == 402
    assert r.json()["detail"] == {"reason": "OVER_CAP", "meterCode": TS_METER, "evaluationBasis": "OVER_CAP", "cap": 0, "usage": 0, "reserved": 0, "requested": 1, "remaining": 0}
    assert env.provider.calls == 0 and env.n("cmo_generation") == 0 and env.n("agent_run") == 0 and env.reservations() == [] and env.n("seller_fact") == 0


def test_cap_exhausted_is_a_402_with_no_execution_and_the_first_result_is_intact(env):
    seed_cap(env.engine, TS_METER, 1)
    assert env.post("title-sets", title_body("c1")).status_code == 200
    calls, rows = env.provider.calls, env.n("cmo_generation")
    r = env.post("title-sets", title_body("c2"))
    assert r.status_code == 402 and r.json()["detail"]["remaining"] == 0 and r.json()["detail"]["usage"] == 1
    assert (env.provider.calls, env.n("cmo_generation"), len(env.events())) == (calls, rows, 1)


def test_the_quota_precheck_is_all_or_nothing_for_a_multi_marketplace_request(env):
    seed_cap(env.engine, TS_METER, 2)
    r = env.post("title-sets", title_body("m3", (AMAZON, FLIPKART, MEESHO)))
    assert r.status_code == 402
    d = r.json()["detail"]
    assert (d["requested"], d["remaining"]) == (3, 2) and env.provider.calls == 0 and env.n("cmo_generation") == 0
    assert env.post("title-sets", title_body("m2", (AMAZON, FLIPKART))).status_code == 200


def test_a_missing_reservation_ttl_with_a_cap_is_503_cmo_not_configured_and_writes_nothing(env):
    seed_cap(env.engine, TS_METER, 3)
    env.monkeypatch.delenv("CMO_QUOTA_RESERVATION_TTL_SECONDS")
    config.cmo_quota_reservation_ttl_seconds.cache_clear()
    r = env.post("title-sets", title_body("t1"))
    assert r.status_code == 503 and r.json()["detail"] == {"code": "CMO_NOT_CONFIGURED"}
    assert env.provider.calls == 0 and env.n("cmo_generation") == 0 and env.reservations() == [] and env.n("agent_run") == 0


@pytest.mark.parametrize("cap,threads", [(1, 8), (3, 12)])
def test_concurrent_requests_cannot_exceed_the_cap(env, cap, threads):
    seed_cap(env.engine, TS_METER, cap)
    env.provider.delay = 0.25
    barrier = threading.Barrier(threads)

    def go(i: int) -> int:
        client = env.client()
        barrier.wait()
        return env.post("title-sets", title_body(f"race-{i}"), client=client).status_code

    with ThreadPoolExecutor(max_workers=threads) as pool:
        statuses = sorted(pool.map(go, range(threads)))
    assert statuses.count(200) == cap and statuses.count(402) == threads - cap, statuses
    assert len(env.events()) == cap and env.n("cmo_generation", "status = 'COMPLETE'") == cap and env.provider.calls == cap
    assert sorted(env.reservations()) == ["SETTLED"] * cap  # denied requests never held a reservation


def test_concurrent_identical_requests_run_once(env):
    seed_cap(env.engine, TS_METER, 1)
    env.provider.delay = 0.4
    barrier = threading.Barrier(6)

    def go(_: int):
        client = env.client()
        barrier.wait()
        r = env.post("title-sets", title_body("same-key"), client=client)
        return r.status_code, (r.json()["artefacts"][0]["reused"] if r.status_code == 200 else r.json()["detail"])

    with ThreadPoolExecutor(max_workers=6) as pool:
        out = list(pool.map(go, range(6)))
    ok = [o for o in out if o[0] == 200]
    assert len([o for o in ok if o[1] is False]) == 1                       # exactly one executed
    assert all(o[0] in (200, 409) for o in out) and all(o[1] == {"code": "REQUEST_IN_PROGRESS"} for o in out if o[0] == 409)
    assert env.provider.calls == 1 and env.n("cmo_generation", "status = 'COMPLETE'") == 1 and len(env.events()) == 1 and env.n("agent_run") == 1


def test_reservations_expire_serialize_and_are_never_billing(env):
    t0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    args = dict(agent_code="CMO", meter_code="m", period_key="2026-10", cap_value=1, ttl_seconds=300)
    first = cmo_quota_repo.reserve(env.tenant, units=1, request_key="a", now=t0, **args)
    assert isinstance(first, cmo_quota_repo.Reserved)
    denied = cmo_quota_repo.reserve(env.tenant, units=1, request_key="b", now=t0 + timedelta(seconds=10), **args)
    assert isinstance(denied, cmo_quota_repo.ReserveDenied) and (denied.reserved_units, denied.metered_units) == (1, 0)
    with pytest.raises(cmo_quota_repo.ReservationInProgress):
        cmo_quota_repo.reserve(env.tenant, units=0 + 1, request_key="a", now=t0 + timedelta(seconds=11), **{**args, "cap_value": 5})
    again = cmo_quota_repo.reserve(env.tenant, units=1, request_key="b", now=t0 + timedelta(seconds=301), **args)  # the first one expired
    assert isinstance(again, cmo_quota_repo.Reserved)
    assert env.reservations() == ["RELEASED", "RESERVED"]
    assert env.events() == []  # a reservation is not a metered event


# ---- failure and settlement semantics -----------------------------------------------------------------


def test_a_failed_artefact_is_persisted_free_and_does_not_consume_the_cap(env):
    seed_cap(env.engine, TS_METER, 1)
    env.provider.mode = "garbage"
    r = env.post("title-sets", title_body("f1"))
    body = r.json()
    assert r.status_code == 200 and body["runStatus"] == "FAILED" and body["unitsBilled"] == 0
    art = body["artefacts"][0]
    assert art["status"] == "FAILED" and art["failure"]["code"] == "UNPARSEABLE_OUTPUT" and "options" not in art
    assert "SECRET-RAW-MODEL-OUTPUT" not in r.text and "Reply shape" not in r.text
    assert env.events() == [] and env.n("cmo_generation", "status = 'FAILED'") == 1 and env.reservations() == ["SETTLED"]
    assert env.n("agent_run", "status = 'FAILED'") == 1
    env.provider.mode = "ok"
    assert env.post("title-sets", title_body("f2")).status_code == 200  # the cap of 1 is still available
    assert len(env.events()) == 1


def test_a_partial_run_bills_only_the_delivered_artefacts(env):
    with env.engine.begin() as conn:
        conn.execute(text("DELETE FROM format_constraint WHERE row_kind='TEST_FIXTURE' AND marketplace='FLIPKART'"))
    seed_cap(env.engine, TS_METER, 3)
    body = env.post("title-sets", title_body("p1", (AMAZON, FLIPKART, MEESHO))).json()
    assert body["runStatus"] == "PARTIAL" and body["unitsBilled"] == 2
    assert [a["status"] for a in body["artefacts"]] == ["COMPLETE", "FAILED", "COMPLETE"]
    assert body["artefacts"][1]["failure"]["code"] == "CONSTRAINT_BLOCKED"
    assert len(env.events()) == 2 and resolve_cmo_entitlement(env.tenant, direct_action_code=TS_METER).usage_count == 2
    assert env.reservations() == ["SETTLED"]


def test_domain_configuration_missing_is_a_persisted_failed_artefact_with_no_model_call_or_billing(migrate_engine, ctx_engine, fake_clerk, monkeypatch):
    monkeypatch.setenv("CMO_QUOTA_RESERVATION_TTL_SECONDS", "300")
    config.cmo_quota_reservation_ttl_seconds.cache_clear()
    tenant = _make_tenant(migrate_engine)
    headers, uid = _login(fake_clerk, tenant, role="OWNER")
    _seed_rules(migrate_engine, tenant, config_values={"hashtag_set_size": 3})  # the generation keys are absent
    provider = RoutingProvider()
    rt = _install(monkeypatch, provider)
    e = Env(migrate_engine, ctx_engine, tenant, headers, uid, provider, rt, monkeypatch, fake_clerk)
    r = e.post("title-sets", title_body("cm"))
    assert r.status_code == 200 and r.json()["artefacts"][0]["failure"]["code"] == "CONFIG_MISSING"
    assert provider.calls == 0 and e.events() == [] and e.n("cmo_generation", "status = 'FAILED'") == 1


def test_missing_runtime_configuration_is_503_before_any_write(env):
    env.monkeypatch.setattr(cmo_runtime, "build_runtime", _REAL_BUILD_RUNTIME)
    for name in ("CMO_LLM_MODEL", "CMO_OLLAMA_HOST", "CMO_LLM_TIMEOUT_SECONDS"):
        env.monkeypatch.delenv(name, raising=False)
    for fn in (config.cmo_llm_model, config.cmo_ollama_host, config.cmo_llm_timeout_seconds):
        fn.cache_clear()
    for path, body in (("title-sets", title_body("n1")), ("catalog-answers", {"request_key": "n2", "questions": ["COLOR"]}),
                       ("title-approvals", {"generation_id": str(uuid.uuid4()), "option_id": str(uuid.uuid4())})):
        r = env.post(path, body)
        assert r.status_code == 503 and r.json()["detail"] == {"code": "CMO_NOT_CONFIGURED"}, path
        assert "CMO_LLM_MODEL" not in r.text
    assert env.n("cmo_generation") == 0 and env.n("agent_run") == 0 and env.n("seller_fact") == 0


def test_provider_failure_is_a_failed_artefact_not_a_500_and_leaks_nothing(env):
    env.provider.mode = "raise"
    r = env.post("title-sets", title_body("pf"))
    assert r.status_code == 200 and r.json()["artefacts"][0]["failure"]["code"] == "PROVIDER_ERROR"
    assert "boom-secret-token" not in r.text and "internal-ollama" not in r.text and env.events() == []


def test_an_unexpected_execution_failure_is_a_generic_500_releases_the_reservation_and_charges_nothing(env):
    seed_cap(env.engine, TS_METER, 1)

    def boom(*a, **k):
        raise RuntimeError("psycopg.errors.UndefinedTable secret_tbl; password=hunter2")

    real = env.runtime.generation.generate_title_sets
    env.monkeypatch.setattr(env.runtime.generation, "generate_title_sets", boom)
    r = env.post("title-sets", title_body("u1"))
    assert r.status_code == 500 and r.json() == {"detail": {"code": "INTERNAL_ERROR"}}
    assert "hunter2" not in r.text and "secret_tbl" not in r.text
    assert env.reservations() == ["RELEASED"] and env.events() == [] and env.n("agent_run", "status = 'FAILED'") == 1
    env.monkeypatch.setattr(env.runtime.generation, "generate_title_sets", real)
    assert env.post("title-sets", title_body("u2")).status_code == 200  # the single unit of cap is untouched


def test_a_failed_metering_write_never_blocks_delivery_keeps_the_quota_held_and_is_reconciled_on_replay(env):
    seed_cap(env.engine, TS_METER, 1)
    real = cmo_actions.record_metered_event
    env.monkeypatch.setattr(cmo_actions, "record_metered_event", lambda *a, **k: None)
    first = env.post("title-sets", title_body("mw"))
    assert first.status_code == 200 and first.json()["artefacts"][0]["status"] == "COMPLETE"      # delivered despite the write failing
    assert env.events() == [] and env.reservations() == ["RESERVED"]                                # unmetered, but still protecting the cap
    assert env.post("title-sets", title_body("other")).status_code == 402                           # so it cannot be used to exceed the cap
    env.monkeypatch.setattr(cmo_actions, "record_metered_event", real)
    replay = env.post("title-sets", title_body("mw"))
    assert replay.status_code == 200 and replay.json()["artefacts"][0]["reused"] is True
    assert len(env.events()) == 1 and env.n("cmo_generation") == 1 and env.n("agent_run") == 1       # reconciled; nothing duplicated
    again = env.post("title-sets", title_body("mw"))
    assert again.status_code == 200 and len(env.events()) == 1                                       # settlement retry is idempotent


# ---- zero-unit actions ----------------------------------------------------------------------------------


def test_confirm_image_hint_is_zero_units_and_never_enters_billing(env):
    for m in ("cmo.confirm_image_hint", "cmo.approve_title", TS_METER):
        seed_cap(env.engine, m, 0)  # even a zero cap on every CMO meter cannot block or bill a zero-unit action
    attrs = [{"name": "color", "value": "matte blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}]
    analysis = seed_analysis(env.cengine, env.tenant, attrs)
    r = env.post("image-hints/confirm", {"analysis_id": str(analysis), "attribute_name": "color", "sku": "SKU1"})
    assert r.status_code == 200 and r.json()["created"] is True and r.json()["unitsBilled"] == 0
    assert env.events() == [] and env.n("cmo_generation") == 0 and env.reservations() == []
    fact = env.q("SELECT fact_type, attribute_name, fact_value, image_analysis_id FROM seller_fact")
    assert len(fact) == 1 and tuple(fact[0]) == ("ATTRIBUTE", "color", "matte blue", analysis)
    assert env.q("SELECT attributes FROM product_image_analysis")[0][0] == attrs  # the analysis row is untouched: still an unverified hint
    assert env.n("agent_run", "trigger_ref = 'cmo.confirm_image_hint'") == 1
    again = env.post("image-hints/confirm", {"analysis_id": str(analysis), "attribute_name": "color", "sku": "SKU1"})
    assert again.status_code == 200 and again.json()["created"] is False and again.json()["agentRunId"] is None
    assert env.n("seller_fact") == 1 and env.n("agent_run") == 1
    ans = env.post("catalog-answers", {"request_key": "ca", "sku": "SKU1", "questions": ["COLOR"], "image_analysis_id": str(analysis)}).json()
    color = ans["artefacts"][0]["attributes"][0]
    assert (color["basis"], color["value"], color["claimEligible"]) == ("SELLER_PROVIDED", "matte blue", True)


def test_approval_is_zero_units_and_a_refusal_writes_nothing(env):
    seed_cap(env.engine, "cmo.approve_title", 0)
    ts = env.post("title-sets", title_body("ap")).json()["artefacts"][0]
    ok = env.post("title-approvals", {"generation_id": ts["id"], "edited_text": "AquaKeep Mug"})
    assert ok.status_code == 200 and ok.json()["editedBySeller"] is True and len(env.events()) == 1  # only the title set was billed
    runs = env.n("agent_run")
    refused = env.post("title-approvals", {"generation_id": ts["id"], "edited_text": "AquaKeep " * 30})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "TITLE_INVALID"
    assert any("TOO_LONG" in v for v in refused.json()["detail"]["violations"])
    assert env.n("cmo_title_approval") == 1 and env.n("agent_run") == runs


# ---- validation ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path,body,status,code", [
    ("title-sets", {"request_key": "bad key!", "marketplaces": [AMAZON]}, 422, "BAD_REQUEST_KEY"),
    ("title-sets", {"request_key": "k", "marketplaces": [AMAZON, AMAZON]}, 422, "DUPLICATE_ARTEFACT"),
    ("title-sets", {"request_key": "k", "marketplaces": []}, 422, None),
    ("title-sets", {"request_key": "k", "marketplaces": ["EBAY"]}, 422, None),
    ("title-sets", {"request_key": "k", "marketplaces": [AMAZON], "target_price_paise": 4.5}, 422, None),
    ("title-sets", "not an object", 422, None),
    ("listing-copy", {"request_key": "k", "marketplace": AMAZON}, 422, "GROUNDING_REQUIRED"),
    ("listing-copy", {"request_key": "k", "marketplace": AMAZON, "seller_title": "AquaKeep", "approval_id": str(uuid.uuid4())}, 422, "GROUNDING_REQUIRED"),
    ("backend-terms", {"request_key": "k", "marketplace": FLIPKART, "seller_title": "AquaKeep Bottle"}, 422, "BACKEND_TERMS_AMAZON_ONLY"),
    ("catalog-answers", {"request_key": "k", "questions": ["PRICE"]}, 422, None),
    ("title-approvals", {"generation_id": str(uuid.uuid4())}, 422, "INVALID_APPROVAL"),
    ("title-approvals", {"generation_id": "nope", "option_id": str(uuid.uuid4())}, 422, None),
    ("image-hints/confirm", {"analysis_id": str(uuid.uuid4()), "attribute_name": "color", "sku": " "}, 422, "INVALID_CONFIRMATION"),
])
def test_malformed_requests_are_422_and_persist_nothing(env, path, body, status, code):
    seed_cap(env.engine, TS_METER, 1)
    r = env.post(path, body)
    assert r.status_code == status, r.text
    if code:
        assert r.json()["detail"]["code"] == code
    assert env.provider.calls == 0 and env.n("cmo_generation") == 0 and env.n("agent_run") == 0 and env.n("seller_fact") == 0
    assert env.events() == [] and "RESERVED" not in env.reservations()  # nothing left holding quota
    assert env.post("title-sets", title_body("after")).status_code == 200  # the single unit of cap is still there


def test_unknown_ids_are_404(env):
    for path, body in (("title-approvals", {"generation_id": str(uuid.uuid4()), "option_id": str(uuid.uuid4())}),
                       ("listing-copy", {"request_key": "k", "marketplace": AMAZON, "approval_id": str(uuid.uuid4())}),
                       ("catalog-answers", {"request_key": "k", "questions": ["COLOR"], "image_analysis_id": str(uuid.uuid4())})):
        assert env.post(path, body).status_code == 404, path
    assert env.n("cmo_generation") == 0 and env.n("agent_run") == 0 and env.events() == []


# ---- no leakage, no write-back --------------------------------------------------------------------------------


def test_successful_responses_expose_only_the_allow_listed_fields(env):
    other, _ = env.other_tenant()
    r = env.post("title-sets", title_body("lk", (AMAZON, FLIPKART)))
    blob = r.text
    for banned in ("provenance", "fact_ids", "excluded_facts", "format_constraint_ref", "Reply shape", "DATA (JSON", str(other), "tenant_id", "output_structured"):
        assert banned not in blob, banned
    assert r.headers["Cache-Control"] == "no-store"
    pack = env.post("listing-copy", {"request_key": "lk2", "sku": "SKU1", "brand": "AquaKeep", "marketplace": AMAZON, "seller_title": "AquaKeep Steel Bottle"}).text
    for banned in ("provenance", "fact_ids", "grounding_title", "Reply shape", "excluded_facts"):
        assert banned not in pack, banned


def test_there_is_no_marketplace_publish_or_update_route_at_runtime(env):
    c = env.client()
    for method in ("put", "patch", "delete"):
        assert getattr(c, method)("/api/v1/cmo/title-sets", headers=env.headers).status_code == 405
    for path in ("publish", "update-listing", "marketplaces/amazon/publish", "listings", "push", "sync"):
        for method in ("post", "put"):
            assert getattr(c, method)(f"/api/v1/cmo/{path}", json={}, headers=env.headers).status_code in (404, 405)
    assert env.provider.calls == 0


# ---- R5: a CMO run is discoverable from its first model call on ------------------------------------------------------


def _running_cmo_runs(env):
    return [r[0] for r in env.q("SELECT status FROM agent_run WHERE agent_id = 'CMO'")]


def test_a_cmo_run_row_exists_and_is_running_during_the_model_call_then_completes(env):
    seen: list[list[str]] = []
    original = env.provider.complete

    def spy(*, model: str, prompt: str) -> str:
        seen.append(_running_cmo_runs(env))
        return original(model=model, prompt=prompt)

    env.provider.complete = spy  # type: ignore[method-assign]
    assert env.post("title-sets", title_body("r5-inflight")).status_code == 200
    assert seen and all(s == ["RUNNING"] for s in seen)  # mid-flight: exactly one row, RUNNING
    assert _running_cmo_runs(env) == ["COMPLETE"]  # and one terminal row afterwards (same count as before this change)


def test_a_request_rejected_before_any_model_call_leaves_no_run_row(env):
    r = env.post("listing-copy", {"request_key": "r5-rejected", "sku": "S", "brand": "B", "marketplace": AMAZON})
    assert r.status_code == 422 and env.provider.calls == 0
    assert _running_cmo_runs(env) == []  # rejected requests still persist nothing


def test_a_hard_killed_cmo_request_leaves_a_run_that_recovery_settles(env):
    import subprocess
    import sys

    from backend.ceo import recovery
    from backend.repositories import run_liveness

    child = os.path.join(os.path.dirname(__file__), "cmo_kill_child.py")
    proc = subprocess.run([sys.executable, child, str(env.tenant), str(env.user_id)], capture_output=True, text=True, env=os.environ.copy(), timeout=120)
    assert "IN_FLIGHT" in proc.stdout and proc.returncode == 137, (proc.stdout, proc.stderr[-400:])
    assert _running_cmo_runs(env) == ["RUNNING"]  # the stuck-RUNNING state: no terminal write, no cleanup
    run_id = env.q("SELECT id FROM agent_run WHERE agent_id = 'CMO'")[0][0]
    for _ in range(200):
        if not run_liveness.is_owned_elsewhere(run_id):
            break
        time.sleep(0.1)
    assert recovery.sweep_orphan_runs(tenants=[env.tenant]).orphans_settled == 1
    assert env.q("SELECT status, error_reason FROM agent_run WHERE agent_id = 'CMO'")[0][0] == "FAILED"
    assert recovery.sweep_orphan_runs(tenants=[env.tenant]).orphans_settled == 0
    assert env.n("cmo_generation") == 0 and env.events() == []  # nothing was delivered or billed
