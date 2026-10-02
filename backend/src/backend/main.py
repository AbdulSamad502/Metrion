"""FastAPI app factory. Run locally with:

    uvicorn backend.main:app --reload --app-dir src
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1 import ceo_hub, cfo, ci, onboarding, pi, ping, session
from backend.config import (
    ci_max_evidence_bytes,
    cfo_max_upload_bytes,
    clerk_jwt_key,
    clerk_secret_key,
    clerk_webhook_secret,
    frontend_origin,
)
from backend.auth.key_diagnostics import jwt_key_problem
from backend.request_limits import RequestBodyLimitMiddleware
from backend.webhooks import clerk as clerk_webhooks

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    # Fail at startup, not on the first request that happens to need a secret — a
    # misconfigured deployment should never serve traffic unauthenticated.
    clerk_secret_key()
    clerk_webhook_secret()
    clerk_jwt_key()
    # A malformed key does not stop startup (tests and key-less local runs rely on that) but every
    # authenticated request would then be rejected with an indistinguishable 401 — say so, loudly, now.
    key_problem = jwt_key_problem(clerk_jwt_key())
    if key_problem:
        logger.error("Clerk authentication will reject EVERY authenticated request: %s", key_problem)

    app = FastAPI(title="Metrion API")

    # Registered FIRST so it is the innermost middleware: CORS and the security headers below still
    # wrap its 413 (a browser can read the error). Rejects an oversized upload before Starlette
    # parses/spools it — see request_limits.py; the routes' own exact-size check stays authoritative.
    app.add_middleware(
        RequestBodyLimitMiddleware,
        limits={
            "/api/v1/cfo/ingest": cfo_max_upload_bytes(),
            "/api/v1/ci/evidence": ci_max_evidence_bytes(),
        },
    )

    # Named explicitly rather than "*" — this is the auth-adjacent boundary of the app;
    # a wildcard here would let any origin ride the browser's credentialed CORS preflight.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "svix-id", "svix-timestamp", "svix-signature"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        # Defence-in-depth for the auth entry point: no sniffing/framing/leaking, even
        # though the API itself never renders HTML an attacker could exploit directly.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(session.router)
    app.include_router(onboarding.router)
    app.include_router(ping.router)
    app.include_router(clerk_webhooks.router)
    app.include_router(ci.router)
    app.include_router(cfo.router)
    app.include_router(pi.router)
    app.include_router(ceo_hub.router)

    return app


app = create_app()
