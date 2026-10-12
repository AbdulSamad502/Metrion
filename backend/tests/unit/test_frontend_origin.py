"""FRONTEND_ORIGIN: explicit in a deployment, validated everywhere, still convenient in local development."""

from __future__ import annotations

import os

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

import pytest
from fastapi.testclient import TestClient

from backend import config


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for name in ("FRONTEND_ORIGIN", "METRION_ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_dummy")
    config.frontend_origin.cache_clear()
    yield
    config.frontend_origin.cache_clear()


def test_local_development_keeps_its_default(monkeypatch):
    assert config.frontend_origin() == "http://localhost:3000"


def test_a_valid_origin_is_normalised(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://App.Example.com")
    assert config.frontend_origin() == "https://app.example.com"
    config.frontend_origin.cache_clear()
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173")
    assert config.frontend_origin() == "http://127.0.0.1:5173"


@pytest.mark.parametrize("bad", ["*", "https://*.example.com", "app.example.com", "ftp://app.example.com", "https://app.example.com/", "https://app.example.com/app",
                                 "https://app.example.com?x=1", "https://user:pw@app.example.com", "https://", "http://host:99999", "http://host:abc"])
def test_an_invalid_origin_is_refused_even_in_development(monkeypatch, bad):
    monkeypatch.setenv("FRONTEND_ORIGIN", bad)
    with pytest.raises(config.InvalidConfig):
        config.frontend_origin()


@pytest.mark.parametrize("env", [{"METRION_ENV": "production"}, {"METRION_ENV": "staging"}, {"CLERK_SECRET_KEY": "sk_live_realkey"}])
def test_a_deployment_must_set_it_explicitly(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert config.deployment_like() is True
    with pytest.raises(config.MissingConfig):
        config.frontend_origin()


@pytest.mark.parametrize("env", [{"METRION_ENV": "production"}, {"CLERK_SECRET_KEY": "sk_live_realkey"}])
def test_a_deployment_requires_https_except_for_loopback(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://app.example.com")
    with pytest.raises(config.InvalidConfig):
        config.frontend_origin()
    config.frontend_origin.cache_clear()
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example.com")
    assert config.frontend_origin() == "https://app.example.com"
    config.frontend_origin.cache_clear()
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000")  # a rehearsal on one machine
    assert config.frontend_origin() == "http://localhost:3000"


def test_the_app_refuses_to_start_in_a_deployment_without_the_origin_and_cors_uses_the_configured_one(monkeypatch):
    from backend.main import create_app

    monkeypatch.setenv("METRION_ENV", "production")
    config.frontend_origin.cache_clear()  # importing backend.main built the module-level app once with the development default
    with pytest.raises(config.MissingConfig):
        create_app()
    config.frontend_origin.cache_clear()
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example.com")
    client = TestClient(create_app(), raise_server_exceptions=False)
    ok = client.options("/api/v1/session", headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "GET"})
    other = client.options("/api/v1/session", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://app.example.com"
    assert other.headers.get("access-control-allow-origin") is None


def test_the_example_file_documents_it():
    text = open(os.path.join(os.path.dirname(__file__), "..", "..", ".env.example"), encoding="utf-8").read()
    assert "FRONTEND_ORIGIN" in text and "METRION_ENV" in text
