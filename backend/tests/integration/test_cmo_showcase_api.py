"""CHECKPOINT 4: the read API behind the read-only CMO showcase (docs/specs/ceo-cmo-delegation.md 6.9-6.10, CD14). Real FastAPI app, auth chain (Clerk faked),
real Postgres with RLS. Artefacts are produced through the existing (deprecated, internal) CMO routes with the fake model, so every row is a real saved artefact."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from backend.tenant_context import tenant_scope

from .test_cmo_api import AMAZON, _login, _make_tenant, ctx_engine, env, fake_clerk, _erase_cmo_rows, title_body  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

BASE = "/api/v1/cmo/showcase"


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setenv("CMO_SHOWCASE_PAGE_LIMIT", "50")
    monkeypatch.setenv("CMO_FREQUENT_MIN_COUNT", "2")
    monkeypatch.setenv("CMO_FREQUENT_LOOKBACK_DAYS", "30")
    monkeypatch.delenv("CMO_USAGE_EVENT_DEDUP_SECONDS", raising=False)


def get(env, path, headers=None):
    return env.client().get(f"{BASE}/{path}", headers=env.headers if headers is None else headers)


def usage(env, body, headers=None):
    return env.client().post(f"{BASE}/usage-events", json=body, headers=env.headers if headers is None else headers)


def produce(env):
    """title set -> approval -> listing copy -> hashtags, all saved artefacts of the tenant."""
    ts = env.post("title-sets", title_body("a1")).json()["artefacts"][0]
    ap = env.post("title-approvals", {"generation_id": ts["id"], "option_id": ts["options"][0]["id"]}).json()
    copy = env.post("listing-copy", {"request_key": "a2", "sku": "SKU1", "brand": "AquaKeep", "marketplace": AMAZON, "approval_id": ap["approvalId"]}).json()["artefacts"][0]
    tags = env.post("hashtags", {"request_key": "a3", "sku": "SKU1", "brand": "AquaKeep"}).json()["artefacts"][0]
    return ts, ap, copy, tags


def test_unauthenticated_and_missing_permission_are_refused(env):
    for p in ("products", "trends", f"titles?marketplace={AMAZON}", f"copy-packs?marketplace={AMAZON}", "hashtags", "compliance"):
        assert get(env, p, {}).status_code == 401
    assert usage(env, {"generationId": str(uuid.uuid4()), "kind": "VIEWED", "surface": "DASHBOARD"}, {}).status_code == 401
    no_cmo, _ = _login(env.fake_clerk, env.tenant, role="PARTNER", permissions={"catalog.view": True})
    assert get(env, f"titles?marketplace={AMAZON}", no_cmo).status_code == 403
    assert usage(env, {"generationId": str(uuid.uuid4()), "kind": "VIEWED", "surface": "DASHBOARD"}, no_cmo).status_code == 403


def test_page_limit_is_required_config_not_a_default(env, monkeypatch):
    monkeypatch.delenv("CMO_SHOWCASE_PAGE_LIMIT")
    r = get(env, f"titles?marketplace={AMAZON}")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "CMO_NOT_CONFIGURED"


def test_response_shapes_match_the_frontend_client(env):
    ts, ap, copy, tags = produce(env)
    titles = get(env, f"titles?marketplace={AMAZON}").json()
    t = titles["items"][0]
    assert {"generationId", "optionId", "rank", "titleText", "charCount", "maxChars", "constraint", "approved", "sku", "productLabel", "marketplace",
            "generatedAt", "origin", "usage"} <= set(t)
    assert t["maxChars"] == 80 and t["constraint"]["sourceUrl"] and t["origin"]["kind"] == "PRE_CHAT_WORKFLOW" and t["sku"] == "SKU1"
    approved = [x for x in titles["items"] if x["approved"]]
    assert len(approved) == 1 and approved[0]["approved"]["approvalId"] == ap["approvalId"] and approved[0]["approved"]["editedBySeller"] is False
    # GENERATED is recorded by the server in the artefact's own transaction, and is shown as its own count, never as use
    assert t["usage"]["generated"] == 1 and t["usage"]["copied"] == 0 and titles["usage"] == {"available": False, "basis": None, "since": None}

    pack = get(env, f"copy-packs?marketplace={AMAZON}").json()["items"][0]
    assert pack["generationId"] == copy["id"] and pack["groundedOn"]["approvalId"] == ap["approvalId"] and pack["groundedOn"]["basis"] == "APPROVED_TITLE"
    assert pack["bullets"] and all(b["max"] == 100 and b["chars"] == len(b["text"]) for b in pack["bullets"])
    assert pack["description"]["max"] == 500 and pack["backendTerms"] is None  # no backend-terms artefact was generated

    tag = get(env, "hashtags").json()["items"][0]
    assert tag["generationId"] == tags["id"] and tag["hashtags"] == ["#steelbottle", "#aquakeep"]
    prod = get(env, "products").json()["items"]
    assert prod[0]["sku"] == "SKU1" and prod[0]["counts"].get(AMAZON, 0) >= 1
    comp = get(env, "compliance").json()["counts"]
    assert comp and all(set(c) == {"label", "count", "basis"} for c in comp)
    assert get(env, "trends").json() == {"items": [], "nextCursor": None}  # nothing invented when no market-trend report exists


def test_tenant_isolation_reads_and_writes(env):
    ts, _, copy, tags = produce(env)
    other = env.other_tenant()
    other_id, oh = other
    for p in (f"titles?marketplace={AMAZON}", f"copy-packs?marketplace={AMAZON}", "hashtags", "products"):
        assert get(env, p, oh).json()["items"] == [], p
    assert get(env, "compliance", oh).json()["counts"] == []
    # a foreign generation / option id is the same 404 as an unknown one, and nothing is written
    for body in ({"generationId": ts["id"]}, {"generationId": str(uuid.uuid4())}, {"generationId": ts["id"], "optionId": ts["options"][0]["id"]}):
        assert usage(env, {**body, "kind": "COPIED", "surface": "DASHBOARD"}, oh).status_code == 404
    assert env.n("cmo_result_usage_event", "event_kind <> 'GENERATED'") == 0
    # an option that does not belong to the stated generation is also a 404
    assert usage(env, {"generationId": tags["id"], "optionId": ts["options"][0]["id"], "kind": "COPIED", "surface": "DASHBOARD"}).status_code == 404
    # RLS is the boundary underneath: another tenant's context sees none of this tenant's events
    assert env.n("cmo_result_usage_event", tenant=other_id) == 0


def test_usage_event_rules(env):
    ts, _, copy, tags = produce(env)
    opt = ts["options"][0]["id"]
    ok = {"generationId": ts["id"], "optionId": opt, "resultPart": "TITLE", "surface": "DASHBOARD"}
    # GENERATED is server-written only; client-supplied tenant / actor / time / unknown part or surface are all 422
    assert usage(env, {**ok, "kind": "GENERATED"}).status_code == 422
    assert usage(env, {**ok, "kind": "COPIED", "surface": "SYSTEM"}).status_code == 422
    assert usage(env, {**ok, "kind": "COPIED", "tenant_id": str(uuid.uuid4())}).status_code == 422
    assert usage(env, {**ok, "kind": "COPIED", "occurred_at": "2020-01-01T00:00:00Z"}).status_code == 422
    assert usage(env, {**ok, "kind": "COPIED", "resultPart": "NOPE"}).status_code == 422
    assert env.n("cmo_result_usage_event", "event_kind <> 'GENERATED'") == 0

    # VIEWED never feeds "frequently used": still unavailable
    assert usage(env, {**ok, "kind": "VIEWED"}).status_code == 204
    f = get(env, f"titles?marketplace={AMAZON}&view=frequent").json()
    assert f["items"] == [] and f["usage"]["available"] is False and f["usage"]["reason"] == "NO_USAGE_RECORDED"

    # COPIED + MARKED_USED rank; below the configured minimum (2) an item is not frequent
    assert usage(env, {**ok, "kind": "COPIED"}).status_code == 204
    # an identical repeat within the same second collapses (the spec's fallback when no window is configured)
    assert usage(env, {**ok, "kind": "COPIED"}).status_code == 204
    assert env.n("cmo_result_usage_event", "event_kind = 'COPIED'") == 1
    f = get(env, f"titles?marketplace={AMAZON}&view=frequent").json()
    assert f["items"] == [] and f["usage"]["available"] is True
    assert usage(env, {**ok, "kind": "MARKED_USED"}).status_code == 204
    f = get(env, f"titles?marketplace={AMAZON}&view=frequent").json()
    assert [i["optionId"] for i in f["items"]] == [opt] and f["usage"]["basis"] == "RECORDED_EVENTS"
    u = f["items"][0]["usage"]
    assert (u["copied"], u["markedUsed"], u["viewed"], u["generated"]) == (1, 1, 1, 1)  # separate labelled counts; generation / view are not use

    # missing thresholds => the frequent view is UNAVAILABLE, never defaulted
    env.monkeypatch.delenv("CMO_FREQUENT_MIN_COUNT")
    f = get(env, f"titles?marketplace={AMAZON}&view=frequent").json()
    assert f["items"] == [] and f["usage"]["available"] is False and f["usage"]["reason"] == "NOT_CONFIGURED"
    # the recent view is unaffected
    assert get(env, f"titles?marketplace={AMAZON}").json()["items"]

    # a configured dedup window collapses identical events inside it; a different part / kind is a different event
    env.monkeypatch.setenv("CMO_USAGE_EVENT_DEDUP_SECONDS", "3600")
    hashtag = {"generationId": tags["id"], "resultPart": "HASHTAGS", "surface": "DASHBOARD"}
    assert usage(env, {**hashtag, "kind": "COPIED"}).status_code == 204 and usage(env, {**hashtag, "kind": "COPIED"}).status_code == 204
    assert usage(env, {**hashtag, "kind": "MARKED_USED"}).status_code == 204
    assert env.n("cmo_result_usage_event", "generation_id = :g AND event_kind <> 'GENERATED'", g=tags["id"]) == 2


def test_events_table_is_force_rls_and_append_only_for_the_app_role(env, migrate_engine):
    ts, *_ = produce(env)
    with migrate_engine.connect() as conn:
        rls = conn.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'cmo_result_usage_event'")).one()
        quals = conn.execute(text("SELECT qual, with_check FROM pg_policies WHERE tablename = 'cmo_result_usage_event'")).all()
        assert tuple(rls) == (True, True) and quals and all("app.current_tenant_id" in q and "app.current_tenant_id" in (c or "") for q, c in quals)
        for priv in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not conn.execute(text("SELECT has_table_privilege('metrion_app', 'cmo_result_usage_event', :p)"), {"p": priv}).scalar_one(), priv
        assert conn.execute(text("SELECT has_table_privilege('metrion_app', 'cmo_result_usage_event', 'INSERT')")).scalar_one()
    for sql in ("UPDATE cmo_result_usage_event SET event_kind = 'COPIED'", "DELETE FROM cmo_result_usage_event"):
        with pytest.raises((ProgrammingError, DBAPIError)):
            with tenant_scope(env.tenant) as conn:
                conn.execute(text(sql))
    # the database refuses a forged GENERATED from a client surface and a SYSTEM surface for anything but GENERATED
    for kind, surface in (("GENERATED", "DASHBOARD"), ("COPIED", "SYSTEM")):
        with pytest.raises((ProgrammingError, DBAPIError)):
            with tenant_scope(env.tenant) as conn:
                conn.execute(text("INSERT INTO cmo_result_usage_event (tenant_id, generation_id, event_kind, actor_user_id, surface) VALUES (:t, :g, :k, :u, :s)"),
                             {"t": env.tenant, "g": ts["id"], "k": kind, "u": env.user_id, "s": surface})


def test_trends_show_stored_source_and_publication_date_only(env):
    import json

    gen, run = uuid.uuid4(), uuid.uuid4()
    finding = {"finding_id": "f1", "theme": "Steel bottles", "summary": "Coverage is rising.", "corroboration": "MODERATE",
               "sources": [{"url": "https://news.example/a", "title": "Example News", "published_at": "2026-10-01T00:00:00+00:00", "retrieved_at": "2026-10-12T00:00:00+00:00"},
                           {"url": "https://news.example/b", "title": "Undated", "published_at": None, "retrieved_at": "2026-10-12T00:00:00+00:00"}]}
    with env.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
        conn.execute(text("INSERT INTO cmo_generation (id, tenant_id, output_type, input_mode, output_structured, status, request_key, generated_by) "
                          "VALUES (:g, :t, 'TREND_REPORT', 'INDEPENDENT', '{}'::jsonb, 'COMPLETE', 'tr1', :u)"), {"g": str(gen), "t": str(env.tenant), "u": str(env.user_id)})
        conn.execute(text("INSERT INTO cmo_trend_report (tenant_id, generation_id, sections_requested, sections, interpretation, evidence, outbound_queries, config_snapshot, market_signal_run_ref) "
                          "VALUES (:t, :g, ARRAY['MARKET_NEWS'], CAST(:s AS jsonb), CAST(:i AS jsonb), '{\"sources\": []}'::jsonb, '[]'::jsonb, '{}'::jsonb, :r)"),
                     {"t": str(env.tenant), "g": str(gen), "s": json.dumps({"MARKET_NEWS": {"state": "OK", "reason": None, "findings": [finding]}}),
                      "i": json.dumps({"label": "CMO's interpretation — not a verified market fact.", "items": [{"statement": "x"}]}), "r": str(run)})
    item = get(env, "trends").json()["items"][0]
    f = item["sections"][0]["findings"][0]
    assert item["generationId"] == str(gen) and f["sourceName"] == "Example News" and f["publishedAt"] == "2026-10-01T00:00:00+00:00"
    assert f["sources"][1]["publishedAt"] is None  # a source with no stated date stays undated, never guessed
    assert item["interpretationLabel"].endswith("not a verified market fact.")
    assert get(env, "trends", env.other_tenant()[1]).json()["items"] == []
