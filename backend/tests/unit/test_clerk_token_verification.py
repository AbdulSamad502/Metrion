"""Step 1 of the auth chain against Clerk's REAL token verification (no fake Clerk client, no
network): a self-generated RSA keypair stands in for the instance's signing key, and
`require_auth()` runs the real `authenticate_request_async` with the same options production uses.

Covers the failure behind "authenticated frontend flow returns 401": a perfectly valid token
rejected only because this machine's clock disagrees with Clerk's by more than the SDK's fixed 5s
leeway — and proves the fix is a bounded, configurable leeway, not weaker verification (a wrong key
or an expired token is still rejected)."""

from __future__ import annotations

import logging
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.auth import context
from backend.auth.clock_diagnostics import clock_hint, is_time_related
from backend.config import clerk_clock_skew_ms


def _keypair() -> tuple[bytes, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


_PRIVATE, _PUBLIC = _keypair()
_OTHER_PRIVATE, _ = _keypair()


def _token(*, private: bytes = _PRIVATE, **overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": "https://example-12.clerk.accounts.dev", "sub": "user_abc", "sid": "sess_1", "azp": "http://localhost:3000",
        "iat": now, "nbf": now - 5, "exp": now + 60, "v": 2, "o": {"id": "org_1", "rol": "admin", "slg": "acme"},
    }
    claims.update(overrides)
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "ins_1"})


@pytest.fixture
def client(monkeypatch):
    """A one-route app protected by the real `require_auth()`; only the DB-backed tail
    (`resolve_auth_context`) is stubbed, so Step 1 is exercised for real."""
    seen: dict[str, object] = {}

    async def fake_resolve(*, clerk_user_id, clerk_org_id, permission):
        seen.update(user=clerk_user_id, org=clerk_org_id)
        return context.AuthContext(
            app_user_id=uuid.uuid4(), clerk_user_id=clerk_user_id, email_verified=True, tenant_id=None,
            membership_status=None, role=None, permissions={}, onboarding_state=context.ACTIVE,
        )

    monkeypatch.setattr(context, "resolve_auth_context", fake_resolve)
    monkeypatch.setattr(context, "clerk_secret_key", lambda: "sk_test_dummy")
    # Exactly how .env stores it (one line, literal \n) and how config.clerk_jwt_key() unescapes it.
    monkeypatch.setattr(context, "clerk_jwt_key", lambda: _PUBLIC.strip().replace("\n", "\\n").replace("\\n", "\n"))
    monkeypatch.setattr(context, "clerk_clock_skew_ms", lambda: 5_000)

    app = FastAPI()

    @app.get("/whoami")
    async def whoami(ctx: context.AuthContext = Depends(context.require_auth().dependency)):  # type: ignore[attr-defined]
        return {"user": ctx.clerk_user_id}

    test_client = TestClient(app)
    test_client.seen = seen  # type: ignore[attr-defined]
    return test_client


def _get(client: TestClient, token: str | None):
    return client.get("/whoami", headers={"Authorization": f"Bearer {token}"} if token else {})


def test_valid_clerk_session_token_authenticates_and_passes_user_and_org(client):
    resp = _get(client, _token())
    assert resp.status_code == 200, resp.text
    # v2 session tokens carry the active org nested under `o`; the SDK exposes it as org_id.
    assert client.seen == {"user": "user_abc", "org": "org_1"}


def test_no_token_is_401(client):
    assert _get(client, None).status_code == 401


def test_token_signed_by_another_key_is_rejected(client):
    assert _get(client, _token(private=_OTHER_PRIVATE)).status_code == 401


def test_clock_behind_by_more_than_the_leeway_is_rejected_and_explained(client, caplog):
    """The reported failure: the machine's clock is ~24s behind real time, so Clerk's brand-new token
    looks like it was issued in the future. Valid signature, valid key — rejected on time alone."""
    now = int(time.time())
    with caplog.at_level(logging.WARNING, logger="backend.auth.context"):
        resp = _get(client, _token(iat=now + 24, nbf=now + 24, exp=now + 84))
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Not authenticated"}  # the client still learns nothing
    text = caplog.text
    assert "Clerk rejected request" in text and "TOKEN_NOT_ACTIVE_YET" in text
    assert "clock is about" in text and "BEHIND real time" in text and "CLERK_CLOCK_SKEW_MS" in text
    assert "eyJ" not in text  # the token itself is never logged


def test_a_larger_configured_leeway_accepts_the_same_skewed_token(client, monkeypatch):
    now = int(time.time())
    skewed = _token(iat=now + 24, nbf=now + 24, exp=now + 84)
    assert _get(client, skewed).status_code == 401
    monkeypatch.setattr(context, "clerk_clock_skew_ms", lambda: 30_000)
    assert _get(client, skewed).status_code == 200


