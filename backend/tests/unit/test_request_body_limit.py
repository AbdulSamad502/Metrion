"""Request-level upload protection (`request_limits.RequestBodyLimitMiddleware`).

Before: the only limit was `uploads.read_upload_capped`, applied at `await file.read()` — after
Starlette had already received the whole request and spooled it to a temp file on disk. These
tests pin the new first line of defence: an oversized body is answered 413 BEFORE auth, form
parsing or spooling, including when there is no Content-Length (chunked)."""

from __future__ import annotations

import os

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

import json

import pytest
from fastapi.testclient import TestClient
from starlette import formparsers

import backend.main as main_module
from backend.request_limits import RequestBodyLimitMiddleware

_PATH = "/upload"


# ---- the middleware as a bare ASGI component ---------------------------------------------------


class _Recorder:
    """Inner app: records how much of the body it was given, replies 200."""

    def __init__(self) -> None:
        self.called = False
        self.body_bytes = 0

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                raise RuntimeError("client disconnected")  # what Starlette raises when the stream is cut
            self.body_bytes += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _call(app, *, chunks, content_length=None, method="POST", path=_PATH):
    headers = [(b"content-type", b"application/octet-stream")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {"type": "http", "method": method, "path": path, "headers": headers}
    pulled = 0
    queue = list(chunks)

    async def receive():
        nonlocal pulled
        if not queue:
            return {"type": "http.disconnect"}
        pulled += 1
        body = queue.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body, pulled


def _mw(inner, limit=100, overhead=0):
    return RequestBodyLimitMiddleware(inner, limits={_PATH: limit}, overhead_bytes=overhead)


async def test_body_exactly_at_the_limit_is_passed_through_intact() -> None:
    inner = _Recorder()
    status, _, _ = await _call(_mw(inner), chunks=[b"x" * 100], content_length=100)
    assert status == 200 and inner.body_bytes == 100


async def test_one_byte_over_with_content_length_is_413_and_the_app_never_runs() -> None:
    inner = _Recorder()
    status, body, pulled = await _call(_mw(inner), chunks=[b"x" * 101], content_length=101)
    assert status == 413 and not inner.called and pulled == 0  # body not even read
    assert "limit" in json.loads(body)["detail"]


async def test_chunked_body_without_content_length_is_cut_off_as_soon_as_it_passes_the_limit() -> None:
    inner = _Recorder()
    chunks = [b"x" * 40 for _ in range(50)]  # 2000 bytes arriving as 40-byte chunks, no Content-Length
    status, _, pulled = await _call(_mw(inner), chunks=chunks)
    assert status == 413
    assert pulled == 3  # 40, 80, 120 > 100 -> stopped there; the other 47 chunks were never pulled


async def test_chunked_body_within_the_limit_is_accepted() -> None:
    inner = _Recorder()
    status, _, _ = await _call(_mw(inner), chunks=[b"x" * 40, b"x" * 40])
    assert status == 200 and inner.body_bytes == 80


async def test_invalid_content_length_header_is_a_400_not_a_crash() -> None:
    inner = _Recorder()
    status, _, _ = await _call(_mw(inner), chunks=[b""], content_length="not-a-number")
    assert status == 400 and not inner.called


async def test_other_paths_and_methods_are_untouched() -> None:
    inner = _Recorder()
    big = [b"x" * 5000]
    assert (await _call(_mw(inner), chunks=big, content_length=5000, path="/other"))[0] == 200
    assert (await _call(_mw(_Recorder()), chunks=[b""], content_length=0, method="GET"))[0] == 200


# ---- the real app -------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main_module, "cfo_max_upload_bytes", lambda: 1000)
    monkeypatch.setattr(main_module, "ci_max_evidence_bytes", lambda: 1000)
    return TestClient(main_module.create_app())


def _forbid_form_parsing(monkeypatch):
    async def boom(self):
        raise AssertionError("an oversized upload must be rejected before multipart parsing/spooling")

    monkeypatch.setattr(formparsers.MultiPartParser, "parse", boom)


def test_oversized_evidence_upload_gets_413_before_auth_or_parsing(client, monkeypatch) -> None:
    _forbid_form_parsing(monkeypatch)
    r = client.post("/api/v1/ci/evidence", files={"file": ("big.png", b"x" * 300_000, "image/png")})
    assert r.status_code == 413  # not 401: rejected before the auth dependency even ran


def test_oversized_cfo_ingest_gets_413_before_parsing(client, monkeypatch) -> None:
    _forbid_form_parsing(monkeypatch)
    r = client.post("/api/v1/cfo/ingest?marketplace=MEESHO&adapter_id=x", files={"file": ("big.csv", b"a,b\n" * 100_000)})
    assert r.status_code == 413


def test_oversized_chunked_upload_through_the_real_app_is_413(client) -> None:
    def gen():
        for _ in range(200):
            yield b"x" * 4096  # ~800 KB, streamed with no Content-Length

    r = client.post("/api/v1/ci/evidence", content=gen(), headers={"content-type": "multipart/form-data; boundary=zz"})
    assert r.status_code == 413


def test_normal_sized_unauthenticated_upload_still_reaches_auth(client) -> None:
    r = client.post("/api/v1/ci/evidence", files={"file": ("ok.png", b"x" * 500, "image/png")})
    assert r.status_code == 401  # passed the size gate; stopped by auth as before


def test_malformed_multipart_within_the_limit_is_a_client_error_never_a_500(client) -> None:
    r = client.post("/api/v1/ci/evidence", content=b"--nope\r\ngarbage", headers={"content-type": "multipart/form-data; boundary=zz"})
    assert r.status_code < 500 and r.status_code != 413


def test_routes_not_in_the_limit_table_are_unaffected(client) -> None:
    r = client.post("/api/v1/cfo/pricing-curve", content=b"x" * 300_000)
    assert r.status_code != 413
