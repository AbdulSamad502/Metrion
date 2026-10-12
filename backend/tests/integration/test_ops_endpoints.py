"""Operations endpoints (`/api/v1/ops/*`): off unless OPS_TOKEN is set, constant-time token check, counts only, bounded readiness, and diagnostics that really see a stuck run."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.api.v1 import ops
from backend.ceo import recovery
from backend.main import create_app
from backend.repositories import run_liveness

pytestmark = pytest.mark.usefixtures("two_tenants")
TOKEN = "t" * 12 + "o" * 12 + "k" * 8
H = {"X-Ops-Token": TOKEN}
CHILD = os.path.join(os.path.dirname(__file__), "run_liveness_child.py")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    ops._probe_engine.cache_clear()
    yield TestClient(create_app(), raise_server_exceptions=False)
    ops._probe_engine.cache_clear()


@pytest.mark.parametrize("path", ["live", "ready", "runs"])
def test_the_endpoints_are_off_when_no_token_is_configured(monkeypatch, path):
    monkeypatch.delenv("OPS_TOKEN", raising=False)
    r = TestClient(create_app(), raise_server_exceptions=False).get(f"/api/v1/ops/{path}", headers=H)
    assert r.status_code == 401 and r.json()["detail"] == "Not authenticated"  # indistinguishable from any unauthenticated call


@pytest.mark.parametrize("path", ["live", "ready", "runs"])
@pytest.mark.parametrize("headers", [{}, {"X-Ops-Token": "wrong"}, {"X-Ops-Token": TOKEN[:-1]}, {"X-Ops-Token": TOKEN + "x"}, {"Authorization": f"Bearer {TOKEN}"}])
def test_a_missing_or_wrong_token_is_401(client, path, headers):
    assert client.get(f"/api/v1/ops/{path}", headers=headers).status_code == 401


def test_a_too_short_token_is_a_start_up_error_not_a_weak_secret(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "short")
    with pytest.raises(config.InvalidConfig):
        config.ops_token()


def test_live_and_ready(client):
    assert client.get("/api/v1/ops/live", headers=H).json() == {"status": "ok"}
    r = client.get("/api/v1/ops/ready", headers=H)
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok"}


def test_ready_is_503_and_prompt_when_the_database_is_unreachable(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL_APP", "postgresql+psycopg://metrion_app:x@127.0.0.1:9/metrion")  # nothing listens there
    ops._probe_engine.cache_clear()
    started = time.monotonic()
    r = client.get("/api/v1/ops/ready", headers=H)
    assert r.status_code == 503 and r.json() == {"status": "unavailable", "database": "unavailable"}
    assert time.monotonic() - started < ops.PROBE_SECONDS + 3  # bounded
    assert "127.0.0.1" not in r.text and "psycopg" not in r.text  # no infrastructure detail in the answer


def test_runs_counts_a_live_owner_then_an_ownerless_run_then_nothing(client, two_tenants, app_user):
    a, _ = two_tenants
    baseline = client.get("/api/v1/ops/runs", headers=H).json()["running"]["total"]
    proc = subprocess.Popen([sys.executable, CHILD, str(a), str(app_user)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy())
    line = proc.stdout.readline()
    assert line.startswith("RUN ")
    run = uuid.UUID(line.split()[1])
    try:
        live = client.get("/api/v1/ops/runs", headers=H).json()
        assert live["running"]["total"] == baseline + 1 and live["running"]["byKind"]["PI"] >= 1
        assert live["oldestRunningSeconds"] is not None
    finally:
        proc.kill()
        proc.wait(timeout=30)
    for _ in range(200):
        if not run_liveness.is_owned_elsewhere(run):
            break
        time.sleep(0.1)
    stuck = client.get("/api/v1/ops/runs", headers=H).json()
    assert stuck["running"]["ownerless"] >= 1  # visible: RUNNING with nobody working on it
    recovery.sweep_all(tenants=[a])
    after = client.get("/api/v1/ops/runs", headers=H).json()
    assert after["running"]["total"] == baseline and after["lastSweep"]["ownerlessRunsSettled"] >= 1


def test_the_diagnostics_contain_no_identifiers_or_text(client, two_tenants, app_user):
    a, _ = two_tenants
    body = client.get("/api/v1/ops/runs", headers=H).text
    assert str(a) not in body and str(app_user) not in body
    assert set(client.get("/api/v1/ops/runs", headers=H).json()) == {"running", "oldestRunningSeconds", "piResearchRunsActive", "thisProcess", "lastSweep"}