def test_a_larger_leeway_does_not_make_a_clearly_expired_token_valid(client, monkeypatch):
    monkeypatch.setattr(context, "clerk_clock_skew_ms", lambda: 30_000)
    now = int(time.time())
    expired = _token(iat=now - 400, nbf=now - 400, exp=now - 340)
    assert _get(client, expired).status_code == 401


# --- the clock diagnostic and the leeway config, directly ---------------------------------------


def test_clock_hint_reports_a_behind_clock_and_reads_only_timing_claims():
    now = 1_000_000.0
    token = _token(iat=int(now) + 24, nbf=int(now) + 24, exp=int(now) + 84)
    hint = clock_hint(f"Bearer {token}", leeway_ms=5_000, now=now)
    assert hint is not None and "24s" in hint and "BEHIND" in hint
    assert token not in hint


def test_clock_hint_is_silent_when_the_clock_is_fine_or_the_token_is_garbage():
    now = time.time()
    assert clock_hint(f"Bearer {_token()}", leeway_ms=5_000, now=now) is None
    assert clock_hint("Bearer not-a-jwt", leeway_ms=5_000) is None
    assert clock_hint(None, leeway_ms=5_000) is None


def test_time_related_reasons_are_recognised_by_name():
    class _Reason:
        name = "TOKEN_NOT_ACTIVE_YET"

    class _Other:
        name = "TOKEN_INVALID_SIGNATURE"

    assert is_time_related(_Reason()) and not is_time_related(_Other())


@pytest.mark.parametrize(
    ("secret", "override", "expected"),
    [
        ("sk_test_x", None, 30_000),  # development instance: tolerant by default
        ("sk_live_x", None, 5_000),  # production instance: the SDK's strict default, never relaxed implicitly
        ("sk_live_x", "20000", 20_000),  # explicit override always wins
        ("sk_test_x", "0", 0),
    ],
)
def test_clock_skew_config(monkeypatch, secret, override, expected):
    monkeypatch.setenv("CLERK_SECRET_KEY", secret)
    if override is None:
        monkeypatch.delenv("CLERK_CLOCK_SKEW_MS", raising=False)
    else:
        monkeypatch.setenv("CLERK_CLOCK_SKEW_MS", override)
    clerk_clock_skew_ms.cache_clear()
    from backend.config import clerk_secret_key

    clerk_secret_key.cache_clear()
    try:
        assert clerk_clock_skew_ms() == expected
    finally:
        clerk_clock_skew_ms.cache_clear()
        clerk_secret_key.cache_clear()


@pytest.mark.parametrize("bad", ["abc", "-1", "120001"])
def test_clock_skew_config_rejects_unbounded_or_invalid_values(monkeypatch, bad):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_live_x")
    monkeypatch.setenv("CLERK_CLOCK_SKEW_MS", bad)
    clerk_clock_skew_ms.cache_clear()
    try:
        with pytest.raises(ValueError):
            clerk_clock_skew_ms()
    finally:
        clerk_clock_skew_ms.cache_clear()


# --- the key problem: a malformed CLERK_JWT_KEY must be loud, not an anonymous 401 ---------------


def test_placeholder_or_truncated_jwt_key_is_reported():
    from backend.auth.key_diagnostics import jwt_key_problem

    placeholder = "-----BEGIN PUBLIC KEY-----\nxxx\n-----END PUBLIC KEY-----"  # the .env.example value
    assert "not a valid PEM public key" in (jwt_key_problem(placeholder) or "")
    assert jwt_key_problem(_PUBLIC) is None


def test_unparseable_key_rejects_every_token_and_the_log_says_why(client, monkeypatch, caplog):
    monkeypatch.setattr(context, "clerk_jwt_key", lambda: "-----BEGIN PUBLIC KEY-----\nxxx\n-----END PUBLIC KEY-----")
    with caplog.at_level(logging.WARNING, logger="backend.auth.context"):
        resp = _get(client, _token())
    assert resp.status_code == 401
    assert "JWK_FAILED_TO_RESOLVE" in caplog.text
    assert "CLERK_JWT_KEY is not a usable RSA public key" in caplog.text


def test_token_from_a_different_instance_logs_the_key_mismatch(client, caplog):
    with caplog.at_level(logging.WARNING, logger="backend.auth.context"):
        resp = _get(client, _token(private=_OTHER_PRIVATE))
    assert resp.status_code == 401
    assert "TOKEN_INVALID_SIGNATURE" in caplog.text and "different Clerk instance" in caplog.text
