"""FastAPI app factory. Run locally with:

    uvicorn backend.main:app --reload --app-dir src
"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1 import business_profile, ceo, ceo_hub, cfo, ci, cmo, cmo_showcase, onboarding, ops, pi, ping, session
from backend.config import (
    api_max_body_bytes,
    api_docs_enabled,
    ceo_attachment_max_bytes,
    ci_max_evidence_bytes,
    cmo_image_max_bytes,
    cfo_max_upload_bytes,
    clerk_jwt_key,
    clerk_secret_key,
    clerk_webhook_secret,
    frontend_origin,
)
from backend.auth.key_diagnostics import jwt_key_problem
from backend import errors
from backend.observability import RequestIdMiddleware, install_logging
from backend.repositories import run_liveness
from backend.request_limits import RequestBodyLimitMiddleware
from backend.webhooks import clerk as clerk_webhooks

logger = logging.getLogger(__name__)


def _settle_abandoned_ceo_turns() -> None:
    """Start-up sweep (ownership-based, no age threshold): settles CEO turns whose process died. Best effort, off the request path; every worker may run it."""
    try:
        from backend.ceo import recovery

        report = recovery.sweep_all()
        if report.turns_settled or report.orphans_settled or report.pi_runs_settled or report.package_runs_settled:
            logger.warning(
                "start-up recovery settled %d abandoned CEO turn(s), %d leg(s), %d ownerless run(s), %d PI research run(s), %d reconciliation/capture run(s)",
                report.turns_settled, report.legs_settled, report.orphans_settled, report.pi_runs_settled, report.package_runs_settled,
            )
    except Exception:  # noqa: BLE001
        logger.exception("start-up recovery of abandoned CEO turns failed")
    _settle_overdue_ceo_legs_forever()


def _settle_overdue_ceo_legs_forever(stop: threading.Event | None = None) -> None:
    """With a hard leg deadline configured (`CEO_LEG_ABANDON_SECONDS`), repeats the settle pass once per deadline so a leg that hangs in a live process is settled even when its
    investigation is idle. Not configured: returns at once (nothing runs, nothing changes). The period is the deadline itself, so no second number is invented."""
    from backend.ceo import deadlines, recovery

    stop = stop or threading.Event()
    while not stop.is_set():
        seconds = deadlines.effective_abandon_seconds()
        if seconds is None:
            return
        if stop.wait(seconds):
            return
        try:
            report = recovery.sweep_all()
            if report.legs_timed_out or report.turns_settled:
                logger.warning("periodic recovery settled %d abandoned turn(s) and %d overdue leg(s)", report.turns_settled, report.legs_timed_out)
        except Exception:  # noqa: BLE001
            logger.exception("periodic settling of overdue CEO legs failed")


def _sweep_ownerless_runs_forever(stop: threading.Event | None = None) -> None:
    """Periodic ownership-based pass (R5): a worker that dies while other workers live is noticed within one interval instead of at the next start-up. Safe to run from every
    worker (guarded writes; a live owner is never touched). Interval: `config.recovery_sweep_interval_seconds()`; off when 0."""
    from backend import config
    from backend.ceo import recovery

    stop = stop or threading.Event()
    try:
        interval = config.recovery_sweep_interval_seconds()
    except ValueError:
        logger.error("RECOVERY_SWEEP_INTERVAL_SECONDS is invalid; the periodic recovery pass is off")
        return
    while interval is not None and not stop.wait(interval):
        try:
            report = recovery.sweep_all()
            if report.turns_settled or report.orphans_settled or report.pi_runs_settled or report.package_runs_settled:
                logger.warning(
                    "periodic recovery settled %d turn(s), %d ownerless run(s), %d PI research run(s), %d reconciliation/capture run(s)",
                    report.turns_settled, report.orphans_settled, report.pi_runs_settled, report.package_runs_settled,
                )
        except Exception:  # noqa: BLE001
            logger.exception("periodic recovery pass failed")


def _ci_housekeeping_forever(stop: threading.Event | None = None) -> None:
    """Competitor Intelligence's periodic housekeeping (spec 6.25, D16): per tenant, expire unanswered confirmation questions, release quiet-hours alerts (re-checking freshness)
    and add freshness reminders. It reads and writes only CI's own tables and makes no outbound request. A Postgres advisory lock lets exactly one worker run a cycle."""
    from backend import config
    from backend.repositories import ceo_runtime_repo
    from competitor_intelligence.scheduler.cycle import run_tenant_cycle

    stop = stop or threading.Event()
    try:
        interval = config.ci_scheduler_interval_seconds()
    except ValueError:
        logger.error("CI_SCHEDULER_INTERVAL_SECONDS is invalid; the CI housekeeping pass is off")
        return
    while interval is not None and not stop.wait(interval):
        lock = ceo_runtime_repo.AdvisoryLock("ci-housekeeping")
        try:
            if not lock.try_acquire():
                continue
            for tenant_id in ceo_runtime_repo.list_tenant_ids():
                try:
                    counts = run_tenant_cycle(tenant_id)
                    if any(counts.values()):
                        logger.info("CI housekeeping for one tenant: %s", counts)
                except Exception:  # noqa: BLE001 - one tenant's failure never stops the others
                    logger.exception("CI housekeeping failed for a tenant")
        except Exception:  # noqa: BLE001
            logger.exception("CI housekeeping pass failed")
        finally:
            lock.release()
            lock.close()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    threading.Thread(target=_settle_abandoned_ceo_turns, name="ceo-recovery", daemon=True).start()
    threading.Thread(target=_sweep_ownerless_runs_forever, name="run-recovery", daemon=True).start()
    threading.Thread(target=_ci_housekeeping_forever, name="ci-housekeeping", daemon=True).start()
    yield


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

    docs = api_docs_enabled()
    app = FastAPI(
        title="Metrion API", lifespan=_lifespan,
        docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None, openapi_url="/openapi.json" if docs else None,  # unauthenticated and lists every route: opt-in only
    )

    # Registered FIRST so it is the innermost middleware: CORS and the security headers below still
    # wrap its 413 (a browser can read the error). Rejects an oversized upload before Starlette
    # parses/spools it — see request_limits.py; the routes' own exact-size check stays authoritative.
    upload_limits = {
        "/api/v1/cfo/ingest": cfo_max_upload_bytes(),
        "/api/v1/ci/evidence": ci_max_evidence_bytes(),
    }
    image_limit = cmo_image_max_bytes()  # no default (P6): unset -> no entry here, and the route itself refuses with 503
    if image_limit is not None:
        upload_limits["/api/v1/cmo/images"] = image_limit
    attachment_limit = ceo_attachment_max_bytes()  # no default: unset -> no entry, and the route itself refuses with 503
    if attachment_limit is not None:
        upload_limits["/api/v1/ceo/investigations/{investigation_id}/attachments"] = attachment_limit
    app.add_middleware(RequestBodyLimitMiddleware, limits=upload_limits, default_limit=api_max_body_bytes())

    # Named explicitly rather than "*" — this is the auth-adjacent boundary of the app;
    # a wildcard here would let any origin ride the browser's credentialed CORS preflight.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "svix-id", "svix-timestamp", "svix-signature"],
        expose_headers=["X-Request-ID"],
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

    errors.install(app)  # adds an `error` object beside the unchanged `detail` of every error response
    run_liveness.install_package_ownership()  # reconciliation_run / ci_capture_run get the same ownership as agent_run
    app.add_middleware(RequestIdMiddleware)  # outermost: every response, including CORS preflights and 413s, carries X-Request-ID
    install_logging()

    app.include_router(session.router)
    app.include_router(business_profile.router)
    app.include_router(onboarding.router)
    app.include_router(ping.router)
    app.include_router(ops.router)
    app.include_router(clerk_webhooks.router)
    app.include_router(ci.router)
    app.include_router(cfo.router)
    app.include_router(pi.router)
    app.include_router(cmo.router)
    app.include_router(cmo_showcase.router)
    app.include_router(ceo_hub.router)
    app.include_router(ceo.router)

    return app


app = create_app()
