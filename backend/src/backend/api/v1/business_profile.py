"""GET / PUT /api/v1/business-profile — docs/specs/business-profile.md §6. The tenant always comes from the session, never from the request; the body model forbids extra fields."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import DASHBOARD_VIEW, TEAM_MANAGE
from backend.repositories import tenant_repo
from backend.services import business_profile as svc

router = APIRouter(prefix="/api/v1")


def _out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "businessName": row["business_name"], "description": row["description"], "categories": row["categories"], "marketplaces": list(row["marketplaces"]),
        "priceSegment": row["price_segment"], "targetCustomer": row["target_customer"], "businessStage": row["business_stage"], "state": row["state"],
        "updatedAt": row["updated_at"].isoformat(),
    }


def _suggested_name(ctx: AuthContext) -> str | None:
    try:
        return tenant_repo.get_business_name(ctx.tenant_id)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - only a convenience pre-fill
        return None


@router.get("/business-profile")
def get_business_profile(ctx: AuthContext = require_auth(permission=DASHBOARD_VIEW)) -> dict[str, Any]:
    assert ctx.tenant_id is not None
    row = svc.get(ctx.tenant_id)
    return {"profile": _out(row) if row else None, "complete": row is not None, "suggestedName": None if row else _suggested_name(ctx)}


@router.put("/business-profile")
def put_business_profile(body: svc.BusinessProfileIn, ctx: AuthContext = require_auth(permission=TEAM_MANAGE)) -> dict[str, Any]:
    assert ctx.tenant_id is not None
    try:
        row = svc.save(ctx.tenant_id, body, user_id=ctx.app_user_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Could not save the business details") from exc
    return {"profile": _out(row), "complete": True}
