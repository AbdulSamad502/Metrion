"""Clerk webhook signature verification — auth.md AC16. No live DB or network needed: this
only exercises the Svix signature check itself, using a real Webhook signer/verifier pair
against a fixed secret (never a real Clerk secret)."""

from __future__ import annotations

import json
import os

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from svix.webhooks import Webhook

from backend.webhooks.clerk import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)

_SECRET = os.environ["CLERK_WEBHOOK_SECRET"]


def _signed_headers(body: bytes) -> dict[str, str]:
    wh = Webhook(_SECRET)
    msg_id = "msg_test123"
    timestamp = datetime.now(timezone.utc)
    signature = wh.sign(msg_id, timestamp, body.decode())
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature,
    }


def test_invalid_signature_is_rejected():
    body = json.dumps({"type": "user.created", "data": {"id": "user_x"}}).encode()
    resp = client.post("/webhooks/clerk", content=body, headers={"svix-id": "x", "svix-timestamp": "0", "svix-signature": "v1,bogus"})
    assert resp.status_code == 400


def test_valid_signature_with_unhandled_event_is_accepted():
    body = json.dumps({"type": "session.created", "data": {}}).encode()
    resp = client.post("/webhooks/clerk", content=body, headers=_signed_headers(body))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
