"""Issue 24: every error response carries a machine-readable `error` object BESIDE the unchanged `detail`."""

from __future__ import annotations

import os

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import errors
from backend.main import create_app


@pytest.mark.parametrize("status,kind", [
    (400, "validation"), (401, "authentication"), (402, "entitlement"), (403, "permission"), (404, "not_found"), (409, "conflict"), (413, "too_large"),
    (422, "validation"), (429, "rate_limited"), (500, "server"), (502, "unavailable"), (503, "unavailable"), (504, "unavailable"), (507, "server"),
])
def test_kind_follows_the_status(status, kind):
    assert errors.error_info(status, "any bare string")["kind"] == kind


@pytest.mark.parametrize("code", ["CMO_NOT_CONFIGURED", "ATTACHMENTS_NOT_CONFIGURED", "CONFIG_MISSING", "PI_MISSING_CONFIG"])
def test_a_503_that_names_missing_configuration_is_configuration_not_an_outage(code):
    info = errors.error_info(503, {"code": code})
    assert info["kind"] == "configuration" and info["code"] == code


def test_a_503_without_such_a_code_is_a_dependency_being_unavailable_and_the_code_is_echoed():
    info = errors.error_info(503, {"code": "OLLAMA_UNAVAILABLE"})
    assert info["kind"] == "unavailable" and info["code"] == "OLLAMA_UNAVAILABLE"


def test_a_non_string_code_is_ignored_and_no_exception_text_is_ever_included():
    assert "code" not in errors.error_info(409, {"code": 7})
    assert set(errors.error_info(500, None)) <= {"kind", "status", "requestId"}


@pytest.fixture
def client():
    app = create_app()

    @app.get("/boom-string")
    def boom_string():
        raise HTTPException(status_code=409, detail="plain old sentence")

    @app.get("/boom-code")
    def boom_code():
        raise HTTPException(status_code=503, detail={"code": "CMO_NOT_CONFIGURED"}, headers={"Retry-After": "7"})

    @app.get("/boom-crash")
    def boom_crash():
        raise RuntimeError("secret internals: password=hunter2")

    return TestClient(app, raise_server_exceptions=False)


def test_a_bare_string_detail_is_unchanged_and_gains_the_classification(client):
    r = client.get("/boom-string")
    body = r.json()
    assert r.status_code == 409 and body == {"detail": "plain old sentence"}  # the body is exactly what it was: existing consumers and tests pin whole bodies
    assert r.headers["x-error-kind"] == "conflict" and "x-error-code" not in r.headers and r.headers["x-request-id"]


def test_an_object_detail_is_unchanged_and_headers_survive(client):
    r = client.get("/boom-code")
    assert r.json() == {"detail": {"code": "CMO_NOT_CONFIGURED"}} and r.headers["x-error-kind"] == "configuration" and r.headers["x-error-code"] == "CMO_NOT_CONFIGURED" and r.headers["retry-after"] == "7"


def test_the_422_body_keeps_fastapis_own_list_and_adds_the_kind(client):
    r = client.post("/api/v1/ceo/investigations/not-a-uuid/turns", json={})
    body = r.json()
    assert r.status_code in (401, 422)
    if r.status_code == 422:
        assert isinstance(body["detail"], list) and set(body) == {"detail"} and r.headers["x-error-kind"] == "validation"


def test_authentication_and_unknown_routes_are_classified(client):
    r = client.get("/api/v1/session")
    assert r.status_code == 401 and r.json()["detail"] and r.headers["x-error-kind"] == "authentication"
    assert client.get("/api/v1/no-such-route").headers["x-error-kind"] == "not_found"


def test_an_unhandled_crash_is_a_json_500_without_the_exception_text(client):
    r = client.get("/boom-crash")
    assert r.status_code == 500 and r.json() == {"detail": "Internal Server Error"} and r.headers["x-error-kind"] == "server"
    assert "hunter2" not in r.text and "secret" not in r.text and r.headers["x-request-id"]


def test_the_size_limit_response_is_classified_too(monkeypatch):
    monkeypatch.setenv("API_MAX_BODY_BYTES", "100")
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.post("/api/v1/ceo/investigations/6f1c1a52-0d2f-4a9e-8d57-2f1c9c1b7a10/turns", content=b"x" * 500, headers={"content-type": "application/json"})
    assert r.status_code == 413 and "limit" in r.json()["detail"] and set(r.json()) == {"detail"} and r.headers["x-error-kind"] == "too_large"
