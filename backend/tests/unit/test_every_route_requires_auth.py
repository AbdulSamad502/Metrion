"""Every `/api/v1` route refuses an unauthenticated request, except the ones named here on purpose.

One parameterised test over the app's own OpenAPI document, so a new route is covered the day it is added and a new PUBLIC route needs an explicit line in `PUBLIC`
(a reviewed decision) rather than appearing by accident. The request is sent with no Authorization header and a deliberately empty or invalid body: authentication
must be decided before the body is looked at, so the answer is 401, never 422 and never a result.

This is the shared check behind the per-path "401" column of docs/planning/api-contract-coverage.md; the 403 (a signed-in member without the agent key) and tenant-isolation
checks need a database and live in `tests/integration/test_every_route_permission.py`."""

from __future__ import annotations

import os
import re
import uuid

import pytest

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

# Routes that are deliberately reachable without a session, each with its reason.
PUBLIC: dict[str, str] = {
    "GET /api/v1/ping": "liveness probe",
    "GET /api/v1/ceo-hub/agents": "a fixed roster of agent ids and names; carries no tenant data",
}


def _routes() -> list[tuple[str, str]]:
    spec = app.openapi()
    out: list[tuple[str, str]] = []
    for path, methods in sorted(spec["paths"].items()):
        if not path.startswith("/api/v1"):
            continue
        for method in sorted(methods):
            if method in {"get", "post", "put", "patch", "delete"}:
                out.append((method.upper(), path))
    return out


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _m: str(uuid.uuid4()), path)


def test_the_public_list_names_only_routes_that_exist() -> None:
    served = {f"{m} {p}" for m, p in _routes()}
    assert set(PUBLIC) <= served, sorted(set(PUBLIC) - served)


def test_the_scan_sees_the_whole_api() -> None:
    assert len(_routes()) >= 100


@pytest.mark.parametrize("method,path", [r for r in _routes() if f"{r[0]} {r[1]}" not in PUBLIC], ids=lambda v: str(v))
def test_an_unauthenticated_request_is_refused_before_anything_else(method: str, path: str) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.request(method, _fill(path), json={} if method in {"POST", "PUT", "PATCH"} else None)
    assert resp.status_code == 401, f"{method} {path} answered {resp.status_code} to a request with no session"
    garbage = client.request(method, _fill(path), headers={"Authorization": "Bearer not-a-token"}, json={} if method in {"POST", "PUT", "PATCH"} else None)
    assert garbage.status_code == 401, f"{method} {path} answered {garbage.status_code} to a bad token"
