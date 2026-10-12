"""Operations endpoints: liveness, readiness and recovery diagnostics for the operator / an orchestrator's probes.

NOT tenant routes and NOT for sellers. They are protected by a shared secret (`OPS_TOKEN`, sent as `X-Ops-Token`, compared in constant time) and are OFF when it is unset: every
call then answers 401 exactly like any unauthenticated request, so their existence is not revealed. Responses carry counts and statuses only: no tenant id, no run id, no seller text,
no configuration value, no exception text.

  GET /api/v1/ops/live   process is up and serving (no database access)
  GET /api/v1/ops/ready  the database answers a trivial query within a bounded probe time (200 ok / 503 unavailable)
  GET /api/v1/ops/runs   runs RUNNING now (live owner vs ownerless), oldest age, this process's last recovery sweep

The readiness check uses its OWN single-connection engine, so a probe never waits behind the application's pool and a saturated pool does not make the process look dead."""

from __future__ import annotations

import hmac
import logging
import os
from functools import lru_cache

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, create_engine, text

from backend import config
from backend.ceo import recovery

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ops")

PROBE_SECONDS = 5  # the most a readiness probe waits for the database: a probe-specific bound, independent of the application's own connect timeout


def _require_token(supplied: str | None) -> None:
    expected = config.ops_token()
    if expected is None or supplied is None or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Not authenticated")


@lru_cache
def _probe_engine() -> Engine:
    return create_engine(
        os.environ["DATABASE_URL_APP"], pool_size=1, max_overflow=0, pool_timeout=PROBE_SECONDS, pool_pre_ping=True, connect_args={"connect_timeout": PROBE_SECONDS}
    )


@router.get("/live")
def live(x_ops_token: str | None = Header(default=None)) -> dict[str, str]:
    _require_token(x_ops_token)
    return {"status": "ok"}


@router.get("/ready")
def ready(x_ops_token: str | None = Header(default=None)) -> JSONResponse:
    _require_token(x_ops_token)
    try:
        with _probe_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — any failure means "not ready"; the reason is logged, never returned
        logger.warning("readiness probe: the database did not answer")
        return JSONResponse({"status": "unavailable", "database": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok", "database": "ok"})


@router.get("/runs")
def runs(x_ops_token: str | None = Header(default=None)) -> dict[str, object]:
    _require_token(x_ops_token)
    return recovery.diagnose()
