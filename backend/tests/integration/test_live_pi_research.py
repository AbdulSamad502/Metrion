"""LIVE end-to-end CEO -> PI -> CEO research run against the REAL providers (docs/specs/ceo-pi-research-flow.md section 10). Opt-in: skipped unless LIVE_PI=1.

Real: Tavily (web + image search), YouTube Data API, Google Places, the image hosts, local Ollama (product-name extraction, commentary classification, embeddings), the real CEO
registry and handlers, the real approval plan, PI's case assembly, the real saved report. Faked: ONLY the Clerk login (as in every API test) and the two CEO model handles
(the request is routed by explicit rules and an approved plan runs without any model call).

Runs on the isolated scratch Postgres only (the conftest refuses the development database). API keys are read from `backend/.env` into this process only; they are never printed or
written. A run makes real, billable-to-you calls: one research run (a few Tavily searches, a few YouTube searches and comment reads, up to 5 Places lookups and 10 supplier searches,
up to 10 image searches, local model calls). The outcome report is written to the path in LIVE_PI_REPORT (default: live_pi_report.json beside this file's scratch dir)."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.api.v1 import ceo as ceo_api
from backend.auth.permissions import OWNER_ROLE
from backend.ceo.runtime import CeoRuntime
from backend.repositories import accounting_cutover_repo
from backend.services import pi_actions
from tests.integration.test_ceo_api import clerk, login  # noqa: F401  (fixture + helper)
from tests.integration.test_ceo_approval_workflow import Clock, start, turn
from tests.integration.test_ceo_turn import Grounded, Scripted, decision

pytestmark = pytest.mark.skipif(os.environ.get("LIVE_PI") != "1", reason="live run: set LIVE_PI=1 (makes real provider calls)")

_ENV_WHITELIST = ("TAVILY_API_KEY", "YOUTUBE_API_KEY", "GOOGLE_PLACES_API_KEY", "LLM_OPERATOR_CONTROLLED_HOSTS", "OLLAMA_HOST", "PI_TEXT_INSIGHT_MODEL", "PI_PRODUCT_EXTRACTION_MODEL", "PI_EMBEDDING_MODEL")
ASK = "Find me trending products under ₹20,000 on Amazon"
NICHE = os.environ.get("LIVE_PI_NICHE", "wireless earbuds")
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


def _load_keys() -> list[str]:
    """Reads ONLY the whitelisted names from backend/.env (never the database settings) and reports which are present, by name."""
    present: list[str] = []
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() in _ENV_WHITELIST and v.strip():
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    for name in _ENV_WHITELIST[:3]:
        if os.environ.get(name):
            present.append(name)
    return present


@pytest.fixture
def live(clerk, two_tenants, migrate_engine, monkeypatch):  # noqa: F811
    from backend.main import app

    present = _load_keys()
    missing = [n for n in _ENV_WHITELIST[:3] if n not in present]
    assert not missing, f"missing provider keys in backend/.env: {missing}"
    for fn in (config.tavily_api_key, config.youtube_api_key, config.google_places_api_key, config.ollama_host):
        fn.cache_clear()
    import urllib.request

    try:
        urllib.request.urlopen(os.environ.get("OLLAMA_HOST", "http://localhost:11434") + "/api/tags", timeout=5).read()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Ollama is not reachable: {exc}")
    a, _ = two_tenants
    monkeypatch.setenv("CEO_APPROVAL_ENABLED", "true")
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: NOW - timedelta(days=1))
    cls = Scripted({"yes": decision()})
    rt = CeoRuntime(classifier=cls.model(), composer=Grounded().model(), leg_timeout_seconds=int(os.environ.get("LIVE_PI_LEG_TIMEOUT", "1800")), max_legs=5, clock=Clock())
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    try:
        yield TestClient(app), a, login(clerk, a, role=OWNER_ROLE)
    finally:
        app.dependency_overrides.pop(ceo_api.get_runtime, None)
        for fn in (config.tavily_api_key, config.youtube_api_key, config.google_places_api_key, config.ollama_host):
            fn.cache_clear()


class _E:  # the tiny surface `turn`/`start` need
    def __init__(self, client):
        self.client = client


def test_live_ceo_pi_research_end_to_end(live):
    client, tenant, owner = live
    e = _E(client)
    report: dict = {"niche": NICHE, "ask": ASK, "steps": []}
    t0 = time.monotonic()
    inv = start(e, owner)
    r = turn(e, owner, inv, ASK)
    answers = {"category": NICHE, "price_range": "1000 to 3000", "confirm": "yes", "budget": "20000", "marketplaces": "Amazon"}
    asked = []
    for _ in range(8):
        if r["status"] == "PLANNED":
            break
        assert r["status"] == "CLARIFIED", r
        asked.append(r["clarifyFor"])
        r = turn(e, owner, inv, answers[r["clarifyFor"]])
    assert r["status"] == "PLANNED", r
    plan = r["plan"]
    report["questions_asked"] = asked
    report["plan_summary"] = plan["plan"]["summary_text"]
    report["plan_compact_lines"] = plan["plan"]["compact_lines"]

    t1 = time.monotonic()
    resp = client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/approve", json={"plan_hash": plan["planHash"]}, headers=owner)
    report["approve_seconds"] = round(time.monotonic() - t1, 1)
    report["approve_http"] = resp.status_code
    body = resp.json()
    report["turn_status"] = body.get("status")
    report["answer"] = body.get("answer")
    report["findings"] = [{"action": f.get("action_key"), "status": f.get("status"), "headline": (f.get("presentation") or {}).get("headline")} for f in body.get("findings", [])]

    runs = pi_actions.list_research_history(tenant)
    report["history"] = runs
    if runs:
        run_id = uuid.UUID(runs[0]["runId"])
        case = pi_actions.load_research_case(tenant, run_id)
        from backend.tenant_context import tenant_scope
        from sqlalchemy import text

        with tenant_scope(tenant) as conn:
            total = conn.execute(text("SELECT count(*) FROM product_candidate WHERE run_id = :r"), {"r": str(run_id)}).scalar()
            with_img = conn.execute(text("SELECT count(*) FROM product_candidate WHERE run_id = :r AND image_url IS NOT NULL"), {"r": str(run_id)}).scalar()
            statuses = conn.execute(text("SELECT status, depth, candidate_cap FROM pi_research_run WHERE id = :r"), {"r": str(run_id)}).one()
            insight = conn.execute(text("SELECT count(DISTINCT candidate_id) FROM product_review_insight WHERE tenant_id = :t AND candidate_id IN (SELECT id FROM product_candidate WHERE run_id = :r)"), {"t": str(tenant), "r": str(run_id)}).scalar()
            leads = conn.execute(text("SELECT source, count(*) FROM supplier_lead WHERE run_id = :r GROUP BY source"), {"r": str(run_id)}).all()
        report["run"] = {"status": statuses[0], "depth": statuses[1], "cap": statuses[2], "candidates_discovered": total, "candidates_with_image_persisted": with_img,
                         "candidates_with_commentary": insight, "supplier_leads_by_source": {s: n for s, n in leads}}
        report["case"] = case
    # Part 2 (priority 2): the seller takes up the optional quote offer for #1 through chat; the REAL CFO engine runs; the CEO attaches its results to the saved case.
    if runs and os.environ.get("LIVE_PI_CFO", "1") == "1":
        t2 = time.monotonic()
        steps = []
        q = turn(e, owner, inv, "is #1 worth stocking?")
        steps.append({"say": "is #1 worth stocking?", "ceo": q["answer"], "status": q["status"]})
        replies = {"quantity": "100", "supplier_name": "Test Supplier (live-test input)", "unit_cost": "185", "order_shipping": "skip", "budget": "20000", "confirm": "yes"}
        for _ in range(10):
            if q["status"] != "CLARIFIED":
                break
            slot = q["clarifyFor"]
            if slot == "window":
                opt = next(o for o in q["choices"]["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE"))
                q = turn(e, owner, inv, "(chose an option)", clarification={"id": q["clarificationId"], "option": opt["key"]})
                steps.append({"say": f"(option: {opt['label']})", "ceo": q["answer"], "status": q["status"]})
            else:
                q = turn(e, owner, inv, replies[slot])
                steps.append({"say": replies[slot], "ceo": q["answer"], "status": q["status"]})
        report["cfo_followup"] = steps
        report["cfo_followup_seconds"] = round(time.monotonic() - t2, 1)
        report["case_after_cfo"] = pi_actions.load_research_case(tenant, uuid.UUID(runs[0]["runId"]))
    report["total_seconds"] = round(time.monotonic() - t0, 1)

    out = Path(os.environ.get("LIVE_PI_REPORT") or Path(__file__).resolve().parent / "live_pi_report.json")
    out.write_text(json.dumps(report, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    assert resp.status_code == 200, resp.text
