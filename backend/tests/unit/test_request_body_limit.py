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


# ---- a limit for a route with an id in its path (the CEO attachment upload) ----------------------


def _templated(inner, limit=100):
    return RequestBodyLimitMiddleware(inner, limits={"/inv/{investigation_id}/attachments": limit}, overhead_bytes=0)


async def test_a_templated_path_limit_applies_to_any_id() -> None:
    inner = _Recorder()
    status, _, pulled = await _call(_templated(inner), chunks=[b"x" * 101], content_length=101, path="/inv/6f1c1a52-0d2f-4a9e-8d57-2f1c9c1b7a10/attachments")
    assert status == 413 and not inner.called and pulled == 0


async def test_a_templated_path_limit_lets_an_at_limit_body_through() -> None:
    inner = _Recorder()
    status, _, _ = await _call(_templated(inner), chunks=[b"x" * 100], content_length=100, path="/inv/abc/attachments")
    assert status == 200 and inner.body_bytes == 100


@pytest.mark.parametrize("path", ["/inv/a/b/attachments", "/inv//attachments", "/inv/abc/attachments/extra", "/other/abc/attachments"])
async def test_a_templated_limit_does_not_leak_onto_other_paths(path: str) -> None:
    inner = _Recorder()
    status, _, _ = await _call(_templated(inner), chunks=[b"x" * 5000], content_length=5000, path=path)
    assert status == 200 and inner.called  # not this route's limit: handled (or refused) by the route itself


def test_the_real_app_cuts_off_an_oversized_ceo_attachment_before_authentication(monkeypatch) -> None:
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_BYTES", "1000")
    client = TestClient(main_module.create_app(), raise_server_exceptions=False)
    big = {"file": ("big.pdf", b"%PDF-" + b"x" * (200 * 1024), "application/pdf")}  # far over limit + envelope overhead
    resp = client.post("/api/v1/ceo/investigations/6f1c1a52-0d2f-4a9e-8d57-2f1c9c1b7a10/attachments", files=big)  # no credentials at all
    assert resp.status_code == 413  # refused before auth and before the multipart parser spooled it


def test_the_ceo_attachment_cap_is_not_invented_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("CEO_ATTACHMENT_MAX_BYTES", raising=False)
    client = TestClient(main_module.create_app(), raise_server_exceptions=False)
    big = {"file": ("big.pdf", b"%PDF-" + b"x" * (200 * 1024), "application/pdf")}
    resp = client.post("/api/v1/ceo/investigations/6f1c1a52-0d2f-4a9e-8d57-2f1c9c1b7a10/attachments", files=big)
    assert resp.status_code == 401  # no cap configured -> no middleware entry; the normal auth answer, nothing made up


# ---- the default limit for every other (JSON) route ----------------------------------------------------------------


def _with_default(inner, default=100, upload=1000):
    return RequestBodyLimitMiddleware(inner, limits={"/upload": upload}, overhead_bytes=0, default_limit=default)


async def test_a_json_body_exactly_at_the_default_limit_is_passed_through() -> None:
    inner = _Recorder()
    status, _, _ = await _call(_with_default(inner), chunks=[b"x" * 100], content_length=100, path="/api/v1/anything")
    assert status == 200 and inner.body_bytes == 100


async def test_one_byte_over_the_default_limit_is_413_before_the_app_runs() -> None:
    inner = _Recorder()
    status, body, pulled = await _call(_with_default(inner), chunks=[b"x" * 101], content_length=101, path="/api/v1/anything")
    assert status == 413 and not inner.called and pulled == 0
    assert "limit" in json.loads(body)["detail"]


async def test_a_chunked_json_body_without_content_length_is_cut_off() -> None:
    inner = _Recorder()
    status, _, pulled = await _call(_with_default(inner), chunks=[b"x" * 40 for _ in range(50)], path="/api/v1/anything")
    assert status == 413 and pulled < 50


async def test_an_upload_route_keeps_its_own_larger_limit_under_a_small_default() -> None:
    inner = _Recorder()
    status, _, _ = await _call(_with_default(inner), chunks=[b"x" * 900], content_length=900, path="/upload")
    assert status == 200 and inner.body_bytes == 900


async def test_a_malformed_content_length_is_400_and_a_get_is_never_limited() -> None:
    inner = _Recorder()
    status, _, _ = await _call(_with_default(inner), chunks=[b""], content_length="abc", path="/api/v1/anything")  # type: ignore[arg-type]
    assert status == 400 and not inner.called
    status, _, _ = await _call(_with_default(_Recorder()), chunks=[b"x" * 5000], content_length=5000, method="GET", path="/api/v1/anything")
    assert status == 200


async def test_no_default_limit_means_no_limit_on_other_routes() -> None:
    inner = _Recorder()
    status, _, _ = await _call(RequestBodyLimitMiddleware(inner, limits={}, overhead_bytes=0), chunks=[b"x" * 5000], content_length=5000, path="/api/v1/anything")
    assert status == 200


def test_the_default_limit_configuration(monkeypatch) -> None:
    from backend import config

    monkeypatch.delenv("API_MAX_BODY_BYTES", raising=False)
    assert config.api_max_body_bytes() == 1024 * 1024
    monkeypatch.setenv("API_MAX_BODY_BYTES", "2048")
    assert config.api_max_body_bytes() == 2048
    monkeypatch.setenv("API_MAX_BODY_BYTES", "0")
    assert config.api_max_body_bytes() is None
    for bad in ("-1", "abc", "1.5"):
        monkeypatch.setenv("API_MAX_BODY_BYTES", bad)
        with pytest.raises(ValueError):
            config.api_max_body_bytes()


def test_the_real_app_refuses_an_oversized_json_body_before_authentication(monkeypatch) -> None:
    monkeypatch.setenv("API_MAX_BODY_BYTES", "2000")
    client = TestClient(main_module.create_app(), raise_server_exceptions=False)
    url = "/api/v1/ceo/investigations/6f1c1a52-0d2f-4a9e-8d57-2f1c9c1b7a10/turns"
    assert client.post(url, content=b'{"message": "' + b"x" * 5000 + b'"}', headers={"content-type": "application/json"}).status_code == 413
    assert client.post(url, json={"message": "hi"}).status_code == 401  # a normal body reaches the normal answer
    assert client.post(url, content=b'{"message": ' + b"x" * 1000, headers={"content-type": "application/json"}).status_code == 422  # malformed but under the limit: FastAPI's own answer, as before


def test_the_real_app_with_the_limit_off_does_not_cap(monkeypatch) -> None:
    monkeypatch.setenv("API_MAX_BODY_BYTES", "0")
    client = TestClient(main_module.create_app(), raise_server_exceptions=False)
    url = "/api/v1/ceo/investigations/6f1c1a52-0d2f-4a9e-8d57-2f1c9c1b7a10/turns"
    assert client.post(url, content=b"x" * 3_000_000, headers={"content-type": "application/json"}).status_code == 422  # not 413: nothing caps it


def test_the_default_applies_to_the_real_app_when_nothing_is_configured(monkeypatch) -> None:
    monkeypatch.delenv("API_MAX_BODY_BYTES", raising=False)
    client = TestClient(main_module.create_app(), raise_server_exceptions=False)
    url = "/api/v1/ceo/investigations/6f1c1a52-0d2f-4a9e-8d57-2f1c9c1b7a10/turns"
    assert client.post(url, content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/json"}).status_code == 413
    assert client.post(url, content=b"x" * 1024 * 1024, headers={"content-type": "application/json"}).status_code == 422  # exactly at the limit: passed on (then rejected as malformed)
