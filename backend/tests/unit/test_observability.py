"""Request ids and log redaction (backend/observability.py)."""

from __future__ import annotations

import logging
import os

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

import pytest
from fastapi.testclient import TestClient

from backend import observability
from backend.main import app


@pytest.mark.parametrize("raw", [
    "Authorization: Bearer abc.def.ghi-123",
    "GET https://www.googleapis.com/youtube/v3/search?q=x&key=AIzaSyTHIS_IS_A_SECRET_KEY_123",
    "failed with api_key=ABCDEF123456 for tenant",
    "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJl",
    "clerk sk_live_ABCDEFGHIJKL and whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw",
    "password: hunter2hunter2",
])
def test_secrets_are_redacted(raw):
    out = observability.redact(raw)
    for secret in ("abc.def.ghi-123", "AIzaSyTHIS_IS_A_SECRET_KEY_123", "ABCDEF123456", "eyJhbGci", "ABCDEFGHIJKL", "MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", "hunter2hunter2"):
        assert secret not in out
    assert "[redacted]" in out


def test_ordinary_text_is_left_alone():
    text = "settled an ownerless run (tenant=4c433a5d run=e4349fe5 agent=PI trigger=pi.discover)"
    assert observability.redact(text) == text


@pytest.mark.parametrize("candidate,kept", [("abcd1234-EFGH_5678", True), ("short", False), ("has space in it!!", False), ("x" * 65, False), ("evil\r\nX-Injected: 1", False), (None, False)])
def test_request_id_is_kept_only_when_plain(candidate, kept):
    out = observability.new_request_id(candidate)
    assert (out == candidate) is kept and observability._SAFE_ID.match(out)


def test_the_response_carries_a_request_id_and_echoes_a_plain_one():
    client = TestClient(app, raise_server_exceptions=False)
    assert len(client.get("/api/v1/ping").headers["x-request-id"]) >= 8
    assert client.get("/api/v1/ping", headers={"X-Request-ID": "trace-12345678"}).headers["x-request-id"] == "trace-12345678"
    bad = client.get("/api/v1/ping", headers={"X-Request-ID": "no good!"}).headers["x-request-id"]
    assert bad != "no good!" and observability._SAFE_ID.match(bad)
    assert client.get("/api/v1/session").headers["x-request-id"]  # a 401 is correlated too


def test_log_lines_carry_the_request_id_and_never_the_secret(caplog):
    observability.install_logging()
    token = observability.REQUEST_ID.set("req-abcdef12")
    try:
        with caplog.at_level(logging.WARNING):
            logging.getLogger("x").warning("upstream said %s for url %s", 403, "https://h/x?key=AIzaSyTHIS_IS_A_SECRET_KEY_123")
    finally:
        observability.REQUEST_ID.reset(token)
    rec = caplog.records[-1]
    assert "[req=req-abcdef12]" in rec.getMessage() and "AIzaSyTHIS" not in rec.getMessage() and "403" in rec.getMessage()


def test_a_formatter_that_reads_record_args_itself_still_works():  # uvicorn's access formatter unpacks record.args; nulling them broke every access-log line
    observability.install_logging()
    seen = {}

    class ArgsReader(logging.Formatter):
        def format(self, record):
            seen["args"] = record.args
            return super().format(record)

    handler = logging.StreamHandler()
    handler.setFormatter(ArgsReader("%(message)s"))
    log = logging.getLogger("access-test")
    log.addHandler(handler)
    log.propagate = False
    try:
        log.error('%s - "%s %s" %d', "127.0.0.1:1", "GET", "/x", 200)
    finally:
        log.removeHandler(handler)
    assert seen["args"] == ("127.0.0.1:1", "GET", "/x", 200)
