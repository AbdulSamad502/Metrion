"""Read-only CMO showcase API (docs/specs/ceo-cmo-delegation.md 6.8-6.10, CD6-CD8, CD14).

Every route is `require_auth(permission=AGENT_CMO)`; the tenant comes ONLY from the authenticated context (no `tenant_id` in any path, query or body). All reads are over
EXISTING saved CMO artefacts, tenant-wide (all investigations of the tenant). None generates, meters, reserves quota, calls a model or the network, or writes an
`agent_run`. The single write is the usage-event telemetry (VIEWED / COPIED / MARKED_USED); GENERATED is written by the database in the artefact's own transaction and is a 422 here.

Status mapping: 401/403 auth chain, 404 unknown or cross-tenant id (identical), 422 invalid request (including kind GENERATED), 503 CMO_NOT_CONFIGURED (page limit unset), 500 generic.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CMO
from backend.repositories import cmo_showcase_repo as repo
from backend.services import cmo_showcase_config as cfg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/cmo/showcase")

Marketplace = Literal["AMAZON", "FLIPKART", "MEESHO"]
ResultPart = Literal["TITLE", "BULLET_1", "BULLET_2", "BULLET_3", "BULLET_4", "BULLET_5", "DESCRIPTION", "BACKEND_TERMS", "FULL_PACK", "HASHTAGS"]


def _tenant(ctx: AuthContext) -> UUID:
    assert ctx.tenant_id is not None  # require_auth(permission=...) guarantees an active tenant context
    return ctx.tenant_id


def _not_configured() -> HTTPException:
    return HTTPException(status_code=503, detail={"code": "CMO_NOT_CONFIGURED", "detail": "CMO_SHOWCASE_PAGE_LIMIT is not set"})


def _page(limit: int | None, cursor: str | None) -> tuple[int, int]:
    cap = cfg.page_limit()
    if cap is None:
        raise _not_configured()
    size = cap if limit is None else max(1, min(limit, cap))
    offset = 0
    if cursor:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except Exception:
            raise HTTPException(status_code=422, detail="invalid cursor") from None
        if offset < 0:
            raise HTTPException(status_code=422, detail="invalid cursor")
    return size, offset


def _cursor(offset: int, size: int, n: int) -> str | None:
    return base64.urlsafe_b64encode(str(offset + size).encode()).decode() if n > size else None


async def _run(fn, *args, **kwargs):  # sync DB work off the event loop; internals never reach the client
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except HTTPException:
        raise
    except Exception:
        logger.exception("cmo showcase read failed")
        raise HTTPException(status_code=500, detail="Internal error") from None


@router.get("/products")
async def get_products(q: str | None = None, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    size, _ = _page(None, None)
    return {"items": await _run(repo.products, _tenant(ctx), q=q, limit=size)}


@router.get("/trends")
async def get_trends(limit: int | None = None, cursor: str | None = None, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    size, offset = _page(limit, cursor)
    rows = await _run(repo.trends, _tenant(ctx), offset=offset, limit=size + 1)
    return {"items": rows[:size], "nextCursor": _cursor(offset, size, len(rows))}


@router.get("/titles")
async def get_titles(
    marketplace: Marketplace, sku: str | None = None, q: str | None = None, view: Literal["recent", "frequent"] = "recent", approvedOnly: bool = False,
    from_: datetime | None = Query(default=None, alias="from"), to: datetime | None = None, limit: int | None = None, cursor: str | None = None,
    ctx: AuthContext = require_auth(permission=AGENT_CMO),
) -> dict[str, Any]:
    size, offset = _page(limit, cursor)
    tenant = _tenant(ctx)
    since = await _run(repo.use_events_since, tenant)
    usage: dict[str, Any] = {"available": since is not None, "basis": "RECORDED_EVENTS" if since is not None else None, "since": since.isoformat() if since else None}
    frequent = view == "frequent"
    min_count, lookback = cfg.frequent_min_count(), cfg.frequent_lookback_days()
    if frequent:
        if min_count is None or lookback is None:  # required, never defaulted: the view is unavailable until the owner sets them
            return {"items": [], "usage": {"available": False, "basis": None, "since": None, "reason": "NOT_CONFIGURED"}, "nextCursor": None}
        if since is None:
            return {"items": [], "usage": {**usage, "reason": "NO_USAGE_RECORDED"}, "nextCursor": None}
    rows = await _run(
        repo.titles, tenant, marketplace=marketplace, sku=sku, q=q, frequent=frequent, approved_only=approvedOnly, date_from=from_, date_to=to,
        lookback_days=lookback, min_count=min_count, offset=offset, limit=size + 1,
    )
    return {"items": rows[:size], "usage": usage, "nextCursor": _cursor(offset, size, len(rows))}


@router.get("/copy-packs")
async def get_copy_packs(
    marketplace: Marketplace, sku: str | None = None, q: str | None = None, limit: int | None = None, cursor: str | None = None,
    ctx: AuthContext = require_auth(permission=AGENT_CMO),
) -> dict[str, Any]:
    size, offset = _page(limit, cursor)
    rows = await _run(repo.copy_packs, _tenant(ctx), marketplace=marketplace, sku=sku, q=q, offset=offset, limit=size + 1)
    return {"items": rows[:size], "nextCursor": _cursor(offset, size, len(rows))}


@router.get("/hashtags")
async def get_hashtags(
    sku: str | None = None, q: str | None = None, limit: int | None = None, cursor: str | None = None, ctx: AuthContext = require_auth(permission=AGENT_CMO),
) -> dict[str, Any]:
    size, offset = _page(limit, cursor)
    rows = await _run(repo.hashtags, _tenant(ctx), sku=sku, q=q, offset=offset, limit=size + 1)
    return {"items": rows[:size], "nextCursor": _cursor(offset, size, len(rows))}


@router.get("/compliance")
async def get_compliance(sku: str | None = None, marketplace: Marketplace | None = None, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> dict[str, Any]:
    counts = await _run(repo.compliance, _tenant(ctx), sku=sku, marketplace=marketplace)
    return {"counts": counts}


class UsageEventBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a client-supplied tenant_id / actor / occurred_at is a 422
    generationId: UUID
    optionId: UUID | None = None
    resultPart: ResultPart | None = None
    kind: Literal["VIEWED", "COPIED", "MARKED_USED"]  # GENERATED is server-written only -> 422
    surface: Literal["DASHBOARD", "CHAT"]


@router.post("/usage-events", status_code=204)
async def post_usage_event(body: UsageEventBody, ctx: AuthContext = require_auth(permission=AGENT_CMO)) -> Response:
    try:
        window = cfg.usage_dedup_seconds()
    except ValueError:
        raise _not_configured() from None
    try:
        await run_in_threadpool(
            repo.record_usage, _tenant(ctx), ctx.app_user_id, generation_id=body.generationId, option_id=body.optionId, result_part=body.resultPart,
            kind=body.kind, surface=body.surface, dedup_seconds=window,
        )
    except repo.NotFound:
        raise HTTPException(status_code=404, detail="Not found") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("cmo usage event failed")
        raise HTTPException(status_code=500, detail="Internal error") from None
    return Response(status_code=204)
