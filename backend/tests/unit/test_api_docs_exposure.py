"""The unauthenticated API documentation endpoints are off unless a deployment opts in."""

from __future__ import annotations

import os

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app

PATHS = ("/docs", "/redoc", "/openapi.json")


def test_docs_are_not_served_by_default(monkeypatch):
    monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert [client.get(p).status_code for p in PATHS] == [404, 404, 404]


@pytest.mark.parametrize("value", ["", "false", "0", "no", "maybe"])
def test_anything_but_an_explicit_yes_keeps_them_off(monkeypatch, value):
    monkeypatch.setenv("API_DOCS_ENABLED", value)
    assert TestClient(create_app(), raise_server_exceptions=False).get("/openapi.json").status_code == 404


def test_opting_in_serves_them(monkeypatch):
    monkeypatch.setenv("API_DOCS_ENABLED", "true")
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert [client.get(p).status_code for p in PATHS] == [200, 200, 200]


def test_the_schema_can_still_be_generated_in_process(monkeypatch):  # the route-auth test and the request-contract exporter use app.openapi()
    monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
    assert len(create_app().openapi()["paths"]) >= 100
